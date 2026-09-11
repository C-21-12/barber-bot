# handlers_admin.py
# Всі дії, доступні тільки барберу (адміну).

import asyncio
from datetime import datetime

from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

import database as db
import keyboards as kb
from config import ADMIN_IDS, BROADCAST_DELAY
from states import SetPrice, ManualBooking, Broadcast
from utils import esc, now, parse_int, today_str

router = Router()
# Всі обробники в цьому файлі спрацьовують ТІЛЬКИ для адмінів
router.message.filter(F.from_user.id.in_(ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))


def parse_date_input(text: str) -> str | None:
    """Приймає дату у форматі ДД.ММ.РРРР або РРРР-ММ-ДД, повертає РРРР-ММ-ДД або None."""
    text = (text or "").strip()
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_time_input(text: str) -> str | None:
    text = (text or "").strip().replace(".", ":")
    try:
        return datetime.strptime(text, "%H:%M").strftime("%H:%M")
    except ValueError:
        return None


async def _rate_limited_broadcast(bot: Bot, text: str) -> tuple[int, int]:
    """Розсилка всім клієнтам з паузою між повідомленнями.
    Без паузи Telegram віддає 429 приблизно після 30 повідомлень за секунду
    і тимчасово блокує бота."""
    clients = await db.get_all_clients()
    sent, failed = 0, 0
    for telegram_id, _name in clients:
        try:
            await bot.send_message(telegram_id, text)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(BROADCAST_DELAY)
    return sent, failed


# ---------- СТАРТ ----------

@router.message(Command("start"))
async def admin_start(message: Message, state: FSMContext):
    await state.clear()
    price = await db.get_price()
    upcoming = len(await db.get_all_upcoming_bookings())
    await message.answer(
        "👋 Вітаю! Це адмін-панель твого бота для запису клієнтів.\n\n"
        f"💰 Поточна ціна стрижки: <b>{price:.0f} грн</b>\n"
        f"🗓 Майбутніх записів: <b>{upcoming}</b>\n\n"
        "Обери дію в меню нижче 👇",
        reply_markup=kb.admin_main_menu()
    )


@router.message(StateFilter("*"), Command("cancel"))
async def admin_cancel_any(message: Message, state: FSMContext):
    if await state.get_state() is None:
        await message.answer("Нічого скасовувати.", reply_markup=kb.admin_main_menu())
        return
    await state.clear()
    await message.answer("Дію скасовано.", reply_markup=kb.admin_main_menu())


# ---------- ПЕРЕГЛЯД ВСІХ ЗАПИСІВ ----------

async def _send_bookings_dates(target, edit: bool):
    dates = await db.get_dates_with_bookings()
    if not dates:
        text = "Наразі немає жодного активного запису."
        await (target.edit_text(text) if edit else target.answer(text))
        return
    text = "Обери день, щоб подивитись або скасувати конкретний запис:"
    markup = kb.dates_keyboard(dates, prefix="admin_date")
    await (target.edit_text(text, reply_markup=markup) if edit
           else target.answer(text, reply_markup=markup))


