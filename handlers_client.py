# handlers_client.py
# Всі дії, доступні звичайному клієнту: перегляд вільних вікон, запис, скасування.

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, KeyboardButton, ReplyKeyboardMarkup,
)

import database as db
import keyboards as kb
from config import (
    ADMIN_IDS, MAX_ACTIVE_BOOKINGS, CANCEL_DEADLINE_HOURS,
    WORK_SCHEDULE, SLOT_MINUTES,
)
from utils import esc, hours_until, parse_int

router = Router()
# Цей роутер обробляє повідомлення ТІЛЬКИ від звичайних клієнтів (не адмінів)
router.message.filter(~F.from_user.id.in_(ADMIN_IDS))
router.callback_query.filter(~F.from_user.id.in_(ADMIN_IDS))

# Тексти відмов при бронюванні — у одному місці, щоб хендлер лишався читабельним
BOOKING_ERRORS = {
    "taken": "На жаль, цей час щойно зайняли 😔 Обери, будь ласка, інший.",
    "closed": "Цей час уже недоступний — барбер закрив його. Обери інший, будь ласка.",
    "past": "Цей час уже минув 🕐 Обери, будь ласка, інший.",
    "not_in_schedule": "Такого часу немає в графіку. Обери час зі списку, будь ласка.",
    "limit": (
        f"У тебе вже {MAX_ACTIVE_BOOKINGS} активних записи(-ів) — це максимум.\n"
        "Скасуй один у розділі «🗒 Мої записи», щоб записатись на новий час."
    ),
}


def contact_request_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поділитись номером", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )


# ---------- СТАРТ ----------

@router.message(Command("start"))
async def client_start(message: Message):
    await db.add_or_update_client(
        message.from_user.id, message.from_user.full_name, message.from_user.username
    )

    await message.answer(
        f"Привіт, {esc(message.from_user.first_name)}! 👋\n\n"
        "Це бот для запису на стрижку.\n"
        "Онови, будь ласка, свій номер телефону — це допоможе барберу зв'язатись з тобою за потреби.",
        reply_markup=contact_request_keyboard()
    )
    await message.answer(
        "Обери дію в меню нижче 👇",
        reply_markup=kb.client_main_menu()
    )


@router.message(Command("help"))
async def client_help(message: Message):
    await message.answer(
        "ℹ️ <b>Як користуватись ботом</b>\n\n"
        "📅 <b>Записатись</b> — обери дату, потім вільний час і підтверди запис.\n"
        "🗒 <b>Мої записи</b> — подивитись або скасувати свій запис.\n"
        "💈 <b>Ціна та графік</b> — актуальна вартість і години роботи.\n\n"
        f"Одночасно можна мати до {MAX_ACTIVE_BOOKINGS} активних записів.\n"
        f"Скасувати самостійно можна не пізніше ніж за {CANCEL_DEADLINE_HOURS} год до стрижки.\n"
        "Нагадування прийде за день і в день запису.",
        reply_markup=kb.client_main_menu()
    )


@router.message(F.contact)
async def client_contact_shared(message: Message):
    await db.add_or_update_client(
        message.from_user.id,
        message.from_user.full_name,
        username=message.from_user.username,
        phone=message.contact.phone_number
    )
    await message.answer("Дякую! Номер збережено ✅", reply_markup=kb.client_main_menu())


# ---------- ЦІНА ТА ГРАФІК ----------

@router.message(F.text == "💈 Ціна та графік")
async def client_price_and_schedule(message: Message):
    price = await db.get_price()
    lines = [
        f"💰 Вартість стрижки: <b>{price:.0f} грн</b>",
        f"⏱ Тривалість: {SLOT_MINUTES} хв",
        "",
        "🗓 <b>Графік роботи:</b>",
    ]
    for day in range(7):
        name = kb.WEEKDAYS_UA_FULL[day].capitalize()
        if day in WORK_SCHEDULE:
            start, end = WORK_SCHEDULE[day]
            lines.append(f"  • {name}: {start} — {end}")
        else:
            lines.append(f"  • {name}: вихідний")
    await message.answer("\n".join(lines), reply_markup=kb.client_main_menu())


# ---------- ЗАПИС ----------

