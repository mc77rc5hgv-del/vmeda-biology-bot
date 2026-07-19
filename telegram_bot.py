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
ANATOMY_IMAGES_DIR = os.path.join(IMAGES_DIR, "anatomy")
HISTOLOGY_IMAGES_DIR = os.path.join(IMAGES_DIR, "histology")

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

with open("anatomy.json", "r", encoding="utf-8") as f:
    ANATOMY = json.load(f)

with open("histology.json", "r", encoding="utf-8") as f:
    HISTOLOGY = json.load(f)

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
            data.setdefault("temporary_access", {})
            data.setdefault("subscriptions", {})
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
        "temporary_access": {},
        "subscriptions": {},
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
REFERRAL_FULL_ACCESS_THRESHOLD = 2  # столько рефералов нужно, чтобы открыть доступ навсегда
REFERRAL_WARNING_THRESHOLD = 3  # столько предупреждений даём, прежде чем закрыть доступ
REFERRAL_WARNING_COOLDOWN_SECONDS = 4 * 60 * 60  # не чаще одного предупреждения раз в 4 часа
TEMP_ACCESS_GRANT_SECONDS = 7 * 24 * 60 * 60  # длительность временного восстановления доступа

def get_referral_link(user_id: int) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"

def get_referral_count(user_id: int) -> int:
    return len(stats["referrals"].get(str(user_id), []))

def get_temp_access_expiry(user_id: int) -> float:
    return stats["temporary_access"].get(str(user_id), 0)

def has_temp_access(user_id: int) -> bool:
    return time.time() < get_temp_access_expiry(user_id)

