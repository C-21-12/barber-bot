# bot.py
# Головний файл. Запускай саме його: python bot.py

import asyncio
import logging
import os
import shutil

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, ADMIN_IDS, DB_PATH
import database as db
import handlers_admin
import handlers_client
from scheduler import setup_scheduler

logging.basicConfig(level=logging.INFO)

# Шлях, де база лежала ДО того, як з'явився DB_PATH (наприклад, до підключення Volume).
# Якщо в новому місці (DB_PATH) бази ще немає, а стара база на цьому шляху існує —
# бот сам перенесе її, щоб не втратити дані клієнтів.
OLD_DB_PATH = "barber_bot.db"


def migrate_old_db_if_needed():
    if os.path.abspath(OLD_DB_PATH) == os.path.abspath(DB_PATH):
        return  # шлях не змінювався, міграція не потрібна
    if os.path.exists(DB_PATH):
        return  # у новому місці вже є база — нічого не робимо
    if os.path.exists(OLD_DB_PATH):
        target_dir = os.path.dirname(DB_PATH)
        if target_dir:
            os.makedirs(target_dir, exist_ok=True)
        shutil.copy2(OLD_DB_PATH, DB_PATH)
        print(f"Стару базу даних перенесено: {OLD_DB_PATH} → {DB_PATH}")


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

    migrate_old_db_if_needed()
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
