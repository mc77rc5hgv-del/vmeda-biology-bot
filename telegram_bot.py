import asyncio
import copy
import html
import io
import json
import logging
import random
import re
import os
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton, FSInputFile, BufferedInputFile, Update,
    BotCommand, BotCommandScopeDefault, BotCommandScopeChat, LabeledPrice,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from aiogram.dispatcher.event.bases import SkipHandler
from docx import Document as DocxDocument
from docx.shared import Pt

from ai import prompts as ai_prompts
from ai import rag as ai_rag
from ai import router as ai_router
from ai import service as ai_service
from ai.providers import gemini as ai_gemini
from ai.providers import openai as ai_openai
from ai.providers import xai as ai_xai
from ai.router import AIRefusalError
from ai.service import solve as solve_ai_request
from ai.vision import resize_image as resize_image_for_ai
from repositories import knowledge

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is not set. Set it as an environment variable (e.g. Railway → Variables) — "
        "never hardcode the token in source code."
    )
CHANNEL_ID = "@Vmeda_examen"
ADMIN_IDS = {1326779223, 8601892147}
STATS_DIR = os.getenv("STATS_DIR", ".")
STATS_FILE = os.path.join(STATS_DIR, "stats.json")
# Ключи провайдеров AI живут в ai/providers/*.py (каждый модуль сам читает свою переменную
# окружения) — эти два имени просто ре-экспортированы, потому что UI-уровень бота (кнопка
# "Отправить фото", текст меню AI) должен знать, доступен ли AI, не заглядывая внутрь пакета ai.
OPENAI_API_KEY = ai_openai.OPENAI_API_KEY  # без него AI-раздел показывает "временно недоступен"

DIVIDER = "━━━━━━━━━━━━━━"
IMAGES_DIR = "images"
ANATOMY_IMAGES_DIR = os.path.join(IMAGES_DIR, "anatomy")
HISTOLOGY_IMAGES_DIR = os.path.join(IMAGES_DIR, "histology")

# ==================== ЗАГРУЗКА ДАННЫХ ====================
# Контент (билеты/вопросы/теория/анатомия/гистология) грузится из JSON в repositories/knowledge.py
# (импортирован выше вместе с остальными модулями) — здесь только реэкспорт тех же имён под теми
# же названиями, чтобы все обращения по всему файлу (QUESTIONS[...], ANATOMY[...] и т.д.) остались
# без изменений.
TICKETS = knowledge.TICKETS
TICKETS_DICT = knowledge.TICKETS_DICT
QUESTIONS = knowledge.QUESTIONS
PHYSICS_QUESTIONS = knowledge.PHYSICS_QUESTIONS
PHYSICS_GRADE45_QUESTIONS = knowledge.PHYSICS_GRADE45_QUESTIONS
PHYSICS_EXTRA_QUESTIONS = knowledge.PHYSICS_EXTRA_QUESTIONS
CHEMISTRY_LABS = knowledge.CHEMISTRY_LABS
CHEMISTRY_THEORY = knowledge.CHEMISTRY_THEORY
CHEMISTRY_TASKS = knowledge.CHEMISTRY_TASKS
CHEMISTRY_THEORY_TICKETS = knowledge.CHEMISTRY_THEORY_TICKETS
CHEMISTRY_PRACTICE_TICKETS = knowledge.CHEMISTRY_PRACTICE_TICKETS
PHYSICS_TASKS = knowledge.PHYSICS_TASKS
PHYSICS_TEST_TICKETS = knowledge.PHYSICS_TEST_TICKETS
PHYSICS_TASK_TICKETS = knowledge.PHYSICS_TASK_TICKETS
PHYSICS_THEORY_TICKETS = knowledge.PHYSICS_THEORY_TICKETS
ANATOMY = knowledge.ANATOMY
ANATOMY_EXAM_TEST_PARTS = knowledge.ANATOMY_EXAM_TEST_PARTS
ANATOMY_EXAM_THEORY_SECTIONS = knowledge.ANATOMY_EXAM_THEORY_SECTIONS
ANATOMY_EXAM_PRACTICE_SECTIONS = knowledge.ANATOMY_EXAM_PRACTICE_SECTIONS
HISTOLOGY = knowledge.HISTOLOGY

ai_rag.configure(
    questions=QUESTIONS, physics_questions=PHYSICS_QUESTIONS, chemistry_theory=CHEMISTRY_THEORY,
    chemistry_theory_tickets=CHEMISTRY_THEORY_TICKETS, chemistry_practice_tickets=CHEMISTRY_PRACTICE_TICKETS,
    anatomy=ANATOMY,
)

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
            data.setdefault("helperchat_promo_seen", {})
            data.setdefault("referrals", {})
            data.setdefault("referred_by", {})
            data.setdefault("referral_warnings", {})
            data.setdefault("user_names", {})
            data.setdefault("user_username", {})
            data.setdefault("usernames", {})
            data.setdefault("manual_access_granted", [])
            data.setdefault("manual_anatomy_demo_granted", [])
            data.setdefault("assistant_admins", [])
            data.setdefault("referral_battle", None)
            data.setdefault("donations_stars_total", 0)
            data.setdefault("donations_stars_count", 0)
            data.setdefault("donor_stars", {})
            data.setdefault("donor_rubles", {})
            data.setdefault("donor_hide_name", {})
            data.setdefault("temporary_access", {})
            data.setdefault("subscriptions", {})
            data.setdefault("section_promos", {})
            data.setdefault("histology_warnings", {})
            data.setdefault("histology_temp_access", {})
            data.setdefault("rollcall_confirmed", {})
            data.setdefault("anatomy_latin_scores", {})
            data.setdefault("anatomy_exam_test_scores", {})
            data.setdefault("anatomy_exam_test_mode", {})
            data.setdefault("anatomy_exam_flash_scores", {})
            data.setdefault("ai_usage", {})
            data.setdefault("ai_cost_totals", {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
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
        "helperchat_promo_seen": {},
        "referrals": {},
        "referred_by": {},
        "referral_warnings": {},
        "user_names": {},
        "user_username": {},
        "usernames": {},
        "manual_access_granted": [],
        "manual_anatomy_demo_granted": [],
        "assistant_admins": [],
        "referral_battle": None,
        "donations_stars_total": 0,
        "donations_stars_count": 0,
        "donor_stars": {},
        "donor_rubles": {},
        "donor_hide_name": {},
        "temporary_access": {},
        "subscriptions": {},
        "section_promos": {},
        "histology_warnings": {},
        "histology_temp_access": {},
        "rollcall_confirmed": {},
        "anatomy_latin_scores": {},
        "anatomy_exam_test_scores": {},
        "anatomy_exam_test_mode": {},
        "anatomy_exam_flash_scores": {},
        "ai_usage": {},
        "ai_cost_totals": {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
    }

# Один воркер сериализует записи на диск и не даёт им блокировать event loop бота.
_stats_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stats-writer")

def _write_stats_file(data: dict) -> None:
    tmp_path = f"{STATS_FILE}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, STATS_FILE)

def _log_stats_write_result(future) -> None:
    exc = future.exception()
    if exc is not None:
        logger.error("Не удалось сохранить статистику: %s", exc)

def save_stats() -> None:
    # Снимок делаем сразу (deepcopy — быстро), сама запись на диск уходит в отдельный поток.
    data = copy.deepcopy(stats)
    data["total_users"] = list(data["total_users"])
    future = _stats_executor.submit(_write_stats_file, data)
    future.add_done_callback(_log_stats_write_result)

stats = load_stats()

# ==================== ВРЕМЕННЫЕ ПРОМО-ОКНА ДОСТУПА ДЛЯ РАЗДЕЛОВ ====================
def start_section_promo(section: str, duration_seconds: int) -> float:
    """Делает раздел (по ключу, например "histology") бесплатным для всех до истечения окна."""
    until = time.time() + duration_seconds
    stats.setdefault("section_promos", {})[section] = until
    save_stats()
    return until

def is_section_promo_active(section: str) -> bool:
    return time.time() < stats.get("section_promos", {}).get(section, 0)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ==================== ЕЖЕДНЕВНОЕ НАПОМИНАНИЕ ПРО HELPERCHAT_BOT ====================
HELPERCHAT_PROMO_ENABLED = False  # временно отключено по просьбе — включить обратно, поставив True
HELPERCHAT_URL = "https://t.me/Helperchat_bot?start=vmeda"

def get_helperchat_promo_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 Запустить Helperchat_bot", url=HELPERCHAT_URL)
    return builder.as_markup()

async def send_helperchat_promo_if_new_day(user_id: int) -> None:
    today = date.today().isoformat()
    seen = stats["helperchat_promo_seen"]
    if seen.get(str(user_id)) == today:
        return
    seen[str(user_id)] = today
    save_stats()
    try:
        await bot.send_message(
            user_id,
            "🚀 <b>Не забудь запустить нашего бота-помощника</b>\n\n"
            "Он тоже пригодится для подготовки — жми и запускай в один тап:\n"
            f"👉 {HELPERCHAT_URL}",
            parse_mode="HTML",
            reply_markup=get_helperchat_promo_keyboard()
        )
    except Exception:
        logger.exception("Не удалось отправить напоминание про Helperchat_bot пользователю %s", user_id)

@dp.update.outer_middleware()
async def helperchat_promo_middleware(handler, event: Update, data):
    user = None
    if event.message:
        user = event.message.from_user
    elif event.callback_query:
        user = event.callback_query.from_user
    if HELPERCHAT_PROMO_ENABLED and user and not user.is_bot:
        await send_helperchat_promo_if_new_day(user.id)
    return await handler(event, data)

# ==================== РЕФЕРАЛЬНАЯ СИСТЕМА ====================
BOT_USERNAME = "VMEDA_examen_bot"
REFERRAL_FULL_ACCESS_THRESHOLD = 4  # столько рефералов нужно, чтобы открыть доступ навсегда
REFERRAL_WARNING_THRESHOLD = 3  # столько предупреждений даём, прежде чем закрыть доступ
REFERRAL_WARNING_COOLDOWN_SECONDS = 4 * 60 * 60  # не чаще одного предупреждения раз в 4 часа
TEMP_ACCESS_GRANT_SECONDS = 7 * 24 * 60 * 60  # длительность временного восстановления доступа
GLOBAL_PROMO_SECONDS = 24 * 60 * 60  # длительность полного открытия всех разделов всем (раздел "global")
GLOBAL_PROMO_12H_SECONDS = 12 * 60 * 60  # укороченная версия того же промо, на 12 часов

def get_referral_link(user_id: int) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"

def get_referral_count(user_id: int) -> int:
    return len(stats["referrals"].get(str(user_id), []))

def get_temp_access_expiry(user_id: int) -> float:
    return stats["temporary_access"].get(str(user_id), 0)

def has_temp_access(user_id: int) -> bool:
    return time.time() < get_temp_access_expiry(user_id)

# ==================== ПЛАТНАЯ ПОДПИСКА ====================
# Тарифы 1-4 — старая линейка (историческая). Тариф 1 остаётся в продаже (тариф «Месяц»),
# тарифы 2/3/4 сняты с продажи ("retired": True) — их условия НЕ меняются задним числом,
# они просто больше не показываются в меню покупки. У уже купивших их людей доступ
# продолжает работать ровно как был обещан на момент покупки.
# Тарифы 5-10 — новая линейка (актуальный прайс-лист).
TIER1_HISTOLOGY_DEADLINE = time.mktime(date(2027, 1, 1).timetuple())  # легаси: гистология по СТАРЫМ выдачам тарифа 1 — до конца 2026 года
JULY_END_2026 = time.mktime(date(2026, 8, 1).timetuple())  # тариф «Месяц» — предпросмотр Гистологии до конца июля 2026
OCT_2026_CUTOFF = time.mktime(date(2026, 10, 1).timetuple())  # тариф 239₽ — до 1 октября 2026
NOV_END_2026_CUTOFF = time.mktime(date(2026, 12, 1).timetuple())  # тариф 389₽ — до конца ноября 2026
FEB_2027_CUTOFF = time.mktime(date(2027, 2, 1).timetuple())  # тариф 749₽ — до февраля 2027
# «До конца второго курса» — точная дата учебного календаря не была уточнена, взята оценка
# (конец лета 2027). Поправь SECOND_YEAR_END_2027, если известна точная дата окончания 2 курса.
SECOND_YEAR_END_2027 = time.mktime(date(2027, 9, 1).timetuple())

SUBSCRIPTION_TIERS = {
    1: {
        "title": "Месяц — Биология, Физика, Химия",
        "short": "1 месяц, 3 экзамена",
        "emoji": "🔓",
        "price_rub": 89,
        "price_stars": 89,
        "duration_days": 30,
        "expires_at": None,
        "subject_choice_required": False,
        "histology_until_rule": JULY_END_2026,
        "anatomy": False,
        "biology_download": False,
        "cheat_sheets": False,
        "menu_number": 3,
        "joke": "ЭНЕРГЕТИК 🤮 или УСПЕШНАЯ СДАЧА ЭКЗАМЕНА 😇",
        "benefits": [
            "Полный доступ к Биологии, Физике и Химии на 30 дней",
            "🔬 Плюс предпросмотр Гистологии — доступен сейчас, до конца июля 2026 года",
            "Скачивание файлов с ответами — по Физике и Химии",
            "Не нужно ждать и звать друзей — доступ открывается сразу после оплаты",
            "Подходит и для подготовки к текущим практическим занятиям",
        ],
    },
    2: {
        "title": "Навсегда — Биология, Физика, Химия",
        "short": "навсегда, 3 экзамена",
        "scope": "gated",
        "duration_days": None,
        "price_rub": 239,
        "price_stars": 239,
        "emoji": "♾️",
        "early_histology": True,
        "retired": True,
        "joke": "маленькая шаверма 🥙 или УСПЕШНАЯ СДАЧА ЭКЗАМЕНОВ 😇",
        "benefits": [
            "Полный доступ к Биологии, Физике и Химии — один раз и навсегда",
            "🔬 Плюс ранний доступ к разделу Гистологии — она уже полностью готова",
            "Дешевле, чем 3 месячные подписки, а действует бессрочно",
        ],
    },
    3: {
        "title": "Год — все экзамены",
        "short": "1 год, все разделы",
        "scope": "all",
        "duration_days": 365,
        "price_rub": 899,
        "price_stars": 899,
        "emoji": "🚀",
        "retired": True,
        "joke": "2 шавермы 🥙🥙 или ПОДПИСКА НА ГОД 🚀",
        "benefits": [
            "Доступ вообще ко всем разделам бота на целый год",
            "Плюс Анатомия и уже полностью готовая Гистология — уже сейчас, до их открытия всем остальным",
        ],
    },
    4: {
        "title": "6 лет — все экзамены",
        "short": "6 лет, все разделы",
        "scope": "all",
        "duration_days": 6 * 365,
        "price_rub": 2499,
        "price_stars": 2499,
        "emoji": "👑",
        "retired": True,
        "joke": "2499₽ в кармане 💸 или успешно окончить академию 🎓",
        "benefits": [
            "Доступ ко всем разделам бота на весь срок обучения в академии",
            "Анатомия и уже полностью готовая Гистология, а также все будущие разделы — сразу, без ожиданий",
        ],
    },
    5: {
        # temporarily off sale (not a permanent retirement like 2/3/4) — flag removable later
        "retired": True,
        "title": "3 дня — один предмет на выбор",
        "short": "3 дня, 1 предмет",
        "emoji": "⚡",
        "price_rub": 49,
        "price_stars": 49,
        "duration_days": 3,
        "expires_at": None,
        "subject_choice_required": True,
        "histology_until_rule": None,
        "anatomy": False,
        "biology_download": False,
        "cheat_sheets": False,
        "menu_number": 4,
        "joke": "Меньше стакана кофе ☕ — но хватит ровно на один экзамен",
        "benefits": [
            "Доступ только к ОДНОМУ предмету на выбор — Биология, Физика или Химия — на 3 дня",
            "Идеально, если один-два экзамена уже сдал и остался последний рывок",
            "Не нужно ждать и звать друзей — доступ открывается сразу после оплаты",
            "Подходит и для подготовки к текущим практическим занятиям",
        ],
    },
    6: {
        "title": "До октября — Биология, Физика, Химия + Гистология",
        "short": "4 экзамена, до окт. 2026",
        "emoji": "🔬",
        "price_rub": 239,
        "price_stars": 239,
        "duration_days": None,
        "expires_at": OCT_2026_CUTOFF,
        "subject_choice_required": False,
        "histology_until_rule": "expiry",
        "anatomy": False,
        "biology_download": False,
        "cheat_sheets": False,
        "menu_number": 5,
        "benefits": [
            "Полный доступ к Биологии, Физике, Химии и уже готовой Гистологии — все 4 экзамена сразу",
            "Действует до 1 октября 2026 года",
            "Скачивание файлов с ответами — по Физике и Химии (кроме Биологии)",
            "Подходит и для подготовки к текущим практическим занятиям",
        ],
    },
    7: {
        "title": "До конца ноября — все 5 экзаменов",
        "short": "5 экзаменов, до нояб. 2026",
        "emoji": "🚀",
        "price_rub": 389,
        "price_stars": 389,
        "duration_days": None,
        "expires_at": NOV_END_2026_CUTOFF,
        "subject_choice_required": False,
        "histology_until_rule": "expiry",
        "anatomy": True,
        "biology_download": False,
        "cheat_sheets": False,
        "badge": "🔥 ХИТ ПРОДАЖ 🔥",
        "menu_number": 1,
        "benefits": [
            "Полный доступ ко всем 5 предметам — Биология, Физика, Химия, Гистология и досрочно Анатомия",
            "Действует до конца ноября 2026 года",
            "Скачивание файлов с ответами — по Физике и Химии (кроме Биологии)",
            "Подходит и для подготовки к текущим практическим занятиям",
        ],
    },
    8: {
        "title": "До февраля 2027 — все 5 экзаменов",
        "short": "5 экзаменов, до февр. 2027",
        "emoji": "🎯",
        "price_rub": 749,
        "price_stars": 749,
        "duration_days": None,
        "expires_at": FEB_2027_CUTOFF,
        "subject_choice_required": False,
        "histology_until_rule": "expiry",
        "anatomy": True,
        "biology_download": False,
        "cheat_sheets": False,
        "menu_number": 6,
        "benefits": [
            "Полный доступ ко всем 5 предметам — Биология, Физика, Химия, Гистология и досрочно Анатомия",
            "Действует до февраля 2027 года — хватит на весь учебный год без повторной оплаты",
            "Скачивание файлов с ответами — по Физике и Химии (кроме Биологии)",
            "Подходит и для подготовки к текущим практическим занятиям",
        ],
    },
    9: {
        "title": "До конца 2 курса — всё, включая зачёты и диагностики",
        "short": "всё + зачёты, до конца 2 курса",
        "emoji": "👑",
        "price_rub": 1119,
        "price_stars": 1119,
        "duration_days": None,
        "expires_at": SECOND_YEAR_END_2027,
        "subject_choice_required": False,
        "histology_until_rule": "expiry",
        "anatomy": True,
        "biology_download": True,
        "cheat_sheets": True,
        "badge": "🔥 РЕКОМЕНДОВАНО 🔥",
        "menu_number": 2,
        "benefits": [
            "Полный доступ ко всем предметам — Биология, Физика, Химия, Гистология, Анатомия",
            "Плюс текущие зачёты, контрольные и диагностики по мере их появления в боте",
            "Скачивание файлов с ответами — включая Биологию — и готовых шпаргалок для распечатки",
            "Действует до конца второго курса",
            "Подходит и для подготовки к текущим практическим занятиям",
        ],
    },
    10: {
        "title": "6 лет — абсолютно всё",
        "short": "6 лет, абсолютно всё",
        "emoji": "💎",
        "price_rub": 3899,
        "price_stars": 3899,
        "duration_days": 6 * 365,
        "expires_at": None,
        "subject_choice_required": False,
        "histology_until_rule": "expiry",
        "anatomy": True,
        "biology_download": True,
        "cheat_sheets": True,
        "badge": "🔥 HOT 🔥",
        "joke": "Дальше будет только дороже — бери, пока не подняли цену",
        "menu_number": 7,
        "benefits": [
            "АБСОЛЮТНО ПОЛНЫЙ и РАННИЙ доступ ко всем зачётам, экзаменам и контрольным по всем предметам",
            "Один платёж на все 6 лет учёбы в академии — включая всё, что появится в боте позже",
            "Скачивание всех файлов с ответами и шпаргалок для распечатки",
            "Подходит и для подготовки к текущим практическим занятиям",
            "⏫ Цена вырастет позже — сейчас это самая низкая стоимость этого тарифа",
        ],
    },
    11: {
        "title": "2 года — абсолютно всё",
        "short": "2 года, абсолютно всё",
        "emoji": "🏆",
        "price_rub": 1999,
        "price_stars": 1999,
        "duration_days": 2 * 365,
        "expires_at": None,
        "subject_choice_required": False,
        "histology_until_rule": "expiry",
        "anatomy": True,
        "biology_download": True,
        "cheat_sheets": True,
        "menu_number": 8,
        "joke": "Дешевле, чем повторная сдача пересдачи",
        "benefits": [
            "АБСОЛЮТНО ПОЛНЫЙ доступ ко всем предметам — Биология, Физика, Химия, Гистология, Анатомия",
            "Один платёж на 2 года учёбы — включая всё, что появится в боте позже",
            "Скачивание всех файлов с ответами и готовых шпаргалок для распечатки",
            "Подходит и для подготовки к текущим практическим занятиям",
        ],
    },
}
ACTIVE_SUBSCRIPTION_TIERS = {t: cfg for t, cfg in SUBSCRIPTION_TIERS.items() if not cfg.get("retired")}

SEPTEMBER_PRICE_INCREASE = 1.4  # с сентября цены на все тарифы вырастут на 40%

def september_price(price: int) -> int:
    return round(price * SEPTEMBER_PRICE_INCREASE)

DISCOUNT_RATE = 0.10  # разовая скидка 10% для пользователей без рефералов, промо-рассылкой

def discount_price(price: int) -> int:
    return round(price * (1 - DISCOUNT_RATE))

def get_tier_price_line(cfg: dict) -> str:
    """Текущая цена + зачёркнутая цена на 40% выше — с сентября будет дороже."""
    return (
        f"<b>{cfg['price_rub']}₽</b> <s>{september_price(cfg['price_rub'])}₽</s> / "
        f"<b>{cfg['price_stars']}⭐</b> <s>{september_price(cfg['price_stars'])}⭐</s>"
    )

def sorted_active_tiers() -> list[tuple[int, dict]]:
    """Тарифы в порядке показа (menu_number), а не в порядке ключей SUBSCRIPTION_TIERS —
    так самые выгодные для нас предложения можно выводить первыми, не трогая сами tier id."""
    return sorted(ACTIVE_SUBSCRIPTION_TIERS.items(), key=lambda kv: kv[1].get("menu_number", 999))

def cheapest_active_tier(predicate=lambda cfg: True) -> dict:
    """Самый дешёвый тариф из числа продающихся сейчас, подходящий под predicate — чтобы не
    хардкодить цены/тарифы в текстах отдельно от SUBSCRIPTION_TIERS (см. CLAUDE.md pitfalls)."""
    candidates = [cfg for cfg in ACTIVE_SUBSCRIPTION_TIERS.values() if predicate(cfg)]
    return min(candidates, key=lambda c: c["price_rub"])

def cheapest_gated3_tier() -> dict:
    """Самый дешёвый тариф, открывающий все три предмета Био/Физ/Хим (не тариф с выбором
    одного предмета)."""
    return cheapest_active_tier(lambda cfg: not cfg.get("subject_choice_required"))

def cheapest_histology_tier() -> dict:
    return cheapest_active_tier(lambda cfg: cfg.get("histology_until_rule") is not None)

def cheapest_anatomy_tier() -> dict:
    return cheapest_active_tier(lambda cfg: cfg.get("anatomy"))

def cheapest_biology_download_tier() -> dict:
    return cheapest_active_tier(lambda cfg: cfg.get("biology_download"))

def get_subscription(user_id: int) -> dict:
    return stats["subscriptions"].get(str(user_id))

def has_active_subscription(user_id: int) -> bool:
    sub = get_subscription(user_id)
    if not sub:
        return False
    expires = sub.get("expires")
    return expires is None or time.time() < expires

def has_subject_access(user_id: int, subject: str) -> bool:
    """Доступ к конкретному гейтящемуся предмету (biology/physics/chemistry) — в отличие от
    has_free_access() учитывает, что тариф «3 дня, 1 предмет» открывает только ОДИН предмет."""
    if (
        is_admin_or_assistant(user_id)
        or is_section_promo_active("global")
        or get_referral_count(user_id) >= REFERRAL_FULL_ACCESS_THRESHOLD
        or user_id in stats["manual_access_granted"]
        or has_temp_access(user_id)
    ):
        return True
    sub = get_subscription(user_id)
    if not sub or not has_active_subscription(user_id):
        return False
    restricted = sub.get("restricted_subject")
    return restricted is None or restricted == subject

def _sub_has_histology(sub: dict) -> bool:
    if "histology_access" in sub:
        if not sub["histology_access"]:
            return False
        until = sub.get("histology_until")
        return until is None or time.time() < until
    # легаси-подписки, выданные до введения этого поля
    if sub.get("scope") == "all" or sub.get("early_histology", False):
        return True
    return sub.get("tier") == 1 and time.time() < TIER1_HISTOLOGY_DEADLINE

def _sub_has_anatomy(sub: dict) -> bool:
    if "anatomy" in sub:
        return bool(sub["anatomy"])
    return sub.get("scope") == "all"

def _sub_has_biology_download(sub: dict) -> bool:
    if "biology_download" in sub:
        return bool(sub["biology_download"])
    return sub.get("scope") == "all"

def has_subscription_scope_all(user_id: int) -> bool:
    """Легаси-предикат для старых подписок (scope="all"). Новый код использует
    has_subscription_anatomy_access()/biology_tickets_download_ok() напрямую."""
    sub = get_subscription(user_id)
    return bool(sub) and sub.get("scope") == "all" and has_active_subscription(user_id)

def has_subscription_histology_access(user_id: int) -> bool:
    sub = get_subscription(user_id)
    if not sub or not has_active_subscription(user_id):
        return False
    return _sub_has_histology(sub)

def has_subscription_anatomy_access(user_id: int) -> bool:
    sub = get_subscription(user_id)
    if not sub or not has_active_subscription(user_id):
        return False
    return _sub_has_anatomy(sub)

def biology_tickets_download_ok(user_id: int) -> bool:
    if is_admin_or_assistant(user_id):
        return True
    sub = get_subscription(user_id)
    if not sub or not has_active_subscription(user_id):
        return False
    return _sub_has_biology_download(sub)

def grant_subscription(user_id: int, tier: int, method: str, price: int, subject: str | None = None) -> None:
    cfg = SUBSCRIPTION_TIERS[tier]
    now = time.time()
    if cfg.get("expires_at") is not None:
        expires = cfg["expires_at"]
    elif cfg.get("duration_days") is not None:
        expires = now + cfg["duration_days"] * 86400
    else:
        expires = None

    rule = cfg.get("histology_until_rule")
    histology_access = rule is not None
    histology_until = None if rule in (None, "expiry") else rule

    stats["subscriptions"][str(user_id)] = {
        "tier": tier,
        "restricted_subject": subject if cfg.get("subject_choice_required") else None,
        "expires": expires,
        "histology_access": histology_access,
        "histology_until": histology_until,
        "anatomy": cfg.get("anatomy", False),
        "biology_download": cfg.get("biology_download", False),
        "cheat_sheets": cfg.get("cheat_sheets", False),
        "purchased_at": now,
        "method": method,
        "price": price,
    }
    save_stats()

def has_free_access(user_id: int) -> bool:
    return (
        is_admin_or_assistant(user_id)
        or is_section_promo_active("global")
        or get_referral_count(user_id) >= REFERRAL_FULL_ACCESS_THRESHOLD
        or user_id in stats["manual_access_granted"]
        or has_temp_access(user_id)
        or has_active_subscription(user_id)
    )

def get_exhausted_users() -> list:
    """ID пользователей, у которых счётчик предупреждений достиг порога и до сих пор нет доступа."""
    return [
        int(uid_str) for uid_str, entry in stats["referral_warnings"].items()
        if entry.get("count", 0) >= REFERRAL_WARNING_THRESHOLD and not has_free_access(int(uid_str))
    ]

def get_below_threshold_users() -> list:
    """ID пользователей, у которых прямо сейчас нет бесплатного доступа к предметным разделам —
    меньше REFERRAL_FULL_ACCESS_THRESHOLD рефералов и нет подписки/ручного доступа/временного доступа."""
    return [uid for uid in stats["total_users"] if not has_free_access(uid)]

SUBJECT_TITLES = {"biology": "Биологии", "physics": "Физике", "chemistry": "Химии"}
ADMIN_SUBJECT_LABELS_RU = {"Биология": "biology", "Физика": "physics", "Химия": "chemistry"}

def get_admin_tier_reply_keyboard() -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=f"{t} — {cfg['short']} — {cfg['price_rub']}₽")] for t, cfg in ACTIVE_SUBSCRIPTION_TIERS.items()]
    rows.append([KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)

def get_admin_subject_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Биология")],
            [KeyboardButton(text="Физика")],
            [KeyboardButton(text="Химия")],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True, one_time_keyboard=True
    )

def get_subscription_scope_label(sub: dict) -> str:
    restricted = sub.get("restricted_subject")
    if restricted:
        return f"только к {SUBJECT_TITLES[restricted]}"
    if sub.get("scope") == "all":
        return "ко всем разделам бота"
    parts = ["Биологии, Физике и Химии"]
    if _sub_has_histology(sub):
        parts.append("Гистологии")
    if _sub_has_anatomy(sub):
        parts.append("Анатомии")
    if len(parts) == 3:
        return "ко всем разделам бота"
    return "к " + ", ".join(parts)

def get_referral_status_text(user_id: int) -> str:
    count = get_referral_count(user_id)
    link = get_referral_link(user_id)
    if has_active_subscription(user_id):
        sub = get_subscription(user_id)
        cfg = SUBSCRIPTION_TIERS.get(sub["tier"], {})
        scope_label = get_subscription_scope_label(sub)
        return (
            f"👥 <b>Твои приглашения</b>\n{DIVIDER}\n\n"
            f"💎 У тебя активна подписка «{cfg.get('title', '')}» — доступ {scope_label}, "
            f"{format_subscription_expiry(sub['expires'])}.\n\n"
            "Рефералы тебе не нужны, но можно продолжать приглашать друзей и участвовать "
            "в <b>битве рефералов</b> за призы!\n\n"
            f"Твоя ссылка:\n{link}"
        )
    if count >= REFERRAL_FULL_ACCESS_THRESHOLD or user_id in stats["manual_access_granted"]:
        extra = f"Приглашено друзей: <b>{count}</b>\n" if count > 0 else ""
        return (
            f"👥 <b>Твои приглашения</b>\n{DIVIDER}\n\n"
            f"{extra}"
            "Доступ ко всем разделам бота открыт. Спасибо! 🎉\n\n"
            "⚔️ А ещё сейчас можно побороться за призы в <b>битве рефералов</b> — "
            "приглашай друзей дальше и попади в топ-5!\n\n"
            f"Твоя ссылка (можно приглашать ещё):\n{link}"
        )
    if has_temp_access(user_id):
        remaining = format_time_left(get_temp_access_expiry(user_id) - time.time())
        return (
            f"👥 <b>Твои приглашения</b>\n{DIVIDER}\n\n"
            f"🎁 Тебе временно открыт полный доступ ко всем разделам бота — осталось "
            f"<b>{remaining}</b>.\n\n"
            f"Приглашено друзей: <b>{count}</b> из {REFERRAL_FULL_ACCESS_THRESHOLD}\n\n"
            "Пригласи друзей уже сейчас, чтобы доступ остался открытым и после окончания "
            f"временного периода:\n{link}"
        )
    warn_count = stats["referral_warnings"].get(str(user_id), {}).get("count", 0)
    remaining_free = max(REFERRAL_WARNING_THRESHOLD - warn_count, 0)
    remaining_refs = max(REFERRAL_FULL_ACCESS_THRESHOLD - count, 0)
    if remaining_refs <= 1:
        invite_line = (
            "Отправь эту ссылку ещё одному другу — как только он нажмёт /start, "
            "у тебя откроется полный доступ ко всем разделам бота:"
        )
    else:
        friends_word = "двум друзьям" if remaining_refs == 2 else f"{remaining_refs} друзьям"
        invite_line = (
            f"Отправь эту ссылку ещё {friends_word} — как только они нажмут /start, "
            "у тебя откроется полный доступ ко всем разделам бота:"
        )
    return (
        f"👥 <b>Пригласи друзей</b>\n{DIVIDER}\n\n"
        f"{invite_line}\n\n"
        f"{link}\n\n"
        f"Приглашено друзей: <b>{count}</b> из {REFERRAL_FULL_ACCESS_THRESHOLD}\n"
        f"Осталось бесплатных заходов без рефералов: <b>{remaining_free}</b>\n\n"
        f"💎 Не хочешь ждать друзей? Открой доступ сразу оплатой!\n\n"
        f"🔥 Самые выгодные варианты — «{SUBSCRIPTION_TIERS[7]['short']}» за "
        f"{SUBSCRIPTION_TIERS[7]['price_rub']}₽ или «{SUBSCRIPTION_TIERS[9]['short']}» за "
        f"{SUBSCRIPTION_TIERS[9]['price_rub']}₽ ({SUBSCRIPTION_TIERS[9]['badge']}).\n\n"
        f"Также доступна подписка от {cheapest_gated3_tier()['price_rub']}₽. "
        "Жми «💎 Открыть доступ без рефералов» ниже.\n\n"
        "🌐 А ещё рекомендуем пользоваться @Medical_vpn_bot — жми «🚀 Запустить Medical_vpn_bot» ниже."
    )

RANK_MEDALS = ["🥇", "🥈", "🥉"]