# ==================== ПЛАТНАЯ ПОДПИСКА ====================
# scope "gated" — только Биология/Физика/Химия (то, что вообще закрывает реферальный гейт).
# scope "all"  — то же плюс досрочный доступ к Анатомии/Гистологии и любым новым разделам,
# которые появятся, пока подписка активна (даже если раздел ещё не открыт всем через *_PUBLIC).
SUBSCRIPTION_TIERS = {
    1: {
        "title": "Месяц — Биология, Физика, Химия",
        "short": "1 месяц, 3 экзамена",
        "scope": "gated",
        "duration_days": 30,
        "price_rub": 79,
        "price_stars": 79,
        "emoji": "🔓",
        "benefits": [
            "Полный доступ к Биологии, Физике и Химии на 30 дней",
            "Не нужно ждать и звать друзей — доступ открывается сразу после оплаты",
            "Идеально, если экзамен уже скоро и нужно готовиться прямо сейчас",
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
        "benefits": [
            "Полный доступ к Биологии, Физике и Химии — один раз и навсегда",
            "🔬 Плюс ранний доступ к разделу Гистологии — она уже полностью готова: "
            "препараты именно с академии, все протоколы сверены преподавателями",
            "Дешевле, чем 3 месячные подписки, а действует бессрочно",
            "Больше никогда не думать о рефералах и ограничениях",
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
        "benefits": [
            "Доступ вообще ко всем разделам бота на целый год",
            "Плюс Анатомия и уже полностью готовая Гистология (препараты с академии, "
            "протоколы сверены преподавателями) — уже сейчас, до их открытия всем остальным",
            "Все новые разделы и предметы, которые добавятся в течение года — уже включены",
            "Меньше 2.5₽ в день за полную подготовку по всем предметам",
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
        "benefits": [
            "Доступ ко всем разделам бота на весь срок обучения в академии",
            "Анатомия и уже полностью готовая Гистология (препараты с академии, "
            "протоколы сверены преподавателями), а также все будущие разделы — сразу, без ожиданий",
            "Один платёж на все 6 лет учёбы — и больше никаких трат на подготовку",
            "Меньше 35₽ в месяц — дешевле, чем что угодно другое",
        ],
    },
}

def get_subscription(user_id: int) -> dict:
    return stats["subscriptions"].get(str(user_id))

def has_active_subscription(user_id: int) -> bool:
    sub = get_subscription(user_id)
    if not sub:
        return False
    expires = sub.get("expires")
    return expires is None or time.time() < expires

def has_subscription_scope_all(user_id: int) -> bool:
    sub = get_subscription(user_id)
    return bool(sub) and sub.get("scope") == "all" and has_active_subscription(user_id)

def has_subscription_histology_access(user_id: int) -> bool:
    sub = get_subscription(user_id)
    if not sub or not has_active_subscription(user_id):
        return False
    return sub.get("scope") == "all" or sub.get("early_histology", False)

def grant_subscription(user_id: int, tier: int, method: str, price: int) -> None:
    cfg = SUBSCRIPTION_TIERS[tier]
    expires = None if cfg["duration_days"] is None else time.time() + cfg["duration_days"] * 86400
    stats["subscriptions"][str(user_id)] = {
        "tier": tier,
        "scope": cfg["scope"],
        "early_histology": cfg.get("early_histology", False),
        "expires": expires,
        "purchased_at": time.time(),
        "method": method,
        "price": price,
    }
    save_stats()

def has_free_access(user_id: int) -> bool:
    return (
        is_admin(user_id)
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

def get_subscription_scope_label(sub: dict) -> str:
    if sub.get("scope") == "all":
        return "ко всем разделам бота"
    if sub.get("early_histology"):
        return "к Биологии, Физике, Химии и Гистологии"
    return "к Биологии, Физике и Химии"

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
            "приглашай друзей дальше и попади в топ-3!\n\n"
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
        "💎 Не хочешь ждать друзей? Открой доступ сразу оплатой — подписки от 79₽. "
        "Жми «💎 Открыть доступ без рефералов» ниже."
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
BATTLE_PRIZE_LABELS = [
    'полный и <b>вечный</b> доступ к <a href="https://t.me/VMEDA_examen_bot">VMEDA_examen_bot</a> '
    '+ подписка на <b>год</b> в <a href="https://t.me/Helperchat_bot">Helperchat_bot</a>',
    'полный доступ к <a href="https://t.me/VMEDA_examen_bot">VMEDA_examen_bot</a> на <b>год</b> '
    '+ подписка на <b>год</b> в <a href="https://t.me/Helperchat_bot">Helperchat_bot</a>',
    'полный доступ к <a href="https://t.me/VMEDA_examen_bot">VMEDA_examen_bot</a> на <b>год</b>',
]
BATTLE_CHANNEL_POSTING_NOTICE = "📢 <b>ПОСТИНГ В TELEGRAM-КАНАЛЫ РАЗРЕШЁН 🤝</b>"

def format_battle_prizes_block() -> str:
    return "\n".join(f"{RANK_MEDALS[i]} <b>{i + 1} место</b> — {BATTLE_PRIZE_LABELS[i]}" for i in range(3))

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
                "у тебя будет 24 часа, чтобы побороться за призы:\n\n"
                f"{format_battle_prizes_block()}"
            )
        return (
            f"⚔️ <b>Битва рефералов</b>\n{DIVIDER}\n\n"
            "Сейчас битва не идёт. Следи за объявлениями — как только стартует новая, "
            "у тебя будет 24 часа, чтобы побороться за призы:\n\n"
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
        "🎁 Призы для топ-3:",
        format_battle_prizes_block(),
        "",
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

async def _broadcast_to(user_ids, text: str, keyboard=None) -> None:
    for user_id in list(user_ids):
        try:
            await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)
        except Exception:
            logger.exception("Не удалось отправить рассылку пользователю %s", user_id)
        await asyncio.sleep(0.05)

async def _broadcast(text: str, keyboard=None) -> None:
    await _broadcast_to(stats["total_users"], text, keyboard)

async def announce_battle_start() -> None:
    builder = InlineKeyboardBuilder()
    builder.button(text="⚔️ Битва рефералов", callback_data="referral_battle")
    text = (
        "⚔️🔥 <b>СТАРТУЕТ БИТВА РЕФЕРАЛОВ!</b> 🔥⚔️\n"
        f"{DIVIDER}\n\n"
        "У тебя есть <b>24 часа</b>, чтобы пригласить в бота как можно больше друзей "
        "и забрать один из трёх эксклюзивных призов:\n\n"
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
        "🎁 Призы для топ-3:",
        format_battle_prizes_block(),
        "",
    ]
    if leaderboard:
        lines.append("<b>Текущий рейтинг битвы:</b>")
        for i, (uid, diff) in enumerate(leaderboard):
            icon = RANK_MEDALS[i] if i < 3 else f"{i+1}."
            name = stats["user_names"].get(uid, f"Пользователь {uid}")
            lines.append(f"{icon} {name} — <b>{diff}</b>")
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
            lines.append(f"🎁 {BATTLE_PRIZE_LABELS[i]}")
            lines.append("")
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

# Без нужного числа рефералов закрыты только 3 раздела — Биология, Физика, Химия.
# Всё остальное (админка, рефералы, битва, поддержка автора, анатомия) доступно всегда.
GATED_CALLBACKS = {
    # Биология
    "menu_biology", "menu_tickets", "menu_questions",
    "quiz_start", "quiz_show_answer", "quiz_know", "quiz_dont_know", "quiz_stop",
    "random_ticket", "question_random", "question_by_number", "question_search",
    # Физика
    "menu_physics", "physics_tickets", "physics_theory_tickets", "physics_test_tickets",
    "physics_test", "physics_tasks",
    # Химия
    "menu_chemistry", "chemistry_theory", "chemistry_theory_list",
    "chemistry_tasks", "chemistry_labs",
}
GATED_PREFIXES = (
    # Биология
    "ticket:", "ticket_q:", "qpage:", "q:",
    # Физика
    "phys_test_ticket:", "physics_page:", "physics_q:",
    "phystask_topic:", "phystask_formulas:", "phystask_list:", "phystask_show:",
    # Химия
    "chem_theory:", "chemtask_topic:", "chemtask_formulas:", "chemtask_list:", "chemtask_show:",
    "lab:", "lab_exp:", "lab_calc:",
)

def is_gated_callback(data: str) -> bool:
    return data in GATED_CALLBACKS or data.startswith(GATED_PREFIXES)

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
    if event.callback_query and not is_gated_callback(event.callback_query.data or ""):
        return await handler(event, data)

    if has_free_access(user.id):
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
def get_main_menu(user_id: int = None):
    builder = InlineKeyboardBuilder()
    builder.button(text="🧬 Биология", callback_data="menu_biology")
    builder.button(text="⚛️ Физика", callback_data="menu_physics")
    builder.button(text="🧪 Химия", callback_data="menu_chemistry")
    sub_all = user_id is not None and has_subscription_scope_all(user_id)
    sub_histology = user_id is not None and has_subscription_histology_access(user_id)
    if ANATOMY_PUBLIC or (user_id is not None and is_admin(user_id)) or sub_all:
        label = "🦴 Анатомия" + ("" if ANATOMY_PUBLIC else (" 💎" if sub_all else " (админ)"))
        builder.button(text=label, callback_data="anatomy_menu")
    if HISTOLOGY_PUBLIC or (user_id is not None and is_admin(user_id)) or sub_histology:
        label = "🔬 Гистология" + ("" if HISTOLOGY_PUBLIC else (" 💎" if sub_histology else " (админ)"))
        builder.button(text=label, callback_data="histology_menu")
    builder.button(text="👥 Пригласить друзей", callback_data="referral_info")
    builder.button(text="🏆 Рейтинг", callback_data="referral_leaderboard")
    battle_label = "⚔️ Битва рефералов 🔥" if is_battle_active() else "⚔️ Битва рефералов"
    builder.button(text=battle_label, callback_data="referral_battle")
    if user_id is None or not has_free_access(user_id):
        builder.button(text="💎 Подписка без рефералов", callback_data="subscription_menu")
    builder.button(text="😇 Поддержать автора 💰", callback_data="support_menu")
    builder.adjust(1)
    return builder.as_markup()

def get_referral_back_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💎 Открыть доступ без рефералов", callback_data="subscription_menu"))
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()

def get_referral_full_access_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="⚔️ Битва рефералов", callback_data="referral_battle")
    builder.button(text="🔙 Назад в меню", callback_data="back_to_main")
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
    builder.button(text="👥 Список пользователей", callback_data="admin_userlist:0")
    builder.button(text="🔓 Дать доступ по username", callback_data="admin_grant_prompt")
    builder.button(text="🚫 Отозвать доступ по username", callback_data="admin_revoke_prompt")
    builder.button(text="✉️ Написать пользователю", callback_data="admin_dm_prompt")
    builder.button(text="⚔️ Битва рефералов", callback_data="admin_battle_menu")
    builder.button(text="💰 Записать донат рублями", callback_data="admin_donation_prompt")
    builder.button(text="💎 Выдать подписку по username", callback_data="admin_subscription_prompt")
    builder.button(text="📣 Анонс раздела поддержки", callback_data="admin_announce_support_confirm")
    builder.button(text="🎁 Восстановить доступ исчерпавшим (7 дней)", callback_data="admin_restore_access_confirm")
    builder.button(text="📤 Опубликовать пост в канал", callback_data="admin_channel_post_prompt")
    builder.adjust(1)
    return builder.as_markup()

def get_admin_battle_keyboard():
    builder = InlineKeyboardBuilder()
    if is_battle_active():
        builder.button(text="🔄 Обновить", callback_data="admin_battle_menu")
        builder.button(text="📣 Разослать напоминание о битве", callback_data="admin_battle_remind_confirm")
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
        f"получат призы:\n\n{format_battle_prizes_block()}\n\n"
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
        "Битва продлится 24 часа, топ-3 по числу новых приглашённых получат призы:\n\n"
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

@dp.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    total_referrals = sum(len(v) for v in stats["referrals"].values())
    exhausted_free_uses = len(get_exhausted_users())
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
        f"🚫 Исчерпали бесплатные заходы без рефералов: <b>{exhausted_free_uses}</b>\n"
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

@dp.callback_query(F.data == "admin_subscription_prompt")
async def cb_admin_subscription_prompt(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    ADMIN_PENDING[callback.from_user.id] = {"action": "record_subscription_username"}
    await safe_edit_text(
        callback.message,
        "💎 <b>Выдать подписку по username</b>\n\n"
        "Для оплат рублями (перевод в чате с @vmeda_helper) подписку нужно включить вручную "
        "после подтверждения оплаты.\n\n"
        "Отправь username пользователя (с @ или без)",
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

    if action in ("grant", "revoke", "dm_username", "record_donation_username", "record_subscription_username"):
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

        elif action == "record_subscription_username":
            ADMIN_PENDING[admin_id] = {"action": "record_subscription_tier", "target_id": target_id, "target_username": username}
            tier_lines = "\n".join(
                f"{t} — {cfg['title']} ({cfg['price_rub']}₽)" for t, cfg in SUBSCRIPTION_TIERS.items()
            )
            await message.answer(
                f"✅ Нашёл @{username} (ID {target_id}). Теперь пришли номер тарифа:\n\n{tier_lines}",
                parse_mode="HTML"
            )
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

    if action == "record_subscription_tier":
        target_id = pending["target_id"]
        target_username = pending["target_username"]
        raw = message.text.strip()
        if not raw.isdigit() or int(raw) not in SUBSCRIPTION_TIERS:
            tier_lines = "\n".join(
                f"{t} — {cfg['title']}" for t, cfg in SUBSCRIPTION_TIERS.items()
            )
            await message.answer(f"⚠️ Введи номер тарифа из списка:\n\n{tier_lines}")
            return
        tier_id = int(raw)
        cfg = SUBSCRIPTION_TIERS[tier_id]
        del ADMIN_PENDING[admin_id]
        grant_subscription(target_id, tier_id, "rubles", cfg["price_rub"])
        sub = get_subscription(target_id)
        scope_label = "ко всем разделам бота" if cfg["scope"] == "all" else "к Биологии, Физике и Химии"
        await message.answer(
            f"✅ Подписка «{cfg['title']}» выдана @{target_username} (ID {target_id}).",
            parse_mode="HTML"
        )
        try:
            await bot.send_message(
                target_id,
                f"🎉 <b>Подписка «{cfg['title']}» активирована!</b>\n\n"
                f"Доступ {scope_label} открыт — {format_subscription_expiry(sub['expires'])}.\n"
                "Правило про рефералов для тебя больше не действует. Спасибо за поддержку! 🙏😇",
                parse_mode="HTML"
            )
        except Exception:
            logger.exception("Не удалось уведомить пользователя %s о выдаче подписки", target_id)
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
        reply_markup=get_main_menu(callback.from_user.id)
    )

@dp.callback_query(F.data == "referral_info")
async def cb_referral_info(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    keyboard = get_referral_full_access_keyboard() if has_free_access(user_id) else get_referral_back_keyboard()
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
        "и ограничений. Выбери вариант:\n"
    )
    for tier_id, cfg in SUBSCRIPTION_TIERS.items():
        lines.append(f"{cfg['emoji']} <b>{cfg['title']}</b> — {cfg['price_rub']}₽ / {cfg['price_stars']} ⭐")
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
    for tier_id, cfg in SUBSCRIPTION_TIERS.items():
        builder.button(
            text=f"{cfg['emoji']} {cfg['short']} — {cfg['price_rub']}₽/{cfg['price_stars']}⭐",
            callback_data=f"sub_tier:{tier_id}"
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()

def get_sub_tier_text(tier_id: int) -> str:
    cfg = SUBSCRIPTION_TIERS[tier_id]
    lines = [f"{cfg['emoji']} <b>{cfg['title']}</b>\n{DIVIDER}\n"]
    for b in cfg["benefits"]:
        lines.append(f"• {b}")
    lines.append(f"\nЦена: <b>{cfg['price_rub']}₽</b> или <b>{cfg['price_stars']} ⭐</b>")
    lines.append("\nВыбери способ оплаты:")
    return "\n".join(lines)

def get_sub_tier_keyboard(tier_id: int):
    cfg = SUBSCRIPTION_TIERS[tier_id]
    builder = InlineKeyboardBuilder()
    builder.button(text=f"⭐ Оплатить {cfg['price_stars']} звёзд", callback_data=f"buy_sub_stars:{tier_id}")
    builder.button(text=f"💵 Оплатить {cfg['price_rub']}₽", callback_data=f"buy_sub_rubles:{tier_id}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="subscription_menu"))
    return builder.as_markup()

def get_sub_rubles_message_text(tier_id: int) -> str:
    cfg = SUBSCRIPTION_TIERS[tier_id]
    return (
        f"💵 <b>Оплата подписки «{cfg['title']}» — {cfg['price_rub']}₽</b>\n{DIVIDER}\n\n"
        f'Нажми на кнопку ниже — откроется чат с <a href="{HELPER_ACCOUNT_URL}">@vmeda_helper</a>, '
        "сообщение с тарифом уже будет готово. Отправь его и переведи по присланным реквизитам — "
        "как только оплата подтвердится, подписка будет включена вручную.\n\n"
        "Спасибо, что поддерживаешь бота! 🙏"
    )

def get_sub_rubles_keyboard(tier_id: int):
    cfg = SUBSCRIPTION_TIERS[tier_id]
    template = (
        f"Привет! Хочу оформить подписку «{cfg['title']}» за {cfg['price_rub']}₽ в боте "
        "VMEDA_examen_bot. Подскажи, пожалуйста, реквизиты для перевода."
    )
    url = f"{HELPER_ACCOUNT_URL}?text={urllib.parse.quote(template)}"
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💸 Написать @vmeda_helper", url=url))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"sub_tier:{tier_id}"))
    return builder.as_markup()

async def send_subscription_stars_invoice(chat_id: int, tier_id: int) -> None:
    cfg = SUBSCRIPTION_TIERS[tier_id]
    await bot.send_invoice(
        chat_id=chat_id,
        title=f"Подписка: {cfg['title']}",
        description=f"VMEDA_examen_bot — подписка «{cfg['title']}». Доступ откроется сразу после оплаты.",
        payload=f"sub_stars_{tier_id}_{chat_id}_{int(time.time())}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=cfg["title"], amount=cfg["price_stars"])],
    )

def get_subscription_teaser_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💎 Открыть доступ без рефералов", callback_data="subscription_menu"))
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

@dp.callback_query(F.data.startswith("buy_sub_stars:"))
async def cb_buy_sub_stars(callback: CallbackQuery):
    tier_id = int(callback.data.split(":")[1])
    if tier_id not in SUBSCRIPTION_TIERS:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    await callback.answer()
    await send_subscription_stars_invoice(callback.from_user.id, tier_id)

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

@dp.pre_checkout_query()
async def handle_pre_checkout(pre_checkout_query) -> None:
    await pre_checkout_query.answer(ok=True)

@dp.message(F.successful_payment)
async def handle_successful_payment(message: Message):
    payment = message.successful_payment
    stars = payment.total_amount
    payload = payment.invoice_payload or ""

    if payload.startswith("sub_stars_"):
        tier_id = int(payload.split("_")[2])
        grant_subscription(message.from_user.id, tier_id, "stars", stars)
        cfg = SUBSCRIPTION_TIERS[tier_id]
        sub = get_subscription(message.from_user.id)
        scope_label = "ко всем разделам бота" if cfg["scope"] == "all" else "к Биологии, Физике и Химии"
        await message.answer(
            f"🎉 <b>Подписка «{cfg['title']}» активирована!</b>\n\n"
            f"Доступ {scope_label} открыт — {format_subscription_expiry(sub['expires'])}.\n"
            "Правило про рефералов для тебя больше не действует. Спасибо за поддержку! 🙏😇",
            parse_mode="HTML"
        )
        user = message.from_user
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"💎 <b>Новая подписка звёздами!</b>\n\n«{cfg['title']}» ({stars} ⭐) — "
                    f"{user.full_name} (ID <code>{user.id}</code>)",
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

# ==================== АНАТОМИЯ (В РАЗРАБОТКЕ, ПОКА ДОСТУПНО ТОЛЬКО АДМИНАМ) ====================
ANATOMY_PUBLIC = False  # когда раздел будет готов для всех — переключить на True

ANATOMY_FLASH_SESSION_SIZE = 10
ANATOMY_MATCH_SESSION_SIZE = 10

ANATOMY_FLASH_SESSIONS: dict[int, dict] = {}
ANATOMY_MATCH_SESSIONS: dict[int, dict] = {}

def anatomy_access_ok(user_id: int) -> bool:
    return ANATOMY_PUBLIC or is_admin(user_id) or has_subscription_scope_all(user_id)

def get_anatomy_topic_data(topic_key: str):
    for section in ANATOMY.values():
        topic = section.get("topics", {}).get(topic_key)
        if topic:
            return topic
    return None

def get_topic_section_key(topic_key: str) -> str:
    for section_key, section in ANATOMY.items():
        if topic_key in section.get("topics", {}):
            return section_key
    return next(iter(ANATOMY), "osteology")

def get_anatomy_menu_keyboard():
    builder = InlineKeyboardBuilder()
    for section_key, section in ANATOMY.items():
        builder.button(text=section.get("menu_title", section["title"]), callback_data=f"anatomy_section:{section_key}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()

def get_anatomy_section_keyboard(section_key: str):
    section = ANATOMY.get(section_key, {})
    builder = InlineKeyboardBuilder()
    for topic_key, topic in section.get("topics", {}).items():
        builder.button(text=topic.get("menu_title", topic["title"]), callback_data=f"anatomy_topic:{topic_key}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="anatomy_menu"))
    return builder.as_markup()

def get_anatomy_topic_keyboard(topic_key: str):
    topic = get_anatomy_topic_data(topic_key)
    builder = InlineKeyboardBuilder()
    if topic and topic.get("bones_list"):
        builder.button(text="🦴 Кости черепа (по каждой кости)", callback_data=f"anatomy_bones:{topic_key}")
    builder.button(text="📖 Весь материал подряд", callback_data=f"anatomy_material:{topic_key}:0")
    builder.button(text="🎴 Флэш-карточки (все)", callback_data=f"anatomy_flash_start:{topic_key}")
    builder.button(text="🔗 Сопоставление (все)", callback_data=f"anatomy_match_start:{topic_key}")
    builder.button(text="🧠 Мнемоники (все)", callback_data=f"anatomy_mnemonics:{topic_key}:0")
    builder.button(text="🖼 Найди на картинке", callback_data=f"anatomy_picture:{topic_key}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"anatomy_section:{get_topic_section_key(topic_key)}"))
    return builder.as_markup()

# ---- Кости черепа (подразделы по каждой кости) ----
def get_anatomy_bones_keyboard(topic_key: str):
    topic = get_anatomy_topic_data(topic_key)
    builder = InlineKeyboardBuilder()
    for bone in topic.get("bones_list", []):
        builder.button(text=f"🦴 {bone['title']}", callback_data=f"anatomy_bone_hub:{topic_key}:{bone['id']}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К разделу", callback_data=f"anatomy_topic:{topic_key}"))
    return builder.as_markup()

def get_bone_title(topic_key: str, bone_id: str) -> str:
    topic = get_anatomy_topic_data(topic_key)
    for bone in topic.get("bones_list", []):
        if bone["id"] == bone_id:
            return bone["title"]
    return bone_id

def get_bone_material_list(topic_key: str, bone_id: str) -> list:
    topic = get_anatomy_topic_data(topic_key)
    material_ids = topic.get("bone_material_ids", {}).get(bone_id, [bone_id])
    by_id = {m["id"]: m for m in topic["material"]}
    return [by_id[mid] for mid in material_ids if mid in by_id]

def get_bone_flashcards(topic_key: str, bone_id: str) -> list:
    topic = get_anatomy_topic_data(topic_key)
    return [fc for fc in topic["flashcards"] if fc.get("bone") == bone_id]

def get_bone_pairs(topic_key: str, bone_id: str) -> list:
    topic = get_anatomy_topic_data(topic_key)
    pairs = []
    for s in topic["matching_sets"]:
        pairs.extend(p for p in s["pairs"] if p.get("bone") == bone_id)
    return pairs

def get_bone_mnemonics(topic_key: str, bone_id: str) -> list:
    topic = get_anatomy_topic_data(topic_key)
    return [mn for mn in topic["mnemonics"] if mn.get("bone") == bone_id]

def get_bone_images(topic_key: str, bone_id: str) -> list:
    topic = get_anatomy_topic_data(topic_key)
    return topic.get("bone_images", {}).get(bone_id, [])

def get_anatomy_bone_hub_keyboard(topic_key: str, bone_id: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="📖 Материал", callback_data=f"anatomy_bone_material:{topic_key}:{bone_id}:0")
    builder.button(text="🖼 Фото и схемы", callback_data=f"anatomy_bone_img:{topic_key}:{bone_id}:0")
    builder.button(text="🎴 Флэш-карточки", callback_data=f"anatomy_bone_flash_start:{topic_key}:{bone_id}")
    builder.button(text="🔗 Сопоставление", callback_data=f"anatomy_bone_match_start:{topic_key}:{bone_id}")
    builder.button(text="🧠 Мнемоники", callback_data=f"anatomy_bone_mnemonics:{topic_key}:{bone_id}:0")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К списку костей", callback_data=f"anatomy_bones:{topic_key}"))
    return builder.as_markup()

def get_anatomy_bone_hub_text(topic_key: str, bone_id: str) -> str:
    title = get_bone_title(topic_key, bone_id)
    n_material = len(get_bone_material_list(topic_key, bone_id))
    n_images = len(get_bone_images(topic_key, bone_id))
    n_flash = len(get_bone_flashcards(topic_key, bone_id))
    n_pairs = len(get_bone_pairs(topic_key, bone_id))
    n_mnemo = len(get_bone_mnemonics(topic_key, bone_id))
    return (
        f"🦴 <b>{title}</b>\n{DIVIDER}\n\n"
        f"📖 Материал: {n_material} стр.\n"
        f"🖼 Фото и схем: {n_images}\n"
        f"🎴 Флэш-карточек: {n_flash}\n"
        f"🔗 Пар для сопоставления: {n_pairs}\n"
        f"🧠 Мнемоник: {n_mnemo}\n\n"
        "Выбери формат подготовки:"
    )

def get_bone_image_keyboard(topic_key: str, bone_id: str, idx: int, total: int):
    builder = InlineKeyboardBuilder()
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"anatomy_bone_img:{topic_key}:{bone_id}:{idx-1}"))
    if idx < total - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"anatomy_bone_img:{topic_key}:{bone_id}:{idx+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К кости", callback_data=f"anatomy_bone_hub:{topic_key}:{bone_id}"))
    return builder.as_markup()

async def render_bone_image(callback: CallbackQuery, topic_key: str, bone_id: str, idx: int):
    images = get_bone_images(topic_key, bone_id)
    title = get_bone_title(topic_key, bone_id)
    img = images[idx]
    caption = (
        f"🖼 {title}\n\n{img['caption']}\n\n"
        f"Источник: {img['credit']}\n\n{idx + 1}/{len(images)}"
    )
    keyboard = get_bone_image_keyboard(topic_key, bone_id, idx, len(images))
    photo = img["url"] if "url" in img else FSInputFile(os.path.join(ANATOMY_IMAGES_DIR, img["path"]))
    await callback.message.delete()
    await callback.message.answer_photo(photo, caption=caption, reply_markup=keyboard)

def get_bone_material_keyboard(topic_key: str, bone_id: str, idx: int):
    pages = get_bone_material_list(topic_key, bone_id)
    builder = InlineKeyboardBuilder()
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"anatomy_bone_material:{topic_key}:{bone_id}:{idx-1}"))
    if idx < len(pages) - 1:
        nav.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"anatomy_bone_material:{topic_key}:{bone_id}:{idx+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К кости", callback_data=f"anatomy_bone_hub:{topic_key}:{bone_id}"))
    return builder.as_markup()

