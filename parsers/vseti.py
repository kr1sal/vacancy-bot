"""vseti.app/jobs — доска вакансий на Webflow с постраничной CMS-выдачей
(рендерится сервером, без JS/API). Вакансии вперемешку по всем профессиям,
поэтому фильтруем через общий is_relevant().
"""
import logging
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from parsers.filter import is_relevant

logger = logging.getLogger(__name__)

VSETI_URL = "https://www.vseti.app/jobs"
_PAGE_QUERY = "3835ea8c_page"
_MAX_PAGES = 40
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
    source: str = "vseti"


async def fetch_vacancies() -> list[Vacancy]:
    seen: set[str] = set()
    result: list[Vacancy] = []

    async with httpx.AsyncClient(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
        for page in range(1, _MAX_PAGES + 1):
            url = VSETI_URL if page == 1 else f"{VSETI_URL}?{_PAGE_QUERY}={page}"
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning("Vseti fetch failed (page %d): %s", page, e)
                break

            soup = BeautifulSoup(resp.text, "lxml")
            cards = soup.select("a.card-jobs")
            if not cards:
                break

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
    vid = card.get("id", "").strip()
    href = card.get("href", "")
    if not vid or not href:
        return None
    url = urljoin(VSETI_URL, href)

    title_el = card.select_one("h1.titile-jobs")
    title = title_el.get_text(strip=True) if title_el else ""
    if not title:
        return None

    company_el = card.select_one('p[fs-cmsfilter-field="company-name"]')
    company = company_el.get_text(strip=True) if company_el else "—"

    tags = [p.get_text(strip=True) for p in card.select("div.tag-parama p.paragraph-9") if p.get_text(strip=True)]
    salary = tags[-1] if tags else "не указана"

    jobstype = [p.get_text(strip=True) for p in card.select("p.jobstype-p") if p.get_text(strip=True)]
    fmt = [p.get_text(strip=True) for p in card.select('p[class*="format-p"]') if p.get_text(strip=True)]
    description = " · ".join(jobstype + tags[:-1] + fmt)

    return Vacancy(id=f"vseti_{vid}", title=title, company=company, url=url,
                   salary=salary, description=description)
