"""VICEGRAM — бот-ловец для групповых и личных чатов Telegram.

Ловит удалённые и изменённые сообщения, стикеры, файлы и гифки,
следит за исчезающими медиа, умеет восстанавливать историю чата,
считает "огоньки" активности, банит скам-сообщения и поддерживает
кастомные команды в чатах.

Важное техническое ограничение Bot API: Telegram не присылает боту
событие "сообщение удалено" никогда, ни при каких правах, и вообще
не даёт боту доступа к личным перепискам между двумя другими людьми.
Поэтому реализованы два независимых механизма ловли:

- В группах (где бот состоит участником) — периодическая тихая проверка
  существования сообщения (copy_message в лог-чат с мгновенным удалением
  копии), задержка до ~30 секунд.
- В личных чатах — через MTProto-юзербот (Telethon), подключаемый самим
  пользователем командой /connect: он вводит номер телефона и код прямо
  в диалоге с ботом, после чего Telethon-сессия видит его личные диалоги
  как реальный участник и ловит удаления/правки в реальном времени.
  См. vicegram_userbot.py.
"""

import asyncio
import base64
import hashlib
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
    CallbackQuery,
    InlineKeyboardButton,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from cryptography.fernet import Fernet

from vicegram_userbot import UserbotManager

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
DIVIDER = "━━━━━━━━━━━━━━"

# Личные чаты (MTProto): нужны api_id/api_hash одного приложения на
# my.telegram.org, зарегистрированного оператором бота. Каждый пользователь
# логинится под своим номером — api_id/api_hash при этом общие для всех.
USERBOT_API_ID = os.getenv("VICEGRAM_API_ID")
USERBOT_API_HASH = os.getenv("VICEGRAM_API_HASH")
USERBOT_FEATURE_ENABLED = bool(USERBOT_API_ID and USERBOT_API_HASH)


def _derive_fernet_key() -> bytes:
    """Ключ шифрования session-строк. Можно задать явно через
    VICEGRAM_ENCRYPTION_KEY (сгенерировать: Fernet.generate_key()),
    иначе выводится из BOT_TOKEN — отдельный секрет не обязателен."""
    env_key = os.getenv("VICEGRAM_ENCRYPTION_KEY")
    if env_key:
        return env_key.encode()
    digest = hashlib.sha256(BOT_TOKEN.encode()).digest()
    return base64.urlsafe_b64encode(digest)


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