def get_bone_material_text(topic_key: str, bone_id: str, idx: int) -> str:
    pages = get_bone_material_list(topic_key, bone_id)
    m = pages[idx]
    return f"📖 <b>{m['title']}</b>\n{DIVIDER}\n\n{m['content']}\n\n{DIVIDER}\n{idx + 1}/{len(pages)}"

# ---- Материал ----
def get_anatomy_material_keyboard(topic_key: str, idx: int):
    topic = get_anatomy_topic_data(topic_key)
    material = topic["material"]
    builder = InlineKeyboardBuilder()
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"anatomy_material:{topic_key}:{idx-1}"))
    if idx < len(material) - 1:
        nav.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"anatomy_material:{topic_key}:{idx+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="📋 Список тем", callback_data=f"anatomy_material_list:{topic_key}"))
    builder.row(InlineKeyboardButton(text="🔙 К разделу", callback_data=f"anatomy_topic:{topic_key}"))
    return builder.as_markup()

def get_anatomy_material_text(topic_key: str, idx: int) -> str:
    topic = get_anatomy_topic_data(topic_key)
    material = topic["material"]
    m = material[idx]
    return f"📖 <b>{m['title']}</b>\n{DIVIDER}\n\n{m['content']}\n\n{DIVIDER}\n{idx + 1}/{len(material)}"

