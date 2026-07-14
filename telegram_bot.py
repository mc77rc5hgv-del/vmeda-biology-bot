import asyncio
import json
import logging
import random
import os
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, FSInputFile
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8469931783:AAFhj045ghZz4MBDBzfqP2Vs-SN4tucAngo")
CHANNEL_ID = "@Vmeda_examen"
ADMIN_ID = 1326779223
STATS_DIR = os.getenv("STATS_DIR", ".")
STATS_FILE = os.path.join(STATS_DIR, "stats.json")

DIVIDER = "━━━━━━━━━━━━━━"
IMAGES_DIR = "images"

# ==================== ЗАГРУЗКА ДАННЫХ ====================
with open("tickets.json", "r", encoding="utf-8") as f:
    TICKETS = json.load(f)
TICKETS_DICT = {str(t["num"]): t for t in TICKETS}

with open("questions.json", "r", encoding="utf-8") as f:
    QUESTIONS = json.load(f)

with open("physics_questions.json", "r", encoding="utf-8") as f:
    PHYSICS_QUESTIONS = json.load(f)

with open("chemistry_labs.json", "r", encoding="utf-8") as f:
    CHEMISTRY_LABS = json.load(f)

with open("chemistry_theory.json", "r", encoding="utf-8") as f:
    CHEMISTRY_THEORY = json.load(f)["topics"]

# ==================== СТАТИСТИКА (СОХРАНЯЕТСЯ НА ДИСК) ====================
def load_stats() -> dict:
    os.makedirs(STATS_DIR, exist_ok=True)
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["total_users"] = set(data.get("total_users", []))
            data.setdefault("start_count", 0)
            data.setdefault("random_ticket_used", 0)
            data.setdefault("random_question_used", 0)
            data.setdefault("question_opened", {})
            data.setdefault("broadcast_count", 0)
            return data
        except (json.JSONDecodeError, OSError):
            logger.exception("Не удалось прочитать %s, статистика будет создана заново", STATS_FILE)
    return {
        "total_users": set(),
        "start_count": 0,
        "random_ticket_used": 0,
        "random_question_used": 0,
        "question_opened": {},
        "broadcast_count": 0,
    }

def save_stats() -> None:
    data = dict(stats)
    data["total_users"] = list(stats["total_users"])
    tmp_path = f"{STATS_FILE}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, STATS_FILE)

stats = load_stats()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ==================== СКРЫТЫЕ БИЛЕТЫ (40-50) ====================
HIDDEN_TICKET_RANGE = (40, 50)

def _ticket_number_part(ticket_num: str) -> int:
    """Достаёт числовую часть номера билета (например, '20A' -> 20)."""
    digits = ""
    for ch in str(ticket_num):
        if ch.isdigit():
            digits += ch
        else:
            break
    return int(digits) if digits else 0

def is_ticket_visible(ticket_num: str) -> bool:
    n = _ticket_number_part(ticket_num)
    return not (HIDDEN_TICKET_RANGE[0] <= n <= HIDDEN_TICKET_RANGE[1])

def _ticket_sort_key(ticket_num: str):
    digits = ""
    letters = ""
    for ch in str(ticket_num):
        if ch.isdigit():
            digits += ch
        else:
            letters += ch
    return (int(digits) if digits else 0, letters)

VISIBLE_TICKETS = [t for t in TICKETS if is_ticket_visible(str(t.get("num")))]
VISIBLE_TICKET_NUMS = sorted(
    [str(t.get("num")) for t in VISIBLE_TICKETS],
    key=_ticket_sort_key
)

async def is_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
    except Exception:
        return False

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

CAPTION_LIMIT = 1024

async def safe_edit_text(message, text, **kwargs) -> None:
    """Как edit_text, но если сообщение больше не текстовое (например, стало фото),
    удаляет его и отправляет новое вместо падения с ошибкой."""
    try:
        await message.edit_text(text, **kwargs)
    except TelegramBadRequest:
        await message.delete()
        await message.answer(text, **kwargs)

