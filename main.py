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

# Рассылка всем
@router.message(F.text == "📢 Рассылка всем")
async def start_broadcast(message: Message, state: FSMContext):
    if message.chat.id != ADMIN_ID: return
    await message.answer("Введите текст рассылки:\n\nДля отмены: отмена")
    await state.set_state(AdminStates.broadcast)

@router.message(AdminStates.broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    if message.chat.id != ADMIN_ID: return
    if message.text.lower() in {"отмена", "/отмена"}:
        await state.clear()
        await message.answer("Отменено", reply_markup=get_admin_kb())
        return

    text = message.text
    success = failed = 0
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

# Все заявки
@router.message(F.text == "📋 Все заявки")
async def show_all_requests(message: Message):
    if message.chat.id != ADMIN_ID: return
    if not pending_requests:
        return await message.answer("Заявок нет", reply_markup=get_admin_kb())

    text = "📋 Заявки:\n\n"
    for r in pending_requests:
        emoji = {"new": "🆕", "waiting_sms": "🔑", "completed": "✅"}.get(r["status"], "❓")
        extra = " (ожидает принятия)" if r["status"] == "new" else ""
        text += f"#{r['id']} {emoji}{extra}\nЮзер: {r['username']}\nНомер: {r['phone']}\nОп: {r['operator']}\n───────────────\n"

    await message.answer(text, reply_markup=get_admin_kb())

# Поиск по номеру
@router.message(F.text == "🔍 Поиск по номеру")
async def start_search(message: Message, state: FSMContext):
    if message.chat.id != ADMIN_ID: return
    await message.answer("Введите номер (или часть):\nОтмена → отмена")
    await state.set_state(AdminStates.search_phone)

@router.message(AdminStates.search_phone)
async def process_search(message: Message, state: FSMContext):
    if message.chat.id != ADMIN_ID: return
    if message.text.lower() in {"отмена", "/отмена"}:
        await state.clear()
        await message.answer("Отменено", reply_markup=get_admin_kb())
        return

    query = re.sub(r"\D", "", message.text).strip()
    if not query:
        await message.answer("Введите что-то или отмена")
        return

    found = [r for r in pending_requests if query in r["phone"]]
    if not found:
        await message.answer(f"По '{query}' ничего", reply_markup=get_admin_kb())
    else:
        text = f"Найдено {len(found)}:\n\n"
        for r in found:
            text += f"#{r['id']} | {r['status']}\n{r['username']}\n{r['phone']} | {r['operator']}\n───────────────\n"
        await message.answer(text, reply_markup=get_admin_kb())
    await state.clear()

# Регистрация номера — с проверкой на 8 и префиксы
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
        f"📱 Оператор: {message.text}\n\nВведи номер начиная с 8 (11 цифр):\nПример: 87751234567",
        reply_markup=get_operators_kb()
    )
    await state.set_state(RegForm.phone)

@router.message(RegForm.phone)
async def process_phone(message: Message, state: FSMContext):
    all_users.add(message.chat.id)
    raw = message.text.strip()
    phone = re.sub(r"\D", "", raw)

    if len(phone) != 11 or not phone.startswith("8"):
        await message.answer(
            "❌ Номер должен начинаться с 8 и состоять из 11 цифр.\n"
            "Пример: 87751234567\nПопробуй ещё раз:"
        )
        return

    prefix = phone[1:4]  # цифры после 8 (3 шт)

    data = await state.get_data()
    op = data['operator']

    valid_prefixes = {
        "Activ": ["775", "776", "778"],
        "Tele2": ["707", "747"],
        "Altel": ["700", "708"]
    }

    if prefix not in valid_prefixes.get(op, []):
        await message.answer(
            f"❌ Для {op} номер должен начинаться на 8 + один из префиксов: {', '.join(valid_prefixes[op])}\n"
            f"Примеры: 8{valid_prefixes[op][0]}...\nПопробуй ещё раз:"
        )
        return

    user_info = f"@{message.from_user.username}" if message.from_user.username else f"ID {message.from_user.id}"
    rid = len(pending_requests) + 1

    request = {
        "id": rid,
        "user_id": message.chat.id,
        "username": user_info,
        "phone": phone,
        "operator": op,
        "status": "new"
    }
    pending_requests.append(request)

    await message.answer("✅ Заявка отправлена администратору на проверку.\nОжидайте подтверждения...")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять заявку", callback_data=f"accept_{rid}")]
    ])

    await bot.send_message(
        ADMIN_ID,
        f"🆕 НОВАЯ ЗАЯВКА #{rid}\n"
        f"Юзер: {user_info}\n"
        f"Номер: {phone}\n"
        f"Оператор: {op}",
        reply_markup=kb
    )
    await state.clear()

@router.callback_query(F.data.startswith("accept_"))
async def accept_request(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    rid = int(callback.data.split("_")[1])
    for req in pending_requests:
        if req["id"] == rid and req["status"] == "new":
            req["status"] = "waiting_sms"
            await bot.send_message(
                req["user_id"],
                "✅ Заявка принята!\nТеперь пришли код из СМС:"
            )
            await callback.message.edit_text(
                callback.message.text + "\n\n✅ Принято, ожидает код"
            )
            await callback.answer("Заявка принята")
            return
    await callback.answer("Заявка уже обработана или не найдена", show_alert=True)

# ... (остальные хендлеры: catch_sms, check_payment, finish_job, repeat_code — остаются без изменений из предыдущей версии)

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
        await message.answer("Только цифры из СМС")
        return

    await message.answer("Код принят...")

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

# ... (finish_job и repeat_code — без изменений)

async def main():
    logging.info("Бот запущен")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    asyncio.run(main())