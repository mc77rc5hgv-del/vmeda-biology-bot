import asyncio
import copy
import html
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
    Message, CallbackQuery, InlineKeyboardButton, FSInputFile, Update,
    BotCommand, BotCommandScopeDefault, BotCommandScopeChat, LabeledPrice,
)
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from aiogram.dispatcher.event.bases import SkipHandler

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

with open("chemistry_tasks.json", "r", encoding="utf-8") as f:
    CHEMISTRY_TASKS = json.load(f)["topics"]

with open("physics_tasks.json", "r", encoding="utf-8") as f:
    PHYSICS_TASKS = json.load(f)["topics"]

with open("physics_test_tickets.json", "r", encoding="utf-8") as f:
    PHYSICS_TEST_TICKETS = json.load(f)["tickets"]

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
            data.setdefault("referral_battle", None)
            data.setdefault("donations_stars_total", 0)
            data.setdefault("donations_stars_count", 0)
            data.setdefault("donor_stars", {})
            data.setdefault("donor_rubles", {})
            data.setdefault("donor_hide_name", {})
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
        "referral_battle": None,
        "donations_stars_total": 0,
        "donations_stars_count": 0,
        "donor_stars": {},
        "donor_rubles": {},
        "donor_hide_name": {},
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
REFERRAL_WARNING_THRESHOLD = 3  # столько предупреждений даём, прежде чем закрыть доступ
REFERRAL_WARNING_COOLDOWN_SECONDS = 4 * 60 * 60  # не чаще одного предупреждения раз в 4 часа

def get_referral_link(user_id: int) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"

def get_referral_count(user_id: int) -> int:
    return len(stats["referrals"].get(str(user_id), []))

def has_free_access(user_id: int) -> bool:
    return (
        is_admin(user_id)
        or get_referral_count(user_id) > 0
        or user_id in stats["manual_access_granted"]
    )