async def send_answer(target, body: str, short_caption: str, question: dict, keyboard, edit: bool) -> None:
    """Показывает текст вопроса+ответа. Если у вопроса есть картинка-схема, она всегда
    приходит первым сообщением:
    - при коротком ответе (уместился в лимит подписи Telegram) — единое сообщение "фото + текст";
    - при длинном ответе — сначала фото (с коротким заголовком), затем отдельным сообщением
      полный текст ответа (объединить в одно сообщение технически невозможно: Telegram
      ограничивает подпись к фото 1024 символами).
    target — CallbackQuery.message при edit=True, либо обычное Message при edit=False.
    При edit=True старое сообщение удаляется, а не редактируется — иначе оно осталось бы
    на прежнем месте в чате, выше нового фото."""
    image_name = question.get("image")
    image_path = os.path.join(IMAGES_DIR, image_name) if image_name else None
    if image_path and not os.path.exists(image_path):
        logger.warning("Изображение не найдено: %s", image_path)
        image_path = None

    if not image_path:
        if edit:
            await safe_edit_text(target, body, parse_mode="HTML", reply_markup=keyboard)
        else:
            await target.answer(body, parse_mode="HTML", reply_markup=keyboard)
        return

    photo = FSInputFile(image_path)
    if edit:
        await target.delete()

    if len(body) <= CAPTION_LIMIT:
        await target.answer_photo(photo, caption=body, parse_mode="HTML", reply_markup=keyboard)
        return

    caption = short_caption if len(short_caption) <= CAPTION_LIMIT else short_caption[:CAPTION_LIMIT - 1] + "…"
    try:
        await target.answer_photo(photo, caption=caption, parse_mode="HTML")
    except Exception:
        logger.exception("Не удалось отправить изображение %s", image_path)
    await target.answer(body, parse_mode="HTML", reply_markup=keyboard)

# ==================== КЛАВИАТУРЫ ====================
def get_main_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="🧬 Биология", callback_data="menu_biology")
    builder.button(text="⚛️ Физика", callback_data="menu_physics")
    builder.button(text="🧪 Химия", callback_data="menu_chemistry")
    builder.adjust(1)
    return builder.as_markup()

def get_biology_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="📘 Билеты", callback_data="menu_tickets")
    builder.button(text="📝 Вопросы", callback_data="menu_questions")
    builder.button(text="🎯 Опрос (10 вопросов)", callback_data="quiz_start")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()

# ==================== БИОЛОГИЯ — РЕЖИМ ОПРОСА (ФЛЭШ-КАРТОЧКИ) ====================
QUIZ_SESSION_SIZE = 10
QUIZ_SESSIONS: dict[int, dict] = {}

def get_quiz_question_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🙈 Показать ответ", callback_data="quiz_show_answer")
    builder.button(text="🛑 Закончить опрос", callback_data="quiz_stop")
    builder.adjust(1)
    return builder.as_markup()

def get_quiz_answer_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Знаю", callback_data="quiz_know")
    builder.button(text="❌ Не знаю", callback_data="quiz_dont_know")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🛑 Закончить опрос", callback_data="quiz_stop"))
    return builder.as_markup()

def get_quiz_summary_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔁 Пройти ещё раз", callback_data="quiz_start")
    builder.button(text="🔙 К биологии", callback_data="menu_biology")
    builder.adjust(1)
    return builder.as_markup()

def start_quiz_session(user_id: int):
    pool = list(QUESTIONS.keys())
    size = min(QUIZ_SESSION_SIZE, len(pool))
    QUIZ_SESSIONS[user_id] = {
        "questions": random.sample(pool, size),
        "index": 0,
        "know": 0,
        "dont_know": 0,
    }