def get_anatomy_material_list_keyboard(topic_key: str):
    topic = get_anatomy_topic_data(topic_key)
    builder = InlineKeyboardBuilder()
    for i, m in enumerate(topic["material"]):
        builder.button(text=f"{i + 1}. {m['title']}", callback_data=f"anatomy_material:{topic_key}:{i}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К разделу", callback_data=f"anatomy_topic:{topic_key}"))
    return builder.as_markup()

# ---- Флэш-карточки ----
def start_anatomy_flash_session(user_id: int, topic_key: str, bone_id: str = None):
    topic = get_anatomy_topic_data(topic_key)
    if bone_id:
        pool = [i for i, fc in enumerate(topic["flashcards"]) if fc.get("bone") == bone_id]
    else:
        pool = list(range(len(topic["flashcards"])))
    size = min(ANATOMY_FLASH_SESSION_SIZE, len(pool))
    ANATOMY_FLASH_SESSIONS[user_id] = {
        "topic_key": topic_key,
        "bone_id": bone_id,
        "cards": random.sample(pool, size),
        "index": 0,
        "know": 0,
        "dont_know": 0,
    }

def get_anatomy_flash_question_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🙈 Показать ответ", callback_data="anatomy_flash_show_answer")
    builder.button(text="🛑 Закончить", callback_data="anatomy_flash_stop")
    builder.adjust(1)
    return builder.as_markup()

