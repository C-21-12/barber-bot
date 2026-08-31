# scheduler.py
# Фонові завдання за розкладом: нагадування клієнтам і місячна аналітика барберу.

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta

import database as db
from config import ADMIN_IDS, TIMEZONE
import keyboards as kb


async def send_daily_reminders(bot: Bot):
    """Запускається щодня о 9:00. Надсилає:
    - нагадування за день до запису (тим, у кого стрижка завтра)
    - нагадування в день запису (тим, у кого стрижка сьогодні)
    """
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")
    tomorrow_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")

    # За день до запису
    day_before = await db.get_bookings_needing_day_before_reminder(tomorrow_str)
    for booking_id, date_str, time_str, telegram_id in day_before:
        try:
            await bot.send_message(
                telegram_id,
                f"🔔 Нагадування: завтра, {kb.format_date_human(date_str)}, "
                f"о {time_str} у тебе запис на стрижку!"
            )
            await db.mark_day_before_notified(booking_id)
        except Exception:
            pass

    # В день запису
    same_day = await db.get_bookings_needing_same_day_reminder(today_str)
    for booking_id, date_str, time_str, telegram_id in same_day:
        try:
            await bot.send_message(
                telegram_id,
                f"🔔 Нагадування: сьогодні о {time_str} у тебе запис на стрижку!"
            )
            await db.mark_same_day_notified(booking_id)
        except Exception:
            pass


async def send_monthly_analytics(bot: Bot):
    """Запускається 1-го числа кожного місяця. Надсилає барберу статистику за попередній місяць."""
    today = datetime.now()
    first_of_this_month = today.replace(day=1)
    last_month_date = first_of_this_month - timedelta(days=1)
    year, month = last_month_date.year, last_month_date.month

    count, total = await db.get_monthly_stats(year, month)

    month_names_ua = [
        "січень", "лютий", "березень", "квітень", "травень", "червень",
        "липень", "серпень", "вересень", "жовтень", "листопад", "грудень"
    ]
    month_name = month_names_ua[month - 1]

    text = (
        f"📊 Аналітика за {month_name} {year}:\n\n"
        f"Кількість стрижок: {count}\n"
        f"Загальний заробіток: {total:.0f} грн"
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            pass


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    # Щодня о 9:00 — нагадування
    scheduler.add_job(
        send_daily_reminders,
        CronTrigger(hour=9, minute=0, timezone=TIMEZONE),
        args=[bot],
        id="daily_reminders",
        replace_existing=True
    )

    # 1-го числа щомісяця о 9:05 — аналітика за попередній місяць
    scheduler.add_job(
        send_monthly_analytics,
        CronTrigger(day=1, hour=9, minute=5, timezone=TIMEZONE),
        args=[bot],
        id="monthly_analytics",
        replace_existing=True
    )

    return scheduler
