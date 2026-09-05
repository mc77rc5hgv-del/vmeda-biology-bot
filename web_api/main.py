"""VMEDA web_api -- read-only backend для Mini App (ТЗ, Этап 3). Отдельный процесс от
telegram_bot.py (свой `uvicorn web_api.main:app`), НЕ добавлен в Procfile/railway.json бота --
как и telegram_bot.py, требует запуска из корня репозитория (относительные пути к JSON-контенту,
см. repositories/knowledge.py) и того же BOT_TOKEN, что и сам бот (см. bot_state.py).

Запуск:
    export BOT_TOKEN=...            # тот же токен, что у бота
    export SESSION_SECRET=...       # отдельный секрет, только для web_api
    export STATS_DIR=...            # тот же persistent volume, где бот хранит stats.json
    uvicorn web_api.main:app --reload
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .routers import access, ai, auth, me, subjects

app = FastAPI(title="VMEDA web_api", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth.router)
app.include_router(me.router)
app.include_router(access.router)
app.include_router(subjects.router)
app.include_router(ai.router)


@app.get("/healthz")
def healthz() -> dict:
    """Не /api/v1/... -- служебный эндпоинт для Railway healthcheck, не часть публичного API."""
    return {"status": "ok"}
