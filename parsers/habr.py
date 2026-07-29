import logging
import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HABR_URLS = [
    "https://career.habr.com/vacancies?q=flutter&type=all&sort=date",
    "https://career.habr.com/vacancies?q=flutter&type=all&sort=date&remote=true",
    "https://career.habr.com/vacancies?q=flutter&type=all&sort=date&with_salary=true",
]
HABR_BASE = "https://career.habr.com"


@dataclass
class Vacancy:
    id: str
    title: str
    company: str
    url: str
    salary: str
    description: str
    source: str = "habr"


async def fetch_vacancies() -> list[Vacancy]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9",
    }
    seen: set[str] = set()
    result: list[Vacancy] = []

    async with httpx.AsyncClient(headers=headers, timeout=20, follow_redirects=True) as client:
        for url in HABR_URLS:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning("Habr fetch failed %s: %s", url, e)
                continue

            soup = BeautifulSoup(resp.text, "lxml")
            cards = _find_cards(soup)
            if not cards:
                logger.warning("Habr: no cards on %s (структура изменилась?)", url)
                continue

            for card in cards[:20]:
                v = _parse_card(card)
                if v and v.id not in seen:
                    seen.add(v.id)
                    result.append(v)

        return result


def _find_cards(soup: BeautifulSoup):
    # try multiple known selectors in priority order
    for selector in [
        "div.vacancy-card",
        "article.vacancy-card",
        "div.job-snippet",
        "[class*='vacancy-card']",
        "[class*='VacancyCard']",
    ]:
        cards = soup.select(selector)
        if cards:
            return cards
    return []


def _parse_card(card) -> "Vacancy | None":
    # title + url
    title_el = (
        card.select_one("a.vacancy-card__title")
        or card.select_one("a[class*='title']")
        or card.select_one("h2 a")
        or card.select_one("h3 a")
        or card.select_one("a[href*='/vacancies/']")
    )
    if not title_el:
        return None

    title = title_el.get_text(strip=True)
    href = title_el.get("href", "")
    if not href:
        return None
    url = href if href.startswith("http") else HABR_BASE + href

    # stable ID from URL slug
    m = re.search(r"/vacancies/(\d+)", url)
    vid = f"habr_{m.group(1)}" if m else f"habr_{abs(hash(url))}"

    # company
    company_el = (
        card.select_one("a.vacancy-card__company")
        or card.select_one("[class*='company']")
        or card.select_one("span.company-name")
    )
    company = company_el.get_text(strip=True) if company_el else "Не указана"

    # salary
    salary_el = (
        card.select_one("[class*='salary']")
        or card.select_one("[class*='compensation']")
    )
    salary = salary_el.get_text(strip=True) if salary_el else "не указана"

    return Vacancy(id=vid, title=title, company=company, url=url, salary=salary, description="")
