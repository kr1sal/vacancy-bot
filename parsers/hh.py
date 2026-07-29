import logging
import re
from dataclasses import dataclass
from xml.etree import ElementTree as ET

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HH_RSS_URLS = [
    # Москва
    "https://hh.ru/search/vacancy/rss?text=flutter&area=1&order_by=publication_time",
    # СПб
    "https://hh.ru/search/vacancy/rss?text=flutter&area=2&order_by=publication_time",
    # Удалёнка + релокация (без региона)
    "https://hh.ru/search/vacancy/rss?text=flutter&schedule=remote&order_by=publication_time",
    "https://hh.ru/search/vacancy/rss?text=flutter&label=accept_relocation&order_by=publication_time",
]
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
    source: str = "hh"


async def fetch_vacancies() -> list[Vacancy]:
    seen: set[str] = set()
    result: list[Vacancy] = []

    async with httpx.AsyncClient(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
        for rss_url in HH_RSS_URLS:
            try:
                resp = await client.get(rss_url)
                resp.raise_for_status()
                root = ET.fromstring(resp.text)
            except (httpx.HTTPError, ET.ParseError) as e:
                logger.warning("HH RSS failed %s: %s", rss_url, e)
                continue

            for item in root.findall(".//item"):
                v = _parse_item(item)
                if not v or v.id in seen:
                    continue
                if not _matches_flutter(v.title):
                    continue
                seen.add(v.id)
                v.description = await _fetch_description(client, v.url)
                result.append(v)

        return result


def _parse_item(item: ET.Element) -> Vacancy | None:
    title_el = item.find("title")
    link_el = item.find("link")
    desc_el = item.find("description")
    if title_el is None or link_el is None:
        return None
    title = (title_el.text or "").strip()
    url = (link_el.text or "").strip()
    if not title or not url:
        return None

    m = re.search(r"/vacancy/(\d+)", url)
    vid = f"hh_{m.group(1)}" if m else f"hh_{abs(hash(url))}"

    company = "Не указана"
    salary = "не указана"
    if desc_el is not None and desc_el.text:
        company = _extract(desc_el.text, r"Вакансия компании:\s*([^<]+)") or company
        salary = _extract(desc_el.text, r"уровень месячного дохода:\s*([^<]+)") or salary

    return Vacancy(id=vid, title=title, company=company.strip(), url=url,
                   salary=salary.strip(), description="")


def _extract(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text)
    return m.group(1).strip() if m else None


def _matches_flutter(title: str) -> bool:
    return "flutter" in title.lower()


async def _fetch_description(client: httpx.AsyncClient, vacancy_url: str) -> str:
    try:
        resp = await client.get(vacancy_url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for selector in [
            "div.vacancy-description",
            "[data-qa='vacancy-description']",
            "div.g-user-content",
        ]:
            el = soup.select_one(selector)
            if el:
                text = el.get_text(" ", strip=True)
                return text[:3000]
        return ""
    except Exception as e:
        logger.warning("HH description fetch failed for %s: %s", vacancy_url, e)
        return ""
