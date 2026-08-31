# handlers_admin.py
# Всі дії, доступні тільки барберу (адміну).

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from datetime import datetime

import database as db
import keyboards as kb
from config import ADMIN_IDS
from states import SetPrice, ManualBooking

router = Router()
# Всі обробники в цьому файлі спрацьовують ТІЛЬКИ для адмінів
router.message.filter(F.from_user.id.in_(ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))


def parse_date_input(text: str) -> str | None:
    """Приймає дату у форматі ДД.ММ.РРРР або РРРР-ММ-ДД, повертає РРРР-ММ-ДД або None."""
    text = text.strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_time_input(text: str) -> str | None:
    text = text.strip()
    try:
        return datetime.strptime(text, "%H:%M").strftime("%H:%M")
    except ValueError:
        return None


@router.message(Command("start"))
async def admin_start(message: Message):
    price = await db.get_price()
    await message.answer(
        "👋 Вітаю! Це адмін-панель твого бота для запису клієнтів.\n\n"
        f"Поточна ціна стрижки: {price:.0f} грн\n\n"
        "Обери дію в меню нижче 👇",
        reply_markup=kb.admin_main_menu()
    )


# ---------- ПЕРЕГЛЯД ВСІХ ЗАПИСІВ ----------

@router.message(F.text == "📋 Всі записи")
async def admin_view_bookings(message: Message):
    dates = await db.get_dates_with_bookings()
    if not dates:
        await message.answer("Наразі немає жодного активного запису.")
        return

    text_lines = ["📋 Актуальні записи:\n"]
    for date_str in dates:
        bookings = await db.get_bookings_for_date(date_str)
        text_lines.append(f"\n📅 {kb.format_date_human(date_str)}:")
        for _id, time_str, client_name, phone, tg_id, username in bookings:
            contact = kb.format_client_contact(client_name, username, tg_id)
            phone_part = f", {phone}" if phone else ""
            text_lines.append(f"  • {time_str} — {contact}{phone_part}")

    await message.answer("\n".join(text_lines))
    await message.answer(
        "Обери день, якщо хочеш скасувати конкретний запис:",
        reply_markup=kb.dates_keyboard(dates, prefix="admin_date")
    )


