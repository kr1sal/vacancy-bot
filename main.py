import asyncio
import logging
import random

from telegram.ext import Application

from config import (
    BOT_TOKEN,
    CHECK_INTERVAL_MIN_SECONDS,
    CHECK_INTERVAL_MAX_SECONDS,
    WEBAPP_HOST,
    WEBAPP_PORT,
    WEBAPP_PUBLIC_URL,
)
import db
import bot as bot_module
from webapp.server import run_server

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def _polling_loop(app: Application) -> None:
    while True:
        try:
            await bot_module.check_vacancies(app)
        except Exception as e:
            logger.exception("check_vacancies failed: %s", e)

        delay = random.randint(CHECK_INTERVAL_MIN_SECONDS, CHECK_INTERVAL_MAX_SECONDS)
        logger.info("Next vacancy check in %d sec (~%.1f min)", delay, delay / 60)
        await asyncio.sleep(delay)


async def main() -> None:
    db.init_db()
    logger.info("DB initialized")

    app = Application.builder().token(BOT_TOKEN).build()
    bot_module.setup_handlers(app)

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    await bot_module.setup_menu_button(app)

    sender_task = asyncio.create_task(bot_module._sender_worker(app))
    polling_task = asyncio.create_task(_polling_loop(app))
    web_task = asyncio.create_task(run_server())

    logger.info("Chert Vacancy Bot started")
    logger.info("Web server: http://%s:%d", WEBAPP_HOST, WEBAPP_PORT)
    if WEBAPP_PUBLIC_URL:
        logger.info("Mini App URL: %s", WEBAPP_PUBLIC_URL)
    else:
        logger.info("Mini App: WEBAPP_PUBLIC_URL не задан — кнопка не появится")

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
    finally:
        polling_task.cancel()
        sender_task.cancel()
        web_task.cancel()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
