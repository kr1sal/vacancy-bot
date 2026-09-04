"""Wellfound (ex-AngelList) — вакансии стартапов, роль-лендинг /role/r/flutter-developer.

Страница на Next.js, весь листинг уже отрендерен сервером в JSON
`<script id="__NEXT_DATA__">` (Apollo cache), поэтому JS не нужен.
Сайт стоит за Cloudflare Turnstile: если защита сработала, вместо
JSON-данных приходит challenge-страница — в этом случае просто
возвращаем пустой список (как молчащий источник), а не роняем цикл.

Структура кэша: `talent.seoLandingPageJobSearchResults(...)` содержит
список стартапов (`startups`), у каждого — `highlightedJobListings`
(обычно одна вакансия, изредка несколько). Берём только первую
страницу (perPage=20) — как и другие парсеры без полноценного API.
"""
import json
import logging
import re
from dataclasses import dataclass

import httpx

from parsers.filter import is_relevant

logger = logging.getLogger(__name__)

WELLFOUND_URL = "https://wellfound.com/role/r/flutter-developer"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S
)


@dataclass
class Vacancy:
    id: str
    title: str
    company: str
    url: str
    salary: str
    description: str
    source: str = "wellfound"


async def fetch_vacancies() -> list[Vacancy]:
    result: list[Vacancy] = []

    async with httpx.AsyncClient(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
        try:
            resp = await client.get(WELLFOUND_URL)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Wellfound fetch failed: %s", e)
            return result

        apollo = _extract_apollo_state(resp.text)
        if apollo is None:
            logger.warning("Wellfound: не удалось найти __NEXT_DATA__ (challenge-страница?)")
            return result

        for v in _parse_apollo_state(apollo):
            if not is_relevant(v.title, v.description):
                continue
            result.append(v)

    return result


def _extract_apollo_state(html: str) -> dict | None:
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
        return data["props"]["pageProps"]["apolloState"]["data"]
    except (ValueError, KeyError, TypeError) as e:
        logger.warning("Wellfound: разбор __NEXT_DATA__ не удался: %s", e)
        return None


def _parse_apollo_state(apollo: dict) -> list[Vacancy]:
    result: list[Vacancy] = []

    talent = apollo.get("ROOT_QUERY", {}).get("talent", {})
    search_key = next((k for k in talent if k.startswith("seoLandingPageJobSearchResults")), None)
    if not search_key:
        return result

    for startup_ref in talent[search_key].get("startups", []):
        startup = apollo.get(startup_ref.get("__ref", ""))
        if not isinstance(startup, dict):
            continue
        company = (startup.get("name") or "—").strip()

        for job_ref in startup.get("highlightedJobListings", []):
            job = apollo.get(job_ref.get("__ref", ""))
            v = _parse_job(job, company)
            if v:
                result.append(v)

    return result


def _parse_job(job: "dict | None", company: str) -> "Vacancy | None":
    if not isinstance(job, dict):
        return None

    job_id = job.get("id")
    slug = job.get("slug") or ""
    title = (job.get("title") or "").strip()
    if not job_id or not title:
        return None

    url = f"https://wellfound.com/jobs/{job_id}-{slug}"
    description = (job.get("description") or "").strip()[:3000]
    salary = (job.get("compensation") or "").strip() or "не указана"

    return Vacancy(id=f"wellfound_{job_id}", title=title, company=company, url=url,
                   salary=salary, description=description)