async def render_quiz_question(message, user_id: int):
    session = QUIZ_SESSIONS[user_id]
    total = len(session["questions"])
    q_num = session["questions"][session["index"]]
    q = QUESTIONS[q_num]
    text = (
        f"🎯 <b>Опрос — вопрос {session['index'] + 1}/{total}</b>\n{DIVIDER}\n\n"
        f"<b>{q['title']}</b>"
    )
    await message.edit_text(text, parse_mode="HTML", reply_markup=get_quiz_question_keyboard())

async def render_quiz_answer(message, user_id: int):
    session = QUIZ_SESSIONS[user_id]
    total = len(session["questions"])
    q_num = session["questions"][session["index"]]
    q = QUESTIONS[q_num]
    header = f"🎯 <b>Опрос — вопрос {session['index'] + 1}/{total}</b>"
    body = f"{header}\n{DIVIDER}\n\n<b>{q['title']}</b>\n\n{q['answer']}\n\n{DIVIDER}\nТы знал(а) ответ?"
    short_caption = f"{header}\n{DIVIDER}\n\n<b>{q['title']}</b>"
    await send_answer(message, body, short_caption, q, get_quiz_answer_keyboard(), edit=True)

async def render_quiz_summary(message, user_id: int, aborted: bool = False):
    session = QUIZ_SESSIONS.pop(user_id, None)
    if not session:
        await message.edit_text(
            f"🧬 <b>Биология</b>\n{DIVIDER}\n\nВыбери формат подготовки:",
            parse_mode="HTML",
            reply_markup=get_biology_menu()
        )
        return
    answered = session["know"] + session["dont_know"]
    title = "🛑 <b>Опрос прерван</b>" if aborted else "🏁 <b>Опрос завершён!</b>"
    text = (
        f"{title}\n{DIVIDER}\n\n"
        f"Отвечено вопросов: <b>{answered}</b>\n"
        f"✅ Знаю: <b>{session['know']}</b>\n"
        f"❌ Не знаю: <b>{session['dont_know']}</b>"
    )
    await message.edit_text(text, parse_mode="HTML", reply_markup=get_quiz_summary_keyboard())

def get_ticket_keyboard():
    builder = InlineKeyboardBuilder()
    for num in VISIBLE_TICKET_NUMS:
        builder.button(text=f"🟢 {num}", callback_data=f"ticket:{num}")
    builder.adjust(4)
    builder.row(InlineKeyboardButton(text="🎲 Случайный билет", callback_data="random_ticket"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu_biology"))
    return builder.as_markup()

def get_questions_main_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="📄 Страница 1 (1-50)", callback_data="qpage:1")
    builder.button(text="📄 Страница 2 (51-100)", callback_data="qpage:2")
    builder.button(text="📄 Страница 3 (101-150)", callback_data="qpage:3")
    builder.button(text="📄 Страница 4 (151-185)", callback_data="qpage:4")
    builder.button(text="🎲 Случайный вопрос", callback_data="question_random")
    builder.button(text="🔢 Ввести номер вручную", callback_data="question_by_number")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu_biology"))
    return builder.as_markup()

def get_question_page_keyboard(page: int):
    builder = InlineKeyboardBuilder()
    start = (page - 1) * 50 + 1
    end = min(page * 50, 185)
    for i in range(start, end + 1, 5):
        row = [InlineKeyboardButton(text=f"🟢 {num}", callback_data=f"q:{num}") for num in range(i, min(i + 5, end + 1))]
        builder.row(*row)
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"qpage:{page-1}"))
    if page < 4:
        nav.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"qpage:{page+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К списку страниц", callback_data="menu_questions"))
    return builder.as_markup()

def get_ticket_questions_keyboard(ticket_num: str):
    builder = InlineKeyboardBuilder()
    ticket = TICKETS_DICT.get(ticket_num, {})
    questions = ticket.get("questions", [])
    for q in questions:
        q_num = q.get("num")
        builder.button(text=f"🟢 Вопрос {q_num}", callback_data=f"ticket_q:{ticket_num}:{q_num}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад к билетам", callback_data="menu_tickets"))
    return builder.as_markup()

