"""Yandex Jobs — JSON API, отдающий список вакансий (без ключевого поиска
на стороне сайта), поэтому фильтруем локально через общий is_relevant()."""
import logging
from dataclasses import dataclass

import httpx

from parsers.filter import is_relevant

logger = logging.getLogger(__name__)

YANDEX_CITIES = [
    "moscow", "saint-petersburg", "ekaterinburg",
    "novosibirsk", "nizhniy-novgorod", "belgrade",
]
YANDEX_API_URL = "https://yandex.com/jobs/api/publications"
YANDEX_VACANCY_URL = "https://yandex.com/jobs/vacancies/{slug}"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}


@dataclass
class Vacancy:
    id: str
    title: str
    company: str
    url: str
    salary: str
    description: str
    source: str = "yandex"


async def fetch_vacancies() -> list[Vacancy]:
    seen: set[str] = set()
    result: list[Vacancy] = []
    params = [("cities", c) for c in YANDEX_CITIES]

    async with httpx.AsyncClient(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
        try:
            resp = await client.get(YANDEX_API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.warning("Yandex fetch failed: %s", e)
            return result

        for item in data.get("results", []):
            v = _parse_item(item)
            if not v or v.id in seen:
                continue
            if not is_relevant(v.title, v.description):
                continue
            seen.add(v.id)
            result.append(v)

    return result


def _parse_item(item: dict) -> "Vacancy | None":
    title = (item.get("title") or "").strip()
    slug = item.get("publication_slug_url") or ""
    if not title or not slug:
        return None

    company = "Yandex"
    public_service = item.get("public_service") or {}
    if public_service.get("name"):
        company = public_service["name"]

    return Vacancy(
        id=f"yandex_{item.get('id', slug)}",
        title=title,
        company=company,
        url=YANDEX_VACANCY_URL.format(slug=slug),
        salary="не указана",
        description=(item.get("short_summary") or "").strip(),
    )
