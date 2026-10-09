"""VMEDA web_api -- backend для Mini App. Отдельный процесс от
telegram_bot.py (свой `uvicorn web_api.main:app`), НЕ добавлен в Procfile/railway.json бота --
как и telegram_bot.py, требует запуска из корня репозитория (относительные пути к JSON-контенту,
см. repositories/knowledge.py) и того же BOT_TOKEN, что и сам бот (см. bot_state.py).

Запуск:
    export BOT_TOKEN=...            # тот же токен, что у бота
    export SESSION_SECRET=...       # отдельный секрет, только для web_api
    export STATS_DIR=...            # тот же persistent volume, где бот хранит stats.json
    uvicorn web_api.main:app --reload
"""
import asyncio
from contextlib import asynccontextmanager, closing

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .routers import access, ai, auth, learning, me, subjects, sync, anatomy_runs, diagnostics, subscriptions
from . import learning_rpc
from .routers import readiness
from .limits import RequestLimits
from .sync_transport import BotGateway, OwnerGuard, mode

@asynccontextmanager
async def lifespan(_app):
    if mode() == 'gateway':
        # Validate and snapshot the existing journal before reporting readiness.
        # No owner request is required, so the gateway can start first.
        def prepare_storage():
            from .learning import _connect
            with closing(_connect()):
                pass
        await asyncio.to_thread(prepare_storage)
    from services.offsite_backup import periodic
    backup_task = asyncio.create_task(periodic()) if mode() == 'gateway' else None
    try:
        yield
    finally:
        if backup_task:
            backup_task.cancel()
            await asyncio.gather(backup_task, return_exceptions=True)


app = FastAPI(title="VMEDA web_api", version="0.2.0", lifespan=lifespan)


app.include_router(auth.router)
app.include_router(me.router)
app.include_router(access.router)
app.include_router(subjects.router)
app.include_router(ai.router)
app.include_router(learning.router)
app.include_router(sync.router)
app.include_router(anatomy_runs.router)
app.include_router(learning_rpc.router)
app.include_router(diagnostics.router)
app.include_router(subscriptions.router)
app.include_router(readiness.router)

sync_mode = mode()
if sync_mode == 'gateway':
    import os
    app.add_middleware(BotGateway, url=os.environ.get('BOT_SYNC_URL', ''), token=os.environ.get('BOT_SYNC_TOKEN', ''))
elif sync_mode == 'owner':
    import os
    app.add_middleware(OwnerGuard, token=os.environ.get('BOT_SYNC_TOKEN', ''))


app.add_middleware(RequestLimits)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["X-VMEDA-Subscription-Required"],
)


@app.get("/livez")
def healthz() -> dict:
    """Process liveness only; /healthz and /readyz check dependencies."""
    return {"status": "ok"}
