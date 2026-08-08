"""We Work Remotely — RSS-фид категории Programming (100% удалённые вакансии).

WWR отдаёт честный RSS без JS, заголовок в формате "Компания: Позиция".
Вакансии в категории смешанные (frontend/backend/devops/mobile), поэтому
фильтруем через общий is_relevant().
"""
import logging
import re
from dataclasses import dataclass
from xml.etree import ElementTree as ET

import httpx
from bs4 import BeautifulSoup

from parsers.filter import is_relevant

logger = logging.getLogger(__name__)

WWR_RSS_URL = "https://weworkremotely.com/categories/remote-programming-jobs.rss"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
}
_MIN_RSS_BYTES = 200


@dataclass
class Vacancy:
    id: str
    title: str
    company: str
    url: str
    salary: str
    description: str
    source: str = "wwr"


async def fetch_vacancies() -> list[Vacancy]:
    seen: set[str] = set()
    result: list[Vacancy] = []

    async with httpx.AsyncClient(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
        xml_text = await _fetch_rss(client)
        if not xml_text:
            return result

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.warning("WWR: XML parse failed (%d байт): %s", len(xml_text), e)
            return result

        for item in root.findall(".//item"):
            v = _parse_item(item)
            if not v or v.id in seen:
                continue
            if not is_relevant(v.title, v.description):
                continue
            seen.add(v.id)
            result.append(v)

    return result


async def _fetch_rss(client: httpx.AsyncClient, retries: int = 2) -> str | None:
    for attempt in range(retries + 1):
        try:
            resp = await client.get(WWR_RSS_URL)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            if attempt < retries:
                continue
            logger.warning("WWR: fetch failed: %s", e)
            return None

        body = resp.text
        if len(body) < _MIN_RSS_BYTES or "<rss" not in body[:200].lower():
            if attempt < retries:
                continue
            logger.debug("WWR: пустой/битый ответ (%d байт), status=%d",
                         len(body), resp.status_code)
            return None
        return body
    return None


def _parse_item(item: ET.Element) -> "Vacancy | None":
    title_el = item.find("title")
    link_el = item.find("link")
    descr_el = item.find("description")

    if title_el is None or link_el is None:
        return None
    raw_title = (title_el.text or "").strip()
    url = (link_el.text or "").strip()
    if not raw_title or not url:
        return None

    title = raw_title
    company = "—"
    if ": " in raw_title:
        company, title = raw_title.split(": ", 1)
        company = company.strip()
        title = title.strip()

    description = ""
    if descr_el is not None and descr_el.text:
        description = BeautifulSoup(descr_el.text, "lxml").get_text(" ", strip=True)[:3000]

    m = re.search(r"/remote-jobs/([\w-]+)", url)
    vid = f"wwr_{m.group(1)}" if m else f"wwr_{abs(hash(url))}"

    return Vacancy(id=vid, title=title, company=company, url=url,
                   salary="не указана", description=description)