@router.callback_query(F.data.startswith("admin_date:"))
async def admin_view_day_bookings(callback: CallbackQuery):
    date_str = callback.data.split(":", 1)[1]
    bookings = await db.get_bookings_for_date(date_str)
    if not bookings:
        await callback.answer("На цей день записів немає.", show_alert=True)
        return
    await callback.message.edit_text(
        f"Записи на {kb.format_date_human(date_str)} (натисни, щоб скасувати):",
        reply_markup=kb.admin_day_bookings_keyboard(bookings)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_cancel:"))
async def admin_cancel_booking(callback: CallbackQuery, bot: Bot):
    booking_id = int(callback.data.split(":")[1])
    booking = await db.get_booking_by_id(booking_id)
    if not booking:
        await callback.answer("Цей запис вже не існує.", show_alert=True)
        return

    _, date_str, time_str, telegram_id, client_name, phone, price, username = booking
    await db.cancel_booking(booking_id)
    await callback.message.edit_text(
        f"❌ Запис {kb.format_date_human(date_str)} {time_str} ({client_name}) скасовано."
    )
    await callback.answer()

    if telegram_id:
        try:
            await bot.send_message(
                telegram_id,
                f"На жаль, твій запис на {kb.format_date_human(date_str)} о {time_str} "
                f"скасовано барбером. Вибач за незручності — можеш обрати інший час 🙏"
            )
        except Exception:
            pass


# ---------- ЗАКРИТТЯ ДНЯ ----------

@router.message(F.text == "🚫 Закрити день")
async def admin_close_day_start(message: Message):
    dates = await db.get_all_dates_ahead()
    await message.answer(
        "Обери день, який хочеш закрити (всі вільні вікна зникнуть, "
        "існуючі записи залишаться):",
        reply_markup=kb.dates_keyboard(dates, prefix="admin_close")
    )


@router.callback_query(F.data.startswith("admin_close:"))
async def admin_close_day_confirm(callback: CallbackQuery):
    date_str = callback.data.split(":", 1)[1]
    await db.close_day(date_str)
    await callback.message.edit_text(
        f"🚫 День {kb.format_date_human(date_str)} закрито. "
        f"Існуючі записи (якщо були) збережено, нові вільні слоти більше не показуються клієнтам."
    )
    await callback.answer()


# ---------- ВСТАНОВЛЕННЯ ЦІНИ ----------

@router.message(F.text == "💰 Встановити ціну")
async def admin_set_price_start(message: Message, state: FSMContext):
    current = await db.get_price()
    await message.answer(
        f"Поточна ціна: {current:.0f} грн.\nНапиши нову ціну (тільки число, наприклад 350):"
    )
    await state.set_state(SetPrice.waiting_for_price)


@router.message(StateFilter(SetPrice.waiting_for_price))
async def admin_set_price_finish(message: Message, state: FSMContext, bot: Bot):
    try:
        new_price = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("Це не схоже на число. Спробуй ще раз, наприклад: 350")
        return

    await db.set_price(new_price)
    await state.clear()
    await message.answer(f"✅ Нову ціну встановлено: {new_price:.0f} грн", reply_markup=kb.admin_main_menu())

    # Розсилка всім клієнтам про нову ціну
    clients = await db.get_all_clients()
    sent, failed = 0, 0
    for telegram_id, name in clients:
        try:
            await bot.send_message(
                telegram_id,
                f"ℹ️ Ціна на стрижку змінилась і тепер складає {new_price:.0f} грн."
            )
            sent += 1
        except Exception:
            failed += 1
    await message.answer(f"Розсилку завершено: надіслано {sent}, не вдалось {failed}.")


# ---------- РУЧНИЙ ЗАПИС КЛІЄНТА ----------

@router.message(F.text == "➕ Записати клієнта")
async def admin_manual_booking_start(message: Message, state: FSMContext):
    await message.answer(
        "Введи дату запису у форматі ДД.ММ.РРРР (наприклад 15.07.2026):"
    )
    await state.set_state(ManualBooking.choosing_date)


@router.message(StateFilter(ManualBooking.choosing_date))
async def admin_manual_booking_date(message: Message, state: FSMContext):
    date_str = parse_date_input(message.text)
    if not date_str:
        await message.answer("Невірний формат. Введи дату як 15.07.2026")
        return
    await state.update_data(date=date_str)
    await message.answer(
        "Введи час у форматі ГГ:ХХ (наприклад 18:20).\n"
        "Можна вказати будь-який час, навіть поза звичайним графіком."
    )
    await state.set_state(ManualBooking.choosing_time)


@router.message(StateFilter(ManualBooking.choosing_time))
async def admin_manual_booking_time(message: Message, state: FSMContext):
    time_str = parse_time_input(message.text)
    if not time_str:
        await message.answer("Невірний формат. Введи час як 18:20")
        return
    await state.update_data(time=time_str)
    await message.answer("Введи ім'я клієнта:")
    await state.set_state(ManualBooking.waiting_for_name)


@router.message(StateFilter(ManualBooking.waiting_for_name))
async def admin_manual_booking_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("Введи телефон клієнта (або напиши «-», якщо не потрібно):")
    await state.set_state(ManualBooking.waiting_for_phone)


@router.message(StateFilter(ManualBooking.waiting_for_phone))
async def admin_manual_booking_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    if phone == "-":
        phone = None

    data = await state.get_data()
    date_str, time_str, name = data["date"], data["time"], data["name"]

    success = await db.create_booking(
        date=date_str, time=time_str, telegram_id=None,
        client_name=name, phone=phone
    )
    await state.clear()

    if not success:
        await message.answer(
            "⚠️ На цей день і час вже є запис. Спробуй ще раз через «➕ Записати клієнта».",
            reply_markup=kb.admin_main_menu()
        )
        return

    await message.answer(
        f"✅ Записано: {name} на {kb.format_date_human(date_str)} о {time_str}.",
        reply_markup=kb.admin_main_menu()
    )
