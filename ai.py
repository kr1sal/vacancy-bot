import json
import logging
import re

import httpx

from config import OPENROUTER_API_KEY, CV_PATH, COVER_LETTER_EXAMPLE_PATH

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# Дешёвая модель для структурированной суммаризации (~$0.10/1M in)
SUMMARY_MODEL = "google/gemini-2.5-flash-lite"
# Сильная модель для сопроводительных писем
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

Задача: переписать письмо с учётом правок. Не игнорируй ни одной правки. Сохрани всё удачное, но выполни требования кандидата."""

    prompt = f"""Напиши сопроводительное письмо от лица кандидата на вакансию ниже.

РЕЗЮМЕ:
{cv}

ЭТАЛОННЫЙ СТИЛЬ (короткие живые фразы, факты вместо оценок; НЕ копируй фразы, копируй ритм):
{example}

ВАКАНСИЯ:
{title}, {company}

{description}

СТРУКТУРА — ровно 3 коротких абзаца, всего 100-150 слов.
Абзац 1 (1-2 предложения): что откликаешься. Сразу называешь конкретную роль, чтобы было видно, что письмо не шаблонное.
Абзац 2 (2-4 предложения): 2-3 конкретных факта из CV, которые точно матчат требования. Технологии по названию (Riverpod, BLoC, yandex_mapkit, dio), задачи глаголом («реализовал», «настроил», «внедрил»), артефакты (WebView-авторизация, k3s-кластер, GitLab CI/CD).
Абзац 3 (1 предложение): предложение созвониться или следующий шаг. Без «буду рад».

СТИЛЬ — читай эти правила буквально.

1. Пиши уверенно. Утверждай, не предлагай. НЕ используй: «надеюсь», «если у вас есть возможность», «был бы рад», «хотел бы», «мог бы», «по возможности», «если это уместно», «если не сложно», «с удовольствием».

2. НИКАКИХ длинных тире (— или –). Замени на точку, запятую или дефис (-). Обычные тире считаются AI-сигналом.

3. Не начинай предложение с «Я». Максимум 1 «я» на абзац. Ставь вперёд глагол или контекст.

4. Ритм: короткое предложение + среднее + короткое. Не пиши подряд две одинаковые по длине фразы.

5. Каждое утверждение подкрепи фактом из CV. «Работал с Flutter» — плохо. «Год работал с Flutter в NSG Soft, реализовал WebView-авторизацию для стриминговых платформ» — хорошо.

6. Если чего-то нет в CV — скажи прямо одним предложением, без оправданий и без «но зато я быстро учусь».

ЗАПРЕЩЕННЫЕ ФРАЗЫ (recruiters видят их каждый день):
«рад предложить кандидатуру», «с интересом ознакомился», «считаю себя», «убеждён что», «моя ключевая сила», «готов внести вклад», «стремлюсь развиваться», «динамично развивающаяся», «глубокие знания», «сильный опыт», «отличный опыт», «страсть к», «горящие глаза», «синергия», «драйв», «в кратчайшие сроки», «команда мечты», «прошу рассмотреть мою кандидатуру», «спасибо за внимание», «I am excited», «excited to apply», «passionate», «leverage», «spearhead», «game-changer», «impact», «solution-oriented».

ЗАПРЕЩЕННЫЕ ПРИЛАГАТЕЛЬНЫЕ-УСИЛИТЕЛИ:
«масштабный», «инновационный», «передовой», «уникальный», «профессиональный», «эффективный», «качественный», «выдающийся», «значительный». Усиливай фактом, не эпитетом.

ПОДПИСЬ (на новой строке в конце, ровно этот формат):
Кирилл Иванов
kirillivanov523@gmail.com · @kr1salyas

Отвечай ТОЛЬКО текстом письма. Никаких пояснений, никакого markdown, никаких кавычек.{revision_block}"""

    raw = _call(LETTER_MODEL, prompt, max_tokens=800)
    return _post_process_letter(raw)


# em-dash / en-dash: символьные и как HTML entity
_EM_DASH_CHARS = ("—", "–", "&mdash;", "&ndash;")
# Слабые/неуверенные обороты, которые Claude всё равно иногда протаскивает.
# Заменяем на прямые аналоги или срезаем целиком.
_WEAK_REPLACEMENTS = [
    (r"\bбыл бы рад\b", "готов"),
    (r"\bбуду рад\b", "готов"),
    (r"\bхотел бы\b", "хочу"),
    (r"\bмог бы\b", "могу"),
    (r"\bнадеюсь(,)?\s*", ""),
    (r"\bесли (это )?возможно(,)?\s*", ""),
    (r"\bесли не сложно(,)?\s*", ""),
    (r"\bесли это уместно(,)?\s*", ""),
    (r"\bпо возможности(,)?\s*", ""),
    (r"\bс удовольствием\b", ""),
    (r"\bс интересом\b", ""),
    (r"I(?:'|)m excited to", "I want to"),
    (r"\bexcited to apply\b", "applying"),
]


def _post_process_letter(text: str) -> str:
    """Гарантированно чистит em-dash и слабые формулировки после LLM.

    em-dash в русском обычно используется как усиленная запятая или
    вводит пояснение — заменяем на запятую, не на точку, чтобы не
    ломать структуру предложения.
    """
    if not text:
        return text

    # em/en dash → запятая с пробелом (сохраняем связность предложения).
    # Отдельно HTML-entity версии.
    text = text.replace("&mdash;", ",").replace("&ndash;", ",")
    text = re.sub(r"\s*[—–]\s*", ", ", text)

    # слабые обороты
    for pattern, repl in _WEAK_REPLACEMENTS:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)

    # чистка после срезов: двойные пробелы, ", ," , ",." , пустые запятые
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r",\s*\.", ".", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # запятая в начале строки после срезов
    text = re.sub(r"^\s*,\s*", "", text, flags=re.MULTILINE)
    # капитализация после точки/восклицания/вопроса. Не трогаем строки,
    # где первое слово похоже на email или URL.
    def _cap_after_dot(m: re.Match) -> str:
        letter = m.group(1)
        rest_start = m.end()
        # заглядываем на следующие ~40 символов — есть ли @ или :// внутри «слова»
        window = text[rest_start:rest_start + 40].split(maxsplit=1)[0] if rest_start < len(text) else ""
        if "@" in window or "://" in window:
            return letter
        return letter.upper()

    text = re.sub(r"(?<=[.!?]\s)([а-яa-z])", _cap_after_dot, text)

    def _cap_line_start(m: re.Match) -> str:
        letter = m.group(1)
        line_start = m.start()
        window = text[line_start:line_start + 40].split(maxsplit=1)[0] if line_start < len(text) else ""
        if "@" in window or "://" in window:
            return letter
        return letter.upper()

    text = re.sub(r"(?m)^([а-яa-z])", _cap_line_start, text)

    return text.strip()
