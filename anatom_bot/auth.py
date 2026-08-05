"""Telegram Login Widget verification + session tokens for the web app.

Pure functions only (no DB/network) so they're unit-testable without a live bot token or Postgres.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Any, Optional

import jwt

TELEGRAM_AUTH_FIELDS = (
    "id",
    "first_name",
    "last_name",
    "username",
    "photo_url",
    "auth_date",
)


def telegram_data_check_string(payload: dict[str, Any]) -> str:
    pairs = [f"{key}={payload[key]}" for key in sorted(payload) if key != "hash" and payload[key] is not None]
    return "\n".join(pairs)


def verify_telegram_auth(
    payload: dict[str, Any], bot_token: str, *, max_age_seconds: int, now: Optional[int] = None
) -> bool:
    """Validate the {id, first_name, ..., auth_date, hash} object Telegram Login Widget returns.

    See https://core.telegram.org/widgets/login#checking-authorization.
    """
    received_hash = payload.get("hash")
    if not received_hash:
        return False

    data_check_string = telegram_data_check_string(payload)
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, str(received_hash)):
        return False

    auth_date = payload.get("auth_date")
    if auth_date is None:
        return False
    now = now if now is not None else int(time.time())
    if now - int(auth_date) > max_age_seconds:
        return False

    return True


def create_session_token(user_id: int, secret: str, ttl_seconds: int) -> str:
    now = int(time.time())
    payload = {"sub": str(user_id), "iat": now, "exp": now + ttl_seconds}
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_session_token(token: str, secret: str) -> Optional[int]:
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    try:
        return int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        return None


def generate_login_code() -> str:
    return secrets.token_urlsafe(16)
