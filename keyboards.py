# keyboards.py
# Тут зібрані функції, що будують клавіатури (звичайні і inline).

from datetime import datetime

from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)

from utils import esc, now

WEEKDAYS_UA = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
WEEKDAYS_UA_FULL = [
    "понеділок", "вівторок", "середа", "четвер",
    "п{}ятниця".format(chr(39)), "субота", "неділя",
]


def format_date_human(date_str: str) -> str:
    """Дата у вигляді '12.09 (Пт)'. Сьогодні й завтра підписуємо словами —
    так у списку одразу видно найближчі дні."""
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return str(date_str)

    today = now().date()
    delta = (d.date() - today).days
    if delta == 0:
        return f"Сьогодні ({d.strftime('%d.%m')})"
    if delta == 1:
        return f"Завтра ({d.strftime('%d.%m')})"
    return f"{d.strftime('%d.%m')} ({WEEKDAYS_UA[d.weekday()]})"


def format_date_short(date_str: str) -> str:
    """Компактний підпис для кнопки: '12.09 Пт'."""
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return str(date_str)
    return f"{d.strftime('%d.%m')} {WEEKDAYS_UA[d.weekday()]}"


def format_client_contact(client_name: str, username: str = None, telegram_id: int = None) -> str:
    """Формує рядок з контактом клієнта: ім'я + @username (якщо є) + пряме посилання на профіль.
    Посилання tg://user?id=... працює навіть якщо у клієнта немає username.

    Ім'я обов'язково екранується: воно приходить з профілю Telegram, тобто його
    повністю контролює клієнт, а повідомлення адміну йдуть з parse_mode=HTML."""
    parts = [esc(client_name) or "клієнт"]
    if username:
        parts.append(f"@{esc(username)}")
    if telegram_id:
        parts.append(f'<a href="tg://user?id={int(telegram_id)}">написати</a>')
    return " — ".join(parts)


def _grid(buttons: list[InlineKeyboardButton], per_row: int) -> list[list[InlineKeyboardButton]]:
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


# ---------- КЛІЄНТСЬКІ КЛАВІАТУРИ ----------

def client_main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Записатись")],
            [KeyboardButton(text="🗒 Мої записи"), KeyboardButton(text="💈 Ціна та графік")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Обери дію в меню 👇",
    )


def dates_keyboard(dates: list[str], prefix: str, back_data: str = None) -> InlineKeyboardMarkup:
    """prefix визначає, куди піде callback: 'date' для клієнта, 'admin_date' для адміна тощо."""
    buttons = [
        InlineKeyboardButton(text=format_date_short(d), callback_data=f"{prefix}:{d}")
        for d in dates
    ]
    rows = _grid(buttons, 3)
    if back_data:
        rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=back_data)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def times_keyboard(date_str: str, times: list[str], prefix: str, back_data: str) -> InlineKeyboardMarkup:
    """prefix — куди піде callback при натисканні на час.
    Раніше сюди передавали той самий 'date', що й для вибору дати, тому натискання
    на час перехоплював хендлер вибору дати і записатись було неможливо взагалі."""
    buttons = [
        InlineKeyboardButton(text=t, callback_data=f"{prefix}:{date_str}:{t}")
        for t in times
    ]
    rows = _grid(buttons, 4)
    rows.append([InlineKeyboardButton(text="⬅️ Назад до дат", callback_data=back_data)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_booking_keyboard(date_str: str, time_str: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Підтвердити запис", callback_data=f"confirm:{date_str}:{time_str}")],
        [
            InlineKeyboardButton(text="⬅️ Інший час", callback_data=f"date:{date_str}"),
            InlineKeyboardButton(text="❌ Скасувати", callback_data="confirm_cancel"),
        ],
    ])


def my_bookings_keyboard(bookings: list) -> InlineKeyboardMarkup:
    """bookings: список (id, date, time). Натискання відкриває картку запису,
    а не скасовує одразу — щоб не зносити запис випадковим дотиком."""
    rows = [
        [InlineKeyboardButton(
            text=f"🗓 {format_date_human(date_str)} о {time_str}",
            callback_data=f"client_booking:{booking_id}",
        )]
        for booking_id, date_str, time_str in bookings
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def client_booking_card_keyboard(booking_id: int, can_cancel: bool) -> InlineKeyboardMarkup:
    rows = []
    if can_cancel:
        rows.append([InlineKeyboardButton(
            text="❌ Скасувати запис", callback_data=f"client_cancel:{booking_id}"
        )])
    rows.append([InlineKeyboardButton(text="⬅️ До моїх записів", callback_data="client_my_bookings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def client_cancel_confirm_keyboard(booking_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Так, скасувати", callback_data=f"client_cancel_yes:{booking_id}"),
        InlineKeyboardButton(text="⬅️ Ні, лишити", callback_data=f"client_booking:{booking_id}"),
    ]])


# ---------- АДМІНСЬКІ КЛАВІАТУРИ ----------

def admin_main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Всі записи"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="➕ Записати клієнта"), KeyboardButton(text="💰 Встановити ціну")],
            [KeyboardButton(text="🚫 Закрити день"), KeyboardButton(text="🔓 Відкрити день")],
            [KeyboardButton(text="🔒 Закрити слот"), KeyboardButton(text="📢 Розсилка")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Обери дію в меню 👇",
    )


def admin_close_slot_times_keyboard(date_str: str, free_times: list[str]) -> InlineKeyboardMarkup:
    """Клавіатура вільних слотів для закриття адміном."""
    return times_keyboard(date_str, free_times, prefix="admin_close_slot",
                          back_data="admin_close_slot_back")


def admin_day_bookings_keyboard(bookings: list) -> InlineKeyboardMarkup:
    """bookings: список (id, time, client_name, phone, telegram_id, username).
    Підпис кнопки — звичайний текст, не HTML, тому екранувати не треба,
    але обрізаємо довгі імена, щоб кнопка не розповзалася."""
    rows = []
    for booking_id, time_str, client_name, phone, tg_id, username in bookings:
        name = (client_name or "клієнт").strip()
        if len(name) > 24:
            name = name[:23] + "…"
        rows.append([InlineKeyboardButton(
            text=f"❌ {time_str} — {name}", callback_data=f"admin_cancel:{booking_id}"
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Назад до дат", callback_data="admin_bookings_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_reopen_dates_keyboard(closed: list[tuple[str, int]]) -> InlineKeyboardMarkup:
    """closed: список (date, скільки_закритих_слотів)."""
    buttons = [
        InlineKeyboardButton(
            text=f"{format_date_short(d)} ({cnt})", callback_data=f"admin_reopen:{d}"
        )
        for d, cnt in closed
    ]
    return InlineKeyboardMarkup(inline_keyboard=_grid(buttons, 2))


def confirm_keyboard(yes_data: str, no_data: str,
                     yes_text: str = "✅ Так", no_text: str = "❌ Ні") -> InlineKeyboardMarkup:
    """Універсальне 'ти впевнений?' для незворотних дій адміна."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=yes_text, callback_data=yes_data),
        InlineKeyboardButton(text=no_text, callback_data=no_data),
    ]])
