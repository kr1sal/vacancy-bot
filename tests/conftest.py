import os
import sys
import tempfile

# Фейковые значения до импорта config — реальные секреты в CI не нужны.
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("TELEGRAM_USER_ID", "1")
os.environ.setdefault("OPENROUTER_API_KEY", "test")
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["VACANCY_STOPWORDS"] = "react native only"

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