def get_referral_status_text(user_id: int) -> str:
    count = get_referral_count(user_id)
    link = get_referral_link(user_id)
    if count > 0 or user_id in stats["manual_access_granted"]:
        extra = f"Приглашено друзей: <b>{count}</b>\n" if count > 0 else ""
        return (
            f"👥 <b>Твои приглашения</b>\n{DIVIDER}\n\n"
            f"{extra}"
            "Доступ ко всем разделам бота открыт. Спасибо! 🎉\n\n"
            f"Твоя ссылка (можно приглашать ещё):\n{link}"
        )
    warn_count = stats["referral_warnings"].get(str(user_id), {}).get("count", 0)
    remaining = max(REFERRAL_WARNING_THRESHOLD - warn_count, 0)
    return (
        f"👥 <b>Пригласи друга</b>\n{DIVIDER}\n\n"
        "Отправь эту ссылку другу — как только он нажмёт /start, "
        "у тебя откроется полный доступ ко всем разделам бота:\n\n"
        f"{link}\n\n"
        f"Осталось бесплатных заходов без реферала: <b>{remaining}</b>"
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
BATTLE_DURATION_SECONDS = 24 * 60 * 60
BATTLE_PRIZE_TEXT = 'подписку на ГОД в <a href="https://t.me/Helperchat_bot">Helperchat_bot</a>'
BATTLE_CHANNEL_POSTING_NOTICE = "📢 <b>ПОСТИНГ В TELEGRAM-КАНАЛЫ РАЗРЕШЁН 🤝</b>"

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

def get_battle_leaderboard(limit: int = 10):
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
    return gained[:limit]

def format_time_left(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f"{h}ч {m}мин"

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
        if battle and battle.get("results"):
            medals_lines = []
            for i, (uid_str, diff) in enumerate(battle["results"]):
                name = stats["user_names"].get(uid_str, f"Пользователь {uid_str}")
                icon = RANK_MEDALS[i] if i < 3 else f"{i+1}."
                medals_lines.append(f"{icon} {name} — <b>{diff}</b>")
            results_block = "\n".join(medals_lines)
            return (
                f"⚔️ <b>Битва рефералов</b>\n{DIVIDER}\n\n"
                "Сейчас битва не идёт. Результаты последней битвы:\n\n"
                f"{results_block}\n\n"
                "Следи за объявлениями — как только стартует новая битва, "
                f"у тебя будет 24 часа, чтобы побороться за {BATTLE_PRIZE_TEXT}!"
            )
        return (
            f"⚔️ <b>Битва рефералов</b>\n{DIVIDER}\n\n"
            "Сейчас битва не идёт. Следи за объявлениями — как только стартует новая, "
            f"у тебя будет 24 часа, чтобы побороться за {BATTLE_PRIZE_TEXT}!"
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
        f"🎁 Топ-3 получат {BATTLE_PRIZE_TEXT}",
        f"🙋 Твой результат за битву: <b>{my_gained}</b>",
        "",
    ]
    if leaderboard:
        lines.append("<b>Текущий рейтинг битвы:</b>")
        for i, (uid, diff) in enumerate(leaderboard):
            icon = RANK_MEDALS[i] if i < 3 else f"{i+1}."
            name = stats["user_names"].get(uid, f"Пользователь {uid}")
            you = " 👈 ты" if uid == uid_str else ""
            lines.append(f"{icon} {name} — <b>{diff}</b>{you}")
    else:
        lines.append("Пока никто не пригласил друзей в рамках битвы — стань первым!")
    lines.append("")
    lines.append(f"Твоя ссылка:\n{get_referral_link(user_id)}")
    return "\n".join(lines)

async def _broadcast(text: str, keyboard=None) -> None:
    for user_id in list(stats["total_users"]):
        try:
            await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)
        except Exception:
            logger.exception("Не удалось отправить рассылку пользователю %s", user_id)
        await asyncio.sleep(0.05)

async def announce_battle_start() -> None:
    builder = InlineKeyboardBuilder()
    builder.button(text="⚔️ Битва рефералов", callback_data="referral_battle")
    text = (
        "⚔️🔥 <b>СТАРТУЕТ БИТВА РЕФЕРАЛОВ!</b> 🔥⚔️\n"
        f"{DIVIDER}\n\n"
        "У тебя есть <b>24 часа</b>, чтобы пригласить в бота как можно больше друзей!\n\n"
        f"🏆 <b>Топ-3</b> по числу приглашённых за это время получат {BATTLE_PRIZE_TEXT}!\n\n"
        "Считаются только друзья, приглашённые с этого момента.\n"
        "Следи за живым рейтингом на кнопке «⚔️ Битва рефералов» в главном меню.\n\n"
        f"{BATTLE_CHANNEL_POSTING_NOTICE}\n\n"
        "Погнали! 🚀"
    )
    await _broadcast(text, builder.as_markup())

async def resolve_referral_battle() -> None:
    battle = stats.get("referral_battle")
    if not battle or not battle.get("active"):
        return
    battle["active"] = False
    top3 = get_battle_leaderboard(limit=3)
    battle["results"] = top3
    save_stats()

    if top3:
        lines = [f"🏁 <b>Битва рефералов завершена!</b>\n{DIVIDER}\n", "Победители:"]
        for i, (uid_str, diff) in enumerate(top3):
            name = stats["user_names"].get(uid_str, f"Пользователь {uid_str}")
            lines.append(f"{RANK_MEDALS[i]} {name} — <b>{diff}</b> приглашённых")
        lines.append("")
        lines.append(f"🎁 Приз: {BATTLE_PRIZE_TEXT}")
        lines.append("Администратор свяжется с победителями лично 🤝")
        result_text = "\n".join(lines)
    else:
        result_text = (
            f"🏁 <b>Битва рефералов завершена!</b>\n{DIVIDER}\n\n"
            "За время битвы никто не пригласил новых друзей — приз не разыгран в этот раз."
        )
    await _broadcast(result_text)

    if top3:
        admin_lines = ["🏁 <b>Битва рефералов завершена.</b> Победители (для выдачи приза):"]
        for i, (uid_str, diff) in enumerate(top3):
            username = stats["user_username"].get(uid_str)
            handle = f"@{username}" if username else "(нет username)"
            admin_lines.append(f"{RANK_MEDALS[i]} ID <code>{uid_str}</code> {handle} — {diff} рефералов")
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
    new_name = user.full_name or f"Пользователь {user.id}"
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
    if event.callback_query and (
        (event.callback_query.data or "") in SUPPORT_GATE_EXEMPT_CALLBACKS
        or (event.callback_query.data or "").startswith(SUPPORT_GATE_EXEMPT_PREFIXES)
    ):
        return await handler(event, data)

    if has_free_access(user.id):
        return await handler(event, data)

    user_id_str = str(user.id)
    entry = stats["referral_warnings"].get(user_id_str, {"count": 0, "last_warn_at": 0})

    if entry["count"] >= REFERRAL_WARNING_THRESHOLD:
        block_text = (
            "🚨❗️ <b>ДОСТУП ЗАКРЫТ!</b> ❗️🚨\n\n"
            "Чтобы продолжить пользоваться ботом бесплатно — <b>пригласи ОДНОГО друга</b>! "
            "Это займёт меньше минуты! ⏱️\n\n"
            f"{get_referral_status_text(user.id)}\n\n"
            "⚡️ Как только друг нажмёт /start по этой ссылке — бот <b>сразу</b> станет доступен!"
        )
        try:
            if event.callback_query:
                await event.callback_query.answer("🚨 Доступ закрыт — пригласи друга! ‼️", show_alert=True)
                await event.callback_query.message.answer(block_text, parse_mode="HTML")
            elif event.message:
                await event.message.answer(block_text, parse_mode="HTML")
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
            "⚠️❗️ <b>ВНИМАНИЕ! Пригласи друга!</b> ❗️⚠️\n\n"
            f"{get_referral_status_text(user.id)}"
            if remaining > 0 else
            "🚨‼️ <b>ПОСЛЕДНЕЕ ПРЕДУПРЕЖДЕНИЕ!</b> ‼️🚨\n\n"
            "В следующий раз доступ будет <b>полностью закрыт</b>, пока не пригласишь друга!\n\n"
            f"{get_referral_status_text(user.id)}"
        )
        try:
            if event.callback_query:
                await event.callback_query.message.answer(warn_text, parse_mode="HTML")
            elif event.message:
                await event.message.answer(warn_text, parse_mode="HTML")
        except Exception:
            logger.exception("Не удалось отправить предупреждение о реферале пользователю %s", user.id)

    return await handler(event, data)

