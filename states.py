from aiogram.fsm.state import State, StatesGroup


class SetPrice(StatesGroup):
    waiting_for_price = State()


class ManualBooking(StatesGroup):
    choosing_date = State()
    choosing_time = State()
    waiting_for_name = State()
    waiting_for_phone = State()


class Broadcast(StatesGroup):
    waiting_for_message = State()from aiogram.fsm.state import State, StatesGroup


class SetPrice(StatesGroup):
    waiting_for_price = State()


class ManualBooking(StatesGroup):
    choosing_date = State()
    choosing_time = State()
    waiting_for_name = State()
    waiting_for_phone = State()


class Broadcast(StatesGroup):
    waiting_for_message = State()
