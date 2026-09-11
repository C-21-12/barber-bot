# database.py
# Весь код роботи з базою даних SQLite зібраний тут.
# Використовуємо aiosqlite, щоб не блокувати бота під час запитів до БД.

import aiosqlite
from datetime import datetime, timedelta
from config import DB_PATH, WORK_SCHEDULE, SLOT_MINUTES, DAYS_AHEAD


async def init_db():
    """Створює таблиці, якщо їх ще немає. Викликається один раз при старті бота."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                telegram_id INTEGER PRIMARY KEY,
                name TEXT,
                username TEXT,
                phone TEXT,
                created_at TEXT
            )
        """)
        cursor = await db.execute("PRAGMA table_info(clients)")
        columns = [row[1] for row in await cursor.fetchall()]
        if "username" not in columns:
            await db.execute("ALTER TABLE clients ADD COLUMN username TEXT")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,        -- формат YYYY-MM-DD
                time TEXT NOT NULL,        -- формат HH:MM
                telegram_id INTEGER,       -- NULL, якщо запис зробив сам адмін без клієнта в Telegram
                client_name TEXT,
                username TEXT,             -- Telegram username клієнта (без @), може бути NULL
                phone TEXT,
                price REAL,
                created_at TEXT,
                notified_day_before INTEGER DEFAULT 0,
                notified_same_day INTEGER DEFAULT 0,
                UNIQUE(date, time)
            )
        """)
        # Міграція: якщо таблиця bookings вже існувала без колонки username — додаємо її
        cursor = await db.execute("PRAGMA table_info(bookings)")
        columns = [row[1] for row in await cursor.fetchall()]
        if "username" not in columns:
            await db.execute("ALTER TABLE bookings ADD COLUMN username TEXT")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS closed_slots (
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                UNIQUE(date, time)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        # Ціна за замовчуванням, якщо ще не встановлена
        await db.execute("""
            INSERT OR IGNORE INTO settings (key, value) VALUES ('price', '0')
        """)
        await db.commit()


# ---------- НАЛАШТУВАННЯ (ЦІНА) ----------

async def get_price() -> float:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = 'price'")
        row = await cursor.fetchone()
        return float(row[0]) if row else 0.0


async def set_price(new_price: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES ('price', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(new_price),)
        )
        await db.commit()


# ---------- КЛІЄНТИ ----------

async def add_or_update_client(telegram_id: int, name: str, username: str = None, phone: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO clients (telegram_id, name, username, phone, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                name = excluded.name,
                username = excluded.username,
                phone = COALESCE(excluded.phone, clients.phone)
        """, (telegram_id, name, username, phone, datetime.now().isoformat()))
        await db.commit()


async def get_all_clients():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT telegram_id, name FROM clients")
        return await cursor.fetchall()


# ---------- ГЕНЕРАЦІЯ СЛОТІВ ----------

def _generate_day_slots(date_obj: datetime) -> list[str]:
    """Повертає список часів (HH:MM) слотів для конкретної дати, згідно графіка."""
    weekday = date_obj.weekday()
    if weekday not in WORK_SCHEDULE:
        return []

    start_str, end_str = WORK_SCHEDULE[weekday]
    start_time = datetime.strptime(start_str, "%H:%M")
    end_time = datetime.strptime(end_str, "%H:%M")

    slots = []
    current = start_time
    while current <= end_time:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=SLOT_MINUTES)
    return slots


async def get_free_slots_for_date(date_str: str) -> list[str]:
    """Вільні слоти для клієнтів на конкретну дату (виключає заброньовані та закриті)."""
    # Обрізаємо до YYYY-MM-DD на випадок якщо прийшов рядок з часом
    date_str = date_str[:10]
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    all_slots = _generate_day_slots(date_obj)
    if not all_slots:
        return []

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT time FROM bookings WHERE date = ?", (date_str,))
        booked = {row[0] for row in await cursor.fetchall()}

        cursor = await db.execute("SELECT time FROM closed_slots WHERE date = ?", (date_str,))
        closed = {row[0] for row in await cursor.fetchall()}

    return [t for t in all_slots if t not in booked and t not in closed]


