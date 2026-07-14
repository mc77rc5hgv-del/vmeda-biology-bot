"""VICEGRAM userbot-менеджер — ловля удалённых/изменённых сообщений
в личных чатах пользователей.

Обычный бот (Bot API) физически не видит переписки между двумя другими
людьми — Telegram не даёт боту туда доступа. Чтобы ловить удаления/правки
в ЛИЧНЫХ чатах, нужен MTProto-клиент, залогиненный под самим аккаунтом
пользователя (как в Telethon) — тогда он видит свои диалоги как реальный
участник, в реальном времени.

Пользователь подключает свой аккаунт прямо в диалоге с ботом (/connect):
вводит номер телефона, потом код из Telegram, при необходимости — пароль
двухфакторной аутентификации. Полученная session-строка — это полный
доступ к аккаунту, поэтому она хранится в БД в зашифрованном виде
(Fernet). Никогда не пересылайте код из Telegram кому-либо, кроме как
самому себе в этот диалог — это стандартная защита Telegram от угона
аккаунта, и бот тут её не отменяет: код вводится только вами и только
для собственного аккаунта.

Важный протокольный нюанс: событие удаления сообщения в личных чатах
(в отличие от каналов/супергрупп) не содержит id чата — только id
сообщения. Поэтому чат для удалённого сообщения определяется эвристикой
по кэшу (последнее недавнее сообщение с таким id) — это работает на
практике, но не даёt стопроцентной гарантии в редких случаях совпадения id.
"""

