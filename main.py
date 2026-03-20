import asyncio
import json
import logging
import os
import tempfile
import re  # Добавлен для валидации
from pathlib import Path
from typing import Dict, List, Any

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================= НАСТРОЙКИ =================
TOKEN = "8623489996:AAE5rfYaS4JbAGrso_veeFALIsLagXx74s8"
ADMIN_ID = 8209617821

DATA_FILE = Path("bot_data.json")
logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# Глобальные данные
pending_requests: List[Dict[str, Any]] = []
users: set[int] = set()
request_counter: int = 0
data_lock = asyncio.Lock()

# ================= СОСТОЯНИЯ FSM =================
class RegForm(StatesGroup):
    operator = State()
    phone = State()

class AdminForm(StatesGroup):
    broadcast = State()
    search = State()

# ================= ФУНКЦИИ JSON =================
async def load_data():
    global pending_requests, users, request_counter
    if not DATA_FILE.exists():
        await save_data()
        return

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        pending_requests = data.get("pending_requests", [])
        users = set(data.get("users", []))
        request_counter = data.get("request_counter", 0)
        logging.info(f"Загружено {len(pending_requests)} заявок")
    except Exception as e:
        logging.error(f"Ошибка загрузки JSON: {e}")

async def save_data():
    async with data_lock:
        temp_path = Path(tempfile.NamedTemporaryFile(delete=False).name)
        try:
            data = {
                "pending_requests": pending_requests,
                "users": list(users),
                "request_counter": request_counter
            }
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            temp_path.replace(DATA_FILE)
        except Exception as e:
            logging.error(f"Ошибка сохранения: {e}")

# ================= КЛАВИАТУРЫ =================
def get_main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📞 Зарегистрировать SIM"), KeyboardButton(text="🆘 Поддержка")],
        ],
        resize_keyboard=True
    )

def get_operators_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Activ")],
            [KeyboardButton(text="Tele2")],
            [KeyboardButton(text="Altel")],
            [KeyboardButton(text="← Назад в меню")],
        ],
        resize_keyboard=True
    )

# ================= ХЕНДЛЕРЫ =================
@router.message(CommandStart())
async def cmd_start(message: Message):
    users.add(message.chat.id)
    await save_data()
    await message.answer("⚠️ Добро пожаловать в систему.\nВыбери действие:", reply_markup=get_main_kb())

@router.message(F.text == "🆘 Поддержка")
async def support_handler(message: Message):
    await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
    await message.answer("Запрос отправлен. Жди ответа.")

@router.message(F.text == "📞 Зарегистрировать SIM")
async def start_reg(message: Message, state: FSMContext):
    await message.answer("Выбери оператора:", reply_markup=get_operators_kb())
    await state.set_state(RegForm.operator)

@router.message(RegForm.operator, F.text.in_({"Activ", "Tele2", "Altel"}))
async def choose_operator(message: Message, state: FSMContext):
    await state.update_data(operator=message.text)
    await message.answer(f"Оператор: {message.text}\n\nВведи номер (например: 77071234567):")
    await state.set_state(RegForm.phone)

@router.message(RegForm.phone)
async def process_phone(message: Message, state: FSMContext):
    global request_counter
    
    # --- ВАЛИДАЦИЯ НОМЕРА ---
    raw_phone = re.sub(r"\D", "", message.text) # Убираем всё кроме цифр
    
    if len(raw_phone) == 11 and raw_phone.startswith("8"):
        raw_phone = "7" + raw_phone[1:] # Меняем 8 на 7
    
    if not re.match(r"^7\d{10}$", raw_phone):
        await message.answer("❌ Ошибка! Номер должен состоять из 11 цифр и начинаться на 7.\nПопробуй еще раз:")
        return

    phone_formatted = f"+{raw_phone}"

    # --- ПРОВЕРКА НА ДУБЛИКАТЫ ---
    if any(req['phone'] == phone_formatted for req in pending_requests):
        await message.answer(f"⚠️ Номер {phone_formatted} уже подавался на регистрацию!", reply_markup=get_main_kb())
        await state.clear()
        return

    data = await state.get_data()
    op = data.get("operator")

    request_counter += 1
    rid = request_counter

    pending_requests.append({
        "id": rid,
        "user_id": message.chat.id,
        "username": message.from_user.username or "без ника",
        "first_name": message.from_user.first_name,
        "operator": op,
        "phone": phone_formatted,
        "status": "pending",
        "created": int(asyncio.get_event_loop().time())
    })

    await message.answer(f"✅ Заявка #{rid} отправлена.\nОжидай решения.", reply_markup=get_main_kb())

    admin_text = (
        f"🆕 Заявка #{rid}\n"
        f"👤 {message.from_user.first_name} (@{message.from_user.username or 'нет'})\n"
        f"📶 {op}\n"
        f"📱 {phone_formatted}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Зарегистрировать", callback_data=f"reg_{rid}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"rej_{rid}")]
    ])

    await bot.send_message(ADMIN_ID, admin_text, reply_markup=kb)
    await state.clear()
    await save_data()

# [Далее идут остальные твои хендлеры: Command("admin"), CALLBACKS, generate_requests_list и т.д.]
# (Они остаются без изменений, просто добавь их ниже)

@router.message(F.text == "← Назад в меню")
async def back_to_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Главное меню", reply_markup=get_main_kb())

@router.message(Command("admin"))
async def admin_panel(message: Message):
    if message.chat.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Все заявки", callback_data="list_all_1")],
        [InlineKeyboardButton(text="⏳ Только новые", callback_data="list_pending_1")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="broadcast")],
        [InlineKeyboardButton(text="⟳ Обновить", callback_data="admin_menu")]
    ])
    await message.answer("🛠️ ADMIN PANEL", reply_markup=kb)

@router.callback_query(F.data.startswith("reg_"))
async def approve_request(callback: CallbackQuery):
    rid = int(callback.data.split("_")[1])
    for r in pending_requests:
        if r["id"] == rid and r["status"] == "pending":
            r["status"] = "registered"
            await bot.send_message(r["user_id"], f"✓ SIM #{rid} зарегистрирована!")
            await callback.message.edit_text(callback.message.text + f"\n\n✅ Одобрено")
            await save_data()
            break
    await callback.answer()

@router.callback_query(F.data.startswith("rej_"))
async def reject_request(callback: CallbackQuery):
    rid = int(callback.data.split("_")[1])
    for r in pending_requests:
        if r["id"] == rid and r["status"] == "pending":
            r["status"] = "rejected"
            await bot.send_message(r["user_id"], f"✗ Заявка #{rid} отклонена.")
            await callback.message.edit_text(callback.message.text + f"\n\n❌ Отклонено")
            await save_data()
            break
    await callback.answer()

async def main():
    await load_data()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
