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
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    BusinessConnection,
    BusinessMessagesDeleted,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
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
_log_chat_env = os.getenv("VICEGRAM_LOG_CHAT_ID")
LOG_CHAT_ID = int(_log_chat_env) if _log_chat_env else ADMIN_ID

DB_PATH = os.getenv("VICEGRAM_DB_PATH", "vicegram.db")
MEDIA_CACHE_DIR = os.getenv("VICEGRAM_MEDIA_CACHE_DIR", "vicegram_media_cache")
os.makedirs(MEDIA_CACHE_DIR, exist_ok=True)
DIVIDER = "━━━━━━━━━━━━━━"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ==================== БАЗА ДАННЫХ ====================
def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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
        try:
            await bot.send_message(owner_id, body, **kwargs)
            return
        except (TelegramForbiddenError, TelegramBadRequest):
            logger.warning(
                "Не удалось отправить уведомление владельцу %s (чат %s) — шлю в группу",
                owner_id, chat_id,
            )
    await bot.send_message(chat_id, body, **kwargs)


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
    safe_name = (name or "пользователь").replace("<", "").replace(">", "")
    label = f'<a href="tg://user?id={user_id}">{safe_name}</a>'
    if username:
        label += f" (@{username})"
    return label


def format_author(name: str, username: str = None) -> str:
    """Как user_mention, но без кликабельной ссылки — для случаев без user_id."""
    safe_name = (name or "неизвестный").replace("<", "").replace(">", "")
    return f"{safe_name} (@{username})" if username else safe_name