def get_referral_leaderboard_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Обновить", callback_data="referral_leaderboard")
    builder.button(text="🔙 Назад в меню", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()

def get_referral_leaderboard_text(user_id: int = None) -> str:
    referrals = stats["referrals"]
    names = stats["user_names"]
    ranked = sorted(referrals.items(), key=lambda kv: len(kv[1]), reverse=True)
    ranked = [(uid, refs) for uid, refs in ranked if len(refs) > 0]
    if not ranked:
        return f"🏆 <b>Рейтинг приглашений</b>\n{DIVIDER}\n\nПока никто никого не пригласил — стань первым!"
    top = ranked[:10]
    lines = [f"🏆 <b>Рейтинг приглашений</b>\n{DIVIDER}\n"]
    uid_str = str(user_id) if user_id is not None else None
    for i, (uid, refs) in enumerate(top):
        rank_icon = RANK_MEDALS[i] if i < 3 else f"{i+1}."
        name = names.get(uid, f"Пользователь {uid}")
        you = " 👈 ты" if uid == uid_str else ""
        lines.append(f"{rank_icon} {name} — <b>{len(refs)}</b>{you}")
    if uid_str and uid_str not in dict(top):
        pos = next((i for i, (uid, _) in enumerate(ranked) if uid == uid_str), None)
        if pos is not None:
            lines.append("…")
            name = names.get(uid_str, "Ты")
            lines.append(f"{pos + 1}. {name} — <b>{len(referrals[uid_str])}</b> 👈 ты")
    lines.append("")
    lines.append(f"👤 Всего участников: <b>{len(ranked)}</b>")
    return "\n".join(lines)

# ==================== БИТВА РЕФЕРАЛОВ (ЛИМИТИРОВАННОЕ СОРЕВНОВАНИЕ) ====================
BATTLE_DURATION_SECONDS = 7 * 24 * 60 * 60
BATTLE_PLACE_COUNT = 5
BATTLE_PLACE_ICONS = ["🥇", "🥈", "🥉", "🏅", "🎖"]

# 1-3 место разыгрываются только среди тех, кто пригласил от этого числа друзей за битву.
# 4-5 место — без минимума, отдаются следующим по рейтингу.
BATTLE_TOP3_MIN_REFERRALS = 30

MEDICAL_VPN_URL = "https://t.me/Medical_vpn_bot?start=vmeda"

BATTLE_PRIZE_LABELS = [
    'подписка «6 лет — абсолютно всё» (<b>6 лет</b>, все предметы + Анатомия/Гистология) в '
    '<a href="https://t.me/VMEDA_examen_bot">VMEDA_examen_bot</a> + ВПН на <b>год</b> в '
    f'<a href="{MEDICAL_VPN_URL}">Medical_vpn_bot</a>',
    'полный доступ ко всем разделам <a href="https://t.me/VMEDA_examen_bot">VMEDA_examen_bot</a> '
    'на <b>год</b> + ВПН на <b>полгода</b> в '
    f'<a href="{MEDICAL_VPN_URL}">Medical_vpn_bot</a>',
    'Химия, Физика, Биология и ранний доступ к Гистологии <b>навсегда</b> в '
    '<a href="https://t.me/VMEDA_examen_bot">VMEDA_examen_bot</a> + ВПН на <b>месяц</b> в '
    f'<a href="{MEDICAL_VPN_URL}">Medical_vpn_bot</a>',
    'Химия, Физика, Биология и ранний доступ к Гистологии <b>навсегда</b> в '
    '<a href="https://t.me/VMEDA_examen_bot">VMEDA_examen_bot</a> + доступ к '
    '<a href="https://t.me/Helperchat_bot">Helperchat_bot</a>',
    'Химия, Физика, Биология и ранний доступ к Гистологии <b>навсегда</b> в '
    '<a href="https://t.me/VMEDA_examen_bot">VMEDA_examen_bot</a> + доступ к '
    '<a href="https://t.me/Helperchat_bot">Helperchat_bot</a>',
]
BATTLE_CHANNEL_POSTING_NOTICE = "📢 <b>ПОСТИНГ В TELEGRAM-КАНАЛЫ РАЗРЕШЁН 🤝</b>"

# Денежная оценка приза за место (задана вручную, не выводится из цен тарифов подписки).
BATTLE_PRIZE_VALUES_RUB = [5400, 2000, 1800, 1599, 1599]

def format_rub(amount: int) -> str:
    return f"{amount:,}".replace(",", " ")

def format_battle_savings_line(place_index: int) -> str:
    return f"💰🔥 Экономия: <b>~{format_rub(BATTLE_PRIZE_VALUES_RUB[place_index])}₽</b> 🔥💰"

def battle_place_icon(i: int) -> str:
    return BATTLE_PLACE_ICONS[i] if i < len(BATTLE_PLACE_ICONS) else f"{i + 1}."

def format_battle_prizes_block() -> str:
    lines = [
        f"{BATTLE_PLACE_ICONS[i]} <b>{i + 1} место</b> — {BATTLE_PRIZE_LABELS[i]}\n{format_battle_savings_line(i)}"
        for i in range(BATTLE_PLACE_COUNT)
    ]
    lines.append(
        f"\n🔒 1-3 место — только для тех, кто пригласит от <b>{BATTLE_TOP3_MIN_REFERRALS}</b> друзей за битву. "
        "4-5 место — без минимума, по числу приглашений."
    )
    return "\n".join(lines)

def is_battle_active() -> bool:
    battle = stats.get("referral_battle")
    return bool(battle and battle.get("active") and time.time() < battle.get("end_ts", 0))

def get_battle_gained(user_id: int) -> int:
    battle = stats.get("referral_battle")
    if not battle:
        return 0
    uid_str = str(user_id)
    current = len(stats["referrals"].get(uid_str, []))
    start = battle.get("snapshot", {}).get(uid_str, 0)
    return max(current - start, 0)

def get_battle_leaderboard(limit: int | None = 10):
    battle = stats.get("referral_battle")
    if not battle:
        return []
    snapshot = battle.get("snapshot", {})
    gained = []
    for uid_str, refs in stats["referrals"].items():
        diff = len(refs) - snapshot.get(uid_str, 0)
        if diff > 0:
            gained.append((uid_str, diff))
    gained.sort(key=lambda kv: kv[1], reverse=True)
    return gained if limit is None else gained[:limit]

def resolve_battle_winners() -> list:
    """5 призовых мест. 1-3 место — только для участников с BATTLE_TOP3_MIN_REFERRALS+
    рефералами за битву. 4-5 место — без минимума, отдаются следующим по рейтингу.
    Возвращает список из BATTLE_PLACE_COUNT элементов: (uid_str, diff) или None, если
    место не разыграно."""
    full = get_battle_leaderboard(limit=None)
    winners = [None] * BATTLE_PLACE_COUNT
    used_uids = set()
    qualifying = [e for e in full if e[1] >= BATTLE_TOP3_MIN_REFERRALS]
    for i in range(3):
        if i < len(qualifying):
            winners[i] = qualifying[i]
            used_uids.add(qualifying[i][0])
    remaining = [e for e in full if e[0] not in used_uids]
    for i, entry in enumerate(remaining[:2]):
        winners[3 + i] = entry
    return winners

def format_time_left(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d > 0:
        return f"{d}д {h}ч"
    return f"{h}ч {m}мин"

def format_battle_duration() -> str:
    days = BATTLE_DURATION_SECONDS // 86400
    if days == 7:
        return "неделю"
    if days > 0:
        return f"{days} дней"
    hours = BATTLE_DURATION_SECONDS // 3600
    return f"{hours} часов"

def start_referral_battle() -> None:
    now = time.time()
    snapshot = {uid: len(refs) for uid, refs in stats["referrals"].items()}
    stats["referral_battle"] = {
        "active": True,
        "start_ts": now,
        "end_ts": now + BATTLE_DURATION_SECONDS,
        "snapshot": snapshot,
        "results": None,
    }
    save_stats()

def get_battle_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Обновить", callback_data="referral_battle")
    builder.button(text="👥 Пригласить друзей", callback_data="referral_info")
    builder.button(text="🔙 Назад в меню", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()

def get_battle_text(user_id: int) -> str:
    if not is_battle_active():
        battle = stats.get("referral_battle")
        results = battle.get("results") if battle else None
        if results and any(w is not None for w in results):
            medals_lines = []
            for i, w in enumerate(results):
                if w is None:
                    continue
                uid_str, diff = w
                name = stats["user_names"].get(uid_str, f"Пользователь {uid_str}")
                medals_lines.append(f"{battle_place_icon(i)} {i + 1} место — {name} — <b>{diff}</b>")
            results_block = "\n".join(medals_lines)
            return (
                f"⚔️ <b>Битва рефералов</b>\n{DIVIDER}\n\n"
                "Сейчас битва не идёт. Результаты последней битвы:\n\n"
                f"{results_block}\n\n"
                "Следи за объявлениями — как только стартует новая битва, "
                f"у тебя будет {format_battle_duration()}, чтобы побороться за призы:\n\n"
                f"{format_battle_prizes_block()}"
            )
        return (
            f"⚔️ <b>Битва рефералов</b>\n{DIVIDER}\n\n"
            "Сейчас битва не идёт. Следи за объявлениями — как только стартует новая, "
            f"у тебя будет {format_battle_duration()}, чтобы побороться за призы:\n\n"
            f"{format_battle_prizes_block()}"
        )
    battle = stats["referral_battle"]
    remaining = format_time_left(battle["end_ts"] - time.time())
    my_gained = get_battle_gained(user_id)
    leaderboard = get_battle_leaderboard()
    uid_str = str(user_id)
    lines = [
        f"⚔️ <b>Битва рефералов — идёт!</b>\n{DIVIDER}\n",
        BATTLE_CHANNEL_POSTING_NOTICE,
        "",
        f"⏳ Осталось: <b>{remaining}</b>",
        "🎁 Призы для топ-5:",
        format_battle_prizes_block(),
        "",
        f"🙋 Твой результат за битву: <b>{my_gained}</b>",
        "",
    ]
    if leaderboard:
        lines.append("<b>Текущий рейтинг битвы:</b>")
        for i, (uid, diff) in enumerate(leaderboard):
            name = stats["user_names"].get(uid, f"Пользователь {uid}")
            you = " 👈 ты" if uid == uid_str else ""
            lines.append(f"{battle_place_icon(i)} {name} — <b>{diff}</b>{you}")
    else:
        lines.append("Пока никто не пригласил друзей в рамках битвы — стань первым!")
    lines.append("")
    lines.append(f"Твоя ссылка:\n{get_referral_link(user_id)}")
    return "\n".join(lines)

async def _broadcast_to(user_ids, text: str, keyboard=None) -> None:
    for user_id in list(user_ids):
        try:
            await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)
        except Exception:
            logger.exception("Не удалось отправить рассылку пользователю %s", user_id)
        await asyncio.sleep(0.05)

async def _broadcast(text: str, keyboard=None) -> None:
    await _broadcast_to(stats["total_users"], text, keyboard)

async def announce_global_promo_start() -> None:
    text = (
        "🎉🚀 <b>ВСЕ ОГРАНИЧЕНИЯ СНЯТЫ НА 24 ЧАСА!</b> 🚀🎉\n"
        f"{DIVIDER}\n\n"
        "Абсолютно все разделы — Биология, Физика, Химия, Гистология — сейчас "
        "полностью бесплатны для всех, без рефералов и подписки.\n\n"
        "Успей позаниматься, пока открыто — доступ вернётся к обычным правилам ровно через сутки! ⏳"
    )
    await _broadcast(text)

async def announce_global_promo_12h_start() -> None:
    text = (
        "🎉🚀 <b>ВСЕ ОГРАНИЧЕНИЯ СНЯТЫ НА 12 ЧАСОВ!</b> 🚀🎉\n"
        f"{DIVIDER}\n\n"
        "Абсолютно все разделы — Биология, Физика, Химия, Гистология — сейчас "
        "полностью бесплатны для всех, без рефералов и подписки.\n\n"
        "Успей позаниматься, пока открыто — доступ вернётся к обычным правилам через 12 часов! ⏳"
    )
    await _broadcast(text)

async def announce_battle_start() -> None:
    builder = InlineKeyboardBuilder()
    builder.button(text="⚔️ Битва рефералов", callback_data="referral_battle")
    text = (
        "⚔️🔥 <b>СТАРТУЕТ БИТВА РЕФЕРАЛОВ!</b> 🔥⚔️\n"
        f"{DIVIDER}\n\n"
        f"У тебя есть <b>{format_battle_duration()}</b>, чтобы пригласить в бота как можно больше друзей "
        "и забрать один из пяти эксклюзивных призов:\n\n"
        f"{format_battle_prizes_block()}\n\n"
        f"{DIVIDER}\n\n"
        "Считаются только друзья, приглашённые с этого момента.\n"
        "Следи за живым рейтингом на кнопке «⚔️ Битва рефералов» в главном меню.\n\n"
        f"{BATTLE_CHANNEL_POSTING_NOTICE}\n\n"
        "Погнали! 🚀"
    )
    await _broadcast(text, builder.as_markup())

def get_battle_remind_broadcast_text() -> str:
    battle = stats["referral_battle"]
    remaining = format_time_left(battle["end_ts"] - time.time())
    leaderboard = get_battle_leaderboard()
    lines = [
        "⚔️🔥 <b>БИТВА РЕФЕРАЛОВ ПРОДОЛЖАЕТСЯ!</b> 🔥⚔️\n",
        f"{DIVIDER}\n",
        f"⏳ Осталось: <b>{remaining}</b>\n",
        "🎁 Призы для топ-5:",
        format_battle_prizes_block(),
        "",
    ]
    if leaderboard:
        lines.append("<b>Текущий рейтинг битвы:</b>")
        for i, (uid, diff) in enumerate(leaderboard):
            name = stats["user_names"].get(uid, f"Пользователь {uid}")
            lines.append(f"{battle_place_icon(i)} {name} — <b>{diff}</b>")
        lines.append("")
    lines.append("Успей попасть в топ — жми «👥 Пригласить друзей» в главном меню и забирай свою ссылку!")
    return "\n".join(lines)

def get_access_restored_broadcast_text() -> str:
    return (
        "🎁 <b>Тебе восстановлен доступ!</b>\n"
        f"{DIVIDER}\n\n"
        "Мы заметили, что у тебя закончились бесплатные заходы в разделы Биология, Физика и Химия "
        "без приглашения друзей.\n\n"
        "Специально для тебя доступ ко всем разделам бота открыт заново на <b>7 дней</b> — "
        "взамен, пожалуйста, включи уведомления от бота (в Telegram: настройки чата с ботом → "
        "уведомления), чтобы не пропустить важные новости и новые материалы.\n\n"
        "⏳ Через 7 дней временный доступ закончится, и снова понадобится "
        f"{REFERRAL_FULL_ACCESS_THRESHOLD} приглашённых друга, чтобы открыть доступ навсегда — "
        "это правило не меняется и остаётся таким же для всех.\n\n"
        "👥 Открыть доступ насовсем можно в любой момент — кнопка «Пригласить друзей» в главном меню."
    )

def get_referral_reminder_broadcast_text() -> str:
    cheapest = cheapest_gated3_tier()
    return (
        f"👋 <b>Напоминание</b>\n{DIVIDER}\n\n"
        f"Чтобы бесплатно пользоваться разделами Биология, Физика и Химия, нужно пригласить "
        f"{REFERRAL_FULL_ACCESS_THRESHOLD} друзей в бота — открой «👥 Пригласить друзей» в "
        "главном меню, посмотри свой прогресс и отправь ссылку.\n\n"
        f"💎 Не хочешь ждать друзей? Открой доступ сразу оплатой — подписки от "
        f"{cheapest['price_rub']}₽/{cheapest['price_stars']}⭐. Жми «💎 Подписка» в главном меню."
    )

def get_referral_reminder_broadcast_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 Пригласить друзей", callback_data="referral_info")
    builder.button(text="💎 Подписка", callback_data="subscription_menu")
    builder.adjust(1)
    return builder.as_markup()

DISCOUNT_PROMO_TIER_IDS = (7, 9)  # какие тарифы предлагаются со скидкой в этой рассылке

def get_discount_promo_broadcast_text() -> str:
    t7, t9 = (SUBSCRIPTION_TIERS[t] for t in DISCOUNT_PROMO_TIER_IDS)
    return (
        f"🔥 <b>Скидка {int(DISCOUNT_RATE * 100)}% специально для тебя!</b>\n{DIVIDER}\n\n"
        "Ты ещё не пригласил друзей и пока не открыл доступ к боту — специально для тебя разовая "
        f"скидка {int(DISCOUNT_RATE * 100)}% на два самых выгодных тарифа:\n\n"
        f"{t7['emoji']} «{t7['title']}» — <s>{t7['price_rub']}₽</s> <b>{discount_price(t7['price_rub'])}₽</b>\n"
        f"{t9['emoji']} «{t9['title']}» — <s>{t9['price_rub']}₽</s> <b>{discount_price(t9['price_rub'])}₽</b>\n\n"
        "Жми на кнопку ниже, чтобы забрать скидку — предложение разовое!"
    )

def get_discount_promo_broadcast_keyboard():
    builder = InlineKeyboardBuilder()
    for t in DISCOUNT_PROMO_TIER_IDS:
        cfg = SUBSCRIPTION_TIERS[t]
        builder.button(
            text=f"{cfg['emoji']} {cfg['short']} — {discount_price(cfg['price_rub'])}₽ со скидкой",
            callback_data=f"sub_discount:{t}"
        )
    builder.adjust(1)
    return builder.as_markup()

def get_battle_results_announcement_text(winners: list) -> str:
    awarded = [(i, w) for i, w in enumerate(winners) if w is not None]
    if not awarded:
        return (
            f"🏁 <b>Битва рефералов завершена!</b>\n{DIVIDER}\n\n"
            "За время битвы никто не пригласил новых друзей — приз не разыгран в этот раз."
        )
    lines = [f"🏁 <b>Битва рефералов завершена!</b>\n{DIVIDER}\n", "Победители:"]
    for i, (uid_str, diff) in awarded:
        name = stats["user_names"].get(uid_str, f"Пользователь {uid_str}")
        lines.append(f"{BATTLE_PLACE_ICONS[i]} <b>{i + 1} место</b> — {name} — <b>{diff}</b> приглашённых")
        lines.append(f"🎁 {BATTLE_PRIZE_LABELS[i]}")
        lines.append(format_battle_savings_line(i))
        lines.append("")
    if any(winners[i] is None for i in range(3)):
        lines.append(
            f"⚠️ Часть мест в топ-3 не разыграна — не набралось участников от "
            f"{BATTLE_TOP3_MIN_REFERRALS} приглашённых.\n"
        )
    lines.append("Администратор свяжется с победителями лично 🤝")
    return "\n".join(lines)

async def resolve_referral_battle() -> None:
    battle = stats.get("referral_battle")
    if not battle or not battle.get("active"):
        return
    battle["active"] = False
    winners = resolve_battle_winners()
    battle["results"] = winners
    save_stats()

    result_text = get_battle_results_announcement_text(winners)
    await _broadcast(result_text)

    awarded = [(i, w) for i, w in enumerate(winners) if w is not None]
    if awarded:
        admin_lines = ["🏁 <b>Битва рефералов завершена.</b> Победители (для выдачи приза):"]
        for i, (uid_str, diff) in awarded:
            username = stats["user_username"].get(uid_str)
            handle = f"@{username}" if username else "(нет username)"
            admin_lines.append(f"{BATTLE_PLACE_ICONS[i]} {i + 1} место — ID <code>{uid_str}</code> {handle} — {diff} рефералов")
        admin_text = "\n".join(admin_lines)
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, admin_text, parse_mode="HTML")
            except Exception:
                logger.exception("Не удалось уведомить админа %s об итогах битвы", admin_id)

async def _battle_timer(end_ts: float) -> None:
    await asyncio.sleep(max(end_ts - time.time(), 0))
    battle = stats.get("referral_battle")
    if battle and battle.get("active") and time.time() >= battle.get("end_ts", 0):
        await resolve_referral_battle()

def resume_battle_timer_if_needed() -> None:
    battle = stats.get("referral_battle")
    if not battle or not battle.get("active"):
        return
    if time.time() >= battle.get("end_ts", 0):
        asyncio.create_task(resolve_referral_battle())
    else:
        asyncio.create_task(_battle_timer(battle["end_ts"]))

async def register_referral(referrer_id: int, referred_id: int) -> None:
    if referrer_id == referred_id:
        return
    if str(referred_id) in stats["referred_by"]:
        return  # у этого пользователя уже есть реферер, повторно не засчитываем
    stats["referred_by"][str(referred_id)] = referrer_id
    refs = stats["referrals"].setdefault(str(referrer_id), [])
    if referred_id not in refs:
        refs.append(referred_id)
        save_stats()
        try:
            await bot.send_message(
                referrer_id,
                "🎉 <b>По твоей ссылке в бота зашёл новый пользователь!</b>\n\n"
                f"Всего приглашено: <b>{len(refs)}</b>",
                parse_mode="HTML"
            )
        except Exception:
            logger.exception("Не удалось уведомить реферера %s", referrer_id)
    else:
        save_stats()

def track_user_identity(user) -> None:
    """Обновляет карты имя/username <-> id, чтобы админ мог находить пользователей по @username."""
    uid_str = str(user.id)
    changed = False
    new_name = html.escape(user.full_name) if user.full_name else f"Пользователь {user.id}"
    if stats["user_names"].get(uid_str) != new_name:
        stats["user_names"][uid_str] = new_name
        changed = True
    new_username = (user.username or "").strip().lower() or None
    if stats["user_username"].get(uid_str) != new_username:
        stats["user_username"][uid_str] = new_username
        changed = True
    if new_username and stats["usernames"].get(new_username) != user.id:
        stats["usernames"][new_username] = user.id
        changed = True
    if changed:
        save_stats()

# Без нужного числа рефералов закрыты только 3 раздела — Биология, Физика, Химия.
# Всё остальное (админка, рефералы, битва, поддержка автора, анатомия) доступно всегда.
# Разбито по предметам (а не одним плоским множеством) — с тарифа «3 дня, один предмет»
# подписка может закрывать доступ только к одному конкретному предмету, и гейту нужно знать,
# какому именно предмету принадлежит каждый callback, а не просто «гейтится ли он вообще».
GATED_CALLBACKS_BIOLOGY = {
    "menu_biology", "menu_tickets", "menu_questions",
    "quiz_start", "quiz_show_answer", "quiz_know", "quiz_dont_know", "quiz_stop",
    "random_ticket", "question_random", "question_by_number", "question_search",
    # download_biology_tickets гейтится отдельно, biology_tickets_download_ok().
}
GATED_PREFIXES_BIOLOGY = ("ticket:", "ticket_q:", "qpage:", "q:")

GATED_CALLBACKS_PHYSICS = {
    "menu_physics", "physics_tickets", "physics_theory_tickets", "physics_test_tickets",
    "physics_task_tickets",
    "physics_test", "physics_tasks", "download_physics_full", "download_physics_ticket_tasks",
    "physics_grade45", "download_physics_grade45", "download_physics_tasks_cheatsheet", "physics_extra",
}
GATED_PREFIXES_PHYSICS = (
    "phys_test_ticket:", "phys_test_ticket_tasks:", "phys_test_ticket_task_show:", "physics_page:", "physics_q:",
    "phystask_topic:", "phystask_formulas:", "phystask_list:", "phystask_show:", "physics45_q:",
    "phys_theory_ticket:", "phys_theory_q:", "physics_extra_q:",
    "phys_task_ticket:", "phys_task_ticket_show:",
)

GATED_CALLBACKS_CHEMISTRY = {
    "menu_chemistry", "chemistry_theory", "chemistry_theory_list",
    "chemistry_tasks", "chemistry_labs", "download_chemistry_labs", "download_chemistry_tasks",
    "chemistry_tickets", "chem_theory_tickets", "chem_practice_tickets",
}
GATED_PREFIXES_CHEMISTRY = (
    "chem_theory:", "chemtask_topic:", "chemtask_formulas:", "chemtask_list:", "chemtask_show:",
    "lab:", "lab_exp:", "lab_calc:", "lab_summary:",
    "chem_theory_ticket:", "chem_theory_q:", "chem_practice_ticket:",
)

GATED_CALLBACKS = GATED_CALLBACKS_BIOLOGY | GATED_CALLBACKS_PHYSICS | GATED_CALLBACKS_CHEMISTRY
GATED_PREFIXES = GATED_PREFIXES_BIOLOGY + GATED_PREFIXES_PHYSICS + GATED_PREFIXES_CHEMISTRY

def get_gated_subject(data: str) -> str | None:
    """Возвращает 'biology'/'physics'/'chemistry', если callback относится к одному из закрытых
    разделов, иначе None (раздел не гейтится вообще)."""
    if data in GATED_CALLBACKS_BIOLOGY or data.startswith(GATED_PREFIXES_BIOLOGY):
        return "biology"
    if data in GATED_CALLBACKS_PHYSICS or data.startswith(GATED_PREFIXES_PHYSICS):
        return "physics"
    if data in GATED_CALLBACKS_CHEMISTRY or data.startswith(GATED_PREFIXES_CHEMISTRY):
        return "chemistry"
    return None

def is_gated_callback(data: str) -> bool:
    return get_gated_subject(data) is not None

@dp.update.outer_middleware()
async def referral_gate_middleware(handler, event: Update, data):
    user = None
    if event.message:
        user = event.message.from_user
    elif event.callback_query:
        user = event.callback_query.from_user
    if not user or user.is_bot:
        return await handler(event, data)

    track_user_identity(user)

    # команды (/start, /stats, /broadcast и т.д.) не блокируем — гейт касается только контента
    if event.message and event.message.text and event.message.text.startswith("/"):
        return await handler(event, data)

    # поддержку автора (пожертвования) не блокируем никому, даже без рефералов
    if event.message and event.message.successful_payment:
        return await handler(event, data)
    if user.id in DONATION_PENDING:
        return await handler(event, data)

    # гейт касается только разделов Биология/Физика/Химия — остальные кнопки
    # (админка, рефералы, битва, поддержка автора, анатомия) доступны всегда
    subject = get_gated_subject(event.callback_query.data or "") if event.callback_query else None
    if event.callback_query and subject is None:
        return await handler(event, data)

    # у callback'ов проверяем доступ именно к ЭТОМУ предмету (тариф «3 дня, 1 предмет» открывает
    # только один) — у обычных сообщений (не привязаны к конкретному предмету) достаточно
    # любого действующего доступа вообще.
    if event.callback_query:
        if has_subject_access(user.id, subject):
            return await handler(event, data)
    elif has_free_access(user.id):
        return await handler(event, data)

    user_id_str = str(user.id)
    entry = stats["referral_warnings"].get(user_id_str, {"count": 0, "last_warn_at": 0})

    if entry["count"] >= REFERRAL_WARNING_THRESHOLD:
        block_text = (
            "🚨❗️ <b>ДОСТУП ЗАКРЫТ!</b> ❗️🚨\n\n"
            "Чтобы продолжить пользоваться ботом бесплатно — <b>пригласи друзей</b>! "
            "Это займёт меньше минуты! ⏱️\n\n"
            f"{get_referral_status_text(user.id)}\n\n"
            "⚡️ Как только твои друзья нажмут /start по этой ссылке — бот <b>сразу</b> станет доступен!"
        )
        try:
            if event.callback_query:
                await event.callback_query.answer("🚨 Доступ закрыт — пригласи друзей! ‼️", show_alert=True)
                await event.callback_query.message.answer(block_text, parse_mode="HTML", reply_markup=get_subscription_teaser_keyboard())
            elif event.message:
                await event.message.answer(block_text, parse_mode="HTML", reply_markup=get_subscription_teaser_keyboard())
        except Exception:
            logger.exception("Не удалось отправить сообщение о блокировке пользователю %s", user.id)
        return  # обработчик НЕ вызываем — доступ закрыт

    now = time.time()
    if now - entry.get("last_warn_at", 0) >= REFERRAL_WARNING_COOLDOWN_SECONDS:
        entry["count"] += 1
        entry["last_warn_at"] = now
        stats["referral_warnings"][user_id_str] = entry
        save_stats()
        remaining = REFERRAL_WARNING_THRESHOLD - entry["count"]
        warn_text = (
            "⚠️❗️ <b>ВНИМАНИЕ! Пригласи друзей!</b> ❗️⚠️\n\n"
            f"{get_referral_status_text(user.id)}"
            if remaining > 0 else
            "🚨‼️ <b>ПОСЛЕДНЕЕ ПРЕДУПРЕЖДЕНИЕ!</b> ‼️🚨\n\n"
            "В следующий раз доступ будет <b>полностью закрыт</b>, пока не пригласишь друзей!\n\n"
            f"{get_referral_status_text(user.id)}"
        )
        try:
            if event.callback_query:
                await event.callback_query.message.answer(warn_text, parse_mode="HTML", reply_markup=get_subscription_teaser_keyboard())
            elif event.message:
                await event.message.answer(warn_text, parse_mode="HTML", reply_markup=get_subscription_teaser_keyboard())
        except Exception:
            logger.exception("Не удалось отправить предупреждение о реферале пользователю %s", user.id)

    return await handler(event, data)

# ==================== ПЕРЕКЛИЧКА ГРУПП ====================
# Собираем по одному представителю от каждой группы, чтобы быть с ними на связи. Список
# групп генерируется по шаблону, не хранится в JSON — сами группы никогда не меняются местами.
ROLLCALL_GROUP_COUNT = 45

def rollcall_group_name(n: int) -> str:
    return f"25-ЛД/СТ-{n}"

def get_rollcall_menu_text() -> str:
    confirmed = len(stats["rollcall_confirmed"])
    return (
        f"📋 <b>Перекличка групп</b>\n{DIVIDER}\n\n"
        "Собираем по одному представителю от каждой группы, чтобы быть на связи.\n\n"
        "⚡ <b>ПЕРВЫМ ВЫБЕРИ СВОЮ ГРУППУ</b> и получи бонусную подписку на неделю!\n\n"
        f"Подтверждено представителей: <b>{confirmed}</b> из {ROLLCALL_GROUP_COUNT}\n\n"
        "Выбери номер своей группы:"
    )

def get_rollcall_menu_keyboard():
    builder = InlineKeyboardBuilder()
    for n in range(1, ROLLCALL_GROUP_COUNT + 1):
        group = rollcall_group_name(n)
        if group in stats["rollcall_confirmed"]:
            builder.button(text=f"✅ {group}", callback_data="rollcall_taken")
        else:
            builder.button(text=group, callback_data=f"rollcall_group:{n}")
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()

def get_rollcall_group_text(n: int) -> str:
    group = rollcall_group_name(n)
    return (
        f"👥 <b>Группа {group}</b>\n{DIVIDER}\n\n"
        "Нажми на кнопку ниже — откроется чат с @vmeda_helper, сообщение с номером твоей "
        "группы уже будет готово. Напиши его и подтверди, что ты из этой группы — как только "
        "это проверят, тебе включат бонусную подписку на неделю.\n\n"
        "Спасибо, что будешь на связи! 🙏"
    )

def get_rollcall_group_keyboard(n: int):
    group = rollcall_group_name(n)
    template = f"Привет! Я представитель группы {group}, хочу подтвердить участие в перекличке."
    url = f"{HELPER_ACCOUNT_URL}?text={urllib.parse.quote(template)}"
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💬 Написать @vmeda_helper", url=url))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="rollcall_menu"))
    return builder.as_markup()

async def notify_admins_of_rollcall_request(n: int, user) -> None:
    group = rollcall_group_name(n)
    text = (
        f"📋 <b>Отклик на перекличку</b>\n{DIVIDER}\n\n"
        f"Группа: <b>{group}</b>\n"
        f"От: {html.escape(user.full_name)} "
        f"({f'@{user.username} ' if user.username else ''}ID <code>{user.id}</code>)\n\n"
        "Проверь в чате с @vmeda_helper, что это правда представитель этой группы, и подтверди:"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить — выдать бонус", callback_data=f"rollcall_confirm:{n}:{user.id}")
    keyboard = builder.as_markup()
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            logger.exception("Не удалось уведомить админа %s о перекличке", admin_id)

def get_rollcall_announcement_text() -> str:
    return (
        f"📋 <b>Перекличка групп!</b>\n{DIVIDER}\n\n"
        "Собираем по одному представителю от каждой группы, чтобы быть на связи с курсом.\n\n"
        "⚡ <b>ПЕРВЫМ ВЫБЕРИ СВОЮ ГРУППУ</b> и получи бонусную подписку на неделю!\n\n"
        "Жми «📋 Перекличка» в главном меню и выбирай номер своей группы."
    )

def get_rollcall_announcement_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Перекличка", callback_data="rollcall_menu")
    return builder.as_markup()

@dp.callback_query(F.data == "rollcall_menu")
async def cb_rollcall_menu(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        get_rollcall_menu_text(),
        parse_mode="HTML",
        reply_markup=get_rollcall_menu_keyboard()
    )

@dp.callback_query(F.data == "rollcall_taken")
async def cb_rollcall_taken(callback: CallbackQuery):
    await callback.answer("У этой группы уже есть подтверждённый представитель. Спасибо! 🙏", show_alert=True)

@dp.callback_query(F.data.startswith("rollcall_group:"))
async def cb_rollcall_group(callback: CallbackQuery):
    n = int(callback.data.split(":")[1])
    if not (1 <= n <= ROLLCALL_GROUP_COUNT):
        await callback.answer("Группа не найдена", show_alert=True)
        return
    group = rollcall_group_name(n)
    if group in stats["rollcall_confirmed"]:
        await callback.answer("У этой группы уже есть подтверждённый представитель. Спасибо! 🙏", show_alert=True)
        await safe_edit_text(
            callback.message, get_rollcall_menu_text(), parse_mode="HTML", reply_markup=get_rollcall_menu_keyboard()
        )
        return
    await callback.answer()
    await safe_edit_text(
        callback.message,
        get_rollcall_group_text(n),
        parse_mode="HTML",
        reply_markup=get_rollcall_group_keyboard(n),
        disable_web_page_preview=True,
    )
    await notify_admins_of_rollcall_request(n, callback.from_user)

@dp.callback_query(F.data.startswith("rollcall_confirm:"))
async def cb_rollcall_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    _, n_raw, target_id_raw = callback.data.split(":")
    n = int(n_raw)
    target_id = int(target_id_raw)
    if not (1 <= n <= ROLLCALL_GROUP_COUNT):
        await callback.answer("Группа не найдена", show_alert=True)
        return
    group = rollcall_group_name(n)
    existing = stats["rollcall_confirmed"].get(group)
    if existing:
        await callback.answer("У этой группы уже есть подтверждённый представитель", show_alert=True)
        await safe_edit_text(
            callback.message,
            f"✅ Уже подтверждено — представитель группы {group}: "
            f"{format_admin_target_label(None, existing['user_id'])}.",
            parse_mode="HTML"
        )
        return

    stats["rollcall_confirmed"][group] = {"user_id": target_id, "confirmed_at": time.time()}
    stats["temporary_access"][str(target_id)] = time.time() + TEMP_ACCESS_GRANT_SECONDS
    save_stats()
    await callback.answer("Подтверждено ✅", show_alert=True)
    await safe_edit_text(
        callback.message,
        f"✅ Подтверждено — {format_admin_target_label(None, target_id)} представитель группы {group}. Бонус выдан.",
        parse_mode="HTML"
    )
    try:
        await bot.send_message(
            target_id,
            f"🎉 <b>Ты подтверждён как представитель группы {group}!</b>\n\n"
            "Бонусная подписка на неделю активирована — доступ к Биологии, Физике и Химии "
            "открыт на 7 дней без рефералов. Спасибо, что будешь на связи! 🙏",
            parse_mode="HTML"
        )
    except Exception:
        logger.exception("Не удалось уведомить пользователя %s о подтверждении переклички", target_id)

@dp.callback_query(F.data == "admin_announce_rollcall_confirm")
async def cb_admin_announce_rollcall_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить всем", callback_data="admin_announce_rollcall_go")
    builder.button(text="❌ Отмена", callback_data="admin_panel")
    builder.adjust(1)
    preview = (
        f"👀 <b>Предпросмотр анонса</b>\n{DIVIDER}\n\n"
        f"{get_rollcall_announcement_text()}\n\n{DIVIDER}\n"
        f"Отправить это всем {len(stats['total_users'])} пользователям?"
    )
    await safe_edit_text(callback.message, preview, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "admin_announce_rollcall_go")
async def cb_admin_announce_rollcall_go(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer("📣 Рассылка запущена!", show_alert=True)
    recipients = len(stats["total_users"])
    stats["broadcast_count"] = stats.get("broadcast_count", 0) + 1
    save_stats()
    await _broadcast(get_rollcall_announcement_text(), get_rollcall_announcement_keyboard())
    await safe_edit_text(
        callback.message,
        f"✅ Анонс переклички отправлен (попытка охватить {recipients} пользователей).",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

# ==================== ПОДДЕРЖКА АВТОРА ====================
DONATION_PENDING: dict[int, dict] = {}
STARS_MIN, STARS_MAX = 1, 2500
RUBLES_MIN, RUBLES_MAX = 10, 1_000_000
STARS_PRESETS = [25, 50, 100, 250, 500]
RUBLES_PRESETS = [100, 300, 500, 1000, 2000]
HELPER_ACCOUNT_URL = "https://t.me/vmeda_helper"

def get_support_text() -> str:
    return (
        f"😇💰 <b>Поддержка автора</b>\n{DIVIDER}\n\n"
        "Бот без рекламы, а основные разделы всегда можно открыть бесплатно за рефералов.\n\n"
        "На разработку и организацию бота (хостинг, домен, работа над контентом) "
        "потрачено уже около <b>5000₽</b>, а получено с бота — <b>0₽</b>.\n\n"
        "Здесь — просто пожертвование без каких-либо условий, любая сумма. "
        "Если хочешь вместо этого открыть доступ без рефералов — "
        "загляни в «💎 Подписка» в главном меню.\n\n"
        "Можно звёздами Telegram или переводом в рублях — выбери, как удобнее 👇"
    )

def get_support_keyboard(user_id: int):
    hidden = stats.get("donor_hide_name", {}).get(str(user_id), False)
    visibility_label = "🙋 Показывать меня в рейтинге" if hidden else "🙈 Скрыть меня в рейтинге"
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Пожертвовать звёзды", callback_data="donate_stars_menu")
    builder.button(text="💵 Перевести рубли", callback_data="donate_rubles_menu")
    builder.button(text="🏆 Лучшие донатеры", callback_data="donors_leaderboard")
    builder.button(text=visibility_label, callback_data="toggle_donor_visibility")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()

def get_support_announcement_text() -> str:
    return (
        f"📣 <b>Новое в боте — раздел «Поддержка автора»!</b>\n{DIVIDER}\n\n"
        "Бот без рекламы, основные разделы всегда можно открыть бесплатно за рефералов — "
        "но на разработку и хостинг уже "
        "потрачено около <b>5000₽</b>, а получено с бота — <b>0₽</b>.\n\n"
        "Теперь его можно поддержать:\n"
        "⭐ звёздами Telegram — сумму выбираешь сам\n"
        "💵 переводом в рублях — тоже любая сумма, реквизиты пришлют в чате с "
        '<a href="https://t.me/vmeda_helper">@vmeda_helper</a>\n\n'
        "А ещё есть рейтинг «🏆 Лучшие донатеры» — топ по звёздам и топ по рублям! "
        "Можно засветить свой ник или остаться анонимом — выбираешь сам.\n\n"
        "Заходи в «😇 Поддержать автора 💰» в главном меню, жертвуй любую сумму — "
        "и попади в топ! 🙏"
    )

def get_support_announcement_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="😇 Поддержать автора 💰", callback_data="support_menu")
    return builder.as_markup()

def get_subscription_announcement_text() -> str:
    tier_lines = "\n".join(
        f"{cfg['emoji']} <b>{cfg['price_rub']}₽ / {cfg['price_stars']}⭐</b> — {cfg['short']}"
        for cfg in ACTIVE_SUBSCRIPTION_TIERS.values()
    )
    return (
        f"💎 <b>Новое в боте — платная подписка без рефералов!</b>\n{DIVIDER}\n\n"
        "Разработка и содержание бота требуют серьёзных затрат — поэтому в дополнение "
        f"к бесплатному доступу за {REFERRAL_FULL_ACCESS_THRESHOLD} рефералов теперь можно "
        "открыть доступ сразу оплатой:\n\n"
        f"{tier_lines}\n\n"
        "После оплаты правило с рефералами для тебя больше не действует — доступ "
        "открывается сразу и держится всё оплаченное время.\n\n"
        "Загляни в «💎 Подписка» в главном меню, чтобы посмотреть плюсы каждого тарифа 👇"
    )

def get_subscription_announcement_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="💎 Подписка без рефералов", callback_data="subscription_menu")
    return builder.as_markup()

def get_anatomy_announcement_text() -> str:
    tier_lines = " или ".join(
        f"«{cfg['emoji']} {cfg['title']}» ({cfg['price_rub']}₽)"
        for cfg in ACTIVE_SUBSCRIPTION_TIERS.values()
        if cfg.get("anatomy")
    )
    return (
        f"🦴 <b>Открываем раздел «Анатомия»!</b>\n{DIVIDER}\n\n"
        "Самый подробный раздел бота — теперь доступен по подписке 👇\n\n"
        "📚 <b>Что внутри:</b>\n"
        "• 10 модулей по программе Кафарова — 107 тем: от остеологии и миологии до "
        "нервной, сердечно-сосудистой и клинической анатомии\n"
        "• Материал написан по учебнику Гайворонского и методичкам кафедры, с латинской "
        "номенклатурой в каждой теме\n"
        "• Кости черепа, туловища и конечностей разобраны отдельно по каждой кости — "
        "с фото, флэш-карточками, сопоставлением терминов и мнемониками\n"
        "• Атлас с иллюстрациями Неттера и Гайворонского плюс учебные фотопрезентации "
        "кафедры\n"
        "• Тренажёр латинских терминов по каждой кости и теме, а также общий тест по "
        "всей номенклатуре с рейтингом лучших\n"
        "• Видео-разборы по темам и разделам\n\n"
        f"💎 Доступна в тарифах: {tier_lines}\n\n"
        "Загляни в «💎 Подписка» в главном меню, чтобы выбрать тариф 👇"
    )

def get_anatomy_announcement_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="💎 Подписка", callback_data="subscription_menu")
    builder.button(text="🦴 Анатомия", callback_data="anatomy_root")
    builder.adjust(1)
    return builder.as_markup()

def get_anatomy_exam_announcement_text() -> str:
    return (
        f"🎓 <b>Открыт раздел «Экзамен» по Анатомии!</b>\n{DIVIDER}\n\n"
        "Готовься к экзамену прицельно — три инструмента, и все бесплатно, без рефералов "
        "и подписки:\n\n"
        "✅ <b>ТЕСТ</b> — официальный банк вопросов кафедры нормальной анатомии ВМедА "
        "(Гайворонский и др.), 1040 вопросов, 10 частей\n"
        "📖 <b>Вопросы теории</b> — разбор экзаменационных вопросов с полными ответами\n"
        "🖐 <b>Вопросы практики</b> — «покажите и назовите» с фото атласа к каждому ответу\n\n"
        "🏆 Включи <b>рейтинговый режим</b> в ТЕСТе — результаты идут в общий рейтинг лучших. "
        "Самые активные и точные получат призы от нас!\n\n"
        "Жми «🎓 Экзамен» в разделе Анатомии и начинай готовиться 👇"
    )

def get_anatomy_exam_announcement_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ ТЕСТ", callback_data="anatomy_exam_test_menu")
    builder.button(text="📖 Вопросы теории", callback_data="anatomy_exam_theory")
    builder.button(text="🖐 Вопросы практики", callback_data="anatomy_exam_practice")
    builder.button(text="🏆 Рейтинг ТЕСТа", callback_data="anatomy_exam_test_leaderboard")
    builder.adjust(1)
    return builder.as_markup()

def get_anatomy_latin_announcement_text() -> str:
    return (
        f"🏛 <b>Тест по латинским терминам — по всему курсу анатомии!</b>\n{DIVIDER}\n\n"
        "Проверь себя: общий тест собирает вопросы по латинской номенклатуре сразу со всего "
        "курса анатомии, а не по одной теме — и совершенно бесплатно, без рефералов и "
        "подписки.\n\n"
        "🏆 Лучшие результаты попадают в общий рейтинг — посмотри, на каком ты месте, "
        "и постарайся его улучшить.\n\n"
        "Жми кнопку ниже и проходи тест 👇"
    )

def get_anatomy_latin_announcement_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🏛 Пройти тест", callback_data="anatomy_latin_all_start")
    builder.button(text="🏆 Рейтинг", callback_data="anatomy_latin_leaderboard")
    builder.adjust(1)
    return builder.as_markup()

def donor_display_name(uid_str: str) -> str:
    if stats.get("donor_hide_name", {}).get(uid_str):
        return "🙈 Аноним"
    username = stats["user_username"].get(uid_str)
    if username:
        return f"@{username}"
    return stats["user_names"].get(uid_str, f"Пользователь {uid_str}")

def get_donors_leaderboard_text() -> str:
    star_ranked = sorted(stats.get("donor_stars", {}).items(), key=lambda kv: kv[1], reverse=True)[:10]
    ruble_ranked = sorted(stats.get("donor_rubles", {}).items(), key=lambda kv: kv[1], reverse=True)[:10]

    lines = [f"🏆 <b>Лучшие донатеры</b>\n{DIVIDER}"]
    if star_ranked:
        lines.append("\n⭐ <b>По звёздам:</b>")
        for i, (uid, total) in enumerate(star_ranked):
            icon = RANK_MEDALS[i] if i < 3 else f"{i + 1}."
            lines.append(f"{icon} {donor_display_name(uid)} — <b>{total}</b> ⭐")
    if ruble_ranked:
        lines.append("\n💵 <b>По рублям:</b>")
        for i, (uid, total) in enumerate(ruble_ranked):
            icon = RANK_MEDALS[i] if i < 3 else f"{i + 1}."
            lines.append(f"{icon} {donor_display_name(uid)} — <b>{total}</b>₽")
    if not star_ranked and not ruble_ranked:
        lines.append("\nПока никто не пожертвовал — стань первым! 🙏")
    return "\n".join(lines)

def get_donors_leaderboard_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Обновить", callback_data="donors_leaderboard")
    builder.button(text="🔙 Назад", callback_data="support_menu")
    builder.adjust(1)
    return builder.as_markup()

def get_visibility_choice_text(amount: int, unit: str) -> str:
    return (
        f"👀 <b>Показывать тебя в рейтинге?</b>\n{DIVIDER}\n\n"
        f"Сумма: <b>{amount}{unit}</b>\n\n"
        "Можно пожертвовать открыто — твой ник появится в «🏆 Лучшие донатеры» — "
        "или анонимно, тогда в рейтинге будет просто «Аноним»."
    )

def get_stars_visibility_keyboard(amount: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="🙋 Показывать мой ник", callback_data=f"donate_stars_confirm:{amount}:pub")
    builder.button(text="🙈 Анонимно", callback_data=f"donate_stars_confirm:{amount}:anon")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="donate_stars_menu"))
    return builder.as_markup()

