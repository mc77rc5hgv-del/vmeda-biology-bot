import json
import logging
import random
import os
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, ChatMemberUpdated
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ChatMemberStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8469931783:AAFhj045ghZz4MBDBzfqP2Vs-SN4tucAngo")
CHANNEL_ID = "@Vmeda_examen"   # ← твой канал

try:
    with open("tickets.json", "r", encoding="utf-8") as f:
        TICKETS = json.load(f)
    TICKETS_DICT = {t["num"]: t for t in TICKETS}
except Exception as e:
    logger.error(f"Ошибка загрузки tickets.json: {e}")
    TICKETS = []
    TICKETS_DICT = {}

# Простая статистика (в памяти)
stats = {
    "total_users": set(),
    "start_count": 0,
    "random_used": 0,
    "ticket_opened": {}
}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


async def is_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
    except:
        return False


def get_ticket_keyboard():
    builder = InlineKeyboardBuilder()
    for i in range(1, 51):
        builder.button(text=f"📘 {i}", callback_data=f"ticket:{i}")
    builder.adjust(4)  # 4 кнопки в ряд — крупнее
    builder.row(InlineKeyboardButton(text="🎲 Случайный билет", callback_data="random"))
    return builder.as_markup()


def get_questions_keyboard(ticket_num: int):
    ticket = TICKETS_DICT.get(ticket_num)
    if not ticket:
        return None

    builder = InlineKeyboardBuilder()
    for q in ticket["questions"]:
        builder.button(text=f"❓ Вопрос {q['num']}", callback_data=f"show_q:{ticket_num}:{q['num']}")
    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(text="🔙 Назад к списку билетов", callback_data="choose_ticket"),
        InlineKeyboardButton(text="🎲 Random", callback_data="random")
    )
    return builder.as_markup()


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
        "👋 Привет! Бот для подготовки к экзамену по биологии.\n\n"
        "Выбери билет или нажми «Случайный билет»:",
        reply_markup=get_ticket_keyboard()
    )


@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    text = (
        "📊 <b>Статистика бота</b>\n\n"
        f"👥 Уникальных пользователей: <b>{len(stats['total_users'])}</b>\n"
        f"▶️ Запусков бота: <b>{stats['start_count']}</b>\n"
        f"🎲 Использовано «Случайный билет»: <b>{stats['random_used']}</b>\n"
    )
    await message.answer(text, parse_mode="HTML")


@dp.callback_query(F.data == "random")
async def cb_random(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not await is_subscribed(user_id):
        await callback.answer("Подпишись на канал, чтобы пользоваться ботом!", show_alert=True)
        return

    stats["random_used"] += 1
    await callback.answer()
    await send_random_ticket(callback)


async def send_random_ticket(message_or_call):
    if not TICKETS:
        text = "Билеты пока не загружены."
        if isinstance(message_or_call, Message):
            await message_or_call.answer(text)
        else:
            await message_or_call.message.edit_text(text)
        return

    ticket = random.choice(TICKETS)
    text = f"🎲 <b>Случайный билет №{ticket['num']}</b>\n\n"
    for q in ticket["questions"]:
        text += f"<b>Вопрос {q['num']}.</b> {q['title']}\n\n"

    keyboard = get_questions_keyboard(ticket["num"])

    if isinstance(message_or_call, Message):
        await message_or_call.answer(text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await message_or_call.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)


@dp.callback_query(F.data == "choose_ticket")
async def cb_choose_ticket(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Выбери билет:", reply_markup=get_ticket_keyboard())


@dp.callback_query(F.data.startswith("ticket:"))
async def cb_ticket(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not await is_subscribed(user_id):
        await callback.answer("Подпишись на канал, чтобы пользоваться ботом!", show_alert=True)
        return

    await callback.answer()
    ticket_num = int(callback.data.split(":")[1])
    ticket = TICKETS_DICT.get(ticket_num)
    if not ticket:
        return

    # Статистика
    stats["ticket_opened"][ticket_num] = stats["ticket_opened"].get(ticket_num, 0) + 1

    text = f"📘 <b>Билет №{ticket_num}</b>\n\n"
    for q in ticket["questions"]:
        text += f"<b>Вопрос {q['num']}.</b> {q['title']}\n\n"

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_questions_keyboard(ticket_num))


@dp.callback_query(F.data.startswith("show_q:"))
async def cb_show_question(callback: CallbackQuery):
    await callback.answer()
    _, ticket_num, q_num = callback.data.split(":")
    ticket_num = int(ticket_num)
    q_num = int(q_num)

    ticket = TICKETS_DICT.get(ticket_num)
    if not ticket:
        return

    question = next((q for q in ticket["questions"] if q["num"] == q_num), None)
    if not question:
        return

    answer_text = (
        f"📘 <b>Билет №{ticket_num} — Вопрос {q_num}</b>\n\n"
        f"<b>{question['title']}</b>\n\n"
        f"{question['answer']}"
    )

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔙 Назад к вопросам", callback_data=f"ticket:{ticket_num}"),
        InlineKeyboardButton(text="🎲 Random", callback_data="random")
    )

    await callback.message.edit_text(answer_text, parse_mode="HTML", reply_markup=builder.as_markup())


async def main():
    if not TICKETS:
        logger.error("Билеты не загружены!")
        return
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
