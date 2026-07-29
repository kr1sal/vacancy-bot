import json
import logging
import re

import httpx

from config import OPENROUTER_API_KEY, CV_PATH, COVER_LETTER_EXAMPLE_PATH

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
SUMMARY_MODEL = "google/gemini-2.0-flash-exp:free"
LETTER_MODEL = "anthropic/claude-sonnet-4.5"

_HEADERS = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
    "HTTP-Referer": "https://github.com/kr1sal",
    "X-Title": "Chert Vacancy Bot",
}


def _read_file(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _call(model: str, prompt: str, max_tokens: int = 800) -> str:
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    with httpx.Client(timeout=90) as client:
        resp = client.post(OPENROUTER_URL, json=payload, headers=_HEADERS)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


def summarize_vacancy(title: str, company: str, description: str) -> dict:
    """Дешёвая LLM извлекает выжимку: stack / experience / conditions / company_about."""
    prompt = f"""Извлеки из описания вакансии структурированную выжимку.

Вакансия: {title}
Компания: {company}

Описание:
{description}

Верни СТРОГО валидный JSON без комментариев и без markdown:
{{
  "stack": "технологии через запятую (Flutter, Dart, BLoC, REST) — только реально упомянутые в описании",
  "experience": "требуемый опыт короткой строкой (1+ год / 3-5 лет / без опыта / senior). Если не указан — 'не указан'",
  "conditions": "условия одной короткой фразой: формат работы (офис/удалёнка/гибрид), оформление, зарплата если указана в описании, ключевые бонусы. Максимум 15 слов",
  "company_about": "чем занимается компания. Одно короткое предложение, что за продукт/индустрия"
}}

Если поле извлечь невозможно — ставь 'не указано'."""

    try:
        raw = _call(SUMMARY_MODEL, prompt, max_tokens=500)
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
        return json.loads(raw)
    except Exception as e:
        logger.error("Vacancy summarize failed: %s", e)
        return {
            "stack": "не удалось извлечь",
            "experience": "не указан",
            "conditions": "см. вакансию",
            "company_about": company,
        }


def generate_cover_letter(
    title: str,
    company: str,
    description: str,
    previous_letter: str | None = None,
    feedback: str | None = None,
) -> str:
    cv = _read_file(CV_PATH)
    example = _read_file(COVER_LETTER_EXAMPLE_PATH)

    revision_block = ""
    if previous_letter and feedback:
        revision_block = f"""

ПРЕДЫДУЩИЙ ВАРИАНТ ПИСЬМА:
{previous_letter}

ПРАВКИ ОТ КАНДИДАТА (обязательно учти при перегенерации):
{feedback}

Задача: переписать письмо с учётом правок выше. Не игнорируй ни одной правки. Сохрани всё удачное из предыдущего варианта, но выполни требования кандидата."""

    prompt = f"""Напиши сопроводительное письмо от лица кандидата на вакансию ниже.

РЕЗЮМЕ:
{cv}

ЭТАЛОННЫЙ СТИЛЬ (тон и рытм, которые нужно повторить — но не копируй фразы):
{example}

ВАКАНСИЯ:
{title} — {company}

{description}

СТРУКТУРА (3 абзаца, до 200 слов всего):
- Абзац 1 (1-2 предложения): что видел в вакансии + чем конкретно из своего опыта попадаю. Без «Добрый день, я хочу откликнуться» — сразу к делу после приветствия.
- Абзац 2 (3-4 предложения): 2-3 конкретных факта из резюме, которые матчат требования. Технологии, задачи, что реально делал. Без прилагательных.
- Абзац 3 (1-2 предложения): либо честно про пробел в требованиях (если есть), либо короткий следующий шаг. Без «буду рад пообщаться».

ЖЁСТКИЕ ПРАВИЛА СТИЛЯ:
1. Каждое предложение делает одно из трёх: (а) доказывает fit, (б) объясняет мотивацию, (в) двигает письмо вперёд. Ничего не «для красоты».
2. Варьируй длину предложений. Одно короткое, одно среднее — рытм важнее гладкости.
3. НЕ начинай подряд несколько предложений с «Я». Ставь глагол или контекст вперёд.
4. Пиши конкретно: не «работал с state management», а «Riverpod и BLoC». Не «интегрировал карты», а «yandex_mapkit».
5. Если требования вакансии не совпадают с опытом — скажи одним предложением, без оправданий и «но зато я быстро учусь».

ЗАПРЕЩЕННЫЕ ФРАЗЫ (не использовать ни в каком виде):
«рад предложить свою кандидатуру», «с интересом ознакомился», «считаю себя», «убеждён что», «моя ключевая сила», «был бы рад», «готов внести вклад», «стремлюсь развиваться», «динамично развивающаяся», «глубокие знания», «сильный опыт», «отличный опыт», «страсть к», «горящие глаза», «синергия», «драйв», «в кратчайшие сроки», «команда мечты», «прошу рассмотреть мою кандидатуру», «спасибо за внимание».

ЗАПРЕЩЕННЫЕ ПРИЛАГАТЕЛЬНЫЕ-УСИЛИТЕЛИ:
«масштабный», «инновационный», «передовой», «уникальный», «профессиональный», «эффективный», «качественный». Если хочешь усилить — усиливай фактом, не словом.

ПОДПИСЬ (на новой строке в конце):
Кирилл Иванов
kirillivanov523@gmail.com · @kr1salyas

Отвечай ТОЛЬКО текстом письма. Никаких пояснений, никакого markdown, никаких кавычек вокруг.{revision_block}"""

    return _call(LETTER_MODEL, prompt, max_tokens=800)
