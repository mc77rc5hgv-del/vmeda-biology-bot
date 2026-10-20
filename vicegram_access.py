"""Single-owner access; Telegram-authenticated username is pinned to a durable ID.

Existing application records are only read. A separate, atomic policy file survives
deployments and prevents a subsequently reassigned username from obtaining access.
"""
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path


class SingleOwnerAccess:
    username = "vmeda_helper"

    def __init__(self, db_path):
        self.db_path = Path(db_path).resolve()
        self.pin_path = self.db_path.with_name("vicegram-owner-access.json")
        self.owner_id = None
        if self.pin_path.exists():
            record = json.loads(self.pin_path.read_text(encoding="utf-8"))
            owner = record.get("user_id")
            if record.get("username") != self.username or type(owner) is not int or owner <= 0:
                raise ValueError("Invalid Vicegram owner identity file")
            self.owner_id = owner

    def permits(self, user_id):
        return self.owner_id is not None and user_id == self.owner_id

    def authenticate(self, user):
        if user is None or getattr(user, "is_bot", False):
            return False
        if self.owner_id is not None:
            return self.permits(user.id)
        if (getattr(user, "username", None) or "").casefold() != self.username:
            return False
        # Publish only a fully written file. Never overwrite an existing identity.
        payload = json.dumps({"username": self.username, "user_id": user.id})
        import tempfile
        fd, temporary = tempfile.mkstemp(prefix=".vicegram-owner-", dir=self.pin_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, self.pin_path)
                directory = os.open(self.pin_path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            except FileExistsError:
                pass
            record = json.loads(self.pin_path.read_text(encoding="utf-8"))
            if record.get("username") != self.username or type(record.get("user_id")) is not int:
                raise ValueError("Invalid Vicegram owner identity file")
            self.owner_id = record["user_id"]
        finally:
            os.unlink(temporary)
        return self.permits(user.id)

    def read(self, sql, args=()):
        with closing(sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(sql, args)]

    def group_owner(self, chat_id):
        rows = self.read("SELECT owner_id FROM settings WHERE chat_id = ?", (chat_id,))
        return rows[0]["owner_id"] if rows else None

    async def resolve_existing(self, bot):
        if self.owner_id is not None:
            return
        candidates = self.read("SELECT user_id FROM users WHERE lower(username) = ?", (self.username,))
        for candidate in candidates:
            try:
                user = await bot.get_chat(candidate["user_id"])
            except Exception:
                continue
            if self.authenticate(user):
                return

    async def __call__(self, handler, update, data):
        kind = update.event_type
        event = update.event
        if kind == "business_connection":
            allowed = self.authenticate(event.user)
        elif kind in {"business_message", "edited_business_message", "deleted_business_messages"}:
            rows = self.read(
                "SELECT owner_id, is_enabled FROM business_connections WHERE business_connection_id = ?",
                (event.business_connection_id,),
            )
            if rows:
                allowed = bool(rows[0]["is_enabled"]) and self.permits(rows[0]["owner_id"])
            else:
                # A connection may predate this bot process. Validate its OWNER,
                # never the sender/recipient of a business message.
                connection = await data["bot"].get_business_connection(event.business_connection_id)
                allowed = connection.is_enabled and self.authenticate(connection.user)
                if allowed:
                    data["vicegram_register_connection"](connection)
        else:
            actor = getattr(event, "from_user", None)
            allowed = self.authenticate(actor)
            message = getattr(event, "message", None) if kind == "callback_query" else event
            chat = getattr(message, "chat", None)
            if chat and chat.type in {"group", "supergroup"}:
                owner = self.group_owner(chat.id)
                if kind in {"message", "edited_message"} and not allowed:
                    text = getattr(event, "text", None) or getattr(event, "caption", None) or ""
                    allowed = self.permits(owner) and not text.lstrip().startswith("/")
                elif allowed:
                    allowed = owner is None or self.permits(owner)
        if allowed:
            return await handler(update, data)
        if kind == "callback_query":
            await event.answer("VICEGRAM доступен только @vmeda_helper.", show_alert=True)
        elif kind == "pre_checkout_query":
            await event.answer(ok=False, error_message="VICEGRAM доступен только @vmeda_helper.")
        elif kind == "message" and getattr(event, "chat", None) and event.chat.type == "private":
            if (event.text or "").split(maxsplit=1)[0:1] == ["/start"]:
                await event.answer("VICEGRAM доступен только @vmeda_helper.")
        return None
