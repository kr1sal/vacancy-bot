"""relocate.me/international-jobs — вакансии с релокацией/visa sponsorship.

Листинг серверный (без API), карточки `.jobs-list__job` (первая — платная
реклама `.job_featured`, пропускаем). Пагинация `?page=N`, всего 2 страницы.
Фильтруем по заголовку+превью через is_relevant(), и только для прошедших
фильтр вакансий подтягиваем полное описание со страницы вакансии
(`.job-info__description`).
"""
import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from parsers.filter import is_relevant

logger = logging.getLogger(__name__)

RELOCATEME_BASE_URL = "https://relocate.me"
RELOCATEME_LISTING_URL = "https://relocate.me/international-jobs"
_MAX_PAGES = 2

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class Vacancy:
    id: str
    title: str
    company: str
    url: str
    salary: str
    description: str
    source: str = "relocateme"


async def fetch_vacancies() -> list[Vacancy]:
    seen: set[str] = set()
    result: list[Vacancy] = []

    async with httpx.AsyncClient(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
        for page in range(1, _MAX_PAGES + 1):
            url = RELOCATEME_LISTING_URL if page == 1 else f"{RELOCATEME_LISTING_URL}?page={page}"
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning("Relocate.me fetch failed (page %d): %s", page, e)
                continue

            soup = BeautifulSoup(resp.text, "lxml")
            cards = soup.select(".jobs-list__job")
            if not cards and page == 1:
                logger.warning("Relocate.me: no cards on %s (структура изменилась?)", url)

            for card in cards:
                if "job_featured" in (card.get("class") or []):
                    continue  # платная реклама, не своя вакансия
                v = _parse_card(card)
                if not v or v.id in seen:
                    continue
                if not is_relevant(v.title, v.description):
                    continue
                seen.add(v.id)
                v.description = await _fetch_description(client, v.url) or v.description
                result.append(v)

    return result


def _parse_card(card) -> "Vacancy | None":
    title_el = card.select_one(".job__title a")
    if not title_el:
        return None

    href = title_el.get("href", "")
    if not href:
        return None
    url = urljoin(RELOCATEME_BASE_URL, href)

    b = title_el.select_one("b")
    title = b.get_text(strip=True) if b else title_el.get_text(" ", strip=True)
    if not title:
        return None

    company_el = card.select_one(".job__company p")
    company = company_el.get_text(strip=True) if company_el else "—"

    preview_el = card.select_one(".job__preview")
    description = preview_el.get_text(" ", strip=True) if preview_el else ""

    m = re.search(r"-(\d+)/?$", href.rstrip("/"))
    slug = m.group(1) if m else re.sub(r"\W+", "_", href.strip("/")).strip("_")
    vid = f"relocateme_{slug}"

    return Vacancy(id=vid, title=title, company=company, url=url,
                   salary="не указана", description=description)


async def _fetch_description(client: httpx.AsyncClient, url: str) -> str:
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        el = soup.select_one(".job-info__description")
        return el.get_text(" ", strip=True)[:3000] if el else ""
    except Exception as e:
        logger.warning("Relocate.me description fetch failed for %s: %s", url, e)
        return ""
