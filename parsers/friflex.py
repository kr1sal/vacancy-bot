"""career.friflex.com — карьерная страница студии Friflex.

Вакансии рендерятся сервером в аккордеоне `li.drop-list-wrap` (без RSS/API
и без отдельного URL на вакансию — общая ссылка на карьерную страницу),
поэтому парсим HTML и фильтруем через общий is_relevant().
"""
import logging
import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from parsers.filter import is_relevant

logger = logging.getLogger(__name__)

FRIFLEX_URL = "https://career.friflex.com/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
}


@dataclass
class Vacancy:
    id: str
    title: str
    company: str
    url: str
    salary: str
    description: str
    source: str = "friflex"


async def fetch_vacancies() -> list[Vacancy]:
    seen: set[str] = set()
    result: list[Vacancy] = []

    async with httpx.AsyncClient(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
        try:
            resp = await client.get(FRIFLEX_URL)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Friflex fetch failed: %s", e)
            return result

        soup = BeautifulSoup(resp.text, "lxml")
        cards = soup.select("li.drop-list-wrap")
        if not cards:
            logger.warning("Friflex: no cards on %s (структура изменилась?)", FRIFLEX_URL)
            return result

        for card in cards:
            v = _parse_card(card)
            if not v or v.id in seen:
                continue
            if not is_relevant(v.title, v.description):
                continue
            seen.add(v.id)
            result.append(v)

    return result


def _parse_card(card) -> "Vacancy | None":
    title_el = card.select_one(".drop-item__title")
    if not title_el:
        return None
    title = title_el.get_text(strip=True)
    if not title:
        return None

    subtitle_el = card.select_one(".drop-item__subtitle")
    location = subtitle_el.get_text(strip=True) if subtitle_el else ""

    descr_el = card.select_one(".drop-item__content")
    description = descr_el.get_text(" ", strip=True)[:3000] if descr_el else ""
    if location:
        description = f"{location}. {description}"

    slug = re.sub(r"\W+", "_", title.lower()).strip("_") or str(abs(hash(title)))
    return Vacancy(id=f"friflex_{slug}", title=title, company="Friflex", url=FRIFLEX_URL,
                   salary="не указана", description=description)
