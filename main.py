import asyncio
import logging
import re
from typing import Dict, List, Any

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiocryptopay import AioCryptoPay, Networks

# ================= НАСТРОЙКИ =================
TOKEN = "8644586406:AAE77FSG_ddArp7DnhkpMu8HtQy5SaqItgE"
ADMIN_ID = 8209617821
CRYPTO_TOKEN = "552977:AABwZSaXYMIl5cJIpPZgfGgE5tek7vHNaX4"

FREE_MODE = True
PRICE_USD = 2.58

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

crypto = AioCryptoPay(
    token=CRYPTO_TOKEN.strip(),
    network=Networks.MAIN_NET
)

router = Router()
dp.include_router(router)

# Список всех пользователей, которые взаимодействовали с ботом
all_users: set[int] = set()

pending_requests: List[Dict[str, Any]] = []

class RegForm(StatesGroup):
    operator = State()
    phone = State()

class AdminStates(StatesGroup):
    broadcast = State()
    search_phone = State()

# ================= КЛАВИАТУРЫ =================
def get_main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📞 Зарегистрировать номер")]],
        resize_keyboard=True
    )

def get_operators_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Activ"), KeyboardButton(text="Tele2"), KeyboardButton(text="Altel")],
            [KeyboardButton(text="← Назад")]
        ],
        resize_keyboard=True
    )

def get_admin_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📢 Рассылка всем")],
            [KeyboardButton(text="📋 Все заявки")],
            [KeyboardButton(text="🔍 Поиск по номеру")],
            [KeyboardButton(text="← Выйти из админки")]
        ],
        resize_keyboard=True
    )

# ================= ХЕНДЛЕРЫ =================
@router.message(CommandStart())
async def cmd_start(message: Message):
    all_users.add(message.chat.id)
    status = "🆓 ТЕСТОВЫЙ РЕЖИМ (БЕСПЛАТНО)" if FREE_MODE else f"💰 ЦЕНА: ${PRICE_USD} USDT"
    await message.answer(
        f"👋 Привет! Анонимная регистрация SIM.\n\n{status}",
        reply_markup=get_main_kb()
    )

@router.message(F.text.in_({"/admin", "админ", "admin"}))
async def admin_panel(message: Message):
    if message.chat.id != ADMIN_ID:
        return await message.answer("Доступ запрещён")
    await message.answer("🛠 Админ-панель", reply_markup=get_admin_kb())

@router.message(F.text == "← Выйти из админки")
async def exit_admin(message: Message):
    if message.chat.id != ADMIN_ID:
        return
    await message.answer("↩️ Обычный режим", reply_markup=get_main_kb())

# ───────────────────────────────────────────────
# Рассылка всем
# ───────────────────────────────────────────────
@router.message(F.text == "📢 Рассылка всем")
async def start_broadcast(message: Message, state: FSMContext):
    if message.chat.id != ADMIN_ID:
        return
    await message.answer(
        "Введите текст рассылки всем пользователям\n\n"
        "Для отмены напишите: отмена",
        reply_markup=None
    )
    await state.set_state(AdminStates.broadcast)

@router.message(AdminStates.broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    if message.chat.id != ADMIN_ID:
        return

    if message.text.lower() in {"отмена", "/отмена"}:
        await state.clear()
        await message.answer("Рассылка отменена", reply_markup=get_admin_kb())
        return

    text = message.text
    success = 0
    failed = 0

    for uid in list(all_users):
        try:
            await bot.send_message(uid, text)
            success += 1
        except:
            failed += 1

    await message.answer(
        f"Рассылка завершена\nУспешно: {success}\nНе удалось: {failed}\nВсего: {len(all_users)}",
        reply_markup=get_admin_kb()
    )
    await state.clear()

# ───────────────────────────────────────────────
# Все заявки
# ───────────────────────────────────────────────
@router.message(F.text == "📋 Все заявки")
async def show_all_requests(message: Message):
    if message.chat.id != ADMIN_ID:
        return

    if not pending_requests:
        return await message.answer("Заявок пока нет", reply_markup=get_admin_kb())

    lines = ["📋 Заявки:\n"]
    for r in pending_requests:
        emoji = {"waiting_pay": "💳", "waiting_sms": "🔑", "completed": "✅"}.get(r["status"], "❓")
        lines.append(
            f"#{r['id']} {emoji} {r['status']}\n"
            f"Юзер: {r['username']}\n"
            f"Номер: {r['phone']}\n"
            f"Оп: {r['operator']}\n"
            "───────────────\n"
        )

    text = "".join(lines)
    if len(text) > 3800:
        for i in range(0, len(text), 3800):
            await message.answer(text[i:i+3800])
    else:
        await message.answer(text or "Пусто", reply_markup=get_admin_kb())

# ───────────────────────────────────────────────
# Поиск по номеру
# ───────────────────────────────────────────────
@router.message(F.text == "🔍 Поиск по номеру")
async def start_search(message: Message, state: FSMContext):
    if message.chat.id != ADMIN_ID:
        return
    await message.answer(
        "Введите номер (или его часть) для поиска:\nПример: 747 или 77123\n\nОтмена → отмена",
        reply_markup=None
    )
    await state.set_state(AdminStates.search_phone)

@router.message(AdminStates.search_phone)
async def process_search(message: Message, state: FSMContext):
    if message.chat.id != ADMIN_ID:
        return

    if message.text.lower() in {"отмена", "/отмена"}:
        await state.clear()
        await message.answer("Поиск отменён", reply_markup=get_admin_kb())
        return

    query = re.sub(r"\D", "", message.text).strip()
    if not query:
        await message.answer("Ничего не введено. Попробуйте снова или отмена")
        return

    found = [r for r in pending_requests if query in r["phone"]]

    if not found:
        await message.answer(f"По '{query}' ничего не найдено", reply_markup=get_admin_kb())
    else:
        lines = [f"Найдено {len(found)}:\n"]
        for r in found:
            lines.append(
                f"#{r['id']} | {r['status']}\n"
                f"{r['username']}\n"
                f"{r['phone']} | {r['operator']}\n"
                "───────────────\n"
            )
        await message.answer("".join(lines), reply_markup=get_admin_kb())

    await state.clear()

# ───────────────────────────────────────────────
# Остальные хендлеры (регистрация, оплата, коды и т.д.)
# ───────────────────────────────────────────────
@router.message(F.text == "📞 Зарегистрировать номер")
async def start_reg(message: Message, state: FSMContext):
    all_users.add(message.chat.id)
    await state.clear()
    await message.answer("📊 Выбери оператора:", reply_markup=get_operators_kb())
    await state.set_state(RegForm.operator)