# ==================== ФИЗИКА ====================
def get_physics_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Тестовая часть (186 вопросов)", callback_data="physics_test")
    builder.button(text="📘 Билеты", callback_data="physics_tickets")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()

def get_physics_test_pages():
    builder = InlineKeyboardBuilder()
    builder.button(text="📄 Страница 1 (1-50)", callback_data="physics_page:1")
    builder.button(text="📄 Страница 2 (51-100)", callback_data="physics_page:2")
    builder.button(text="📄 Страница 3 (101-150)", callback_data="physics_page:3")
    builder.button(text="📄 Страница 4 (151-186)", callback_data="physics_page:4")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu_physics"))
    return builder.as_markup()

def get_physics_question_keyboard(page: int):
    builder = InlineKeyboardBuilder()
    start = (page - 1) * 50 + 1
    end = min(page * 50, 186)
    for i in range(start, end + 1, 5):
        row = [InlineKeyboardButton(text=f"🟢 {num}", callback_data=f"physics_q:{num}") for num in range(i, min(i + 5, end + 1))]
        builder.row(*row)
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"physics_page:{page-1}"))
    if page < 4:
        nav.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"physics_page:{page+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К страницам", callback_data="physics_test"))
    return builder.as_markup()

# ==================== ХИМИЯ ====================
def get_chemistry_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="📚 Теория", callback_data="chemistry_theory")
    builder.button(text="📝 Задачи", callback_data="chemistry_tasks")
    builder.button(text="🧪 Лабораторные работы", callback_data="chemistry_labs")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()

def get_chemistry_theory_list():
    builder = InlineKeyboardBuilder()
    for num in range(1, 17):
        builder.button(text=f"📖 Тема {num}", callback_data=f"chem_theory:{num}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu_chemistry"))
    return builder.as_markup()

def get_theory_navigation(current_num: int):
    builder = InlineKeyboardBuilder()
    if current_num > 1:
        builder.button(text="⬅️ Предыдущая", callback_data=f"chem_theory:{current_num-1}")
    if current_num < 16:
        builder.button(text="Следующая ➡️", callback_data=f"chem_theory:{current_num+1}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙 К списку тем", callback_data="chemistry_theory_list"))
    return builder.as_markup()

def get_labs_keyboard():
    builder = InlineKeyboardBuilder()
    for lab in CHEMISTRY_LABS["labs"]:
        builder.button(text=f"🧪 Лаба {lab['number']}", callback_data=f"lab:{lab['number']}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu_chemistry"))
    return builder.as_markup()