# ==================== ПОДДЕРЖКА АВТОРА ====================
DONATION_PENDING: dict[int, dict] = {}
STARS_MIN, STARS_MAX = 1, 2500
RUBLES_MIN, RUBLES_MAX = 10, 1_000_000
STARS_PRESETS = [25, 50, 100, 250, 500]
RUBLES_PRESETS = [100, 300, 500, 1000, 2000]
HELPER_ACCOUNT_URL = "https://t.me/vmeda_helper"
SUPPORT_GATE_EXEMPT_CALLBACKS = {
    "support_menu", "donate_stars_menu", "donate_stars_custom",
    "donate_rubles_menu", "donate_rubles_custom", "donors_leaderboard",
    "toggle_donor_visibility",
}
SUPPORT_GATE_EXEMPT_PREFIXES = (
    "donate_stars_amount:", "donate_rubles_amount:",
    "donate_stars_confirm:", "donate_rubles_confirm:",
)

def get_support_text() -> str:
    return (
        f"😇💰 <b>Поддержка автора</b>\n{DIVIDER}\n\n"
        "Бот полностью бесплатный, без рекламы и платных подписок.\n\n"
        "На разработку и организацию бота (хостинг, домен, работа над контентом) "
        "потрачено уже около <b>5000₽</b>, а получено с бота — <b>0₽</b>.\n\n"
        "Если бот тебе помогает — буду очень благодарен любой поддержке! "
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

async def is_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
    except Exception:
        return False

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

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
    builder.button(text="👥 Пригласить друзей", callback_data="referral_info")
    builder.button(text="🏆 Рейтинг", callback_data="referral_leaderboard")
    battle_label = "⚔️ Битва рефералов 🔥" if is_battle_active() else "⚔️ Битва рефералов"
    builder.button(text=battle_label, callback_data="referral_battle")
    builder.button(text="😇 Поддержать автора 💰", callback_data="support_menu")
    builder.adjust(1)
    return builder.as_markup()

def get_referral_back_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
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
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()

def get_physics_tickets_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Тестовые билеты", callback_data="physics_test_tickets")
    builder.button(text="📖 Билеты теоретической части", callback_data="physics_theory_tickets")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu_physics"))
    return builder.as_markup()

def get_physics_test_tickets_keyboard():
    builder = InlineKeyboardBuilder()
    for num in sorted(PHYSICS_TEST_TICKETS.keys(), key=int):
        builder.button(text=f"📄 {PHYSICS_TEST_TICKETS[num]['title']}", callback_data=f"phys_test_ticket:{num}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="physics_tickets"))
    return builder.as_markup()

def get_physics_test_ticket_back_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 К списку билетов", callback_data="physics_test_tickets"))
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

# ==================== ОБРАБОТЧИКИ ====================
@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    is_new_user = user_id not in stats["total_users"]
    stats["total_users"].add(user_id)
    stats["start_count"] += 1
    save_stats()

    payload = message.text.split(maxsplit=1)
    if len(payload) > 1 and payload[1].startswith("ref_"):
        referrer_id_str = payload[1][len("ref_"):]
        if referrer_id_str.isdigit():
            await register_referral(int(referrer_id_str), user_id)

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
ADMIN_USERLIST_PAGE_SIZE = 25

def get_admin_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="👥 Список пользователей", callback_data="admin_userlist:0")
    builder.button(text="🔓 Дать доступ по username", callback_data="admin_grant_prompt")
    builder.button(text="🚫 Отозвать доступ по username", callback_data="admin_revoke_prompt")
    builder.button(text="✉️ Написать пользователю", callback_data="admin_dm_prompt")
    builder.button(text="⚔️ Битва рефералов", callback_data="admin_battle_menu")
    builder.button(text="💰 Записать донат рублями", callback_data="admin_donation_prompt")
    builder.adjust(1)
    return builder.as_markup()

def get_admin_battle_keyboard():
    builder = InlineKeyboardBuilder()
    if is_battle_active():
        builder.button(text="🔄 Обновить", callback_data="admin_battle_menu")
        builder.button(text="🛑 Завершить досрочно", callback_data="admin_battle_end_confirm")
    else:
        builder.button(text="🚀 Начать битву рефералов (24ч)", callback_data="admin_battle_start_confirm")
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
                icon = RANK_MEDALS[i] if i < 3 else f"{i+1}."
                name = stats["user_names"].get(uid, f"Пользователь {uid}")
                lines.append(f"{icon} {name} — <b>{diff}</b>")
        else:
            lines.append("Пока никто не пригласил друзей в рамках битвы.")
        return "\n".join(lines)
    return (
        f"⚔️ <b>Битва рефералов</b>\n{DIVIDER}\n\n"
        "Сейчас битва не идёт.\n\n"
        "Запусти битву на 24 часа — топ-3 пользователя по числу приглашённых друзей за это время "
        f"получат {BATTLE_PRIZE_TEXT}.\n\n"
        "Всем пользователям бота придёт рассылка с объявлением о старте и правилах."
    )

def get_admin_back_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 В админ-панель", callback_data="admin_panel"))
    return builder.as_markup()

def resolve_user_by_username(raw: str):
    username = raw.strip().lstrip("@").lower()
    return username, stats["usernames"].get(username)

def format_user_line(user_id: int) -> str:
    uid_str = str(user_id)
    username = stats["user_username"].get(uid_str)
    handle = f"@{username}" if username else "(без username)"
    name = stats["user_names"].get(uid_str, "—")
    refs = len(stats["referrals"].get(uid_str, []))
    granted = " 🔓" if user_id in stats["manual_access_granted"] else ""
    return f"<code>{user_id}</code> — {handle} — {name} — реф: {refs}{granted}"

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
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        f"🛠 <b>Админ-панель</b>\n{DIVIDER}\n\nВыбери действие:",
        parse_mode="HTML",
        reply_markup=get_admin_menu()
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

@dp.callback_query(F.data == "admin_battle_start_confirm")
async def cb_admin_battle_start_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, начать битву на 24ч", callback_data="admin_battle_start_go")
    builder.button(text="❌ Отмена", callback_data="admin_battle_menu")
    builder.adjust(1)
    await safe_edit_text(
        callback.message,
        "⚔️ <b>Подтверди запуск битвы рефералов</b>\n\n"
        "Битва продлится 24 часа, топ-3 по числу новых приглашённых получат "
        f"{BATTLE_PRIZE_TEXT}.\n\nВсем пользователям придёт рассылка с объявлением.",
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

@dp.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    total_referrals = sum(len(v) for v in stats["referrals"].values())
    text = (
        f"📊 <b>Статистика бота</b>\n{DIVIDER}\n\n"
        f"👥 Уникальных пользователей: <b>{len(stats['total_users'])}</b>\n"
        f"▶️ Запусков бота: <b>{stats['start_count']}</b>\n"
        f"❓ Вопросов просмотрено: <b>{sum(stats['question_opened'].values())}</b>\n"
        f"🎲 Случайных билетов открыто: <b>{stats['random_ticket_used']}</b>\n"
        f"🎲 Случайных вопросов открыто: <b>{stats['random_question_used']}</b>\n"
        f"📢 Рассылок отправлено: <b>{stats.get('broadcast_count', 0)}</b>\n"
        f"🔗 Всего рефералов: <b>{total_referrals}</b>\n"
        f"🔓 Ручных доступов выдано: <b>{len(stats['manual_access_granted'])}</b>\n"
        f"🪪 Известно username: <b>{len(stats['usernames'])}</b>"
    )
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=get_admin_back_keyboard())

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
        "🔓 <b>Выдать доступ по username</b>\n\nОтправь username пользователя (с @ или без), например: <code>@ivanov</code>",
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
        "🚫 <b>Отозвать ручной доступ по username</b>\n\nОтправь username пользователя (с @ или без)",
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
        "✉️ <b>Личное сообщение по username</b>\n\nОтправь username пользователя (с @ или без)",
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
        "Отправь username пользователя (с @ или без)",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@dp.message(F.text)
async def handle_admin_pending_action(message: Message):
    admin_id = message.from_user.id
    if not is_admin(admin_id) or admin_id not in ADMIN_PENDING:
        raise SkipHandler
    if message.text.startswith("/"):
        raise SkipHandler

    pending = ADMIN_PENDING[admin_id]
    action = pending["action"]

    if action in ("grant", "revoke", "dm_username", "record_donation_username"):
        username, target_id = resolve_user_by_username(message.text)
        if not target_id:
            await message.answer(
                f"⚠️ Пользователь @{username} не найден — он ещё не писал боту, либо сменил username.\n"
                "Попробуй ещё раз или вернись в /admin.",
                parse_mode="HTML"
            )
            return

        if action == "grant":
            if target_id not in stats["manual_access_granted"]:
                stats["manual_access_granted"].append(target_id)
                save_stats()
            del ADMIN_PENDING[admin_id]
            await message.answer(f"✅ Доступ выдан @{username} (ID {target_id}).", parse_mode="HTML")
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
                f"✅ Ручной доступ для @{username} (ID {target_id}) отозван.\n"
                "Если у пользователя уже есть свои рефералы, доступ всё равно останется открытым.",
                parse_mode="HTML"
            )

        elif action == "dm_username":
            ADMIN_PENDING[admin_id] = {"action": "dm_message", "target_id": target_id, "target_username": username}
            await message.answer(f"✅ Нашёл @{username} (ID {target_id}). Теперь отправь текст сообщения для него.", parse_mode="HTML")

        elif action == "record_donation_username":
            ADMIN_PENDING[admin_id] = {"action": "record_donation_amount", "target_id": target_id, "target_username": username}
            await message.answer(f"✅ Нашёл @{username} (ID {target_id}). Теперь пришли сумму в рублях (целое число).", parse_mode="HTML")
        return

    if action == "record_donation_amount":
        target_id = pending["target_id"]
        target_username = pending["target_username"]
        raw = message.text.strip().replace(" ", "")
        if not raw.isdigit() or int(raw) <= 0:
            await message.answer("⚠️ Введи, пожалуйста, положительное целое число рублей.")
            return
        amount = int(raw)
        del ADMIN_PENDING[admin_id]
        uid_str = str(target_id)
        stats["donor_rubles"][uid_str] = stats["donor_rubles"].get(uid_str, 0) + amount
        save_stats()
        await message.answer(f"✅ Записано пожертвование {amount}₽ от @{target_username}.", parse_mode="HTML")
        return

    if action == "dm_message":
        target_id = pending["target_id"]
        target_username = pending["target_username"]
        del ADMIN_PENDING[admin_id]
        try:
            await bot.send_message(
                target_id,
                f"✉️ <b>Личное сообщение от администрации</b>\n{DIVIDER}\n\n{message.html_text}",
                parse_mode="HTML"
            )
            await message.answer(f"✅ Сообщение отправлено @{target_username}.", parse_mode="HTML")
        except Exception:
            logger.exception("Не удалось отправить личное сообщение пользователю %s", target_id)
            await message.answer(f"⚠️ Не удалось отправить сообщение @{target_username} — возможно, он заблокировал бота.", parse_mode="HTML")
        return

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
        reply_markup=get_main_menu()
    )

