# Исправлено для aiogram 3.7+
#!/usr/bin/env python3
"""
[Исправленная версия для aiogram 3.7+]

Telegram бот для подготовки к экзамену по биологии.
"""

import json
import logging
import random
import os
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8469931783:AAFhj045ghZz4MBDBzfqP2Vs-SN4tucAngo")

# Загрузка билетов
try:
    with open("tickets.json","r",encoding="utf-8") as f:
        TICKETS=json.load(f)
    TICKETS_DICT={t["num"]:t for t in TICKETS}
except FileNotFoundError:
    logger.error("Файл tickets.json не найден.")
    TICKETS=[]
    TICKETS_DICT={}
except json.JSONDecodeError:
    logger.error("Файл tickets.json поврежден или содержит некорректный JSON.")
    TICKETS=[]
    TICKETS_DICT={}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def get_ticket_keyboard():
    builder = InlineKeyboardBuilder()
    for i in range(1, 51):
        builder.button(text=f"Билет {i}", callback_data=f"ticket:{i}")
        if i % 5 == 0:
            builder.adjust(5)
    builder.row(
        InlineKeyboardButton(text="🎲 Случайный билет", callback_data="random")
    )
    return builder.as_markup()

def get_questions_keyboard(ticket_num: int):
    ticket = TICKETS_DICT[ticket_num]
    builder = InlineKeyboardBuilder()
    for q in ticket["questions"]:
        title_short = q["title"][:55] + "..." if len(q["title"]) > 55 else q["title"]
        builder.button(
            text=f"Вопрос {q['num']}",
            callback_data=f"show_q:{ticket_num}:{q['num']}"
        )
    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(text="🔄 Другой билет", callback_data="choose_ticket"),
        InlineKeyboardButton(text="🎲 Random", callback_data="random")
    )
    return builder.as_markup()

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Бот для подготовки к экзамену по биологии.\n\n"
        "Выбери билет или нажми «Случайный билет»:",
        reply_markup=get_ticket_keyboard()
    )

@dp.message(Command("random"))
async def cmd_random(message: Message):
    await send_random_ticket(message)

async def send_random_ticket(message_or_call):
    ticket = random.choice(TICKETS)
    text = f"🎲 <b>Случайный билет №{ticket['num']}</b>\n\n"
    for q in ticket["questions"]:
        text += f"<b>Вопрос {q['num']}.</b> {q['title']}\n\n"
    text += "Нажми кнопку ниже, чтобы посмотреть ответ."

    if isinstance(message_or_call, Message):
        await message_or_call.answer(text, parse_mode="HTML", reply_markup=get_questions_keyboard(ticket["num"]))
    else:
        await message_or_call.message.edit_text(text, parse_mode="HTML", reply_markup=get_questions_keyboard(ticket["num"]))

@dp.callback_query(F.data == "random")
async def cb_random(callback: CallbackQuery):
    await callback.answer()
    await send_random_ticket(callback)

@dp.callback_query(F.data == "choose_ticket")
async def cb_choose_ticket(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Выбери билет:", reply_markup=get_ticket_keyboard())

@dp.callback_query(F.data.startswith("ticket:"))
async def cb_ticket(callback: CallbackQuery):
    await callback.answer()
    ticket_num = int(callback.data.split(":")[1])
    ticket = TICKETS_DICT[ticket_num]
    text = f"📘 <b>Билет №{ticket_num}</b>\n\n"
    for q in ticket["questions"]:
        text += f"<b>Вопрос {q['num']}.</b> {q['title']}\n\n"
    text += "Выбери вопрос, чтобы посмотреть ответ:"
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_questions_keyboard(ticket_num))

@dp.callback_query(F.data.startswith("show_q:"))
async def cb_show_question(callback: CallbackQuery):
    await callback.answer()
    _, ticket_num, q_num = callback.data.split(":")
    ticket_num = int(ticket_num)
    q_num = int(q_num)
    ticket = TICKETS_DICT[ticket_num]
    question = next((q for q in ticket["questions"] if q["num"] == q_num), None)
    if not question:
        return
    answer_text = f"📘 <b>Билет №{ticket_num} — Вопрос {q_num}</b>\n\n<b>{question['title']}</b>\n\n{question['answer']}"
    await callback.message.edit_text(answer_text, parse_mode="HTML")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())