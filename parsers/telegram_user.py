"""Парсер публичных Telegram-каналов через t.me/s/<channel>.

Использует HTML-предпросмотр, который Telegram отдаёт без авторизации.
Не требует api_id/api_hash, не требует Telethon.

Ограничения:
- Только публичные каналы с включённым предпросмотром.
- Приватные группы/каналы недоступны — для них нужен User API.
"""
import logging
import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from config import TG_CHANNELS
from parsers.filter import is_relevant

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}


@dataclass
class Vacancy:
    id: str
    title: str
    company: str
    url: str
    salary: str
    description: str
    source: str = "tg"


def is_enabled() -> bool:
    return bool(TG_CHANNELS)


async def fetch_vacancies() -> list[Vacancy]:
    if not is_enabled():
        return []

    result: list[Vacancy] = []
    async with httpx.AsyncClient(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
        for channel in TG_CHANNELS:
            try:
                resp = await client.get(f"https://t.me/s/{channel}")
                resp.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning("TG fetch failed @%s: %s", channel, e)
                continue

            soup = BeautifulSoup(resp.text, "lxml")
            posts = soup.select(".tgme_widget_message")
            if not posts:
                logger.warning("TG @%s: нет постов (превью выключено?)", channel)
                continue

            for post in posts:
                v = _parse_post(channel, post)
                if not v:
                    continue
                if not is_relevant(v.title, v.description):
                    continue
                result.append(v)

    return result


def _parse_post(channel: str, post) -> Vacancy | None:
    data_post = post.get("data-post", "")
    m = re.match(r"([^/]+)/(\d+)", data_post)
    if not m:
        return None
    msg_id = m.group(2)
    vid = f"tg_{channel}_{msg_id}"

    text_el = post.select_one(".tgme_widget_message_text")
    if not text_el:
        return None

    for br in text_el.find_all("br"):
        br.replace_with("\n")
    text = text_el.get_text("\n", strip=True)
    if len(text) < 40:
        return None

    title = _pick_title(text)

    company = _extract_company(text) or f"@{channel}"
    salary = _extract_salary(text) or "не указана"
    url = _extract_external_url(text_el) or f"https://t.me/{channel}/{msg_id}"

    return Vacancy(
        id=vid,
        title=title,
        company=company,
        url=url,
        salary=salary,
        description=text[:3000],
    )


def _pick_title(text: str) -> str:
    """Первая строка, где есть кириллица или латиница (не просто эмодзи/#хештеги)."""
    for line in text.split("\n"):
        cleaned = line.strip()
        if len(cleaned) < 5:
            continue
        if re.search(r"[A-Za-zА-Яа-я]", cleaned) and not cleaned.startswith("#"):
            return cleaned[:120]
    return "Вакансия из Telegram"


def _extract_external_url(text_el) -> str | None:
    """Ищем внешнюю ссылку (HH, Habr, компания и т.д.), не t.me."""
    for a in text_el.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http") and "t.me/" not in href:
            return href
    return None


def _extract_company(text: str) -> str | None:
    patterns = [
        r"[Кк]омпани[яи]:\s*([^\n]+)",
        r"[Cc]ompany:\s*([^\n]+)",
        r"🏢\s*([^\n]+)",
        r"[Вв] компанию\s+([^\n]+?)(?:\s+(?:ищ[еу]|требуется|нужен))",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1).strip()[:80]
    return None


def _extract_salary(text: str) -> str | None:
    patterns = [
        r"(?:[Зз]/?[Пп]|[Зз]арплата|[Сс]алари|[Ss]alary|💰)\s*[:—-]?\s*([^\n]+)",
        r"(\$\d[\d,]*(?:\s*[-–]\s*\$?\d[\d,]*)?[^\n]{0,20})",
        r"(\d{2,3}[\s.]?\d{3}(?:\s*[-–]\s*\d{2,3}[\s.]?\d{3})?\s*(?:руб|₽|€|EUR|USD|\$))",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1).strip()[:80]
    return None
