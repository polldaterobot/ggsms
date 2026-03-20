import telebot
from telebot import types
import time
import json
import os
import tempfile
from threading import Lock

# ================= НАСТРОЙКИ =================
TOKEN = "8623489996:AAE5rfYaS4JbAGrso_veeFALIsLagXx74s8"
ADMIN_ID = 8209617821

bot = telebot.TeleBot(TOKEN)

# Файл и защита от одновременной записи
DATA_FILE = "bot_data.json"
data_lock = Lock()

# Глобальные переменные (загружаются из JSON)
pending_requests = []
users = set()
request_counter = 0

# ================= ФУНКЦИИ СОХРАНЕНИЯ / ЗАГРУЗКИ =================
def load_data():
    global pending_requests, users, request_counter
    
    if not os.path.exists(DATA_FILE):
        print("Файл данных не найден → создаём новый")
        save_data()
        return
    
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        pending_requests = data.get("pending_requests", [])
        users = set(data.get("users", []))
        request_counter = data.get("request_counter", 0)
        print(f"Загружено: {len(pending_requests)} заявок, {len(users)} пользователей, счётчик = {request_counter}")
    except Exception as e:
        print(f"Ошибка загрузки JSON: {e}. Используем пустые данные.")
        pending_requests = []
        users = set()
        request_counter = 0
        save_data()

def save_data():
    with data_lock:
        temp_file = tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False)
        try:
            data = {
                "pending_requests": pending_requests,
                "users": list(users),
                "request_counter": request_counter
            }
            json.dump(data, temp_file, ensure_ascii=False, indent=2)
            temp_file.close()
            os.replace(temp_file.name, DATA_FILE)
            # print("Данные сохранены")
        except Exception as e:
            print(f"Ошибка сохранения JSON: {e}")
            try:
                os.unlink(temp_file.name)
            except:
                pass

# Загружаем данные при запуске
load_data()

# ================= КЛАВИАТУРЫ =================
def main_menu():
    mk = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    mk.add("📞 Зарегистрировать SIM", "🆘 Поддержка")
    return mk

def operators_menu():
    mk = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    mk.add("Activ", "Tele2", "Altel")
    mk.add("← Назад в меню")
    return mk

# ================= START =================
@bot.message_handler(commands=['start'])
def start(msg):
    users.add(msg.chat.id)
    if len(users) % 5 == 0:  # сохраняем не каждый раз, чтобы не нагружать диск
        save_data()
    
    text = (
        "⚠️ Добро пожаловать в систему.\n"
        "Контроль — иллюзия.\n\n"
        "Выбери действие:"
    )
    bot.send_message(msg.chat.id, text, reply_markup=main_menu())

