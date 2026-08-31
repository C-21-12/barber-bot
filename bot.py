# bot.py
# Головний файл. Запускай саме його: python bot.py

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, ADMIN_IDS
import database as db
import handlers_admin
import handlers_client
from scheduler import setup_scheduler

logging.basicConfig(level=logging.INFO)


async def main():
    if BOT_TOKEN == "ВСТАВ_СЮДИ_СВІЙ_ТОКЕН" or not BOT_TOKEN:
        raise RuntimeError(
            "Не вказано BOT_TOKEN! Відкрий config.py (або встанови змінну оточення BOT_TOKEN) "
            "і встав токен, отриманий від @BotFather."
        )
    if not ADMIN_IDS:
        raise RuntimeError(
            "Не вказано ADMIN_IDS! Відкрий config.py (або встанови змінну оточення ADMIN_IDS) "
            "і встав свій Telegram ID (можна дізнатись у @userinfobot)."
        )

    await db.init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    # Порядок важливий: адмінський роутер першим, клієнтський — другим
    dp.include_router(handlers_admin.router)
    dp.include_router(handlers_client.router)

    scheduler = setup_scheduler(bot)
    scheduler.start()

    print("Бот запущено. Натисни Ctrl+C, щоб зупинити.")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
