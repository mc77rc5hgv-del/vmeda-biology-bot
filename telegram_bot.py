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

# ==================== ДАННЫЕ ====================
try:
    with open("tickets.json", "r", encoding="utf-8") as f:
        TICKETS = json.load(f)
    TICKETS_DICT = {t["num"]: t for t in TICKETS}
except:
    TICKETS = []
    TICKETS_DICT = {}

try:
    with open("questions.json", "r", encoding="utf-8") as f:
        QUESTIONS = json.load(f)          # { "1": {"title": "...", "answer": "..."}, ... }
except:
    QUESTIONS = {}

# Статистика
stats = {
    "total_users": set(),
    "start_count": 0,
    "random_used": 0,
    "ticket_opened": {},
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
    builder.row(InlineKeyboardButton(text="🎲 Случайный билет", callback_data="random"))
    return builder.as_markup()

def get_questions_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔢 Выбрать по номеру", callback_data="question_by_number")
    builder.button(text="🎲 Случайный вопрос", callback_data="question_random")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()

# ==================== КОМАНДЫ ====================
@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    stats["total_users"].add(user_id)
    stats["start_count"] += 1

    if not await is_subscribed(user_id):
        await message.answer(
            "👋 Привет!\n\n"
            "Чтобы пользоваться ботом, подпишись на наш канал:\n"
            "https://t.me/Vmeda_examen\n\n"
            "После подписки нажми /start ещё раз."
        )
        return

    await message.answer(
        "👋 Привет! Выбери режим подготовки:",
        reply_markup=get_main_menu()
    )

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    text = (
        "📊 <b>Статистика бота</b>\n\n"
        f"👥 Уникальных пользователей: <b>{len(stats['total_users'])}</b>\n"
        f"▶️ Запусков бота: <b>{stats['start_count']}</b>\n"
        f"🎲 Случайных билетов: <b>{stats['random_used']}</b>\n"
        f"❓ Вопросов просмотрено: <b>{sum(stats['question_opened'].values())}</b>\n"
    )
    await message.answer(text, parse_mode="HTML")

# ==================== МЕНЮ ====================
@dp.callback_query(F.data == "menu_tickets")
async def cb_menu_tickets(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Выбери билет:", reply_markup=get_ticket_keyboard())

@dp.callback_query(F.data == "menu_questions")
async def cb_menu_questions(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "📝 <b>Готовиться по вопросам</b>\n\n"
        "Выбери режим:",
        parse_mode="HTML",
        reply_markup=get_questions_menu()
    )

@dp.callback_query(F.data == "back_to_main")
async def cb_back_to_main(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Выбери режим подготовки:", reply_markup=get_main_menu())

# ==================== БИЛЕТЫ (старый функционал) ====================
@dp.callback_query(F.data == "random")
async def cb_random(callback: CallbackQuery):
    if not await is_subscribed(callback.from_user.id):
        await callback.answer("Подпишись на канал!", show_alert=True)
        return
    stats["random_used"] += 1
    await callback.answer()
    # ... (твой старый код отправки случайного билета)

@dp.callback_query(F.data.startswith("ticket:"))
async def cb_ticket(callback: CallbackQuery):
    # ... (твой старый код работы с билетами)
    pass

# ==================== ВОПРОСЫ (новый раздел) ====================
@dp.callback_query(F.data == "question_by_number")
async def cb_question_by_number(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "Введите номер вопроса (от 1 до 185):\n"
        "Например: <code>45</code>",
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "question_random")
async def cb_question_random(callback: CallbackQuery):
    if not QUESTIONS:
        await callback.answer("Вопросы пока не загружены.")
        return
    q_num = random.choice(list(QUESTIONS.keys()))
    await show_question(callback.message, q_num)

async def show_question(message, q_num: str):
    if q_num not in QUESTIONS:
        await message.answer("Вопрос не найден.")
        return

    q = QUESTIONS[q_num]
    text = f"❓ <b>Вопрос {q_num}</b>\n\n<b>{q['title']}</b>\n\n{q['answer']}"

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔙 К вопросам", callback_data="menu_questions"),
        InlineKeyboardButton(text="🎲 Случайный", callback_data="question_random")
    )

    await message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    stats["question_opened"][q_num] = stats["question_opened"].get(q_num, 0) + 1

@dp.message(F.text.regexp(r"^\d{1,3}$"))
async def handle_question_number(message: Message):
    q_num = message.text
    if q_num in QUESTIONS:
        await show_question(message, q_num)
    else:
        await message.answer("Вопрос с таким номером не найден. Введите число от 1 до 185.")

# ==================== ЗАПУСК ====================
async def main():
    if not TICKETS:
        logger.warning("tickets.json не загружен")
    if not QUESTIONS:
        logger.warning("questions.json не загружен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
