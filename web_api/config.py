import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
MINIAPP_ACCESS_MODE = os.environ.get("MINIAPP_ACCESS_MODE", "admin_only").strip().lower()
if MINIAPP_ACCESS_MODE not in {"admin_only", "public"}:
    raise RuntimeError("MINIAPP_ACCESS_MODE должен быть admin_only или public")
# CORS: Mini App is served from Telegram's own webview origin, not a fixed domain we control in
# dev -- см. README.md за тем, как сузить это в проде (Telegram сам передаёт Origin: null для
# webview в некоторых клиентах, поэтому жёсткий allowlist по домену тут не всегда применим).
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("WEB_API_ALLOWED_ORIGINS", "*").split(",") if o.strip()]
