import json
import logging
import random
import os
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ChatMemberStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8469931783:AAFhj045ghZz4MBDBzfqP2Vs-SN4tucAngo")
CHANNEL_ID = "@Vmeda_examen"

# ==================== ЗАГРУЗКА ДАННЫХ ====================
try:
    with open("tickets.json", "r", encoding="utf-8") as f:
        TICKETS = json.load(f)
    TICKETS_DICT = {str(t["num"]): t for t in TICKETS}
except:
    TICKETS = []
    TICKETS_DICT = {}

try:
    with open("questions.json", "r", encoding="utf-8") as f:
        QUESTIONS = json.load(f)
except:
    QUESTIONS = {}

stats = {
    "total_users": set(),
    "start_count": 0,
    "random_ticket_used": 0,
    "random_question_used": 0,
    "question_opened": {}
}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ==================== ПРОВЕРКА ПОДПИСКИ ====================
async def is_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
    except:
        return False

# ==================== КЛАВИАТУРЫ ====================
def get_main_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="📘 Билеты", callback_data="menu_tickets")
    builder.button(text="📝 Готовиться по вопросам", callback_data="menu_questions")
    builder.adjust(1)
    return builder.as_markup()

def get_ticket_keyboard():
    builder = InlineKeyboardBuilder()
    for i in range(1, 51):
        builder.button(text=f"📘 {i}", callback_data=f"ticket:{i}")
    builder.adjust(4)
    builder.row(InlineKeyboardButton(text="🎲 Случайный билет", callback_data="random_ticket"))
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
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
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()

def get_question_page_keyboard(page: int):
    builder = InlineKeyboardBuilder()
    start = (page - 1) * 50 + 1
    end = min(page * 50, 185)
    
    for i in range(start, end + 1, 5):
        row = [InlineKeyboardButton(text=str(num), callback_data=f"q:{num}") for num in range(i, min(i+5, end+1))]
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

# ==================== КОМАНДЫ ====================
@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    stats["total_users"].add(user_id)
    stats["start_count"] += 1

    if not await is_subscribed(user_id):
        await message.answer(
            "👋 Привет!\n\nЧтобы пользоваться ботом, подпишись на канал:\n"
            "https://t.me/Vmeda_examen\n\nПосле подписки нажми /start ещё раз."
        )
        return

    await message.answer("👋 Привет! Выбери режим подготовки:", reply_markup=get_main_menu())

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Уникальных пользователей: <b>{len(stats['total_users'])}</b>\n"
        f"▶️ Запусков: <b>{stats['start_count']}</b>\n"
        f"❓ Вопросов просмотрено: <b>{sum(stats['question_opened'].values())}</b>\n"
    )
    await message.answer(text, parse_mode="HTML")

# ==================== МЕНЮ ====================
@dp.callback_query(F.data == "menu_tickets")
async def cb_menu_tickets(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("📘 Выбери билет:", reply_markup=get_ticket_keyboard())

@dp.callback_query(F.data == "menu_questions")
async def cb_menu_questions(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "📝 <b>Готовиться по вопросам</b>\n\nВыбери страницу:",
        parse_mode="HTML",
        reply_markup=get_questions_main_menu()
    )

@dp.callback_query(F.data == "back_to_main")
async def cb_back_to_main(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Выбери режим подготовки:", reply_markup=get_main_menu())

# ==================== БИЛЕТЫ ====================
@dp.callback_query(F.data == "random_ticket")
async def cb_random_ticket(callback: CallbackQuery):
    if not await is_subscribed(callback.from_user.id):
        await callback.answer("Подпишись на канал!", show_alert=True)
        return
    
    stats["random_ticket_used"] += 1
    ticket = random.choice(TICKETS)
    text = f"📘 <b>Билет {ticket['num']}</b>\n\n{ticket.get('content', 'Содержимое билета...')}"
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_ticket_keyboard())

@dp.callback_query(F.data.startswith("ticket:"))
async def cb_ticket(callback: CallbackQuery):
    ticket_num = callback.data.split(":")[1]
    if ticket_num in TICKETS_DICT:
        ticket = TICKETS_DICT[ticket_num]
        text = f"📘 <b>Билет {ticket_num}</b>\n\n{ticket.get('content', 'Содержимое билета...')}"
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_ticket_keyboard())
    else:
        await callback.answer("Билет не найден")

# ==================== ВОПРОСЫ ====================
@dp.callback_query(F.data.startswith("qpage:"))
async def cb_question_page(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    await callback.answer()
    await callback.message.edit_text(
        f"📄 <b>Страница {page}</b>",
        parse_mode="HTML",
        reply_markup=get_question_page_keyboard(page)
    )

@dp.callback_query(F.data.startswith("q:"))
async def cb_show_question(callback: CallbackQuery):
    q_num = callback.data.split(":")[1]
    if q_num in QUESTIONS:
        stats["question_opened"][q_num] = stats["question_opened"].get(q_num, 0) + 1
        q = QUESTIONS[q_num]
        text = f"❓ <b>Вопрос {q_num}</b>\n\n<b>{q['title']}</b>\n\n{q['answer']}"
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_questions_main_menu())
    else:
        await callback.answer("Вопрос не найден")

@dp.callback_query(F.data == "question_random")
async def cb_question_random(callback: CallbackQuery):
    if not QUESTIONS:
        await callback.answer("Вопросы не загружены")
        return
    stats["random_question_used"] += 1
    q_num = random.choice(list(QUESTIONS.keys()))
    q = QUESTIONS[q_num]
    text = f"❓ <b>Вопрос {q_num}</b>\n\n<b>{q['title']}</b>\n\n{q['answer']}"
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_questions_main_menu())

@dp.callback_query(F.data == "question_by_number")
async def cb_question_by_number(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Введите номер вопроса (1–185):", parse_mode="HTML")

@dp.message(F.text.isdigit())
async def handle_question_number(message: Message):
    q_num = message.text.strip()
    if q_num in QUESTIONS:
        q = QUESTIONS[q_num]
        text = f"❓ <b>Вопрос {q_num}</b>\n\n<b>{q['title']}</b>\n\n{q['answer']}"
        await message.answer(text, parse_mode="HTML", reply_markup=get_questions_main_menu())
    else:
        await message.answer("Вопрос с таким номером не найден.")

# ==================== ЗАПУСК ====================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