def get_anatomy_flash_answer_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Знаю", callback_data="anatomy_flash_know")
    builder.button(text="❌ Не знаю", callback_data="anatomy_flash_dont_know")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🛑 Закончить", callback_data="anatomy_flash_stop"))
    return builder.as_markup()

def get_anatomy_flash_summary_keyboard(topic_key: str, bone_id: str = None):
    builder = InlineKeyboardBuilder()
    if bone_id:
        builder.button(text="🔁 Пройти ещё раз", callback_data=f"anatomy_bone_flash_start:{topic_key}:{bone_id}")
        builder.button(text="🔙 К кости", callback_data=f"anatomy_bone_hub:{topic_key}:{bone_id}")
    else:
        builder.button(text="🔁 Пройти ещё раз", callback_data=f"anatomy_flash_start:{topic_key}")
        builder.button(text="🔙 К разделу", callback_data=f"anatomy_topic:{topic_key}")
    builder.adjust(1)
    return builder.as_markup()

async def render_anatomy_flash_question(message, user_id: int):
    session = ANATOMY_FLASH_SESSIONS[user_id]
    topic = get_anatomy_topic_data(session["topic_key"])
    total = len(session["cards"])
    card = topic["flashcards"][session["cards"][session["index"]]]
    text = f"🎴 <b>Флэш-карточки — {session['index'] + 1}/{total}</b>\n{DIVIDER}\n\n{card['front']}"
    await safe_edit_text(message, text, parse_mode="HTML", reply_markup=get_anatomy_flash_question_keyboard())

async def render_anatomy_flash_answer(message, user_id: int):
    session = ANATOMY_FLASH_SESSIONS[user_id]
    topic = get_anatomy_topic_data(session["topic_key"])
    total = len(session["cards"])
    card = topic["flashcards"][session["cards"][session["index"]]]
    text = (
        f"🎴 <b>Флэш-карточки — {session['index'] + 1}/{total}</b>\n{DIVIDER}\n\n"
        f"❓ {card['front']}\n\n💡 {card['back']}\n\n{DIVIDER}\nТы знал(а) ответ?"
    )
    await safe_edit_text(message, text, parse_mode="HTML", reply_markup=get_anatomy_flash_answer_keyboard())

async def render_anatomy_flash_summary(message, user_id: int, aborted: bool = False):
    session = ANATOMY_FLASH_SESSIONS.pop(user_id, None)
    if not session:
        return
    topic_key = session["topic_key"]
    bone_id = session.get("bone_id")
    answered = session["know"] + session["dont_know"]
    title = "🛑 <b>Прервано</b>" if aborted else "🏁 <b>Карточки пройдены!</b>"
    text = (
        f"{title}\n{DIVIDER}\n\n"
        f"Отвечено: <b>{answered}</b>\n✅ Знаю: <b>{session['know']}</b>\n❌ Не знаю: <b>{session['dont_know']}</b>"
    )
    await safe_edit_text(message, text, parse_mode="HTML", reply_markup=get_anatomy_flash_summary_keyboard(topic_key, bone_id))

# ---- Сопоставление (матчинг как тест с вариантами) ----
def get_anatomy_all_pairs(topic_key: str, bone_id: str = None):
    topic = get_anatomy_topic_data(topic_key)
    pairs = []
    for s in topic["matching_sets"]:
        pairs.extend(s["pairs"])
    if bone_id:
        pairs = [p for p in pairs if p.get("bone") == bone_id]
    return pairs

def start_anatomy_match_session(user_id: int, topic_key: str, bone_id: str = None):
    all_pairs = get_anatomy_all_pairs(topic_key)
    queue_pairs = get_anatomy_all_pairs(topic_key, bone_id) if bone_id else all_pairs
    size = min(ANATOMY_MATCH_SESSION_SIZE, len(queue_pairs))
    ANATOMY_MATCH_SESSIONS[user_id] = {
        "topic_key": topic_key,
        "bone_id": bone_id,
        "all_pairs": all_pairs,
        "queue": random.sample(queue_pairs, size),
        "index": 0,
        "correct": 0,
        "wrong": 0,
        "current_correct_idx": None,
        "current_options": None,
    }

def get_anatomy_match_keyboard(options: list):
    builder = InlineKeyboardBuilder()
    for i in range(len(options)):
        builder.button(text=str(i + 1), callback_data=f"anatomy_match_answer:{i}")
    builder.adjust(len(options))
    builder.row(InlineKeyboardButton(text="🛑 Закончить", callback_data="anatomy_match_stop"))
    return builder.as_markup()

async def render_anatomy_match_question(message, user_id: int):
    session = ANATOMY_MATCH_SESSIONS[user_id]
    pair = session["queue"][session["index"]]
    term, correct_def = pair["term"], pair["definition"]
    distractor_pool = [p["definition"] for p in session["all_pairs"] if p["definition"] != correct_def]
    distractors = random.sample(distractor_pool, min(3, len(distractor_pool)))
    options = distractors + [correct_def]
    random.shuffle(options)
    session["current_correct_idx"] = options.index(correct_def)
    session["current_options"] = options
    lines = [
        f"🔗 <b>Сопоставление — {session['index'] + 1}/{len(session['queue'])}</b>\n{DIVIDER}\n",
        f"<b>{term}</b>\n",
        "Выбери правильное соответствие:",
        "",
    ]
    for i, opt in enumerate(options):
        lines.append(f"{i + 1}. {opt}")
    await safe_edit_text(message, "\n".join(lines), parse_mode="HTML", reply_markup=get_anatomy_match_keyboard(options))

async def render_anatomy_match_summary(message, user_id: int, aborted: bool = False):
    session = ANATOMY_MATCH_SESSIONS.pop(user_id, None)
    if not session:
        return
    topic_key = session["topic_key"]
    bone_id = session.get("bone_id")
    answered = session["correct"] + session["wrong"]
    title = "🛑 <b>Прервано</b>" if aborted else "🏁 <b>Сопоставление завершено!</b>"
    text = (
        f"{title}\n{DIVIDER}\n\n"
        f"Отвечено: <b>{answered}</b>\n✅ Верно: <b>{session['correct']}</b>\n❌ Неверно: <b>{session['wrong']}</b>"
    )
    builder = InlineKeyboardBuilder()
    if bone_id:
        builder.button(text="🔁 Пройти ещё раз", callback_data=f"anatomy_bone_match_start:{topic_key}:{bone_id}")
        builder.button(text="🔙 К кости", callback_data=f"anatomy_bone_hub:{topic_key}:{bone_id}")
    else:
        builder.button(text="🔁 Пройти ещё раз", callback_data=f"anatomy_match_start:{topic_key}")
        builder.button(text="🔙 К разделу", callback_data=f"anatomy_topic:{topic_key}")
    builder.adjust(1)
    await safe_edit_text(message, text, parse_mode="HTML", reply_markup=builder.as_markup())

# ---- Мнемоники ----
def get_anatomy_mnemonics_keyboard(topic_key: str, idx: int):
    topic = get_anatomy_topic_data(topic_key)
    mnemonics = topic["mnemonics"]
    builder = InlineKeyboardBuilder()
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"anatomy_mnemonics:{topic_key}:{idx-1}"))
    if idx < len(mnemonics) - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"anatomy_mnemonics:{topic_key}:{idx+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К разделу", callback_data=f"anatomy_topic:{topic_key}"))
    return builder.as_markup()

def get_anatomy_mnemonic_text(topic_key: str, idx: int) -> str:
    topic = get_anatomy_topic_data(topic_key)
    mnemonics = topic["mnemonics"]
    mn = mnemonics[idx]
    return f"🧠 <b>{mn['title']}</b>\n{DIVIDER}\n\n{mn['text']}\n\n{DIVIDER}\n{idx + 1}/{len(mnemonics)}"

