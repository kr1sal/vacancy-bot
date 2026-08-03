import asyncio
import logging
import html as html_lib

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, MenuButtonWebApp
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from config import TELEGRAM_USER_ID, MESSAGE_DELAY_SECONDS, WEBAPP_PUBLIC_URL
import db
import ai
from parsers import hh as hh_parser
from parsers import habr as habr_parser
from parsers import djinni as djinni_parser
from parsers import surf as surf_parser
from parsers import yandex as yandex_parser
from parsers import telegram_user as tg_parser
from parsers import gmail_imap as gmail_parser

logger = logging.getLogger(__name__)

_vacancies: dict = {}
_send_queue: asyncio.Queue = asyncio.Queue()

# Отслеживание молчаливых сбоев: N подряд нулевых ответов от источника
_ZERO_STREAK_WARN = 5     # предупредить в лог
_ZERO_STREAK_ALERT = 10   # прислать в TG владельцу
_zero_streak: dict[str, int] = {}
_alerted_sources: set[str] = set()


async def _safe_fetch(parser, name: str) -> list:
    try:
        return await parser.fetch_vacancies()
    except Exception as e:
        logger.exception("%s fetch failed: %s", name, e)
        return []


def _track_source_health(app: Application, results: dict[str, int]) -> None:
    """Ловит источники, которые молчат подряд, и алертит владельца."""
    for name, count in results.items():
        if count > 0:
            if _zero_streak.get(name, 0) >= _ZERO_STREAK_WARN:
                logger.info("Source %s: восстановлен (нашлось %d)", name, count)
            _zero_streak[name] = 0
            _alerted_sources.discard(name)
            continue

        _zero_streak[name] = _zero_streak.get(name, 0) + 1
        streak = _zero_streak[name]
        if streak == _ZERO_STREAK_WARN:
            logger.warning("Source %s: %d подряд нулевых ответов", name, streak)
        if streak == _ZERO_STREAK_ALERT and name not in _alerted_sources:
            _alerted_sources.add(name)
            asyncio.create_task(
                _send_owner_alert(app, f"⚠️ Источник <b>{name}</b> молчит {streak} циклов подряд. Возможно сломался парсер.")
            )


async def _send_owner_alert(app: Application, text: str) -> None:
    try:
        await app.bot.send_message(
            chat_id=TELEGRAM_USER_ID, text=text, parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.error("Alert send failed: %s", e)


def _is_owner(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else None
    return uid == TELEGRAM_USER_ID


def _esc(s: str) -> str:
    return html_lib.escape(s or "")


def _vacancy_message(v, summary) -> tuple[str, InlineKeyboardMarkup]:
    if not isinstance(summary, dict):
        summary = {}
    salary_line = f"💰 <b>{_esc(v.salary)}</b>\n" if v.salary and v.salary not in ("не указана", "не указан") else ""

    text = (
        f"🆕 <b>{_esc(v.title)}</b>\n"
        f"🏢 {_esc(v.company)}\n"
        f"{salary_line}"
        f"\n"
        f"📋 <b>Стек:</b> {_esc(str(summary.get('stack', '—')))}\n"
        f"🎯 <b>Опыт:</b> {_esc(str(summary.get('experience', '—')))}\n"
        f"💼 <b>Условия:</b> {_esc(str(summary.get('conditions', '—')))}\n"
        f"🏭 <b>Компания:</b> {_esc(str(summary.get('company_about', '—')))}\n"
        f"\n"
        f"🔗 <a href='{_esc(v.url)}'>Открыть вакансию</a>"
    )
    buttons = [
        [InlineKeyboardButton("✍️ Написать сопроводительное", callback_data=f"letter:{v.id}")],
        [InlineKeyboardButton("📤 Откликнуться", url=v.url)],
    ]
    if WEBAPP_PUBLIC_URL:
        buttons.append([
            InlineKeyboardButton("📱 Открыть в приложении", web_app=WebAppInfo(url=WEBAPP_PUBLIC_URL))
        ])
    return text, InlineKeyboardMarkup(buttons)


async def _sender_worker(app: Application) -> None:
    while True:
        try:
            item = await _send_queue.get()
            text, markup = item
            try:
                await app.bot.send_message(
                    chat_id=TELEGRAM_USER_ID,
                    text=text,
                    reply_markup=markup,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            except Exception as e:
                logger.error("Send failed: %s", e)
            finally:
                _send_queue.task_done()
            await asyncio.sleep(MESSAGE_DELAY_SECONDS)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Sender worker error: %s", e)


async def check_vacancies(app: Application) -> None:
    logger.info("Checking vacancies...")

    tasks: dict[str, asyncio.Task] = {}
    tasks["hh"] = asyncio.create_task(_safe_fetch(hh_parser, "hh"))
    tasks["habr"] = asyncio.create_task(_safe_fetch(habr_parser, "habr"))
    tasks["djinni"] = asyncio.create_task(_safe_fetch(djinni_parser, "djinni"))
    tasks["surf"] = asyncio.create_task(_safe_fetch(surf_parser, "surf"))
    tasks["yandex"] = asyncio.create_task(_safe_fetch(yandex_parser, "yandex"))
    if tg_parser.is_enabled():
        tasks["tg"] = asyncio.create_task(_safe_fetch(tg_parser, "tg"))
    if gmail_parser.is_enabled():
        tasks["gmail"] = asyncio.create_task(_safe_fetch(gmail_parser, "gmail"))

    batches = await asyncio.gather(*tasks.values())
    counts_by_source = dict(zip(tasks.keys(), (len(b) for b in batches)))
    all_vacancies = [v for batch in batches for v in batch]

    logger.info("Fetched: %s (total=%d)",
                ", ".join(f"{k}={v}" for k, v in counts_by_source.items()),
                len(all_vacancies))
    _track_source_health(app, counts_by_source)

    new_count = 0
    for v in all_vacancies:
        if db.is_seen(v.id):
            continue
        db.mark_seen(v.id, v.source, v.title, v.company, v.url,
                     salary=v.salary, description=v.description)
        _vacancies[v.id] = v

        summary = db.get_summary(v.id)
        if not summary:
            try:
                summary = await asyncio.to_thread(
                    ai.summarize_vacancy, v.title, v.company, v.description
                )
                db.save_summary(v.id, summary)
            except Exception as e:
                logger.error("Summary generation failed for %s: %s", v.id, e)
                summary = {"stack": "—", "experience": "—", "conditions": "—", "company_about": v.company}

        text, markup = _vacancy_message(v, summary)
        await _send_queue.put((text, markup))
        new_count += 1

    logger.info("Enqueued %d new vacancies (queue size: %d)", new_count, _send_queue.qsize())


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    text = (
        "🤖 <b>Chert Vacancy Bot</b>\n\n"
        "Присылаю новые Flutter-вакансии с HH.ru и Habr Career.\n\n"
        "/check — проверить прямо сейчас\n"
        "/app — открыть Mini App\n"
        "/status — статус бота"
    )
    markup = None
    if WEBAPP_PUBLIC_URL:
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("📱 Открыть приложение", web_app=WebAppInfo(url=WEBAPP_PUBLIC_URL))
        ]])
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=markup)


