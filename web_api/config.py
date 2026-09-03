import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
# CORS: Mini App is served from Telegram's own webview origin, not a fixed domain we control in
# dev -- см. README.md за тем, как сузить это в проде (Telegram сам передаёт Origin: null для
# webview в некоторых клиентах, поэтому жёсткий allowlist по домену тут не всегда применим).
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("WEB_API_ALLOWED_ORIGINS", "*").split(",") if o.strip()]