# ================= ОСНОВНОЙ ОБРАБОТЧИК =================
@bot.message_handler(func=lambda m: True)
def message_handler(msg):
    global request_counter
    cid = msg.chat.id
    text = msg.text.strip()
    state = user_states.get(cid, {}).get('state')

    # Рассылка (только админ)
    if state == 'broadcast' and cid == ADMIN_ID:
        count = 0
        for uid in list(users):
            try:
                bot.send_message(uid, text)
                count += 1
            except:
                pass
        bot.send_message(ADMIN_ID, f"Рассылка завершена.\nОтправлено: {count}")
        user_states.pop(cid, None)
        save_data()  # сохраняем на всякий случай
        return

    # Ввод номера телефона
    if state == 'wait_phone':
        op = user_states[cid]['operator']
        phone = text

        request_counter += 1
        rid = request_counter

        pending_requests.append({
            'id': rid,
            'user_id': cid,
            'username': msg.from_user.username or "без ника",
            'first_name': msg.from_user.first_name,
            'operator': op,
            'phone': phone,
            'status': 'pending',
            'created': int(time.time())
        })

        bot.send_message(cid,
            f"Заявка #{rid} отправлена.\nОжидай решения.",
            reply_markup=main_menu()
        )

        admin_msg = (
            f"🆕 Заявка #{rid}\n"
            f"👤 {msg.from_user.first_name} (@{msg.from_user.username or 'нет'})\n"
            f"🆔 {cid}\n"
            f"📶 {op}\n"
            f"📱 {phone}"
        )

        mk = types.InlineKeyboardMarkup()
        mk.add(
            types.InlineKeyboardButton("✅ Зарегистрировать", callback_data=f"reg_{rid}"),
            types.InlineKeyboardButton("❌ Отклонить",     callback_data=f"rej_{rid}")
        )

        bot.send_message(ADMIN_ID, admin_msg, reply_markup=mk)
        user_states.pop(cid, None)
        save_data()  # ← важно: сохраняем новую заявку
        return

    # Кнопки меню
    if text == "🆘 Поддержка":
        bot.forward_message(ADMIN_ID, cid, msg.message_id)
        bot.send_message(ADMIN_ID, f"Поддержка от @{msg.from_user.username or cid}")
        bot.send_message(cid, "Запрос отправлен. Жди ответа.")

    elif text == "📞 Зарегистрировать SIM":
        bot.send_message(cid, "Выбери оператора:", reply_markup=operators_menu())
        user_states[cid] = {'state': 'wait_operator'}

    elif text in ["Activ", "Tele2", "Altel"] and state == 'wait_operator':
        user_states[cid] = {'state': 'wait_phone', 'operator': text}
        bot.send_message(cid, f"Оператор: {text}\n\nВведи номер (пример: +77001234567):")

    elif text == "← Назад в меню":
        bot.send_message(cid, "Главное меню", reply_markup=main_menu())
        user_states.pop(cid, None)

    else:
        bot.send_message(cid, "Используй кнопки ниже ↓", reply_markup=main_menu())

# ================= АДМИН-ПАНЕЛЬ =================
@bot.message_handler(commands=['admin'])
def admin_panel(msg):
    if msg.chat.id != ADMIN_ID:
        return

    mk = types.InlineKeyboardMarkup(row_width=2)
    mk.add(
        types.InlineKeyboardButton("📋 Все заявки",     callback_data="list_all_1"),
        types.InlineKeyboardButton("⏳ Только новые",   callback_data="list_pending_1")
    )
    mk.add(
        types.InlineKeyboardButton("🔍 Поиск по номеру", callback_data="search_phone"),
        types.InlineKeyboardButton("🔍 Поиск по ID",     callback_data="search_id")
    )
    mk.add(
        types.InlineKeyboardButton("📢 Рассылка",       callback_data="broadcast"),
        types.InlineKeyboardButton("⟳ Обновить",        callback_data="admin_menu")
    )

    bot.send_message(ADMIN_ID, "🛠️ ADMIN PANEL\nВыбери действие:", reply_markup=mk)

# ================= ФУНКЦИЯ СПИСКА ЗАЯВОК =================
def get_requests_text(page=1, per_page=8, status=None, search=None, field="phone"):
    filtered = [r for r in pending_requests
                if (not status or r['status'] == status)
                and (not search or search.lower() in str(r.get(field, '')).lower())]

    total = len(filtered)
    start = (page - 1) * per_page
    items = filtered[start:start + per_page]

    if not items:
        return "Нет подходящих заявок.", None

    lines = [f"Заявки | стр {page}/{max(1, (total + per_page - 1)//per_page)} | всего {total}\n"]
    for r in items:
        emoji = "⏳" if r['status']=='pending' else "✅" if r['status']=='registered' else "❌"
        lines.append(f"{emoji} #{r['id']} | {r['operator']} | {r['phone']}")
        lines.append(f"   @{r['username']} | {r['first_name']} | {r['user_id']}\n")

    text = "".join(lines)

    mk = types.InlineKeyboardMarkup(row_width=3)

    for r in items:
        if r['status'] == 'pending':
            mk.row(
                types.InlineKeyboardButton(f"✅ #{r['id']}", callback_data=f"reg_{r['id']}"),
                types.InlineKeyboardButton(f"❌ #{r['id']}", callback_data=f"rej_{r['id']}")
            )

    if page > 1:
        mk.add(types.InlineKeyboardButton("← Назад", callback_data=f"list_{status or 'all'}_{page-1}"))

    if start + per_page < total:
        mk.add(types.InlineKeyboardButton("Вперёд →", callback_data=f"list_{status or 'all'}_{page+1}"))

    mk.add(types.InlineKeyboardButton("↩ Админ меню", callback_data="admin_menu"))

    return text, mk