@router.message(F.text == "📋 Всі записи")
async def admin_view_bookings(message: Message):
    dates = await db.get_dates_with_bookings()
    if not dates:
        await message.answer("Наразі немає жодного активного запису.")
        return

    text_lines = ["📋 <b>Актуальні записи</b>"]
    total = 0
    for date_str in dates:
        bookings = await db.get_bookings_for_date(date_str)
        text_lines.append(f"\n📅 <b>{kb.format_date_human(date_str)}</b>")
        for _id, time_str, client_name, phone, tg_id, username in bookings:
            total += 1
            contact = kb.format_client_contact(client_name, username, tg_id)
            phone_part = f", {esc(phone)}" if phone else ""
            text_lines.append(f"  • <b>{time_str}</b> — {contact}{phone_part}")
    text_lines.append(f"\nВсього записів: <b>{total}</b>")

    # Telegram не приймає повідомлення довші за 4096 символів — ріжемо на частини
    chunk = ""
    for line in text_lines:
        if len(chunk) + len(line) + 1 > 3500:
            await message.answer(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk.strip():
        await message.answer(chunk)

    await _send_bookings_dates(message, edit=False)


@router.callback_query(F.data == "admin_bookings_back")
async def admin_bookings_back(callback: CallbackQuery):
    await _send_bookings_dates(callback.message, edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_date:"))
async def admin_view_day_bookings(callback: CallbackQuery):
    date_str = callback.data.split(":", 1)[1][:10]
    bookings = await db.get_bookings_for_date(date_str)
    if not bookings:
        await callback.answer("На цей день записів немає.", show_alert=True)
        await _send_bookings_dates(callback.message, edit=True)
        return

    lines = [f"📅 <b>{kb.format_date_human(date_str)}</b>\n"]
    for _id, time_str, client_name, phone, tg_id, username in bookings:
        contact = kb.format_client_contact(client_name, username, tg_id)
        phone_part = f", {esc(phone)}" if phone else ""
        lines.append(f"• <b>{time_str}</b> — {contact}{phone_part}")
    lines.append("\nНатисни на запис, щоб його скасувати:")

    await callback.message.edit_text(
        "\n".join(lines), reply_markup=kb.admin_day_bookings_keyboard(bookings)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_cancel:"))
async def admin_cancel_booking(callback: CallbackQuery, bot: Bot):
    booking_id = parse_int(callback.data.split(":", 1)[1])
    if booking_id is None:
        await callback.answer("Некоректні дані запису.", show_alert=True)
        return

    booking = await db.get_booking_by_id(booking_id)
    if not booking:
        await callback.answer("Цей запис вже не існує.", show_alert=True)
        return

    _, date_str, time_str, telegram_id, client_name, _phone, _price, _username = booking
    if not await db.cancel_booking(booking_id):
        await callback.answer("Цей запис вже скасовано.", show_alert=True)
        return

    await callback.message.edit_text(
        f"❌ Запис {kb.format_date_human(date_str)} {time_str} "
        f"({esc(client_name) or 'клієнт'}) скасовано.\nСлот знову вільний для запису."
    )
    await callback.answer("Скасовано")

    if telegram_id:
        try:
            await bot.send_message(
                telegram_id,
                f"На жаль, твій запис на {kb.format_date_human(date_str)} о {time_str} "
                f"скасовано барбером. Вибач за незручності — можеш обрати інший час 🙏"
            )
        except Exception:
            pass


# ---------- СТАТИСТИКА ----------

@router.message(F.text == "📊 Статистика")
async def admin_stats(message: Message):
    s = await db.get_stats_overview()
    month_names_ua = [
        "січень", "лютий", "березень", "квітень", "травень", "червень",
        "липень", "серпень", "вересень", "жовтень", "листопад", "грудень"
    ]
    this_name = month_names_ua[now().month - 1]
    prev_name = month_names_ua[s["prev_month"] - 1]

    await message.answer(
        "📊 <b>Статистика</b>\n\n"
        f"<b>{this_name.capitalize()} {now().year}</b> (поточний місяць)\n"
        f"  • стрижок: {s['this_month'][0]}\n"
        f"  • заробіток: {s['this_month'][1]:.0f} грн\n\n"
        f"<b>{prev_name.capitalize()} {s['prev_year']}</b>\n"
        f"  • стрижок: {s['last_month'][0]}\n"
        f"  • заробіток: {s['last_month'][1]:.0f} грн\n\n"
        f"🗓 Записів на найближчі 7 днів: <b>{s['upcoming_week']}</b>\n"
        f"🗓 Всього майбутніх записів: <b>{s['upcoming_total']}</b>\n"
        f"👥 Клієнтів у базі: <b>{s['clients']}</b>",
        reply_markup=kb.admin_main_menu()
    )


# ---------- ЗАКРИТТЯ ДНЯ ----------

@router.message(F.text == "🚫 Закрити день")
async def admin_close_day_start(message: Message):
    dates = await db.get_all_dates_ahead()
    await message.answer(
        "Обери день, який хочеш закрити.\n"
        "Всі вільні вікна цього дня зникнуть, існуючі записи залишаться:",
        reply_markup=kb.dates_keyboard(dates, prefix="admin_close")
    )


@router.callback_query(F.data.startswith("admin_close:"))
async def admin_close_day_ask(callback: CallbackQuery):
    date_str = callback.data.split(":", 1)[1][:10]
    free = await db.get_free_slots_for_date(date_str)
    if not free:
        await callback.answer("На цей день і так немає вільних вікон.", show_alert=True)
        return
    await callback.message.edit_text(
        f"Закрити <b>{kb.format_date_human(date_str)}</b>?\n"
        f"Зникне вільних вікон: <b>{len(free)}</b>. Наявні записи залишаться.",
        reply_markup=kb.confirm_keyboard(
            f"admin_close_yes:{date_str}", "admin_close_no",
            yes_text="🚫 Так, закрити"
        )
    )
    await callback.answer()


@router.callback_query(F.data == "admin_close_no")
async def admin_close_day_abort(callback: CallbackQuery):
    await callback.message.edit_text("Добре, день не закрито.")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_close_yes:"))
async def admin_close_day_confirm(callback: CallbackQuery):
    date_str = callback.data.split(":", 1)[1][:10]
    closed = await db.close_day(date_str)
    await callback.message.edit_text(
        f"🚫 День <b>{kb.format_date_human(date_str)}</b> закрито (вікон: {closed}).\n"
        f"Існуючі записи збережено, нові вільні слоти клієнтам більше не показуються.\n"
        f"Передумав? Кнопка «🔓 Відкрити день»."
    )
    await callback.answer()


# ---------- ВІДКРИТТЯ ДНЯ ----------

@router.message(F.text == "🔓 Відкрити день")
async def admin_reopen_day_start(message: Message):
    closed = await db.get_closed_dates()
    if not closed:
        await message.answer(
            "Немає закритих днів чи слотів — усе відкрито.",
            reply_markup=kb.admin_main_menu()
        )
        return
    await message.answer(
        "Обери день, який хочеш відкрити знову.\n"
        "У дужках — скільки слотів зараз закрито:",
        reply_markup=kb.admin_reopen_dates_keyboard(closed)
    )


@router.callback_query(F.data.startswith("admin_reopen:"))
async def admin_reopen_day_confirm(callback: CallbackQuery):
    date_str = callback.data.split(":", 1)[1][:10]
    reopened = await db.reopen_day(date_str)
    if not reopened:
        await callback.answer("Цей день уже відкритий.", show_alert=True)
        return
    free = await db.get_free_slots_for_date(date_str)
    await callback.message.edit_text(
        f"🔓 День <b>{kb.format_date_human(date_str)}</b> знову відкрито "
        f"(знято закриттів: {reopened}).\n"
        f"Зараз вільних вікон для клієнтів: <b>{len(free)}</b>."
    )
    await callback.answer("Відкрито")


# ---------- ВСТАНОВЛЕННЯ ЦІНИ ----------

@router.message(F.text == "💰 Встановити ціну")
async def admin_set_price_start(message: Message, state: FSMContext):
    current = await db.get_price()
    await message.answer(
        f"Поточна ціна: <b>{current:.0f} грн</b>\n\n"
        "Напиши нову ціну (тільки число, наприклад 350).\n"
        "Щоб вийти — /cancel"
    )
    await state.set_state(SetPrice.waiting_for_price)


@router.message(StateFilter(SetPrice.waiting_for_price))
async def admin_set_price_finish(message: Message, state: FSMContext):
    try:
        new_price = float((message.text or "").strip().replace(",", "."))
    except ValueError:
        await message.answer("Це не схоже на число. Спробуй ще раз, наприклад: 350")
        return
    if new_price < 0 or new_price > 1_000_000:
        await message.answer("Ціна виглядає дивно. Введи число від 0 до 1 000 000.")
        return

    await db.set_price(new_price)
    await state.clear()

    clients = await db.count_clients()
    await message.answer(
        f"✅ Нову ціну встановлено: <b>{new_price:.0f} грн</b>",
        reply_markup=kb.admin_main_menu()
    )
    # Раніше розсилка про нову ціну йшла автоматично — навіть якщо адмін просто
    # виправляв одруківку. Тепер це окреме свідоме рішення.
    await message.answer(
        f"Повідомити про нову ціну всіх клієнтів ({clients})?",
        reply_markup=kb.confirm_keyboard(
            f"price_notify_yes:{new_price:.2f}", "price_notify_no",
            yes_text="📢 Так, розіслати", no_text="🔕 Ні, тихо"
        )
    )


@router.callback_query(F.data == "price_notify_no")
async def admin_price_notify_skip(callback: CallbackQuery):
    await callback.message.edit_text("Добре, клієнтам нічого не надсилав.")
    await callback.answer()


@router.callback_query(F.data.startswith("price_notify_yes:"))
async def admin_price_notify_send(callback: CallbackQuery, bot: Bot):
    try:
        price = float(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Некоректна ціна.", show_alert=True)
        return

    await callback.message.edit_text("📢 Розсилаю…")
    await callback.answer()
    sent, failed = await _rate_limited_broadcast(
        bot, f"ℹ️ Ціна на стрижку змінилась і тепер складає {price:.0f} грн."
    )
    await callback.message.answer(
        f"Розсилку завершено: надіслано {sent}, не вдалось {failed}.",
        reply_markup=kb.admin_main_menu()
    )


# ---------- РУЧНИЙ ЗАПИС КЛІЄНТА ----------

@router.message(F.text == "➕ Записати клієнта")
async def admin_manual_booking_start(message: Message, state: FSMContext):
    await message.answer(
        "Введи дату запису у форматі ДД.ММ.РРРР (наприклад 15.07.2026).\n"
        "Щоб вийти — /cancel"
    )
    await state.set_state(ManualBooking.choosing_date)


@router.message(StateFilter(ManualBooking.choosing_date))
async def admin_manual_booking_date(message: Message, state: FSMContext):
    date_str = parse_date_input(message.text)
    if not date_str:
        await message.answer("Невірний формат. Введи дату як 15.07.2026")
        return
    if date_str < today_str():
        await message.answer("Ця дата вже минула. Введи сьогоднішню або майбутню.")
        return
    await state.update_data(date=date_str)

    free = await db.get_free_slots_for_date(date_str)
    hint = ("Вільні вікна цього дня: " + ", ".join(free)) if free else "Вільних вікон цього дня немає."
    await message.answer(
        f"{kb.format_date_human(date_str)}. {hint}\n\n"
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
    name = (message.text or "").strip()
    if not name:
        await message.answer("Ім'я не може бути порожнім. Введи ще раз:")
        return
    await state.update_data(name=name[:100])
    await message.answer("Введи телефон клієнта (або напиши «-», якщо не потрібно):")
    await state.set_state(ManualBooking.waiting_for_phone)


@router.message(StateFilter(ManualBooking.waiting_for_phone))
async def admin_manual_booking_phone(message: Message, state: FSMContext):
    phone = (message.text or "").strip()
    if phone == "-":
        phone = None

    data = await state.get_data()
    date_str, time_str, name = data.get("date"), data.get("time"), data.get("name")
    await state.clear()

    if not (date_str and time_str and name):
        await message.answer(
            "Щось загубилось у процесі. Почни заново через «➕ Записати клієнта».",
            reply_markup=kb.admin_main_menu()
        )
        return

    # enforce_rules=False: барбер свідомо може записати клієнта поза графіком
    success, reason = await db.create_booking(
        date=date_str, time=time_str, telegram_id=None,
        client_name=name, phone=phone, enforce_rules=False
    )

    if not success:
        note = ("На цей день і час вже є запис." if reason == "taken"
                else "Не вдалось створити запис.")
        await message.answer(
            f"⚠️ {note} Спробуй ще раз через «➕ Записати клієнта».",
            reply_markup=kb.admin_main_menu()
        )
        return

    phone_part = f"\nТелефон: {esc(phone)}" if phone else ""
    await message.answer(
        f"✅ Записано: <b>{esc(name)}</b>\n"
        f"Дата: {kb.format_date_human(date_str)}\n"
        f"Час: {time_str}{phone_part}",
        reply_markup=kb.admin_main_menu()
    )


# ---------- ЗАКРИТТЯ ОКРЕМОГО СЛОТУ ----------

async def _send_close_slot_dates(target, edit: bool):
    dates_with_free = await db.get_available_dates()
    if not dates_with_free:
        text = "Немає дат із вільними слотами для закриття."
        await (target.edit_text(text) if edit else target.answer(text))
        return
    text = "Обери дату, в якій хочеш закрити конкретний слот:"
    markup = kb.dates_keyboard(dates_with_free, prefix="admin_close_slot_date")
    await (target.edit_text(text, reply_markup=markup) if edit
           else target.answer(text, reply_markup=markup))


@router.message(F.text == "🔒 Закрити слот")
async def admin_close_slot_start(message: Message):
    await _send_close_slot_dates(message, edit=False)


@router.callback_query(F.data == "admin_close_slot_back")
async def admin_close_slot_back(callback: CallbackQuery):
    await _send_close_slot_dates(callback.message, edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_close_slot_date:"))
async def admin_close_slot_choose_time(callback: CallbackQuery):
    date_str = callback.data.split(":", 1)[1][:10]
    free_times = await db.get_free_slots_for_date(date_str)
    if not free_times:
        await callback.answer("На цю дату вже немає вільних слотів.", show_alert=True)
        await _send_close_slot_dates(callback.message, edit=True)
        return
    await callback.message.edit_text(
        f"🗓 <b>{kb.format_date_human(date_str)}</b>\n"
        f"Обери час, який хочеш закрити:",
        reply_markup=kb.admin_close_slot_times_keyboard(date_str, free_times)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_close_slot:"))
async def admin_close_slot_confirm(callback: CallbackQuery):
    parts = callback.data.split(":", 2)
    if len(parts) != 3:
        await callback.answer("Некоректні дані слота.", show_alert=True)
        return
    _, date_str, time_str = parts

    if not await db.close_slot(date_str, time_str):
        await callback.answer(
            "Слот зайнятий клієнтом або вже закритий — закрити не можна.", show_alert=True
        )
        return

    free_left = await db.get_free_slots_for_date(date_str)
    if free_left:
        await callback.message.edit_text(
            f"🔒 Слот <b>{kb.format_date_human(date_str)} о {time_str}</b> закрито.\n"
            f"Лишилось вільних вікон цього дня: {len(free_left)}. Закрити ще один?",
            reply_markup=kb.admin_close_slot_times_keyboard(date_str, free_left)
        )
    else:
        await callback.message.edit_text(
            f"🔒 Слот <b>{kb.format_date_human(date_str)} о {time_str}</b> закрито.\n"
            f"Вільних вікон цього дня більше немає."
        )
    await callback.answer("Закрито")


# ---------- ДОВІЛЬНА РОЗСИЛКА ----------

@router.message(F.text == "📢 Розсилка")
async def admin_broadcast_start(message: Message, state: FSMContext):
    clients = await db.count_clients()
    if not clients:
        await message.answer(
            "У базі поки немає жодного клієнта для розсилки.",
            reply_markup=kb.admin_main_menu()
        )
        return
    await message.answer(
        f"Напиши текст повідомлення для всіх клієнтів ({clients}).\n"
        "Щоб скасувати — /cancel"
    )
    await state.set_state(Broadcast.waiting_for_message)


@router.message(StateFilter(Broadcast.waiting_for_message))
async def admin_broadcast_preview(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Розсилка підтримує лише текстові повідомлення. Напиши текст:")
        return

    text = message.text.strip()
    if len(text) > 3500:
        await message.answer("Занадто довго (максимум 3500 символів). Скороти текст:")
        return

    await state.update_data(text=text)
    await state.set_state(Broadcast.confirming)

    clients = await db.count_clients()
    await message.answer(
        "Ось як це побачать клієнти:\n\n"
        f"<blockquote>{esc(text)}</blockquote>\n\n"
        f"Надіслати {clients} клієнтам?",
        reply_markup=kb.confirm_keyboard(
            "bcast_yes", "bcast_no", yes_text="📢 Надіслати", no_text="❌ Скасувати"
        )
    )


@router.callback_query(StateFilter(Broadcast.confirming), F.data == "bcast_no")
async def admin_broadcast_abort(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Розсилку скасовано.")
    await callback.answer()


@router.callback_query(StateFilter(Broadcast.confirming), F.data == "bcast_yes")
async def admin_broadcast_send(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    text = data.get("text")
    await state.clear()

    if not text:
        await callback.message.edit_text("Текст загубився. Почни розсилку заново.")
        await callback.answer()
        return

    await callback.message.edit_text("📢 Розсилаю…")
    await callback.answer()

    # Текст адміна відправляємо екранованим: parse_mode=HTML увімкнений глобально,
    # і будь-який '<' у звичайному тексті інакше зламав би всю розсилку.
    sent, failed = await _rate_limited_broadcast(bot, esc(text))
    await callback.message.answer(
        f"✅ Розсилку завершено.\nНадіслано: {sent}\nНе вдалось: {failed}",
        reply_markup=kb.admin_main_menu()
    )


# ---------- ПІДКАЗКА НА НЕЗРОЗУМІЛИЙ ТЕКСТ ----------

@router.message(F.text)
async def admin_fallback(message: Message):
    await message.answer(
        "Не зрозумів 🤔 Скористайся кнопками меню нижче.",
        reply_markup=kb.admin_main_menu()
    )