async def _send_dates(target, edit: bool):
    dates = await db.get_available_dates()
    if not dates:
        text = "На жаль, наразі немає вільних дат для запису 😔"
        await (target.edit_text(text) if edit else target.answer(text))
        return
    text = "Обери дату:"
    markup = kb.dates_keyboard(dates, prefix="date")
    await (target.edit_text(text, reply_markup=markup) if edit
           else target.answer(text, reply_markup=markup))


@router.message(F.text == "📅 Записатись")
async def client_show_dates(message: Message):
    await _send_dates(message, edit=False)


@router.callback_query(F.data == "back_to_dates")
async def client_back_to_dates(callback: CallbackQuery):
    await _send_dates(callback.message, edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith("date:"))
async def client_show_times(callback: CallbackQuery):
    date_str = callback.data.split(":", 1)[1][:10]
    times = await db.get_free_slots_for_date(date_str)
    if not times:
        await callback.answer("На цю дату вже немає вільних вікон 😔", show_alert=True)
        await _send_dates(callback.message, edit=True)
        return
    await callback.message.edit_text(
        f"🗓 <b>{kb.format_date_human(date_str)}</b>\nОбери вільний час:",
        reply_markup=kb.times_keyboard(date_str, times, prefix="time", back_data="back_to_dates")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("time:"))
async def client_confirm_time(callback: CallbackQuery):
    parts = callback.data.split(":", 2)
    if len(parts) != 3:
        await callback.answer("Щось пішло не так, спробуй ще раз.", show_alert=True)
        return
    _, date_str, time_str = parts

    price = await db.get_price()
    await callback.message.edit_text(
        "Перевір деталі запису:\n\n"
        f"🗓 Дата: <b>{kb.format_date_human(date_str)}</b>\n"
        f"🕐 Час: <b>{time_str}</b>\n"
        f"💰 Вартість: <b>{price:.0f} грн</b>\n\n"
        "Підтверджуємо?",
        reply_markup=kb.confirm_booking_keyboard(date_str, time_str)
    )
    await callback.answer()