def get_rubles_visibility_keyboard(amount: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="🙋 Показывать мой ник", callback_data=f"donate_rubles_confirm:{amount}:pub")
    builder.button(text="🙈 Анонимно", callback_data=f"donate_rubles_confirm:{amount}:anon")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="donate_rubles_menu"))
    return builder.as_markup()

def get_stars_menu_text() -> str:
    return (
        f"⭐ <b>Пожертвовать звёзды</b>\n{DIVIDER}\n\n"
        "Выбери количество звёзд Telegram, либо укажи своё:"
    )

def get_stars_menu_keyboard():
    builder = InlineKeyboardBuilder()
    for n in STARS_PRESETS:
        builder.button(text=f"⭐ {n}", callback_data=f"donate_stars_amount:{n}")
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="✏️ Своя сумма", callback_data="donate_stars_custom"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="support_menu"))
    return builder.as_markup()

def get_rubles_menu_text() -> str:
    return (
        f"💵 <b>Перевести рубли</b>\n{DIVIDER}\n\n"
        "Выбери сумму в рублях, либо укажи свою:"
    )

def get_rubles_menu_keyboard():
    builder = InlineKeyboardBuilder()
    for n in RUBLES_PRESETS:
        builder.button(text=f"{n}₽", callback_data=f"donate_rubles_amount:{n}")
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="✏️ Своя сумма", callback_data="donate_rubles_custom"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="support_menu"))
    return builder.as_markup()

def get_rubles_donation_message_text(amount: int) -> str:
    return (
        f"💵 <b>Перевод {amount}₽</b>\n{DIVIDER}\n\n"
        f'Нажми на кнопку ниже — откроется чат с <a href="{HELPER_ACCOUNT_URL}">@vmeda_helper</a>, '
        "сообщение с суммой уже будет готово. Останется его отправить — и тебе пришлют реквизиты для перевода.\n\n"
        "Спасибо огромное за поддержку! 🙏😇"
    )

def get_rubles_donation_keyboard(amount: int):
    template = (
        f"Привет! Хочу перевести {amount}₽ в поддержку бота VMEDA_examen_bot 🙏 "
        "Подскажи, пожалуйста, реквизиты для перевода."
    )
    url = f"{HELPER_ACCOUNT_URL}?text={urllib.parse.quote(template)}"
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💸 Пожертвовать рубли", url=url))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="donate_rubles_menu"))
    return builder.as_markup()

async def send_stars_invoice(chat_id: int, stars: int) -> None:
    await bot.send_invoice(
        chat_id=chat_id,
        title="Поддержка автора бота",
        description=f"Спасибо за поддержку VMEDA_examen_bot! Пожертвование: {stars} ⭐",
        payload=f"donate_stars_{stars}_{chat_id}_{int(time.time())}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Поддержка автора", amount=stars)],
    )

# ==================== СКРЫТЫЕ БИЛЕТЫ (40-50) ====================
HIDDEN_TICKET_RANGE = (40, 50)
FORCE_VISIBLE_TICKETS = {"40A"}  # исключения из скрытого диапазона — показывать всегда

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
    if str(ticket_num) in FORCE_VISIBLE_TICKETS:
        return True
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

def _normalize_ticket_num(s: str) -> str:
    """Убирает пробелы и приводит букву А к единому виду (кириллица/латиница, регистр)."""
    return (s or "").strip().upper().replace(" ", "").replace("А", "A")

TICKET_LOOKUP = {_normalize_ticket_num(k): v for k, v in TICKETS_DICT.items()}

# ==================== ПОИСК ПО КЛЮЧЕВЫМ СЛОВАМ ====================
SEARCH_RESULTS_LIMIT = 25

def _extract_words(text: str) -> list:
    return re.findall(r"[a-zа-яё]+", (text or "").lower().replace("ё", "е"))

def _word_stem(word: str) -> str:
    """Грубый стеммер: отбрасывает окончание, чтобы находить разные словоформы
    ("плазмодий" / "плазмодия" / "плазмодии")."""
    n = len(word)
    if n <= 4:
        return word
    if n <= 6:
        return word[:-1]
    return word[:-2]

def search_questions_by_keyword(query: str, limit: int = SEARCH_RESULTS_LIMIT):
    query_stems = [_word_stem(w) for w in _extract_words(query) if len(w) >= 3]
    if not query_stems:
        return []
    matches = []
    for num in sorted(QUESTIONS.keys(), key=lambda x: int(x)):
        # Игнорируем короткие служебные слова ("и", "с", "у"), иначе они ложно
        # совпадают с любым стеммом запроса через startswith.
        title_words = [w for w in _extract_words(QUESTIONS[num].get("title", "")) if len(w) >= 3]
        if all(any(tw.startswith(qs) for tw in title_words) for qs in query_stems):
            matches.append(num)
            if len(matches) >= limit:
                break
    return matches

# AI RAG-lite (индекс/поиск/подмес материалов ВМедА) перенесён в ai/rag.py — см. ai_rag.configure()
# (вызывается один раз при старте, см. конец файла) и ai_rag.search_snippets_multi()/format_context()
# (используются в обработчиках AI-режима).

async def is_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
    except Exception:
        return False

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def is_assistant_admin(user_id: int) -> bool:
    return user_id in stats["assistant_admins"]

def is_admin_or_assistant(user_id: int) -> bool:
    """Полный админ ИЛИ помощник администратора — используется только в гейтах доступа к
    контенту (Анатомия/Гистология/гейтящиеся предметы), НЕ в гейтах самой админ-панели.
    Помощник получает доступ ко всем разделам, но не получает права полного админа
    (выдача/отзыв доступа, рассылки, подписки и т.д. — только через отдельную,
    ограниченную панель помощника, см. секцию «ПОМОЩНИК АДМИНИСТРАТОРА»)."""
    return is_admin(user_id) or is_assistant_admin(user_id)

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

# ==================== ВЫГРУЗКА РАЗДЕЛОВ В WORD-ФАЙЛ ====================
_HTML_TOKEN_RE = re.compile(r"(<b>|</b>|<i>|</i>|<u>|</u>)")

def strip_html_tags(text: str) -> str:
    """Контент хранится с Telegram-HTML-разметкой (<b>, <i>, <u>) — вне докс-раннов она не нужна."""
    return _HTML_TOKEN_RE.sub("", text)

def add_html_run(paragraph, text: str) -> None:
    """Разбирает Telegram-HTML-подмножество (<b>, <i>, <u>) в форматированные докс-раны."""
    bold = italic = underline = False
    for token in _HTML_TOKEN_RE.split(text):
        if token == "<b>":
            bold = True
        elif token == "</b>":
            bold = False
        elif token == "<i>":
            italic = True
        elif token == "</i>":
            italic = False
        elif token == "<u>":
            underline = True
        elif token == "</u>":
            underline = False
        elif token:
            run = paragraph.add_run(token)
            run.bold = bold
            run.italic = italic
            run.underline = underline

def add_html_paragraphs(doc, text: str) -> None:
    """text может содержать \n\n (разрыв абзаца) и \n (перенос строки внутри абзаца)."""
    for block in text.split("\n\n"):
        p = doc.add_paragraph()
        for i, line in enumerate(block.split("\n")):
            if i > 0:
                p.add_run().add_break()
            add_html_run(p, line)

def add_labeled_field(doc, label: str, value: str) -> None:
    p = doc.add_paragraph()
    p.add_run(f"{label}:").bold = True
    add_html_paragraphs(doc, value)

def add_topic_block(doc, topic: dict) -> None:
    """Общий для physics_tasks.json и chemistry_tasks.json блок темы: заголовок, вступление,
    формулы/алгоритм и разобранные задачи."""
    doc.add_heading(topic["title"], level=2)
    if topic.get("intro"):
        add_html_paragraphs(doc, topic["intro"])
    add_html_paragraphs(doc, topic["formulas"])
    for task in topic.get("tasks", []):
        doc.add_heading(f"{task['num']}. {task['title']}", level=3)
        add_labeled_field(doc, "Условие", task["condition"])
        add_labeled_field(doc, "Решение", task["solution"])

def docx_filename(title: str) -> str:
    return re.sub(r"[^\w\-]+", "_", title, flags=re.UNICODE).strip("_")[:60] + ".docx"

def build_docx_file(title: str, fill_fn) -> BufferedInputFile:
    doc = DocxDocument()
    doc.add_heading(title, level=0)
    fill_fn(doc)
    buf = io.BytesIO()
    doc.save(buf)
    return BufferedInputFile(buf.getvalue(), filename=docx_filename(title))

def build_biology_tickets_file() -> BufferedInputFile:
    def fill(doc):
        for ticket in TICKETS:
            doc.add_heading(ticket["title"], level=1)
            for q in ticket["questions"]:
                doc.add_heading(f"{q['num']}. {q['title']}", level=2)
                add_html_paragraphs(doc, q["answer"])
    return build_docx_file("Биология — все билеты (вопросы и ответы)", fill)

def build_physics_full_file() -> BufferedInputFile:
    def fill(doc):
        doc.add_heading("Часть 1. Тестовая часть — 186 вопросов (по алфавиту)", level=1)
        items = sorted(PHYSICS_QUESTIONS.values(), key=lambda v: v["title"])
        for item in items:
            doc.add_heading(item["title"], level=2)
            add_html_paragraphs(doc, item["answer"])
        doc.add_page_break()
        doc.add_heading("Часть 2. Шаблоны решения задач по всем темам", level=1)
        for topic in PHYSICS_TASKS.values():
            add_topic_block(doc, topic)
    return build_docx_file("Физика — тестовая часть и шаблоны решения задач", fill)

def build_physics_grade45_file() -> BufferedInputFile:
    def fill(doc):
        items = sorted(PHYSICS_GRADE45_QUESTIONS.values(), key=lambda v: v["title"])
        for i, item in enumerate(items):
            heading = doc.add_heading(item["title"], level=1)
            heading.paragraph_format.space_before = Pt(0 if i == 0 else 30)
            heading.paragraph_format.space_after = Pt(12)
            add_html_paragraphs(doc, item["answer"])
    return build_docx_file("Физика — (60 вопросов) на 4/5", fill)

_ALGORITHM_BLOCK_RE = re.compile(
    r"\n\n<b>Алгоритм решения:</b>.*?(?=\n\n<b>Единицы измерения:</b>)", re.DOTALL
)

def build_physics_tasks_cheatsheet_file() -> BufferedInputFile:
    """Краткая шпаргалка по всем типам задач по физике — только формулы и обозначения
    (пошаговый алгоритм решения из physics_tasks.json намеренно опущен для краткости)."""
    def fill(doc):
        for num in sorted(PHYSICS_TASKS.keys(), key=int):
            topic = PHYSICS_TASKS[num]
            heading = doc.add_heading(topic["title"], level=1)
            heading.paragraph_format.space_before = Pt(0 if num == "1" else 24)
            heading.paragraph_format.space_after = Pt(6)
            formulas_only = _ALGORITHM_BLOCK_RE.sub("", topic["formulas"])
            add_html_paragraphs(doc, formulas_only)
    return build_docx_file("Физика — шпаргалка по формулам к задачам", fill)

def build_physics_ticket_tasks_file() -> BufferedInputFile:
    def fill(doc):
        for num in sorted(PHYSICS_TEST_TICKETS.keys(), key=int):
            ticket = PHYSICS_TEST_TICKETS[num]
            tasks = ticket.get("tasks")
            if not tasks:
                continue
            doc.add_heading(f"{ticket['title']} — Часть 2. Задачи", level=1)
            for task in tasks:
                doc.add_heading(f"Задача {task['num']}. {task['title']}", level=2)
                add_labeled_field(doc, "Условие", task["condition"])
                add_labeled_field(doc, "Решение", task["solution"])
    return build_docx_file("Физика — билеты с задачами (ответы)", fill)

_LAB_FIELD_LABELS = {
    "positive_sol": "Положительный золь", "negative_sol": "Отрицательный золь",
    "procedure": "Методика", "theory": "Теория", "titrant": "Титрант",
    "indicator": "Индикатор", "buffer": "Буфер", "equations": "Уравнения реакций",
    "calculations": "Расчёты",
}

def build_chemistry_labs_file() -> BufferedInputFile:
    def fill(doc):
        for lab in CHEMISTRY_LABS["labs"]:
            doc.add_heading(f"Лабораторная работа {lab['number']}. {lab['theme']}", level=1)
            add_labeled_field(doc, "Условие", lab["condition"])
            for exp in lab.get("experiments", []):
                doc.add_heading(exp.get("name", ""), level=2)
                for key in ("description", "mechanism", "technique", "sorbent", "eluent", "procedure"):
                    value = exp.get(key)
                    if value:
                        add_html_paragraphs(doc, value)
            for key, label in _LAB_FIELD_LABELS.items():
                value = lab.get(key)
                if value:
                    add_labeled_field(doc, label, value)
    return build_docx_file("Химия — все лабораторные работы", fill)

def build_chemistry_tasks_file() -> BufferedInputFile:
    def fill(doc):
        for topic in CHEMISTRY_TASKS.values():
            add_topic_block(doc, topic)
    return build_docx_file("Химия — все задачи", fill)

# ==================== КЛАВИАТУРЫ ====================
def get_main_menu(user_id: int = None):
    builder = InlineKeyboardBuilder()
    builder.button(text="🤖 VMedA AI (бета)", callback_data="ai_menu")
    sub_anatomy = user_id is not None and has_subscription_anatomy_access(user_id)
    sub_histology = user_id is not None and has_subscription_histology_access(user_id)
    if user_id is not None and is_admin(user_id):
        anatomy_label = "🔥🦴 Анатомия (админ)"
    elif anatomy_handlers.ANATOMY_MAINTENANCE_MODE:
        anatomy_label = "🦴 Анатомия (техобслуживание)"
    elif sub_anatomy:
        anatomy_label = "🔥🦴 Анатомия 💎"
    else:
        anatomy_label = "🔥🦴 Анатомия"
    builder.button(text=anatomy_label, callback_data="anatomy_root")
    builder.button(text="🧬 Биология", callback_data="menu_biology")
    builder.button(text="⚛️ Физика", callback_data="menu_physics")
    builder.button(text="🧪 Химия", callback_data="menu_chemistry")
    if HISTOLOGY_PUBLIC:
        histology_label = "🔬 Гистология"
    elif user_id is not None and is_admin(user_id):
        histology_label = "🔬 Гистология (админ)"
    elif is_section_promo_active("histology"):
        histology_label = "🔬 Гистология 🎉"
    elif user_id is not None and get_referral_count(user_id) >= REFERRAL_FULL_ACCESS_THRESHOLD:
        histology_label = "🔬 Гистология"
    elif sub_histology:
        histology_label = "🔬 Гистология 💎"
    elif user_id is not None and has_histology_temp_access(user_id):
        histology_label = "🔬 Гистология (пробный период)"
    else:
        histology_label = "🔬 Гистология (рефералы/подписка)"
    builder.button(text=histology_label, callback_data="histology_menu")
    builder.button(text="👥 Пригласить друзей", callback_data="referral_info")
    builder.button(text="🏆 Рейтинг", callback_data="referral_leaderboard")
    rollcall_confirmed_count = len(stats["rollcall_confirmed"])
    builder.button(
        text=f"📋 Перекличка ({rollcall_confirmed_count}/{ROLLCALL_GROUP_COUNT})",
        callback_data="rollcall_menu"
    )
    battle_label = "⚔️ Битва рефералов 🔥" if is_battle_active() else "⚔️ Битва рефералов"
    builder.button(text=battle_label, callback_data="referral_battle")
    if user_id is not None and has_active_subscription(user_id):
        sub_label = "💎 Моя подписка"
    else:
        sub_label = "💎 Подписка без рефералов"
    builder.button(text=sub_label, callback_data="subscription_menu")
    builder.button(text="😇 Поддержать автора 💰", callback_data="support_menu")
    builder.adjust(1)
    return builder.as_markup()

def get_referral_back_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💎 Открыть доступ без рефералов", callback_data="subscription_menu"))
    builder.row(InlineKeyboardButton(text="🚀 Запустить Medical_vpn_bot", url=MEDICAL_VPN_URL))
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()

def get_referral_full_access_keyboard(user_id: int = None):
    builder = InlineKeyboardBuilder()
    builder.button(text="⚔️ Битва рефералов", callback_data="referral_battle")
    sub_label = "💎 Моя подписка" if user_id is not None and has_active_subscription(user_id) else "💎 Подписка"
    builder.button(text=sub_label, callback_data="subscription_menu")
    builder.button(text="🔙 Назад в меню", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()

def get_biology_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="📘 Билеты", callback_data="menu_tickets")
    builder.button(text="📝 Вопросы", callback_data="menu_questions")
    builder.button(text="🎯 Опрос (10 вопросов)", callback_data="quiz_start")
    builder.button(text="📄 Все билеты (текстовый файл)", callback_data="download_biology_tickets")
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
    await safe_edit_text(message, text, parse_mode="HTML", reply_markup=get_quiz_question_keyboard())

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
        await safe_edit_text(
            message,
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
    await safe_edit_text(message, text, parse_mode="HTML", reply_markup=get_quiz_summary_keyboard())

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
    builder.button(text="🔍 Поиск по ключевым словам", callback_data="question_search")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu_biology"))
    return builder.as_markup()

def get_search_results_keyboard(nums: list):
    builder = InlineKeyboardBuilder()
    for num in nums:
        title = QUESTIONS[num].get("title", "")
        short_title = title if len(title) <= 60 else title[:57] + "…"
        builder.button(text=f"{num}. {short_title}", callback_data=f"q:{num}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu_questions"))
    return builder.as_markup()

def get_question_answer_keyboard(q_num: str):
    builder = InlineKeyboardBuilder()
    n = int(q_num)
    nav = []
    if str(n - 1) in QUESTIONS:
        nav.append(InlineKeyboardButton(text="⬅️ Предыдущий вопрос", callback_data=f"q:{n - 1}"))
    if str(n + 1) in QUESTIONS:
        nav.append(InlineKeyboardButton(text="Следующий вопрос ➡️", callback_data=f"q:{n + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🎲 Случайный вопрос", callback_data="question_random"))
    builder.row(InlineKeyboardButton(text="🔢 Ввести номер вручную", callback_data="question_by_number"))
    page = (n - 1) // 50 + 1
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"qpage:{page}"))
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
    builder.button(text="🧮 Задачи", callback_data="physics_tasks")
    builder.button(text="❓ (60 вопросов) на 4/5", callback_data="physics_grade45")
    builder.button(text="⭐ Доп. вопросы от преподавателей", callback_data="physics_extra")
    builder.button(text="📄 186 вопросов + шаблоны задач (файл)", callback_data="download_physics_full")
    builder.button(text="📄 (60 вопросов) на 4/5 (файл)", callback_data="download_physics_grade45")
    builder.button(text="📄 Ответы на задачи билетов (файл)", callback_data="download_physics_ticket_tasks")
    builder.button(text="📄 Шпаргалка по формулам к задачам (файл)", callback_data="download_physics_tasks_cheatsheet")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()

def get_physics_tickets_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Тестовые билеты", callback_data="physics_test_tickets")
    builder.button(text="📖 Билеты теоретической части", callback_data="physics_theory_tickets")
    builder.button(text="🧮 Билеты с задачами", callback_data="physics_task_tickets")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu_physics"))
    return builder.as_markup()

def get_physics_task_tickets_keyboard():
    builder = InlineKeyboardBuilder()
    for num in sorted(PHYSICS_TASK_TICKETS.keys(), key=int):
        builder.button(text=f"🧮 {PHYSICS_TASK_TICKETS[num]['title']}", callback_data=f"phys_task_ticket:{num}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="physics_tickets"))
    return builder.as_markup()

def get_physics_task_ticket_list_keyboard(num: str):
    builder = InlineKeyboardBuilder()
    for task in PHYSICS_TASK_TICKETS[num]["tasks"]:
        builder.button(text=f"📝 Задача {task['num']}", callback_data=f"phys_task_ticket_show:{num}:{task['num']}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К списку билетов", callback_data="physics_task_tickets"))
    return builder.as_markup()

def get_physics_task_ticket_detail_keyboard(num: str, task_num: int):
    builder = InlineKeyboardBuilder()
    tasks = PHYSICS_TASK_TICKETS[num]["tasks"]
    nums = [t["num"] for t in tasks]
    idx = nums.index(task_num)
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Предыдущая", callback_data=f"phys_task_ticket_show:{num}:{nums[idx-1]}"))
    if idx < len(nums) - 1:
        nav.append(InlineKeyboardButton(text="Следующая ➡️", callback_data=f"phys_task_ticket_show:{num}:{nums[idx+1]}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К списку задач", callback_data=f"phys_task_ticket:{num}"))
    return builder.as_markup()

def get_physics_test_tickets_keyboard():
    builder = InlineKeyboardBuilder()
    for num in sorted(PHYSICS_TEST_TICKETS.keys(), key=int):
        builder.button(text=f"📄 {PHYSICS_TEST_TICKETS[num]['title']}", callback_data=f"phys_test_ticket:{num}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="physics_tickets"))
    return builder.as_markup()

def get_physics_test_ticket_detail_keyboard(num: str):
    builder = InlineKeyboardBuilder()
    ticket = PHYSICS_TEST_TICKETS.get(num, {})
    if ticket.get("tasks"):
        builder.row(InlineKeyboardButton(text="🧮 Часть 2. Задачи", callback_data=f"phys_test_ticket_tasks:{num}"))
    builder.row(InlineKeyboardButton(text="🔙 К списку билетов", callback_data="physics_test_tickets"))
    return builder.as_markup()

def get_physics_test_ticket_task_list_keyboard(num: str):
    builder = InlineKeyboardBuilder()
    for task in PHYSICS_TEST_TICKETS[num]["tasks"]:
        builder.button(text=f"📝 Задача {task['num']}", callback_data=f"phys_test_ticket_task_show:{num}:{task['num']}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К билету", callback_data=f"phys_test_ticket:{num}"))
    return builder.as_markup()

def get_physics_test_ticket_task_detail_keyboard(num: str, task_num: int):
    builder = InlineKeyboardBuilder()
    tasks = PHYSICS_TEST_TICKETS[num]["tasks"]
    nums = [t["num"] for t in tasks]
    idx = nums.index(task_num)
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Предыдущая", callback_data=f"phys_test_ticket_task_show:{num}:{nums[idx-1]}"))
    if idx < len(nums) - 1:
        nav.append(InlineKeyboardButton(text="Следующая ➡️", callback_data=f"phys_test_ticket_task_show:{num}:{nums[idx+1]}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К списку задач", callback_data=f"phys_test_ticket_tasks:{num}"))
    return builder.as_markup()

def get_physics_theory_tickets_keyboard():
    builder = InlineKeyboardBuilder()
    for num in sorted(PHYSICS_THEORY_TICKETS.keys(), key=int):
        builder.button(text=f"📖 {PHYSICS_THEORY_TICKETS[num]['title']}", callback_data=f"phys_theory_ticket:{num}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="physics_tickets"))
    return builder.as_markup()

def get_physics_theory_ticket_detail_keyboard(num: str):
    builder = InlineKeyboardBuilder()
    ticket = PHYSICS_THEORY_TICKETS[num]
    for i, q in enumerate(ticket["questions"]):
        label = q["title"] if len(q["title"]) <= 60 else q["title"][:57] + "..."
        builder.button(text=f"{i + 1}. {label}", callback_data=f"phys_theory_q:{num}:{i}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К списку билетов", callback_data="physics_theory_tickets"))
    return builder.as_markup()

def get_physics_theory_question_keyboard(num: str, idx: int):
    builder = InlineKeyboardBuilder()
    total = len(PHYSICS_THEORY_TICKETS[num]["questions"])
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Предыдущий вопрос", callback_data=f"phys_theory_q:{num}:{idx - 1}"))
    if idx < total - 1:
        nav.append(InlineKeyboardButton(text="Следующий вопрос ➡️", callback_data=f"phys_theory_q:{num}:{idx + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К билету", callback_data=f"phys_theory_ticket:{num}"))
    return builder.as_markup()

