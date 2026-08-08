"""Remote OK — публичный JSON API (без ключа), только удалённые вакансии.

Первый элемент ответа — служебный объект legal/API-info, не вакансия,
поэтому пропускаем его отдельно. Лента общая по всем стекам, фильтруем
через is_relevant() по позиции/тегам/описанию.
"""
import logging
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from parsers.filter import is_relevant

logger = logging.getLogger(__name__)

REMOTEOK_API_URL = "https://remoteok.com/api"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


@dataclass
class Vacancy:
    id: str
    title: str
    company: str
    url: str
    salary: str
    description: str
    source: str = "remoteok"


async def fetch_vacancies() -> list[Vacancy]:
    result: list[Vacancy] = []

    async with httpx.AsyncClient(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
        try:
            resp = await client.get(REMOTEOK_API_URL)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.warning("RemoteOK fetch failed: %s", e)
            return result

        if not isinstance(data, list):
            logger.warning("RemoteOK: неожиданный формат ответа")
            return result

        for item in data:
            if not isinstance(item, dict) or "id" not in item or "position" not in item:
                continue  # служебный объект legal/API-info
            v = _parse_item(item)
            if not v:
                continue
            tags = " ".join(item.get("tags") or [])
            if not is_relevant(v.title, tags, v.description):
                continue
            result.append(v)

    return result


def _parse_item(item: dict) -> "Vacancy | None":
    title = (item.get("position") or "").strip()
    url = (item.get("url") or "").strip()
    if not title or not url:
        return None

    company = (item.get("company") or "—").strip()
    description = BeautifulSoup(item.get("description") or "", "lxml").get_text(" ", strip=True)[:3000]

    salary_min = item.get("salary_min") or 0
    salary_max = item.get("salary_max") or 0
    salary = f"${salary_min:,}–${salary_max:,}" if salary_min and salary_max else "не указана"

    return Vacancy(id=f"remoteok_{item['id']}", title=title, company=company, url=url,
                   salary=salary, description=description)
