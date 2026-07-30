"""Парсер входящих писем Gmail через IMAP.

Настройка (5 минут):
1. Включи 2-Step Verification в Google-аккаунте
2. Создай App Password: https://myaccount.google.com/apppasswords
3. Впиши в .env:
     GMAIL_USER=your.email@gmail.com
     GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx

Отлавливает вакансии из писем HH.ru, Habr Career, Djinni, LinkedIn.
"""
import asyncio
import email
import email.message
import imaplib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.header import decode_header

from bs4 import BeautifulSoup

from config import GMAIL_USER, GMAIL_APP_PASSWORD, GMAIL_LOOKBACK_DAYS
from parsers.filter import is_relevant

logger = logging.getLogger(__name__)


@dataclass
class Vacancy:
    id: str
    title: str
    company: str
    url: str
    salary: str
    description: str
    source: str = "gmail"


# Отправители, чьи Job Alerts парсим из Gmail.
# key: substring в From, value: (display_name, url_regex).
# Чтобы включить LinkedIn/Indeed — подпишись на их Job Alerts (Weekly/Daily)
# по запросу "Flutter" (+ Serbia / remote), письма приходят автоматически.
SENDERS = {
    # HH.ru и Habr Career намеренно НЕ включены — они парсятся напрямую
    # через RSS/HTML (parsers/hh.py, parsers/habr.py). Их email-подборки
    # содержат «вакансии по подписке» — 20 нерелевантных позиций одной
    # компании ради одного совпадения по ключевому слову.
    "djinni.co": ("Djinni", r"https?://[^\s\"<>]*djinni\.co/jobs/\d+"),
    "linkedin.com": ("LinkedIn",
                     r"https?://[^\s\"<>]*linkedin\.com/(?:jobs/view|comm/jobs|jobs/collections)/[^\s\"<>]+"),
    "indeed.com": ("Indeed",
                   r"https?://[^\s\"<>]*indeed\.com/(?:rc/clk|viewjob|jobs)[^\s\"<>]*jk=[a-zA-Z0-9]+"),
    "getmatch.ru": ("getmatch", r"https?://[^\s\"<>]*getmatch\.ru/vacancies/\d+"),
    "geekjob.ru": ("GeekJob", r"https?://[^\s\"<>]*geekjob\.ru/vacancy/[a-z0-9]+"),
}

def is_enabled() -> bool:
    return bool(GMAIL_USER and GMAIL_APP_PASSWORD)


async def fetch_vacancies() -> list[Vacancy]:
    if not is_enabled():
        return []
    return await asyncio.to_thread(_fetch_sync)


def _fetch_sync() -> list[Vacancy]:
    result: list[Vacancy] = []
    seen_urls: set[str] = set()

    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        imap.login(GMAIL_USER, GMAIL_APP_PASSWORD)
    except Exception as e:
        logger.error("Gmail IMAP login failed: %s", e)
        return []

    try:
        imap.select("INBOX", readonly=True)
        since = (datetime.now() - timedelta(days=GMAIL_LOOKBACK_DAYS)).strftime("%d-%b-%Y")

        for sender_key, (source_name, url_pattern) in SENDERS.items():
            criteria = f'(FROM "{sender_key}" SINCE {since})'
            try:
                typ, data = imap.search(None, criteria)
                if typ != "OK":
                    continue
                ids = data[0].split()
            except Exception as e:
                logger.warning("Gmail search failed for %s: %s", sender_key, e)
                continue

            for uid in ids[-30:]:  # последние 30 писем от отправителя
                try:
                    typ, msg_data = imap.fetch(uid, "(RFC822)")
                    if typ != "OK" or not msg_data or not msg_data[0]:
                        continue
                    msg = email.message_from_bytes(msg_data[0][1])
                    vacancies = _parse_message(msg, source_name, url_pattern)
                    for v in vacancies:
                        if v.url in seen_urls:
                            continue
                        seen_urls.add(v.url)
                        result.append(v)
                except Exception as e:
                    logger.warning("Gmail parse failed uid=%s: %s", uid, e)
    finally:
        try:
            imap.close()
        except Exception:
            pass
        imap.logout()

    return result


def _parse_message(msg: email.message.Message, source_name: str, url_pattern: str) -> list[Vacancy]:
    subject = _decode_header(msg.get("Subject", ""))
    body_html, body_text = _extract_body(msg)

    urls = list(set(re.findall(url_pattern, body_html + " " + body_text)))
    if not urls:
        return []

    if not is_relevant(subject, body_text):
        return []

    result = []
    for url in urls[:10]:  # ограничим на письмо
        vid = _make_id(source_name, url)
        title = subject[:120] if subject else "Вакансия из Gmail"
        result.append(Vacancy(
            id=vid,
            title=title,
            company=source_name,
            url=url,
            salary="не указана",
            description=body_text[:3000],
        ))
    return result


def _make_id(source_name: str, url: str) -> str:
    m = re.search(r"(\d+)(?:/|\?|$)", url)
    if m:
        prefix = source_name.lower().replace(" ", "_").replace(".", "_")
        return f"gmail_{prefix}_{m.group(1)}"
    return f"gmail_{abs(hash(url))}"


def _decode_header(s: str) -> str:
    if not s:
        return ""
    parts = decode_header(s)
    result = ""
    for text, charset in parts:
        if isinstance(text, bytes):
            try:
                result += text.decode(charset or "utf-8", errors="replace")
            except LookupError:
                result += text.decode("utf-8", errors="replace")
        else:
            result += text
    return result.strip()


def _extract_body(msg: email.message.Message) -> tuple[str, str]:
    html_parts, text_parts = [], []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if "attachment" in disp:
                continue
            try:
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                charset = part.get_content_charset() or "utf-8"
                content = payload.decode(charset, errors="replace")
            except Exception:
                continue
            if ctype == "text/html":
                html_parts.append(content)
            elif ctype == "text/plain":
                text_parts.append(content)
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                content = payload.decode(charset, errors="replace")
                if msg.get_content_type() == "text/html":
                    html_parts.append(content)
                else:
                    text_parts.append(content)
        except Exception:
            pass

    body_html = "\n".join(html_parts)
    body_text = "\n".join(text_parts)
    if body_html and not body_text:
        body_text = BeautifulSoup(body_html, "lxml").get_text(" ", strip=True)
    return body_html, body_text