@router.callback_query(F.data == "confirm_cancel")
async def client_cancel_confirmation(callback: CallbackQuery):
    await callback.message.edit_text(
        "Добре, запис не створено. Обрати інший час — кнопка «📅 Записатись» у меню."
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm:"))
async def client_finalize_booking(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split(":", 2)
    if len(parts) != 3:
        await callback.answer("Щось пішло не так, спробуй ще раз.", show_alert=True)
        return
    _, date_str, time_str = parts
    user = callback.from_user

    # Клієнта може не бути в таблиці clients, якщо він записується, не натиснувши /start
    await db.add_or_update_client(user.id, user.full_name, user.username)

    success, reason = await db.create_booking(
        date=date_str,
        time=time_str,
        telegram_id=user.id,
        client_name=user.full_name,
        username=user.username
    )

    if not success:
        await callback.answer(BOOKING_ERRORS.get(reason, "Не вдалось створити запис."), show_alert=True)
        await _send_dates(callback.message, edit=True)
        return

    await callback.message.edit_text(
        f"✅ <b>Готово!</b> Ти записаний(а) на {kb.format_date_human(date_str)} о {time_str}.\n\n"
        "Нагадаю про запис за день і в день стрижки.\n"
        "Плани змінились? Скасуй у розділі «🗒 Мої записи»."
    )
    await callback.answer("Записано ✅")

    # Миттєве сповіщення барберу
    contact = kb.format_client_contact(user.full_name, user.username, user.id)
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🆕 <b>Новий запис!</b>\n"
                f"Клієнт: {contact}\n"
                f"Дата: {kb.format_date_human(date_str)}\n"
                f"Час: {time_str}"
            )
        except Exception:
            pass


# ---------- МОЇ ЗАПИСИ ----------

async def _send_my_bookings(target, telegram_id: int, edit: bool):
    bookings = await db.get_client_bookings(telegram_id)
    if not bookings:
        text = "У тебе немає активних записів.\nНатисни «📅 Записатись», щоб обрати час."
        await (target.edit_text(text) if edit else target.answer(text))
        return
    text = f"🗒 Твої записи ({len(bookings)}). Натисни на запис, щоб побачити деталі:"
    markup = kb.my_bookings_keyboard(bookings)
    await (target.edit_text(text, reply_markup=markup) if edit
           else target.answer(text, reply_markup=markup))


@router.message(F.text == "🗒 Мої записи")
async def client_my_bookings(message: Message):
    await _send_my_bookings(message, message.from_user.id, edit=False)


@router.callback_query(F.data == "client_my_bookings")
async def client_my_bookings_back(callback: CallbackQuery):
    await _send_my_bookings(callback.message, callback.from_user.id, edit=True)
    await callback.answer()


async def _load_own_booking(callback: CallbackQuery):
    """Дістає запис з callback_data і перевіряє, що він належить саме цьому клієнту.
    Повертає None і сам відповідає користувачу, якщо щось не так."""
    booking_id = parse_int(callback.data.split(":", 1)[-1])
    if booking_id is None:
        await callback.answer("Некоректні дані запису.", show_alert=True)
        return None

    booking = await db.get_booking_by_id(booking_id)
    if not booking:
        await callback.answer("Цей запис вже не існує.", show_alert=True)
        await _send_my_bookings(callback.message, callback.from_user.id, edit=True)
        return None

    if booking[3] != callback.from_user.id:
        await callback.answer("Це не твій запис.", show_alert=True)
        return None

    return booking


@router.callback_query(F.data.startswith("client_booking:"))
async def client_booking_card(callback: CallbackQuery):
    booking = await _load_own_booking(callback)
    if not booking:
        return
    booking_id, date_str, time_str, _tg, _name, _phone, price, _username = booking

    left = hours_until(date_str, time_str)
    can_cancel = left is not None and left >= CANCEL_DEADLINE_HOURS

    text = (
        "🗓 <b>Твій запис</b>\n\n"
        f"Дата: <b>{kb.format_date_human(date_str)}</b>\n"
        f"Час: <b>{time_str}</b>\n"
        f"Вартість: <b>{(price or 0):.0f} грн</b>"
    )
    if not can_cancel:
        text += (
            f"\n\n⚠️ До запису лишилось менше {CANCEL_DEADLINE_HOURS} год — "
            "скасувати через бота вже не можна. Напиши барберу напряму."
        )
    await callback.message.edit_text(
        text, reply_markup=kb.client_booking_card_keyboard(booking_id, can_cancel)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("client_cancel:"))
async def client_cancel_ask(callback: CallbackQuery):
    booking = await _load_own_booking(callback)
    if not booking:
        return
    booking_id, date_str, time_str = booking[0], booking[1], booking[2]

    left = hours_until(date_str, time_str)
    if left is None or left < CANCEL_DEADLINE_HOURS:
        await callback.answer(
            f"До запису менше {CANCEL_DEADLINE_HOURS} год — скасувати через бота не можна.",
            show_alert=True
        )
        return

    await callback.message.edit_text(
        f"Точно скасувати запис на {kb.format_date_human(date_str)} о {time_str}?",
        reply_markup=kb.client_cancel_confirm_keyboard(booking_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("client_cancel_yes:"))
async def client_cancel_booking(callback: CallbackQuery, bot: Bot):
    booking = await _load_own_booking(callback)
    if not booking:
        return
    booking_id, date_str, time_str, telegram_id, client_name, _phone, _price, username = booking

    left = hours_until(date_str, time_str)
    if left is None or left < CANCEL_DEADLINE_HOURS:
        await callback.answer(
            f"До запису менше {CANCEL_DEADLINE_HOURS} год — скасувати через бота не можна.",
            show_alert=True
        )
        return

    if not await db.cancel_booking(booking_id):
        await callback.answer("Цей запис вже скасовано.", show_alert=True)
        await _send_my_bookings(callback.message, callback.from_user.id, edit=True)
        return

    await callback.message.edit_text(
        f"Запис на {kb.format_date_human(date_str)} о {time_str} скасовано.\n"
        "Записатись знову — кнопка «📅 Записатись»."
    )
    await callback.answer("Скасовано")

    contact = kb.format_client_contact(client_name, username, telegram_id)
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"⚠️ <b>Клієнт скасував запис</b>\n"
                f"Клієнт: {contact}\n"
                f"Дата: {kb.format_date_human(date_str)}\n"
                f"Час: {time_str}\n"
                f"Слот знову вільний."
            )
        except Exception:
            pass


# ---------- ПІДКАЗКА НА НЕЗРОЗУМІЛИЙ ТЕКСТ ----------

@router.message(F.text)
async def client_fallback(message: Message):
    await message.answer(
        "Не зрозумів 🤔 Скористайся кнопками меню нижче або напиши /help.",
        reply_markup=kb.client_main_menu()
    )
