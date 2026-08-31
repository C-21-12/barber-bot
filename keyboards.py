# keyboards.py
# Тут зібрані функції, що будують клавіатури (звичайні і inline).

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from datetime import datetime

WEEKDAYS_UA = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]


def format_date_human(date_str: str) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{d.strftime('%d.%m')} ({WEEKDAYS_UA[d.weekday()]})"


def format_client_contact(client_name: str, username: str = None, telegram_id: int = None) -> str:
    """Формує рядок з контактом клієнта: ім'я + @username (якщо є) + пряме посилання на профіль.
    Посилання tg://user?id=... працює навіть якщо у клієнта немає username."""
    parts = [client_name or "клієнт"]
    if username:
        parts.append(f"@{username}")
    if telegram_id:
        parts.append(f'<a href="tg://user?id={telegram_id}">написати</a>')
    return " — ".join(parts)


# ---------- КЛІЄНТСЬКІ КЛАВІАТУРИ ----------

def client_main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Записатись")],
            [KeyboardButton(text="🗒 Мої записи")],
        ],
        resize_keyboard=True
    )


def dates_keyboard(dates: list[str], prefix: str) -> InlineKeyboardMarkup:
    """prefix визначає, куди піде callback: 'date' для клієнта, 'admin_date' для адміна тощо."""
    buttons = []
    row = []
    for i, date_str in enumerate(dates, start=1):
        row.append(InlineKeyboardButton(text=format_date_human(date_str), callback_data=f"{prefix}:{date_str}"))
        if i % 3 == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def times_keyboard(date_str: str, times: list[str], prefix: str) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for i, t in enumerate(times, start=1):
        row.append(InlineKeyboardButton(text=t, callback_data=f"{prefix}:{date_str}:{t}"))
        if i % 4 == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="⬅️ Назад до дат", callback_data=f"back_to_dates:{prefix}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def confirm_booking_keyboard(date_str: str, time_str: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Підтвердити запис", callback_data=f"confirm:{date_str}:{time_str}"),
        InlineKeyboardButton(text="❌ Скасувати", callback_data="confirm_cancel")
    ]])


def my_bookings_keyboard(bookings: list) -> InlineKeyboardMarkup:
    """bookings: список (id, date, time)"""
    buttons = []
    for booking_id, date_str, time_str in bookings:
        text = f"❌ {format_date_human(date_str)} {time_str}"
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"client_cancel:{booking_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ---------- АДМІНСЬКІ КЛАВІАТУРИ ----------

def admin_main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Всі записи")],
            [KeyboardButton(text="➕ Записати клієнта"), KeyboardButton(text="🚫 Закрити день")],
            [KeyboardButton(text="💰 Встановити ціну")],
        ],
        resize_keyboard=True
    )


def admin_day_bookings_keyboard(bookings: list) -> InlineKeyboardMarkup:
    """bookings: список (id, time, client_name, phone, telegram_id, username)"""
    buttons = []
    for booking_id, time_str, client_name, phone, tg_id, username in bookings:
        label = f"❌ {time_str} — {client_name or 'клієнт'}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"admin_cancel:{booking_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
