# utils.py
# Дрібні спільні хелпери: час у правильному поясі та екранування HTML.

import html
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import TIMEZONE

TZ = ZoneInfo(TIMEZONE)


def now() -> datetime:
    """Поточний час у робочому часовому поясі (а не в поясі сервера).
    Раніше всюди був datetime.now(), і на сервері в UTC 'сьогодні' не збігалося
    з 'сьогодні' у планувальнику — дати роз'їжджалися на кілька годин."""
    return datetime.now(TZ)


def today_str() -> str:
    return now().strftime("%Y-%m-%d")


def date_str_offset(days: int) -> str:
    return (now() + timedelta(days=days)).strftime("%Y-%m-%d")


def esc(text) -> str:
    """Екранує текст перед вставкою в повідомлення з parse_mode=HTML.
    Ім'я клієнта в Telegram — довільний рядок, і без екранування в нього
    можна засунути <a href=...> або зламати розмітку повідомлення.

    quote=True — лапки теж екрануємо, щоб у тексті не лишалось нічого схожого
    на атрибут тега."""
    if text is None:
        return ""
    return html.escape(str(text), quote=True)


def slot_dt(date_str: str, time_str: str) -> datetime | None:
    """Дата+час слота як aware-datetime у робочому поясі, або None якщо формат битий."""
    try:
        return datetime.strptime(
            f"{str(date_str)[:10]} {time_str}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=TZ)
    except (ValueError, TypeError):
        return None


def hours_until(date_str: str, time_str: str) -> float | None:
    """Скільки годин лишилось до слота. None — якщо дату не вдалось розібрати."""
    dt = slot_dt(date_str, time_str)
    if dt is None:
        return None
    return (dt - now()).total_seconds() / 3600


def parse_int(raw: str) -> int | None:
    """Безпечний int() для даних з callback_data."""
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
