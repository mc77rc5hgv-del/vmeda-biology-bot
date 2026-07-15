"""VICEGRAM — бот-ловец для групповых и личных чатов Telegram.

Ловит удалённые и изменённые сообщения, стикеры, файлы и гифки,
следит за исчезающими медиа, умеет восстанавливать историю чата,
считает "огоньки" активности, банит скам-сообщения и поддерживает
кастомные команды в чатах.

Механизмы ловли:

- В группах (где бот состоит участником) — периодическая тихая проверка
  существования сообщения (copy_message в лог-чат с мгновенным удалением
  копии), задержка до ~30 секунд. Bot API не присылает боту событие
  "сообщение удалено" в группах ни при каких правах, поэтому мгновенно
  здесь поймать нельзя.
- В личных чатах — через официальную функцию Telegram "Автоматизация
  чатов" (Telegram Business): пользователь сам подключает бота в своих
  настройках (Настройки → Изменить → Автоматизация чатов → username бота),
  без пароля и кода. После подключения Telegram сам присылает боту
  события business_message / edited_business_message /
  deleted_business_messages — включая настоящее мгновенное событие
  удаления с указанием чата, в отличие от групп.
"""

import asyncio
import html
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import aiohttp

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    BufferedInputFile,
    BusinessConnection,
    BusinessMessagesDeleted,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    LabeledPrice,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("VICEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError(
        "Не задан VICEGRAM_BOT_TOKEN. Установи переменную окружения с токеном "
        "бота VICEGRAM (полученным у @BotFather) перед запуском."
    )

ADMIN_ID = int(os.getenv("VICEGRAM_ADMIN_ID", "1326779223"))
_extra_admin_ids = os.getenv("VICEGRAM_ADMIN_IDS", "7928720775,1326779223,8601892147")
ADMIN_IDS = {int(x) for x in _extra_admin_ids.split(",") if x.strip()} | {ADMIN_ID}
_log_chat_env = os.getenv("VICEGRAM_LOG_CHAT_ID")
LOG_CHAT_ID = int(_log_chat_env) if _log_chat_env else ADMIN_ID


def is_bot_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

DB_PATH = os.getenv("VICEGRAM_DB_PATH", "vicegram.db")
MEDIA_CACHE_DIR = os.getenv("VICEGRAM_MEDIA_CACHE_DIR", "vicegram_media_cache")
os.makedirs(MEDIA_CACHE_DIR, exist_ok=True)
DIVIDER = "━━━━━━━━━━━━━━"

LOGO_PATH = os.path.join(os.path.dirname(__file__), "vicegram_assets", "logo.png")
SETUP_GUIDE_PATH = os.path.join(os.path.dirname(__file__), "vicegram_assets", "setup_guide.jpg")
TRIAL_BASE_DAYS = 7
TRIAL_BONUS_DAYS_PER_REFERRAL = 2

# ==================== ПЛАТНАЯ ПОДПИСКА ====================
# Цены — заглушка по умолчанию, поправь под свои условия.
SUBSCRIPTION_TIERS = {
    "max": {
        "name": "VICEGRAM MAX",
        "tagline": "Абсолютно все функции, включая добавление бота в группы",
        "group_access": True,
    },
    "pro": {
        "name": "VICEGRAM PRO",
        "tagline": "Все функции, кроме добавления бота в группы",
        "group_access": False,
    },
}

SUBSCRIPTION_DURATIONS = [
    {"code": "month", "label": "1 месяц", "days": 30},
    {"code": "half_year", "label": "6 месяцев", "days": 182},
    {"code": "year", "label": "1 год", "days": 365},
    {"code": "lifetime", "label": "Навсегда", "days": 36500},
]

# цена в рублях; звёзды — 1:1 к рублю (по просьбе); USDT — ориентировочно, поправь курс
RUB_PER_USDT = 95
SUBSCRIPTION_PRICES_RUB = {
    ("max", "month"): 59,
    ("max", "half_year"): 219,
    ("max", "year"): 390,
    ("max", "lifetime"): 599,
    ("pro", "month"): 49,
    ("pro", "half_year"): 199,
    ("pro", "year"): 319,
    ("pro", "lifetime"): 439,
}

YEAR_PLAN_JOKE = "🥙 Съесть один раз шаурму, или иметь подписку весь год — выбор очевиден"


def get_plan(plan_code: str) -> dict:
    """plan_code вида 'max_year' — разбирает на тариф+период и возвращает цены."""
    tier_code, duration_code = plan_code.split("_", 1)
    tier = SUBSCRIPTION_TIERS[tier_code]
    duration = next(d for d in SUBSCRIPTION_DURATIONS if d["code"] == duration_code)
    rub = SUBSCRIPTION_PRICES_RUB[(tier_code, duration_code)]
    return {
        "code": plan_code,
        "tier_code": tier_code,
        "duration_code": duration_code,
        "label": f"{tier['name']} — {duration['label']}",
        "tier_name": tier["name"],
        "tier_tagline": tier["tagline"],
        "group_access": tier["group_access"],
        "duration_label": duration["label"],
        "days": duration["days"],
        "rub": rub,
        "stars": rub,  # 1:1 к рублю
        "usdt": round(rub / RUB_PER_USDT, 2),
        "joke": YEAR_PLAN_JOKE if duration_code == "year" else "",
    }


def iter_plans(tier_code: str):
    for duration in SUBSCRIPTION_DURATIONS:
        yield get_plan(f"{tier_code}_{duration['code']}")


CRYPTOBOT_API_TOKEN = os.getenv("VICEGRAM_CRYPTOBOT_TOKEN")
CRYPTOBOT_API_URL = "https://pay.crypt.bot/api"
MANUAL_PAYMENT_USERNAME = os.getenv("VICEGRAM_MANUAL_PAYMENT_USERNAME", "vice_helper")


def build_manual_payment_url(plan: dict) -> str:
    """Ссылка на чат с админом с уже готовым текстом заявки — клиент сразу
    попадает в переписку, не тратя время на скриншоты в самом боте."""
    prefill = (
        f"Здравствуйте! Хочу оформить подписку «{plan['label']}» — {plan['rub']}₽."
    )
    return f"https://t.me/{MANUAL_PAYMENT_USERNAME}?text={quote(prefill)}"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ==================== БАЗА ДАННЫХ ====================