# ==================== ОБРАБОТЧИКИ ====================
@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    is_new_user = user_id not in stats["total_users"]
    stats["total_users"].add(user_id)
    stats["start_count"] += 1
    save_stats()

    if not await is_subscribed(user_id):
        await message.answer(
            "👋 <b>Добро пожаловать!</b>\n\n"
            "Этот бот поможет подготовиться к экзаменам ВМедА:\n"
            "🧬 биология · ⚛️ физика · 🧪 химия\n\n"
            f"{DIVIDER}\n"
            "🔒 Чтобы пользоваться ботом, подпишись на канал:\n"
            "👉 https://t.me/Vmeda_examen\n\n"
            "После подписки нажми /start ещё раз.",
            parse_mode="HTML"
        )
        return

    greeting = "🎉 <b>С возвращением!</b>" if not is_new_user else "👋 <b>Привет!</b>"
    await message.answer(
        f"{greeting}\n\nВыбери предмет для подготовки:",
        parse_mode="HTML",
        reply_markup=get_main_menu()
    )

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    text = (
        "📊 <b>Статистика бота</b>\n"
        f"{DIVIDER}\n"
        f"👥 Уникальных пользователей: <b>{len(stats['total_users'])}</b>\n"
        f"▶️ Запусков бота: <b>{stats['start_count']}</b>\n"
        f"❓ Вопросов просмотрено: <b>{sum(stats['question_opened'].values())}</b>\n"
        f"🎲 Случайных билетов открыто: <b>{stats['random_ticket_used']}</b>\n"
        f"🎲 Случайных вопросов открыто: <b>{stats['random_question_used']}</b>\n"
        f"📢 Рассылок отправлено: <b>{stats.get('broadcast_count', 0)}</b>"
    )
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if not is_admin(message.from_user.id):
        return

    text = message.html_text.split(maxsplit=1)
    if len(text) < 2 or not text[1].strip():
        await message.answer(
            "✏️ <b>Публичное сообщение от администрации</b>\n\n"
            "Использование:\n<code>/broadcast Текст сообщения</code>",
            parse_mode="HTML"
        )
        return

    announcement = text[1]
    body = (
        "📢 <b>Сообщение от администрации</b>\n"
        f"{DIVIDER}\n\n"
        f"{announcement}"
    )

    recipients = list(stats["total_users"])
    status = await message.answer(f"⏳ Рассылка запущена для {len(recipients)} пользователей...")

    sent, failed = 0, 0
    for user_id in recipients:
        try:
            await bot.send_message(user_id, body, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    stats["broadcast_count"] = stats.get("broadcast_count", 0) + 1
    save_stats()

    await status.edit_text(
        "✅ <b>Рассылка завершена</b>\n"
        f"{DIVIDER}\n"
        f"Доставлено: <b>{sent}</b>\n"
        f"Не доставлено: <b>{failed}</b>"
        , parse_mode="HTML"
    )

# ==================== МЕНЮ ====================
@dp.callback_query(F.data == "menu_biology")
async def cb_menu_biology(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        f"🧬 <b>Биология</b>\n{DIVIDER}\n\nВыбери формат подготовки:",
        parse_mode="HTML",
        reply_markup=get_biology_menu()
    )

@dp.callback_query(F.data == "quiz_start")
async def cb_quiz_start(callback: CallbackQuery):
    if not QUESTIONS:
        await callback.answer("Вопросы ещё не загружены", show_alert=True)
        return
    await callback.answer()
    start_quiz_session(callback.from_user.id)
    await render_quiz_question(callback.message, callback.from_user.id)

@dp.callback_query(F.data == "quiz_show_answer")
async def cb_quiz_show_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in QUIZ_SESSIONS:
        await callback.answer("Сессия опроса истекла, начни заново", show_alert=True)
        return
    await callback.answer()
    await render_quiz_answer(callback.message, user_id)

@dp.callback_query(F.data.in_({"quiz_know", "quiz_dont_know"}))
async def cb_quiz_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = QUIZ_SESSIONS.get(user_id)
    if not session:
        await callback.answer("Сессия опроса истекла, начни заново", show_alert=True)
        return
    await callback.answer()
    if callback.data == "quiz_know":
        session["know"] += 1
    else:
        session["dont_know"] += 1
    session["index"] += 1
    if session["index"] >= len(session["questions"]):
        await render_quiz_summary(callback.message, user_id)
    else:
        await render_quiz_question(callback.message, user_id)

@dp.callback_query(F.data == "quiz_stop")
async def cb_quiz_stop(callback: CallbackQuery):
    await callback.answer()
    await render_quiz_summary(callback.message, callback.from_user.id, aborted=True)

@dp.callback_query(F.data == "menu_tickets")
async def cb_menu_tickets(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        f"📘 <b>Билеты — Биология</b>\n{DIVIDER}\n\nВыбери билет:",
        parse_mode="HTML",
        reply_markup=get_ticket_keyboard()
    )

@dp.callback_query(F.data == "menu_questions")
async def cb_menu_questions(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        f"📝 <b>Вопросы — Биология</b>\n{DIVIDER}\n\nВыбери страницу:",
        parse_mode="HTML",
        reply_markup=get_questions_main_menu()
    )

@dp.callback_query(F.data == "back_to_main")
async def cb_back_to_main(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "🏠 <b>Главное меню</b>\n\nВыбери предмет для подготовки:",
        parse_mode="HTML",
        reply_markup=get_main_menu()
    )

@dp.callback_query(F.data == "menu_physics")
async def cb_menu_physics(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        f"⚛️ <b>Физика</b>\n{DIVIDER}\n\nВыбери раздел:",
        parse_mode="HTML",
        reply_markup=get_physics_menu()
    )

@dp.callback_query(F.data == "menu_chemistry")
async def cb_menu_chemistry(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        f"🧪 <b>Химия</b>\n{DIVIDER}\n\nВыбери раздел:",
        parse_mode="HTML",
        reply_markup=get_chemistry_menu()
    )

# ==================== ХИМИЯ - ТЕОРИЯ (С НАВИГАЦИЕЙ) ====================
@dp.callback_query(F.data == "chemistry_theory")
async def cb_chemistry_theory(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        f"📚 <b>Теория по химии</b>\n{DIVIDER}\n\nВыбери тему:",
        parse_mode="HTML",
        reply_markup=get_chemistry_theory_list()
    )

@dp.callback_query(F.data.startswith("chem_theory:"))
async def cb_show_theory_topic(callback: CallbackQuery):
    await callback.answer()
    num = int(callback.data.split(":")[1])
    topic = CHEMISTRY_THEORY.get(str(num))
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    text = f"📖 <b>{topic['title']}</b>\n{DIVIDER}\n\n{topic['content']}"
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_theory_navigation(num))