@dp.callback_query(F.data == "referral_info")
async def cb_referral_info(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        get_referral_status_text(callback.from_user.id),
        parse_mode="HTML",
        reply_markup=get_referral_back_keyboard()
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

@dp.pre_checkout_query()
async def handle_pre_checkout(pre_checkout_query) -> None:
    await pre_checkout_query.answer(ok=True)

@dp.message(F.successful_payment)
async def handle_successful_payment(message: Message):
    payment = message.successful_payment
    stars = payment.total_amount
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
                f"⭐ <b>Новое пожертвование звёздами!</b>\n\n{stars} ⭐ от {user.full_name} (ID <code>{user.id}</code>)",
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

@dp.callback_query(F.data == "menu_chemistry")
async def cb_menu_chemistry(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        f"🧪 <b>Химия</b>\n{DIVIDER}\n\nВыбери раздел:",
        parse_mode="HTML",
        reply_markup=get_chemistry_menu()
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
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=builder.as_markup())

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
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=builder.as_markup())

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
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=builder.as_markup())

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
    await safe_edit_text(message, text, parse_mode="HTML", reply_markup=get_ticket_questions_keyboard(str(ticket_num)))

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
    await safe_edit_text(
        callback.message,
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
        await send_answer(callback.message, body, short_caption, q, get_question_answer_keyboard(q_num), edit=True)
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
    await send_answer(callback.message, body, short_caption, q, get_question_answer_keyboard(q_num), edit=True)

@dp.callback_query(F.data == "question_by_number")
async def cb_question_by_number(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        f"🔢 <b>Поиск вопроса по номеру</b>\n{DIVIDER}\n\nВведи номер вопроса (от 1 до 185):",
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "question_search")
async def cb_question_search(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        f"🔍 <b>Поиск по ключевым словам</b>\n{DIVIDER}\n\n"
        "Напиши слово или часть слова (например: <i>плазмодий</i>) — "
        "покажу все вопросы, где оно встречается, вместе с падежами и склонениями.",
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
        await send_answer(message, body, short_caption, q, get_question_answer_keyboard(q_num), edit=False)
    else:
        await message.answer("⚠️ Вопрос с таким номером не найден.")

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
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="physics_tickets"))
    await safe_edit_text(
        callback.message,
        f"📖 <b>Билеты теоретической части</b>\n{DIVIDER}\n\n🚧 Скоро будут добавлены!",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

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
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=get_physics_test_ticket_back_keyboard())

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