def get_physics_tasks_topics_keyboard():
    builder = InlineKeyboardBuilder()
    for num, topic in sorted(PHYSICS_TASKS.items(), key=lambda x: int(x[0])):
        builder.button(text=f"📂 {topic['title']}", callback_data=f"phystask_topic:{num}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu_physics"))
    return builder.as_markup()

def get_physics_task_topic_keyboard(topic_num: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="📐 Формулы и алгоритм", callback_data=f"phystask_formulas:{topic_num}")
    builder.button(text="📋 Список задач", callback_data=f"phystask_list:{topic_num}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К темам", callback_data="physics_tasks"))
    return builder.as_markup()

def get_physics_formulas_keyboard(topic_num: str):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"phystask_topic:{topic_num}"))
    return builder.as_markup()

def get_physics_task_list_keyboard(topic_num: str):
    builder = InlineKeyboardBuilder()
    topic = PHYSICS_TASKS[topic_num]
    for task in topic["tasks"]:
        builder.button(text=f"📝 Задача {task['num']}", callback_data=f"phystask_show:{topic_num}:{task['num']}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"phystask_topic:{topic_num}"))
    return builder.as_markup()

def get_physics_task_detail_keyboard(topic_num: str, task_num: int):
    builder = InlineKeyboardBuilder()
    tasks = PHYSICS_TASKS[topic_num]["tasks"]
    nums = [t["num"] for t in tasks]
    idx = nums.index(task_num)
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Предыдущая", callback_data=f"phystask_show:{topic_num}:{nums[idx-1]}"))
    if idx < len(nums) - 1:
        nav.append(InlineKeyboardButton(text="Следующая ➡️", callback_data=f"phystask_show:{topic_num}:{nums[idx+1]}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К списку задач", callback_data=f"phystask_list:{topic_num}"))
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

def get_physics_answer_keyboard(q_num: str):
    builder = InlineKeyboardBuilder()
    n = int(q_num)
    nav = []
    if str(n - 1) in PHYSICS_QUESTIONS:
        nav.append(InlineKeyboardButton(text="⬅️ Предыдущий вопрос", callback_data=f"physics_q:{n - 1}"))
    if str(n + 1) in PHYSICS_QUESTIONS:
        nav.append(InlineKeyboardButton(text="Следующий вопрос ➡️", callback_data=f"physics_q:{n + 1}"))
    if nav:
        builder.row(*nav)
    page = (n - 1) // 50 + 1
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"physics_page:{page}"))
    return builder.as_markup()

def get_physics_grade45_keyboard():
    builder = InlineKeyboardBuilder()
    nums = sorted(PHYSICS_GRADE45_QUESTIONS.keys(), key=int)
    for i in range(0, len(nums), 5):
        row = [InlineKeyboardButton(text=f"🟢 {n}", callback_data=f"physics45_q:{n}") for n in nums[i:i + 5]]
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu_physics"))
    return builder.as_markup()

def get_physics_grade45_answer_keyboard(q_num: str):
    builder = InlineKeyboardBuilder()
    nums = sorted(PHYSICS_GRADE45_QUESTIONS.keys(), key=int)
    idx = nums.index(q_num)
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Предыдущий вопрос", callback_data=f"physics45_q:{nums[idx - 1]}"))
    if idx < len(nums) - 1:
        nav.append(InlineKeyboardButton(text="Следующий вопрос ➡️", callback_data=f"physics45_q:{nums[idx + 1]}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К списку вопросов", callback_data="physics_grade45"))
    return builder.as_markup()

def get_physics_extra_keyboard():
    builder = InlineKeyboardBuilder()
    for num in sorted(PHYSICS_EXTRA_QUESTIONS.keys(), key=int):
        builder.button(text=f"⭐ {PHYSICS_EXTRA_QUESTIONS[num]['title']}", callback_data=f"physics_extra_q:{num}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu_physics"))
    return builder.as_markup()

def get_physics_extra_answer_keyboard(q_num: str):
    builder = InlineKeyboardBuilder()
    nums = sorted(PHYSICS_EXTRA_QUESTIONS.keys(), key=int)
    idx = nums.index(q_num)
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Предыдущий вопрос", callback_data=f"physics_extra_q:{nums[idx - 1]}"))
    if idx < len(nums) - 1:
        nav.append(InlineKeyboardButton(text="Следующий вопрос ➡️", callback_data=f"physics_extra_q:{nums[idx + 1]}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К списку вопросов", callback_data="physics_extra"))
    return builder.as_markup()

# ==================== ХИМИЯ ====================
def get_chemistry_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="📚 Теория", callback_data="chemistry_theory")
    builder.button(text="📝 Задачи", callback_data="chemistry_tasks")
    builder.button(text="🧪 Лабораторные работы", callback_data="chemistry_labs")
    builder.button(text="🎫 Билеты", callback_data="chemistry_tickets")
    builder.button(text="📄 Все лабораторные работы (файл)", callback_data="download_chemistry_labs")
    builder.button(text="📄 Все задачи (файл)", callback_data="download_chemistry_tasks")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()

def chemistry_tickets_access_ok(user_id: int) -> bool:
    """Дополнительное, более строгое ограничение только для раздела «Билеты» химии — обычного
    гейта по предмету (референт REFERRAL_FULL_ACCESS_THRESHOLD рефералов ИЛИ любой доступ к
    Химии, включая ручной/временный доступ и промо) недостаточно. Сюда пускают только по
    REFERRAL_FULL_ACCESS_THRESHOLD рефералам либо по активной подписке ценой от 89₽ — то есть
    ручной/временный доступ и промо-акции ("Снять все ограничения") здесь не считаются."""
    if is_admin_or_assistant(user_id):
        return True
    if get_referral_count(user_id) >= REFERRAL_FULL_ACCESS_THRESHOLD:
        return True
    sub = get_subscription(user_id)
    if sub and has_active_subscription(user_id):
        cfg = SUBSCRIPTION_TIERS.get(sub.get("tier"), {})
        if cfg.get("price_rub", 0) >= 89:
            return True
    return False

def get_chemistry_tickets_locked_text() -> str:
    cheapest = cheapest_gated3_tier()
    return (
        f"🎫 <b>Билеты по химии</b>\n{DIVIDER}\n\n"
        f"Раздел закрыт дополнительным условием: нужно {REFERRAL_FULL_ACCESS_THRESHOLD} "
        f"реферала или подписка от 89₽ (например, «{cheapest['emoji']} {cheapest['title']}» за "
        f"{cheapest['price_rub']}₽ / {cheapest['price_stars']}⭐) — обычного доступа к Химии для "
        "билетов недостаточно.\n\n"
        "Пригласи друзей или оформи подписку, чтобы открыть раздел."
    )

def get_chemistry_tickets_locked_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 Пригласить друзей", callback_data="referral_info")
    builder.button(text="💎 Оформить подписку", callback_data="subscription_menu")
    builder.button(text="🔙 Назад", callback_data="menu_chemistry")
    builder.adjust(1)
    return builder.as_markup()

def get_chemistry_tickets_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="📖 Билеты теории", callback_data="chem_theory_tickets")
    builder.button(text="🧮 Билеты практики", callback_data="chem_practice_tickets")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu_chemistry"))
    return builder.as_markup()

def get_chemistry_theory_tickets_keyboard():
    builder = InlineKeyboardBuilder()
    for num in sorted(CHEMISTRY_THEORY_TICKETS.keys(), key=int):
        builder.button(text=f"📖 {CHEMISTRY_THEORY_TICKETS[num]['title']}", callback_data=f"chem_theory_ticket:{num}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="chemistry_tickets"))
    return builder.as_markup()

def get_chemistry_theory_ticket_detail_keyboard(num: str):
    builder = InlineKeyboardBuilder()
    ticket = CHEMISTRY_THEORY_TICKETS[num]
    for i, q in enumerate(ticket["questions"]):
        label = q["title"] if len(q["title"]) <= 60 else q["title"][:57] + "..."
        builder.button(text=f"{i + 1}. {label}", callback_data=f"chem_theory_q:{num}:{i}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К списку билетов", callback_data="chem_theory_tickets"))
    return builder.as_markup()

def get_chemistry_theory_question_keyboard(num: str, idx: int):
    builder = InlineKeyboardBuilder()
    total = len(CHEMISTRY_THEORY_TICKETS[num]["questions"])
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Предыдущий вопрос", callback_data=f"chem_theory_q:{num}:{idx - 1}"))
    if idx < total - 1:
        nav.append(InlineKeyboardButton(text="Следующий вопрос ➡️", callback_data=f"chem_theory_q:{num}:{idx + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К списку билетов", callback_data="chem_theory_tickets"))
    return builder.as_markup()

def get_chemistry_practice_tickets_keyboard():
    builder = InlineKeyboardBuilder()
    for num in sorted(CHEMISTRY_PRACTICE_TICKETS.keys(), key=int):
        builder.button(text=f"🧮 {CHEMISTRY_PRACTICE_TICKETS[num]['title']}", callback_data=f"chem_practice_ticket:{num}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="chemistry_tickets"))
    return builder.as_markup()

def get_chemistry_practice_ticket_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 К списку билетов", callback_data="chem_practice_tickets"))
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

def get_chemistry_tasks_topics_keyboard():
    builder = InlineKeyboardBuilder()
    for num, topic in sorted(CHEMISTRY_TASKS.items(), key=lambda x: int(x[0])):
        builder.button(text=f"📂 {topic['title']}", callback_data=f"chemtask_topic:{num}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu_chemistry"))
    return builder.as_markup()

def get_chemistry_task_topic_keyboard(topic_num: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="📐 Формулы и алгоритм", callback_data=f"chemtask_formulas:{topic_num}")
    builder.button(text="📋 Список задач", callback_data=f"chemtask_list:{topic_num}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К темам", callback_data="chemistry_tasks"))
    return builder.as_markup()

def get_chemistry_formulas_keyboard(topic_num: str):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"chemtask_topic:{topic_num}"))
    return builder.as_markup()

def get_chemistry_task_list_keyboard(topic_num: str):
    builder = InlineKeyboardBuilder()
    topic = CHEMISTRY_TASKS[topic_num]
    for task in topic["tasks"]:
        builder.button(text=f"📝 Задача {task['num']}", callback_data=f"chemtask_show:{topic_num}:{task['num']}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"chemtask_topic:{topic_num}"))
    return builder.as_markup()

def get_chemistry_task_detail_keyboard(topic_num: str, task_num: int):
    builder = InlineKeyboardBuilder()
    tasks = CHEMISTRY_TASKS[topic_num]["tasks"]
    nums = [t["num"] for t in tasks]
    idx = nums.index(task_num)
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Предыдущая", callback_data=f"chemtask_show:{topic_num}:{nums[idx-1]}"))
    if idx < len(nums) - 1:
        nav.append(InlineKeyboardButton(text="Следующая ➡️", callback_data=f"chemtask_show:{topic_num}:{nums[idx+1]}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К списку задач", callback_data=f"chemtask_list:{topic_num}"))
    return builder.as_markup()

# ==================== ГЛУБОКИЕ ССЫЛКИ (t.me/BOT?start=...) ====================
SECTION_DEEPLINKS = {
    "physics_tasks": (
        f"🧮 <b>Задачи по физике</b>\n{DIVIDER}\n\nВыбери тему:",
        lambda uid: get_physics_tasks_topics_keyboard(),
    ),
    "support_menu": (
        get_support_text(),
        lambda uid: get_support_keyboard(uid),
    ),
}

# ==================== ОБРАБОТЧИКИ ====================
@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    is_new_user = user_id not in stats["total_users"]
    stats["total_users"].add(user_id)
    stats["start_count"] += 1
    save_stats()

    payload = message.text.split(maxsplit=1)
    deep_link_key = None
    if len(payload) > 1:
        if payload[1].startswith("ref_"):
            referrer_id_str = payload[1][len("ref_"):]
            if referrer_id_str.isdigit():
                await register_referral(int(referrer_id_str), user_id)
        else:
            deep_link_key = payload[1]

    if not await is_subscribed(user_id):
        builder = InlineKeyboardBuilder()
        builder.button(text="📢 Открыть канал Vmeda_examen", url="https://t.me/Vmeda_examen")
        await message.answer(
            "👋 <b>Добро пожаловать!</b>\n\n"
            "Этот бот поможет подготовиться к экзаменам ВМедА:\n"
            "🧬 биология · ⚛️ физика · 🧪 химия\n\n"
            f"{DIVIDER}\n"
            "🔒 Чтобы пользоваться ботом, подпишись на канал:\n"
            "👉 https://t.me/Vmeda_examen\n\n"
            "После подписки нажми /start ещё раз.",
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )
        return

    if deep_link_key in SECTION_DEEPLINKS:
        text, keyboard_func = SECTION_DEEPLINKS[deep_link_key]
        await message.answer(text, parse_mode="HTML", reply_markup=keyboard_func(user_id))
        return

    if deep_link_key and deep_link_key.startswith("q_"):
        q_num = deep_link_key[len("q_"):]
        if q_num in QUESTIONS:
            stats["question_opened"][q_num] = stats["question_opened"].get(q_num, 0) + 1
            save_stats()
            q = QUESTIONS[q_num]
            header = f"❓ <b>Вопрос {q_num}</b>"
            body = f"{header}\n{DIVIDER}\n\n<b>{q['title']}</b>\n\n{q['answer']}"
            short_caption = f"{header}\n{DIVIDER}\n\n<b>{q['title']}</b>"
            await send_answer(message, body, short_caption, q, get_question_answer_keyboard(q_num), edit=False)
            return

    greeting = "🎉 <b>С возвращением!</b>" if not is_new_user else "👋 <b>Привет!</b>"
    await message.answer(
        f"{greeting}\n\nВыбери предмет для подготовки:",
        parse_mode="HTML",
        reply_markup=get_main_menu(user_id)
    )

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if not is_admin(message.from_user.id):
        return
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

    await safe_edit_text(
        status,
        "✅ <b>Рассылка завершена</b>\n"
        f"{DIVIDER}\n"
        f"Доставлено: <b>{sent}</b>\n"
        f"Не доставлено: <b>{failed}</b>",
        parse_mode="HTML"
    )

# ==================== АДМИН-ПАНЕЛЬ ====================
ADMIN_PENDING: dict = {}  # admin_id -> {"action": ...}
ADMIN_CHANNEL_POST_PREVIEW: dict = {}  # admin_id -> {"text": ..., "buttons": [(label, url), ...]}
ADMIN_USERLIST_PAGE_SIZE = 25

def parse_channel_post_buttons(raw: str):
    """Разбирает построчный ввод "Текст | Ссылка" в список кнопок.
    Возвращает None, если формат хотя бы одной строки некорректен."""
    buttons = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" not in line:
            return None
        label, url = line.split("|", 1)
        label = label.strip()
        url = url.strip()
        if not label or not url.startswith(("http://", "https://", "tg://")):
            return None
        buttons.append((label, url))
    return buttons or None

def build_channel_post_builder(buttons: list) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for label, url in buttons:
        builder.row(InlineKeyboardButton(text=label, url=url))
    return builder

def build_channel_post_keyboard(buttons: list):
    return build_channel_post_builder(buttons).as_markup() if buttons else None

def get_admin_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="📥 Экспорт stats.json", callback_data="admin_export_stats")
    builder.button(text="👥 Список пользователей", callback_data="admin_userlist:0")
    builder.button(text="🔓 Дать доступ по username/ID", callback_data="admin_grant_prompt")
    builder.button(text="🚫 Отозвать доступ по username/ID", callback_data="admin_revoke_prompt")
    builder.button(text="🦴 Дать демо-доступ к Анатомии", callback_data="admin_grant_anatomy_demo_prompt")
    builder.button(text="🦴🚫 Забрать демо-доступ к Анатомии", callback_data="admin_revoke_anatomy_demo_prompt")
    builder.button(text="🧑‍💼 Назначить помощника админа", callback_data="admin_grant_assistant_prompt")
    builder.button(text="🧑‍💼🚫 Снять помощника админа", callback_data="admin_revoke_assistant_prompt")
    builder.button(text="✉️ Написать пользователю", callback_data="admin_dm_prompt")
    builder.button(text="⚔️ Битва рефералов", callback_data="admin_battle_menu")
    builder.button(text="💰 Записать донат рублями", callback_data="admin_donation_prompt")
    builder.button(text="💎 Выдать подписку по username/ID", callback_data="admin_subscription_prompt")
    builder.button(text="📣 Оповещение о подписке", callback_data="admin_announce_subscription_confirm")
    builder.button(text="📣 Анонс раздела поддержки", callback_data="admin_announce_support_confirm")
    builder.button(text="🎁 Восстановить доступ исчерпавшим (7 дней)", callback_data="admin_restore_access_confirm")
    builder.button(
        text=f"📣 Напомнить о реферале/подписке (<{REFERRAL_FULL_ACCESS_THRESHOLD} реф.)",
        callback_data="admin_referral_reminder_confirm",
    )
    builder.button(
        text=f"🔥 Скидка 10% без рефералов (<{REFERRAL_FULL_ACCESS_THRESHOLD} реф.)",
        callback_data="admin_discount_promo_confirm",
    )
    builder.button(text="📣 Анонс раздела Анатомия", callback_data="admin_announce_anatomy_confirm")
    builder.button(text="📣 Анонс Экзамена (ТЕСТ/теория/практика)", callback_data="admin_announce_anatomy_exam_confirm")
    builder.button(text="📣 Анонс теста по латыни", callback_data="admin_announce_anatomy_latin_confirm")
    builder.button(text="📤 Опубликовать пост в канал", callback_data="admin_channel_post_prompt")
    builder.button(text="🔬 Открыть Гистологию всем на 24ч", callback_data="admin_histology_promo_confirm")
    builder.button(text="🎉 Снять все ограничения всем на 24ч", callback_data="admin_global_promo_confirm")
    builder.button(text="🎉 Снять все ограничения всем на 12ч", callback_data="admin_global_promo_12h_confirm")
    builder.button(text="🔒 Вернуть ограничения", callback_data="admin_restore_restrictions_confirm")
    builder.button(text="📋 Анонс переклички групп", callback_data="admin_announce_rollcall_confirm")
    builder.adjust(1)
    return builder.as_markup()

def get_admin_battle_keyboard():
    builder = InlineKeyboardBuilder()
    if is_battle_active():
        builder.button(text="🔄 Обновить", callback_data="admin_battle_menu")
        builder.button(text="📣 Разослать напоминание о битве", callback_data="admin_battle_remind_confirm")
        builder.button(text="🛑 Завершить досрочно", callback_data="admin_battle_end_confirm")
    else:
        builder.button(text="🚀 Начать битву рефералов (неделя)", callback_data="admin_battle_start_confirm")
    battle = stats.get("referral_battle")
    if battle and battle.get("results") is not None:
        builder.button(text="🏁 Итоги последней битвы (для публикации)", callback_data="admin_battle_last_results")
    builder.button(text="🔙 В админ-панель", callback_data="admin_panel")
    builder.adjust(1)
    return builder.as_markup()

def get_admin_battle_text() -> str:
    if is_battle_active():
        battle = stats["referral_battle"]
        remaining = format_time_left(battle["end_ts"] - time.time())
        leaderboard = get_battle_leaderboard()
        lines = [
            f"⚔️ <b>Битва рефералов — идёт!</b>\n{DIVIDER}\n",
            BATTLE_CHANNEL_POSTING_NOTICE,
            "",
            f"⏳ Осталось: <b>{remaining}</b>\n",
        ]
        if leaderboard:
            for i, (uid, diff) in enumerate(leaderboard):
                name = stats["user_names"].get(uid, f"Пользователь {uid}")
                lines.append(f"{battle_place_icon(i)} {name} — <b>{diff}</b>")
        else:
            lines.append("Пока никто не пригласил друзей в рамках битвы.")
        return "\n".join(lines)
    return (
        f"⚔️ <b>Битва рефералов</b>\n{DIVIDER}\n\n"
        "Сейчас битва не идёт.\n\n"
        f"Запусти битву на {format_battle_duration()} — топ-5 пользователей по числу приглашённых друзей за это время "
        f"получат призы:\n\n{format_battle_prizes_block()}\n\n"
        "Всем пользователям бота придёт рассылка с объявлением о старте и правилах."
    )

def get_admin_back_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 В админ-панель", callback_data="admin_panel"))
    return builder.as_markup()

def resolve_user_by_username(raw: str):
    """Резолвит введённый админом идентификатор — username (с @ или без) или
    числовой Telegram ID — в (username_или_None, target_id_или_None). ID должен
    принадлежать пользователю, который уже писал боту. username может быть None,
    если пользователь найден по ID, но своего username у него нет."""
    identifier = raw.strip().lstrip("@")
    if identifier.isdigit():
        user_id = int(identifier)
        if user_id in stats["total_users"]:
            return stats["user_username"].get(str(user_id)), user_id
        return None, None
    username = identifier.lower()
    return username, stats["usernames"].get(username)

def format_admin_target_label(username, target_id: int) -> str:
    return f"@{username} (ID {target_id})" if username else f"ID {target_id}"

def format_user_line(user_id: int) -> str:
    uid_str = str(user_id)
    username = stats["user_username"].get(uid_str)
    handle = f"@{username}" if username else "(без username)"
    name = stats["user_names"].get(uid_str, "—")
    refs = len(stats["referrals"].get(uid_str, []))
    granted = " 🔓" if user_id in stats["manual_access_granted"] else ""
    anatomy_demo = " 🦴" if user_id in stats["manual_anatomy_demo_granted"] else ""
    assistant = " 🧑‍💼" if user_id in stats["assistant_admins"] else ""
    return f"<code>{user_id}</code> — {handle} — {name} — реф: {refs}{granted}{anatomy_demo}{assistant}"