def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    # WAL — читатели больше не блокируются на писателе (иначе конкурентные
    # апдейты от разных чатов периодически стопорили ответ бота на команды);
    # busy_timeout — ждать освободившийся лок вместо мгновенного "database is locked".
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    conn = db_connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings (
            chat_id INTEGER PRIMARY KEY,
            catch_deleted INTEGER NOT NULL DEFAULT 1,
            catch_edited INTEGER NOT NULL DEFAULT 1,
            catch_disappearing INTEGER NOT NULL DEFAULT 1,
            chat_restore INTEGER NOT NULL DEFAULT 1,
            flames INTEGER NOT NULL DEFAULT 1,
            anti_scam INTEGER NOT NULL DEFAULT 1,
            custom_commands INTEGER NOT NULL DEFAULT 1,
            lang TEXT NOT NULL DEFAULT 'ru',
            owner_id INTEGER,
            owner_name TEXT
        );

        CREATE TABLE IF NOT EXISTS messages (
            source TEXT NOT NULL DEFAULT 'group_bot',
            owner_id INTEGER NOT NULL DEFAULT 0,
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            user_id INTEGER,
            user_name TEXT,
            user_username TEXT,
            text TEXT,
            media_type TEXT,
            file_id TEXT,
            media_path TEXT,
            date INTEGER NOT NULL,
            deleted INTEGER NOT NULL DEFAULT 0,
            expired INTEGER NOT NULL DEFAULT 0,
            check_count INTEGER NOT NULL DEFAULT 0,
            next_check_at INTEGER NOT NULL,
            PRIMARY KEY (owner_id, chat_id, message_id)
        );
        CREATE INDEX IF NOT EXISTS idx_messages_next_check
            ON messages (source, deleted, expired, next_check_at);
        CREATE INDEX IF NOT EXISTS idx_messages_source_date
            ON messages (source, date);
        CREATE INDEX IF NOT EXISTS idx_messages_chat_date
            ON messages (source, chat_id, date);

        CREATE TABLE IF NOT EXISTS business_connections (
            business_connection_id TEXT PRIMARY KEY,
            owner_id INTEGER NOT NULL,
            owner_chat_id INTEGER NOT NULL,
            is_enabled INTEGER NOT NULL DEFAULT 1,
            connected_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS custom_commands (
            chat_id INTEGER NOT NULL,
            trigger TEXT NOT NULL,
            response TEXT NOT NULL,
            PRIMARY KEY (chat_id, trigger)
        );

        CREATE TABLE IF NOT EXISTS streaks (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            user_name TEXT,
            last_date TEXT,
            streak INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (chat_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            trial_started_at INTEGER NOT NULL,
            subscribed_until INTEGER,
            subscription_tier TEXT,
            last_expiry_notice_at INTEGER,
            banned INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_users_username ON users (username);

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            method TEXT NOT NULL,
            plan TEXT NOT NULL,
            amount TEXT,
            external_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at INTEGER NOT NULL,
            confirmed_at INTEGER
        );

        CREATE TABLE IF NOT EXISTS referrals (
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL UNIQUE,
            created_at INTEGER NOT NULL,
            PRIMARY KEY (referrer_id, referred_id)
        );
        """
    )
    existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(settings)")}
    if "owner_id" not in existing_columns:
        conn.execute("ALTER TABLE settings ADD COLUMN owner_id INTEGER")
    if "owner_name" not in existing_columns:
        conn.execute("ALTER TABLE settings ADD COLUMN owner_name TEXT")
    message_columns = {row["name"] for row in conn.execute("PRAGMA table_info(messages)")}
    if "user_username" not in message_columns:
        conn.execute("ALTER TABLE messages ADD COLUMN user_username TEXT")
    if "media_path" not in message_columns:
        conn.execute("ALTER TABLE messages ADD COLUMN media_path TEXT")
    user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    if "banned" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN banned INTEGER NOT NULL DEFAULT 0")
    if "subscription_tier" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN subscription_tier TEXT")
    if "username" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN username TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users (username)")
    conn.commit()
    conn.close()


DEFAULT_SETTINGS = {
    "catch_deleted": 1,
    "catch_edited": 1,
    "catch_disappearing": 1,
    "chat_restore": 1,
    "flames": 1,
    "anti_scam": 1,
    "custom_commands": 1,
    "lang": "ru",
}


def get_settings(chat_id: int) -> dict:
    conn = db_connect()
    row = conn.execute("SELECT * FROM settings WHERE chat_id = ?", (chat_id,)).fetchone()
    if row is None:
        conn.execute("INSERT INTO settings (chat_id) VALUES (?)", (chat_id,))
        conn.commit()
        row = conn.execute("SELECT * FROM settings WHERE chat_id = ?", (chat_id,)).fetchone()
    conn.close()
    return dict(row)


def set_setting(chat_id: int, key: str, value) -> None:
    if key not in TOGGLE_KEYS and key != "lang":
        raise ValueError(f"Недопустимый ключ настройки: {key!r}")
    get_settings(chat_id)  # гарантирует наличие строки
    conn = db_connect()
    conn.execute(f"UPDATE settings SET {key} = ? WHERE chat_id = ?", (value, chat_id))
    conn.commit()
    conn.close()


def set_owner(chat_id: int, user_id: int, user_name: str) -> None:
    get_settings(chat_id)
    conn = db_connect()
    conn.execute(
        "UPDATE settings SET owner_id = ?, owner_name = ? WHERE chat_id = ?",
        (user_id, user_name, chat_id),
    )
    conn.commit()
    conn.close()


async def notify_chat_owner(chat_id: int, body: str, **kwargs) -> None:
    """Отправляет пойманное сообщение владельцу настроек группы в личку.
    Если владелец ещё не назначен (никто не запускал /settings) или бот
    не может ему написать (не нажимал /start в личке) — падаем обратно
    в группу, чтобы уведомление не потерялось молча."""
    settings = get_settings(chat_id)
    owner_id = settings.get("owner_id")
    if owner_id:
        if not await gate_by_trial(owner_id, require_group_access=True):
            return
        try:
            await bot.send_message(owner_id, body, **kwargs)
            return
        except (TelegramForbiddenError, TelegramBadRequest):
            logger.warning(
                "Не удалось отправить уведомление владельцу %s (чат %s) — шлю в группу",
                owner_id, chat_id,
            )
    await bot.send_message(chat_id, body, **kwargs)


# ==================== ПРОБНЫЙ ПЕРИОД И РЕФЕРАЛЫ ====================
def register_user(user_id: int, name: str, referrer_id: int = None, username: str = None) -> bool:
    """Регистрирует пользователя при первом обращении к боту (создаёт запись
    о начале пробного периода). Возвращает True, если пользователь новый.
    Если пришёл по реферальной ссылке — засчитывает реферала пригласившему
    (только для новых пользователей и только если реферер существует).
    Если передан username — держит его свежим и для уже существующих
    пользователей (нужно для поиска по @username в админке)."""
    conn = db_connect()
    row = conn.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)).fetchone()
    is_new = row is None
    now = int(time.time())
    if is_new:
        conn.execute(
            "INSERT INTO users (user_id, first_name, username, trial_started_at, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, name, username, now, now),
        )
        if referrer_id and referrer_id != user_id:
            referrer_exists = conn.execute(
                "SELECT 1 FROM users WHERE user_id = ?", (referrer_id,)
            ).fetchone()
            if referrer_exists:
                try:
                    conn.execute(
                        "INSERT INTO referrals (referrer_id, referred_id, created_at) VALUES (?, ?, ?)",
                        (referrer_id, user_id, now),
                    )
                except sqlite3.IntegrityError:
                    pass
    elif username:
        conn.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
    conn.commit()
    conn.close()
    return is_new


def get_trial_info(user_id: int) -> dict:
    conn = db_connect()
    row = conn.execute(
        "SELECT trial_started_at, subscribed_until FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    if row is None:
        conn.close()
        return None
    referral_count = conn.execute(
        "SELECT COUNT(*) c FROM referrals WHERE referrer_id = ?", (user_id,)
    ).fetchone()["c"]
    conn.close()
    trial_days = TRIAL_BASE_DAYS + referral_count * TRIAL_BONUS_DAYS_PER_REFERRAL
    trial_end = row["trial_started_at"] + trial_days * 86400
    subscribed_until = row["subscribed_until"] or 0
    active_until = max(trial_end, subscribed_until)
    now = int(time.time())
    return {
        "referral_count": referral_count,
        "trial_days": trial_days,
        "trial_end": trial_end,
        "subscribed_until": row["subscribed_until"],
        "active": now < active_until,
        "days_left": max(0, (active_until - now + 86399) // 86400),
    }


def is_trial_active(user_id: int) -> bool:
    info = get_trial_info(user_id)
    if info is None:
        return True  # ещё не встречались этому боту — не блокируем
    return info["active"]


async def maybe_notify_trial_expired(owner_id: int) -> None:
    """Шлёт напоминание об окончании пробного периода не чаще раза в сутки,
    чтобы не спамить владельца при каждой пойманной попытке удаления."""
    conn = db_connect()
    row = conn.execute(
        "SELECT last_expiry_notice_at FROM users WHERE user_id = ?", (owner_id,)
    ).fetchone()
    now = int(time.time())
    if row and row["last_expiry_notice_at"] and now - row["last_expiry_notice_at"] < 86400:
        conn.close()
        return
    conn.execute("UPDATE users SET last_expiry_notice_at = ? WHERE user_id = ?", (now, owner_id))
    conn.commit()
    conn.close()
    try:
        builder = InlineKeyboardBuilder()
        builder.button(text="🎁 Пригласить друга", callback_data="dm_referral")
        builder.button(text="💳 Оформить подписку", callback_data="dm_subscribe")
        builder.adjust(1)
        await bot.send_message(
            owner_id,
            "⏳ <b>Пробный период закончился</b>\n"
            f"{DIVIDER}\n\n"
            "Ловля удалённых и изменённых сообщений приостановлена.\n\n"
            "Пригласи друга (+2 дня за каждого) или оформи подписку, "
            "чтобы продолжить.",
            parse_mode="HTML",
            reply_markup=builder.as_markup(),
        )
    except Exception:
        logger.warning("Не удалось отправить уведомление об окончании триала %s", owner_id)


async def maybe_notify_pro_group_upgrade(owner_id: int) -> None:
    """Как maybe_notify_trial_expired, но для случая, когда у владельца
    действует PRO (личные чаты), а не MAX — группам PRO не полагается."""
    conn = db_connect()
    row = conn.execute(
        "SELECT last_expiry_notice_at FROM users WHERE user_id = ?", (owner_id,)
    ).fetchone()
    now = int(time.time())
    if row and row["last_expiry_notice_at"] and now - row["last_expiry_notice_at"] < 86400:
        conn.close()
        return
    conn.execute("UPDATE users SET last_expiry_notice_at = ? WHERE user_id = ?", (now, owner_id))
    conn.commit()
    conn.close()
    try:
        builder = InlineKeyboardBuilder()
        builder.button(text="💳 Улучшить до MAX", callback_data="dm_subscribe")
        await bot.send_message(
            owner_id,
            "🔒 <b>Это функция VICEGRAM MAX</b>\n"
            f"{DIVIDER}\n\n"
            "Твоя подписка PRO не включает работу в группах — только "
            "личные чаты. Улучши до MAX, чтобы ловить удаления и здесь.",
            parse_mode="HTML",
            reply_markup=builder.as_markup(),
        )
    except Exception:
        logger.warning("Не удалось отправить уведомление о PRO/MAX владельцу %s", owner_id)


async def gate_by_trial(owner_id: int, require_group_access: bool = False) -> bool:
    """True — можно доставлять пойманное сообщение.
    False — владелец забанен (молча), ничего не активно (уведомление про
    триал), либо у него PRO, а нужен доступ к группам, то есть MAX
    (уведомление с предложением апгрейда)."""
    if is_user_banned(owner_id):
        return False
    tier = get_active_tier(owner_id)
    if tier is None:
        await maybe_notify_trial_expired(owner_id)
        return False
    if require_group_access and tier != "max":
        await maybe_notify_pro_group_upgrade(owner_id)
        return False
    return True


def get_referral_link(bot_username: str, user_id: int) -> str:
    return f"https://t.me/{bot_username}?start=ref{user_id}"


def grant_subscription_days(user_id: int, days: int, tier: str = "max") -> int:
    """Продлевает подписку пользователя на N дней от текущего окончания
    (или от текущего момента, если подписка уже истекла/не оформлена) и
    выставляет тариф (по умолчанию max — так работают ручные продления
    админом). Возвращает новый timestamp окончания подписки."""
    register_user(user_id, None)
    conn = db_connect()
    row = conn.execute("SELECT subscribed_until FROM users WHERE user_id = ?", (user_id,)).fetchone()
    now = int(time.time())
    base = row["subscribed_until"] if row and row["subscribed_until"] and row["subscribed_until"] > now else now
    new_until = base + days * 86400
    conn.execute(
        "UPDATE users SET subscribed_until = ?, subscription_tier = ? WHERE user_id = ?",
        (new_until, tier, user_id),
    )
    conn.commit()
    conn.close()
    return new_until


def get_active_tier(user_id: int):
    """'max' | 'pro' | None. Во время бесплатного пробного периода — 'max'
    (полный доступ, как и раньше). None — вообще ничего не активно."""
    info = get_trial_info(user_id)
    if info is None:
        return "max"  # ещё не встречались этому боту — не блокируем (как и раньше)
    now = int(time.time())
    if info.get("subscribed_until") and info["subscribed_until"] > now:
        conn = db_connect()
        row = conn.execute(
            "SELECT subscription_tier FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        conn.close()
        return (row["subscription_tier"] if row and row["subscription_tier"] else "max")
    if info["active"]:
        return "max"  # ещё идёт бесплатный триал
    return None


def set_user_banned(user_id: int, banned: bool) -> None:
    register_user(user_id, None)
    conn = db_connect()
    conn.execute("UPDATE users SET banned = ? WHERE user_id = ?", (int(banned), user_id))
    conn.commit()
    conn.close()


def is_user_banned(user_id: int) -> bool:
    conn = db_connect()
    row = conn.execute("SELECT banned FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return bool(row and row["banned"])


def get_user_admin_summary(user_id: int) -> dict:
    conn = db_connect()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    info = get_trial_info(user_id) or {}
    return {
        "user_id": user_id,
        "first_name": row["first_name"],
        "username": row["username"],
        "banned": bool(row["banned"]),
        "subscribed_until": row["subscribed_until"],
        "trial_days_left": info.get("days_left"),
        "trial_active": info.get("active"),
        "referral_count": info.get("referral_count", 0),
    }


def find_user_id_by_username(username: str) -> int:
    """Регистронезависимый поиск user_id по @username (без @, ведущие/хвостовые
    пробелы уже обрезаны вызывающей стороной). None, если не найден."""
    conn = db_connect()
    row = conn.execute(
        "SELECT user_id FROM users WHERE username = ? COLLATE NOCASE", (username,)
    ).fetchone()
    conn.close()
    return row["user_id"] if row else None


def resolve_target_user_id(text: str):
    """Разбирает ввод админа: число — это user_id как есть (даже если
    пользователь ещё не писал боту — так можно выдать подписку заранее);
    @username или username — ищет среди уже писавших боту. None — не разобрал."""
    text = text.strip()
    if text.lstrip("-").isdigit():
        return int(text)
    username = text.lstrip("@").strip()
    return find_user_id_by_username(username) if username else None


def record_payment(user_id: int, method: str, plan: str, amount: str, external_id: str = None) -> int:
    conn = db_connect()
    cur = conn.execute(
        """
        INSERT INTO payments (user_id, method, plan, amount, external_id, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'pending', ?)
        """,
        (user_id, method, plan, amount, external_id, int(time.time())),
    )
    payment_id = cur.lastrowid
    conn.commit()
    conn.close()
    return payment_id


def confirm_payment(payment_id: int) -> dict:
    conn = db_connect()
    row = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
    if row is None or row["status"] == "confirmed":
        conn.close()
        return None
    conn.execute(
        "UPDATE payments SET status = 'confirmed', confirmed_at = ? WHERE id = ?",
        (int(time.time()), payment_id),
    )
    conn.commit()
    conn.close()
    return dict(row)


def get_payment(payment_id: int) -> dict:
    conn = db_connect()
    row = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_payment_external_id(payment_id: int, external_id: str) -> None:
    conn = db_connect()
    conn.execute("UPDATE payments SET external_id = ? WHERE id = ?", (external_id, payment_id))
    conn.commit()
    conn.close()


def get_total_user_count() -> int:
    conn = db_connect()
    count = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    conn.close()
    return count


def get_recent_payments(limit: int = 10):
    conn = db_connect()
    rows = conn.execute(
        "SELECT * FROM payments ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_bot_stats() -> dict:
    conn = db_connect()
    total_users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    now = int(time.time())
    active_subs = conn.execute(
        "SELECT COUNT(*) c FROM users WHERE subscribed_until IS NOT NULL AND subscribed_until > ?", (now,)
    ).fetchone()["c"]
    banned_count = conn.execute("SELECT COUNT(*) c FROM users WHERE banned = 1").fetchone()["c"]
    total_referrals = conn.execute("SELECT COUNT(*) c FROM referrals").fetchone()["c"]
    total_groups = conn.execute("SELECT COUNT(*) c FROM settings").fetchone()["c"]
    connected_dms = conn.execute(
        "SELECT COUNT(*) c FROM business_connections WHERE is_enabled = 1"
    ).fetchone()["c"]
    total_caught = conn.execute("SELECT COUNT(*) c FROM messages WHERE deleted = 1").fetchone()["c"]
    confirmed_payments = conn.execute(
        "SELECT COUNT(*) c FROM payments WHERE status = 'confirmed'"
    ).fetchone()["c"]
    conn.close()
    return {
        "total_users": total_users,
        "active_subs": active_subs,
        "banned_count": banned_count,
        "total_referrals": total_referrals,
        "total_groups": total_groups,
        "connected_dms": connected_dms,
        "total_caught": total_caught,
        "confirmed_payments": confirmed_payments,
    }


# ==================== ПЕРЕВОДЫ ====================
STRINGS = {
    "ru": {
        "settings_title": "⚙️ <b>Настройки</b>",
        "settings_body": "VICEGRAM всемогущий. Выбери что хочешь настроить:",
        "catch_deleted": "🗑 Удалённые сообщения",
        "catch_edited": "📝 Изменённые сообщения",
        "catch_disappearing": "⏳ Исчезающие медиа",
        "chat_restore": "📤 Восстановление чатов",
        "flames": "⚡ Огоньки в чатах",
        "anti_scam": "✋ Анти-скам",
        "custom_commands": "🤖 Команды в чатах",
        "lang": "🌐 Язык: 🇷🇺",
        "on": "включено ✅",
        "off": "выключено ❌",
        "enable": "✅ Включить",
        "disable": "❌ Выключить",
        "back": "🔙 Назад",
    },
    "en": {
        "settings_title": "⚙️ <b>Settings</b>",
        "settings_body": "VICEGRAM is all-powerful. Choose what to configure:",
        "catch_deleted": "🗑 Deleted messages",
        "catch_edited": "📝 Edited messages",
        "catch_disappearing": "⏳ Disappearing media",
        "chat_restore": "📤 Chat restoration",
        "flames": "⚡ Chat streaks",
        "anti_scam": "✋ Anti-scam",
        "custom_commands": "🤖 Chat commands",
        "lang": "🌐 Language: 🇬🇧",
        "on": "on ✅",
        "off": "off ❌",
        "enable": "✅ Enable",
        "disable": "❌ Disable",
        "back": "🔙 Back",
    },
}


def t(lang: str, key: str) -> str:
    return STRINGS.get(lang, STRINGS["ru"]).get(key, key)


TOGGLE_KEYS = [
    "catch_deleted",
    "catch_edited",
    "catch_disappearing",
    "chat_restore",
    "flames",
    "anti_scam",
    "custom_commands",
]

# ==================== АНТИ-СКАМ ====================
SCAM_PATTERNS = [
    r"заработ\w*\s+без\s+вложен",
    r"гарантирован\w*\s+доход",
    r"инвестици\w*\s+от\s+\d+\s*%",
    r"переведи(те)?\s+предоплат",
    r"криптоподарок|crypto\s*giveaway",
    r"выигра(л|ли|ла)\w*\s+в\s+розыгрыш",
    r"напиши(те)?\s+в\s+лс\s+для\s+получен",
    r"удвои\w*\s+(деньги|биткоин|крипту)",
    r"free\s+airdrop",
    r"only\s*fans.*скидк",
]
SCAM_RE = re.compile("|".join(SCAM_PATTERNS), re.IGNORECASE)


def looks_like_scam(text: str) -> bool:
    return bool(text) and bool(SCAM_RE.search(text))


# ==================== ПОМОЩНИКИ ====================
def user_mention(user_id: int, name: str, username: str = None) -> str:
    safe_name = html.escape(name) if name else "пользователь"
    label = f'<a href="tg://user?id={user_id}">{safe_name}</a>'
    if username:
        label += f" (@{username})"
    return label


def format_author(name: str, username: str = None) -> str:
    """Как user_mention, но без кликабельной ссылки — для случаев без user_id."""
    safe_name = html.escape(name) if name else "неизвестный"
    return f"{safe_name} (@{username})" if username else safe_name


async def is_group_admin(chat_id: int, user_id: int) -> bool:
    if is_bot_admin(user_id):
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)
    except Exception:
        return False


def extract_media(message: Message):
    """Возвращает (media_type, file_id) для стикеров/файлов/гифок/фото/видео и т.п."""
    if message.sticker:
        return "sticker", message.sticker.file_id
    if message.animation:
        return "animation", message.animation.file_id
    if message.document:
        return "document", message.document.file_id
    if message.photo:
        return "photo", message.photo[-1].file_id
    if message.video:
        return "video", message.video.file_id
    if message.video_note:
        return "video_note", message.video_note.file_id
    if message.voice:
        return "voice", message.voice.file_id
    if message.audio:
        return "audio", message.audio.file_id
    return None, None


async def repost_media(chat_id: int, media_type: str, file_id: str, caption: str = None):
    kwargs = {"caption": caption, "parse_mode": "HTML"} if caption else {}
    if media_type == "sticker":
        await bot.send_sticker(chat_id, file_id)
        if caption:
            await bot.send_message(chat_id, caption, parse_mode="HTML")
    elif media_type == "animation":
        await bot.send_animation(chat_id, file_id, **kwargs)
    elif media_type == "document":
        await bot.send_document(chat_id, file_id, **kwargs)
    elif media_type == "photo":
        await bot.send_photo(chat_id, file_id, **kwargs)
    elif media_type == "video":
        await bot.send_video(chat_id, file_id, **kwargs)
    elif media_type == "video_note":
        await bot.send_video_note(chat_id, file_id)
        if caption:
            await bot.send_message(chat_id, caption, parse_mode="HTML")
    elif media_type == "voice":
        await bot.send_voice(chat_id, file_id, **kwargs)
    elif media_type == "audio":
        await bot.send_audio(chat_id, file_id, **kwargs)


async def download_media_copy(file_id: str, owner_id: int, chat_id: int, message_id: int) -> str:
    """Сразу скачивает копию медиа на диск. Нужно для личных чатов: если
    фото/видео самоуничтожается после просмотра, Telegram может отозвать
    доступ к file_id ещё до того, как придёт событие удаления — тогда
    переслать поймать удаление уже будет нечем. Скачивание сразу при
    получении подстраховывает от этого."""
    try:
        path = os.path.join(MEDIA_CACHE_DIR, f"{owner_id}_{chat_id}_{message_id}")
        result = await bot.download(file_id, destination=path)
        return path if result else None
    except Exception:
        logger.warning("Не удалось заранее скачать медиа %s", file_id)
        return None


# ==================== КЭШИРОВАНИЕ СООБЩЕНИЙ ====================
BACKOFF_SCHEDULE = [30, 60, 120, 300, 900, 1800, 3600]  # секунды
MAX_MESSAGE_AGE = 48 * 3600  # после этого возраста перестаём проверять


def cache_message(message: Message) -> None:
    media_type, file_id = extract_media(message)
    text = message.text or message.caption
    now = int(time.time())
    conn = db_connect()
    conn.execute(
        """
        INSERT OR REPLACE INTO messages
            (source, owner_id, chat_id, message_id, user_id, user_name, user_username, text,
             media_type, file_id, date, deleted, expired, check_count, next_check_at)
        VALUES ('group_bot', 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, ?)
        """,
        (
            message.chat.id,
            message.message_id,
            message.from_user.id if message.from_user else None,
            message.from_user.full_name if message.from_user else None,
            message.from_user.username if message.from_user else None,
            text,
            media_type,
            file_id,
            now,
            now + BACKOFF_SCHEDULE[0],
        ),
    )
    conn.commit()
    conn.close()


def get_cached_message(chat_id: int, message_id: int):
    conn = db_connect()
    row = conn.execute(
        "SELECT * FROM messages WHERE source = 'group_bot' AND owner_id = 0 AND chat_id = ? AND message_id = ?",
        (chat_id, message_id),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_cached_text(chat_id: int, message_id: int, new_text: str) -> None:
    conn = db_connect()
    conn.execute(
        "UPDATE messages SET text = ? WHERE source = 'group_bot' AND owner_id = 0 AND chat_id = ? AND message_id = ?",
        (new_text, chat_id, message_id),
    )
    conn.commit()
    conn.close()


# ==================== ОГОНЬКИ (СТРИКИ АКТИВНОСТИ) ====================
def update_streak(chat_id: int, user_id: int, user_name: str) -> None:
    today = datetime.now(timezone.utc).date().isoformat()
    conn = db_connect()
    row = conn.execute(
        "SELECT * FROM streaks WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO streaks (chat_id, user_id, user_name, last_date, streak) VALUES (?, ?, ?, ?, 1)",
            (chat_id, user_id, user_name, today),
        )
    else:
        last_date = row["last_date"]
        if last_date == today:
            pass  # уже засчитан сегодня
        else:
            yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
            new_streak = row["streak"] + 1 if last_date == yesterday else 1
            conn.execute(
                "UPDATE streaks SET user_name = ?, last_date = ?, streak = ? WHERE chat_id = ? AND user_id = ?",
                (user_name, today, new_streak, chat_id, user_id),
            )
    conn.commit()
    conn.close()


def get_streak_leaderboard(chat_id: int, limit: int = 10):
    conn = db_connect()
    rows = conn.execute(
        "SELECT user_name, streak FROM streaks WHERE chat_id = ? ORDER BY streak DESC LIMIT ?",
        (chat_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ==================== КАСТОМНЫЕ КОМАНДЫ ====================
def add_custom_command(chat_id: int, trigger: str, response: str) -> None:
    conn = db_connect()
    conn.execute(
        "INSERT OR REPLACE INTO custom_commands (chat_id, trigger, response) VALUES (?, ?, ?)",
        (chat_id, trigger.lower(), response),
    )
    conn.commit()
    conn.close()


def remove_custom_command(chat_id: int, trigger: str) -> None:
    conn = db_connect()
    conn.execute(
        "DELETE FROM custom_commands WHERE chat_id = ? AND trigger = ?",
        (chat_id, trigger.lower()),
    )
    conn.commit()
    conn.close()


def list_custom_commands(chat_id: int):
    conn = db_connect()
    rows = conn.execute(
        "SELECT trigger, response FROM custom_commands WHERE chat_id = ? ORDER BY trigger", (chat_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def find_custom_command(chat_id: int, text: str):
    conn = db_connect()
    row = conn.execute(
        "SELECT response FROM custom_commands WHERE chat_id = ? AND trigger = ?",
        (chat_id, (text or "").strip().lower()),
    ).fetchone()
    conn.close()
    return row["response"] if row else None


# в памяти: ожидание ввода триггера/ответа для новой команды, ключ (chat_id, user_id)
PENDING_COMMAND_INPUT: dict[tuple[int, int], dict] = {}

# ==================== КЛАВИАТУРЫ ====================
def get_settings_menu(chat_id: int):
    settings = get_settings(chat_id)
    lang = settings["lang"]
    builder = InlineKeyboardBuilder()
    for key in TOGGLE_KEYS:
        state = "✅" if settings[key] else "❌"
        builder.button(text=f"{state} {t(lang, key)}", callback_data=f"open:{key}")
    builder.button(text=t(lang, "lang"), callback_data="open:lang")
    owner_name = settings.get("owner_name") or "никто"
    builder.button(text=f"📩 Уведомления получает: {owner_name}", callback_data="claim_owner")
    builder.adjust(1)
    return builder.as_markup()


def get_toggle_menu(chat_id: int, key: str):
    settings = get_settings(chat_id)
    lang = settings["lang"]
    builder = InlineKeyboardBuilder()
    builder.button(text=t(lang, "enable"), callback_data=f"toggle:{key}:1")
    builder.button(text=t(lang, "disable"), callback_data=f"toggle:{key}:0")
    builder.adjust(2)
    if key == "custom_commands":
        builder.row(InlineKeyboardButton(text="➕ Добавить команду", callback_data="cmd_add"))
        builder.row(InlineKeyboardButton(text="📋 Список команд", callback_data="cmd_list"))
    builder.row(InlineKeyboardButton(text=t(lang, "back"), callback_data="open:main"))
    return builder.as_markup()


def get_lang_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="🇷🇺 Русский", callback_data="lang:ru")
    builder.button(text="🇬🇧 English", callback_data="lang:en")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="open:main"))
    return builder.as_markup()


# ==================== ОБРАБОТЧИКИ: СЕРВИСНЫЕ ====================
def build_intro_text() -> str:
    return (
        "🎣 <b>VICEGRAM</b> — ловец пропавших сообщений\n\n"
        "Бот, от которого ничего не скроется. Вот что я умею:\n\n"
        "🗑 <b>Ловлю удалённые сообщения</b> — увидишь, что от тебя скрыли\n"
        "📝 <b>Ловлю изменённые сообщения</b> — покажу старый и новый текст рядом\n"
        "🎭 <b>Стикеры, файлы, гифки</b> — ловятся вместе с текстом, ничего не теряется\n"
        "⏳ <b>Исчезающие фото и видео</b> — сохраняю копию даже после самоуничтожения\n"
        "⚡ <b>Огоньки активности</b> — рейтинг самых активных в чате\n"
        "✋ <b>Анти-скам</b> — чищу мошеннические сообщения на автомате\n"
        "🤖 <b>Свои команды</b> — настрой ответы бота под конкретный чат\n"
        "📤 <b>Восстановление истории</b> — выгрузка переписки одним кликом\n"
        "🌐 <b>Два языка</b> — русский и английский\n\n"
        f"{DIVIDER}\n"
        "Работаю и в личных чатах, и в группах. Начнём с личных — "
        "это займёт меньше минуты."
    )


def get_intro_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔌 Настроить бота", callback_data="dm_setup")
    builder.button(text="🎁 Пригласить друга (+2 дня)", callback_data="dm_referral")
    builder.button(text="💳 Оформить подписку", callback_data="dm_subscribe")
    builder.adjust(1)
    return builder.as_markup()


async def send_dm_screen(
    message: Message, caption: str, reply_markup=None, photo_path: str = LOGO_PATH
) -> None:
    """Отправляет "экран" онбординга в личке — фото + подпись одним сообщением."""
    await message.answer_photo(
        FSInputFile(photo_path), caption=caption, parse_mode="HTML", reply_markup=reply_markup
    )


async def edit_dm_screen(
    callback: CallbackQuery, caption: str, reply_markup=None, photo_path: str = LOGO_PATH
) -> None:
    """Переключает "экран" онбординга на новый текст/фото через edit_media
    (так можно менять и подпись, и саму картинку за один вызов). Если
    предыдущее сообщение почему-то было текстовым (старые чаты до
    добавления фото) — просто пересоздаёт сообщение с фото."""
    from aiogram.types import InputMediaPhoto

    try:
        media = InputMediaPhoto(media=FSInputFile(photo_path), caption=caption, parse_mode="HTML")
        await callback.message.edit_media(media=media, reply_markup=reply_markup)
    except TelegramBadRequest:
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
        await send_dm_screen(callback.message, caption, reply_markup, photo_path)


def build_setup_instructions(username: str) -> str:
    return (
        "🔐 <b>Подключение личных чатов</b>\n"
        f"{DIVIDER}\n\n"
        "1️⃣ Открой Настройки Telegram → «Изменить»\n"
        "2️⃣ Найди пункт «Автоматизация чатов»\n"
        f"3️⃣ Впиши <code>@{username}</code> → «Добавить»\n"
        "4️⃣ Выбери «Все личные чаты, кроме…» (или только нужные)\n\n"
        "Готово! Как только подключишь — я сам напишу сюда с "
        "подтверждением ✅"
    )


def get_setup_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 А если нужны группы?", callback_data="dm_group_info")
    builder.button(text="🔙 Назад", callback_data="dm_home")
    builder.adjust(1)
    return builder.as_markup()


def build_group_instructions() -> str:
    return (
        "👥 <b>Ловля в группах</b>\n"
        f"{DIVIDER}\n\n"
        "Группы технически не входят в «Автоматизацию чатов» — Telegram "
        "не даёт её на них распространить, это отдельный механизм только "
        "для личных переписок. Для групп есть свой привычный способ:\n\n"
        "1️⃣ Добавь меня в нужную группу\n"
        "2️⃣ Выдай права администратора (минимум — удаление сообщений и "
        "чтение истории)\n"
        "3️⃣ Напиши в группе /settings — там же настроишь всё: удалённые/"
        "изменённые сообщения, анти-скам, огоньки, команды и язык"
    )


def get_group_info_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="dm_home")
    return builder.as_markup()


def build_features_menu_text(user_id: int = None) -> str:
    trial_line = ""
    if user_id is not None:
        info = get_trial_info(user_id)
        if info:
            trial_line = f"\n\n⏳ Пробный период: <b>{info['days_left']} дн.</b> осталось"
    return (
        "🎉 <b>Готово, личные чаты подключены!</b>\n"
        f"{DIVIDER}\n\n"
        "Буду присылать сюда пойманные удалённые и изменённые сообщения, "
        "включая исчезающие фото и видео."
        f"{trial_line}\n\n"
        "Что ещё можно посмотреть:"
    )


def get_features_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Все возможности", callback_data="dm_features")
    builder.button(text="👥 Настроить в группе", callback_data="dm_group_info")
    builder.button(text="🎁 Пригласить друга (+2 дня)", callback_data="dm_referral")
    builder.button(text="💳 Оформить подписку", callback_data="dm_subscribe")
    builder.adjust(1)
    return builder.as_markup()


def build_referral_text(bot_username: str, user_id: int) -> str:
    info = get_trial_info(user_id) or {
        "referral_count": 0,
        "trial_days": TRIAL_BASE_DAYS,
        "days_left": TRIAL_BASE_DAYS,
    }
    link = get_referral_link(bot_username, user_id)
    return (
        "🎁 <b>Реферальная программа</b>\n"
        f"{DIVIDER}\n\n"
        f"Бесплатный пробный период — {TRIAL_BASE_DAYS} дней. За каждого друга, "
        f"который подключит VICEGRAM по твоей ссылке — +{TRIAL_BONUS_DAYS_PER_REFERRAL} дня.\n\n"
        f"Твоя ссылка:\n<code>{link}</code>\n\n"
        f"👥 Приглашено друзей: <b>{info['referral_count']}</b>\n"
        f"⏳ Осталось дней: <b>{info['days_left']}</b>"
    )


def get_referral_keyboard(bot_username: str, user_id: int):
    link = get_referral_link(bot_username, user_id)
    share_url = f"https://t.me/share/url?url={link}&text=Ловит удалённые и изменённые сообщения в Telegram — попробуй VICEGRAM"
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📤 Поделиться ссылкой", url=share_url))
    builder.row(InlineKeyboardButton(text="💳 Оформить подписку", callback_data="dm_subscribe"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="dm_home"))
    return builder.as_markup()


# ==================== ПОДПИСКА: ВЫБОР ТАРИФА → СРОКА → СПОСОБА ОПЛАТЫ ====================
def build_tier_selection_text() -> str:
    max_from = min(p["rub"] for p in iter_plans("max"))
    pro_from = min(p["rub"] for p in iter_plans("pro"))
    return (
        "💳 <b>Подписка VICEGRAM</b>\n"
        f"{DIVIDER}\n\n"
        f"🚀 <b>{SUBSCRIPTION_TIERS['max']['name']}</b>\n"
        f"{SUBSCRIPTION_TIERS['max']['tagline']}\n"
        f"от {max_from}₽\n\n"
        f"⭐ <b>{SUBSCRIPTION_TIERS['pro']['name']}</b>\n"
        f"{SUBSCRIPTION_TIERS['pro']['tagline']}\n"
        f"от {pro_from}₽\n\n"
        "Выбери тариф:"
    )


def get_tier_selection_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 VICEGRAM MAX", callback_data="sub_tier:max")
    builder.button(text="⭐ VICEGRAM PRO", callback_data="sub_tier:pro")
    builder.button(text="🔙 Назад", callback_data="dm_home")
    builder.adjust(1)
    return builder.as_markup()


@dp.callback_query(F.data == "dm_subscribe")
async def cb_dm_subscribe(callback: CallbackQuery):
    await callback.answer()
    register_user(callback.from_user.id, callback.from_user.full_name, username=callback.from_user.username)
    await edit_dm_screen(callback, build_tier_selection_text(), get_tier_selection_keyboard())


def build_duration_selection_text(tier_code: str) -> str:
    tier = SUBSCRIPTION_TIERS[tier_code]
    lines = [f"💳 <b>{tier['name']}</b>", tier["tagline"], f"{DIVIDER}", ""]
    for plan in iter_plans(tier_code):
        line = f"• {plan['duration_label']} — {plan['rub']}₽"
        if plan["joke"]:
            line += f"\n  {plan['joke']}"
        lines.append(line)
    lines.append("")
    lines.append("Цена в Stars — 1:1 к рублю. Выбери срок:")
    return "\n".join(lines)


def get_duration_selection_keyboard(tier_code: str):
    builder = InlineKeyboardBuilder()
    for plan in iter_plans(tier_code):
        builder.button(text=f"{plan['duration_label']} — {plan['rub']}₽", callback_data=f"sub_plan:{plan['code']}")
    builder.button(text="🔙 Назад", callback_data="dm_subscribe")
    builder.adjust(1)
    return builder.as_markup()


@dp.callback_query(F.data.startswith("sub_tier:"))
async def cb_sub_tier(callback: CallbackQuery):
    tier_code = callback.data.split(":", 1)[1]
    if tier_code not in SUBSCRIPTION_TIERS:
        await callback.answer("Неизвестный тариф", show_alert=True)
        return
    await callback.answer()
    await edit_dm_screen(
        callback, build_duration_selection_text(tier_code), get_duration_selection_keyboard(tier_code)
    )


def build_payment_method_text(plan: dict) -> str:
    joke_line = f"\n{plan['joke']}\n" if plan["joke"] else ""
    return (
        f"💳 <b>{plan['label']}</b>\n"
        f"{DIVIDER}\n\n"
        f"{plan['tier_tagline']}{joke_line}\n\n"
        f"⭐ {plan['stars']} Stars — оплата прямо в Telegram\n"
        f"💎 {plan['usdt']} USDT — крипта через @CryptoBot\n"
        "🏦 Перевод — переписка с администратором в отдельном чате\n\n"
        "Выбери способ оплаты:"
    )


def get_payment_method_keyboard(plan: dict):
    builder = InlineKeyboardBuilder()
    builder.button(text=f"⭐ Stars — {plan['stars']}", callback_data=f"pay_stars:{plan['code']}")
    if CRYPTOBOT_API_TOKEN:
        builder.button(text=f"💎 Крипта — {plan['usdt']} USDT", callback_data=f"pay_crypto:{plan['code']}")
    builder.button(text="🏦 Перевод администратору", url=build_manual_payment_url(plan))
    builder.button(text="🔙 Назад", callback_data=f"sub_tier:{plan['tier_code']}")
    builder.adjust(1)
    return builder.as_markup()


@dp.callback_query(F.data.startswith("sub_plan:"))
async def cb_sub_plan(callback: CallbackQuery):
    plan_code = callback.data.split(":", 1)[1]
    try:
        plan = get_plan(plan_code)
    except (KeyError, StopIteration, ValueError):
        await callback.answer("Неизвестный план", show_alert=True)
        return
    await callback.answer()
    await edit_dm_screen(callback, build_payment_method_text(plan), get_payment_method_keyboard(plan))


@dp.callback_query(F.data.startswith("pay_stars:"))
async def cb_pay_stars(callback: CallbackQuery):
    plan_code = callback.data.split(":", 1)[1]
    try:
        plan = get_plan(plan_code)
    except (KeyError, StopIteration, ValueError):
        await callback.answer("Неизвестный план", show_alert=True)
        return
    await callback.answer()
    payment_id = record_payment(callback.from_user.id, "stars", plan["code"], f"{plan['stars']} XTR")
    try:
        await bot.send_invoice(
            chat_id=callback.from_user.id,
            title=plan["label"],
            description=f"Подписка {plan['label']} на {plan['days']} дней",
            payload=f"sub:{plan['code']}:{payment_id}",
            currency="XTR",
            prices=[LabeledPrice(label=plan["label"], amount=plan["stars"])],
        )
    except Exception:
        logger.exception("Не удалось выставить счёт в Stars")
        await callback.message.answer("⚠️ Не получилось выставить счёт. Попробуй ещё раз чуть позже.")


@dp.pre_checkout_query()
async def handle_pre_checkout(pre_checkout_query) -> None:
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@dp.message(F.successful_payment)
async def handle_successful_payment(message: Message) -> None:
    payload = message.successful_payment.invoice_payload
    parts = payload.split(":")
    if len(parts) != 3 or parts[0] != "sub":
        return
    _, plan_code, payment_id_str = parts
    try:
        payment_id = int(payment_id_str)
        plan = get_plan(plan_code)
    except (ValueError, KeyError, StopIteration):
        return
    confirm_payment(payment_id)
    new_until = grant_subscription_days(message.from_user.id, plan["days"], tier=plan["tier_code"])
    until_str = datetime.fromtimestamp(new_until, tz=timezone.utc).strftime("%d.%m.%Y")
    await message.answer(
        f"✅ <b>Оплата получена!</b>\n{DIVIDER}\n\n"
        f"{plan['tier_name']} активен до <b>{until_str}</b>. Спасибо за поддержку VICEGRAM! 🎉",
        parse_mode="HTML",
    )


# ==================== ОПЛАТА: CRYPTOBOT (CRYPTO PAY API) ====================
async def cryptobot_create_invoice(amount: float, asset: str, description: str, payload: str) -> dict:
    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_API_TOKEN}
    data = {"asset": asset, "amount": str(amount), "description": description, "payload": payload}
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{CRYPTOBOT_API_URL}/createInvoice", json=data, headers=headers) as resp:
            result = await resp.json()
    if not result.get("ok"):
        raise RuntimeError(f"CryptoBot createInvoice error: {result}")
    return result["result"]


async def cryptobot_get_invoice_status(invoice_id: int) -> str:
    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_API_TOKEN}
    params = {"invoice_ids": str(invoice_id)}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{CRYPTOBOT_API_URL}/getInvoices", params=params, headers=headers) as resp:
            result = await resp.json()
    if not result.get("ok"):
        return "unknown"
    items = result["result"]["items"]
    return items[0]["status"] if items else "unknown"


@dp.callback_query(F.data.startswith("pay_crypto:"))
async def cb_pay_crypto(callback: CallbackQuery):
    plan_code = callback.data.split(":", 1)[1]
    try:
        plan = get_plan(plan_code)
    except (KeyError, StopIteration, ValueError):
        await callback.answer("Неизвестный план", show_alert=True)
        return
    await callback.answer()
    if not CRYPTOBOT_API_TOKEN:
        await callback.message.answer("⚠️ Оплата криптой сейчас недоступна.")
        return
    payment_id = record_payment(callback.from_user.id, "crypto", plan["code"], f"{plan['usdt']} USDT")
    try:
        invoice = await cryptobot_create_invoice(
            plan["usdt"], "USDT", f"Подписка {plan['label']}", f"sub:{plan['code']}:{payment_id}"
        )
    except Exception:
        logger.exception("Не удалось создать счёт CryptoBot")
        await callback.message.answer("⚠️ Не получилось создать счёт. Попробуй позже.")
        return
    update_payment_external_id(payment_id, str(invoice["invoice_id"]))
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💎 Оплатить", url=invoice["pay_url"]))
    builder.row(InlineKeyboardButton(text="✅ Я оплатил — проверить", callback_data=f"check_crypto:{payment_id}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"sub_plan:{plan['code']}"))
    await callback.message.answer(
        f"💎 <b>Оплата криптой</b>\n{DIVIDER}\n\n"
        f"Сумма: {plan['usdt']} USDT\n\n"
        "Нажми «Оплатить», заверши платёж в @CryptoBot, затем вернись сюда "
        "и нажми «Я оплатил — проверить».",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )


@dp.callback_query(F.data.startswith("check_crypto:"))
async def cb_check_crypto(callback: CallbackQuery):
    payment_id = int(callback.data.split(":")[1])
    payment = get_payment(payment_id)
    if not payment:
        await callback.answer("Платёж не найден", show_alert=True)
        return
    if payment["status"] == "confirmed":
        await callback.answer("Уже подтверждено ✅", show_alert=True)
        return
    if not payment["external_id"]:
        await callback.answer("Счёт ещё создаётся, попробуй через минуту", show_alert=True)
        return
    status = await cryptobot_get_invoice_status(int(payment["external_id"]))
    if status == "paid":
        try:
            plan = get_plan(payment["plan"])
        except (KeyError, StopIteration, ValueError):
            await callback.answer("Неизвестный план платежа", show_alert=True)
            return
        confirm_payment(payment_id)
        new_until = grant_subscription_days(payment["user_id"], plan["days"], tier=plan["tier_code"])
        until_str = datetime.fromtimestamp(new_until, tz=timezone.utc).strftime("%d.%m.%Y")
        await callback.answer("✅ Оплата подтверждена!", show_alert=True)
        await callback.message.answer(
            f"✅ <b>Оплата получена!</b>\n{DIVIDER}\n\n{plan['tier_name']} активен до <b>{until_str}</b>. "
            "Спасибо за поддержку VICEGRAM! 🎉",
            parse_mode="HTML",
        )
    else:
        await callback.answer("Пока не вижу оплату. Попробуй ещё раз через минуту.", show_alert=True)


# ==================== ОПЛАТА: РУЧНОЙ ПЕРЕВОД ====================
# Кнопка "Перевод администратору" — прямая ссылка на чат с готовым текстом
# заявки (см. build_manual_payment_url), без промежуточных экранов в самом
# боте. Дальше клиент и админ договариваются в том чате напрямую, а админ
# продлевает подписку вручную через /admin.


@dp.callback_query(F.data.startswith("admin_confirm_pay:"))
async def cb_admin_confirm_pay(callback: CallbackQuery):
    if not is_bot_admin(callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    payment_id = int(callback.data.split(":")[1])
    payment = get_payment(payment_id)
    if not payment or payment["status"] == "confirmed":
        await callback.answer("Платёж не найден или уже подтверждён", show_alert=True)
        return
    try:
        plan = get_plan(payment["plan"])
    except (KeyError, StopIteration, ValueError):
        await callback.answer("Неизвестный план платежа", show_alert=True)
        return
    confirm_payment(payment_id)
    new_until = grant_subscription_days(payment["user_id"], plan["days"], tier=plan["tier_code"])
    until_str = datetime.fromtimestamp(new_until, tz=timezone.utc).strftime("%d.%m.%Y")
    await callback.answer("✅ Подтверждено")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await callback.message.answer(f"✅ Платёж #{payment_id} подтверждён администратором {callback.from_user.full_name}.")
    try:
        await bot.send_message(
            payment["user_id"],
            f"✅ <b>Оплата получена!</b>\n{DIVIDER}\n\n{plan['tier_name']} активен до <b>{until_str}</b>. "
            "Спасибо за поддержку VICEGRAM! 🎉",
            parse_mode="HTML",
        )
    except Exception:
        logger.warning("Не удалось уведомить пользователя %s о подтверждении оплаты", payment["user_id"])


@dp.callback_query(F.data.startswith("admin_reject_pay:"))
async def cb_admin_reject_pay(callback: CallbackQuery):
    if not is_bot_admin(callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    payment_id = int(callback.data.split(":")[1])
    payment = get_payment(payment_id)
    if not payment:
        await callback.answer("Платёж не найден", show_alert=True)
        return
    conn = db_connect()
    conn.execute("UPDATE payments SET status = 'rejected' WHERE id = ?", (payment_id,))
    conn.commit()
    conn.close()
    await callback.answer("❌ Отклонено")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await callback.message.answer(f"❌ Платёж #{payment_id} отклонён администратором {callback.from_user.full_name}.")
    try:
        await bot.send_message(
            payment["user_id"],
            f"❌ Заявка на оплату (#{payment_id}) отклонена администратором. "
            "Если это ошибка — напиши в поддержку.",
        )
    except Exception:
        logger.warning("Не удалось уведомить пользователя %s об отклонении оплаты", payment["user_id"])


# ==================== ПАНЕЛЬ АДМИНИСТРАТОРА ====================
PENDING_ADMIN_INPUT: dict[int, dict] = {}


def get_all_user_ids() -> list:
    conn = db_connect()
    rows = conn.execute("SELECT user_id FROM users").fetchall()
    conn.close()
    return [r["user_id"] for r in rows]


def get_admin_panel_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="👤 Найти пользователя", callback_data="admin_find_user")
    builder.button(text="➕ Продлить подписку", callback_data="admin_extend")
    builder.button(text="📢 Рассылка", callback_data="admin_broadcast")
    builder.button(text="💰 Платежи", callback_data="admin_payments")
    builder.button(text="ℹ️ Инструкция", callback_data="admin_help")
    builder.adjust(1)
    return builder.as_markup()


def build_admin_help_text() -> str:
    return (
        "ℹ️ <b>Как управлять подписками</b>\n"
        f"{DIVIDER}\n\n"
        "👤 <b>Найти пользователя</b> — вводишь user_id <b>или @username</b>, "
        "видишь статус триала/подписки/бана, оттуда же можно продлить на "
        "30 дней или забанить.\n\n"
        "➕ <b>Продлить подписку</b> — вводишь user_id (или @username) и "
        "количество дней вручную (любое число, не только 30) — прибавится "
        "к текущей подписке, либо начнётся от сегодняшнего дня, если её "
        "не было.\n\n"
        "🏦 <b>Ручные платежи</b> — кнопка «Перевод администратору» сразу "
        "открывает клиенту чат с готовым текстом заявки (тариф и цена в "
        "рублях), минуя бота. Договорившись об оплате там, продли клиенту "
        "подписку вручную через «👤 Найти пользователя» → «➕ Продлить».\n\n"
        "⭐💎 <b>Stars и крипта</b> — подтверждаются автоматически (Stars — "
        "сразу, крипта — по кнопке «Я оплатил»), но если что-то пошло не "
        "так, заявку всё равно можно подтвердить/отклонить вручную кнопкой "
        "в разделе «💰 Платежи».\n\n"
        "📢 <b>Рассылка</b> — текст уйдёт всем, кто хоть раз писал "
        "боту /start (в личке или как владелец группы).\n\n"
        "🚫 <b>Бан</b> — забаненный не получает ответы бота нигде: ни в "
        "группах, ни в личке, ни в подключённых бизнес-чатах.\n\n"
        "ID админов бота (могут делать всё вышеперечисленное): "
        + ", ".join(f"<code>{aid}</code>" for aid in sorted(ADMIN_IDS))
    )


@dp.message(Command("admin"), F.chat.type == ChatType.PRIVATE)
async def cmd_admin(message: Message):
    if not is_bot_admin(message.from_user.id):
        return
    await message.answer(
        "🛠 <b>Панель администратора VICEGRAM</b>",
        parse_mode="HTML",
        reply_markup=get_admin_panel_keyboard(),
    )


@dp.message(Command("stats"), F.chat.type == ChatType.PRIVATE)
async def cmd_stats(message: Message):
    if not is_bot_admin(message.from_user.id):
        return
    s = get_bot_stats()
    text = (
        "📊 <b>Статистика VICEGRAM</b>\n"
        f"{DIVIDER}\n\n"
        f"👥 Пользователей всего: <b>{s['total_users']}</b>\n"
        f"💳 Активных платных подписок: <b>{s['active_subs']}</b>\n"
        f"🚫 Забанено: <b>{s['banned_count']}</b>\n"
        f"🎁 Рефералов всего: <b>{s['total_referrals']}</b>\n"
        f"👥 Групп настроено: <b>{s['total_groups']}</b>\n"
        f"💬 Личных подключений (Business): <b>{s['connected_dms']}</b>\n"
        f"🗑 Поймано удалений всего: <b>{s['total_caught']}</b>\n"
        f"✅ Подтверждённых платежей: <b>{s['confirmed_payments']}</b>"
    )
    await message.answer(text, parse_mode="HTML")


@dp.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: CallbackQuery):
    if not is_bot_admin(callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        "🛠 <b>Панель администратора VICEGRAM</b>", parse_mode="HTML", reply_markup=get_admin_panel_keyboard()
    )


@dp.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery):
    if not is_bot_admin(callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    await callback.answer()
    s = get_bot_stats()
    text = (
        "📊 <b>Статистика VICEGRAM</b>\n"
        f"{DIVIDER}\n\n"
        f"👥 Пользователей всего: <b>{s['total_users']}</b>\n"
        f"💳 Активных платных подписок: <b>{s['active_subs']}</b>\n"
        f"🚫 Забанено: <b>{s['banned_count']}</b>\n"
        f"🎁 Рефералов всего: <b>{s['total_referrals']}</b>\n"
        f"👥 Групп настроено: <b>{s['total_groups']}</b>\n"
        f"💬 Личных подключений (Business): <b>{s['connected_dms']}</b>\n"
        f"🗑 Поймано удалений всего: <b>{s['total_caught']}</b>\n"
        f"✅ Подтверждённых платежей: <b>{s['confirmed_payments']}</b>"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_panel")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())


@dp.callback_query(F.data == "admin_help")
async def cb_admin_help(callback: CallbackQuery):
    if not is_bot_admin(callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_panel")
    await callback.message.edit_text(build_admin_help_text(), parse_mode="HTML", reply_markup=builder.as_markup())


@dp.callback_query(F.data == "admin_payments")
async def cb_admin_payments(callback: CallbackQuery):
    if not is_bot_admin(callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    await callback.answer()
    payments = get_recent_payments(15)
    builder = InlineKeyboardBuilder()
    if not payments:
        text = f"💰 <b>Платежи</b>\n{DIVIDER}\n\nПлатежей пока нет."
    else:
        status_emoji = {"confirmed": "✅", "pending": "⏳", "rejected": "❌"}
        lines = ["💰 <b>Последние платежи</b>", DIVIDER, "", "Stars и крипта подтверждаются автоматически — "
                  "кнопки ниже нужны только для зависших ⏳ заявок:", ""]
        for p in payments:
            ts = datetime.fromtimestamp(p["created_at"], tz=timezone.utc).strftime("%d.%m %H:%M")
            mark = status_emoji.get(p["status"], "❓")
            lines.append(f"{mark} #{p['id']} · {ts} · {p['method']} · {p['amount']} · user <code>{p['user_id']}</code>")
            if p["status"] == "pending":
                builder.button(text=f"✅ #{p['id']}", callback_data=f"admin_confirm_pay:{p['id']}")
                builder.button(text=f"❌ #{p['id']}", callback_data=f"admin_reject_pay:{p['id']}")
        text = "\n".join(lines)
        builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())


@dp.callback_query(F.data == "admin_find_user")
async def cb_admin_find_user(callback: CallbackQuery):
    if not is_bot_admin(callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    await callback.answer()
    PENDING_ADMIN_INPUT[callback.from_user.id] = {"stage": "find_user"}
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Отмена", callback_data="admin_panel")
    await callback.message.edit_text(
        "👤 Пришли <b>user_id</b> (числом) или <b>@username</b> пользователя.",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )


@dp.callback_query(F.data == "admin_extend")
async def cb_admin_extend(callback: CallbackQuery):
    if not is_bot_admin(callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    await callback.answer()
    PENDING_ADMIN_INPUT[callback.from_user.id] = {"stage": "extend_user_id"}
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Отмена", callback_data="admin_panel")
    await callback.message.edit_text(
        "➕ Пришли <b>user_id</b> или <b>@username</b> пользователя, которому продлить подписку.",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )


@dp.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(callback: CallbackQuery):
    if not is_bot_admin(callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    await callback.answer()
    PENDING_ADMIN_INPUT[callback.from_user.id] = {"stage": "broadcast_text"}
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Отмена", callback_data="admin_panel")
    await callback.message.edit_text(
        "📢 Пришли текст рассылки — уйдёт всем пользователям бота.",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )


def build_user_summary_text(summary: dict) -> str:
    sub_str = "нет"
    if summary["subscribed_until"]:
        sub_str = datetime.fromtimestamp(summary["subscribed_until"], tz=timezone.utc).strftime("%d.%m.%Y")
    username_line = f"@{html.escape(summary['username'])}" if summary.get("username") else "—"
    return (
        f"👤 <b>Пользователь</b> <code>{summary['user_id']}</code>\n"
        f"{DIVIDER}\n\n"
        f"Имя: {html.escape(summary['first_name'] or '—')}\n"
        f"Username: {username_line}\n"
        f"Забанен: {'Да 🚫' if summary['banned'] else 'Нет'}\n"
        f"Подписка до: <b>{sub_str}</b>\n"
        f"Пробный период: {summary['trial_days_left']} дн. "
        f"(активен: {'да' if summary['trial_active'] else 'нет'})\n"
        f"Приглашено рефералов: {summary['referral_count']}"
    )


def get_user_actions_keyboard(user_id: int, banned: bool):
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Продлить на 30 дн.", callback_data=f"admin_ext30:{user_id}")
    builder.button(
        text="✅ Разбанить" if banned else "🚫 Забанить", callback_data=f"admin_toggleban:{user_id}"
    )
    builder.button(text="🔙 Назад", callback_data="admin_panel")
    builder.adjust(1)
    return builder.as_markup()


@dp.callback_query(F.data.startswith("admin_ext30:"))
async def cb_admin_ext30(callback: CallbackQuery):
    if not is_bot_admin(callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    target_id = int(callback.data.split(":")[1])
    new_until = grant_subscription_days(target_id, 30)
    until_str = datetime.fromtimestamp(new_until, tz=timezone.utc).strftime("%d.%m.%Y")
    await callback.answer(f"✅ Продлено до {until_str}")
    summary = get_user_admin_summary(target_id)
    await callback.message.edit_text(
        build_user_summary_text(summary),
        parse_mode="HTML",
        reply_markup=get_user_actions_keyboard(target_id, summary["banned"]),
    )
    try:
        await bot.send_message(target_id, "🎉 Администратор продлил тебе подписку VICEGRAM на 30 дней!")
    except Exception:
        pass


@dp.callback_query(F.data.startswith("admin_toggleban:"))
async def cb_admin_toggleban(callback: CallbackQuery):
    if not is_bot_admin(callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    target_id = int(callback.data.split(":")[1])
    currently_banned = is_user_banned(target_id)
    set_user_banned(target_id, not currently_banned)
    await callback.answer("✅ Разбанен" if currently_banned else "🚫 Забанен")
    summary = get_user_admin_summary(target_id)
    await callback.message.edit_text(
        build_user_summary_text(summary),
        parse_mode="HTML",
        reply_markup=get_user_actions_keyboard(target_id, summary["banned"]),
    )


async def process_pending_admin_input(message: Message, pending: dict) -> None:
    admin_id = message.from_user.id
    stage = pending["stage"]
    text = (message.text or "").strip()

    if stage == "find_user":
        target_id = resolve_target_user_id(text)
        if target_id is None:
            await message.answer(
                "⚠️ Не нашёл такого пользователя. Пришли user_id (числом) или "
                "@username — но только если он уже писал боту раньше."
            )
            return
        PENDING_ADMIN_INPUT.pop(admin_id, None)
        summary = get_user_admin_summary(target_id)
        if summary is None:
            await message.answer("🤷 Такой пользователь боту ещё не писал.")
            return
        await message.answer(
            build_user_summary_text(summary),
            parse_mode="HTML",
            reply_markup=get_user_actions_keyboard(target_id, summary["banned"]),
        )

    elif stage == "extend_user_id":
        target_id = resolve_target_user_id(text)
        if target_id is None:
            await message.answer(
                "⚠️ Не нашёл такого пользователя. Пришли user_id (числом) или "
                "@username — но только если он уже писал боту раньше."
            )
            return
        PENDING_ADMIN_INPUT[admin_id] = {"stage": "extend_days", "target_id": target_id}
        await message.answer(f"На сколько дней продлить пользователю {target_id}? Пришли число.")

    elif stage == "extend_days":
        try:
            days = int(text)
        except ValueError:
            await message.answer("⚠️ Пришли целое число дней.")
            return
        target_id = pending["target_id"]
        PENDING_ADMIN_INPUT.pop(admin_id, None)
        new_until = grant_subscription_days(target_id, days)
        until_str = datetime.fromtimestamp(new_until, tz=timezone.utc).strftime("%d.%m.%Y")
        await message.answer(f"✅ Подписка пользователя {target_id} продлена на {days} дн. Действует до {until_str}.")
        try:
            await bot.send_message(target_id, f"🎉 Администратор продлил тебе подписку VICEGRAM на {days} дн.!")
        except Exception:
            pass

    elif stage == "broadcast_text":
        PENDING_ADMIN_INPUT.pop(admin_id, None)
        recipients = get_all_user_ids()
        status_msg = await message.answer(f"⏳ Рассылка запущена для {len(recipients)} пользователей...")
        sent, failed = 0, 0
        for uid in recipients:
            try:
                await bot.send_message(uid, message.html_text if message.html_text else text, parse_mode="HTML")
                sent += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.05)
        await status_msg.edit_text(f"✅ Рассылка завершена.\nДоставлено: {sent}\nНе доставлено: {failed}")


def is_user_connected(user_id: int) -> bool:
    conn = db_connect()
    row = conn.execute(
        "SELECT 1 FROM business_connections WHERE owner_id = ? AND is_enabled = 1", (user_id,)
    ).fetchone()
    conn.close()
    return row is not None


@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    if is_user_banned(message.from_user.id):
        await message.answer("🚫 Доступ к боту ограничен администратором.")
        return

    referrer_id = None
    if command.args and command.args.startswith("ref"):
        try:
            referrer_id = int(command.args[3:])
        except ValueError:
            referrer_id = None
    register_user(message.from_user.id, message.from_user.full_name, referrer_id, message.from_user.username)

    if is_user_connected(message.from_user.id):
        await send_dm_screen(
            message,
            build_features_menu_text(message.from_user.id),
            get_features_menu_keyboard(),
        )
        return
    await send_dm_screen(message, build_intro_text(), get_intro_keyboard())


@dp.callback_query(F.data == "dm_home")
async def cb_dm_home(callback: CallbackQuery):
    await callback.answer()
    if is_user_connected(callback.from_user.id):
        await edit_dm_screen(
            callback,
            build_features_menu_text(callback.from_user.id),
            get_features_menu_keyboard(),
        )
    else:
        await edit_dm_screen(callback, build_intro_text(), get_intro_keyboard())


@dp.callback_query(F.data == "dm_setup")
async def cb_dm_setup(callback: CallbackQuery):
    await callback.answer()
    me = await bot.get_me()
    await edit_dm_screen(
        callback,
        build_setup_instructions(me.username),
        get_setup_keyboard(),
        photo_path=SETUP_GUIDE_PATH,
    )


@dp.callback_query(F.data == "dm_group_info")
async def cb_dm_group_info(callback: CallbackQuery):
    await callback.answer()
    await edit_dm_screen(callback, build_group_instructions(), get_group_info_keyboard())


@dp.callback_query(F.data == "dm_features")
async def cb_dm_features(callback: CallbackQuery):
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="🔌 Настроить бота", callback_data="dm_setup")
    builder.button(text="🎁 Пригласить друга (+2 дня)", callback_data="dm_referral")
    builder.button(text="🔙 Назад", callback_data="dm_home")
    builder.adjust(1)
    await edit_dm_screen(callback, build_intro_text(), builder.as_markup())


@dp.callback_query(F.data == "dm_referral")
async def cb_dm_referral(callback: CallbackQuery):
    await callback.answer()
    register_user(callback.from_user.id, callback.from_user.full_name, username=callback.from_user.username)
    me = await bot.get_me()
    await edit_dm_screen(
        callback,
        build_referral_text(me.username, callback.from_user.id),
        get_referral_keyboard(me.username, callback.from_user.id),
    )


@dp.message(Command("settings"), F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def cmd_settings(message: Message):
    if not await is_group_admin(message.chat.id, message.from_user.id):
        await message.answer("⛔ Настройки доступны только администраторам чата.")
        return
    settings = get_settings(message.chat.id)
    lang = settings["lang"]
    claim_note = ""
    if not settings.get("owner_id"):
        set_owner(message.chat.id, message.from_user.id, message.from_user.full_name)
        register_user(message.from_user.id, message.from_user.full_name, username=message.from_user.username)
        claim_note = (
            "\n\n📩 Пойманные удалённые и изменённые сообщения теперь будут "
            "приходить тебе в личные сообщения с ботом (а не в этот чат)."
        )
    await message.answer(
        f"{t(lang, 'settings_title')}\n\n{t(lang, 'settings_body')}{claim_note}",
        parse_mode="HTML",
        reply_markup=get_settings_menu(message.chat.id),
    )


# ==================== ЛИЧНЫЕ ЧАТЫ: TELEGRAM BUSINESS (АВТОМАТИЗАЦИЯ ЧАТОВ) ====================
def get_business_connection(business_connection_id: str):
    conn = db_connect()
    row = conn.execute(
        "SELECT * FROM business_connections WHERE business_connection_id = ?",
        (business_connection_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_business_connection(connection: BusinessConnection) -> None:
    conn = db_connect()
    conn.execute(
        """
        INSERT INTO business_connections
            (business_connection_id, owner_id, owner_chat_id, is_enabled, connected_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(business_connection_id) DO UPDATE SET
            is_enabled = excluded.is_enabled,
            connected_at = excluded.connected_at
        """,
        (
            connection.id,
            connection.user.id,
            connection.user_chat_id,
            int(connection.is_enabled),
            int(time.time()),
        ),
    )
    conn.commit()
    conn.close()


async def notify_unsavable_media(owner_id: int, message: Message, media_type: str) -> None:
    """Медиа пришло, но скачать копию сразу не удалось — почти наверняка это
    фото/видео «на один просмотр»: Telegram не отдаёт боту такие файлы, это
    ограничение платформы, обойти его нечем. Хотя бы сообщаем владельцу,
    что именно пропало, вместо тихого умолчания."""
    if not await gate_by_trial(owner_id):
        return
    author = format_author(
        message.from_user.full_name if message.from_user else None,
        message.from_user.username if message.from_user else None,
    )
    kind = {"photo": "фото", "video": "видео", "video_note": "видеосообщение"}.get(media_type, "медиа")
    try:
        await bot.send_message(
            owner_id,
            f"⏳🔒 <b>Пришло {kind} «на один просмотр»</b>\n{DIVIDER}\n\n"
            f"👤 От: {author}\n\n"
            "Telegram не даёт боту скачать такие файлы — это защита приватности "
            "на уровне платформы, её нельзя обойти в рамках Bot API.",
            parse_mode="HTML",
        )
    except Exception:
        logger.warning("Не удалось уведомить владельца %s о неперехваченном view-once медиа", owner_id)


async def cache_business_message(owner_id: int, message: Message) -> None:
    media_type, file_id = extract_media(message)
    text = message.text or message.caption
    now = int(time.time())

    media_path = None
    if file_id:
        media_path = await download_media_copy(file_id, owner_id, message.chat.id, message.message_id)
        if media_path is None:
            await notify_unsavable_media(owner_id, message, media_type)

    conn = db_connect()
    conn.execute(
        """
        INSERT OR REPLACE INTO messages
            (source, owner_id, chat_id, message_id, user_id, user_name, user_username, text,
             media_type, file_id, media_path, date, deleted, expired, check_count, next_check_at)
        VALUES ('business', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, 0, 0)
        """,
        (
            owner_id,
            message.chat.id,
            message.message_id,
            message.from_user.id if message.from_user else None,
            message.from_user.full_name if message.from_user else None,
            message.from_user.username if message.from_user else None,
            text,
            media_type,
            file_id,
            media_path,
            now,
        ),
    )
    conn.commit()
    conn.close()


def get_cached_business_message(owner_id: int, chat_id: int, message_id: int):
    conn = db_connect()
    row = conn.execute(
        "SELECT * FROM messages WHERE source = 'business' AND owner_id = ? AND chat_id = ? AND message_id = ?",
        (owner_id, chat_id, message_id),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def mark_business_message_deleted(owner_id: int, chat_id: int, message_id: int) -> None:
    conn = db_connect()
    conn.execute(
        "UPDATE messages SET deleted = 1 WHERE source = 'business' AND owner_id = ? AND chat_id = ? AND message_id = ?",
        (owner_id, chat_id, message_id),
    )
    conn.commit()
    conn.close()


async def announce_deleted_business(owner_id: int, row: dict) -> None:
    if not await gate_by_trial(owner_id):
        return
    author = format_author(row["user_name"], row["user_username"])
    header = f"🗑💌 <b>Поймано удалённое личное сообщение!</b>\n{DIVIDER}\n\n👤 От: {author}"
    safe_text = html.escape(row["text"]) if row["text"] else row["text"]
    try:
        media_path = row["media_path"]
        if row["media_type"] and media_path and os.path.exists(media_path):
            caption = header if not safe_text else f"{header}\n\n{safe_text}"
            await repost_media(owner_id, row["media_type"], FSInputFile(media_path), caption)
        elif row["media_type"]:
            # локальной копии нет (например, БД пересоздана) — пробуем через file_id,
            # но для самоуничтожающихся медиа он может быть уже недействителен
            caption = header if not safe_text else f"{header}\n\n{safe_text}"
            try:
                await repost_media(owner_id, row["media_type"], row["file_id"], caption)
            except TelegramBadRequest:
                await bot.send_message(
                    owner_id,
                    f"{header}\n\n⚠️ Медиа было исчезающим и уже недоступно для пересылки.",
                    parse_mode="HTML",
                )
        else:
            body = f"{header}\n\n💬 {safe_text or '(пусто)'}"
            await bot.send_message(owner_id, body, parse_mode="HTML")
    except Exception:
        logger.exception("Не удалось отправить оповещение об удалении личного сообщения")


@dp.message(Command("settings"), F.chat.type == ChatType.PRIVATE)
async def cmd_settings_private(message: Message):
    if is_user_banned(message.from_user.id):
        await message.answer("🚫 Доступ к боту ограничен администратором.")
        return
    register_user(message.from_user.id, message.from_user.full_name, username=message.from_user.username)
    if is_user_connected(message.from_user.id):
        await send_dm_screen(
            message,
            build_features_menu_text(message.from_user.id),
            get_features_menu_keyboard(),
        )
        return
    await send_dm_screen(message, build_intro_text(), get_intro_keyboard())


@dp.business_connection()
async def handle_business_connection(connection: BusinessConnection):
    upsert_business_connection(connection)
    register_user(connection.user.id, connection.user.full_name, username=connection.user.username)
    if not connection.is_enabled:
        logger.info("Бизнес-подключение %s отключено пользователем %s", connection.id, connection.user.id)
        return
    try:
        await bot.send_photo(
            connection.user.id,
            FSInputFile(LOGO_PATH),
            caption=build_features_menu_text(connection.user.id),
            parse_mode="HTML",
            reply_markup=get_features_menu_keyboard(),
        )
    except Exception:
        logger.exception("Не удалось отправить подтверждение подключения личных чатов")


@dp.business_message()
async def handle_business_message(message: Message):
    connection = get_business_connection(message.business_connection_id)
    if not connection or not connection["is_enabled"]:
        return
    await cache_business_message(connection["owner_id"], message)


@dp.edited_business_message()
async def handle_edited_business_message(message: Message):
    connection = get_business_connection(message.business_connection_id)
    if not connection or not connection["is_enabled"]:
        return
    owner_id = connection["owner_id"]
    old = get_cached_business_message(owner_id, message.chat.id, message.message_id)
    new_text = message.text or message.caption or ""
    if old and old["text"] and old["text"] != new_text and await gate_by_trial(owner_id):
        author = user_mention(
            message.from_user.id, message.from_user.full_name, message.from_user.username
        ) if message.from_user else "неизвестный"
        body = (
            "📝✏️ <b>Изменённое личное сообщение:</b>\n\n"
            f"💬 <b>Старый текст:</b>\n« {html.escape(old['text'])} »\n\n"
            f"✨ <b>Новый текст:</b>\n« {html.escape(new_text)} »\n\n"
            f"👤 От: {author}"
        )
        try:
            await bot.send_message(owner_id, body, parse_mode="HTML")
        except Exception:
            logger.exception("Не удалось отправить оповещение об изменении личного сообщения")
    await cache_business_message(owner_id, message)


@dp.deleted_business_messages()
async def handle_deleted_business_messages(deleted: BusinessMessagesDeleted):
    connection = get_business_connection(deleted.business_connection_id)
    if not connection or not connection["is_enabled"]:
        return
    owner_id = connection["owner_id"]
    for message_id in deleted.message_ids:
        row = get_cached_business_message(owner_id, deleted.chat.id, message_id)
        if not row:
            continue
        mark_business_message_deleted(owner_id, deleted.chat.id, message_id)
        await announce_deleted_business(owner_id, row)


@dp.callback_query(F.data == "open:main")
async def cb_open_main(callback: CallbackQuery):
    await callback.answer()
    lang = get_settings(callback.message.chat.id)["lang"]
    await callback.message.edit_text(
        f"{t(lang, 'settings_title')}\n\n{t(lang, 'settings_body')}",
        parse_mode="HTML",
        reply_markup=get_settings_menu(callback.message.chat.id),
    )


@dp.callback_query(F.data == "open:lang")
async def cb_open_lang(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "🌐 <b>Язык / Language</b>\n\nВыбери язык интерфейса:",
        parse_mode="HTML",
        reply_markup=get_lang_menu(),
    )


@dp.callback_query(F.data.startswith("lang:"))
async def cb_set_lang(callback: CallbackQuery):
    if not await is_group_admin(callback.message.chat.id, callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    lang = callback.data.split(":")[1]
    set_setting(callback.message.chat.id, "lang", lang)
    await callback.answer("✅")
    await callback.message.edit_text(
        f"{t(lang, 'settings_title')}\n\n{t(lang, 'settings_body')}",
        parse_mode="HTML",
        reply_markup=get_settings_menu(callback.message.chat.id),
    )


@dp.callback_query(F.data == "claim_owner")
async def cb_claim_owner(callback: CallbackQuery):
    if not await is_group_admin(callback.message.chat.id, callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    set_owner(callback.message.chat.id, callback.from_user.id, callback.from_user.full_name)
    register_user(callback.from_user.id, callback.from_user.full_name, username=callback.from_user.username)
    await callback.answer("✅ Теперь уведомления идут тебе в личку")
    settings = get_settings(callback.message.chat.id)
    lang = settings["lang"]
    await callback.message.edit_text(
        f"{t(lang, 'settings_title')}\n\n{t(lang, 'settings_body')}",
        parse_mode="HTML",
        reply_markup=get_settings_menu(callback.message.chat.id),
    )


@dp.callback_query(F.data.startswith("open:"))
async def cb_open_toggle(callback: CallbackQuery):
    key = callback.data.split(":")[1]
    if key not in TOGGLE_KEYS:
        await callback.answer("Неизвестный раздел настроек", show_alert=True)
        return
    await callback.answer()
    settings = get_settings(callback.message.chat.id)
    lang = settings["lang"]
    state_text = t(lang, "on") if settings[key] else t(lang, "off")
    await callback.message.edit_text(
        f"{t(lang, key)}\n{DIVIDER}\n\nТекущее состояние: <b>{state_text}</b>",
        parse_mode="HTML",
        reply_markup=get_toggle_menu(callback.message.chat.id, key),
    )


@dp.callback_query(F.data.startswith("toggle:"))
async def cb_toggle(callback: CallbackQuery):
    if not await is_group_admin(callback.message.chat.id, callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    _, key, value = callback.data.split(":")
    if key not in TOGGLE_KEYS:
        await callback.answer("Неизвестный раздел настроек", show_alert=True)
        return
    set_setting(callback.message.chat.id, key, int(value))
    await callback.answer("✅ Сохранено")
    settings = get_settings(callback.message.chat.id)
    lang = settings["lang"]
    state_text = t(lang, "on") if settings[key] else t(lang, "off")
    await callback.message.edit_text(
        f"{t(lang, key)}\n{DIVIDER}\n\nТекущее состояние: <b>{state_text}</b>",
        parse_mode="HTML",
        reply_markup=get_toggle_menu(callback.message.chat.id, key),
    )


# ==================== КАСТОМНЫЕ КОМАНДЫ: UI ====================
@dp.callback_query(F.data == "cmd_add")
async def cb_cmd_add(callback: CallbackQuery):
    if not await is_group_admin(callback.message.chat.id, callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    await callback.answer()
    PENDING_COMMAND_INPUT[(callback.message.chat.id, callback.from_user.id)] = {"stage": "trigger"}
    await callback.message.answer(
        "✏️ Напиши слово-триггер новой команды (например: <code>правила</code>).",
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "cmd_list")
async def cb_cmd_list(callback: CallbackQuery):
    await callback.answer()
    commands = list_custom_commands(callback.message.chat.id)
    if not commands:
        text = "🤖 В этом чате пока нет кастомных команд."
    else:
        lines = ["🤖 <b>Команды в чате:</b>", DIVIDER, ""]
        for c in commands:
            lines.append(f"• <code>{html.escape(c['trigger'])}</code>")
        text = "\n".join(lines)
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="open:custom_commands")
    await callback.message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())


# ==================== ФОНОВАЯ ЗАДАЧА: ЛОВЛЯ УДАЛЕНИЙ ====================
async def message_still_exists(chat_id: int, message_id: int) -> bool:
    """Тихая проверка через copy_message в лог-чат с немедленным удалением копии.
    True — сообщение существует, False — было удалено."""
    try:
        copy = await bot.copy_message(LOG_CHAT_ID, chat_id, message_id)
        try:
            await bot.delete_message(LOG_CHAT_ID, copy.message_id)
        except TelegramBadRequest:
            pass
        return True
    except TelegramForbiddenError:
        return True  # не можем проверить (нет доступа к лог-чату) — считаем, что существует
    except TelegramBadRequest as e:
        text = str(e).lower()
        if "not found" in text or "message to copy not found" in text or "message_id_invalid" in text:
            return False
        return True


async def announce_deleted(row: dict) -> None:
    settings = get_settings(row["chat_id"])
    owner_id = settings.get("owner_id")

    if owner_id and not await gate_by_trial(owner_id, require_group_access=True):
        return

    chat_label = ""
    if owner_id:
        try:
            chat = await bot.get_chat(row["chat_id"])
            chat_title = html.escape(chat.title) if chat.title else row["chat_id"]
            chat_label = f"\n💬 Чат: {chat_title}"
        except Exception:
            pass

    author = (
        user_mention(row["user_id"], row["user_name"], row["user_username"])
        if row["user_id"] else "неизвестный"
    )
    header = f"🗑🔍 <b>Поймано удалённое сообщение!</b>\n{DIVIDER}\n\n👤 Автор: {author}{chat_label}"
    safe_text = html.escape(row["text"]) if row["text"] else row["text"]

    async def _send(target: int) -> None:
        if row["media_type"]:
            caption = header if not safe_text else f"{header}\n\n{safe_text}"
            await repost_media(target, row["media_type"], row["file_id"], caption)
        else:
            body = f"{header}\n\n💬 {safe_text or '(пусто)'}"
            await bot.send_message(target, body, parse_mode="HTML")

    target_chat_id = owner_id or row["chat_id"]
    try:
        await _send(target_chat_id)
    except (TelegramForbiddenError, TelegramBadRequest):
        if not owner_id:
            raise
        logger.warning(
            "Не удалось отправить владельцу %s (чат %s) — шлю в группу", owner_id, row["chat_id"]
        )
        await _send(row["chat_id"])


CLEANUP_INTERVAL_SECONDS = 900  # чистка старого кэша — раз в 15 минут, не на каждом тике поллера


async def deleted_message_poller() -> None:
    last_cleanup_at = 0
    while True:
        try:
            now = int(time.time())
            conn = db_connect()
            due = conn.execute(
                """
                SELECT * FROM messages
                WHERE source = 'group_bot' AND deleted = 0 AND expired = 0 AND next_check_at <= ?
                ORDER BY next_check_at ASC LIMIT 15
                """,
                (now,),
            ).fetchall()
            conn.close()

            for row in due:
                row = dict(row)
                settings = get_settings(row["chat_id"])
                age = now - row["date"]

                if not settings["catch_deleted"] or age > MAX_MESSAGE_AGE:
                    conn = db_connect()
                    conn.execute(
                        "UPDATE messages SET expired = 1 WHERE source = 'group_bot' AND chat_id = ? AND message_id = ?",
                        (row["chat_id"], row["message_id"]),
                    )
                    conn.commit()
                    conn.close()
                    continue

                exists = await message_still_exists(row["chat_id"], row["message_id"])
                conn = db_connect()
                if not exists:
                    conn.execute(
                        "UPDATE messages SET deleted = 1 WHERE source = 'group_bot' AND chat_id = ? AND message_id = ?",
                        (row["chat_id"], row["message_id"]),
                    )
                    conn.commit()
                    conn.close()
                    try:
                        await announce_deleted(row)
                    except Exception:
                        logger.exception("Не удалось отправить оповещение об удалении")
                else:
                    check_count = row["check_count"] + 1
                    delay = BACKOFF_SCHEDULE[min(check_count, len(BACKOFF_SCHEDULE) - 1)]
                    conn.execute(
                        "UPDATE messages SET check_count = ?, next_check_at = ? WHERE source = 'group_bot' AND chat_id = ? AND message_id = ?",
                        (check_count, now + delay, row["chat_id"], row["message_id"]),
                    )
                    conn.commit()
                    conn.close()
                await asyncio.sleep(0.1)

            # чистим совсем старые записи кэша (7 дней) — и файлы медиа личных чатов;
            # не на каждом 20-секундном тике, иначе полное сканирование растущей
            # таблицы messages регулярно подвешивает ответ бота на команды
            if now - last_cleanup_at >= CLEANUP_INTERVAL_SECONDS:
                last_cleanup_at = now
                cutoff = now - 7 * 24 * 3600
                conn = db_connect()
                conn.execute("DELETE FROM messages WHERE source = 'group_bot' AND date < ?", (cutoff,))
                old_media = conn.execute(
                    "SELECT media_path FROM messages WHERE source = 'business' AND date < ? AND media_path IS NOT NULL",
                    (cutoff,),
                ).fetchall()
                for old_row in old_media:
                    try:
                        if old_row["media_path"] and os.path.exists(old_row["media_path"]):
                            os.remove(old_row["media_path"])
                    except OSError:
                        pass
                conn.execute("DELETE FROM messages WHERE source = 'business' AND date < ?", (cutoff,))
                conn.commit()
                conn.close()
        except Exception:
            logger.exception("Ошибка в поллере удалённых сообщений")
        await asyncio.sleep(20)


# ==================== ОБРАБОТЧИК: ИЗМЕНЁННЫЕ СООБЩЕНИЯ ====================
@dp.edited_message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def handle_edited_message(message: Message):
    settings = get_settings(message.chat.id)
    if not settings["catch_edited"]:
        cache_message(message)
        return
    old = get_cached_message(message.chat.id, message.message_id)
    new_text = message.text or message.caption or ""
    if old and old["text"] and old["text"] != new_text:
        author = user_mention(
            message.from_user.id, message.from_user.full_name, message.from_user.username
        ) if message.from_user else "неизвестный"
        chat_label = f"\n💬 Чат: {html.escape(message.chat.title)}" if settings.get("owner_id") and message.chat.title else ""
        body = (
            "📝✏️ <b>Изменённое сообщение:</b>\n\n"
            f"💬 <b>Старый текст:</b>\n« {html.escape(old['text'])} »\n\n"
            f"✨ <b>Новый текст:</b>\n« {html.escape(new_text)} »\n\n"
            f"👤 Изменил(а): {author}{chat_label}"
        )
        await notify_chat_owner(message.chat.id, body, parse_mode="HTML")
    update_cached_text(message.chat.id, message.message_id, new_text)


# ==================== ОГОНЬКИ: КОМАНДА ====================
@dp.message(Command("flames"), F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def cmd_flames(message: Message):
    settings = get_settings(message.chat.id)
    if not settings["flames"]:
        await message.answer("⚡ Огоньки выключены в этом чате. Включи их в /settings.")
        return
    leaderboard = get_streak_leaderboard(message.chat.id)
    if not leaderboard:
        await message.answer("⚡ Пока никто не поддерживает огонёк активности.")
        return
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = ["⚡🔥 <b>Огоньки чата — топ активности</b>", DIVIDER, ""]
    for i, entry in enumerate(leaderboard, 1):
        mark = medals.get(i, f"{i}.")
        lines.append(f"{mark} {entry['user_name']} — 🔥 {entry['streak']}")
    await message.answer("\n".join(lines), parse_mode="HTML")


# ==================== ВОССТАНОВЛЕНИЕ ЧАТА ====================
@dp.message(Command("restore"), F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def cmd_restore(message: Message):
    settings = get_settings(message.chat.id)
    if not settings["chat_restore"]:
        await message.answer("📤 Восстановление чатов выключено. Включи его в /settings.")
        return
    if not await is_group_admin(message.chat.id, message.from_user.id):
        await message.answer("⛔ Восстановление доступно только администраторам чата.")
        return

    conn = db_connect()
    rows = conn.execute(
        "SELECT * FROM messages WHERE source = 'group_bot' AND chat_id = ? ORDER BY date DESC LIMIT 200",
        (message.chat.id,),
    ).fetchall()
    conn.close()

    if not rows:
        await message.answer("📤 В кэше пока нет сообщений для восстановления.")
        return

    lines = []
    for row in reversed(rows):
        ts = datetime.fromtimestamp(row["date"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        mark = "[удалено] " if row["deleted"] else ""
        content = row["text"] or (f"[{row['media_type']}]" if row["media_type"] else "")
        lines.append(f"{ts} — {row['user_name']}: {mark}{content}")

    dump = "\n".join(lines).encode("utf-8")
    file = BufferedInputFile(dump, filename=f"chat_{message.chat.id}_restore.txt")
    await message.answer_document(file, caption="📤 Восстановленная история сообщений из кэша VICEGRAM.")


# ==================== ОБРАБОТЧИК: "ПОЙМАЙ ВСЁ" НА ЛИЧКУ ====================
# Регистрируется после всех приватных команд — иначе перехватит /start,
# /settings и /admin ещё до того, как они сработают.
@dp.message(F.chat.type == ChatType.PRIVATE)
async def handle_private_catchall(message: Message):
    admin_pending = PENDING_ADMIN_INPUT.get(message.from_user.id)
    if admin_pending and is_bot_admin(message.from_user.id) and message.text:
        await process_pending_admin_input(message, admin_pending)

    await message.answer(
        "📨 Заявка отправлена администратору. Как только подтвердит — подписка активируется автоматически."
    )


# ==================== ОБРАБОТЧИК: ОБЫЧНЫЕ СООБЩЕНИЯ В ГРУППЕ ====================
# Регистрируется последним: это "поймай всё" на все остальные сообщения группы,
# и он не должен перехватывать /settings, /flames, /restore и другие команды.
@dp.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def handle_group_message(message: Message):
    if message.from_user is None or message.from_user.is_bot:
        return

    pending = PENDING_COMMAND_INPUT.get((message.chat.id, message.from_user.id))
    if pending and message.text:
        await process_pending_command_input(message, pending)
        return

    cache_message(message)

    settings = get_settings(message.chat.id)
    text = message.text or message.caption or ""

    if settings["anti_scam"] and text and looks_like_scam(text):
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        author = user_mention(message.from_user.id, message.from_user.full_name, message.from_user.username)
        await bot.send_message(
            message.chat.id,
            f"✋🚫 <b>Анти-скам сработал!</b>\n{DIVIDER}\n\nСообщение от {author} похоже на мошенничество и было удалено.",
            parse_mode="HTML",
        )
        return

    if settings["custom_commands"] and text:
        response = find_custom_command(message.chat.id, text)
        if response:
            await message.answer(response)

    if settings["flames"]:
        update_streak(message.chat.id, message.from_user.id, message.from_user.full_name)


async def process_pending_command_input(message: Message, pending: dict) -> None:
    key = (message.chat.id, message.from_user.id)
    if pending["stage"] == "trigger":
        trigger = message.text.strip()
        if not trigger or len(trigger) > 64:
            await message.answer("⚠️ Триггер должен быть короче 64 символов. Попробуй ещё раз.")
            return
        PENDING_COMMAND_INPUT[key] = {"stage": "response", "trigger": trigger}
        await message.answer(
            f"✏️ Теперь напиши ответ бота на команду «{trigger}»."
        )
    else:
        trigger = pending["trigger"]
        response = message.text
        add_custom_command(message.chat.id, trigger, response)
        PENDING_COMMAND_INPUT.pop(key, None)
        await message.answer(f"✅ Команда «{trigger}» добавлена.")


async def start_health_server() -> None:
    """Заглушка-HTTP-сервер для платформ вроде Render, которым нужен
    открытый порт с ответом на запрос (health check), иначе они считают
    сервис неживым и убивают его. Самому боту это не нужно — он работает
    через long polling, а не через входящие HTTP-запросы."""
    from aiohttp import web

    async def health(request):
        return web.Response(text="VICEGRAM is running")

    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Health-check HTTP сервер слушает порт %s", port)


# ==================== ЗАПУСК ====================
async def setup_bot_commands() -> None:
    """Настраивает нативное меню команд Telegram (кнопка "☰" рядом с полем
    ввода) — это кнопки самого бота, а не инлайн-кнопки в сообщениях."""
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="🎣 Запустить / открыть меню"),
            BotCommand(command="settings", description="⚙️ Настройки"),
        ],
        scope=BotCommandScopeAllPrivateChats(),
    )
    await bot.set_my_commands(
        [
            BotCommand(command="settings", description="⚙️ Настроить бота в этой группе"),
            BotCommand(command="flames", description="⚡ Топ активности чата"),
            BotCommand(command="restore", description="📤 Восстановить историю чата"),
        ],
        scope=BotCommandScopeAllGroupChats(),
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.set_my_commands(
                [
                    BotCommand(command="start", description="🎣 Запустить / открыть меню"),
                    BotCommand(command="settings", description="⚙️ Настройки"),
                    BotCommand(command="admin", description="🛠 Панель администратора"),
                    BotCommand(command="stats", description="📊 Статистика бота"),
                ],
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception:
            logger.warning("Не удалось установить меню команд для админа %s (ещё не писал боту?)", admin_id)


PUBLIC_STATS_UPDATE_INTERVAL_SECONDS = 1800  # раз в 30 минут — счётчик не обязан быть секундным


async def update_public_user_count() -> None:
    """Публикует число пользователей в короткое описание бота — оно видно
    в профиле бота в Telegram прямо под именем и подписью "бот" (тот же
    экран, где юзернейм и кнопка "Добавить в группу")."""
    count = get_total_user_count()
    try:
        await bot.set_my_short_description(
            short_description=f"🎣 С ботом уже {count} пользователей"
        )
    except Exception:
        logger.warning("Не удалось обновить короткое описание бота (счётчик пользователей)")


async def public_user_count_updater() -> None:
    while True:
        try:
            await update_public_user_count()
        except Exception:
            logger.exception("Ошибка в обновлении публичного счётчика пользователей")
        await asyncio.sleep(PUBLIC_STATS_UPDATE_INTERVAL_SECONDS)


async def main() -> None:
    init_db()
    logger.info("VICEGRAM запускается...")
    await setup_bot_commands()
    asyncio.create_task(start_health_server())
    asyncio.create_task(deleted_message_poller())
    asyncio.create_task(public_user_count_updater())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
