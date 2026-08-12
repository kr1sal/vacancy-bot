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
    # Только прямые ссылки на конкретную вакансию (числовой id после /jobs/view/).
    # Текущий шаблон digest-писем LinkedIn шлёт в основном /comm/jobs/alerts
    # (управление оповещениями) и /comm/jobs/search-results (страница поиска) —
    # обе ведут в никуда конкретное, а заголовком становилась тема письма,
    # из-за чего в ленте всплывали «вакансии», реально ведущие на общий поиск.
    "linkedin.com": ("LinkedIn",
                     r"https?://[^\s\"<>]*linkedin\.com/(?:jobs/view|comm/jobs/view)/\d+[^\s\"<>]*"),
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

    if not is_relevant(subject, body_text):
        return []

    # LinkedIn job-alert дайджест — не одна вакансия, а основная + карточки
    # «похожих вакансий», у каждой свой jobid, реальная компания и должность.
    # Ставить всем тему письма (как для остальных отправителей) даёт кучу
    # «дублей» с company="LinkedIn" и одинаковым title.
    if source_name == "LinkedIn" and body_html:
        result = _parse_linkedin_digest(body_html, body_text)
        if result:
            return result
        # Карточки не распознались (LinkedIn поменял вёрстку) — не плодим
        # дубли по всем найденным ссылкам, берём только первую.
        urls = re.findall(url_pattern, body_html + " " + body_text)
        if not urls:
            return []
        title = subject[:120] if subject else "Вакансия из Gmail"
        return [Vacancy(
            id=_make_id(source_name, urls[0]), title=title, company=source_name,
            url=urls[0], salary="не указана", description=body_text[:3000],
        )]

    urls = list(set(re.findall(url_pattern, body_html + " " + body_text)))
    if not urls:
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


_LI_JOB_ID_RE = re.compile(r"linkedin\.com/(?:jobs/view|comm/jobs/view)/(\d+)")


def _parse_linkedin_digest(body_html: str, body_text: str) -> list[Vacancy]:
    """Вытаскивает реальные title/company для каждой карточки вакансии в письме.

    У каждой ссылки .../jobs/view/<id> в ближайшей родительской <table> лежит
    текст вида: "<Должность>\\n<Компания> · <Локация>\\n[доп. строка]" — так
    LinkedIn верстает и основную вакансию письма, и карточки "похожих"."""
    soup = BeautifulSoup(body_html, "lxml")
    seen_ids: set[str] = set()
    result: list[Vacancy] = []

    for a in soup.find_all("a", href=True):
        m = _LI_JOB_ID_RE.search(a["href"])
        if not m:
            continue
        jid = m.group(1)
        if jid in seen_ids:
            continue
        seen_ids.add(jid)

        table = a.find_parent("table")
        if not table:
            continue
        lines = [l.strip() for l in table.get_text("\n", strip=True).split("\n") if l.strip()]
        if len(lines) < 2 or " · " not in lines[1]:
            continue
        title, company = lines[0], lines[1].split(" · ")[0].strip()
        if not title or not company or title == company:
            continue

        result.append(Vacancy(
            id=f"gmail_linkedin_{jid}",
            title=title[:200],
            company=company[:200],
            url=a["href"],
            salary="не указана",
            description=body_text[:3000],
        ))
        if len(result) >= 10:
            break

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
