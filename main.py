import asyncio
import json
import logging
import os
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

DATA_FILE = Path("bot_data.json")
logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# Глобальные данные (загружаются из JSON)
pending_requests: List[Dict[str, Any]] = []
users: set[int] = set()
request_counter: int = 0
data_lock = asyncio.Lock()  # для безопасной записи

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
        logging.info(f"Загружено {len(pending_requests)} заявок, {len(users)} пользователей")
    except Exception as e:
        logging.error(f"Ошибка загрузки JSON: {e}")
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
    if len(users) % 5 == 0:
        await save_data()

    await message.answer(
        "⚠️ Добро пожаловать в систему.\nКонтроль — иллюзия.\n\nВыбери действие:",
        reply_markup=get_main_kb()
    )

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
    await message.answer(f"Оператор: {message.text}\n\nВведи номер (пример: +77001234567):")
    await state.set_state(RegForm.phone)

@router.message(RegForm.phone)
async def process_phone(message: Message, state: FSMContext):
    global request_counter
    data = await state.get_data()
    op = data.get("operator")
    phone = message.text.strip()

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
        "created": int(asyncio.get_event_loop().time())
    })

    await message.answer(f"Заявка #{rid} отправлена.\nОжидай решения.", reply_markup=get_main_kb())

    admin_text = (
        f"🆕 Заявка #{rid}\n"
        f"👤 {message.from_user.first_name} (@{message.from_user.username or 'нет'})\n"
        f"🆔 {message.chat.id}\n"
        f"📶 {op}\n"
        f"📱 {phone}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Зарегистрировать", callback_data=f"reg_{rid}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"rej_{rid}")]
    ])

    await bot.send_message(ADMIN_ID, admin_text, reply_markup=kb)
    await state.clear()
    await save_data()

@router.message(F.text == "← Назад в меню")
async def back_to_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Главное меню", reply_markup=get_main_kb())

@router.message(Command("admin"))
async def admin_panel(message: Message):
    if message.chat.id != ADMIN_ID:
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Все заявки", callback_data="list_all_1")],
        [InlineKeyboardButton(text="⏳ Только новые", callback_data="list_pending_1")],
        [InlineKeyboardButton(text="🔍 Поиск по номеру", callback_data="search_phone")],
        [InlineKeyboardButton(text="🔍 Поиск по ID", callback_data="search_id")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="broadcast")],
        [InlineKeyboardButton(text="⟳ Обновить", callback_data="admin_menu")]
    ])

    await message.answer("🛠️ ADMIN PANEL\nВыбери действие:", reply_markup=kb)

# ================= CALLBACKS =================
@router.callback_query(F.data.startswith("reg_"))
async def approve_request(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещён")
        return

    rid = int(callback.data.split("_")[1])
    for r in pending_requests:
        if r["id"] == rid and r["status"] == "pending":
            r["status"] = "registered"
            await bot.send_message(r["user_id"], f"✓ SIM #{rid} зарегистрирована!\n{r['operator']} | {r['phone']}")
            await callback.message.edit_text(callback.message.text + f"\n\n✅ Зарегистрировано #{rid}")
            await callback.answer("Готово")
            await save_data()
            return

@router.callback_query(F.data.startswith("rej_"))
async def reject_request(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещён")
        return

    rid = int(callback.data.split("_")[1])
    for r in pending_requests:
        if r["id"] == rid and r["status"] == "pending":
            r["status"] = "rejected"
            await bot.send_message(r["user_id"], f"✗ Заявка #{rid} отклонена.")
            await callback.message.edit_text(callback.message.text + f"\n\n❌ Отклонено #{rid}")
            await callback.answer("Отклонено")
            await save_data()
            return

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

@router.callback_query(F.data.in_({"search_phone", "search_id"}))
async def start_search(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещён")
        return

    field = "phone" if callback.data == "search_phone" else "id"
    await state.set_state(AdminForm.search)
    await state.update_data(field=field)

    hint = "номер телефона (часть)" if field == "phone" else "ID заявки"
    await callback.message.answer(f"Введи {hint} для поиска:")
    await callback.answer()

@router.message(AdminForm.search)
async def process_search(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    data = await state.get_data()
    field = data.get("field")
    query = message.text.strip()

    text, kb = await generate_requests_list(page=1, search=query, field=field)
    await message.answer(text, reply_markup=kb)
    await state.clear()

@router.callback_query(F.data == "broadcast")
async def start_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещён")
        return

    await state.set_state(AdminForm.broadcast)
    await callback.message.answer("Напиши текст для рассылки всем пользователям:")
    await callback.answer()

@router.message(AdminForm.broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    count = 0
    for uid in list(users):
        try:
            await bot.send_message(uid, message.text)
            count += 1
        except:
            pass

    await message.answer(f"Рассылка завершена.\nОтправлено: {count}")
    await state.clear()
    await save_data()

@router.callback_query(F.data == "admin_menu")
async def back_to_admin(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещён")
        return

    await admin_panel(callback.message)
    try:
        await callback.message.delete()
    except:
        pass
    await callback.answer()

# ================= СПИСОК ЗАЯВОК =================
async def generate_requests_list(
    page: int = 1,
    per_page: int = 8,
    status: str | None = None,
    search: str | None = None,
    field: str = "phone"
) -> tuple[str, InlineKeyboardMarkup | None]:
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

# ================= ЗАПУСК =================
async def main():
    await load_data()
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