def get_bone_mnemonics_keyboard(topic_key: str, bone_id: str, idx: int):
    mnemonics = get_bone_mnemonics(topic_key, bone_id)
    builder = InlineKeyboardBuilder()
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"anatomy_bone_mnemonics:{topic_key}:{bone_id}:{idx-1}"))
    if idx < len(mnemonics) - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"anatomy_bone_mnemonics:{topic_key}:{bone_id}:{idx+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К кости", callback_data=f"anatomy_bone_hub:{topic_key}:{bone_id}"))
    return builder.as_markup()

def get_bone_mnemonic_text(topic_key: str, bone_id: str, idx: int) -> str:
    mnemonics = get_bone_mnemonics(topic_key, bone_id)
    mn = mnemonics[idx]
    return f"🧠 <b>{mn['title']}</b>\n{DIVIDER}\n\n{mn['text']}\n\n{DIVIDER}\n{idx + 1}/{len(mnemonics)}"

# ---- Хендлеры ----
@dp.callback_query(F.data == "anatomy_menu")
async def cb_anatomy_menu(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    await callback.answer()
    await safe_edit_text(
        callback.message,
        f"🦴 <b>Анатомия</b>\n{DIVIDER}\n\nВыбери подраздел:",
        parse_mode="HTML",
        reply_markup=get_anatomy_menu_keyboard()
    )

@dp.callback_query(F.data.startswith("anatomy_section:"))
async def cb_anatomy_section(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    section_key = callback.data.split(":")[1]
    section = ANATOMY.get(section_key)
    if not section:
        await callback.answer("Раздел не найден", show_alert=True)
        return
    await callback.answer()
    await safe_edit_text(
        callback.message,
        f"🦴 <b>{section['title']}</b>\n{DIVIDER}\n\nВыбери тему:",
        parse_mode="HTML",
        reply_markup=get_anatomy_section_keyboard(section_key)
    )

@dp.callback_query(F.data.startswith("anatomy_topic:"))
async def cb_anatomy_topic(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    topic_key = callback.data.split(":")[1]
    topic = get_anatomy_topic_data(topic_key)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    await callback.answer()
    icon = topic.get("icon", "📚")
    text = (
        f"{icon} <b>{topic['title']}</b>\n{DIVIDER}\n\n"
        f"📖 Материал: {len(topic['material'])} тем\n"
        f"🎴 Флэш-карточек: {len(topic['flashcards'])}\n"
        f"🔗 Пар для сопоставления: {sum(len(s['pairs']) for s in topic['matching_sets'])}\n"
        f"🧠 Мнемоник: {len(topic['mnemonics'])}\n\n"
        "Выбери формат подготовки:"
    )
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=get_anatomy_topic_keyboard(topic_key))

@dp.callback_query(F.data.startswith("anatomy_bones:"))
async def cb_anatomy_bones(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    topic_key = callback.data.split(":")[1]
    topic = get_anatomy_topic_data(topic_key)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    await callback.answer()
    await safe_edit_text(
        callback.message,
        f"🦴 <b>{topic['title']} — по костям</b>\n{DIVIDER}\n\nВыбери кость:",
        parse_mode="HTML",
        reply_markup=get_anatomy_bones_keyboard(topic_key)
    )

@dp.callback_query(F.data.startswith("anatomy_bone_hub:"))
async def cb_anatomy_bone_hub(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    _, topic_key, bone_id = callback.data.split(":")
    topic = get_anatomy_topic_data(topic_key)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    await callback.answer()
    await safe_edit_text(
        callback.message,
        get_anatomy_bone_hub_text(topic_key, bone_id),
        parse_mode="HTML",
        reply_markup=get_anatomy_bone_hub_keyboard(topic_key, bone_id)
    )

@dp.callback_query(F.data.startswith("anatomy_bone_material:"))
async def cb_anatomy_bone_material(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    _, topic_key, bone_id, idx_s = callback.data.split(":")
    idx = int(idx_s)
    pages = get_bone_material_list(topic_key, bone_id)
    if not pages or not (0 <= idx < len(pages)):
        await callback.answer("Материал не найден", show_alert=True)
        return
    await callback.answer()
    await safe_edit_text(
        callback.message,
        get_bone_material_text(topic_key, bone_id, idx),
        parse_mode="HTML",
        reply_markup=get_bone_material_keyboard(topic_key, bone_id, idx)
    )

@dp.callback_query(F.data.startswith("anatomy_bone_img:"))
async def cb_anatomy_bone_img(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    _, topic_key, bone_id, idx_s = callback.data.split(":")
    idx = int(idx_s)
    images = get_bone_images(topic_key, bone_id)
    if not images or not (0 <= idx < len(images)):
        await callback.answer("Фото для этой кости пока нет", show_alert=True)
        return
    await callback.answer()
    await render_bone_image(callback, topic_key, bone_id, idx)

@dp.callback_query(F.data.startswith("anatomy_bone_flash_start:"))
async def cb_anatomy_bone_flash_start(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    _, topic_key, bone_id = callback.data.split(":")
    topic = get_anatomy_topic_data(topic_key)
    if not topic or not get_bone_flashcards(topic_key, bone_id):
        await callback.answer("Карточки для этой кости ещё не добавлены", show_alert=True)
        return
    await callback.answer()
    start_anatomy_flash_session(callback.from_user.id, topic_key, bone_id=bone_id)
    await render_anatomy_flash_question(callback.message, callback.from_user.id)

@dp.callback_query(F.data.startswith("anatomy_bone_match_start:"))
async def cb_anatomy_bone_match_start(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    _, topic_key, bone_id = callback.data.split(":")
    topic = get_anatomy_topic_data(topic_key)
    if not topic or not get_bone_pairs(topic_key, bone_id):
        await callback.answer("Пары для этой кости ещё не добавлены", show_alert=True)
        return
    await callback.answer()
    start_anatomy_match_session(callback.from_user.id, topic_key, bone_id=bone_id)
    await render_anatomy_match_question(callback.message, callback.from_user.id)

@dp.callback_query(F.data.startswith("anatomy_bone_mnemonics:"))
async def cb_anatomy_bone_mnemonics(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    _, topic_key, bone_id, idx_s = callback.data.split(":")
    idx = int(idx_s)
    mnemonics = get_bone_mnemonics(topic_key, bone_id)
    if not mnemonics or not (0 <= idx < len(mnemonics)):
        await callback.answer("Мнемоники для этой кости ещё не добавлены", show_alert=True)
        return
    await callback.answer()
    await safe_edit_text(
        callback.message,
        get_bone_mnemonic_text(topic_key, bone_id, idx),
        parse_mode="HTML",
        reply_markup=get_bone_mnemonics_keyboard(topic_key, bone_id, idx)
    )

@dp.callback_query(F.data.startswith("anatomy_material_list:"))
async def cb_anatomy_material_list(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    await callback.answer()
    topic_key = callback.data.split(":")[1]
    topic = get_anatomy_topic_data(topic_key)
    await safe_edit_text(
        callback.message,
        f"📋 <b>{topic['title']} — список тем</b>\n{DIVIDER}\n\nВыбери тему:",
        parse_mode="HTML",
        reply_markup=get_anatomy_material_list_keyboard(topic_key)
    )

@dp.callback_query(F.data.startswith("anatomy_material:"))
async def cb_anatomy_material(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    _, topic_key, idx_s = callback.data.split(":")
    idx = int(idx_s)
    topic = get_anatomy_topic_data(topic_key)
    if not topic or not (0 <= idx < len(topic["material"])):
        await callback.answer("Тема не найдена", show_alert=True)
        return
    await callback.answer()
    await safe_edit_text(
        callback.message,
        get_anatomy_material_text(topic_key, idx),
        parse_mode="HTML",
        reply_markup=get_anatomy_material_keyboard(topic_key, idx)
    )

@dp.callback_query(F.data.startswith("anatomy_flash_start:"))
async def cb_anatomy_flash_start(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    topic_key = callback.data.split(":")[1]
    topic = get_anatomy_topic_data(topic_key)
    if not topic or not topic["flashcards"]:
        await callback.answer("Карточки ещё не добавлены", show_alert=True)
        return
    await callback.answer()
    start_anatomy_flash_session(callback.from_user.id, topic_key)
    await render_anatomy_flash_question(callback.message, callback.from_user.id)

@dp.callback_query(F.data == "anatomy_flash_show_answer")
async def cb_anatomy_flash_show_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in ANATOMY_FLASH_SESSIONS:
        await callback.answer("Сессия истекла, начни заново", show_alert=True)
        return
    await callback.answer()
    await render_anatomy_flash_answer(callback.message, user_id)

@dp.callback_query(F.data.in_({"anatomy_flash_know", "anatomy_flash_dont_know"}))
async def cb_anatomy_flash_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = ANATOMY_FLASH_SESSIONS.get(user_id)
    if not session:
        await callback.answer("Сессия истекла, начни заново", show_alert=True)
        return
    await callback.answer()
    if callback.data == "anatomy_flash_know":
        session["know"] += 1
    else:
        session["dont_know"] += 1
    session["index"] += 1
    if session["index"] >= len(session["cards"]):
        await render_anatomy_flash_summary(callback.message, user_id)
    else:
        await render_anatomy_flash_question(callback.message, user_id)

@dp.callback_query(F.data == "anatomy_flash_stop")
async def cb_anatomy_flash_stop(callback: CallbackQuery):
    await callback.answer()
    if callback.from_user.id in ANATOMY_FLASH_SESSIONS:
        await render_anatomy_flash_summary(callback.message, callback.from_user.id, aborted=True)

@dp.callback_query(F.data.startswith("anatomy_match_start:"))
async def cb_anatomy_match_start(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    topic_key = callback.data.split(":")[1]
    topic = get_anatomy_topic_data(topic_key)
    if not topic or not get_anatomy_all_pairs(topic_key):
        await callback.answer("Пары ещё не добавлены", show_alert=True)
        return
    await callback.answer()
    start_anatomy_match_session(callback.from_user.id, topic_key)
    await render_anatomy_match_question(callback.message, callback.from_user.id)

@dp.callback_query(F.data.startswith("anatomy_match_answer:"))
async def cb_anatomy_match_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = ANATOMY_MATCH_SESSIONS.get(user_id)
    if not session:
        await callback.answer("Сессия истекла, начни заново", show_alert=True)
        return
    chosen = int(callback.data.split(":")[1])
    correct_idx = session["current_correct_idx"]
    if chosen == correct_idx:
        session["correct"] += 1
        await callback.answer("✅ Верно!")
    else:
        session["wrong"] += 1
        correct_text = session["current_options"][correct_idx]
        await callback.answer(f"❌ Неверно. Правильно: {correct_text}", show_alert=True)
    session["index"] += 1
    if session["index"] >= len(session["queue"]):
        await render_anatomy_match_summary(callback.message, user_id)
    else:
        await render_anatomy_match_question(callback.message, user_id)

@dp.callback_query(F.data == "anatomy_match_stop")
async def cb_anatomy_match_stop(callback: CallbackQuery):
    await callback.answer()
    if callback.from_user.id in ANATOMY_MATCH_SESSIONS:
        await render_anatomy_match_summary(callback.message, callback.from_user.id, aborted=True)

@dp.callback_query(F.data.startswith("anatomy_mnemonics:"))
async def cb_anatomy_mnemonics(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    _, topic_key, idx_s = callback.data.split(":")
    idx = int(idx_s)
    topic = get_anatomy_topic_data(topic_key)
    if not topic or not topic["mnemonics"] or not (0 <= idx < len(topic["mnemonics"])):
        await callback.answer("Мнемоники ещё не добавлены", show_alert=True)
        return
    await callback.answer()
    await safe_edit_text(
        callback.message,
        get_anatomy_mnemonic_text(topic_key, idx),
        parse_mode="HTML",
        reply_markup=get_anatomy_mnemonics_keyboard(topic_key, idx)
    )

@dp.callback_query(F.data.startswith("anatomy_picture:"))
async def cb_anatomy_picture(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    await callback.answer()
    topic_key = callback.data.split(":")[1]
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"anatomy_topic:{topic_key}"))
    await safe_edit_text(
        callback.message,
        f"🖼 <b>Найди на картинке</b>\n{DIVIDER}\n\n"
        "🚧 Скоро будет добавлено — нужны изображения из атласов Неттера и Гайворонского.",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

# ==================== ГИСТОЛОГИЯ ====================
HISTOLOGY_PUBLIC = False  # когда раздел будет готов для всех — переключить на True

def histology_access_ok(user_id: int) -> bool:
    return HISTOLOGY_PUBLIC or is_admin(user_id) or has_subscription_histology_access(user_id)

def get_histology_specimen(diag_key: str, spec_id: str):
    diag = HISTOLOGY.get(diag_key)
    if not diag:
        return None
    for spec in diag["specimens"]:
        if spec["id"] == spec_id:
            return spec
    return None

def get_histology_menu_keyboard():
    builder = InlineKeyboardBuilder()
    for diag_key, diag in HISTOLOGY.items():
        builder.button(text=diag.get("menu_title", diag["title"]), callback_data=f"histology_topic:{diag_key}")
    builder.button(text="🎯 Угадай препарат (все разделы)", callback_data="histology_guess_start:all")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()

def get_histology_topic_text(diag_key: str) -> str:
    diag = HISTOLOGY[diag_key]
    n = len(diag["specimens"])
    total = diag.get("total_official")
    progress = f"{n}" if not total or n >= total else f"{n} из {total}"
    note = "" if not total or n >= total else "\n\nОстальные препараты добавим по мере поступления презентаций."
    return (
        f"🔬 <b>{diag['title']}</b>\n{DIVIDER}\n\n"
        f"Препаратов доступно: <b>{progress}</b>{note}\n\n"
        "Выбери препарат:"
    )

def get_histology_topic_keyboard(diag_key: str):
    diag = HISTOLOGY[diag_key]
    builder = InlineKeyboardBuilder()
    builder.button(text="🎯 Угадай препарат", callback_data=f"histology_guess_start:{diag_key}")
    for spec in diag["specimens"]:
        builder.button(text=f"№{spec['number']}. {spec['title']}", callback_data=f"histology_specimen:{diag_key}:{spec['id']}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К разделу", callback_data="histology_menu"))
    return builder.as_markup()

def get_histology_specimen_text(diag_key: str, spec_id: str) -> str:
    spec = get_histology_specimen(diag_key, spec_id)
    lines = [f"🔬 <b>№{spec['number']}. {spec['title']}</b>\n{DIVIDER}\n"]
    if spec.get("stain"):
        lines.append(f"Окраска: {spec['stain']}")
    if spec.get("magnification"):
        lines.append(f"Увеличение: {spec['magnification']}")
    lines.append("")
    lines.append(spec["protocol"] or "Протокол-описание пока не добавлено.")
    return "\n".join(lines)

def get_histology_specimen_keyboard(diag_key: str, spec_id: str):
    spec = get_histology_specimen(diag_key, spec_id)
    builder = InlineKeyboardBuilder()
    n_img = len(spec.get("images", []))
    if n_img:
        builder.button(text=f"🖼 Микрофото ({n_img})", callback_data=f"histology_img:{diag_key}:{spec_id}:0")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К списку препаратов", callback_data=f"histology_topic:{diag_key}"))
    return builder.as_markup()

def get_histology_image_keyboard(diag_key: str, spec_id: str, idx: int, total: int):
    builder = InlineKeyboardBuilder()
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"histology_img:{diag_key}:{spec_id}:{idx-1}"))
    if idx < total - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"histology_img:{diag_key}:{spec_id}:{idx+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К препарату", callback_data=f"histology_specimen:{diag_key}:{spec_id}"))
    return builder.as_markup()

async def render_histology_image(callback: CallbackQuery, diag_key: str, spec_id: str, idx: int):
    spec = get_histology_specimen(diag_key, spec_id)
    images = spec.get("images", [])
    caption = f"🔬 №{spec['number']}. {spec['title']}\n\n{idx + 1}/{len(images)}"
    keyboard = get_histology_image_keyboard(diag_key, spec_id, idx, len(images))
    photo = FSInputFile(os.path.join(HISTOLOGY_IMAGES_DIR, images[idx]))
    await callback.message.delete()
    await callback.message.answer_photo(photo, caption=caption, reply_markup=keyboard)

@dp.callback_query(F.data == "histology_menu")
async def cb_histology_menu(callback: CallbackQuery):
    if not histology_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    await callback.answer()
    await safe_edit_text(
        callback.message,
        f"🔬 <b>Гистология</b>\n{DIVIDER}\n\nВыбери диагностику:",
        parse_mode="HTML",
        reply_markup=get_histology_menu_keyboard()
    )

@dp.callback_query(F.data.startswith("histology_topic:"))
async def cb_histology_topic(callback: CallbackQuery):
    if not histology_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    diag_key = callback.data.split(":")[1]
    if diag_key not in HISTOLOGY:
        await callback.answer("Раздел не найден", show_alert=True)
        return
    await callback.answer()
    await safe_edit_text(
        callback.message,
        get_histology_topic_text(diag_key),
        parse_mode="HTML",
        reply_markup=get_histology_topic_keyboard(diag_key)
    )

@dp.callback_query(F.data.startswith("histology_specimen:"))
async def cb_histology_specimen(callback: CallbackQuery):
    if not histology_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    _, diag_key, spec_id = callback.data.split(":")
    spec = get_histology_specimen(diag_key, spec_id)
    if not spec:
        await callback.answer("Препарат не найден", show_alert=True)
        return
    await callback.answer()
    await safe_edit_text(
        callback.message,
        get_histology_specimen_text(diag_key, spec_id),
        parse_mode="HTML",
        reply_markup=get_histology_specimen_keyboard(diag_key, spec_id)
    )

@dp.callback_query(F.data.startswith("histology_img:"))
async def cb_histology_img(callback: CallbackQuery):
    if not histology_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    _, diag_key, spec_id, idx_s = callback.data.split(":")
    idx = int(idx_s)
    spec = get_histology_specimen(diag_key, spec_id)
    images = spec.get("images", []) if spec else []
    if not images or not (0 <= idx < len(images)):
        await callback.answer("Фото для этого препарата пока нет", show_alert=True)
        return
    await callback.answer()
    await render_histology_image(callback, diag_key, spec_id, idx)

# ---- Угадай препарат ----
HISTOLOGY_GUESS_SESSION_SIZE = 10
HISTOLOGY_GUESS_SESSIONS: dict[int, dict] = {}

def get_histology_guess_pool(scope: str):
    # only specimens with a verified label-free "guess_image" are eligible --
    # many source slides bake the answer or structure labels into every available
    # photo, so those specimens are deliberately left out of this mode.
    if scope == "all":
        return [(diag_key, spec["id"]) for diag_key, diag in HISTOLOGY.items()
                 for spec in diag["specimens"] if spec.get("guess_image")]
    diag = HISTOLOGY.get(scope)
    if not diag:
        return []
    return [(scope, spec["id"]) for spec in diag["specimens"] if spec.get("guess_image")]

def start_histology_guess_session(user_id: int, scope: str) -> bool:
    pool = get_histology_guess_pool(scope)
    if not pool:
        return False
    size = min(HISTOLOGY_GUESS_SESSION_SIZE, len(pool))
    HISTOLOGY_GUESS_SESSIONS[user_id] = {
        "scope": scope,
        "items": random.sample(pool, size),
        "index": 0,
        "know": 0,
        "dont_know": 0,
    }
    return True

def get_histology_guess_question_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🙈 Показать ответ", callback_data="histology_guess_show_answer")
    builder.button(text="🛑 Закончить", callback_data="histology_guess_stop")
    builder.adjust(1)
    return builder.as_markup()

def get_histology_guess_answer_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Угадал(а)", callback_data="histology_guess_know")
    builder.button(text="❌ Не угадал(а)", callback_data="histology_guess_dont_know")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🛑 Закончить", callback_data="histology_guess_stop"))
    return builder.as_markup()

def get_histology_guess_summary_keyboard(scope: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="🔁 Пройти ещё раз", callback_data=f"histology_guess_start:{scope}")
    if scope == "all":
        builder.button(text="🔙 К разделу", callback_data="histology_menu")
    else:
        builder.button(text="🔙 К разделу", callback_data=f"histology_topic:{scope}")
    builder.adjust(1)
    return builder.as_markup()

async def render_histology_guess_question(callback: CallbackQuery, user_id: int):
    session = HISTOLOGY_GUESS_SESSIONS[user_id]
    total = len(session["items"])
    diag_key, spec_id = session["items"][session["index"]]
    spec = get_histology_specimen(diag_key, spec_id)
    caption = f"🎯 Угадай препарат — {session['index'] + 1}/{total}\n\nЧто это за препарат?"
    photo = FSInputFile(os.path.join(HISTOLOGY_IMAGES_DIR, spec["guess_image"]))
    await callback.message.delete()
    sent = await callback.message.answer_photo(photo, caption=caption, reply_markup=get_histology_guess_question_keyboard())
    session["msg"] = sent

async def render_histology_guess_answer(user_id: int):
    session = HISTOLOGY_GUESS_SESSIONS[user_id]
    total = len(session["items"])
    diag_key, spec_id = session["items"][session["index"]]
    spec = get_histology_specimen(diag_key, spec_id)
    lines = [f"🎯 Угадай препарат — {session['index'] + 1}/{total}", "", f"№{spec['number']}. {spec['title']}"]
    if spec.get("stain"):
        lines.append(f"Окраска: {spec['stain']}")
    if spec.get("magnification"):
        lines.append(f"Увеличение: {spec['magnification']}")
    lines.append("")
    lines.append("Ты угадал(а)?")
    await session["msg"].edit_caption(caption="\n".join(lines), reply_markup=get_histology_guess_answer_keyboard())

async def render_histology_guess_summary(user_id: int, aborted: bool = False):
    session = HISTOLOGY_GUESS_SESSIONS.pop(user_id, None)
    if not session:
        return
    scope = session["scope"]
    answered = session["know"] + session["dont_know"]
    title = "🛑 Прервано" if aborted else "🏁 Препараты закончились!"
    caption = (
        f"{title}\n\n"
        f"Отвечено: {answered}\n✅ Угадано: {session['know']}\n❌ Не угадано: {session['dont_know']}"
    )
    await session["msg"].edit_caption(caption=caption, reply_markup=get_histology_guess_summary_keyboard(scope))

@dp.callback_query(F.data.startswith("histology_guess_start:"))
async def cb_histology_guess_start(callback: CallbackQuery):
    if not histology_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    scope = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    if not start_histology_guess_session(user_id, scope):
        await callback.answer("Препаратов пока нет", show_alert=True)
        return
    await callback.answer()
    await render_histology_guess_question(callback, user_id)

@dp.callback_query(F.data == "histology_guess_show_answer")
async def cb_histology_guess_show_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in HISTOLOGY_GUESS_SESSIONS:
        await callback.answer("Сессия истекла, начни заново", show_alert=True)
        return
    await callback.answer()
    await render_histology_guess_answer(user_id)

@dp.callback_query(F.data.in_({"histology_guess_know", "histology_guess_dont_know"}))
async def cb_histology_guess_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = HISTOLOGY_GUESS_SESSIONS.get(user_id)
    if not session:
        await callback.answer("Сессия истекла, начни заново", show_alert=True)
        return
    await callback.answer()
    if callback.data == "histology_guess_know":
        session["know"] += 1
    else:
        session["dont_know"] += 1
    session["index"] += 1
    if session["index"] >= len(session["items"]):
        await render_histology_guess_summary(user_id)
    else:
        await render_histology_guess_question(callback, user_id)

@dp.callback_query(F.data == "histology_guess_stop")
async def cb_histology_guess_stop(callback: CallbackQuery):
    await callback.answer()
    if callback.from_user.id in HISTOLOGY_GUESS_SESSIONS:
        await render_histology_guess_summary(callback.from_user.id, aborted=True)

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