userbot_manager: UserbotManager | None = None
if USERBOT_FEATURE_ENABLED:
    userbot_manager = UserbotManager(
        bot=bot,
        db_path=DB_PATH,
        api_id=int(USERBOT_API_ID),
        api_hash=USERBOT_API_HASH,
        fernet=Fernet(_derive_fernet_key()),
        media_dir=MEDIA_CACHE_DIR,
    )

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
            lang TEXT NOT NULL DEFAULT 'ru'
        );

        CREATE TABLE IF NOT EXISTS messages (
            source TEXT NOT NULL DEFAULT 'group_bot',
            owner_id INTEGER NOT NULL DEFAULT 0,
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            user_id INTEGER,
            user_name TEXT,
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

        CREATE TABLE IF NOT EXISTS user_sessions (
            user_id INTEGER PRIMARY KEY,
            phone TEXT,
            session_enc BLOB NOT NULL,
            status TEXT NOT NULL DEFAULT 'connected',
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
def user_mention(user_id: int, name: str) -> str:
    safe_name = (name or "пользователь").replace("<", "").replace(">", "")
    return f'<a href="tg://user?id={user_id}">{safe_name}</a>'


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
            (source, owner_id, chat_id, message_id, user_id, user_name, text, media_type, file_id,
             date, deleted, expired, check_count, next_check_at)
        VALUES ('group_bot', 0, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, ?)
        """,
        (
            message.chat.id,
            message.message_id,
            message.from_user.id if message.from_user else None,
            message.from_user.full_name if message.from_user else None,
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
    await message.answer(
        "🎣 <b>VICEGRAM</b>\n\n"
        "Профессионально ловлю удалённые и изменённые сообщения, "
        "стикеры, файлы и гифки — в группах и в личных чатах.\n\n"
        f"{DIVIDER}\n"
        "📢 <b>В группе:</b> добавь меня и выдай права администратора "
        "(минимум — удаление сообщений и чтение истории), затем "
        "напиши в группе /settings.\n\n"
        "💬 <b>В личных чатах:</b> напиши мне сюда /connect, чтобы "
        "подключить ловлю удалений в твоих личных перепиcках.",
        parse_mode="HTML",
    )


@dp.message(Command("settings"), F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def cmd_settings(message: Message):
    if not await is_group_admin(message.chat.id, message.from_user.id):
        await message.answer("⛔ Настройки доступны только администраторам чата.")
        return
    lang = get_settings(message.chat.id)["lang"]
    await message.answer(
        f"{t(lang, 'settings_title')}\n\n{t(lang, 'settings_body')}",
        parse_mode="HTML",
        reply_markup=get_settings_menu(message.chat.id),
    )


# ==================== ЛИЧНЫЕ ЧАТЫ: ПОДКЛЮЧЕНИЕ MTPROTO ====================
def get_dm_menu(user_id: int):
    builder = InlineKeyboardBuilder()
    if not USERBOT_FEATURE_ENABLED:
        builder.button(text="🔐 Личные чаты (не настроено на сервере)", callback_data="dm_noop")
    elif userbot_manager.is_connected(user_id):
        builder.button(text="🔌 Отключить личные чаты", callback_data="dm_disconnect")
    else:
        builder.button(text="🔐 Подключить личные чаты", callback_data="dm_connect")
    builder.adjust(1)
    return builder.as_markup()


@dp.message(Command("settings"), F.chat.type == ChatType.PRIVATE)
async def cmd_settings_private(message: Message):
    await message.answer(
        f"⚙️ <b>Настройки</b>\n{DIVIDER}\n\n"
        "Настройки конкретной группы (удалённые/изменённые сообщения, "
        "анти-скам, огоньки, команды) задаются командой /settings прямо "
        "в этой группе.\n\n"
        "Здесь можно подключить ловлю удалённых и изменённых сообщений "
        "в твоих личных перепиcках с другими людьми.",
        parse_mode="HTML",
        reply_markup=get_dm_menu(message.from_user.id),
    )


async def start_connect_flow(target: Message, user_id: int) -> None:
    if not USERBOT_FEATURE_ENABLED or userbot_manager is None:
        await target.answer(
            "⚠️ Ловля личных чатов не настроена на этом сервере — "
            "оператору бота нужно задать переменные окружения VICEGRAM_API_ID "
            "и VICEGRAM_API_HASH (получить на my.telegram.org)."
        )
        return
    if userbot_manager.is_connected(user_id):
        await target.answer("✅ Личные чаты уже подключены. Чтобы переподключить — сначала /disconnect.")
        return
    await userbot_manager.begin_login(user_id)
    await target.answer(
        "🔐 <b>Подключение личных чатов</b>\n"
        f"{DIVIDER}\n\n"
        "⚠️ Дальше я попрошу код подтверждения из Telegram — это стандартный "
        "код входа в твой аккаунт. <b>Никогда никому его не пересылай</b>, "
        "кроме как сюда, в этот диалог, и только для собственного аккаунта.\n\n"
        "Напиши номер телефона в международном формате, например "
        "<code>+79991234567</code>.",
        parse_mode="HTML",
    )


async def do_disconnect(target: Message, user_id: int) -> None:
    if not userbot_manager:
        await target.answer("Личные чаты и так не подключены.")
        return
    changed = await userbot_manager.disconnect_user(user_id)
    await target.answer("🔌 Личные чаты отключены." if changed else "Личные чаты и так не были подключены.")


@dp.message(Command("connect"), F.chat.type == ChatType.PRIVATE)
async def cmd_connect(message: Message):
    await start_connect_flow(message, message.from_user.id)


@dp.message(Command("disconnect"), F.chat.type == ChatType.PRIVATE)
async def cmd_disconnect(message: Message):
    await do_disconnect(message, message.from_user.id)


@dp.callback_query(F.data == "dm_connect")
async def cb_dm_connect(callback: CallbackQuery):
    await callback.answer()
    await start_connect_flow(callback.message, callback.from_user.id)


@dp.callback_query(F.data == "dm_disconnect")
async def cb_dm_disconnect(callback: CallbackQuery):
    await callback.answer()
    await do_disconnect(callback.message, callback.from_user.id)


@dp.callback_query(F.data == "dm_noop")
async def cb_dm_noop(callback: CallbackQuery):
    await callback.answer("Функция не настроена на этом сервере", show_alert=True)


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
    lang = get_settings(row["chat_id"])["lang"]
    author = user_mention(row["user_id"], row["user_name"]) if row["user_id"] else "неизвестный"
    header = f"🗑 <b>Поймано удалённое сообщение!</b>\n{DIVIDER}\n\n👤 Автор: {author}"
    if row["media_type"]:
        caption = header if not row["text"] else f"{header}\n\n{row['text']}"
        try:
            await repost_media(row["chat_id"], row["media_type"], row["file_id"], caption)
        except Exception:
            logger.exception("Не удалось переслать удалённое медиа")
    else:
        body = f"{header}\n\n💬 {row['text'] or '(пусто)'}"
        await bot.send_message(row["chat_id"], body, parse_mode="HTML")


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

            # чистим совсем старые записи группового кэша (личный кэш чистит UserbotManager)
            conn = db_connect()
            conn.execute(
                "DELETE FROM messages WHERE source = 'group_bot' AND date < ?",
                (now - 7 * 24 * 3600,),
            )
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
            message.from_user.id, message.from_user.full_name
        ) if message.from_user else "неизвестный"
        body = (
            "📝 <b>Изменённое сообщение:</b>\n\n"
            f"💬 <b>Старый текст:</b>\n« {old['text']} »\n\n"
            f"📝 <b>Новый текст:</b>\n« {new_text} »\n\n"
            f"Изменил(а): {author}"
        )
        await bot.send_message(message.chat.id, body, parse_mode="HTML")
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
    lines = ["⚡ <b>Огоньки чата — топ активности</b>", DIVIDER, ""]
    for i, entry in enumerate(leaderboard, 1):
        lines.append(f"{i}. {entry['user_name']} — 🔥 {entry['streak']}")
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
        author = user_mention(message.from_user.id, message.from_user.full_name)
        await bot.send_message(
            message.chat.id,
            f"✋ <b>Анти-скам:</b> сообщение от {author} похоже на мошенничество и было удалено.",
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


# ==================== ЛИЧНЫЕ ЧАТЫ: ШАГИ ВХОДА (ТЕЛЕФОН/КОД/ПАРОЛЬ) ====================
# Регистрируется последним среди приватных обработчиков: реагирует только
# если у пользователя есть незавершённый вход, иначе не мешает командам.
PHONE_RE = re.compile(r"^\+?\d{7,15}$")


@dp.message(F.chat.type == ChatType.PRIVATE, F.text)
async def handle_private_login_step(message: Message):
    if message.text.startswith("/"):
        return
    if not userbot_manager or not userbot_manager.has_pending_login(message.from_user.id):
        return

    user_id = message.from_user.id
    stage = userbot_manager.get_pending_stage(user_id)
    text = message.text.strip()

    if stage == "phone":
        if not PHONE_RE.match(text):
            await message.answer("⚠️ Это не похоже на номер телефона. Пример: +79991234567")
            return
        result = await userbot_manager.submit_phone(user_id, text)
        if result == "code_sent":
            await message.answer("📩 Код отправлен в Telegram на этот номер. Введи его сюда.")
        elif result == "invalid_phone":
            await message.answer("⚠️ Неверный номер телефона. Попробуй ещё раз.")
        elif result.startswith("flood_wait"):
            await message.answer(f"⏳ Telegram просит подождать {result.split(':')[1]} сек. Попробуй позже: /connect")
            await userbot_manager.cancel_login(user_id)
        else:
            await message.answer("⚠️ Не получилось отправить код. Попробуй /connect ещё раз позже.")
            await userbot_manager.cancel_login(user_id)
        return

    if stage == "code":
        result = await userbot_manager.submit_code(user_id, text.replace(" ", ""))
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        if result == "success":
            await message.answer("✅ Личные чаты подключены! Буду ловить в них удалённые и изменённые сообщения.")
        elif result == "need_password":
            await message.answer("🔒 На аккаунте включена двухфакторная аутентификация. Введи пароль.")
        elif result == "invalid_code":
            await message.answer("⚠️ Неверный код. Попробуй ещё раз.")
        elif result.startswith("flood_wait"):
            await message.answer(f"⏳ Telegram просит подождать {result.split(':')[1]} сек. Попробуй позже: /connect")
            await userbot_manager.cancel_login(user_id)
        else:
            await message.answer("⚠️ Ошибка входа. Попробуй /connect ещё раз позже.")
            await userbot_manager.cancel_login(user_id)
        return

    if stage == "password":
        result = await userbot_manager.submit_password(user_id, text)
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        if result == "success":
            await message.answer("✅ Личные чаты подключены! Буду ловить в них удалённые и изменённые сообщения.")
        elif result.startswith("flood_wait"):
            await message.answer(f"⏳ Telegram просит подождать {result.split(':')[1]} сек. Попробуй позже: /connect")
            await userbot_manager.cancel_login(user_id)
        else:
            await message.answer("⚠️ Неверный пароль. Попробуй ещё раз, либо начни заново: /connect")
        return


async def userbot_cleanup_loop() -> None:
    while True:
        await asyncio.sleep(3600)
        try:
            await userbot_manager.cleanup_old_media()
        except Exception:
            logger.exception("Ошибка очистки кэша личных чатов")


# ==================== ЗАПУСК ====================
async def main() -> None:
    init_db()
    logger.info("VICEGRAM запускается...")
    asyncio.create_task(deleted_message_poller())
    if userbot_manager:
        await userbot_manager.start_existing_sessions()
        asyncio.create_task(userbot_cleanup_loop())
        logger.info("Ловля личных чатов включена (VICEGRAM_API_ID/HASH заданы)")
    else:
        logger.info(
            "Ловля личных чатов выключена — задай VICEGRAM_API_ID и VICEGRAM_API_HASH, "
            "чтобы включить /connect"
        )
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
