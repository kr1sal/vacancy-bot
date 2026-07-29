"""Единый фильтр релевантности вакансии.

Используется всеми парсерами, которые получают неотфильтрованный поток
(TG, Djinni, Gmail). HH и Habr фильтруются на стороне API поиском.
"""
from config import VACANCY_KEYWORDS, VACANCY_STOPWORDS


def is_relevant(*text_fields: str) -> bool:
    """Возвращает True, если в объединённом тексте есть хоть одно
    ключевое слово И нет ни одного стоп-слова."""
    haystack = " ".join(t for t in text_fields if t).lower()
    if not haystack:
        return False
    if not any(kw in haystack for kw in VACANCY_KEYWORDS):
        return False
    if VACANCY_STOPWORDS and any(sw in haystack for sw in VACANCY_STOPWORDS):
        return False
    return True