async def is_group_admin(chat_id: int, user_id: int) -> bool:
    if user_id == ADMIN_ID:
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
@dp.message(CommandStart())
async def cmd_start(message: Message):
    me = await bot.get_me()
    await message.answer(
        "🎣 <b>VICEGRAM</b>\n\n"
        "Профессионально ловлю удалённые и изменённые сообщения, "
        "стикеры, файлы и гифки — в группах и в личных чатах.\n\n"
        f"{DIVIDER}\n"
        "📢 <b>В группе:</b> добавь меня и выдай права администратора "
        "(минимум — удаление сообщений и чтение истории), затем "
        "напиши в группе /settings.\n\n"
        "💬 <b>В личных чатах:</b> подключи меня через встроенную "
        "функцию Telegram «Автоматизация чатов» — это делается в твоих "
        "настройках, без пароля и кода:\n"
        "1. Настройки → «Изменить»\n"
        "2. «Автоматизация чатов»\n"
        f"3. Впиши <b>@{me.username}</b> и нажми «Добавить»\n"
        "4. Выбери, какие чаты мне доверить (все личные, кроме выбранных — "
        "или только выбранные)\n\n"
        "После подключения я сам пришлю подтверждение сюда, в этот диалог — "
        "и с этого момента буду ловить в твоих личных чатах удалённые и "
        "изменённые сообщения.",
        parse_mode="HTML",
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


async def cache_business_message(owner_id: int, message: Message) -> None:
    media_type, file_id = extract_media(message)
    text = message.text or message.caption
    now = int(time.time())

    media_path = None
    if file_id:
        media_path = await download_media_copy(file_id, owner_id, message.chat.id, message.message_id)

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
    author = format_author(row["user_name"], row["user_username"])
    header = f"🗑💌 <b>Поймано удалённое личное сообщение!</b>\n{DIVIDER}\n\n👤 От: {author}"
    try:
        media_path = row["media_path"]
        if row["media_type"] and media_path and os.path.exists(media_path):
            caption = header if not row["text"] else f"{header}\n\n{row['text']}"
            await repost_media(owner_id, row["media_type"], FSInputFile(media_path), caption)
        elif row["media_type"]:
            # локальной копии нет (например, БД пересоздана) — пробуем через file_id,
            # но для самоуничтожающихся медиа он может быть уже недействителен
            caption = header if not row["text"] else f"{header}\n\n{row['text']}"
            try:
                await repost_media(owner_id, row["media_type"], row["file_id"], caption)
            except TelegramBadRequest:
                await bot.send_message(
                    owner_id,
                    f"{header}\n\n⚠️ Медиа было исчезающим и уже недоступно для пересылки.",
                    parse_mode="HTML",
                )
        else:
            body = f"{header}\n\n💬 {row['text'] or '(пусто)'}"
            await bot.send_message(owner_id, body, parse_mode="HTML")
    except Exception:
        logger.exception("Не удалось отправить оповещение об удалении личного сообщения")


@dp.message(Command("settings"), F.chat.type == ChatType.PRIVATE)
async def cmd_settings_private(message: Message):
    me = await bot.get_me()
    await message.answer(
        f"⚙️ <b>Настройки</b>\n{DIVIDER}\n\n"
        "Настройки конкретной группы (удалённые/изменённые сообщения, "
        "анти-скам, огоньки, команды) задаются командой /settings прямо "
        "в этой группе.\n\n"
        "Ловля личных сообщений подключается не здесь, а в самом Telegram:\n"
        "Настройки → «Изменить» → «Автоматизация чатов» → впиши "
        f"<b>@{me.username}</b> → «Добавить».",
        parse_mode="HTML",
    )


@dp.business_connection()
async def handle_business_connection(connection: BusinessConnection):
    upsert_business_connection(connection)
    if not connection.is_enabled:
        logger.info("Бизнес-подключение %s отключено пользователем %s", connection.id, connection.user.id)
        return
    try:
        await bot.send_message(
            connection.user.id,
            "✅ <b>Личные чаты подключены!</b>\n\n"
            "Буду ловить в них удалённые и изменённые сообщения — "
            "уведомления будут приходить сюда, в этот диалог.",
            parse_mode="HTML",
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
    if old and old["text"] and old["text"] != new_text:
        author = user_mention(
            message.from_user.id, message.from_user.full_name, message.from_user.username
        ) if message.from_user else "неизвестный"
        body = (
            "📝✏️ <b>Изменённое личное сообщение:</b>\n\n"
            f"💬 <b>Старый текст:</b>\n« {old['text']} »\n\n"
            f"✨ <b>Новый текст:</b>\n« {new_text} »\n\n"
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
            lines.append(f"• <code>{c['trigger']}</code>")
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

    chat_label = ""
    if owner_id:
        try:
            chat = await bot.get_chat(row["chat_id"])
            chat_label = f"\n💬 Чат: {chat.title or row['chat_id']}"
        except Exception:
            pass

    author = (
        user_mention(row["user_id"], row["user_name"], row["user_username"])
        if row["user_id"] else "неизвестный"
    )
    header = f"🗑🔍 <b>Поймано удалённое сообщение!</b>\n{DIVIDER}\n\n👤 Автор: {author}{chat_label}"

    async def _send(target: int) -> None:
        if row["media_type"]:
            caption = header if not row["text"] else f"{header}\n\n{row['text']}"
            await repost_media(target, row["media_type"], row["file_id"], caption)
        else:
            body = f"{header}\n\n💬 {row['text'] or '(пусто)'}"
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


async def deleted_message_poller() -> None:
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

            # чистим совсем старые записи кэша (7 дней) — и файлы медиа личных чатов
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
        chat_label = f"\n💬 Чат: {message.chat.title}" if settings.get("owner_id") else ""
        body = (
            "📝✏️ <b>Изменённое сообщение:</b>\n\n"
            f"💬 <b>Старый текст:</b>\n« {old['text']} »\n\n"
            f"✨ <b>Новый текст:</b>\n« {new_text} »\n\n"
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
async def main() -> None:
    init_db()
    logger.info("VICEGRAM запускается...")
    asyncio.create_task(start_health_server())
    asyncio.create_task(deleted_message_poller())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