async def cmd_app(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    if not WEBAPP_PUBLIC_URL:
        await update.message.reply_text(
            "Mini App не настроен. Задай WEBAPP_PUBLIC_URL в .env (нужен HTTPS URL — используй cloudflared или ngrok)."
        )
        return
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("📱 Открыть приложение", web_app=WebAppInfo(url=WEBAPP_PUBLIC_URL))
    ]])
    await update.message.reply_text("Открыть Mini App:", reply_markup=markup)


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    await update.message.reply_text("Проверяю вакансии...")
    await check_vacancies(context.application)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    c = db.counts()
    await update.message.reply_text(
        f"<b>Chert Vacancy Bot</b>\n"
        f"Всего: {c['all']} · новых: {c['new']} · просмотрено: {c['viewed']} · ⭐ {c['starred']}\n"
        f"В очереди отправки: {_send_queue.qsize()}\n"
        f"Mini App: {'настроен' if WEBAPP_PUBLIC_URL else 'не настроен'}",
        parse_mode="HTML",
    )


async def on_letter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    vacancy_id = query.data.split(":", 1)[1]

    cached = db.get_letter(vacancy_id)
    if cached:
        await query.message.reply_text(cached)
        return

    v = _vacancies.get(vacancy_id)
    if not v:
        stored = db.get_vacancy(vacancy_id)
        if stored:
            class _V:
                pass
            v = _V()
            v.title = stored["title"]
            v.company = stored["company"]
            v.description = stored.get("description", "") or ""

    if not v:
        await query.message.reply_text(
            "Вакансия не найдена в БД.\nОткрой её вручную по ссылке."
        )
        return

    msg = await query.message.reply_text("Генерирую сопроводительное письмо...")
    try:
        letter = await asyncio.to_thread(
            ai.generate_cover_letter, v.title, v.company, v.description
        )
        db.save_letter(vacancy_id, letter)
        await msg.edit_text(letter)
    except Exception as e:
        logger.error("Letter generation error: %s", e)
        await msg.edit_text(f"Ошибка при генерации: {e}")


async def setup_menu_button(app: Application) -> None:
    """Настраивает Mini App кнопку в меню бота (иконка слева от поля ввода)."""
    if not WEBAPP_PUBLIC_URL:
        return
    try:
        await app.bot.set_chat_menu_button(
            chat_id=TELEGRAM_USER_ID,
            menu_button=MenuButtonWebApp(
                text="📱 Вакансии",
                web_app=WebAppInfo(url=WEBAPP_PUBLIC_URL),
            ),
        )
        logger.info("Menu button configured for Mini App")
    except Exception as e:
        logger.warning("Failed to set menu button: %s", e)


def setup_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("app", cmd_app))
    app.add_handler(CallbackQueryHandler(on_letter_callback, pattern=r"^letter:"))