async def get_all_dates_ahead() -> list[str]:
    """Список усіх дат (наступні DAYS_AHEAD днів), незалежно від наявності вільних слотів.
    Потрібно адміну, наприклад, щоб закрити день."""
    today = datetime.now()
    return [(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(DAYS_AHEAD)]


async def get_available_dates() -> list[str]:
    """Список дат (наступні DAYS_AHEAD днів), на які є хоча б один вільний слот."""
    result = []
    today = datetime.now()
    for i in range(DAYS_AHEAD):
        d = today + timedelta(days=i)
        date_str = d.strftime("%Y-%m-%d")
        free = await get_free_slots_for_date(date_str)
        if free:
            result.append(date_str)
    return result


# ---------- БРОНЮВАННЯ ----------

async def create_booking(date: str, time: str, telegram_id: int = None,
                          client_name: str = "", username: str = None, phone: str = None) -> bool:
    """Створює запис. Повертає False, якщо слот вже зайнятий."""
    price = await get_price()
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO bookings (date, time, telegram_id, client_name, username, phone, price, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (date, time, telegram_id, client_name, username, phone, price, datetime.now().isoformat()))
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def cancel_booking(booking_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        await db.commit()
        return cursor.rowcount > 0


async def get_booking_by_id(booking_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, date, time, telegram_id, client_name, phone, price, username FROM bookings WHERE id = ?",
            (booking_id,)
        )
        return await cursor.fetchone()


async def get_client_bookings(telegram_id: int):
    """Майбутні записи конкретного клієнта."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT id, date, time FROM bookings
            WHERE telegram_id = ? AND date >= ?
            ORDER BY date, time
        """, (telegram_id, today_str))
        return await cursor.fetchall()


async def get_all_upcoming_bookings():
    """Всі майбутні записи — для перегляду адміном."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT id, date, time, client_name, phone, telegram_id FROM bookings
            WHERE date >= ?
            ORDER BY date, time
        """, (today_str,))
        return await cursor.fetchall()


async def get_dates_with_bookings() -> list[str]:
    """Дати (від сьогодні), на які є хоча б один активний запис."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT DISTINCT date FROM bookings WHERE date >= ? ORDER BY date
        """, (today_str,))
        return [row[0] for row in await cursor.fetchall()]


async def get_bookings_for_date(date_str: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT id, time, client_name, phone, telegram_id, username FROM bookings
            WHERE date = ? ORDER BY time
        """, (date_str,))
        return await cursor.fetchall()


# ---------- ЗАКРИТТЯ ДНЯ ----------

async def close_day(date_str: str):
    """Закриває всі ВІЛЬНІ слоти на день (заброньовані записи не чіпає)."""
    free_slots = await get_free_slots_for_date(date_str)
    if not free_slots:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        for t in free_slots:
            await db.execute(
                "INSERT OR IGNORE INTO closed_slots (date, time) VALUES (?, ?)",
                (date_str, t)
            )
        await db.commit()


async def close_slot(date_str: str, time_str: str) -> bool:
    """Закриває один конкретний вільний слот. Повертає False, якщо слот вже зайнятий або закритий."""
    # Перевіряємо, що слот справді вільний (не заброньований)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id FROM bookings WHERE date = ? AND time = ?", (date_str, time_str)
        )
        if await cursor.fetchone():
            return False  # слот заброньований клієнтом — не можна закрити
        try:
            await db.execute(
                "INSERT OR IGNORE INTO closed_slots (date, time) VALUES (?, ?)",
                (date_str, time_str)
            )
            await db.commit()
            return True
        except Exception:
            return False


async def reopen_day(date_str: str):
    """Знову відкриває день (прибирає позначки 'закрито' для вже минулих закриттів)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM closed_slots WHERE date = ?", (date_str,))
        await db.commit()


# ---------- НАГАДУВАННЯ ----------

async def get_bookings_needing_day_before_reminder(tomorrow_str: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT id, date, time, telegram_id FROM bookings
            WHERE date = ? AND telegram_id IS NOT NULL AND notified_day_before = 0
        """, (tomorrow_str,))
        return await cursor.fetchall()


async def get_bookings_needing_same_day_reminder(today_str: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT id, date, time, telegram_id FROM bookings
            WHERE date = ? AND telegram_id IS NOT NULL AND notified_same_day = 0
        """, (today_str,))
        return await cursor.fetchall()


async def mark_day_before_notified(booking_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE bookings SET notified_day_before = 1 WHERE id = ?", (booking_id,))
        await db.commit()


async def mark_same_day_notified(booking_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE bookings SET notified_same_day = 1 WHERE id = ?", (booking_id,))
        await db.commit()


# ---------- АНАЛІТИКА ----------

async def get_monthly_stats(year: int, month: int):
    """Повертає (кількість_стрижок, сума_заробітку) за конкретний місяць."""
    prefix = f"{year:04d}-{month:02d}"
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT COUNT(*), COALESCE(SUM(price), 0) FROM bookings
            WHERE date LIKE ?
        """, (f"{prefix}%",))
        row = await cursor.fetchone()
        return row[0], row[1]
                             