@dp.callback_query(F.data == "chemistry_theory_list")
async def cb_theory_list(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        f"📚 <b>Теория по химии</b>\n{DIVIDER}\n\nВыбери тему:",
        parse_mode="HTML",
        reply_markup=get_chemistry_theory_list()
    )

# ==================== ХИМИЯ - ЗАДАЧИ (пока заглушка) ====================
@dp.callback_query(F.data == "chemistry_tasks")
async def cb_chemistry_tasks(callback: CallbackQuery):
    await callback.answer("Раздел скоро появится", show_alert=True)

# ==================== ХИМИЯ - ЛАБОРАТОРНЫЕ РАБОТЫ ====================
@dp.callback_query(F.data == "chemistry_labs")
async def cb_chemistry_labs(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        f"🧪 <b>Лабораторные работы по химии</b>\n{DIVIDER}\n\nВыбери лабораторную работу:",
        parse_mode="HTML",
        reply_markup=get_labs_keyboard()
    )

@dp.callback_query(F.data.startswith("lab:"))
async def cb_show_lab(callback: CallbackQuery):
    await callback.answer()
    lab_num = int(callback.data.split(":")[1])
    lab = next((l for l in CHEMISTRY_LABS["labs"] if l["number"] == lab_num), None)
    if not lab:
        await callback.answer("Лабораторная работа не найдена", show_alert=True)
        return
    text = (
        f"🧪 <b>Лабораторная работа {lab['number']}</b>\n"
        f"{DIVIDER}\n\n"
        f"<b>Тема:</b> {lab.get('theme', '')}\n\n"
        f"<b>Условие:</b>\n{lab.get('condition', '')}"
    )
    builder = InlineKeyboardBuilder()
    if lab.get("experiments"):
        builder.button(text="🔬 Опыты", callback_data=f"lab_exp:{lab_num}")
    if lab.get("calculations"):
        builder.button(text="📐 Расчёты", callback_data=f"lab_calc:{lab_num}")
    builder.button(text="🔙 Назад к лабам", callback_data="chemistry_labs")
    builder.adjust(1)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("lab_exp:"))
async def cb_lab_experiments(callback: CallbackQuery):
    await callback.answer()
    lab_num = int(callback.data.split(":")[1])
    lab = next((l for l in CHEMISTRY_LABS["labs"] if l["number"] == lab_num), None)
    if not lab or not lab.get("experiments"):
        await callback.answer("Опыты не найдены", show_alert=True)
        return
    text = f"🔬 <b>Опыты — Лабораторная работа {lab_num}</b>\n{DIVIDER}\n\n"
    for exp in lab["experiments"]:
        text += f"<b>{exp.get('name', '')}</b>\n{exp.get('description', '')}\n\n"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data=f"lab:{lab_num}")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("lab_calc:"))
