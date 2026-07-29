"""Djinni.co RSS-парсер. Много EU/remote/relocate вакансий, включая Сербию."""
import logging
import re
from dataclasses import dataclass
from xml.etree import ElementTree as ET

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DJINNI_RSS_URLS = [
    "https://djinni.co/jobs/rss/?primary_keyword=Flutter",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
}


@dataclass
class Vacancy:
    id: str
    title: str
    company: str
    url: str
    salary: str
    description: str
    source: str = "djinni"


async def fetch_vacancies() -> list[Vacancy]:
    seen: set[str] = set()
    result: list[Vacancy] = []

    async with httpx.AsyncClient(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
        for url in DJINNI_RSS_URLS:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning("Djinni fetch failed %s: %s", url, e)
                continue

            try:
                root = ET.fromstring(resp.text)
            except ET.ParseError as e:
                logger.warning("Djinni parse failed %s: %s", url, e)
                continue

            for item in root.findall(".//item"):
                v = _parse_item(item)
                if not v or v.id in seen:
                    continue
                if not _matches_flutter(v):
                    continue
                seen.add(v.id)
                result.append(v)

    return result


def _matches_flutter(v: "Vacancy") -> bool:
    haystack = f"{v.title} {v.description}".lower()
    keywords = ("flutter", "dart ", " dart", "мобильн", "mobile developer", "mobile-разработчик")
    return any(k in haystack for k in keywords)


def _parse_item(item: ET.Element) -> Vacancy | None:
    title_el = item.find("title")
    link_el = item.find("link")
    desc_el = item.find("description")

    if title_el is None or link_el is None:
        return None
    raw_title = (title_el.text or "").strip()
    url = (link_el.text or "").strip()
    if not raw_title or not url:
        return None

    m = re.search(r"/jobs/(\d+)", url)
    vid = f"djinni_{m.group(1)}" if m else f"djinni_{abs(hash(url))}"

    # Djinni title format: "Position at Company" или "Position — Company"
    title = raw_title
    company = "Djinni"
    for sep in [" at ", " — ", " – ", " - "]:
        if sep in raw_title:
            parts = raw_title.rsplit(sep, 1)
            if len(parts) == 2 and len(parts[1]) < 60:
                title = parts[0].strip()
                company = parts[1].strip()
                break

    description = ""
    salary = "не указана"
    if desc_el is not None and desc_el.text:
        soup = BeautifulSoup(desc_el.text, "lxml")
        description = soup.get_text(" ", strip=True)[:3000]
        salary = _extract_salary(description) or "не указана"

    return Vacancy(id=vid, title=title, company=company, url=url,
                   salary=salary, description=description)


def _extract_salary(text: str) -> str | None:
    patterns = [
        r"\$\d[\d,]*(?:\s*[-–]\s*\$?\d[\d,]*)?[^\n]{0,20}",
        r"€\d[\d,\.]*(?:\s*[-–]\s*€?\d[\d,\.]*)?[^\n]{0,20}",
        r"\d[\d\s]{2,}\s*(?:USD|EUR|€|\$)",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(0).strip()[:60]
    return None