import logging
import os
import sqlite3
import time
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.types import FSInputFile
from cryptography.fernet import Fernet
from telethon import TelegramClient, events
from telethon.errors import (
    FloodWaitError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

logger = logging.getLogger(__name__)

DIVIDER = "━━━━━━━━━━━━━━"
MAX_PRIVATE_MESSAGE_AGE = 7 * 24 * 3600  # храним кэш личных сообщений неделю


def classify_telethon_media(msg):
    if msg.sticker:
        return "sticker"
    if msg.gif:
        return "animation"
    if msg.video_note:
        return "video_note"
    if msg.voice:
        return "voice"
    if msg.video:
        return "video"
    if msg.audio:
        return "audio"
    if msg.photo:
        return "photo"
    if msg.document:
        return "document"
    return None


async def send_local_media(bot: Bot, chat_id: int, media_type: str, path: str, caption: str = None):
    file = FSInputFile(path)
    kwargs = {"caption": caption, "parse_mode": "HTML"} if caption else {}
    if media_type == "sticker":
        await bot.send_sticker(chat_id, file)
        if caption:
            await bot.send_message(chat_id, caption, parse_mode="HTML")
    elif media_type == "animation":
        await bot.send_animation(chat_id, file, **kwargs)
    elif media_type == "document":
        await bot.send_document(chat_id, file, **kwargs)
    elif media_type == "photo":
        await bot.send_photo(chat_id, file, **kwargs)
    elif media_type == "video":
        await bot.send_video(chat_id, file, **kwargs)
    elif media_type == "video_note":
        await bot.send_video_note(chat_id, file)
        if caption:
            await bot.send_message(chat_id, caption, parse_mode="HTML")
    elif media_type == "voice":
        await bot.send_voice(chat_id, file, **kwargs)
    elif media_type == "audio":
        await bot.send_audio(chat_id, file, **kwargs)


class UserbotManager:
    def __init__(self, bot: Bot, db_path: str, api_id: int, api_hash: str, fernet: Fernet, media_dir: str):
        self.bot = bot
        self.db_path = db_path
        self.api_id = api_id
        self.api_hash = api_hash
        self.fernet = fernet
        self.media_dir = media_dir
        os.makedirs(self.media_dir, exist_ok=True)
        self.clients: dict[int, TelegramClient] = {}
        self.pending_logins: dict[int, dict] = {}

    # ---------- БД ----------
    def _db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def is_connected(self, user_id: int) -> bool:
        return user_id in self.clients

    def has_pending_login(self, user_id: int) -> bool:
        return user_id in self.pending_logins

    def get_pending_stage(self, user_id: int) -> str | None:
        entry = self.pending_logins.get(user_id)
        return entry["stage"] if entry else None

    # ---------- Жизненный цикл подключения ----------
    async def start_existing_sessions(self) -> None:
        conn = self._db()
        rows = conn.execute(
            "SELECT user_id, session_enc FROM user_sessions WHERE status = 'connected'"
        ).fetchall()
        conn.close()
        for row in rows:
            try:
                session_str = self.fernet.decrypt(row["session_enc"]).decode()
                client = TelegramClient(StringSession(session_str), self.api_id, self.api_hash)
                await client.connect()
                if not await client.is_user_authorized():
                    logger.warning("Сессия пользователя %s больше не авторизована", row["user_id"])
                    continue
                self._register_handlers(client, row["user_id"])
                self.clients[row["user_id"]] = client
                logger.info("Восстановлено подключение личных чатов для %s", row["user_id"])
            except Exception:
                logger.exception("Не удалось восстановить сессию для %s", row["user_id"])

    async def begin_login(self, user_id: int) -> None:
        await self.cancel_login(user_id)
        client = TelegramClient(StringSession(), self.api_id, self.api_hash)
        await client.connect()
        self.pending_logins[user_id] = {"client": client, "stage": "phone"}

    async def cancel_login(self, user_id: int) -> None:
        entry = self.pending_logins.pop(user_id, None)
        if entry:
            try:
                await entry["client"].disconnect()
            except Exception:
                pass

    async def submit_phone(self, user_id: int, phone: str) -> str:
        entry = self.pending_logins.get(user_id)
        if not entry:
            return "no_session"
        try:
            sent = await entry["client"].send_code_request(phone)
            entry["phone"] = phone
            entry["phone_code_hash"] = sent.phone_code_hash
            entry["stage"] = "code"
            return "code_sent"
        except PhoneNumberInvalidError:
            return "invalid_phone"
        except FloodWaitError as e:
            return f"flood_wait:{e.seconds}"
        except Exception:
            logger.exception("Ошибка при запросе кода для %s", user_id)
            return "error"

    async def submit_code(self, user_id: int, code: str) -> str:
        entry = self.pending_logins.get(user_id)
        if not entry:
            return "no_session"
        try:
            await entry["client"].sign_in(
                phone=entry["phone"], code=code, phone_code_hash=entry.get("phone_code_hash")
            )
            await self._finalize_login(user_id, entry)
            return "success"
        except SessionPasswordNeededError:
            entry["stage"] = "password"
            return "need_password"
        except PhoneCodeInvalidError:
            return "invalid_code"
        except FloodWaitError as e:
            return f"flood_wait:{e.seconds}"
        except Exception:
            logger.exception("Ошибка при вводе кода для %s", user_id)
            return "error"

    async def submit_password(self, user_id: int, password: str) -> str:
        entry = self.pending_logins.get(user_id)
        if not entry:
            return "no_session"
        try:
            await entry["client"].sign_in(password=password)
            await self._finalize_login(user_id, entry)
            return "success"
        except FloodWaitError as e:
            return f"flood_wait:{e.seconds}"
        except Exception:
            return "invalid_password"

    async def _finalize_login(self, user_id: int, entry: dict) -> None:
        client = entry["client"]
        session_str = client.session.save()
        encrypted = self.fernet.encrypt(session_str.encode())
        conn = self._db()
        conn.execute(
            """
            INSERT INTO user_sessions (user_id, phone, session_enc, status, connected_at)
            VALUES (?, ?, ?, 'connected', ?)
            ON CONFLICT(user_id) DO UPDATE SET
                phone = excluded.phone,
                session_enc = excluded.session_enc,
                status = 'connected',
                connected_at = excluded.connected_at
            """,
            (user_id, entry.get("phone", ""), encrypted, int(time.time())),
        )
        conn.commit()
        conn.close()
        self._register_handlers(client, user_id)
        self.clients[user_id] = client
        self.pending_logins.pop(user_id, None)

    async def disconnect_user(self, user_id: int) -> bool:
        await self.cancel_login(user_id)
        client = self.clients.pop(user_id, None)
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass
        conn = self._db()
        cur = conn.execute(
            "UPDATE user_sessions SET status = 'disconnected' WHERE user_id = ?", (user_id,)
        )
        conn.commit()
        changed = cur.rowcount > 0
        conn.close()
        return changed or client is not None

    # ---------- Обработка событий личных чатов ----------
    def _register_handlers(self, client: TelegramClient, owner_id: int) -> None:
        @client.on(events.NewMessage(incoming=True, outgoing=True))
        async def _on_new(event):
            if not event.is_private:
                return
            try:
                await self._cache_private_message(owner_id, event)
            except Exception:
                logger.exception("Ошибка кэширования личного сообщения для %s", owner_id)

        @client.on(events.MessageEdited)
        async def _on_edit(event):
            if not event.is_private:
                return
            try:
                await self._handle_private_edit(owner_id, event)
            except Exception:
                logger.exception("Ошибка обработки правки личного сообщения для %s", owner_id)

        @client.on(events.MessageDeleted)
        async def _on_delete(event):
            try:
                await self._handle_private_delete(owner_id, event)
            except Exception:
                logger.exception("Ошибка обработки удаления личного сообщения для %s", owner_id)

    async def _cache_private_message(self, owner_id: int, event) -> None:
        msg = event.message
        sender = await event.get_sender()
        sender_name = getattr(sender, "first_name", None) or "Пользователь"
        if getattr(sender, "last_name", None):
            sender_name += f" {sender.last_name}"
        text = msg.raw_text or ""
        media_type = classify_telethon_media(msg)
        media_path = None
        if media_type:
            try:
                fname = f"{owner_id}_{event.chat_id}_{msg.id}"
                media_path = await msg.download_media(file=os.path.join(self.media_dir, fname))
            except Exception:
                logger.exception("Не удалось скачать медиа личного сообщения")

        conn = self._db()
        conn.execute(
            """
            INSERT OR REPLACE INTO messages
                (source, owner_id, chat_id, message_id, user_id, user_name, text,
                 media_type, file_id, media_path, date, deleted, expired, check_count, next_check_at)
            VALUES ('private_userbot', ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, 0, 1, 0, 0)
            """,
            (
                owner_id,
                event.chat_id,
                msg.id,
                getattr(sender, "id", None),
                sender_name,
                text,
                media_type,
                media_path,
                int(time.time()),
            ),
        )
        conn.commit()
        conn.close()

    def _get_cached(self, owner_id: int, chat_id: int, message_id: int):
        conn = self._db()
        row = conn.execute(
            """
            SELECT * FROM messages
            WHERE source = 'private_userbot' AND owner_id = ? AND chat_id = ? AND message_id = ?
            """,
            (owner_id, chat_id, message_id),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    async def _handle_private_edit(self, owner_id: int, event) -> None:
        msg = event.message
        old = self._get_cached(owner_id, event.chat_id, msg.id)
        new_text = msg.raw_text or ""
        if old and old["text"] and old["text"] != new_text:
            body = (
                "📝 <b>Изменённое личное сообщение:</b>\n\n"
                f"💬 <b>Старый текст:</b>\n« {old['text']} »\n\n"
                f"📝 <b>Новый текст:</b>\n« {new_text} »\n\n"
                f"Собеседник: {old['user_name']}"
            )
            await self.bot.send_message(owner_id, body, parse_mode="HTML")
        conn = self._db()
        conn.execute(
            """
            UPDATE messages SET text = ?
            WHERE source = 'private_userbot' AND owner_id = ? AND chat_id = ? AND message_id = ?
            """,
            (new_text, owner_id, event.chat_id, msg.id),
        )
        conn.commit()
        conn.close()

    async def _handle_private_delete(self, owner_id: int, event) -> None:
        conn = self._db()
        for message_id in event.deleted_ids:
            if event.chat_id is not None:
                row = conn.execute(
                    """
                    SELECT * FROM messages
                    WHERE source = 'private_userbot' AND owner_id = ? AND chat_id = ? AND message_id = ? AND deleted = 0
                    """,
                    (owner_id, event.chat_id, message_id),
                ).fetchone()
            else:
                # Telegram не сообщает чат для личных удалений — угадываем
                # по самому недавнему совпадению id в кэше этого владельца.
                row = conn.execute(
                    """
                    SELECT * FROM messages
                    WHERE source = 'private_userbot' AND owner_id = ? AND message_id = ? AND deleted = 0
                    ORDER BY date DESC LIMIT 1
                    """,
                    (owner_id, message_id),
                ).fetchone()
            if not row:
                continue
            row = dict(row)
            conn.execute(
                "UPDATE messages SET deleted = 1 WHERE source = 'private_userbot' AND owner_id = ? AND chat_id = ? AND message_id = ?",
                (owner_id, row["chat_id"], row["message_id"]),
            )
            conn.commit()
            await self._announce_private_deleted(owner_id, row)
        conn.close()

    async def _announce_private_deleted(self, owner_id: int, row: dict) -> None:
        header = (
            f"🗑 <b>Поймано удалённое личное сообщение!</b>\n{DIVIDER}\n\n"
            f"👤 Собеседник: {row['user_name']}"
        )
        try:
            if row["media_type"] and row["media_path"] and os.path.exists(row["media_path"]):
                caption = header if not row["text"] else f"{header}\n\n{row['text']}"
                await send_local_media(self.bot, owner_id, row["media_type"], row["media_path"], caption)
            else:
                body = f"{header}\n\n💬 {row['text'] or '(пусто либо медиа устарело)'}"
                await self.bot.send_message(owner_id, body, parse_mode="HTML")
        except Exception:
            logger.exception("Не удалось отправить оповещение об удалении личного сообщения")

    # ---------- Обслуживание ----------
    async def cleanup_old_media(self) -> None:
        cutoff = int(time.time()) - MAX_PRIVATE_MESSAGE_AGE
        conn = self._db()
        rows = conn.execute(
            "SELECT media_path FROM messages WHERE source = 'private_userbot' AND date < ? AND media_path IS NOT NULL",
            (cutoff,),
        ).fetchall()
        for row in rows:
            try:
                if row["media_path"] and os.path.exists(row["media_path"]):
                    os.remove(row["media_path"])
            except OSError:
                pass
        conn.execute(
            "DELETE FROM messages WHERE source = 'private_userbot' AND date < ?", (cutoff,)
        )
        conn.commit()
        conn.close()