# ================= CALLBACK =================
@bot.callback_query_handler(func=lambda c: True)
def callback(c):
    if c.from_user.id != ADMIN_ID:
        bot.answer_callback_query(c.id, "Доступ запрещён")
        return

    d = c.data

    if d.startswith("reg_"):
        rid = int(d[4:])
        for r in pending_requests:
            if r['id'] == rid and r['status'] == 'pending':
                r['status'] = 'registered'
                bot.send_message(r['user_id'], f"✓ SIM #{rid} зарегистрирована!\n{r['operator']} | {r['phone']}")
                bot.edit_message_text(f"{c.message.text}\n\n✅ Зарегистрировано #{rid}", c.message.chat.id, c.message.message_id)
                save_data()  # ← сохраняем изменение статуса
                bot.answer_callback_query(c.id, "Готово")
                return

    if d.startswith("rej_"):
        rid = int(d[4:])
        for r in pending_requests:
            if r['id'] == rid and r['status'] == 'pending':
                r['status'] = 'rejected'
                bot.send_message(r['user_id'], f"✗ Заявка #{rid} отклонена.")
                bot.edit_message_text(f"{c.message.text}\n\n❌ Отклонено #{rid}", c.message.chat.id, c.message.message_id)
                save_data()  # ← сохраняем изменение статуса
                bot.answer_callback_query(c.id, "Отклонено")
                return

    if d.startswith("list_"):
        parts = d.split("_")
        flt = parts[1] if len(parts) > 2 else "all"
        page = int(parts[-1]) if parts[-1].isdigit() else 1

        status = None if flt == "all" else "pending" if flt == "pending" else None

        txt, mk = get_requests_text(page=page, status=status)
        bot.edit_message_text(txt, c.message.chat.id, c.message.message_id, reply_markup=mk)
        bot.answer_callback_query(c.id)

    elif d in ("search_phone", "search_id"):
        field = "phone" if d == "search_phone" else "id"
        user_states[ADMIN_ID] = {'state': 'admin_search', 'field': field}
        hint = "номер телефона (часть)" if field == "phone" else "ID заявки"
        bot.send_message(ADMIN_ID, f"Введи {hint} для поиска:")
        bot.answer_callback_query(c.id)

    elif d == "broadcast":
        bot.send_message(ADMIN_ID, "Напиши текст для рассылки всем пользователям:")
        user_states[ADMIN_ID] = {'state': 'broadcast'}
        bot.answer_callback_query(c.id)

    elif d == "admin_menu":
        admin_panel(c.message)
        try:
            bot.delete_message(c.message.chat.id, c.message.message_id)
        except:
            pass

    # Обработка поиска (когда админ пишет текст)
    elif ADMIN_ID in user_states and user_states[ADMIN_ID].get('state') == 'admin_search':
        if not hasattr(c, 'message') or not c.message.text:
            return
        query = c.message.text.strip()
        field = user_states[ADMIN_ID]['field']

        txt, mk = get_requests_text(page=1, search=query, field=field)
        bot.send_message(ADMIN_ID, txt, reply_markup=mk)
        user_states.pop(ADMIN_ID, None)

# ================= СЛОВАРЬ СОСТОЯНИЙ =================
user_states = {}  # {chat_id: {'state': '...', ...}}

if __name__ == '__main__':
    print("Bot started... Данные хранятся в bot_data.json")
    try:
        bot.infinity_polling(timeout=30)
    except Exception as e:
        print(f"Критическая ошибка: {e}")
    finally:
        save_data()  # на всякий случай сохраняем при выходе