async def cb_lab_calculations(callback: CallbackQuery):
    await callback.answer()
    lab_num = int(callback.data.split(":")[1])
    lab = next((l for l in CHEMISTRY_LABS["labs"] if l["number"] == lab_num), None)
    if not lab or not lab.get("calculations"):
        await callback.answer("Расчёты не найдены", show_alert=True)
        return
    text = f"📐 <b>Расчёты — Лабораторная работа {lab_num}</b>\n{DIVIDER}\n\n{lab['calculations']}"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data=f"lab:{lab_num}")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())

# ==================== БИОЛОГИЯ — БИЛЕТЫ ====================
@dp.callback_query(F.data == "random_ticket")
async def cb_random_ticket(callback: CallbackQuery):
    if not await is_subscribed(callback.from_user.id):
        await callback.answer("Сначала подпишись на канал!", show_alert=True)
        return
    if not VISIBLE_TICKETS:
        await callback.answer("Билеты пока не загружены", show_alert=True)
        return
    await callback.answer()
    stats["random_ticket_used"] += 1
    save_stats()
    ticket = random.choice(VISIBLE_TICKETS)
    await show_ticket(callback.message, ticket)

@dp.callback_query(F.data.startswith("ticket:"))
async def cb_ticket(callback: CallbackQuery):
    await callback.answer()
    ticket_num = callback.data.split(":")[1]
    if ticket_num in TICKETS_DICT and is_ticket_visible(ticket_num):
        await show_ticket(callback.message, TICKETS_DICT[ticket_num])
    else:
        await callback.answer("Билет не найден", show_alert=True)

async def show_ticket(message, ticket: dict):
    ticket_num = ticket.get("num", "?")
    questions = ticket.get("questions", [])
    lines = [f"📘 <b>Билет {ticket_num}</b>", DIVIDER, ""]
    for q in questions:
        lines.append(f"<b>{q.get('num')}.</b> {q.get('title', '')}")
        lines.append("")
    lines.append("👇 Нажми на номер вопроса, чтобы увидеть ответ:")
    text = "\n".join(lines)
    await message.edit_text(text, parse_mode="HTML", reply_markup=get_ticket_questions_keyboard(str(ticket_num)))

@dp.callback_query(F.data.startswith("ticket_q:"))
async def cb_ticket_question(callback: CallbackQuery):
    await callback.answer()
    _, ticket_num, q_num = callback.data.split(":")
    ticket = TICKETS_DICT.get(ticket_num, {})
    questions = ticket.get("questions", [])
    question = next((q for q in questions if str(q.get("num")) == q_num), None)
    if question:
        header = f"❓ <b>Вопрос {q_num}</b> · Билет {ticket_num}"
        body = f"{header}\n{DIVIDER}\n\n<b>{question['title']}</b>\n\n{question['answer']}"
        short_caption = f"{header}\n{DIVIDER}\n\n<b>{question['title']}</b>"
        keyboard = get_ticket_questions_keyboard(ticket_num)
        await send_answer(callback.message, body, short_caption, question, keyboard, edit=True)
    else:
        await callback.answer("Вопрос не найден", show_alert=True)

