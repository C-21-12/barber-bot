# scheduler.py
# Фонові завдання за розкладом: нагадування клієнтам і місячна аналітика барберу.

import asyncio
import logging
from datetime import timedelta

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import database as db
import keyboards as kb
from config import ADMIN_IDS, TIMEZONE, BROADCAST_DELAY
from utils import now

logger = logging.getLogger(__name__)

MONTH_NAMES_UA = [
    "січень", "лютий", "березень", "квітень", "травень", "червень",
    "липень", "серпень", "вересень", "жовтень", "листопад", "грудень"
]


async def send_daily_reminders(bot: Bot):
    """Запускається щодня о 9:00. Надсилає:
    - нагадування за день до запису (тим, у кого стрижка завтра)
    - нагадування в день запису (тим, у кого стрижка сьогодні)
    """
    today = now()
    today_s = today.strftime("%Y-%m-%d")
    tomorrow_s = (today + timedelta(days=1)).strftime("%Y-%m-%d")

    # За день до запису
    day_before = await db.get_bookings_needing_day_before_reminder(tomorrow_s)
    for booking_id, date_str, time_str, telegram_id in day_before:
        try:
            await bot.send_message(
                telegram_id,
                f"🔔 Нагадування: завтра, {kb.format_date_human(date_str)}, "
                f"о {time_str} у тебе запис на стрижку!"
            )
            await db.mark_day_before_notified(booking_id)
        except Exception as e:
            logger.warning("Не вдалось нагадати (за день) %s: %s", telegram_id, e)
        await asyncio.sleep(BROADCAST_DELAY)

    # В день запису
    same_day = await db.get_bookings_needing_same_day_reminder(today_s)
    for booking_id, date_str, time_str, telegram_id in same_day:
        try:
            await bot.send_message(
                telegram_id,
                f"🔔 Нагадування: сьогодні о {time_str} у тебе запис на стрижку!"
            )
            await db.mark_same_day_notified(booking_id)
        except Exception as e:
            logger.warning("Не вдалось нагадати (в день) %s: %s", telegram_id, e)
        await asyncio.sleep(BROADCAST_DELAY)

    logger.info("Нагадування: за день %s, сьогодні %s", len(day_before), len(same_day))


async def send_daily_agenda(bot: Bot):
    """Запускається щодня о 9:00 — барберу приходить план на сьогодні."""
    today_s = now().strftime("%Y-%m-%d")
    bookings = await db.get_bookings_for_date(today_s)
    if not bookings:
        text = f"🗓 {kb.format_date_human(today_s)}: записів на сьогодні немає."
    else:
        lines = [f"🗓 <b>План на {kb.format_date_human(today_s)}</b> ({len(bookings)}):", ""]
        for _id, time_str, client_name, phone, tg_id, username in bookings:
            contact = kb.format_client_contact(client_name, username, tg_id)
            lines.append(f"• <b>{time_str}</b> — {contact}")
        text = "\n".join(lines)

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception as e:
            logger.warning("Не вдалось надіслати план дня %s: %s", admin_id, e)


async def send_monthly_analytics(bot: Bot):
    """Запускається 1-го числа кожного місяця. Надсилає барберу статистику за попередній місяць."""
    today = now()
    first_of_this_month = today.replace(day=1)
    last_month_date = first_of_this_month - timedelta(days=1)
    year, month = last_month_date.year, last_month_date.month

    count, total = await db.get_monthly_stats(year, month)
    month_name = MONTH_NAMES_UA[month - 1]

    text = (
        f"📊 <b>Аналітика за {month_name} {year}</b>\n\n"
        f"Кількість стрижок: {count}\n"
        f"Загальний заробіток: {total:.0f} грн"
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception as e:
            logger.warning("Не вдалось надіслати аналітику %s: %s", admin_id, e)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    # Щодня о 9:00 — нагадування клієнтам
    scheduler.add_job(
        send_daily_reminders,
        CronTrigger(hour=9, minute=0, timezone=TIMEZONE),
        args=[bot],
        id="daily_reminders",
        replace_existing=True
    )

    # Щодня о 9:05 — план дня барберу
    scheduler.add_job(
        send_daily_agenda,
        CronTrigger(hour=9, minute=5, timezone=TIMEZONE),
        args=[bot],
        id="daily_agenda",
        replace_existing=True
    )

    # 1-го числа щомісяця о 9:10 — аналітика за попередній місяць
    scheduler.add_job(
        send_monthly_analytics,
        CronTrigger(day=1, hour=9, minute=10, timezone=TIMEZONE),
        args=[bot],
        id="monthly_analytics",
        replace_existing=True
    )

    return scheduler
