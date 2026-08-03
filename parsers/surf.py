"""career.surf.ru — карьерная страница студии Surf (Tilda, статическая вёрстка).

Вакансии рендерятся сервером в карточках `div.t983__card` на вкладке "Все",
без RSS/API, поэтому парсим HTML и фильтруем через общий is_relevant()
(на странице вперемешку Development/QA/Design/Management/HR).
"""
import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from parsers.filter import is_relevant

logger = logging.getLogger(__name__)

SURF_URL = "https://career.surf.ru/"
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
    source: str = "surf"


async def fetch_vacancies() -> list[Vacancy]:
    seen: set[str] = set()
    result: list[Vacancy] = []

    async with httpx.AsyncClient(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
        try:
            resp = await client.get(SURF_URL)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Surf fetch failed: %s", e)
            return result

        soup = BeautifulSoup(resp.text, "lxml")
        cards = soup.select("div.t983__card")
        if not cards:
            logger.warning("Surf: no cards on %s (структура изменилась?)", SURF_URL)
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
    title_el = card.select_one("a.t-card__link")
    if not title_el:
        return None

    title = title_el.get_text(strip=True)
    href = title_el.get("href", "")
    if not title or not href:
        return None
    url = urljoin(SURF_URL, href)

    slug = re.sub(r"\W+", "_", href.strip("/")).strip("_") or str(abs(hash(url)))
    vid = f"surf_{slug}"

    descr_el = card.select_one(".t-card__descr")
    description = descr_el.get_text(" ", strip=True) if descr_el else ""

    return Vacancy(id=vid, title=title, company="Surf", url=url,
                   salary="не указана", description=description)
