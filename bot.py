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
from aiogram.types import BotCommand, BotCommandScopeDefault

from config import BOT_TOKEN, ADMIN_IDS, DB_PATH
import database as db
import handlers_admin
import handlers_client
from scheduler import setup_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

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
        logger.info("Стару базу даних перенесено: %s -> %s", OLD_DB_PATH, DB_PATH)


async def set_commands(bot: Bot):
    """Список команд у синьому меню Telegram."""
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Головне меню"),
            BotCommand(command="help", description="Як користуватись ботом"),
        ],
        scope=BotCommandScopeDefault(),
    )


async def main():
    if BOT_TOKEN == "ВСТАВ_СЮДИ_СВІЙ_ТОКЕН" or not BOT_TOKEN:
        raise RuntimeError(
            "Не вказано BOT_TOKEN! Встанови змінну оточення BOT_TOKEN "
            "(токен, отриманий від @BotFather)."
        )
    if not ADMIN_IDS:
        raise RuntimeError(
            "Не вказано ADMIN_IDS! Встанови змінну оточення ADMIN_IDS "
            "(свій Telegram ID, можна дізнатись у @userinfobot)."
        )

    migrate_old_db_if_needed()
    await db.init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    # Порядок важливий: адмінський роутер першим, клієнтський — другим
    dp.include_router(handlers_admin.router)
    dp.include_router(handlers_client.router)

    scheduler = setup_scheduler(bot)

    # Все мережеві виклики — всередині try, щоб навіть при помилці на старті
    # (наприклад, неправильний токен) коректно закрити сесію і планувальник.
    try:
        me = await bot.get_me()
        await set_commands(bot)
        scheduler.start()
        logger.info("Бот @%s запущено. Натисни Ctrl+C, щоб зупинити.", me.username)
        # drop_pending_updates: після простою бот не відпрацьовує чергу старих натискань
        await dp.start_polling(bot, drop_pending_updates=True)
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        await bot.session.close()
        logger.info("Бот зупинено.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
