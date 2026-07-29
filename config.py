import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
TELEGRAM_USER_ID = int(os.environ["TELEGRAM_USER_ID"])
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]

MESSAGE_DELAY_SECONDS = int(os.environ.get("MESSAGE_DELAY_SECONDS", "15"))
CHECK_INTERVAL_MIN_SECONDS = int(os.environ.get("CHECK_INTERVAL_MIN_SECONDS", "60"))
CHECK_INTERVAL_MAX_SECONDS = int(os.environ.get("CHECK_INTERVAL_MAX_SECONDS", "300"))

WEBAPP_HOST = os.environ.get("WEBAPP_HOST", "127.0.0.1")
WEBAPP_PORT = int(os.environ.get("WEBAPP_PORT", "8080"))
WEBAPP_PUBLIC_URL = os.environ.get("WEBAPP_PUBLIC_URL", "").strip()
# Секрет для локального доступа без Telegram initData (curl/браузер).
# Пустая строка = локальный доступ запрещён.
WEBAPP_LOCAL_TOKEN = os.environ.get("WEBAPP_LOCAL_TOKEN", "").strip()

# Gmail IMAP (App Password: https://myaccount.google.com/apppasswords)
GMAIL_USER = os.environ.get("GMAIL_USER", "").strip()
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
GMAIL_LOOKBACK_DAYS = int(os.environ.get("GMAIL_LOOKBACK_DAYS", "3"))

# Публичные Telegram-каналы (через t.me/s/, без авторизации)
_channels_raw = os.environ.get(
    "TG_CHANNELS",
    "mobiledevjob,dartlang_jobs,forallmobile",
).strip()
TG_CHANNELS = [c.strip().lstrip("@") for c in _channels_raw.split(",") if c.strip()]

# Единый список ключевых слов для фильтрации во всех источниках
# (TG, Djinni, Gmail). HH и Habr фильтруются на стороне сайта по запросу.
VACANCY_KEYWORDS = [
    k.strip().lower() for k in os.environ.get(
        "VACANCY_KEYWORDS",
        # `мобильн` покрывает мобильный/мобильного/мобильному/мобильных...
        "flutter,dart,mobile developer,mobile-разработчик,мобильн",
    ).split(",") if k.strip()
]

# Стоп-слова: если хоть одно есть в тексте — вакансия отбрасывается.
# Полезно чтобы фильтровать «Senior only» / «Lead only» / «React Native only».
VACANCY_STOPWORDS = [
    s.strip().lower() for s in os.environ.get("VACANCY_STOPWORDS", "").split(",") if s.strip()
]

DB_PATH = os.path.join(os.path.dirname(__file__), "vacancies.db")
CV_PATH = os.path.join(os.path.dirname(__file__), "..", "CV.md")
COVER_LETTER_EXAMPLE_PATH = os.path.join(os.path.dirname(__file__), "..", "cover_letter_AMA.txt")
