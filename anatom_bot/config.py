"""Environment-driven configuration for the anatom-bot service pair (bot process + API process)."""

from __future__ import annotations

import os


def _env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value or ""


def _normalize_database_url(url: str) -> str:
    """Railway (and Heroku-style providers) hand out `postgres://`/`postgresql://` — the async
    engine needs the `+asyncpg` driver suffix, so rewrite it rather than requiring people to
    hand-edit the string every time they copy it from the provider's dashboard."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix) and "+asyncpg" not in url:
            return "postgresql+asyncpg://" + url[len(prefix) :]
    return url


BOT_TOKEN = _env("ANATOM_BOT_TOKEN", required=True)
BOT_USERNAME = _env("ANATOM_BOT_USERNAME", "Vmeda_anatom_bot")
DATABASE_URL = _normalize_database_url(_env("DATABASE_URL", required=True))

# Website origin the bot links out to (e.g. https://anatom.example.com). Used to build
# the "Открыть АНАТОМ" button and the deep-link login URL.
WEBAPP_URL = _env("ANATOM_WEBAPP_URL", "https://anatom.dc.example")

# Secret used to sign session tokens handed to the web app after a successful login.
SESSION_SECRET = _env("ANATOM_SESSION_SECRET", required=True)
SESSION_TTL_SECONDS = int(_env("ANATOM_SESSION_TTL_SECONDS", str(30 * 24 * 3600)))

# How long a Telegram Login Widget payload is considered fresh (guards against replay).
TELEGRAM_AUTH_MAX_AGE_SECONDS = int(_env("ANATOM_TELEGRAM_AUTH_MAX_AGE_SECONDS", "86400"))

# Deep-link login code (used by /start <code>) lifetime.
LOGIN_CODE_TTL_SECONDS = int(_env("ANATOM_LOGIN_CODE_TTL_SECONDS", "600"))

# Inactivity win-back threshold, in days ("не заходил >14 дней").
INACTIVITY_THRESHOLD_DAYS = int(_env("ANATOM_INACTIVITY_THRESHOLD_DAYS", "14"))

SUPPORT_URL = _env("ANATOM_SUPPORT_URL", "https://t.me/vmeda_helper")
