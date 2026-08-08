"""agima.ru/careers/ — карьерная страница digital-агентства AGIMA.

Вакансии рендерятся сервером в карточках `div.careers-jobs__vacancy`
(дизайн/аккаунтинг/HR/разработка вперемешку, без RSS/API), поэтому парсим
HTML листинга, фильтруем по заголовку через is_relevant() и только для
прошедших фильтр вакансий дополнительно подтягиваем полное описание со
страницы вакансии.
"""
import logging
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from parsers.filter import is_relevant

logger = logging.getLogger(__name__)

AGIMA_URL = "https://agima.ru/careers/"
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
    source: str = "agima"


async def fetch_vacancies() -> list[Vacancy]:
    seen: set[str] = set()
    result: list[Vacancy] = []

    async with httpx.AsyncClient(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
        try:
            resp = await client.get(AGIMA_URL)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Agima fetch failed: %s", e)
            return result

        soup = BeautifulSoup(resp.text, "lxml")
        cards = soup.select("div.careers-jobs__vacancy")
        if not cards:
            logger.warning("Agima: no cards on %s (структура изменилась?)", AGIMA_URL)
            return result

        for card in cards:
            v = _parse_card(card)
            if not v or v.id in seen:
                continue
            if not is_relevant(v.title):
                continue
            seen.add(v.id)
            v.description = await _fetch_description(client, v.url)
            result.append(v)

    return result


def _parse_card(card) -> "Vacancy | None":
    link = card.select_one("a[href]")
    if not link:
        return None
    title = link.get_text(strip=True)
    href = link.get("href", "")
    if not title or not href:
        return None

    url = urljoin(AGIMA_URL, href)
    slug = href.strip("/").rsplit("/", 1)[-1]
    return Vacancy(id=f"agima_{slug}", title=title, company="AGIMA", url=url,
                   salary="не указана", description="")


async def _fetch_description(client: httpx.AsyncClient, url: str) -> str:
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        el = soup.select_one("div.vacancy__description")
        return el.get_text(" ", strip=True)[:3000] if el else ""
    except Exception as e:
        logger.warning("Agima description fetch failed for %s: %s", url, e)
        return ""
