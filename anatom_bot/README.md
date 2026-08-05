# anatom-bot

`@Vmeda_anatom_bot` — Telegram auth + reminders bridge for the (separately hosted) АНАТОМ web app.
Independent of `telegram_bot.py` at the repo root: separate deps, separate Postgres DB, separate deploy.
Full design: [`../docs/anatom-bot-spec.md`](../docs/anatom-bot-spec.md).

## Layout

- `config.py` — env-driven settings.
- `db.py` — SQLAlchemy async models (`User`, `UserState`, `Reminder`, `LoginSession`) + session helpers.
  Shared by both processes below; each connects to Postgres directly, there's no HTTP hop between them.
- `auth.py` — Telegram Login Widget hash verification, JWT session tokens, login-code generation. Pure
  functions, no I/O — see `tests/test_auth.py`.
- `state_logic.py` — pure helpers over the frontend's `state` JSON blob (due-for-review count, streak-risk,
  inactivity check, achievement diffing, message templates). See `tests/test_state_logic.py`.
- `api.py` — FastAPI app: `POST /auth/telegram` (Login Widget), `POST /auth/start` + `GET /auth/session/{code}`
  (deep-link `/start <code>` flow), `GET`/`PUT /api/state`.
- `bot.py` — aiogram bot: `/start /study /progress /review /streak /reminder /reminder_off /help`.
- `scheduler.py` — APScheduler cron jobs (runs inside the bot process): daily reminder, evening streak
  protection, 14-day inactivity win-back.

## Running locally

```
pip install -r requirements.txt
cp .env.example .env   # fill in ANATOM_BOT_TOKEN, DATABASE_URL, ANATOM_SESSION_SECRET
set -a && source .env && set +a

python3 bot.py                                  # bot + scheduler (long polling)
uvicorn api:app --reload --port 8000             # auth/state API for the web app
```

Both processes call `db.init_models()` on startup, so tables are created automatically against
whatever Postgres `DATABASE_URL` points at — no separate migration step yet.

## Tests

Pure-logic unit tests only (no live bot token or Postgres needed):

```
python3 -m unittest discover -s tests
```

## Deploying

Two Railway services sharing one `DATABASE_URL`:
1. Bot worker: `python3 bot.py` (long polling + the reminder cron jobs).
2. API web service: `uvicorn api:app --host 0.0.0.0 --port $PORT`.

## Open items / assumptions to confirm with the frontend

- `state["progress"][topicId]` is assumed to look like `{"nextReview": <epoch seconds>, "percent": 0-100,
  "accuracy": 0-100, "title": str}` for `/review`, `/progress`, and the achievement nudge — the real frontend
  shape isn't documented yet beyond the top-level `state` keys. Update `state_logic.py` once it's confirmed.
- `/auth/start` builds its deep-link from `ANATOM_BOT_USERNAME` (defaults to `Vmeda_anatom_bot`) — override it
  if the bot is ever registered under a different @username.
- `api.py`'s `PUT /api/state` diffs old vs. new state on every save and pushes an achievement message via a
  send-only `Bot` instance (no polling, so it's safe to share the token with the polling process in `bot.py`).