def get_admin_userlist_page(page: int):
    all_ids = sorted(stats["total_users"])
    total = len(all_ids)
    start = page * ADMIN_USERLIST_PAGE_SIZE
    end = start + ADMIN_USERLIST_PAGE_SIZE
    chunk = all_ids[start:end]
    lines = [f"👥 <b>Пользователи</b> ({total} всего)\n{DIVIDER}"]
    lines.extend(format_user_line(uid) for uid in chunk)
    text = "\n".join(lines)
    builder = InlineKeyboardBuilder()
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"admin_userlist:{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"admin_userlist:{page+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 В админ-панель", callback_data="admin_panel"))
    return text, builder.as_markup()

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    user_id = message.from_user.id
    if is_admin(user_id):
        await message.answer(
            f"🛠 <b>Админ-панель</b>\n{DIVIDER}\n\nВыбери действие:",
            parse_mode="HTML",
            reply_markup=get_admin_menu()
        )
        return
    if is_assistant_admin(user_id):
        await message.answer(
            get_assistant_admin_menu_text(),
            parse_mode="HTML",
            reply_markup=get_assistant_admin_menu_keyboard()
        )

@dp.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    ADMIN_PENDING.pop(callback.from_user.id, None)
    await safe_edit_text(
        callback.message,
        f"🛠 <b>Админ-панель</b>\n{DIVIDER}\n\nВыбери действие:",
        parse_mode="HTML",
        reply_markup=get_admin_menu()
    )

@dp.callback_query(F.data == "admin_battle_menu")
async def cb_admin_battle_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    await safe_edit_text(
        callback.message,
        get_admin_battle_text(),
        parse_mode="HTML",
        reply_markup=get_admin_battle_keyboard()
    )

@dp.callback_query(F.data == "admin_battle_last_results")
async def cb_admin_battle_last_results(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    battle = stats.get("referral_battle")
    results = battle.get("results") if battle else None
    if results is None:
        await callback.answer("Нет сохранённых итогов ни одной завершённой битвы", show_alert=True)
        return
    await callback.answer()
    text = get_battle_results_announcement_text(results)
    await safe_edit_text(
        callback.message,
        f"{text}\n\n{DIVIDER}\n"
        "👆 Текст выше — в том же виде, что уходит пользователям рассылкой. "
        "Скопируй его, чтобы опубликовать отдельно.",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.callback_query(F.data == "admin_battle_start_confirm")
async def cb_admin_battle_start_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, начать битву на неделю", callback_data="admin_battle_start_go")
    builder.button(text="❌ Отмена", callback_data="admin_battle_menu")
    builder.adjust(1)
    await safe_edit_text(
        callback.message,
        "⚔️ <b>Подтверди запуск битвы рефералов</b>\n\n"
        f"Битва продлится {format_battle_duration()}, топ-5 по числу новых приглашённых получат призы:\n\n"
        f"{format_battle_prizes_block()}\n\nВсем пользователям придёт рассылка с объявлением.",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "admin_battle_start_go")
async def cb_admin_battle_start_go(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    if is_battle_active():
        await callback.answer("Битва уже идёт", show_alert=True)
        return
    await callback.answer("🚀 Битва запущена!", show_alert=True)
    start_referral_battle()
    asyncio.create_task(_battle_timer(stats["referral_battle"]["end_ts"]))
    asyncio.create_task(announce_battle_start())
    await safe_edit_text(
        callback.message,
        get_admin_battle_text(),
        parse_mode="HTML",
        reply_markup=get_admin_battle_keyboard()
    )

@dp.callback_query(F.data == "admin_histology_promo_confirm")
async def cb_admin_histology_promo_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, открыть на 24ч", callback_data="admin_histology_promo_go")
    builder.button(text="❌ Отмена", callback_data="admin_panel")
    builder.adjust(1)
    await safe_edit_text(
        callback.message,
        "🔬 <b>Подтверди промо-доступ к Гистологии</b>\n\n"
        "Раздел станет бесплатным для всех на 24 часа. После этого доступ вернётся к обычному "
        f"правилу: {REFERRAL_FULL_ACCESS_THRESHOLD} реферала или подписка (как остальные предметы).\n\n"
        "Всем пользователям придёт рассылка с объявлением.",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "admin_histology_promo_go")
async def cb_admin_histology_promo_go(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    if is_section_promo_active("histology"):
        await callback.answer("Промо уже идёт", show_alert=True)
        return
    await callback.answer("🚀 Гистология открыта для всех на 24 часа!", show_alert=True)
    start_section_promo("histology", HISTOLOGY_PROMO_SECONDS)
    asyncio.create_task(announce_histology_promo_start())
    await safe_edit_text(
        callback.message,
        "✅ Гистология открыта для всех на 24 часа.",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.callback_query(F.data == "admin_global_promo_confirm")
async def cb_admin_global_promo_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, открыть всё на 24ч", callback_data="admin_global_promo_go")
    builder.button(text="❌ Отмена", callback_data="admin_panel")
    builder.adjust(1)
    await safe_edit_text(
        callback.message,
        "🎉 <b>Подтверди снятие всех ограничений</b>\n\n"
        "Биология, Физика, Химия и Гистология станут бесплатными для всех пользователей на 24 часа — "
        "без рефералов и подписки. Анатомия (ещё в разработке) и скачивание билетов по биологии "
        "(всегда только по подписке) промо не затрагивает. После 24 часов доступ вернётся к обычным "
        "правилам каждого раздела.\n\n"
        "Всем пользователям придёт рассылка с объявлением.",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "admin_global_promo_go")
async def cb_admin_global_promo_go(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    if is_section_promo_active("global"):
        await callback.answer("Промо уже идёт", show_alert=True)
        return
    await callback.answer("🚀 Все ограничения сняты на 24 часа!", show_alert=True)
    start_section_promo("global", GLOBAL_PROMO_SECONDS)
    asyncio.create_task(announce_global_promo_start())
    await safe_edit_text(
        callback.message,
        "✅ Все ограничения сняты для всех на 24 часа.",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.callback_query(F.data == "admin_global_promo_12h_confirm")
async def cb_admin_global_promo_12h_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, открыть всё на 12ч", callback_data="admin_global_promo_12h_go")
    builder.button(text="❌ Отмена", callback_data="admin_panel")
    builder.adjust(1)
    await safe_edit_text(
        callback.message,
        "🎉 <b>Подтверди снятие всех ограничений на 12ч</b>\n\n"
        "Биология, Физика, Химия и Гистология станут бесплатными для всех пользователей на 12 часов — "
        "без рефералов и подписки. Анатомия (ещё в разработке) и скачивание билетов по биологии "
        "(всегда только по подписке) промо не затрагивает. После 12 часов доступ вернётся к обычным "
        "правилам каждого раздела.\n\n"
        "Всем пользователям придёт рассылка с объявлением.",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "admin_global_promo_12h_go")
async def cb_admin_global_promo_12h_go(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    if is_section_promo_active("global"):
        await callback.answer("Промо уже идёт", show_alert=True)
        return
    await callback.answer("🚀 Все ограничения сняты на 12 часов!", show_alert=True)
    start_section_promo("global", GLOBAL_PROMO_12H_SECONDS)
    asyncio.create_task(announce_global_promo_12h_start())
    await safe_edit_text(
        callback.message,
        "✅ Все ограничения сняты для всех на 12 часов.",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.callback_query(F.data == "admin_restore_restrictions_confirm")
async def cb_admin_restore_restrictions_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    active = [section for section, until in stats.get("section_promos", {}).items() if time.time() < until]
    if not active:
        await safe_edit_text(
            callback.message,
            "🔒 Сейчас нет активных промо-доступов — возвращать нечего.",
            parse_mode="HTML",
            reply_markup=get_admin_back_keyboard()
        )
        return
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, вернуть ограничения", callback_data="admin_restore_restrictions_go")
    builder.button(text="❌ Отмена", callback_data="admin_panel")
    builder.adjust(1)
    await safe_edit_text(
        callback.message,
        "🔒 <b>Подтверди возврат ограничений</b>\n\n"
        f"Сейчас активны промо-доступы: {', '.join(active)}. Все они будут закрыты немедленно, доступ "
        "вернётся к обычным правилам каждого раздела.",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "admin_restore_restrictions_go")
async def cb_admin_restore_restrictions_go(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    stats["section_promos"] = {}
    save_stats()
    await callback.answer("🔒 Ограничения возвращены для всех.", show_alert=True)
    await safe_edit_text(
        callback.message,
        "✅ Все активные промо-доступы закрыты, ограничения возвращены.",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.callback_query(F.data == "admin_battle_end_confirm")
async def cb_admin_battle_end_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, завершить битву", callback_data="admin_battle_end_go")
    builder.button(text="❌ Отмена", callback_data="admin_battle_menu")
    builder.adjust(1)
    await safe_edit_text(
        callback.message,
        "🛑 <b>Завершить битву досрочно?</b>\n\nПобедители будут определены по текущему рейтингу, "
        "всем пользователям придёт рассылка с итогами.",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "admin_battle_end_go")
async def cb_admin_battle_end_go(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer("Битва завершена")
    await resolve_referral_battle()
    await safe_edit_text(
        callback.message,
        get_admin_battle_text(),
        parse_mode="HTML",
        reply_markup=get_admin_battle_keyboard()
    )

@dp.callback_query(F.data == "admin_battle_remind_confirm")
async def cb_admin_battle_remind_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    if not is_battle_active():
        await callback.answer("Битва сейчас не идёт", show_alert=True)
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить всем", callback_data="admin_battle_remind_go")
    builder.button(text="❌ Отмена", callback_data="admin_battle_menu")
    builder.adjust(1)
    preview = (
        f"👀 <b>Предпросмотр напоминания</b>\n{DIVIDER}\n\n"
        f"{get_battle_remind_broadcast_text()}\n\n{DIVIDER}\n"
        f"Отправить это всем {len(stats['total_users'])} пользователям?"
    )
    await safe_edit_text(callback.message, preview, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "admin_battle_remind_go")
async def cb_admin_battle_remind_go(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    if not is_battle_active():
        await callback.answer("Битва сейчас не идёт", show_alert=True)
        return
    await callback.answer("📣 Рассылка запущена!", show_alert=True)
    recipients = len(stats["total_users"])
    stats["broadcast_count"] = stats.get("broadcast_count", 0) + 1
    save_stats()
    builder = InlineKeyboardBuilder()
    builder.button(text="⚔️ Битва рефералов", callback_data="referral_battle")
    await _broadcast(get_battle_remind_broadcast_text(), builder.as_markup())
    await safe_edit_text(
        callback.message,
        f"✅ Напоминание о битве рефералов отправлено (попытка охватить {recipients} пользователей).",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.callback_query(F.data == "admin_restore_access_confirm")
async def cb_admin_restore_access_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    cohort = get_exhausted_users()
    if not cohort:
        await callback.answer("Сейчас нет пользователей с исчерпанным доступом", show_alert=True)
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Восстановить и отправить", callback_data="admin_restore_access_go")
    builder.button(text="❌ Отмена", callback_data="admin_panel")
    builder.adjust(1)
    preview = (
        f"👀 <b>Предпросмотр рассылки</b>\n{DIVIDER}\n\n"
        f"{get_access_restored_broadcast_text()}\n\n{DIVIDER}\n"
        f"Доступ будет восстановлен на 7 дней и рассылка отправлена {len(cohort)} пользователям, "
        "у которых закончились бесплатные заходы без рефералов.\n"
        "Правило с рефералами для остальных пользователей не изменится."
    )
    await safe_edit_text(callback.message, preview, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "admin_restore_access_go")
async def cb_admin_restore_access_go(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    cohort = get_exhausted_users()
    if not cohort:
        await callback.answer("Сейчас нет пользователей с исчерпанным доступом", show_alert=True)
        return
    await callback.answer("🎁 Восстанавливаю доступ и отправляю рассылку!", show_alert=True)
    expiry = time.time() + TEMP_ACCESS_GRANT_SECONDS
    for uid in cohort:
        stats["temporary_access"][str(uid)] = expiry
    stats["broadcast_count"] = stats.get("broadcast_count", 0) + 1
    save_stats()
    await _broadcast_to(cohort, get_access_restored_broadcast_text())
    await safe_edit_text(
        callback.message,
        f"✅ Доступ восстановлен на 7 дней, рассылка отправлена (попытка охватить {len(cohort)} пользователей).\n\n"
        "Правило с рефералами (2 друга для доступа навсегда) для остальных не изменилось.",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.callback_query(F.data == "admin_referral_reminder_confirm")
async def cb_admin_referral_reminder_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    cohort = get_below_threshold_users()
    if not cohort:
        await callback.answer("Сейчас нет пользователей без бесплатного доступа", show_alert=True)
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить напоминание", callback_data="admin_referral_reminder_go")
    builder.button(text="❌ Отмена", callback_data="admin_panel")
    builder.adjust(1)
    preview = (
        f"👀 <b>Предпросмотр рассылки</b>\n{DIVIDER}\n\n"
        f"{get_referral_reminder_broadcast_text()}\n\n{DIVIDER}\n"
        f"Рассылка уйдёт {len(cohort)} пользователям, у которых меньше "
        f"{REFERRAL_FULL_ACCESS_THRESHOLD} рефералов и нет подписки/ручного/временного доступа. "
        "Никакой доступ не выдаётся — только напоминание пригласить друзей или оформить подписку."
    )
    await safe_edit_text(callback.message, preview, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "admin_referral_reminder_go")
async def cb_admin_referral_reminder_go(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    cohort = get_below_threshold_users()
    if not cohort:
        await callback.answer("Сейчас нет пользователей без бесплатного доступа", show_alert=True)
        return
    await callback.answer("📣 Рассылка запущена!", show_alert=True)
    stats["broadcast_count"] = stats.get("broadcast_count", 0) + 1
    save_stats()
    await _broadcast_to(cohort, get_referral_reminder_broadcast_text(), get_referral_reminder_broadcast_keyboard())
    await safe_edit_text(
        callback.message,
        f"✅ Напоминание отправлено (попытка охватить {len(cohort)} пользователей).",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.callback_query(F.data == "admin_discount_promo_confirm")
async def cb_admin_discount_promo_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    cohort = get_below_threshold_users()
    if not cohort:
        await callback.answer("Сейчас нет пользователей без бесплатного доступа", show_alert=True)
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить рассылку", callback_data="admin_discount_promo_go")
    builder.button(text="❌ Отмена", callback_data="admin_panel")
    builder.adjust(1)
    preview = (
        f"👀 <b>Предпросмотр рассылки</b>\n{DIVIDER}\n\n"
        f"{get_discount_promo_broadcast_text()}\n\n{DIVIDER}\n"
        f"Рассылка уйдёт {len(cohort)} пользователям, у которых меньше "
        f"{REFERRAL_FULL_ACCESS_THRESHOLD} рефералов и нет подписки/ручного/временного доступа. "
        "Кнопки в рассылке ведут прямо на оформление подписки со скидкой."
    )
    await safe_edit_text(callback.message, preview, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "admin_discount_promo_go")
async def cb_admin_discount_promo_go(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    cohort = get_below_threshold_users()
    if not cohort:
        await callback.answer("Сейчас нет пользователей без бесплатного доступа", show_alert=True)
        return
    await callback.answer("📣 Рассылка запущена!", show_alert=True)
    stats["broadcast_count"] = stats.get("broadcast_count", 0) + 1
    save_stats()
    await _broadcast_to(cohort, get_discount_promo_broadcast_text(), get_discount_promo_broadcast_keyboard())
    await safe_edit_text(
        callback.message,
        f"✅ Рассылка со скидкой отправлена (попытка охватить {len(cohort)} пользователей).",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    total_referrals = sum(len(v) for v in stats["referrals"].values())
    exhausted_free_uses = len(get_exhausted_users())
    below_threshold_count = sum(
        1 for uid in stats["total_users"] if get_referral_count(uid) < REFERRAL_FULL_ACCESS_THRESHOLD
    )

    subs = stats["subscriptions"]
    active_by_tier = {tier_id: 0 for tier_id in SUBSCRIPTION_TIERS}
    active_total = 0
    sub_revenue_stars = 0
    sub_revenue_rubles = 0
    for uid_str, sub in subs.items():
        method = sub.get("method")
        price = sub.get("price", 0)
        if method == "stars":
            sub_revenue_stars += price
        elif method == "rubles":
            sub_revenue_rubles += price
        if has_active_subscription(int(uid_str)):
            active_total += 1
            tier = sub.get("tier")
            if tier in active_by_tier:
                active_by_tier[tier] += 1
    subscription_lines = "\n".join(
        f"  {cfg['emoji']} {cfg['short']}: <b>{active_by_tier[tier_id]}</b>"
        for tier_id, cfg in SUBSCRIPTION_TIERS.items()
    )

    donation_stars_total = stats.get("donations_stars_total", 0)
    donation_stars_count = stats.get("donations_stars_count", 0)
    donation_rubles_total = sum(stats.get("donor_rubles", {}).values())
    donation_rubles_count = len(stats.get("donor_rubles", {}))

    text = (
        f"📊 <b>Статистика бота</b>\n{DIVIDER}\n\n"
        f"👥 Уникальных пользователей: <b>{len(stats['total_users'])}</b>\n"
        f"▶️ Запусков бота: <b>{stats['start_count']}</b>\n"
        f"❓ Вопросов просмотрено: <b>{sum(stats['question_opened'].values())}</b>\n"
        f"🎲 Случайных билетов открыто: <b>{stats['random_ticket_used']}</b>\n"
        f"🎲 Случайных вопросов открыто: <b>{stats['random_question_used']}</b>\n"
        f"📢 Рассылок отправлено: <b>{stats.get('broadcast_count', 0)}</b>\n"
        f"🔗 Всего рефералов: <b>{total_referrals}</b>\n"
        f"📉 Меньше {REFERRAL_FULL_ACCESS_THRESHOLD} рефералов: <b>{below_threshold_count}</b>\n"
        f"🔓 Ручных доступов выдано: <b>{len(stats['manual_access_granted'])}</b>\n"
        f"🦴 Демо-доступов к Анатомии выдано: <b>{len(stats['manual_anatomy_demo_granted'])}</b>\n"
        f"🚫 Исчерпали бесплатные заходы без рефералов: <b>{exhausted_free_uses}</b>\n"
        f"🪪 Известно username: <b>{len(stats['usernames'])}</b>\n"
        f"\n💎 <b>Подписки</b>\n"
        f"Всего куплено: <b>{len(subs)}</b>, активных сейчас: <b>{active_total}</b>\n"
        f"{subscription_lines}\n"
        f"\n💰 <b>Платежи</b>\n"
        f"⭐ Донаты звёздами: <b>{donation_stars_total}</b> ({donation_stars_count} платежей)\n"
        f"💵 Донаты рублями: <b>{donation_rubles_total}</b>₽ ({donation_rubles_count} чел.)\n"
        f"⭐ Подписки звёздами: <b>{sub_revenue_stars}</b>\n"
        f"💵 Подписки рублями: <b>{sub_revenue_rubles}</b>₽\n"
        f"{get_ai_cost_stats_block()}"
    )
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=get_admin_back_keyboard())

@dp.callback_query(F.data == "admin_export_stats")
async def cb_admin_export_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    if not os.path.exists(STATS_FILE):
        await callback.message.answer("Файл stats.json ещё не создан.")
        return
    await callback.message.answer_document(
        FSInputFile(STATS_FILE),
        caption=f"📥 Текущий stats.json (снимок на момент запроса, только чтение — сама выгрузка ничего не меняет).\n\n@{BOT_USERNAME}"
    )

@dp.callback_query(F.data.startswith("admin_userlist:"))
async def cb_admin_userlist(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    page = int(callback.data.split(":")[1])
    text, kb = get_admin_userlist_page(page)
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "admin_grant_prompt")
async def cb_admin_grant_prompt(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    ADMIN_PENDING[callback.from_user.id] = {"action": "grant"}
    await safe_edit_text(
        callback.message,
        "🔓 <b>Выдать доступ</b>\n\nОтправь username пользователя (с @ или без, например <code>@ivanov</code>) "
        "или его числовой ID",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.callback_query(F.data == "admin_revoke_prompt")
async def cb_admin_revoke_prompt(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    ADMIN_PENDING[callback.from_user.id] = {"action": "revoke"}
    await safe_edit_text(
        callback.message,
        "🚫 <b>Отозвать ручной доступ</b>\n\nОтправь username пользователя (с @ или без) или его числовой ID",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.callback_query(F.data == "admin_grant_anatomy_demo_prompt")
async def cb_admin_grant_anatomy_demo_prompt(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    ADMIN_PENDING[callback.from_user.id] = {"action": "grant_anatomy_demo"}
    await safe_edit_text(
        callback.message,
        "🦴 <b>Дать демо-доступ к Анатомии</b>\n\nОтправь username пользователя (с @ или без, например <code>@ivanov</code>) "
        "или его числовой ID",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.callback_query(F.data == "admin_revoke_anatomy_demo_prompt")
async def cb_admin_revoke_anatomy_demo_prompt(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    ADMIN_PENDING[callback.from_user.id] = {"action": "revoke_anatomy_demo"}
    await safe_edit_text(
        callback.message,
        "🦴🚫 <b>Забрать демо-доступ к Анатомии</b>\n\nОтправь username пользователя (с @ или без) или его числовой ID",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.callback_query(F.data == "admin_grant_assistant_prompt")
async def cb_admin_grant_assistant_prompt(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    ADMIN_PENDING[callback.from_user.id] = {"action": "grant_assistant_admin"}
    await safe_edit_text(
        callback.message,
        "🧑‍💼 <b>Назначить помощника админа</b>\n\n"
        "Помощник получит доступ ко всем разделам бота, ограниченную статистику и сможет "
        "писать пользователям — но только с твоего подтверждения на каждое сообщение. "
        "Полных прав админ-панели (выдача доступа, рассылки, подписки) у него не будет.\n\n"
        "Отправь username пользователя (с @ или без, например <code>@ivanov</code>) или его числовой ID",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.callback_query(F.data == "admin_revoke_assistant_prompt")
async def cb_admin_revoke_assistant_prompt(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    ADMIN_PENDING[callback.from_user.id] = {"action": "revoke_assistant_admin"}
    await safe_edit_text(
        callback.message,
        "🧑‍💼🚫 <b>Снять помощника админа</b>\n\nОтправь username пользователя (с @ или без) или его числовой ID",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.callback_query(F.data == "admin_dm_prompt")
async def cb_admin_dm_prompt(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    ADMIN_PENDING[callback.from_user.id] = {"action": "dm_username"}
    await safe_edit_text(
        callback.message,
        "✉️ <b>Личное сообщение</b>\n\nОтправь username пользователя (с @ или без) или его числовой ID "
        "— например, из «👥 Список пользователей»",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.callback_query(F.data == "admin_donation_prompt")
async def cb_admin_donation_prompt(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    ADMIN_PENDING[callback.from_user.id] = {"action": "record_donation_username"}
    await safe_edit_text(
        callback.message,
        "💰 <b>Записать пожертвование рублями</b>\n\n"
        "Переводы в рублях идут напрямую в чат с @vmeda_helper, бот их не видит — "
        "запиши сюда вручную, чтобы человек попал в рейтинг донатеров.\n\n"
        "Отправь username пользователя (с @ или без) или его числовой ID",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.callback_query(F.data == "admin_subscription_prompt")
async def cb_admin_subscription_prompt(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    ADMIN_PENDING[callback.from_user.id] = {"action": "record_subscription_username"}
    await safe_edit_text(
        callback.message,
        "💎 <b>Выдать подписку</b>\n\n"
        "Для оплат рублями (перевод в чате с @vmeda_helper) подписку нужно включить вручную "
        "после подтверждения оплаты.\n\n"
        "Отправь username пользователя (с @ или без) или его числовой ID",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.callback_query(F.data == "admin_announce_support_confirm")
async def cb_admin_announce_support_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить всем", callback_data="admin_announce_support_go")
    builder.button(text="❌ Отмена", callback_data="admin_panel")
    builder.adjust(1)
    preview = (
        f"👀 <b>Предпросмотр анонса</b>\n{DIVIDER}\n\n"
        f"{get_support_announcement_text()}\n\n{DIVIDER}\n"
        f"Отправить это всем {len(stats['total_users'])} пользователям?"
    )
    await safe_edit_text(callback.message, preview, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "admin_announce_support_go")
async def cb_admin_announce_support_go(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer("📣 Рассылка запущена!", show_alert=True)
    recipients = len(stats["total_users"])
    stats["broadcast_count"] = stats.get("broadcast_count", 0) + 1
    save_stats()
    await _broadcast(get_support_announcement_text(), get_support_announcement_keyboard())
    await safe_edit_text(
        callback.message,
        f"✅ Анонс раздела поддержки отправлен (попытка охватить {recipients} пользователей).",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.callback_query(F.data == "admin_announce_subscription_confirm")
async def cb_admin_announce_subscription_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить всем", callback_data="admin_announce_subscription_go")
    builder.button(text="❌ Отмена", callback_data="admin_panel")
    builder.adjust(1)
    preview = (
        f"👀 <b>Предпросмотр анонса</b>\n{DIVIDER}\n\n"
        f"{get_subscription_announcement_text()}\n\n{DIVIDER}\n"
        f"Отправить это всем {len(stats['total_users'])} пользователям?"
    )
    await safe_edit_text(callback.message, preview, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "admin_announce_subscription_go")
async def cb_admin_announce_subscription_go(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer("📣 Рассылка запущена!", show_alert=True)
    recipients = len(stats["total_users"])
    stats["broadcast_count"] = stats.get("broadcast_count", 0) + 1
    save_stats()
    await _broadcast(get_subscription_announcement_text(), get_subscription_announcement_keyboard())
    await safe_edit_text(
        callback.message,
        f"✅ Оповещение о подписке отправлено (попытка охватить {recipients} пользователей).",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.callback_query(F.data == "admin_announce_anatomy_confirm")
async def cb_admin_announce_anatomy_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить всем", callback_data="admin_announce_anatomy_go")
    builder.button(text="❌ Отмена", callback_data="admin_panel")
    builder.adjust(1)
    preview = (
        f"👀 <b>Предпросмотр анонса</b>\n{DIVIDER}\n\n"
        f"{get_anatomy_announcement_text()}\n\n{DIVIDER}\n"
        f"Отправить это всем {len(stats['total_users'])} пользователям?"
    )
    await safe_edit_text(callback.message, preview, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "admin_announce_anatomy_go")
async def cb_admin_announce_anatomy_go(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer("📣 Рассылка запущена!", show_alert=True)
    recipients = len(stats["total_users"])
    stats["broadcast_count"] = stats.get("broadcast_count", 0) + 1
    save_stats()
    await _broadcast(get_anatomy_announcement_text(), get_anatomy_announcement_keyboard())
    await safe_edit_text(
        callback.message,
        f"✅ Анонс раздела Анатомия отправлен (попытка охватить {recipients} пользователей).",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.callback_query(F.data == "admin_announce_anatomy_exam_confirm")
async def cb_admin_announce_anatomy_exam_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить всем", callback_data="admin_announce_anatomy_exam_go")
    builder.button(text="❌ Отмена", callback_data="admin_panel")
    builder.adjust(1)
    preview = (
        f"👀 <b>Предпросмотр анонса</b>\n{DIVIDER}\n\n"
        f"{get_anatomy_exam_announcement_text()}\n\n{DIVIDER}\n"
        f"Отправить это всем {len(stats['total_users'])} пользователям?"
    )
    await safe_edit_text(callback.message, preview, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "admin_announce_anatomy_exam_go")
async def cb_admin_announce_anatomy_exam_go(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer("📣 Рассылка запущена!", show_alert=True)
    recipients = len(stats["total_users"])
    stats["broadcast_count"] = stats.get("broadcast_count", 0) + 1
    save_stats()
    await _broadcast(get_anatomy_exam_announcement_text(), get_anatomy_exam_announcement_keyboard())
    await safe_edit_text(
        callback.message,
        f"✅ Анонс раздела Экзамен отправлен (попытка охватить {recipients} пользователей).",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.callback_query(F.data == "admin_announce_anatomy_latin_confirm")
async def cb_admin_announce_anatomy_latin_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить всем", callback_data="admin_announce_anatomy_latin_go")
    builder.button(text="❌ Отмена", callback_data="admin_panel")
    builder.adjust(1)
    preview = (
        f"👀 <b>Предпросмотр анонса</b>\n{DIVIDER}\n\n"
        f"{get_anatomy_latin_announcement_text()}\n\n{DIVIDER}\n"
        f"Отправить это всем {len(stats['total_users'])} пользователям?"
    )
    await safe_edit_text(callback.message, preview, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "admin_announce_anatomy_latin_go")
async def cb_admin_announce_anatomy_latin_go(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer("📣 Рассылка запущена!", show_alert=True)
    recipients = len(stats["total_users"])
    stats["broadcast_count"] = stats.get("broadcast_count", 0) + 1
    save_stats()
    await _broadcast(get_anatomy_latin_announcement_text(), get_anatomy_latin_announcement_keyboard())
    await safe_edit_text(
        callback.message,
        f"✅ Анонс теста по латыни отправлен (попытка охватить {recipients} пользователей).",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.callback_query(F.data == "admin_channel_post_prompt")
async def cb_admin_channel_post_prompt(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    ADMIN_PENDING[callback.from_user.id] = {"action": "channel_post_text"}
    await safe_edit_text(
        callback.message,
        f"📤 <b>Пост в канал {CHANNEL_ID}</b>\n{DIVIDER}\n\n"
        "Пришли текст поста (можно с форматированием Telegram — жирный, курсив, ссылки и т.д. "
        "— просто выдели текст и примени стиль перед отправкой).",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.callback_query(F.data == "admin_channel_post_go")
async def cb_admin_channel_post_go(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    pending = ADMIN_CHANNEL_POST_PREVIEW.pop(callback.from_user.id, None)
    if not pending:
        await callback.answer("Черновик не найден, начни заново.", show_alert=True)
        return
    try:
        await bot.send_message(
            CHANNEL_ID,
            pending["text"],
            parse_mode="HTML",
            reply_markup=build_channel_post_keyboard(pending["buttons"]),
        )
        await callback.answer("✅ Опубликовано!", show_alert=True)
        await safe_edit_text(
            callback.message,
            f"✅ Пост опубликован в {CHANNEL_ID}.",
            parse_mode="HTML",
            reply_markup=get_admin_back_keyboard()
        )
    except Exception:
        logger.exception("Не удалось опубликовать пост в канал %s", CHANNEL_ID)
        await callback.answer()
        await safe_edit_text(
            callback.message,
            "⚠️ <b>Не удалось опубликовать пост.</b>\n\n"
            f"Скорее всего, бот не администратор канала {CHANNEL_ID} или у него нет права "
            "«Публиковать сообщения». Добавь бота в администраторы канала с этим правом и попробуй снова.",
            parse_mode="HTML",
            reply_markup=get_admin_back_keyboard()
        )

@dp.callback_query(F.data == "admin_channel_post_cancel")
async def cb_admin_channel_post_cancel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    ADMIN_CHANNEL_POST_PREVIEW.pop(callback.from_user.id, None)
    await callback.answer("Отменено")
    await safe_edit_text(callback.message, "❌ Публикация отменена.", parse_mode="HTML", reply_markup=get_admin_back_keyboard())

@dp.message(F.text)
async def handle_admin_pending_action(message: Message):
    admin_id = message.from_user.id
    if not is_admin(admin_id) or admin_id not in ADMIN_PENDING:
        raise SkipHandler
    if message.text.startswith("/"):
        raise SkipHandler

    pending = ADMIN_PENDING[admin_id]
    action = pending["action"]

    if action in (
        "grant", "revoke", "grant_anatomy_demo", "revoke_anatomy_demo",
        "grant_assistant_admin", "revoke_assistant_admin",
        "dm_username", "record_donation_username", "record_subscription_username",
    ):
        raw_input = message.text.strip()
        username, target_id = resolve_user_by_username(raw_input)
        if not target_id:
            identifier = raw_input.lstrip("@")
            if identifier.isdigit():
                await message.answer(
                    f"⚠️ Пользователь с ID <code>{identifier}</code> не найден — он ещё не писал боту.\n"
                    "Попробуй ещё раз или вернись в /admin.",
                    parse_mode="HTML"
                )
            else:
                await message.answer(
                    f"⚠️ Пользователь @{identifier} не найден — он ещё не писал боту, либо сменил username. "
                    "Можно также ввести его числовой ID.\n"
                    "Попробуй ещё раз или вернись в /admin.",
                    parse_mode="HTML"
                )
            return

        label = format_admin_target_label(username, target_id)

        if action == "grant":
            if target_id not in stats["manual_access_granted"]:
                stats["manual_access_granted"].append(target_id)
                save_stats()
            del ADMIN_PENDING[admin_id]
            await message.answer(f"✅ Доступ выдан {label}.", parse_mode="HTML")
            try:
                await bot.send_message(
                    target_id,
                    "🎉 Администратор открыл тебе полный доступ к боту без необходимости приглашать друзей!",
                    parse_mode="HTML"
                )
            except Exception:
                logger.exception("Не удалось уведомить пользователя %s о выдаче доступа", target_id)

        elif action == "revoke":
            if target_id in stats["manual_access_granted"]:
                stats["manual_access_granted"].remove(target_id)
                save_stats()
            del ADMIN_PENDING[admin_id]
            await message.answer(
                f"✅ Ручной доступ для {label} отозван.\n"
                "Если у пользователя уже есть свои рефералы, доступ всё равно останется открытым.",
                parse_mode="HTML"
            )

        elif action == "grant_anatomy_demo":
            if target_id not in stats["manual_anatomy_demo_granted"]:
                stats["manual_anatomy_demo_granted"].append(target_id)
                save_stats()
            del ADMIN_PENDING[admin_id]
            await message.answer(f"✅ Демо-доступ к Анатомии выдан {label}.", parse_mode="HTML")
            try:
                await bot.send_message(
                    target_id,
                    "🦴 Администратор открыл тебе демо-доступ к разделу «Анатомия»!",
                    parse_mode="HTML"
                )
            except Exception:
                logger.exception("Не удалось уведомить пользователя %s о выдаче демо-доступа к анатомии", target_id)

        elif action == "revoke_anatomy_demo":
            if target_id in stats["manual_anatomy_demo_granted"]:
                stats["manual_anatomy_demo_granted"].remove(target_id)
                save_stats()
            del ADMIN_PENDING[admin_id]
            await message.answer(f"✅ Демо-доступ к Анатомии для {label} отозван.", parse_mode="HTML")

        elif action == "grant_assistant_admin":
            if target_id not in stats["assistant_admins"]:
                stats["assistant_admins"].append(target_id)
                save_stats()
            del ADMIN_PENDING[admin_id]
            await message.answer(f"✅ {label} назначен(а) помощником администратора.", parse_mode="HTML")
            try:
                await bot.send_message(
                    target_id,
                    "🧑‍💼 Тебя назначили помощником администратора!\n\n"
                    "Открой /admin — там доступна статистика бота и возможность написать "
                    "пользователю (сообщение уйдёт только после подтверждения главным админом). "
                    "Также у тебя теперь есть доступ ко всем разделам бота.",
                    parse_mode="HTML"
                )
            except Exception:
                logger.exception("Не удалось уведомить пользователя %s о назначении помощником", target_id)

        elif action == "revoke_assistant_admin":
            if target_id in stats["assistant_admins"]:
                stats["assistant_admins"].remove(target_id)
                save_stats()
            del ADMIN_PENDING[admin_id]
            await message.answer(f"✅ {label} больше не помощник администратора.", parse_mode="HTML")

        elif action == "dm_username":
            ADMIN_PENDING[admin_id] = {"action": "dm_message", "target_id": target_id, "target_label": label}
            await message.answer(f"✅ Нашёл {label}. Теперь отправь текст сообщения для него.", parse_mode="HTML")

        elif action == "record_donation_username":
            ADMIN_PENDING[admin_id] = {"action": "record_donation_amount", "target_id": target_id, "target_label": label}
            await message.answer(f"✅ Нашёл {label}. Теперь пришли сумму в рублях (целое число).", parse_mode="HTML")

        elif action == "record_subscription_username":
            ADMIN_PENDING[admin_id] = {"action": "record_subscription_tier", "target_id": target_id, "target_label": label}
            tier_lines = "\n".join(
                f"{t} — {cfg['title']} ({cfg['price_rub']}₽)" for t, cfg in ACTIVE_SUBSCRIPTION_TIERS.items()
            )
            await message.answer(
                f"✅ Нашёл {label}. Выбери тариф кнопкой ниже или пришли номер:\n\n{tier_lines}",
                parse_mode="HTML",
                reply_markup=get_admin_tier_reply_keyboard()
            )
        return

    if action == "record_donation_amount":
        target_id = pending["target_id"]
        target_label = pending["target_label"]
        raw = message.text.strip().replace(" ", "")
        if not raw.isdigit() or int(raw) <= 0:
            await message.answer("⚠️ Введи, пожалуйста, положительное целое число рублей.")
            return
        amount = int(raw)
        del ADMIN_PENDING[admin_id]
        uid_str = str(target_id)
        stats["donor_rubles"][uid_str] = stats["donor_rubles"].get(uid_str, 0) + amount
        save_stats()
        await message.answer(f"✅ Записано пожертвование {amount}₽ от {target_label}.", parse_mode="HTML")
        return

    if action == "record_subscription_tier":
        target_id = pending["target_id"]
        target_label = pending["target_label"]
        raw = message.text.strip()
        if raw in ("❌ Отмена", "Отмена"):
            del ADMIN_PENDING[admin_id]
            await message.answer("Отменено.", reply_markup=ReplyKeyboardRemove())
            return
        tier_match = re.match(r"\d+", raw)
        tier_id = int(tier_match.group()) if tier_match else None
        if tier_id not in ACTIVE_SUBSCRIPTION_TIERS:
            tier_lines = "\n".join(
                f"{t} — {cfg['title']}" for t, cfg in ACTIVE_SUBSCRIPTION_TIERS.items()
            )
            await message.answer(f"⚠️ Введи номер тарифа из списка:\n\n{tier_lines}", reply_markup=get_admin_tier_reply_keyboard())
            return
        cfg = ACTIVE_SUBSCRIPTION_TIERS[tier_id]
        if cfg.get("subject_choice_required"):
            ADMIN_PENDING[admin_id] = {
                "action": "record_subscription_subject",
                "target_id": target_id, "target_label": target_label, "tier_id": tier_id,
            }
            await message.answer(
                f"✅ Тариф «{cfg['title']}». Какой предмет выбрать?",
                reply_markup=get_admin_subject_reply_keyboard()
            )
            return
        del ADMIN_PENDING[admin_id]
        await message.answer(
            f"✅ Подписка «{cfg['title']}» выдана {target_label}.",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove()
        )
        await grant_subscription_and_notify_buyer(target_id, tier_id, "rubles_manual", cfg["price_rub"])
        return

    if action == "record_subscription_subject":
        target_id = pending["target_id"]
        target_label = pending["target_label"]
        tier_id = pending["tier_id"]
        raw = message.text.strip()
        if raw in ("❌ Отмена", "Отмена"):
            del ADMIN_PENDING[admin_id]
            await message.answer("Отменено.", reply_markup=ReplyKeyboardRemove())
            return
        subject = ADMIN_SUBJECT_LABELS_RU.get(raw)
        if not subject:
            await message.answer(
                "⚠️ Выбери предмет кнопкой ниже.",
                reply_markup=get_admin_subject_reply_keyboard()
            )
            return
        cfg = SUBSCRIPTION_TIERS[tier_id]
        del ADMIN_PENDING[admin_id]
        await message.answer(
            f"✅ Подписка «{cfg['title']}» ({SUBJECT_TITLES[subject]}) выдана {target_label}.",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove()
        )
        await grant_subscription_and_notify_buyer(target_id, tier_id, "rubles_manual", cfg["price_rub"], subject)
        return

    if action == "dm_message":
        target_id = pending["target_id"]
        target_label = pending["target_label"]
        del ADMIN_PENDING[admin_id]
        try:
            await bot.send_message(
                target_id,
                f"✉️ <b>Личное сообщение от администрации</b>\n{DIVIDER}\n\n{message.html_text}",
                parse_mode="HTML"
            )
            await message.answer(f"✅ Сообщение отправлено {target_label}.", parse_mode="HTML")
        except Exception:
            logger.exception("Не удалось отправить личное сообщение пользователю %s", target_id)
            await message.answer(f"⚠️ Не удалось отправить сообщение {target_label} — возможно, он заблокировал бота.", parse_mode="HTML")
        return

    if action == "channel_post_text":
        ADMIN_PENDING[admin_id] = {"action": "channel_post_buttons", "text": message.html_text}
        await message.answer(
            "🔘 <b>Кнопки под постом</b>\n\n"
            "Пришли по одной кнопке на строке в формате:\n"
            "<code>Текст кнопки | https://ссылка</code>\n\n"
            "Можно несколько строк — будет несколько кнопок друг под другом.\n"
            "Если кнопки не нужны — пришли «-».",
            parse_mode="HTML"
        )
        return

    if action == "channel_post_buttons":
        raw = message.text or ""
        if raw.strip() in ("-", "нет", "пропустить", "skip"):
            buttons = []
        else:
            buttons = parse_channel_post_buttons(raw)
            if buttons is None:
                await message.answer(
                    "⚠️ Не понял формат. Каждая строка: <code>Текст кнопки | https://ссылка</code>. "
                    "Либо пришли «-», если кнопки не нужны.",
                    parse_mode="HTML"
                )
                return
        post_text = pending["text"]
        del ADMIN_PENDING[admin_id]
        ADMIN_CHANNEL_POST_PREVIEW[admin_id] = {"text": post_text, "buttons": buttons}
        builder = build_channel_post_builder(buttons)
        builder.row(InlineKeyboardButton(text="✅ Опубликовать в канал", callback_data="admin_channel_post_go"))
        builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_channel_post_cancel"))
        await message.answer(
            f"👀 <b>Предпросмотр поста для {CHANNEL_ID}:</b>\n{DIVIDER}\n\n{post_text}",
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )
        return

# ==================== ПОМОЩНИК АДМИНИСТРАТОРА ====================
# Отдельная, сильно урезанная версия админ-панели для user_id из stats["assistant_admins"]
# (назначаются/снимаются только полным админом — см. admin_grant_assistant_prompt/
# admin_revoke_assistant_prompt выше). Помощник НЕ получает доступ к обычной админ-панели
# (get_admin_menu/cb_admin_panel/handle_admin_pending_action остаются is_admin-only) — только
# к своему собственному меню из двух пунктов: урезанная статистика и сообщение пользователю,
# которое не уходит напрямую, а ставится на подтверждение всем ADMIN_IDS (одно-тап confirm/
# reject, тот же паттерн гонки через pop(), что и у admin_confirm_sub/rollcall_confirm).
# Доступ ко ВСЕМ разделам контента у помощника уже есть через is_admin_or_assistant() —
# это отдельный, самостоятельный механизм, определённый в самом начале файла.
ASSISTANT_PENDING: dict = {}  # assistant_id -> {"action": ..., ...}
ASSISTANT_DM_REQUESTS: dict = {}  # request_id (str) -> {assistant_id, assistant_label, target_id, target_label, text_html}
_assistant_dm_request_seq = 0

def _next_assistant_dm_request_id() -> str:
    global _assistant_dm_request_seq
    _assistant_dm_request_seq += 1
    return str(_assistant_dm_request_seq)

def get_assistant_admin_menu_text() -> str:
    return (
        f"🧑‍💼 <b>Панель помощника</b>\n{DIVIDER}\n\n"
        "Тебе доступна статистика бота и возможность написать пользователю — сообщение "
        "уйдёт только после подтверждения главным админом.\n\nВыбери действие:"
    )

def get_assistant_admin_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="assistant_stats")
    builder.button(text="✉️ Написать пользователю", callback_data="assistant_dm_prompt")
    builder.adjust(1)
    return builder.as_markup()

def get_assistant_back_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="assistant_panel"))
    return builder.as_markup()

def get_assistant_stats_text() -> str:
    """Та же арифметика, что и в cb_admin_stats, но выводится ровно урезанное подмножество
    строк — без разделов «Подписки»/«Платежи» и без остальной админ-панели."""
    total_referrals = sum(len(v) for v in stats["referrals"].values())
    exhausted_free_uses = len(get_exhausted_users())
    below_threshold_count = sum(
        1 for uid in stats["total_users"] if get_referral_count(uid) < REFERRAL_FULL_ACCESS_THRESHOLD
    )
    return (
        f"📊 <b>Статистика бота</b>\n{DIVIDER}\n\n"
        f"👥 Уникальных пользователей: <b>{len(stats['total_users'])}</b>\n"
        f"▶️ Запусков бота: <b>{stats['start_count']}</b>\n"
        f"❓ Вопросов просмотрено: <b>{sum(stats['question_opened'].values())}</b>\n"
        f"🎲 Случайных билетов открыто: <b>{stats['random_ticket_used']}</b>\n"
        f"🎲 Случайных вопросов открыто: <b>{stats['random_question_used']}</b>\n"
        f"📢 Рассылок отправлено: <b>{stats.get('broadcast_count', 0)}</b>\n"
        f"🔗 Всего рефералов: <b>{total_referrals}</b>\n"
        f"📉 Меньше {REFERRAL_FULL_ACCESS_THRESHOLD} рефералов: <b>{below_threshold_count}</b>\n"
        f"🔓 Ручных доступов выдано: <b>{len(stats['manual_access_granted'])}</b>\n"
        f"🦴 Демо-доступов к Анатомии выдано: <b>{len(stats['manual_anatomy_demo_granted'])}</b>\n"
        f"🚫 Исчерпали бесплатные заходы без рефералов: <b>{exhausted_free_uses}</b>\n"
        f"🪪 Известно username: <b>{len(stats['usernames'])}</b>"
    )

@dp.callback_query(F.data == "assistant_panel")
async def cb_assistant_panel(callback: CallbackQuery):
    if not is_assistant_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    ASSISTANT_PENDING.pop(callback.from_user.id, None)
    await safe_edit_text(
        callback.message,
        get_assistant_admin_menu_text(),
        parse_mode="HTML",
        reply_markup=get_assistant_admin_menu_keyboard()
    )

@dp.callback_query(F.data == "assistant_stats")
async def cb_assistant_stats(callback: CallbackQuery):
    if not is_assistant_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    await safe_edit_text(
        callback.message,
        get_assistant_stats_text(),
        parse_mode="HTML",
        reply_markup=get_assistant_back_keyboard()
    )

@dp.callback_query(F.data == "assistant_dm_prompt")
async def cb_assistant_dm_prompt(callback: CallbackQuery):
    if not is_assistant_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    ASSISTANT_PENDING[callback.from_user.id] = {"action": "dm_username"}
    await safe_edit_text(
        callback.message,
        "✉️ <b>Личное сообщение</b>\n\nОтправь username пользователя (с @ или без) или его "
        "числовой ID. Сообщение будет отправлено только после подтверждения главным админом.",
        parse_mode="HTML",
        reply_markup=get_assistant_back_keyboard()
    )

async def notify_admins_of_assistant_dm_request(req_id: str) -> None:
    req = ASSISTANT_DM_REQUESTS[req_id]
    text = (
        f"🧑‍💼 <b>Помощник просит согласовать сообщение</b>\n{DIVIDER}\n\n"
        f"От: {req['assistant_label']}\n"
        f"Кому: {req['target_label']}\n\n"
        f"Текст:\n{req['text_html']}"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить", callback_data=f"assistant_dm_approve:{req_id}")
    builder.button(text="❌ Отклонить", callback_data=f"assistant_dm_reject:{req_id}")
    builder.adjust(1)
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=builder.as_markup())
        except Exception:
            logger.exception("Не удалось уведомить админа %s о запросе помощника на сообщение", admin_id)

@dp.message(F.text)
async def handle_assistant_pending_action(message: Message):
    assistant_id = message.from_user.id
    if not is_assistant_admin(assistant_id) or assistant_id not in ASSISTANT_PENDING:
        raise SkipHandler
    if message.text.startswith("/"):
        raise SkipHandler

    pending = ASSISTANT_PENDING[assistant_id]
    action = pending["action"]

    if action == "dm_username":
        raw_input = message.text.strip()
        username, target_id = resolve_user_by_username(raw_input)
        if not target_id:
            identifier = raw_input.lstrip("@")
            if identifier.isdigit():
                await message.answer(f"⚠️ Пользователь с ID <code>{identifier}</code> не найден — он ещё не писал боту.", parse_mode="HTML")
            else:
                await message.answer(f"⚠️ Пользователь @{identifier} не найден — он ещё не писал боту, либо сменил username.", parse_mode="HTML")
            return
        label = format_admin_target_label(username, target_id)
        ASSISTANT_PENDING[assistant_id] = {"action": "dm_message", "target_id": target_id, "target_label": label}
        await message.answer(f"✅ Нашёл {label}. Теперь отправь текст сообщения для него.", parse_mode="HTML")
        return

    if action == "dm_message":
        target_id = pending["target_id"]
        target_label = pending["target_label"]
        del ASSISTANT_PENDING[assistant_id]
        assistant_label = format_admin_target_label(
            stats["user_username"].get(str(assistant_id)), assistant_id
        )
        req_id = _next_assistant_dm_request_id()
        ASSISTANT_DM_REQUESTS[req_id] = {
            "assistant_id": assistant_id,
            "assistant_label": assistant_label,
            "target_id": target_id,
            "target_label": target_label,
            "text_html": message.html_text,
        }
        await message.answer(
            f"✅ Запрос отправлен главному админу на согласование — сообщение для {target_label} "
            "уйдёт после подтверждения.",
            parse_mode="HTML"
        )
        await notify_admins_of_assistant_dm_request(req_id)
        return

@dp.callback_query(F.data.startswith("assistant_dm_approve:"))
async def cb_assistant_dm_approve(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    req_id = callback.data.split(":", 1)[1]
    req = ASSISTANT_DM_REQUESTS.pop(req_id, None)
    if req is None:
        await callback.answer("Заявка уже обработана (скорее всего, другим админом)", show_alert=True)
        return
    await callback.answer("Подтверждено ✅", show_alert=True)
    try:
        await bot.send_message(
            req["target_id"],
            f"✉️ <b>Личное сообщение от администрации</b>\n{DIVIDER}\n\n{req['text_html']}",
            parse_mode="HTML"
        )
        await safe_edit_text(
            callback.message,
            f"✅ Отправлено {req['target_label']} (от помощника {req['assistant_label']}).",
            parse_mode="HTML"
        )
    except Exception:
        logger.exception("Не удалось отправить согласованное сообщение помощника пользователю %s", req["target_id"])
        await safe_edit_text(
            callback.message,
            f"⚠️ Не удалось отправить сообщение {req['target_label']} — возможно, он заблокировал бота.",
            parse_mode="HTML"
        )
    try:
        await bot.send_message(
            req["assistant_id"],
            f"✅ Твоё сообщение для {req['target_label']} одобрено и отправлено.",
            parse_mode="HTML"
        )
    except Exception:
        logger.exception("Не удалось уведомить помощника %s об одобрении сообщения", req["assistant_id"])

@dp.callback_query(F.data.startswith("assistant_dm_reject:"))
async def cb_assistant_dm_reject(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    req_id = callback.data.split(":", 1)[1]
    req = ASSISTANT_DM_REQUESTS.pop(req_id, None)
    if req is None:
        await callback.answer("Заявка уже обработана (скорее всего, другим админом)", show_alert=True)
        return
    await callback.answer("Заявка отклонена", show_alert=True)
    await safe_edit_text(
        callback.message,
        f"❌ Отклонено — сообщение для {req['target_label']} от помощника {req['assistant_label']} не отправлено.",
        parse_mode="HTML"
    )
    try:
        await bot.send_message(
            req["assistant_id"],
            f"❌ Твой запрос на сообщение для {req['target_label']} отклонён администратором.",
            parse_mode="HTML"
        )
    except Exception:
        logger.exception("Не удалось уведомить помощника %s об отклонении сообщения", req["assistant_id"])

# ==================== МЕНЮ ====================
@dp.callback_query(F.data == "menu_biology")
async def cb_menu_biology(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        f"🧬 <b>Биология</b>\n{DIVIDER}\n\nВыбери формат подготовки:",
        parse_mode="HTML",
        reply_markup=get_biology_menu()
    )

def get_biology_tickets_locked_text() -> str:
    tier_lines = "\n".join(
        f"«{cfg['emoji']} {cfg['title']}» ({cfg['price_rub']}₽ / {cfg['price_stars']}⭐)"
        for cfg in ACTIVE_SUBSCRIPTION_TIERS.values() if cfg.get("biology_download")
    )
    return (
        f"📄 <b>Билеты по биологии — файл с ответами</b>\n{DIVIDER}\n\n"
        "Скачивание готового файла со всеми вопросами и ответами доступно по подписке:\n\n"
        f"{tier_lines}\n\n"
        "Само прохождение билетов и вопросов в боте остаётся доступным как обычно — "
        "подписка нужна только для скачивания файла."
    )

def get_biology_tickets_locked_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="💎 Оформить подписку", callback_data="subscription_menu")
    builder.button(text="🔙 Назад к Биологии", callback_data="menu_biology")
    builder.adjust(1)
    return builder.as_markup()

@dp.callback_query(F.data == "download_biology_tickets")
async def cb_download_biology_tickets(callback: CallbackQuery):
    if not biology_tickets_download_ok(callback.from_user.id):
        await callback.answer()
        await safe_edit_text(
            callback.message,
            get_biology_tickets_locked_text(),
            parse_mode="HTML",
            reply_markup=get_biology_tickets_locked_keyboard()
        )
        return
    await callback.answer()
    await callback.message.answer_document(
        build_biology_tickets_file(),
        caption=f"📄 Все билеты по биологии — вопросы и ответы.\n\n@{BOT_USERNAME}"
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
    await safe_edit_text(
        callback.message,
        f"📘 <b>Билеты — Биология</b>\n{DIVIDER}\n\nВыбери билет:",
        parse_mode="HTML",
        reply_markup=get_ticket_keyboard()
    )

@dp.callback_query(F.data == "menu_questions")
async def cb_menu_questions(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        f"📝 <b>Вопросы — Биология</b>\n{DIVIDER}\n\nВыбери страницу:",
        parse_mode="HTML",
        reply_markup=get_questions_main_menu()
    )

@dp.callback_query(F.data == "back_to_main")
async def cb_back_to_main(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        "🏠 <b>Главное меню</b>\n\nВыбери предмет для подготовки:",
        parse_mode="HTML",
        reply_markup=get_main_menu(callback.from_user.id)
    )

@dp.callback_query(F.data == "referral_info")
async def cb_referral_info(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    keyboard = get_referral_full_access_keyboard(user_id) if has_free_access(user_id) else get_referral_back_keyboard()
    await safe_edit_text(
        callback.message,
        get_referral_status_text(user_id),
        parse_mode="HTML",
        reply_markup=keyboard
    )

@dp.callback_query(F.data == "referral_leaderboard")
async def cb_referral_leaderboard(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        get_referral_leaderboard_text(callback.from_user.id),
        parse_mode="HTML",
        reply_markup=get_referral_leaderboard_keyboard()
    )

@dp.callback_query(F.data == "referral_battle")
async def cb_referral_battle(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        get_battle_text(callback.from_user.id),
        parse_mode="HTML",
        reply_markup=get_battle_keyboard(),
        disable_web_page_preview=True,
    )

@dp.callback_query(F.data == "support_menu")
async def cb_support_menu(callback: CallbackQuery):
    await callback.answer()
    DONATION_PENDING.pop(callback.from_user.id, None)
    await safe_edit_text(callback.message, get_support_text(), parse_mode="HTML", reply_markup=get_support_keyboard(callback.from_user.id))

@dp.callback_query(F.data == "toggle_donor_visibility")
async def cb_toggle_donor_visibility(callback: CallbackQuery):
    uid_str = str(callback.from_user.id)
    hidden = not stats["donor_hide_name"].get(uid_str, False)
    stats["donor_hide_name"][uid_str] = hidden
    save_stats()
    await callback.answer("Теперь ты анонимен в рейтинге" if hidden else "Теперь твой ник виден в рейтинге")
    await safe_edit_text(callback.message, get_support_text(), parse_mode="HTML", reply_markup=get_support_keyboard(callback.from_user.id))

@dp.callback_query(F.data == "donors_leaderboard")
async def cb_donors_leaderboard(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        get_donors_leaderboard_text(),
        parse_mode="HTML",
        reply_markup=get_donors_leaderboard_keyboard()
    )

@dp.callback_query(F.data == "donate_stars_menu")
async def cb_donate_stars_menu(callback: CallbackQuery):
    await callback.answer()
    DONATION_PENDING.pop(callback.from_user.id, None)
    await safe_edit_text(callback.message, get_stars_menu_text(), parse_mode="HTML", reply_markup=get_stars_menu_keyboard())

@dp.callback_query(F.data.startswith("donate_stars_amount:"))
async def cb_donate_stars_amount(callback: CallbackQuery):
    await callback.answer()
    amount = int(callback.data.split(":")[1])
    await safe_edit_text(
        callback.message,
        get_visibility_choice_text(amount, " ⭐"),
        parse_mode="HTML",
        reply_markup=get_stars_visibility_keyboard(amount)
    )

@dp.callback_query(F.data.startswith("donate_stars_confirm:"))
async def cb_donate_stars_confirm(callback: CallbackQuery):
    await callback.answer()
    _, amount_s, visibility = callback.data.split(":")
    stats["donor_hide_name"][str(callback.from_user.id)] = (visibility == "anon")
    save_stats()
    await send_stars_invoice(callback.from_user.id, int(amount_s))

@dp.callback_query(F.data == "donate_stars_custom")
async def cb_donate_stars_custom(callback: CallbackQuery):
    await callback.answer()
    DONATION_PENDING[callback.from_user.id] = {"type": "stars"}
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="donate_stars_menu"))
    await safe_edit_text(
        callback.message,
        f"✏️ <b>Своё количество звёзд</b>\n{DIVIDER}\n\nВведи число от {STARS_MIN} до {STARS_MAX}:",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "donate_rubles_menu")
async def cb_donate_rubles_menu(callback: CallbackQuery):
    await callback.answer()
    DONATION_PENDING.pop(callback.from_user.id, None)
    await safe_edit_text(callback.message, get_rubles_menu_text(), parse_mode="HTML", reply_markup=get_rubles_menu_keyboard())

@dp.callback_query(F.data.startswith("donate_rubles_amount:"))
async def cb_donate_rubles_amount(callback: CallbackQuery):
    await callback.answer()
    amount = int(callback.data.split(":")[1])
    await safe_edit_text(
        callback.message,
        get_visibility_choice_text(amount, "₽"),
        parse_mode="HTML",
        reply_markup=get_rubles_visibility_keyboard(amount)
    )

@dp.callback_query(F.data.startswith("donate_rubles_confirm:"))
async def cb_donate_rubles_confirm(callback: CallbackQuery):
    await callback.answer()
    _, amount_s, visibility = callback.data.split(":")
    amount = int(amount_s)
    stats["donor_hide_name"][str(callback.from_user.id)] = (visibility == "anon")
    save_stats()
    await safe_edit_text(
        callback.message,
        get_rubles_donation_message_text(amount),
        parse_mode="HTML",
        reply_markup=get_rubles_donation_keyboard(amount),
        disable_web_page_preview=True,
    )

@dp.callback_query(F.data == "donate_rubles_custom")
async def cb_donate_rubles_custom(callback: CallbackQuery):
    await callback.answer()
    DONATION_PENDING[callback.from_user.id] = {"type": "rubles"}
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="donate_rubles_menu"))
    await safe_edit_text(
        callback.message,
        f"✏️ <b>Своя сумма в рублях</b>\n{DIVIDER}\n\nВведи сумму числом (от {RUBLES_MIN} до {RUBLES_MAX}):",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

# ==================== ПЛАТНАЯ ПОДПИСКА (UI и оплата) ====================
def format_subscription_expiry(expires) -> str:
    if expires is None:
        return "навсегда"
    return f"до {date.fromtimestamp(expires).strftime('%d.%m.%Y')}"

async def grant_subscription_and_notify_buyer(
    target_id: int, tier_id: int, method: str, price: int, subject: str | None = None
) -> None:
    """Общая точка для всех трёх путей выдачи подписки (Stars, ручное подтверждение рублей
    админом, быстрое подтверждение по кнопке) — выдаёт тариф и шлёт покупателю одно и то же
    сообщение об активации + апсейл на следующий тариф. method различает источник для
    статистики платежей: "stars"/"rubles" — реальная подтверждённая оплата, "rubles_manual" —
    ручная выдача админом (например, бесплатно другу) и в выручку не считается."""
    grant_subscription(target_id, tier_id, method, price, subject)
    cfg = SUBSCRIPTION_TIERS[tier_id]
    sub = get_subscription(target_id)
    scope_label = get_subscription_scope_label(sub)
    text = (
        f"🎉 <b>Подписка «{cfg['title']}» активирована!</b>\n\n"
        f"Доступ {scope_label} открыт — {format_subscription_expiry(sub['expires'])}.\n"
        "Правило про рефералов для тебя больше не действует. Спасибо за поддержку! 🙏😇"
    )
    text += get_tier_upsell_text(tier_id)
    keyboard = get_tier_upsell_keyboard(tier_id)
    try:
        await bot.send_message(target_id, text, parse_mode="HTML", reply_markup=keyboard)
    except Exception:
        logger.exception("Не удалось уведомить пользователя %s о выдаче подписки", target_id)

def get_admin_payment_confirm_text(cfg: dict, user, subject: str | None = None, price: int | None = None) -> str:
    price = price if price is not None else cfg["price_rub"]
    subject_line = f"\nПредмет: {SUBJECT_TITLES[subject]}" if subject else ""
    discount_line = " (со скидкой 10%)" if price != cfg["price_rub"] else ""
    return (
        f"💰 <b>Запрос на подтверждение оплаты</b>\n{DIVIDER}\n\n"
        f"Тариф: «{cfg['title']}» — {price}₽{discount_line}{subject_line}\n"
        f"От: {html.escape(user.full_name)} "
        f"({f'@{user.username} ' if user.username else ''}ID <code>{user.id}</code>)\n\n"
        "Нажми ниже, когда увидишь перевод в чате с @vmeda_helper — подписка выдастся сразу."
    )

def get_admin_payment_confirm_keyboard(tier_id: int, target_id: int, subject: str | None = None, price: int | None = None):
    cfg = SUBSCRIPTION_TIERS[tier_id]
    price = price if price is not None else cfg["price_rub"]
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Подтвердить оплату",
        callback_data=f"admin_confirm_sub:{tier_id}:{target_id}:{subject or '-'}:{price}"
    )
    builder.button(
        text="❌ Отклонить",
        callback_data=f"admin_reject_sub:{tier_id}:{target_id}:{subject or '-'}"
    )
    builder.adjust(1)
    return builder.as_markup()

async def notify_admins_of_payment_request(
    tier_id: int, target_id: int, user, subject: str | None = None, price: int | None = None
) -> None:
    cfg = SUBSCRIPTION_TIERS[tier_id]
    text = get_admin_payment_confirm_text(cfg, user, subject, price)
    keyboard = get_admin_payment_confirm_keyboard(tier_id, target_id, subject, price)
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            logger.exception("Не удалось уведомить админа %s о запросе оплаты", admin_id)

def get_my_subscription_status_block(user_id: int) -> str:
    sub = get_subscription(user_id)
    if not sub or not has_active_subscription(user_id):
        return ""
    cfg = SUBSCRIPTION_TIERS.get(sub["tier"], {})
    scope_label = get_subscription_scope_label(sub)
    return (
        f"✅ У тебя активна подписка «{cfg.get('title', '')}»\n"
        f"Доступ {scope_label} — {format_subscription_expiry(sub['expires'])}.\n\n"
    )

def _next_upsell_tier_id(tier_id: int) -> int | None:
    cfg = SUBSCRIPTION_TIERS[tier_id]
    candidates = sorted(
        (t for t, c in ACTIVE_SUBSCRIPTION_TIERS.items() if c["price_rub"] > cfg["price_rub"]),
        key=lambda t: ACTIVE_SUBSCRIPTION_TIERS[t]["price_rub"]
    )
    return candidates[0] if candidates else None

def get_tier_upsell_text(tier_id: int) -> str:
    cfg = SUBSCRIPTION_TIERS[tier_id]
    nxt_id = _next_upsell_tier_id(tier_id)
    if nxt_id is None:
        return ""
    nxt = SUBSCRIPTION_TIERS[nxt_id]
    diff_rub = nxt["price_rub"] - cfg["price_rub"]
    diff_stars = nxt["price_stars"] - cfg["price_stars"]
    return (
        f"\n\n💡 <b>Выгоднее:</b> тариф «{nxt['emoji']} {nxt['title']}» — всего на "
        f"<b>{diff_rub}₽ / {diff_stars}⭐</b> дороже (<b>{nxt['price_rub']}₽ / {nxt['price_stars']}⭐</b> "
        f"вместо {cfg['price_rub']}₽), а даёт: {nxt['benefits'][0].lower()}."
    )

def get_tier_upsell_keyboard(tier_id: int):
    nxt_id = _next_upsell_tier_id(tier_id)
    if nxt_id is None:
        return None
    nxt = SUBSCRIPTION_TIERS[nxt_id]
    builder = InlineKeyboardBuilder()
    builder.button(text=f"⬆️ Перейти на «{nxt['short']}» за {nxt['price_rub']}₽", callback_data=f"sub_tier:{nxt_id}")
    return builder.as_markup()

def get_subscription_menu_text(user_id: int) -> str:
    lines = [f"💎 <b>Подписка без рефералов</b>\n{DIVIDER}\n"]
    lines.append(
        "⚠️ Разработка и содержание бота требуют серьёзных затрат — поэтому в дополнение "
        "к бесплатному доступу за рефералов мы вынуждены были добавить платные подписки. "
        "Так бот сможет и дальше жить, обновляться и получать новые разделы.\n"
    )
    lines.append(
        "🔬 Раздел <b>Гистологии</b> уже полностью готов и проработан: все микрофотографии "
        "и протоколы-описания взяты именно с препаратов академии, а содержание сверено "
        "с преподавателями.\n"
    )
    status = get_my_subscription_status_block(user_id)
    if status:
        lines.append(status)
    lines.append(
        "Не хочешь ждать или звать друзей? Открой доступ сразу оплатой — без рефералов "
        "и ограничений. Выбери вариант:\n\n"
        "⏳ Зачёркнутая цена — во сколько подписка будет обходиться с сентября, успей купить сейчас!\n"
    )
    best7, best9 = SUBSCRIPTION_TIERS[7], SUBSCRIPTION_TIERS[9]
    lines.append(
        "🏆 <b>ТОП-2 предложения:</b>\n"
        f"👉 «{best7['emoji']} {best7['title']}» — {best7['price_rub']}₽, "
        f"или «{best9['emoji']} {best9['title']}» — {best9['price_rub']}₽ — закрывают всё сразу! 🔥\n"
    )
    for tier_id, cfg in sorted_active_tiers():
        if cfg.get("badge"):
            lines.append(f"<b>{cfg['badge']}</b>")
        lines.append(f"{cfg['emoji']} <b>{cfg['title']}</b> — {get_tier_price_line(cfg)}")
        if cfg.get("joke"):
            lines.append(f"<i>{cfg['joke']}</i>")
        for b in cfg["benefits"]:
            lines.append(f"• {b}")
        lines.append("")
    lines.append(
        "После оплаты правило про рефералов для тебя больше не действует — доступ "
        "открывается сразу и держится всё оплаченное время."
    )
    return "\n".join(lines)

def get_subscription_menu_keyboard():
    builder = InlineKeyboardBuilder()
    for tier_id, cfg in sorted_active_tiers():
        badge = f"{cfg['badge']} — " if cfg.get("badge") else ""
        builder.button(
            text=f"{badge}{cfg['emoji']} {cfg['short']} — {cfg['price_rub']}₽/{cfg['price_stars']}⭐",
            callback_data=f"sub_tier:{tier_id}"
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()

def get_sub_tier_text(tier_id: int) -> str:
    cfg = SUBSCRIPTION_TIERS[tier_id]
    lines = [f"{cfg['emoji']} <b>{cfg['title']}</b>"]
    if cfg.get("badge"):
        lines.append(f"<b>{cfg['badge']}</b>")
    lines.append(f"{DIVIDER}\n")
    if cfg.get("joke"):
        lines.append(f"<i>{cfg['joke']}</i>\n")
    for b in cfg["benefits"]:
        lines.append(f"• {b}")
    lines.append(f"\nЦена: {get_tier_price_line(cfg)}")
    lines.append("⏳ Зачёркнутая цена — во сколько подписка будет обходиться с сентября, успей купить сейчас!")
    lines.append(get_tier_upsell_text(tier_id))
    if cfg.get("subject_choice_required"):
        lines.append("\nСначала выбери предмет, потом способ оплаты:")
    else:
        lines.append("\nВыбери способ оплаты:")
    return "\n".join(lines)

def get_sub_tier_keyboard(tier_id: int):
    cfg = SUBSCRIPTION_TIERS[tier_id]
    builder = InlineKeyboardBuilder()
    if cfg.get("subject_choice_required"):
        builder.button(text="🧬 Биология", callback_data=f"sub_subject:{tier_id}:biology")
        builder.button(text="⚛️ Физика", callback_data=f"sub_subject:{tier_id}:physics")
        builder.button(text="🧪 Химия", callback_data=f"sub_subject:{tier_id}:chemistry")
        builder.adjust(1)
    else:
        builder.button(text=f"⭐ Оплатить {cfg['price_stars']} звёзд", callback_data=f"buy_sub_stars:{tier_id}")
        builder.button(text=f"💵 Оплатить {cfg['price_rub']}₽", callback_data=f"buy_sub_rubles:{tier_id}")
        builder.adjust(1)
    nxt_kb = get_tier_upsell_keyboard(tier_id)
    if nxt_kb:
        builder.row(nxt_kb.inline_keyboard[0][0])
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="subscription_menu"))
    return builder.as_markup()

def get_sub_subject_keyboard(tier_id: int, subject: str):
    cfg = SUBSCRIPTION_TIERS[tier_id]
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"⭐ Оплатить {cfg['price_stars']} звёзд",
        callback_data=f"buy_sub_stars_subj:{tier_id}:{subject}"
    )
    builder.button(
        text=f"💵 Оплатить {cfg['price_rub']}₽",
        callback_data=f"buy_sub_rubles_subj:{tier_id}:{subject}"
    )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"sub_tier:{tier_id}"))
    return builder.as_markup()

def get_sub_rubles_message_text(tier_id: int, subject: str | None = None, price: int | None = None) -> str:
    cfg = SUBSCRIPTION_TIERS[tier_id]
    price = price if price is not None else cfg["price_rub"]
    subject_line = f" ({SUBJECT_TITLES[subject]})" if subject else ""
    return (
        f"💵 <b>Оплата подписки «{cfg['title']}»{subject_line} — {price}₽</b>\n{DIVIDER}\n\n"
        f'Нажми на кнопку ниже — откроется чат с <a href="{HELPER_ACCOUNT_URL}">@vmeda_helper</a>, '
        "сообщение с тарифом уже будет готово. Отправь его и переведи по присланным реквизитам — "
        "как только оплата подтвердится, подписка будет включена вручную.\n\n"
        "Спасибо, что поддерживаешь бота! 🙏"
    )

def get_sub_rubles_keyboard(tier_id: int, subject: str | None = None, price: int | None = None):
    cfg = SUBSCRIPTION_TIERS[tier_id]
    price = price if price is not None else cfg["price_rub"]
    subject_line = f" ({SUBJECT_TITLES[subject]})" if subject else ""
    template = (
        f"Привет! Хочу оформить подписку «{cfg['title']}»{subject_line} за {price}₽ в боте "
        "VMEDA_examen_bot. Подскажи, пожалуйста, реквизиты для перевода."
    )
    url = f"{HELPER_ACCOUNT_URL}?text={urllib.parse.quote(template)}"
    back_data = f"sub_subject:{tier_id}:{subject}" if subject else f"sub_tier:{tier_id}"
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💸 Написать @vmeda_helper", url=url))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=back_data))
    return builder.as_markup()

async def send_subscription_stars_invoice(
    chat_id: int, tier_id: int, subject: str | None = None, discount: bool = False
) -> None:
    cfg = SUBSCRIPTION_TIERS[tier_id]
    price_stars = discount_price(cfg["price_stars"]) if discount else cfg["price_stars"]
    subject_line = f" ({SUBJECT_TITLES[subject]})" if subject else ""
    discount_line = " — скидка 10%" if discount else ""
    await bot.send_invoice(
        chat_id=chat_id,
        title=f"Подписка: {cfg['title']}{subject_line}{discount_line}",
        description=f"VMEDA_examen_bot — подписка «{cfg['title']}»{subject_line}{discount_line}. Доступ откроется сразу после оплаты.",
        payload=f"sub_stars_{tier_id}_{subject or '-'}_{chat_id}_{int(time.time())}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=cfg["title"], amount=price_stars)],
    )

def get_discount_offer_text(tier_id: int) -> str:
    cfg = SUBSCRIPTION_TIERS[tier_id]
    lines = [
        f"🔥 <b>Скидка {int(DISCOUNT_RATE * 100)}% — специально для тебя!</b>\n{DIVIDER}\n",
        f"{cfg['emoji']} <b>{cfg['title']}</b>\n",
        f"Цена со скидкой: <b>{discount_price(cfg['price_rub'])}₽</b> <s>{cfg['price_rub']}₽</s> / "
        f"<b>{discount_price(cfg['price_stars'])}⭐</b> <s>{cfg['price_stars']}⭐</s>\n",
    ]
    lines += [f"• {b}" for b in cfg["benefits"]]
    lines.append("\n⏳ Скидка действует ограниченное время — не тяни с оплатой!\n\nВыбери способ оплаты:")
    return "\n".join(lines)

def get_discount_offer_keyboard(tier_id: int):
    cfg = SUBSCRIPTION_TIERS[tier_id]
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"⭐ Оплатить {discount_price(cfg['price_stars'])} звёзд",
        callback_data=f"buy_sub_stars_discount:{tier_id}"
    )
    builder.button(
        text=f"💵 Оплатить {discount_price(cfg['price_rub'])}₽",
        callback_data=f"buy_sub_rubles_discount:{tier_id}"
    )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="subscription_menu"))
    return builder.as_markup()

def get_subscription_teaser_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💎 Открыть доступ без рефералов", callback_data="subscription_menu"))
    builder.row(InlineKeyboardButton(text="🚀 Запустить Medical_vpn_bot", url=MEDICAL_VPN_URL))
    return builder.as_markup()

@dp.callback_query(F.data == "subscription_menu")
async def cb_subscription_menu(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        get_subscription_menu_text(callback.from_user.id),
        parse_mode="HTML",
        reply_markup=get_subscription_menu_keyboard(),
        disable_web_page_preview=True,
    )

@dp.callback_query(F.data.startswith("sub_tier:"))
async def cb_sub_tier(callback: CallbackQuery):
    tier_id = int(callback.data.split(":")[1])
    if tier_id not in SUBSCRIPTION_TIERS:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    await callback.answer()
    await safe_edit_text(
        callback.message,
        get_sub_tier_text(tier_id),
        parse_mode="HTML",
        reply_markup=get_sub_tier_keyboard(tier_id)
    )

@dp.callback_query(F.data.startswith("sub_subject:"))
async def cb_sub_subject(callback: CallbackQuery):
    _, tier_id_raw, subject = callback.data.split(":")
    tier_id = int(tier_id_raw)
    if tier_id not in SUBSCRIPTION_TIERS or subject not in SUBJECT_TITLES:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    await callback.answer()
    cfg = SUBSCRIPTION_TIERS[tier_id]
    text = (
        f"{cfg['emoji']} <b>{cfg['title']}</b> — {SUBJECT_TITLES[subject]}\n{DIVIDER}\n\n"
        f"Цена: {get_tier_price_line(cfg)}\n"
        "⏳ Зачёркнутая цена — во сколько подписка будет обходиться с сентября, успей купить сейчас!\n\n"
        "Выбери способ оплаты:"
    )
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=get_sub_subject_keyboard(tier_id, subject))

@dp.callback_query(F.data.startswith("buy_sub_stars:"))
async def cb_buy_sub_stars(callback: CallbackQuery):
    tier_id = int(callback.data.split(":")[1])
    if tier_id not in SUBSCRIPTION_TIERS:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    await callback.answer()
    await send_subscription_stars_invoice(callback.from_user.id, tier_id)

@dp.callback_query(F.data.startswith("buy_sub_stars_subj:"))
async def cb_buy_sub_stars_subj(callback: CallbackQuery):
    _, tier_id_raw, subject = callback.data.split(":")
    tier_id = int(tier_id_raw)
    if tier_id not in SUBSCRIPTION_TIERS or subject not in SUBJECT_TITLES:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    await callback.answer()
    await send_subscription_stars_invoice(callback.from_user.id, tier_id, subject)

@dp.callback_query(F.data.startswith("buy_sub_rubles:"))
async def cb_buy_sub_rubles(callback: CallbackQuery):
    tier_id = int(callback.data.split(":")[1])
    if tier_id not in SUBSCRIPTION_TIERS:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    await callback.answer()
    await safe_edit_text(
        callback.message,
        get_sub_rubles_message_text(tier_id),
        parse_mode="HTML",
        reply_markup=get_sub_rubles_keyboard(tier_id),
        disable_web_page_preview=True,
    )
    await notify_admins_of_payment_request(tier_id, callback.from_user.id, callback.from_user)

@dp.callback_query(F.data.startswith("buy_sub_rubles_subj:"))
async def cb_buy_sub_rubles_subj(callback: CallbackQuery):
    _, tier_id_raw, subject = callback.data.split(":")
    tier_id = int(tier_id_raw)
    if tier_id not in SUBSCRIPTION_TIERS or subject not in SUBJECT_TITLES:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    await callback.answer()
    await safe_edit_text(
        callback.message,
        get_sub_rubles_message_text(tier_id, subject),
        parse_mode="HTML",
        reply_markup=get_sub_rubles_keyboard(tier_id, subject),
        disable_web_page_preview=True,
    )
    await notify_admins_of_payment_request(tier_id, callback.from_user.id, callback.from_user, subject)

@dp.callback_query(F.data.startswith("sub_discount:"))
async def cb_sub_discount(callback: CallbackQuery):
    tier_id = int(callback.data.split(":")[1])
    cfg = SUBSCRIPTION_TIERS.get(tier_id)
    if not cfg or cfg.get("subject_choice_required"):
        await callback.answer("Тариф не найден", show_alert=True)
        return
    await callback.answer()
    await safe_edit_text(
        callback.message,
        get_discount_offer_text(tier_id),
        parse_mode="HTML",
        reply_markup=get_discount_offer_keyboard(tier_id),
    )

@dp.callback_query(F.data.startswith("buy_sub_stars_discount:"))
async def cb_buy_sub_stars_discount(callback: CallbackQuery):
    tier_id = int(callback.data.split(":")[1])
    if tier_id not in SUBSCRIPTION_TIERS:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    await callback.answer()
    await send_subscription_stars_invoice(callback.from_user.id, tier_id, discount=True)

@dp.callback_query(F.data.startswith("buy_sub_rubles_discount:"))
async def cb_buy_sub_rubles_discount(callback: CallbackQuery):
    tier_id = int(callback.data.split(":")[1])
    if tier_id not in SUBSCRIPTION_TIERS:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    await callback.answer()
    price = discount_price(SUBSCRIPTION_TIERS[tier_id]["price_rub"])
    await safe_edit_text(
        callback.message,
        get_sub_rubles_message_text(tier_id, price=price),
        parse_mode="HTML",
        reply_markup=get_sub_rubles_keyboard(tier_id, price=price),
        disable_web_page_preview=True,
    )
    await notify_admins_of_payment_request(tier_id, callback.from_user.id, callback.from_user, price=price)

@dp.callback_query(F.data.startswith("admin_confirm_sub:"))
async def cb_admin_confirm_sub(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    parts = callback.data.split(":")
    _, tier_id_raw, target_id_raw, subject_raw = parts[:4]
    tier_id = int(tier_id_raw)
    target_id = int(target_id_raw)
    subject = subject_raw if subject_raw != "-" else None
    if tier_id not in SUBSCRIPTION_TIERS:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    price = int(parts[4]) if len(parts) > 4 else SUBSCRIPTION_TIERS[tier_id]["price_rub"]

    existing = get_subscription(target_id)
    already_confirmed = (
        existing and existing.get("tier") == tier_id and existing.get("method") == "rubles"
        and has_active_subscription(target_id)
        and time.time() - existing.get("purchased_at", 0) < 600
    )
    if already_confirmed:
        await callback.answer("Уже подтверждено (скорее всего, другим админом)", show_alert=True)
        await safe_edit_text(
            callback.message,
            f"✅ Уже подтверждено — подписка «{SUBSCRIPTION_TIERS[tier_id]['title']}» "
            f"выдана {format_admin_target_label(None, target_id)}.",
            parse_mode="HTML"
        )
        return

    await callback.answer("Подтверждено ✅", show_alert=True)
    await grant_subscription_and_notify_buyer(target_id, tier_id, "rubles", price, subject)
    await safe_edit_text(
        callback.message,
        f"✅ Подтверждено — подписка «{SUBSCRIPTION_TIERS[tier_id]['title']}» "
        f"выдана {format_admin_target_label(None, target_id)}.",
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("admin_reject_sub:"))
async def cb_admin_reject_sub(callback: CallbackQuery):
    """Позволяет закрыть запрос на подтверждение оплаты, если покупатель так и не перевёл
    деньги (например, проигнорировал) — просто убирает заявку, ничего не выдаёт и не трогает
    статистику."""
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    _, tier_id_raw, target_id_raw, subject_raw = callback.data.split(":")
    tier_id = int(tier_id_raw)
    target_id = int(target_id_raw)
    if tier_id not in SUBSCRIPTION_TIERS:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    await callback.answer("Заявка отклонена", show_alert=True)
    await safe_edit_text(
        callback.message,
        f"❌ Отклонено — заявка на «{SUBSCRIPTION_TIERS[tier_id]['title']}» от "
        f"{format_admin_target_label(None, target_id)} закрыта без выдачи подписки.",
        parse_mode="HTML"
    )

@dp.pre_checkout_query()
async def handle_pre_checkout(pre_checkout_query) -> None:
    await pre_checkout_query.answer(ok=True)

@dp.message(F.successful_payment)
async def handle_successful_payment(message: Message):
    payment = message.successful_payment
    stars = payment.total_amount
    payload = payment.invoice_payload or ""

    if payload.startswith("sub_stars_"):
        parts = payload.split("_")
        tier_id = int(parts[2])
        subject = parts[3] if len(parts) > 3 and parts[3] != "-" else None
        cfg = SUBSCRIPTION_TIERS[tier_id]
        await grant_subscription_and_notify_buyer(message.from_user.id, tier_id, "stars", stars, subject)
        user = message.from_user
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"💎 <b>Новая подписка звёздами!</b>\n\n«{cfg['title']}» ({stars} ⭐) — "
                    f"{html.escape(user.full_name)} (ID <code>{user.id}</code>)",
                    parse_mode="HTML"
                )
            except Exception:
                logger.exception("Не удалось уведомить админа %s о подписке", admin_id)
        return

    stats["donations_stars_total"] += stars
    stats["donations_stars_count"] += 1
    uid_str = str(message.from_user.id)
    stats["donor_stars"][uid_str] = stats["donor_stars"].get(uid_str, 0) + stars
    save_stats()
    await message.answer(
        f"🎉 <b>Спасибо огромное за поддержку — {stars} ⭐!</b>\n\n"
        "Это очень помогает развивать бота дальше 🙏😇",
        parse_mode="HTML"
    )
    user = message.from_user
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"⭐ <b>Новое пожертвование звёздами!</b>\n\n{stars} ⭐ от "
                f"{html.escape(user.full_name)} (ID <code>{user.id}</code>)",
                parse_mode="HTML"
            )
        except Exception:
            logger.exception("Не удалось уведомить админа %s о пожертвовании", admin_id)

@dp.message(F.text)
async def handle_donation_pending_amount(message: Message):
    user_id = message.from_user.id
    if user_id not in DONATION_PENDING:
        raise SkipHandler
    if message.text.startswith("/"):
        raise SkipHandler

    pending = DONATION_PENDING[user_id]
    raw = message.text.strip().replace(" ", "")
    if not raw.isdigit():
        await message.answer("⚠️ Введи, пожалуйста, просто число.")
        return
    amount = int(raw)

    if pending["type"] == "stars":
        if not (STARS_MIN <= amount <= STARS_MAX):
            await message.answer(f"⚠️ Введи число от {STARS_MIN} до {STARS_MAX}.")
            return
        del DONATION_PENDING[user_id]
        await message.answer(
            get_visibility_choice_text(amount, " ⭐"),
            parse_mode="HTML",
            reply_markup=get_stars_visibility_keyboard(amount)
        )
    else:
        if not (RUBLES_MIN <= amount <= RUBLES_MAX):
            await message.answer(f"⚠️ Введи число от {RUBLES_MIN} до {RUBLES_MAX}.")
            return
        del DONATION_PENDING[user_id]
        await message.answer(
            get_visibility_choice_text(amount, "₽"),
            parse_mode="HTML",
            reply_markup=get_rubles_visibility_keyboard(amount)
        )

@dp.callback_query(F.data == "menu_physics")
async def cb_menu_physics(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        f"⚛️ <b>Физика</b>\n{DIVIDER}\n\nВыбери раздел:",
        parse_mode="HTML",
        reply_markup=get_physics_menu()
    )

@dp.callback_query(F.data == "download_physics_full")
async def cb_download_physics_full(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer_document(
        build_physics_full_file(),
        caption=f"📄 Физика: тестовая часть (186 вопросов) + шаблоны решения задач по всем темам.\n\n@{BOT_USERNAME}"
    )

@dp.callback_query(F.data == "download_physics_grade45")
async def cb_download_physics_grade45(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer_document(
        build_physics_grade45_file(),
        caption=f"📄 Физика — «(60 вопросов) на 4/5», все вопросы и ответы.\n\n@{BOT_USERNAME}"
    )

@dp.callback_query(F.data == "download_physics_ticket_tasks")
async def cb_download_physics_ticket_tasks(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer_document(
        build_physics_ticket_tasks_file(),
        caption=f"📄 Ответы на задачи (Часть 2) билетов 66-69.\n\n@{BOT_USERNAME}"
    )

@dp.callback_query(F.data == "download_physics_tasks_cheatsheet")
async def cb_download_physics_tasks_cheatsheet(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer_document(
        build_physics_tasks_cheatsheet_file(),
        caption=f"📄 Шпаргалка по всем типам задач по физике — формулы и обозначения.\n\n@{BOT_USERNAME}"
    )

@dp.callback_query(F.data == "menu_chemistry")
async def cb_menu_chemistry(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        f"🧪 <b>Химия</b>\n{DIVIDER}\n\nВыбери раздел:",
        parse_mode="HTML",
        reply_markup=get_chemistry_menu()
    )

@dp.callback_query(F.data == "download_chemistry_labs")
async def cb_download_chemistry_labs(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer_document(
        build_chemistry_labs_file(),
        caption=f"📄 Все лабораторные работы по химии.\n\n@{BOT_USERNAME}"
    )

@dp.callback_query(F.data == "download_chemistry_tasks")
async def cb_download_chemistry_tasks(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer_document(
        build_chemistry_tasks_file(),
        caption=f"📄 Все задачи по химии.\n\n@{BOT_USERNAME}"
    )

# ==================== ХИМИЯ - ТЕОРИЯ (С НАВИГАЦИЕЙ) ====================
@dp.callback_query(F.data == "chemistry_theory")
async def cb_chemistry_theory(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
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
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=get_theory_navigation(num))

@dp.callback_query(F.data == "chemistry_theory_list")
async def cb_theory_list(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        f"📚 <b>Теория по химии</b>\n{DIVIDER}\n\nВыбери тему:",
        parse_mode="HTML",
        reply_markup=get_chemistry_theory_list()
    )

# ==================== ХИМИЯ - БИЛЕТЫ ====================
@dp.callback_query(F.data == "chemistry_tickets")
async def cb_chemistry_tickets(callback: CallbackQuery):
    await callback.answer()
    if not chemistry_tickets_access_ok(callback.from_user.id):
        await safe_edit_text(
            callback.message,
            get_chemistry_tickets_locked_text(),
            parse_mode="HTML",
            reply_markup=get_chemistry_tickets_locked_keyboard()
        )
        return
    await safe_edit_text(
        callback.message,
        f"🎫 <b>Билеты по химии</b>\n{DIVIDER}\n\nВыбери раздел:",
        parse_mode="HTML",
        reply_markup=get_chemistry_tickets_menu()
    )

@dp.callback_query(F.data == "chem_theory_tickets")
async def cb_chem_theory_tickets(callback: CallbackQuery):
    await callback.answer()
    if not chemistry_tickets_access_ok(callback.from_user.id):
        await safe_edit_text(
            callback.message,
            get_chemistry_tickets_locked_text(),
            parse_mode="HTML",
            reply_markup=get_chemistry_tickets_locked_keyboard()
        )
        return
    await safe_edit_text(
        callback.message,
        f"📖 <b>Билеты теории</b>\n{DIVIDER}\n\nВыбери билет:",
        parse_mode="HTML",
        reply_markup=get_chemistry_theory_tickets_keyboard()
    )

@dp.callback_query(F.data.startswith("chem_theory_ticket:"))
async def cb_chem_theory_ticket(callback: CallbackQuery):
    await callback.answer()
    if not chemistry_tickets_access_ok(callback.from_user.id):
        await safe_edit_text(
            callback.message,
            get_chemistry_tickets_locked_text(),
            parse_mode="HTML",
            reply_markup=get_chemistry_tickets_locked_keyboard()
        )
        return
    num = callback.data.split(":")[1]
    ticket = CHEMISTRY_THEORY_TICKETS.get(num)
    if not ticket:
        await callback.answer("Билет не найден", show_alert=True)
        return
    await safe_edit_text(
        callback.message,
        f"📖 <b>{ticket['title']}</b>\n{DIVIDER}\n\nВыбери вопрос:",
        parse_mode="HTML",
        reply_markup=get_chemistry_theory_ticket_detail_keyboard(num)
    )

@dp.callback_query(F.data.startswith("chem_theory_q:"))
async def cb_chem_theory_question(callback: CallbackQuery):
    await callback.answer()
    if not chemistry_tickets_access_ok(callback.from_user.id):
        await safe_edit_text(
            callback.message,
            get_chemistry_tickets_locked_text(),
            parse_mode="HTML",
            reply_markup=get_chemistry_tickets_locked_keyboard()
        )
        return
    _, num, idx_s = callback.data.split(":")
    idx = int(idx_s)
    ticket = CHEMISTRY_THEORY_TICKETS.get(num)
    if not ticket or idx >= len(ticket["questions"]):
        await callback.answer("Вопрос не найден", show_alert=True)
        return
    q = ticket["questions"][idx]
    header = f"📖 <b>{ticket['title']} — Вопрос {idx + 1}</b>"
    body = f"{header}\n{DIVIDER}\n\n<b>{q['title']}</b>\n\n{q['answer']}"
    await safe_edit_text(callback.message, body, parse_mode="HTML", reply_markup=get_chemistry_theory_question_keyboard(num, idx))

@dp.callback_query(F.data == "chem_practice_tickets")
async def cb_chem_practice_tickets(callback: CallbackQuery):
    await callback.answer()
    if not chemistry_tickets_access_ok(callback.from_user.id):
        await safe_edit_text(
            callback.message,
            get_chemistry_tickets_locked_text(),
            parse_mode="HTML",
            reply_markup=get_chemistry_tickets_locked_keyboard()
        )
        return
    await safe_edit_text(
        callback.message,
        f"🧮 <b>Билеты практики</b>\n{DIVIDER}\n\nВыбери билет:",
        parse_mode="HTML",
        reply_markup=get_chemistry_practice_tickets_keyboard()
    )

@dp.callback_query(F.data.startswith("chem_practice_ticket:"))
async def cb_chem_practice_ticket(callback: CallbackQuery):
    await callback.answer()
    if not chemistry_tickets_access_ok(callback.from_user.id):
        await safe_edit_text(
            callback.message,
            get_chemistry_tickets_locked_text(),
            parse_mode="HTML",
            reply_markup=get_chemistry_tickets_locked_keyboard()
        )
        return
    num = callback.data.split(":")[1]
    ticket = CHEMISTRY_PRACTICE_TICKETS.get(num)
    if not ticket:
        await callback.answer("Билет не найден", show_alert=True)
        return
    text = f"🧮 <b>{ticket['title']}</b>\n{DIVIDER}\n\n{ticket['content']}"
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=get_chemistry_practice_ticket_keyboard())

# ==================== ХИМИЯ - ЗАДАЧИ ====================
@dp.callback_query(F.data == "chemistry_tasks")
async def cb_chemistry_tasks(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        f"📝 <b>Задачи по химии</b>\n{DIVIDER}\n\nВыбери тему:",
        parse_mode="HTML",
        reply_markup=get_chemistry_tasks_topics_keyboard()
    )

@dp.callback_query(F.data.startswith("chemtask_topic:"))
async def cb_chemtask_topic(callback: CallbackQuery):
    await callback.answer()
    topic_num = callback.data.split(":")[1]
    topic = CHEMISTRY_TASKS.get(topic_num)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    text = (
        f"📂 <b>{topic['title']}</b>\n{DIVIDER}\n\n"
        f"{topic.get('intro', '')}\n\n"
        f"Всего типовых задач: {len(topic['tasks'])}"
    )
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=get_chemistry_task_topic_keyboard(topic_num))

@dp.callback_query(F.data.startswith("chemtask_formulas:"))
async def cb_chemtask_formulas(callback: CallbackQuery):
    await callback.answer()
    topic_num = callback.data.split(":")[1]
    topic = CHEMISTRY_TASKS.get(topic_num)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    text = f"📂 <b>{topic['title']}</b>\n{DIVIDER}\n\n{topic['formulas']}"
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=get_chemistry_formulas_keyboard(topic_num))

@dp.callback_query(F.data.startswith("chemtask_list:"))
async def cb_chemtask_list(callback: CallbackQuery):
    await callback.answer()
    topic_num = callback.data.split(":")[1]
    topic = CHEMISTRY_TASKS.get(topic_num)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    text = f"📋 <b>{topic['title']} — список задач</b>\n{DIVIDER}\n\nВыбери задачу:"
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=get_chemistry_task_list_keyboard(topic_num))

@dp.callback_query(F.data.startswith("chemtask_show:"))
async def cb_chemtask_show(callback: CallbackQuery):
    await callback.answer()
    _, topic_num, task_num_s = callback.data.split(":")
    task_num = int(task_num_s)
    topic = CHEMISTRY_TASKS.get(topic_num)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    task = next((t for t in topic["tasks"] if t["num"] == task_num), None)
    if not task:
        await callback.answer("Задача не найдена", show_alert=True)
        return
    text = (
        f"📝 <b>Задача №{task['num']}</b> — {task.get('title', '')}\n{DIVIDER}\n\n"
        f"<b>Условие:</b>\n<i>{task['condition']}</i>\n\n"
        f"<b>Решение:</b>\n{task['solution']}"
    )
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=get_chemistry_task_detail_keyboard(topic_num, task_num))

# ==================== ХИМИЯ - ЛАБОРАТОРНЫЕ РАБОТЫ ====================
@dp.callback_query(F.data == "chemistry_labs")
async def cb_chemistry_labs(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        f"🧪 <b>Лабораторные работы по химии</b>\n{DIVIDER}\n\nВыбери лабораторную работу:",
        parse_mode="HTML",
        reply_markup=get_labs_keyboard()
    )

@dp.callback_query(F.data.startswith("lab:"))
async def cb_show_lab(callback: CallbackQuery):
    await callback.answer()
    lab_num = int(callback.data.split(":")[1])
    lab = next((entry for entry in CHEMISTRY_LABS["labs"] if entry["number"] == lab_num), None)
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
    if lab.get("summary"):
        builder.button(text="📝 Кратко (конспект)", callback_data=f"lab_summary:{lab_num}")
    builder.button(text="🔙 Назад к лабам", callback_data="chemistry_labs")
    builder.adjust(1)
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("lab_summary:"))
async def cb_lab_summary(callback: CallbackQuery):
    await callback.answer()
    lab_num = int(callback.data.split(":")[1])
    lab = next((entry for entry in CHEMISTRY_LABS["labs"] if entry["number"] == lab_num), None)
    if not lab or not lab.get("summary"):
        await callback.answer("Конспект не найден", show_alert=True)
        return
    text = f"📝 <b>Кратко — Лабораторная работа {lab_num}</b>\n{DIVIDER}\n\n{lab['summary']}"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data=f"lab:{lab_num}")
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("lab_exp:"))
async def cb_lab_experiments(callback: CallbackQuery):
    await callback.answer()
    lab_num = int(callback.data.split(":")[1])
    lab = next((entry for entry in CHEMISTRY_LABS["labs"] if entry["number"] == lab_num), None)
    if not lab or not lab.get("experiments"):
        await callback.answer("Опыты не найдены", show_alert=True)
        return
    text = f"🔬 <b>Опыты — Лабораторная работа {lab_num}</b>\n{DIVIDER}\n\n"
    for exp in lab["experiments"]:
        text += f"<b>{exp.get('name', '')}</b>\n{exp.get('description', '')}\n\n"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data=f"lab:{lab_num}")
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("lab_calc:"))
async def cb_lab_calculations(callback: CallbackQuery):
    await callback.answer()
    lab_num = int(callback.data.split(":")[1])
    lab = next((entry for entry in CHEMISTRY_LABS["labs"] if entry["number"] == lab_num), None)
    if not lab or not lab.get("calculations"):
        await callback.answer("Расчёты не найдены", show_alert=True)
        return
    text = f"📐 <b>Расчёты — Лабораторная работа {lab_num}</b>\n{DIVIDER}\n\n{lab['calculations']}"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data=f"lab:{lab_num}")
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=builder.as_markup())

# ==================== БИОЛОГИЯ — БИЛЕТЫ / ВОПРОСЫ ====================
# Билеты и вопросы (уникальные callback_data-фильтры, безопасно для порядка dp) вынесены в
# handlers/biology.py (свой Router) — здесь только регистрация роутера и реэкспорт имён. Режим
# опроса (quiz_*) и handle_question_number (F.text.isdigit(), сразу под этим блоком) сознательно
# НЕ перенесены — см. docstring handlers/biology.py.
from handlers import biology as biology_handlers  # noqa: E402 — mid-file by design, see above

dp.include_router(biology_handlers.router)

cb_random_ticket = biology_handlers.cb_random_ticket
show_ticket = biology_handlers.show_ticket
cb_ticket = biology_handlers.cb_ticket
cb_ticket_question = biology_handlers.cb_ticket_question
cb_question_page = biology_handlers.cb_question_page
cb_show_question = biology_handlers.cb_show_question
cb_question_random = biology_handlers.cb_question_random
cb_question_by_number = biology_handlers.cb_question_by_number
cb_question_search = biology_handlers.cb_question_search

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
        await send_answer(message, body, short_caption, q, get_question_answer_keyboard(q_num), edit=False)
    else:
        await message.answer("⚠️ Вопрос с таким номером не найден.")

# ==================== VMEDA AI (MVP) ====================
# Phase 1 (MVP): пользователь присылает фото/текст задания -> модель отвечает напрямую,
# без Knowledge Base/верификации (это следующие фазы, см. согласованный roadmap).
# Работает поверх существующих паттернов бота: свой gate (не через has_free_access),
# свои ключи в stats.json (ai_usage, через .setdefault — обычная миграция), не трогает
# ни один существующий раздел/контент/тариф.
#
# Провайдеры/роутинг/RAG/промпты/подготовка фото вынесены в пакет ai/ (см. ai/service.py,
# ai/router.py, ai/rag.py, ai/prompts.py, ai/vision.py, ai/providers/*) — здесь остаётся
# только то, что завязано на stats/save_stats/is_admin/DIVIDER и сами @dp-хендлеры (перенос
# хендлеров в отдельный router — следующая фаза рефакторинга, см. CLAUDE.md).
AI_FREE_DAILY_LIMIT = 3
AI_SESSION_TIMEOUT_SECONDS = 20 * 60  # диалог считается закрытым после 20 минут без сообщений
AI_SESSIONS: dict = {}  # user_id -> {"messages": [...], "last_active": ts, "processing": bool} — открытый диалог с памятью

def get_ai_usage_today(user_id: int) -> int:
    entry = stats["ai_usage"].get(str(user_id))
    if not entry or entry.get("date") != date.today().isoformat():
        return 0
    return entry.get("count", 0)

def increment_ai_usage(user_id: int) -> None:
    today = date.today().isoformat()
    entry = stats["ai_usage"].get(str(user_id))
    if not entry or entry.get("date") != today:
        entry = {"date": today, "count": 0}
    entry["count"] += 1
    stats["ai_usage"][str(user_id)] = entry
    save_stats()

def has_unlimited_ai(user_id: int) -> bool:
    return is_admin(user_id)

def ai_requests_left(user_id: int) -> int:
    return max(0, AI_FREE_DAILY_LIMIT - get_ai_usage_today(user_id))

def ai_quota_ok(user_id: int) -> bool:
    return has_unlimited_ai(user_id) or ai_requests_left(user_id) > 0

def get_ai_quota_label(user_id: int) -> str:
    return "♾ безлимит (админ)" if has_unlimited_ai(user_id) else f"{ai_requests_left(user_id)}/{AI_FREE_DAILY_LIMIT}"

_AI_PROVIDER_PRICES = {
    "openai": (ai_openai.PRICE_INPUT_PER_1M, ai_openai.PRICE_OUTPUT_PER_1M),
    "grok": (ai_xai.PRICE_INPUT_PER_1M, ai_xai.PRICE_OUTPUT_PER_1M),
    "gemini": (ai_gemini.PRICE_INPUT_PER_1M, ai_gemini.PRICE_OUTPUT_PER_1M),
}

def record_ai_cost(usage: dict) -> None:
    """Копит агрегированную стоимость AI-запросов — не пишет по записи на каждый запрос
    (раздуло бы stats.json), только бегущие суммы. Нужно, чтобы реально видеть эффект
    любых будущих оптимизаций (короткие ответы, кэш и т.д.), а не гадать на глаз.
    usage["provider"] ("openai"/"grok"/"gemini", по умолчанию "openai") выбирает прайс — у
    каждого провайдера своя цена за токен, общие totals остаются суммой по всем провайдерам, а
    by_provider хранит разбивку, чтобы в статистике было видно расход каждого провайдера
    отдельно от OpenAI."""
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    provider = usage.get("provider", "openai")
    price_in, price_out = _AI_PROVIDER_PRICES.get(provider, _AI_PROVIDER_PRICES["openai"])
    cost = input_tokens * price_in / 1_000_000 + output_tokens * price_out / 1_000_000
    totals = stats["ai_cost_totals"]
    totals["requests"] += 1
    totals["input_tokens"] += input_tokens
    totals["output_tokens"] += output_tokens
    totals["cost_usd"] += cost
    by_provider = totals.setdefault("by_provider", {})
    p = by_provider.setdefault(provider, {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
    p["requests"] += 1
    p["input_tokens"] += input_tokens
    p["output_tokens"] += output_tokens
    p["cost_usd"] += cost
    save_stats()

def get_ai_cost_stats_block() -> str:
    totals = stats["ai_cost_totals"]
    requests = totals["requests"]
    avg = totals["cost_usd"] / requests if requests else 0.0
    block = (
        f"\n🤖 <b>VMedA AI</b>\n"
        f"Запросов: <b>{requests}</b> (вход {totals['input_tokens']:,} / выход {totals['output_tokens']:,} ток.)\n"
        f"Расход: <b>${totals['cost_usd']:.4f}</b>, в среднем ${avg:.5f}/запрос"
    )
    by_provider = totals.get("by_provider", {})
    for provider, label in (("grok", "Grok"), ("gemini", "Gemini")):
        p = by_provider.get(provider)
        if p and p["requests"]:
            block += f"\n  из них {label}: {p['requests']} запр., ${p['cost_usd']:.4f}"
    return block.replace(",", " ")

def is_ai_session_active(user_id: int) -> bool:
    session = AI_SESSIONS.get(user_id)
    return bool(session) and time.time() - session["last_active"] < AI_SESSION_TIMEOUT_SECONDS

def start_ai_session(user_id: int) -> None:
    AI_SESSIONS[user_id] = {"messages": [], "last_active": time.time(), "processing": False}

def end_ai_session(user_id: int) -> None:
    AI_SESSIONS.pop(user_id, None)

def get_ai_menu_text(user_id: int) -> str:
    availability = "" if OPENAI_API_KEY else "\n\n🔧 Идут финальные настройки — совсем скоро запустим."
    return (
        f"🤖 <b>VMedA AI</b>\n{DIVIDER}\n\n"
        "AI-помощник, который разбирает задание по фото или тексту и сразу выдаёт решение: "
        "чёткий ответ и объяснение по шагам. Работает по биологии, физике и химии — тесты, "
        "билеты, контрольные, летучки. Просто присылаешь фото — получаешь разбор.\n\n"
        f"Бесплатных запросов сегодня: <b>{get_ai_quota_label(user_id)}</b>"
        f"{availability}"
    )

def get_ai_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📷 Отправить фото или текст задания", callback_data="ai_solve_start")
    builder.button(text="🔙 Назад в меню", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()

def get_ai_waiting_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🛑 Отмена", callback_data="ai_solve_cancel")
    builder.adjust(1)
    return builder.as_markup()

def get_ai_result_text(answer: str, user_id: int, session_active: bool, offer_explanation: bool = False) -> str:
    if offer_explanation:
        continuation = "\n\n🧠 Это краткий ответ — нажми кнопку ниже, если нужно решение по шагам."
    elif session_active:
        continuation = "\n\n💬 Можешь сразу уточнить вопрос по этой же теме — я помню контекст диалога."
    else:
        continuation = ""
    return (
        f"🤖 <b>Ответ AI</b>\n{DIVIDER}\n\n{ai_service.format_answer_html(answer)}\n\n"
        f"💡 Сверяй важные ответы с материалами курса.\n"
        f"Осталось бесплатных запросов сегодня: {get_ai_quota_label(user_id)}"
        f"{continuation}"
    )

def get_ai_result_keyboard(session_active: bool, offer_explanation: bool = False):
    builder = InlineKeyboardBuilder()
    if offer_explanation and session_active:
        builder.button(text="🧠 Показать решение по шагам", callback_data="ai_show_explanation")
    if session_active:
        builder.button(text="🔚 Закончить диалог", callback_data="ai_session_end")
    else:
        builder.button(text="🔙 Назад в меню", callback_data="ai_menu")
    builder.adjust(1)
    return builder.as_markup()

@dp.callback_query(F.data == "ai_menu")
async def cb_ai_menu(callback: CallbackQuery):
    await callback.answer()
    end_ai_session(callback.from_user.id)
    await safe_edit_text(
        callback.message,
        get_ai_menu_text(callback.from_user.id),
        parse_mode="HTML",
        reply_markup=get_ai_menu_keyboard()
    )

@dp.callback_query(F.data == "ai_solve_start")
async def cb_ai_solve_start(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not OPENAI_API_KEY:
        await callback.answer("AI сейчас на техническом обслуживании, загляни позже.", show_alert=True)
        return
    if not ai_quota_ok(user_id):
        await callback.answer("На сегодня бесплатные AI-запросы закончились, попробуй завтра.", show_alert=True)
        return
    await callback.answer()
    start_ai_session(user_id)
    await safe_edit_text(
        callback.message,
        f"📷 <b>Жду задание</b>\n{DIVIDER}\n\nПришли фото задания или напиши его текстом одним сообщением. "
        "Дальше можно будет уточнять вопросы по теме — контекст диалога сохранится.",
        parse_mode="HTML",
        reply_markup=get_ai_waiting_keyboard()
    )

@dp.callback_query(F.data == "ai_solve_cancel")
async def cb_ai_solve_cancel(callback: CallbackQuery):
    end_ai_session(callback.from_user.id)
    await callback.answer()
    await safe_edit_text(
        callback.message,
        get_ai_menu_text(callback.from_user.id),
        parse_mode="HTML",
        reply_markup=get_ai_menu_keyboard()
    )

@dp.callback_query(F.data == "ai_session_end")
async def cb_ai_session_end(callback: CallbackQuery):
    end_ai_session(callback.from_user.id)
    await callback.answer("Диалог закончен")
    await safe_edit_text(
        callback.message,
        get_ai_menu_text(callback.from_user.id),
        parse_mode="HTML",
        reply_markup=get_ai_menu_keyboard()
    )

@dp.callback_query(F.data == "ai_show_explanation")
async def cb_ai_show_explanation(callback: CallbackQuery):
    """Второй, отдельный запрос — только по явному нажатию, только если после короткого
    ответа ещё остался дневной лимит. Большинство тестовых вопросов на этом и заканчиваются,
    не оплачивая длинный пошаговый разбор, который часто и не нужен."""
    user_id = callback.from_user.id
    if not is_ai_session_active(user_id):
        await callback.answer("Диалог уже закрыт, начни заново через меню AI.", show_alert=True)
        return
    session = AI_SESSIONS[user_id]
    if session["processing"]:
        await callback.answer()
        return
    if not ai_quota_ok(user_id):
        end_ai_session(user_id)
        await callback.answer("На сегодня бесплатные AI-запросы закончились, попробуй завтра.", show_alert=True)
        return
    await callback.answer()
    session["processing"] = True
    thinking = await callback.message.answer("🤖 Готовлю решение по шагам...")
    try:
        answer, user_turn, usage = await solve_ai_request(
            text=ai_prompts.EXPLAIN_FOLLOWUP_TEXT, history=session["messages"], quick=False,
            task_type=session.get("task_type"), rag_context=session.get("rag_context"),
        )
        increment_ai_usage(user_id)
        record_ai_cost(usage)
        session["messages"].append(user_turn)
        session["messages"].append({"role": "assistant", "content": answer})
        session["last_active"] = time.time()
        session_active = ai_quota_ok(user_id)
        if not session_active:
            end_ai_session(user_id)
        await safe_edit_text(
            thinking,
            get_ai_result_text(answer, user_id, session_active),
            parse_mode="HTML",
            reply_markup=get_ai_result_keyboard(session_active)
        )
    except AIRefusalError:
        logger.warning("AI отказался дать подробный разбор пользователю %s", user_id)
        await safe_edit_text(
            thinking,
            "⚠️ AI отказался отвечать на этот конкретный вопрос — похоже, сработал фильтр "
            "содержимого провайдера (так бывает на некоторых медицинских формулировках). "
            "Эта попытка не списана с дневного лимита — попробуй переформулировать вопрос."
        )
    except Exception:
        logger.exception("Ошибка при получении подробного решения для пользователя %s", user_id)
        await safe_edit_text(thinking, "⚠️ Не удалось получить решение. Попробуй ещё раз позже.")
    finally:
        if user_id in AI_SESSIONS:
            AI_SESSIONS[user_id]["processing"] = False

@dp.message(F.photo)
async def handle_ai_photo_input(message: Message):
    """Единственный обработчик входящих фото в боте — фото вне AI-режима бот
    никогда раньше не принимал, поэтому конфликтов с другими хендлерами нет."""
    user_id = message.from_user.id
    if not is_ai_session_active(user_id):
        return
    session = AI_SESSIONS[user_id]
    if session["processing"]:
        return  # предыдущее сообщение этого диалога ещё обрабатывается — вероятный случайный дубль
    if not ai_quota_ok(user_id):
        end_ai_session(user_id)
        await message.answer("На сегодня бесплатные AI-запросы закончились, попробуй завтра.")
        return
    quick = not session["messages"]  # самое первое сообщение сессии — сперва только краткий ответ
    session["processing"] = True
    thinking = await message.answer("🤖 Разбираю задание, подожди немного...")
    try:
        photo = message.photo[-1]
        tg_file = await bot.get_file(photo.file_id)
        buf = await bot.download_file(tg_file.file_path)
        answer, user_turn, usage = await solve_ai_request(
            image_bytes=resize_image_for_ai(buf.read()), history=session["messages"], quick=quick,
            task_type=session.get("task_type"), rag_context=session.get("rag_context"),
        )
        increment_ai_usage(user_id)
        record_ai_cost(usage)
        if quick:
            session["task_type"] = ai_router.classify_quick_answer(answer)
            session["rag_context"] = ai_rag.format_context(ai_rag.search_snippets_multi(answer))
        session["messages"].append(user_turn)
        session["messages"].append({"role": "assistant", "content": answer})
        session["last_active"] = time.time()
        session_active = ai_quota_ok(user_id)
        if not session_active:
            end_ai_session(user_id)
        await safe_edit_text(
            thinking,
            get_ai_result_text(answer, user_id, session_active, offer_explanation=quick),
            parse_mode="HTML",
            reply_markup=get_ai_result_keyboard(session_active, offer_explanation=quick)
        )
    except AIRefusalError:
        logger.warning("AI отказался разобрать фото от пользователя %s", user_id)
        await safe_edit_text(
            thinking,
            "⚠️ AI отказался отвечать на это фото — похоже, сработал фильтр содержимого "
            "провайдера (так бывает на некоторых медицинских формулировках). Эта попытка не "
            "списана с дневного лимита — попробуй прислать вопрос текстом или переформулировать."
        )
    except Exception:
        logger.exception("Ошибка при обработке AI-фото от пользователя %s", user_id)
        await safe_edit_text(thinking, "⚠️ Не удалось обработать фото. Попробуй ещё раз или пришли текстом.")
    finally:
        if user_id in AI_SESSIONS:
            AI_SESSIONS[user_id]["processing"] = False

@dp.message(F.text)
async def handle_ai_text_input(message: Message):
    user_id = message.from_user.id
    if not is_ai_session_active(user_id):
        raise SkipHandler  # не AI-режим — пусть сообщение обработают остальные текстовые хендлеры
    if message.text.startswith("/"):
        raise SkipHandler
    session = AI_SESSIONS[user_id]
    if session["processing"]:
        raise SkipHandler  # предыдущее сообщение этого диалога ещё обрабатывается — вероятный случайный дубль
    if not ai_quota_ok(user_id):
        end_ai_session(user_id)
        await message.answer("На сегодня бесплатные AI-запросы закончились, попробуй завтра.")
        return
    quick = not session["messages"]  # самое первое сообщение сессии — сперва только краткий ответ
    session["processing"] = True
    thinking = await message.answer("🤖 Разбираю задание, подожди немного...")
    try:
        answer, user_turn, usage = await solve_ai_request(
            text=message.text, history=session["messages"], quick=quick,
            task_type=session.get("task_type"), rag_context=session.get("rag_context"),
        )
        increment_ai_usage(user_id)
        record_ai_cost(usage)
        if quick:
            session["task_type"] = ai_router.classify_quick_answer(answer)
            session["rag_context"] = ai_rag.format_context(
                ai_rag.search_snippets_multi(f"{message.text} {answer}")
            )
        session["messages"].append(user_turn)
        session["messages"].append({"role": "assistant", "content": answer})
        session["last_active"] = time.time()
        session_active = ai_quota_ok(user_id)
        if not session_active:
            end_ai_session(user_id)
        await safe_edit_text(
            thinking,
            get_ai_result_text(answer, user_id, session_active, offer_explanation=quick),
            parse_mode="HTML",
            reply_markup=get_ai_result_keyboard(session_active, offer_explanation=quick)
        )
    except AIRefusalError:
        logger.warning("AI отказался ответить на текст от пользователя %s", user_id)
        await safe_edit_text(
            thinking,
            "⚠️ AI отказался отвечать на этот конкретный вопрос — похоже, сработал фильтр "
            "содержимого провайдера (так бывает на некоторых медицинских формулировках). "
            "Эта попытка не списана с дневного лимита — попробуй переформулировать вопрос."
        )
    except Exception:
        logger.exception("Ошибка при обработке AI-текста от пользователя %s", user_id)
        await safe_edit_text(thinking, "⚠️ Не удалось получить ответ от AI. Попробуй ещё раз позже.")
    finally:
        if user_id in AI_SESSIONS:
            AI_SESSIONS[user_id]["processing"] = False

# ==================== СКРЫТАЯ ФУНКЦИЯ (ВРЕМЕННО) ====================
# Если написать боту номер билета текстом (например "20А"), в чат придут все
# вопросы и ответы этого билета подряд, без кнопок. Без команд и упоминаний в меню.
@dp.message(F.text)
async def handle_hidden_ticket_dump(message: Message):
    ticket = TICKET_LOOKUP.get(_normalize_ticket_num(message.text))
    if not ticket:
        raise SkipHandler  # не билет — пусть попробует обработать поиск по словам
    ticket_num = ticket.get("num", "?")
    questions = ticket.get("questions", [])
    await message.answer(f"📘 <b>Билет {ticket_num}</b> — все ответы\n{DIVIDER}", parse_mode="HTML")
    for q in questions:
        q_num = q.get("num")
        body = f"❓ <b>Вопрос {q_num}</b>\n{DIVIDER}\n\n<b>{q.get('title', '')}</b>\n\n{q.get('answer', '')}"
        image_name = q.get("image")
        image_path = os.path.join(IMAGES_DIR, image_name) if image_name else None
        if image_path and os.path.exists(image_path):
            try:
                await message.answer_photo(FSInputFile(image_path))
            except Exception:
                logger.exception("Не удалось отправить изображение %s", image_path)
        await message.answer(body, parse_mode="HTML")

# ==================== ПОИСК ПО КЛЮЧЕВЫМ СЛОВАМ (обработчик) ====================
@dp.message(F.text)
async def handle_keyword_search(message: Message):
    query = (message.text or "").strip()
    if not query or query.startswith("/"):
        return
    results = search_questions_by_keyword(query)
    safe_query = html.escape(query)
    if not results:
        await message.answer(
            f"🔍 По запросу «{safe_query}» ничего не найдено.\n"
            "Попробуй другое слово или загляни в раздел «📝 Вопросы»."
        )
        return
    suffix = f" (показаны первые {SEARCH_RESULTS_LIMIT})" if len(results) >= SEARCH_RESULTS_LIMIT else ""
    text = (
        f"🔍 <b>Результаты поиска:</b> «{safe_query}»\n{DIVIDER}\n\n"
        f"Найдено вопросов: {len(results)}{suffix}\nВыбери нужный:"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_search_results_keyboard(results))

# ==================== ФИЗИКА ====================
@dp.callback_query(F.data == "physics_tickets")
async def cb_physics_tickets(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        f"📘 <b>Билеты по физике</b>\n{DIVIDER}\n\nВыбери раздел:",
        parse_mode="HTML",
        reply_markup=get_physics_tickets_menu()
    )

@dp.callback_query(F.data == "physics_theory_tickets")
async def cb_physics_theory_tickets(callback: CallbackQuery):
    await callback.answer()
    if not PHYSICS_THEORY_TICKETS:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="physics_tickets"))
        await safe_edit_text(
            callback.message,
            f"📖 <b>Билеты теоретической части</b>\n{DIVIDER}\n\n🚧 Скоро будут добавлены!",
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )
        return
    await safe_edit_text(
        callback.message,
        f"📖 <b>Билеты теоретической части</b>\n{DIVIDER}\n\nВыбери билет:",
        parse_mode="HTML",
        reply_markup=get_physics_theory_tickets_keyboard()
    )

@dp.callback_query(F.data.startswith("phys_theory_ticket:"))
async def cb_phys_theory_ticket(callback: CallbackQuery):
    await callback.answer()
    num = callback.data.split(":")[1]
    ticket = PHYSICS_THEORY_TICKETS.get(num)
    if not ticket:
        await callback.answer("Билет не найден", show_alert=True)
        return
    await safe_edit_text(
        callback.message,
        f"📖 <b>{ticket['title']}</b>\n{DIVIDER}\n\nВыбери вопрос:",
        parse_mode="HTML",
        reply_markup=get_physics_theory_ticket_detail_keyboard(num)
    )

@dp.callback_query(F.data.startswith("phys_theory_q:"))
async def cb_phys_theory_question(callback: CallbackQuery):
    await callback.answer()
    _, num, idx_s = callback.data.split(":")
    idx = int(idx_s)
    ticket = PHYSICS_THEORY_TICKETS.get(num)
    if not ticket or idx >= len(ticket["questions"]):
        await callback.answer("Вопрос не найден", show_alert=True)
        return
    q = ticket["questions"][idx]
    header = f"📖 <b>{ticket['title']} — Вопрос {idx + 1}</b>"
    body = f"{header}\n{DIVIDER}\n\n<b>{q['title']}</b>\n\n{q['answer']}"
    await safe_edit_text(callback.message, body, parse_mode="HTML", reply_markup=get_physics_theory_question_keyboard(num, idx))

@dp.callback_query(F.data == "physics_test_tickets")
async def cb_physics_test_tickets(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        f"📝 <b>Тестовые билеты</b>\n{DIVIDER}\n\nВыбери вариант:",
        parse_mode="HTML",
        reply_markup=get_physics_test_tickets_keyboard()
    )

@dp.callback_query(F.data.startswith("phys_test_ticket:"))
async def cb_phys_test_ticket(callback: CallbackQuery):
    await callback.answer()
    num = callback.data.split(":")[1]
    ticket = PHYSICS_TEST_TICKETS.get(num)
    if not ticket:
        await callback.answer("Билет не найден", show_alert=True)
        return
    lines = [f"📄 <b>{ticket['title']}</b>", DIVIDER]
    for question in ticket["questions"]:
        lines.append(f"\n<b>{question['num']}.</b> {question['text']}")
        for letter, option in question["options"].items():
            marker = "✅ " if letter == question["correct"] else ""
            lines.append(f"{marker}{letter}) {option}")
    text = "\n".join(lines)
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=get_physics_test_ticket_detail_keyboard(num))

@dp.callback_query(F.data.startswith("phys_test_ticket_tasks:"))
async def cb_phys_test_ticket_tasks(callback: CallbackQuery):
    await callback.answer()
    num = callback.data.split(":")[1]
    ticket = PHYSICS_TEST_TICKETS.get(num)
    if not ticket or not ticket.get("tasks"):
        await callback.answer("Задачи не найдены", show_alert=True)
        return
    text = f"🧮 <b>{ticket['title']} — Часть 2. Задачи</b>\n{DIVIDER}\n\nВыбери задачу:"
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=get_physics_test_ticket_task_list_keyboard(num))

@dp.callback_query(F.data.startswith("phys_test_ticket_task_show:"))
async def cb_phys_test_ticket_task_show(callback: CallbackQuery):
    await callback.answer()
    _, num, task_num_s = callback.data.split(":")
    task_num = int(task_num_s)
    ticket = PHYSICS_TEST_TICKETS.get(num)
    if not ticket:
        await callback.answer("Билет не найден", show_alert=True)
        return
    task = next((t for t in ticket.get("tasks", []) if t["num"] == task_num), None)
    if not task:
        await callback.answer("Задача не найдена", show_alert=True)
        return
    text = (
        f"📝 <b>{ticket['title']} — Задача №{task['num']}</b> — {task.get('title', '')}\n{DIVIDER}\n\n"
        f"<b>Условие:</b>\n<i>{task['condition']}</i>\n\n"
        f"<b>Решение:</b>\n{task['solution']}"
    )
    await safe_edit_text(
        callback.message, text, parse_mode="HTML",
        reply_markup=get_physics_test_ticket_task_detail_keyboard(num, task_num)
    )

@dp.callback_query(F.data == "physics_task_tickets")
async def cb_physics_task_tickets(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        f"🧮 <b>Билеты с задачами</b>\n{DIVIDER}\n\nВыбери билет:",
        parse_mode="HTML",
        reply_markup=get_physics_task_tickets_keyboard()
    )

@dp.callback_query(F.data.startswith("phys_task_ticket:"))
async def cb_phys_task_ticket(callback: CallbackQuery):
    await callback.answer()
    num = callback.data.split(":")[1]
    ticket = PHYSICS_TASK_TICKETS.get(num)
    if not ticket:
        await callback.answer("Билет не найден", show_alert=True)
        return
    text = f"🧮 <b>{ticket['title']}</b>\n{DIVIDER}\n\nВыбери задачу:"
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=get_physics_task_ticket_list_keyboard(num))

@dp.callback_query(F.data.startswith("phys_task_ticket_show:"))
async def cb_phys_task_ticket_show(callback: CallbackQuery):
    await callback.answer()
    _, num, task_num_s = callback.data.split(":")
    task_num = int(task_num_s)
    ticket = PHYSICS_TASK_TICKETS.get(num)
    if not ticket:
        await callback.answer("Билет не найден", show_alert=True)
        return
    task = next((t for t in ticket.get("tasks", []) if t["num"] == task_num), None)
    if not task:
        await callback.answer("Задача не найдена", show_alert=True)
        return
    text = (
        f"📝 <b>{ticket['title']} — Задача №{task['num']}</b> — {task.get('title', '')}\n{DIVIDER}\n\n"
        f"<b>Условие:</b>\n<i>{task['condition']}</i>\n\n"
        f"<b>Решение:</b>\n{task['solution']}"
    )
    await safe_edit_text(
        callback.message, text, parse_mode="HTML",
        reply_markup=get_physics_task_ticket_detail_keyboard(num, task_num)
    )

@dp.callback_query(F.data == "physics_test")
async def cb_physics_test(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        f"📝 <b>Тестовая часть — Физика</b>\n{DIVIDER}\n\nВыбери страницу:",
        parse_mode="HTML",
        reply_markup=get_physics_test_pages()
    )

@dp.callback_query(F.data.startswith("physics_page:"))
async def cb_physics_page(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    await callback.answer()
    await safe_edit_text(
        callback.message,
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
        header = f"❓ <b>Вопрос {q_num}</b>"
        body = f"{header}\n{DIVIDER}\n\n<b>{q.get('title', '')}</b>\n\n{q.get('answer', '')}"
        short_caption = f"{header}\n{DIVIDER}\n\n<b>{q.get('title', '')}</b>"
        await send_answer(callback.message, body, short_caption, q, get_physics_answer_keyboard(q_num), edit=True)
    else:
        await callback.answer("Вопрос пока не добавлен в файл", show_alert=True)

@dp.callback_query(F.data == "physics_grade45")
async def cb_physics_grade45(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        f"❓ <b>(60 вопросов) на 4/5</b>\n{DIVIDER}\n\nВыбери вопрос:",
        parse_mode="HTML",
        reply_markup=get_physics_grade45_keyboard()
    )

@dp.callback_query(F.data.startswith("physics45_q:"))
async def cb_physics_grade45_question(callback: CallbackQuery):
    await callback.answer()
    q_num = callback.data.split(":")[1]
    if q_num in PHYSICS_GRADE45_QUESTIONS:
        q = PHYSICS_GRADE45_QUESTIONS[q_num]
        header = f"❓ <b>Вопрос {q_num}</b>"
        body = f"{header}\n{DIVIDER}\n\n<b>{q.get('title', '')}</b>\n\n{q.get('answer', '')}"
        short_caption = f"{header}\n{DIVIDER}\n\n<b>{q.get('title', '')}</b>"
        await send_answer(callback.message, body, short_caption, q, get_physics_grade45_answer_keyboard(q_num), edit=True)
    else:
        await callback.answer("Вопрос пока не добавлен в файл", show_alert=True)

@dp.callback_query(F.data == "physics_extra")
async def cb_physics_extra(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        f"⭐ <b>Доп. вопросы от преподавателей</b>\n{DIVIDER}\n\nВыбери вопрос:",
        parse_mode="HTML",
        reply_markup=get_physics_extra_keyboard()
    )

@dp.callback_query(F.data.startswith("physics_extra_q:"))
async def cb_physics_extra_question(callback: CallbackQuery):
    await callback.answer()
    q_num = callback.data.split(":")[1]
    if q_num in PHYSICS_EXTRA_QUESTIONS:
        q = PHYSICS_EXTRA_QUESTIONS[q_num]
        header = "⭐ <b>Доп. вопрос от преподавателей</b>"
        body = f"{header}\n{DIVIDER}\n\n<b>{q.get('title', '')}</b>\n\n{q.get('answer', '')}"
        short_caption = f"{header}\n{DIVIDER}\n\n<b>{q.get('title', '')}</b>"
        await send_answer(callback.message, body, short_caption, q, get_physics_extra_answer_keyboard(q_num), edit=True)
    else:
        await callback.answer("Вопрос пока не добавлен в файл", show_alert=True)

# ==================== ФИЗИКА - ЗАДАЧИ ====================
@dp.callback_query(F.data == "physics_tasks")
async def cb_physics_tasks(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        f"🧮 <b>Задачи по физике</b>\n{DIVIDER}\n\nВыбери тему:",
        parse_mode="HTML",
        reply_markup=get_physics_tasks_topics_keyboard()
    )

@dp.callback_query(F.data.startswith("phystask_topic:"))
async def cb_phystask_topic(callback: CallbackQuery):
    await callback.answer()
    topic_num = callback.data.split(":")[1]
    topic = PHYSICS_TASKS.get(topic_num)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    text = (
        f"📂 <b>{topic['title']}</b>\n{DIVIDER}\n\n"
        f"{topic.get('intro', '')}\n\n"
        f"Всего типовых задач: {len(topic['tasks'])}"
    )
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=get_physics_task_topic_keyboard(topic_num))

@dp.callback_query(F.data.startswith("phystask_formulas:"))
async def cb_phystask_formulas(callback: CallbackQuery):
    await callback.answer()
    topic_num = callback.data.split(":")[1]
    topic = PHYSICS_TASKS.get(topic_num)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    text = f"📂 <b>{topic['title']}</b>\n{DIVIDER}\n\n{topic['formulas']}"
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=get_physics_formulas_keyboard(topic_num))

@dp.callback_query(F.data.startswith("phystask_list:"))
async def cb_phystask_list(callback: CallbackQuery):
    await callback.answer()
    topic_num = callback.data.split(":")[1]
    topic = PHYSICS_TASKS.get(topic_num)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    text = f"📋 <b>{topic['title']} — список задач</b>\n{DIVIDER}\n\nВыбери задачу:"
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=get_physics_task_list_keyboard(topic_num))

@dp.callback_query(F.data.startswith("phystask_show:"))
async def cb_phystask_show(callback: CallbackQuery):
    await callback.answer()
    _, topic_num, task_num_s = callback.data.split(":")
    task_num = int(task_num_s)
    topic = PHYSICS_TASKS.get(topic_num)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    task = next((t for t in topic["tasks"] if t["num"] == task_num), None)
    if not task:
        await callback.answer("Задача не найдена", show_alert=True)
        return
    text = (
        f"📝 <b>Задача №{task['num']}</b> — {task.get('title', '')}\n{DIVIDER}\n\n"
        f"<b>Условие:</b>\n<i>{task['condition']}</i>\n\n"
        f"<b>Решение:</b>\n{task['solution']}"
    )
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=get_physics_task_detail_keyboard(topic_num, task_num))

# ==================== АНАТОМИЯ (В РАЗРАБОТКЕ, ПОКА ДОСТУПНО ТОЛЬКО АДМИНАМ) ====================
# Хендлеры и вся логика раздела вынесены в handlers/anatomy.py (свой Router) — здесь только
# регистрация роутера на dp и реэкспорт имён, на которые ссылается остальной код файла (главное
# меню, админ-панель) и тесты, обращающиеся к ним как tb.<имя>. Сам импорт стоит здесь (в самом
# конце файла, как и раньше стояла вся секция), чтобы handlers/anatomy.py при своём импорте уже
# видел все нужные ему имена (stats, save_stats, DIVIDER, ACTIVE_SUBSCRIPTION_TIERS и т.д.)
# определёнными в этом модуле.
from handlers import anatomy as anatomy_handlers  # noqa: E402 — deliberately late, see above

dp.include_router(anatomy_handlers.router)

ANATOMY_PUBLIC = anatomy_handlers.ANATOMY_PUBLIC
# ANATOMY_MAINTENANCE_MODE is intentionally NOT re-exported as a flat copy here — unlike every
# other name in this block, it's a scalar bool that both production code (get_main_menu, below)
# and tests toggle at runtime. A flat `X = anatomy_handlers.X` assignment only snapshots the
# value at import time; reassigning the copy (`tb.ANATOMY_MAINTENANCE_MODE = ...`) would silently
# stop affecting the real flag `cb_anatomy_root` reads in handlers/anatomy.py, and vice versa —
# always go through `anatomy_handlers.ANATOMY_MAINTENANCE_MODE` (both here and in tests) so
# there's exactly one source of truth.
ANATOMY_FLASH_SESSION_SIZE = anatomy_handlers.ANATOMY_FLASH_SESSION_SIZE
ANATOMY_MATCH_SESSION_SIZE = anatomy_handlers.ANATOMY_MATCH_SESSION_SIZE
ANATOMY_LATIN_SESSION_SIZE = anatomy_handlers.ANATOMY_LATIN_SESSION_SIZE
ANATOMY_LATIN_ALL_SESSION_SIZE = anatomy_handlers.ANATOMY_LATIN_ALL_SESSION_SIZE
ANATOMY_LATIN_LEADERBOARD_MSG_LIMIT = anatomy_handlers.ANATOMY_LATIN_LEADERBOARD_MSG_LIMIT
ANATOMY_FLASH_SESSIONS = anatomy_handlers.ANATOMY_FLASH_SESSIONS
ANATOMY_MATCH_SESSIONS = anatomy_handlers.ANATOMY_MATCH_SESSIONS
ANATOMY_LATIN_SESSIONS = anatomy_handlers.ANATOMY_LATIN_SESSIONS
anatomy_access_ok = anatomy_handlers.anatomy_access_ok
ANATOMY_FREE_SECTIONS = anatomy_handlers.ANATOMY_FREE_SECTIONS
anatomy_section_access_ok = anatomy_handlers.anatomy_section_access_ok
get_anatomy_dev_alert_text = anatomy_handlers.get_anatomy_dev_alert_text
get_anatomy_topic_data = anatomy_handlers.get_anatomy_topic_data
get_topic_section_key = anatomy_handlers.get_topic_section_key
get_anatomy_locked_text = anatomy_handlers.get_anatomy_locked_text
get_anatomy_locked_keyboard = anatomy_handlers.get_anatomy_locked_keyboard
get_anatomy_menu_keyboard = anatomy_handlers.get_anatomy_menu_keyboard
get_anatomy_section_keyboard = anatomy_handlers.get_anatomy_section_keyboard
get_anatomy_topic_keyboard = anatomy_handlers.get_anatomy_topic_keyboard
get_anatomy_bones_keyboard = anatomy_handlers.get_anatomy_bones_keyboard
get_bone_title = anatomy_handlers.get_bone_title
get_bone_material_list = anatomy_handlers.get_bone_material_list
get_bone_flashcards = anatomy_handlers.get_bone_flashcards
get_bone_pairs = anatomy_handlers.get_bone_pairs
get_bone_mnemonics = anatomy_handlers.get_bone_mnemonics
get_bone_latin_terms = anatomy_handlers.get_bone_latin_terms
ANATOMY_ATLAS_CREDITS = anatomy_handlers.ANATOMY_ATLAS_CREDITS
ANATOMY_ALBUM_PAGE_SIZE = anatomy_handlers.ANATOMY_ALBUM_PAGE_SIZE
anatomy_page_count = anatomy_handlers.anatomy_page_count
get_bone_images = anatomy_handlers.get_bone_images
get_anatomy_bone_hub_keyboard = anatomy_handlers.get_anatomy_bone_hub_keyboard
get_anatomy_bone_hub_text = anatomy_handlers.get_anatomy_bone_hub_text
ANATOMY_FILE_ID_CACHE_PATH = anatomy_handlers.ANATOMY_FILE_ID_CACHE_PATH
_load_anatomy_file_id_cache = anatomy_handlers._load_anatomy_file_id_cache
ANATOMY_FILE_ID_CACHE = anatomy_handlers.ANATOMY_FILE_ID_CACHE
_write_anatomy_file_id_cache = anatomy_handlers._write_anatomy_file_id_cache
save_anatomy_file_id_cache = anatomy_handlers.save_anatomy_file_id_cache
_anatomy_image_key = anatomy_handlers._anatomy_image_key
_anatomy_image_media = anatomy_handlers._anatomy_image_media
_cache_anatomy_file_id = anatomy_handlers._cache_anatomy_file_id
build_input_media_photo = anatomy_handlers.build_input_media_photo
send_anatomy_album = anatomy_handlers.send_anatomy_album
get_topic_atlas_images = anatomy_handlers.get_topic_atlas_images
get_topic_latin_terms = anatomy_handlers.get_topic_latin_terms
get_all_latin_terms = anatomy_handlers.get_all_latin_terms
start_anatomy_latin_session = anatomy_handlers.start_anatomy_latin_session
get_anatomy_latin_keyboard = anatomy_handlers.get_anatomy_latin_keyboard
pick_anatomy_latin_distractors = anatomy_handlers.pick_anatomy_latin_distractors
render_anatomy_latin_question = anatomy_handlers.render_anatomy_latin_question
record_anatomy_latin_score = anatomy_handlers.record_anatomy_latin_score
get_anatomy_latin_leaderboard_text = anatomy_handlers.get_anatomy_latin_leaderboard_text
get_anatomy_latin_leaderboard_keyboard = anatomy_handlers.get_anatomy_latin_leaderboard_keyboard
render_anatomy_latin_summary = anatomy_handlers.render_anatomy_latin_summary
get_bone_material_keyboard = anatomy_handlers.get_bone_material_keyboard
get_bone_material_text = anatomy_handlers.get_bone_material_text
get_anatomy_material_keyboard = anatomy_handlers.get_anatomy_material_keyboard
get_anatomy_material_text = anatomy_handlers.get_anatomy_material_text
get_anatomy_material_list_keyboard = anatomy_handlers.get_anatomy_material_list_keyboard
start_anatomy_flash_session = anatomy_handlers.start_anatomy_flash_session
get_anatomy_flash_question_keyboard = anatomy_handlers.get_anatomy_flash_question_keyboard
get_anatomy_flash_answer_keyboard = anatomy_handlers.get_anatomy_flash_answer_keyboard
get_anatomy_flash_summary_keyboard = anatomy_handlers.get_anatomy_flash_summary_keyboard
render_anatomy_flash_question = anatomy_handlers.render_anatomy_flash_question
render_anatomy_flash_answer = anatomy_handlers.render_anatomy_flash_answer
render_anatomy_flash_summary = anatomy_handlers.render_anatomy_flash_summary
get_anatomy_all_pairs = anatomy_handlers.get_anatomy_all_pairs
start_anatomy_match_session = anatomy_handlers.start_anatomy_match_session
get_anatomy_match_keyboard = anatomy_handlers.get_anatomy_match_keyboard
render_anatomy_match_question = anatomy_handlers.render_anatomy_match_question
render_anatomy_match_summary = anatomy_handlers.render_anatomy_match_summary
get_anatomy_mnemonics_keyboard = anatomy_handlers.get_anatomy_mnemonics_keyboard
get_anatomy_mnemonic_text = anatomy_handlers.get_anatomy_mnemonic_text
get_bone_mnemonics_keyboard = anatomy_handlers.get_bone_mnemonics_keyboard
get_bone_mnemonic_text = anatomy_handlers.get_bone_mnemonic_text
get_anatomy_root_keyboard = anatomy_handlers.get_anatomy_root_keyboard
get_anatomy_maintenance_text = anatomy_handlers.get_anatomy_maintenance_text
get_anatomy_maintenance_keyboard = anatomy_handlers.get_anatomy_maintenance_keyboard
cb_anatomy_root = anatomy_handlers.cb_anatomy_root
cb_anatomy_menu = anatomy_handlers.cb_anatomy_menu
get_anatomy_video_text = anatomy_handlers.get_anatomy_video_text
cb_anatomy_section = anatomy_handlers.cb_anatomy_section
cb_anatomy_section_video = anatomy_handlers.cb_anatomy_section_video
cb_anatomy_topic = anatomy_handlers.cb_anatomy_topic
cb_anatomy_topic_video = anatomy_handlers.cb_anatomy_topic_video
cb_anatomy_bones = anatomy_handlers.cb_anatomy_bones
cb_anatomy_bone_hub = anatomy_handlers.cb_anatomy_bone_hub
cb_anatomy_bone_material = anatomy_handlers.cb_anatomy_bone_material
cb_anatomy_bone_slides = anatomy_handlers.cb_anatomy_bone_slides
cb_anatomy_bone_atlas = anatomy_handlers.cb_anatomy_bone_atlas
cb_anatomy_atlas = anatomy_handlers.cb_anatomy_atlas
cb_anatomy_bone_flash_start = anatomy_handlers.cb_anatomy_bone_flash_start
cb_anatomy_bone_match_start = anatomy_handlers.cb_anatomy_bone_match_start
cb_anatomy_bone_latin_start = anatomy_handlers.cb_anatomy_bone_latin_start
cb_anatomy_bone_mnemonics = anatomy_handlers.cb_anatomy_bone_mnemonics
cb_anatomy_material_list = anatomy_handlers.cb_anatomy_material_list
cb_anatomy_material = anatomy_handlers.cb_anatomy_material
cb_anatomy_flash_start = anatomy_handlers.cb_anatomy_flash_start
cb_anatomy_flash_show_answer = anatomy_handlers.cb_anatomy_flash_show_answer
cb_anatomy_flash_answer = anatomy_handlers.cb_anatomy_flash_answer
cb_anatomy_flash_stop = anatomy_handlers.cb_anatomy_flash_stop
cb_anatomy_match_start = anatomy_handlers.cb_anatomy_match_start
cb_anatomy_match_answer = anatomy_handlers.cb_anatomy_match_answer
cb_anatomy_match_stop = anatomy_handlers.cb_anatomy_match_stop
cb_anatomy_latin_all_start = anatomy_handlers.cb_anatomy_latin_all_start
cb_anatomy_latin_leaderboard = anatomy_handlers.cb_anatomy_latin_leaderboard
cb_anatomy_latin_start = anatomy_handlers.cb_anatomy_latin_start
cb_anatomy_latin_answer = anatomy_handlers.cb_anatomy_latin_answer
cb_anatomy_latin_stop = anatomy_handlers.cb_anatomy_latin_stop
cb_anatomy_mnemonics = anatomy_handlers.cb_anatomy_mnemonics
cb_anatomy_picture = anatomy_handlers.cb_anatomy_picture
get_anatomy_exam_menu_keyboard = anatomy_handlers.get_anatomy_exam_menu_keyboard
cb_anatomy_exam_menu = anatomy_handlers.cb_anatomy_exam_menu
get_anatomy_exam_practice_section = anatomy_handlers.get_anatomy_exam_practice_section
get_anatomy_exam_practice_section_keyboard = anatomy_handlers.get_anatomy_exam_practice_section_keyboard
cb_anatomy_exam_practice = anatomy_handlers.cb_anatomy_exam_practice
get_anatomy_exam_practice_question_list_keyboard = anatomy_handlers.get_anatomy_exam_practice_question_list_keyboard
cb_anatomy_exam_practice_section = anatomy_handlers.cb_anatomy_exam_practice_section
get_anatomy_exam_practice_question_text = anatomy_handlers.get_anatomy_exam_practice_question_text
get_anatomy_exam_practice_question_keyboard = anatomy_handlers.get_anatomy_exam_practice_question_keyboard
cb_anatomy_exam_practice_question = anatomy_handlers.cb_anatomy_exam_practice_question
get_anatomy_exam_theory_section = anatomy_handlers.get_anatomy_exam_theory_section
get_anatomy_exam_theory_section_keyboard = anatomy_handlers.get_anatomy_exam_theory_section_keyboard
cb_anatomy_exam_theory = anatomy_handlers.cb_anatomy_exam_theory
get_anatomy_exam_theory_question_list_keyboard = anatomy_handlers.get_anatomy_exam_theory_question_list_keyboard
cb_anatomy_exam_theory_section = anatomy_handlers.cb_anatomy_exam_theory_section
get_anatomy_exam_theory_question_text = anatomy_handlers.get_anatomy_exam_theory_question_text
get_anatomy_exam_theory_question_keyboard = anatomy_handlers.get_anatomy_exam_theory_question_keyboard
cb_anatomy_exam_theory_question = anatomy_handlers.cb_anatomy_exam_theory_question
ANATOMY_EXAM_TEST_SESSIONS = anatomy_handlers.ANATOMY_EXAM_TEST_SESSIONS
ANATOMY_EXAM_TEST_MISTAKES = anatomy_handlers.ANATOMY_EXAM_TEST_MISTAKES
ANATOMY_EXAM_TEST_OPTION_LETTERS = anatomy_handlers.ANATOMY_EXAM_TEST_OPTION_LETTERS
ANATOMY_EXAM_FLASH_SIZE = anatomy_handlers.ANATOMY_EXAM_FLASH_SIZE
ANATOMY_EXAM_TEST_ALL_QUESTIONS = anatomy_handlers.ANATOMY_EXAM_TEST_ALL_QUESTIONS
get_anatomy_exam_test_part = anatomy_handlers.get_anatomy_exam_test_part
get_anatomy_exam_test_mode = anatomy_handlers.get_anatomy_exam_test_mode
set_anatomy_exam_test_mode = anatomy_handlers.set_anatomy_exam_test_mode
record_anatomy_exam_test_score = anatomy_handlers.record_anatomy_exam_test_score
get_anatomy_exam_test_leaderboard_text = anatomy_handlers.get_anatomy_exam_test_leaderboard_text
get_anatomy_exam_test_leaderboard_keyboard = anatomy_handlers.get_anatomy_exam_test_leaderboard_keyboard
cb_anatomy_exam_test_leaderboard = anatomy_handlers.cb_anatomy_exam_test_leaderboard
record_anatomy_exam_flash_score = anatomy_handlers.record_anatomy_exam_flash_score
get_anatomy_exam_flash_leaderboard_text = anatomy_handlers.get_anatomy_exam_flash_leaderboard_text
get_anatomy_exam_flash_leaderboard_keyboard = anatomy_handlers.get_anatomy_exam_flash_leaderboard_keyboard
cb_anatomy_exam_flash_leaderboard = anatomy_handlers.cb_anatomy_exam_flash_leaderboard
get_anatomy_exam_test_menu_keyboard = anatomy_handlers.get_anatomy_exam_test_menu_keyboard
render_anatomy_exam_test_menu = anatomy_handlers.render_anatomy_exam_test_menu
cb_anatomy_exam_test_menu = anatomy_handlers.cb_anatomy_exam_test_menu
cb_anatomy_exam_test_mode_toggle = anatomy_handlers.cb_anatomy_exam_test_mode_toggle
start_anatomy_exam_test_session = anatomy_handlers.start_anatomy_exam_test_session
start_anatomy_exam_flash_session = anatomy_handlers.start_anatomy_exam_flash_session
get_anatomy_exam_test_keyboard = anatomy_handlers.get_anatomy_exam_test_keyboard
render_anatomy_exam_test_question = anatomy_handlers.render_anatomy_exam_test_question
get_anatomy_exam_test_mistake_text = anatomy_handlers.get_anatomy_exam_test_mistake_text
get_anatomy_exam_test_mistake_keyboard = anatomy_handlers.get_anatomy_exam_test_mistake_keyboard
render_anatomy_exam_test_summary = anatomy_handlers.render_anatomy_exam_test_summary
cb_anatomy_exam_test_start = anatomy_handlers.cb_anatomy_exam_test_start
cb_anatomy_exam_test_flash_start = anatomy_handlers.cb_anatomy_exam_test_flash_start
cb_anatomy_exam_test_answer = anatomy_handlers.cb_anatomy_exam_test_answer
cb_anatomy_exam_test_stop = anatomy_handlers.cb_anatomy_exam_test_stop
cb_anatomy_exam_test_mistakes = anatomy_handlers.cb_anatomy_exam_test_mistakes

# ==================== ГИСТОЛОГИЯ ====================
# Хендлеры и вся логика раздела вынесены в handlers/histology.py (свой Router) — здесь только
# регистрация роутера на dp и реэкспорт имён, на которые ссылается остальной код файла (главное
# меню, админ-панель) и тесты, обращающиеся к ним как tb.<имя>. Сам импорт стоит здесь (в самом
# конце файла, как и раньше стояла вся секция), чтобы handlers/histology.py при своём импорте
# уже видел все нужные ему имена (stats, save_stats, DIVIDER, REFERRAL_* и т.д.) определёнными в
# этом модуле.
from handlers import histology as histology_handlers  # noqa: E402 — deliberately late, see above

dp.include_router(histology_handlers.router)

HISTOLOGY_PUBLIC = histology_handlers.HISTOLOGY_PUBLIC
HISTOLOGY_PROMO_SECONDS = histology_handlers.HISTOLOGY_PROMO_SECONDS
HISTOLOGY_WARNING_THRESHOLD = histology_handlers.HISTOLOGY_WARNING_THRESHOLD
HISTOLOGY_WARNING_COOLDOWN_SECONDS = histology_handlers.HISTOLOGY_WARNING_COOLDOWN_SECONDS
HISTOLOGY_GUESS_SESSION_SIZE = histology_handlers.HISTOLOGY_GUESS_SESSION_SIZE
HISTOLOGY_GUESS_SESSIONS = histology_handlers.HISTOLOGY_GUESS_SESSIONS
get_histology_temp_expiry = histology_handlers.get_histology_temp_expiry
has_histology_temp_access = histology_handlers.has_histology_temp_access
histology_permanently_unlocked = histology_handlers.histology_permanently_unlocked
histology_access_ok = histology_handlers.histology_access_ok
histology_gate_ok = histology_handlers.histology_gate_ok
get_histology_specimen = histology_handlers.get_histology_specimen
get_histology_locked_text = histology_handlers.get_histology_locked_text
get_histology_locked_keyboard = histology_handlers.get_histology_locked_keyboard
announce_histology_promo_start = histology_handlers.announce_histology_promo_start
get_histology_menu_keyboard = histology_handlers.get_histology_menu_keyboard
get_histology_topic_text = histology_handlers.get_histology_topic_text
get_histology_topic_keyboard = histology_handlers.get_histology_topic_keyboard
get_histology_specimen_text = histology_handlers.get_histology_specimen_text
get_histology_specimen_keyboard = histology_handlers.get_histology_specimen_keyboard
get_histology_image_keyboard = histology_handlers.get_histology_image_keyboard
render_histology_image = histology_handlers.render_histology_image
get_histology_guess_pool = histology_handlers.get_histology_guess_pool
start_histology_guess_session = histology_handlers.start_histology_guess_session
get_histology_guess_question_keyboard = histology_handlers.get_histology_guess_question_keyboard
get_histology_guess_answer_keyboard = histology_handlers.get_histology_guess_answer_keyboard
get_histology_guess_summary_keyboard = histology_handlers.get_histology_guess_summary_keyboard
render_histology_guess_question = histology_handlers.render_histology_guess_question
render_histology_guess_answer = histology_handlers.render_histology_guess_answer
render_histology_guess_summary = histology_handlers.render_histology_guess_summary
cb_histology_menu = histology_handlers.cb_histology_menu
cb_histology_topic = histology_handlers.cb_histology_topic
cb_histology_specimen = histology_handlers.cb_histology_specimen
cb_histology_img = histology_handlers.cb_histology_img
cb_histology_guess_start = histology_handlers.cb_histology_guess_start
cb_histology_guess_show_answer = histology_handlers.cb_histology_guess_show_answer
cb_histology_guess_answer = histology_handlers.cb_histology_guess_answer
cb_histology_guess_stop = histology_handlers.cb_histology_guess_stop

# ==================== ЗАПУСК ====================
async def setup_bot_commands() -> None:
    default_commands = [
        BotCommand(command="start", description="Начать работу с ботом"),
        BotCommand(command="random", description="Получить случайный билет"),
        BotCommand(command="help", description="Помощь и инструкция"),
    ]
    await bot.set_my_commands(default_commands, scope=BotCommandScopeDefault())

    admin_commands = default_commands + [
        BotCommand(command="admin", description="Админ-панель"),
    ]
    for admin_id in ADMIN_IDS:
        try:
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception:
            logger.exception("Не удалось установить админ-команды для %s", admin_id)

async def main():
    logger.info("Бот запускается...")
    logger.info("Загружена статистика: %d пользователей", len(stats["total_users"]))
    await setup_bot_commands()
    resume_battle_timer_if_needed()
    try:
        await dp.start_polling(bot)
    finally:
        _stats_executor.shutdown(wait=True)

if __name__ == "__main__":
    asyncio.run(main())
