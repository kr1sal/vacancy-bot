# Chert Vacancy Bot

Персональный Telegram-бот для мониторинга Flutter-вакансий с 5 источников и генерации сопроводительных писем через LLM. Плюс Telegram Mini App для просмотра истории откликов.

## Что делает

- Парсит вакансии из HH.ru (RSS), Habr Career (HTML), Djinni.co (RSS), публичных Telegram-каналов (t.me/s/) и Gmail-писем от job-платформ (IMAP)
- Каждая вакансия проходит через LLM-суммаризацию (стек / опыт / условия / о компании) и попадает в Telegram с задержкой 15 секунд между сообщениями
- Кнопка «Написать сопроводительное» вызывает Claude Sonnet 4.5 с CV пользователя и эталонным письмом в промпте
- Дедуп в SQLite (WAL-mode)
- Mini App с фильтрами: 🆕 новые / 👁 просмотренные / ⭐ отмеченные / 📤 отклики
- Режим 🔥 Подбор — tinder-свайп по вакансиям (принять / отклонить / в избранное)
- Кнопка «Откликнулся» замыкает воронку — история откликов остаётся в SQLite
- Кнопка «↻ Правки» — перегенерация письма с указанием правок

## Стек

- Python 3.11, asyncio
- `python-telegram-bot` v21 (Bot API)
- `fastapi` + `uvicorn` (Mini App backend)
- `httpx`, `beautifulsoup4`, `lxml` (парсинг)
- `sqlite3` (raw, без ORM) в WAL-mode
- OpenRouter API: `google/gemini-2.0-flash-exp:free` для summary, `anthropic/claude-sonnet-4.5` для писем
- IMAP (`imaplib`, stdlib) для Gmail

## Архитектура

```
main.py             — оркестратор: bot polling + web server + fetch loop
bot.py              — Telegram handlers, очередь отправки, silent-failure detector
ai.py               — LLM: суммаризация (JSON) + генерация писем с revision loop
db.py               — SQLite: миграции ALTER TABLE, WAL/busy_timeout, PRAGMA
config.py           — env
parsers/
  hh.py             — HH.ru RSS × 4 (Мск, СПб, remote, relocate)
  habr.py           — Habr Career HTML × 3 (обычный, remote, salary)
  djinni.py         — Djinni RSS с фильтром primary_keyword=Flutter
  telegram_user.py  — Публичные каналы через t.me/s/<channel>
  gmail_imap.py     — IMAP от известных отправителей (hh.ru, habr, djinni, linkedin, getmatch)
webapp/
  server.py         — FastAPI + HMAC-верификация Telegram initData
  index.html        — SPA: карточки, фильтры, детали, письма, правки, режим подбора
```

## Ключевые решения

**Multi-source aggregation через дедуп-ключи.** Каждый парсер возвращает `Vacancy(id=f"{source}_{external_id}", ...)`. Дубликаты между источниками пока не склеиваются — цена в лишнем UI-шуме приемлема.

**Prompt chaining в 2 модели.** Дешёвый Gemini Flash пишет summary (JSON: stack/experience/conditions/company_about), дорогой Claude Sonnet пишет письмо на CV + summary + вакансия. Дуальность выбрана осознанно — суммаризация стоит ~$0 против ~$0.02 за письмо.

**Anti-AI-стиль в промпте письма.** Явные запреты: ~20 фраз («рад предложить», «глубокие знания» и др.) + ~10 прилагательных-усилителей. Правило: «каждое предложение делает одно из трёх: доказывает fit / объясняет мотивацию / двигает письмо вперёд».

**Human-in-the-loop для писем.** Регенерация с полем `feedback` — Claude получает предыдущее письмо + правки и переписывает.

**Silent-failure detection.** Каждый источник трекается: 5 подряд пустых ответов → warning в лог; 10 подряд → alert в Telegram владельцу.

**Роутинг режима подбора.** У карточки, открытой свайпом «нравится», путь — `/vacancy/{id}?from=match`. SPA хранит этот контекст в `state.detailsFrom` и при popstate/повторной загрузке восстанавливает его из query-параметра, поэтому «назад» ведёт в `/match`, а не в общий список.

**Безопасность Mini App.** HMAC-верификация `Telegram.WebApp.initData` через SHA-256(BOT_TOKEN). Для локальной разработки — секретный `X-Auth-Token` из `.env` (не «localhost bypass»).

## Локальный запуск

```bash
git clone https://github.com/kr1sal/vacancy-bot.git
cd vacancy-bot
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# заполни BOT_TOKEN, TELEGRAM_USER_ID, OPENROUTER_API_KEY
python main.py
```

Для Telegram Mini App нужен HTTPS URL:

```bash
# в отдельном терминале
cloudflared tunnel --url http://localhost:8080
# скопируй URL в .env → WEBAPP_PUBLIC_URL
```

Для Gmail-парсера: [Google App Password](https://myaccount.google.com/apppasswords) (требуется 2FA).

## Deploy

Планируется в отдельной ветке (docker-compose + cloudflared sidecar).

## Автор

Кирилл Иванов — Flutter-разработчик · [@kr1salyas](https://t.me/kr1salyas)