# ==================== БИОЛОГИЯ — ВОПРОСЫ ====================
@dp.callback_query(F.data.startswith("qpage:"))
async def cb_question_page(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    await callback.answer()
    await callback.message.edit_text(
        f"📄 <b>Вопросы — Страница {page}</b>\n{DIVIDER}",
        parse_mode="HTML",
        reply_markup=get_question_page_keyboard(page)
    )

@dp.callback_query(F.data.startswith("q:"))
async def cb_show_question(callback: CallbackQuery):
    await callback.answer()
    q_num = callback.data.split(":")[1]
    if q_num in QUESTIONS:
        stats["question_opened"][q_num] = stats["question_opened"].get(q_num, 0) + 1
        save_stats()
        q = QUESTIONS[q_num]
        header = f"❓ <b>Вопрос {q_num}</b>"
        body = f"{header}\n{DIVIDER}\n\n<b>{q['title']}</b>\n\n{q['answer']}"
        short_caption = f"{header}\n{DIVIDER}\n\n<b>{q['title']}</b>"
        await send_answer(callback.message, body, short_caption, q, get_questions_main_menu(), edit=True)
    else:
        await callback.answer("Вопрос не найден", show_alert=True)

@dp.callback_query(F.data == "question_random")
async def cb_question_random(callback: CallbackQuery):
    if not QUESTIONS:
        await callback.answer("Вопросы ещё не загружены", show_alert=True)
        return
    await callback.answer()
    stats["random_question_used"] += 1
    q_num = random.choice(list(QUESTIONS.keys()))
    stats["question_opened"][q_num] = stats["question_opened"].get(q_num, 0) + 1
    save_stats()
    q = QUESTIONS[q_num]
    header = f"❓ <b>Вопрос {q_num}</b>"
    body = f"{header}\n{DIVIDER}\n\n<b>{q['title']}</b>\n\n{q['answer']}"
    short_caption = f"{header}\n{DIVIDER}\n\n<b>{q['title']}</b>"
    await send_answer(callback.message, body, short_caption, q, get_questions_main_menu(), edit=True)

@dp.callback_query(F.data == "question_by_number")
async def cb_question_by_number(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        f"🔢 <b>Поиск вопроса по номеру</b>\n{DIVIDER}\n\nВведи номер вопроса (от 1 до 185):",
        parse_mode="HTML"
    )

@dp.message(F.text.isdigit())
async def handle_question_number(message: Message):
    q_num = message.text.strip()
    if q_num in QUESTIONS:
        stats["question_opened"][q_num] = stats["question_opened"].get(q_num, 0) + 1
        save_stats()
        q = QUESTIONS[q_num]
        header = f"❓ <b>Вопрос {q_num}</b>"
        body = f"{header}\n{DIVIDER}\n\n<b>{q['title']}</b>\n\n{q['answer']}"
        short_caption = f"{header}\n{DIVIDER}\n\n<b>{q['title']}</b>"
        await send_answer(message, body, short_caption, q, get_questions_main_menu(), edit=False)
    else:
        await message.answer("⚠️ Вопрос с таким номером не найден.")

# ==================== ФИЗИКА ====================
@dp.callback_query(F.data == "physics_tickets")
async def cb_physics_tickets(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("🚧 Билеты по физике скоро будут добавлены!")

@dp.callback_query(F.data == "physics_test")
async def cb_physics_test(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        f"📝 <b>Тестовая часть — Физика</b>\n{DIVIDER}\n\nВыбери страницу:",
        parse_mode="HTML",
        reply_markup=get_physics_test_pages()
    )

@dp.callback_query(F.data.startswith("physics_page:"))
async def cb_physics_page(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    await callback.answer()
    await callback.message.edit_text(
        f"📄 <b>Физика — Страница {page}</b>\n{DIVIDER}",
        parse_mode="HTML",
        reply_markup=get_physics_question_keyboard(page)
    )

@dp.callback_query(F.data.startswith("physics_q:"))
async def cb_physics_question(callback: CallbackQuery):
    await callback.answer()
    q_num = callback.data.split(":")[1]
    if q_num in PHYSICS_QUESTIONS:
        q = PHYSICS_QUESTIONS[q_num]
        text = f"❓ <b>Вопрос {q_num}</b>\n{DIVIDER}\n\n{q.get('title', '')}\n\n{q.get('answer', '')}"
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_physics_test_pages())
    else:
        await callback.answer("Вопрос пока не добавлен в файл", show_alert=True)

# ==================== ЗАПУСК ====================
async def main():
    logger.info("Бот запускается...")
    logger.info("Загружена статистика: %d пользователей", len(stats["total_users"]))
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
