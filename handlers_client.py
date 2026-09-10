# handlers_client.py
# Всі дії, доступні звичайному клієнту: перегляд вільних вікон, запис, скасування.

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove, KeyboardButton, ReplyKeyboardMarkup
from aiogram.filters import Command

import database as db
import keyboards as kb
from config import ADMIN_IDS

router = Router()
# Цей роутер обробляє повідомлення ТІЛЬКИ від звичайних клієнтів (не адмінів)
router.message.filter(~F.from_user.id.in_(ADMIN_IDS))
router.callback_query.filter(~F.from_user.id.in_(ADMIN_IDS))


def contact_request_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поділитись номером", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )


@router.message(Command("start"))
async def client_start(message: Message):
    if message.from_user.id in ADMIN_IDS:
        return  # адмінський /start обробляється в handlers_admin.py

    await db.add_or_update_client(message.from_user.id, message.from_user.full_name, message.from_user.username)

    await message.answer(
        f"Привіт, {message.from_user.first_name}! 👋\n\n"
        "Це бот для запису на стрижку.\n"
        "Онови, будь ласка, свій номер телефону — це допоможе барберу зв'язатись з тобою за потреби.",
        reply_markup=contact_request_keyboard()
    )
    await message.answer(
        "Обери дію в меню нижче 👇",
        reply_markup=kb.client_main_menu()
    )


@router.message(F.contact)
async def client_contact_shared(message: Message):
    if message.from_user.id in ADMIN_IDS:
        return
    await db.add_or_update_client(
        message.from_user.id,
        message.from_user.full_name,
        username=message.from_user.username,
        phone=message.contact.phone_number
    )
    await message.answer("Дякую! Номер збережено ✅", reply_markup=kb.client_main_menu())


@router.message(F.text == "📅 Записатись")
async def client_show_dates(message: Message):
    if message.from_user.id in ADMIN_IDS:
        return
    dates = await db.get_available_dates()
    if not dates:
        await message.answer("На жаль, наразі немає вільних дат для запису 😔")
        return
    await message.answer("Обери дату:", reply_markup=kb.dates_keyboard(dates, prefix="date"))


@router.callback_query(F.data.startswith("back_to_dates:date"))
async def client_back_to_dates(callback: CallbackQuery):
    dates = await db.get_available_dates()
    if not dates:
        await callback.message.edit_text("На жаль, вільних дат більше немає 😔")
        await callback.answer()
        return
    await callback.message.edit_text("Обери дату:", reply_markup=kb.dates_keyboard(dates, prefix="date"))
    await callback.answer()


@router.callback_query(F.data.startswith("date:"))
async def client_show_times(callback: CallbackQuery):
    date_str = callback.data.split(":", 1)[1]
    times = await db.get_free_slots_for_date(date_str)
    if not times:
        await callback.answer("На цю дату вже немає вільних вікон 😔", show_alert=True)
        return
    await callback.message.edit_text(
        f"Вільні години на {kb.format_date_human(date_str)}:",
        reply_markup=kb.times_keyboard(date_str, times, prefix="date")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("time:"))
async def client_confirm_time(callback: CallbackQuery):
    _, date_str, time_str = callback.data.split(":", 2)
    price = await db.get_price()
    await callback.message.edit_text(
        f"Запис на {kb.format_date_human(date_str)} о {time_str}.\n"
        f"Вартість: {price:.0f} грн.\n\nПідтвердити запис?",
        reply_markup=kb.confirm_booking_keyboard(date_str, time_str)
    )
    await callback.answer()


@router.callback_query(F.data == "confirm_cancel")
async def client_cancel_confirmation(callback: CallbackQuery):
    await callback.message.edit_text("Запис скасовано. Обери іншу дату командою '📅 Записатись'.")
    await callback.answer()


@router.callback_query(F.data.startswith("confirm:"))
async def client_finalize_booking(callback: CallbackQuery, bot: Bot):
    _, date_str, time_str = callback.data.split(":", 2)
    user = callback.from_user

    success = await db.create_booking(
        date=date_str,
        time=time_str,
        telegram_id=user.id,
        client_name=user.full_name,
        username=user.username
    )

    if not success:
        await callback.message.edit_text(
            "На жаль, цей час щойно зайняли 😔 Обери, будь ласка, інший."
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        f"✅ Готово! Ти записаний(а) на {kb.format_date_human(date_str)} о {time_str}.\n"
        f"Нагадаю про запис за день і в день стрижки."
    )
    await callback.answer()

    # Миттєве сповіщення барберу
    contact = kb.format_client_contact(user.full_name, user.username, user.id)
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🆕 Новий запис!\n"
                f"Клієнт: {contact}\n"
                f"Дата: {kb.format_date_human(date_str)}\n"
                f"Час: {time_str}"
            )
        except Exception:
            pass


@router.message(F.text == "🗒 Мої записи")
async def client_my_bookings(message: Message):
    if message.from_user.id in ADMIN_IDS:
        return
    bookings = await db.get_client_bookings(message.from_user.id)
    if not bookings:
        await message.answer("У тебе немає активних записів.")
        return
    await message.answer(
        "Твої записи (натисни, щоб скасувати):",
        reply_markup=kb.my_bookings_keyboard(bookings)
    )


@router.callback_query(F.data.startswith("client_cancel:"))
async def client_cancel_booking(callback: CallbackQuery, bot: Bot):
    booking_id = int(callback.data.split(":")[1])
    booking = await db.get_booking_by_id(booking_id)

    if not booking:
        await callback.answer("Цей запис вже не існує.", show_alert=True)
        return

    _, date_str, time_str, telegram_id, client_name, phone, price, username = booking

    if telegram_id != callback.from_user.id:
        await callback.answer("Це не твій запис.", show_alert=True)
        return

    await db.cancel_booking(booking_id)
    await callback.message.edit_text(
        f"Запис на {kb.format_date_human(date_str)} о {time_str} скасовано."
    )
    await callback.answer()

    for admin_id in ADMIN_IDS:
        try:
            contact = kb.format_client_contact(client_name, username, telegram_id)
            await bot.send_message(
                admin_id,
                f"⚠️ Клієнт скасував запис\n"
                f"Клієнт: {contact}\n"
                f"Дата: {kb.format_date_human(date_str)}\n"
                f"Час: {time_str}"
            )
        except Exception:
            pass
