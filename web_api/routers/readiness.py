"""Read-only dependency readiness; never creates a database or exposes identities."""
import asyncio
import hmac
import os
import sqlite3
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter(tags=['health'])


def storage_ready():
    path = Path(os.environ.get('MINIAPP_LEARNING_DB') or str(Path(os.environ.get('STATS_DIR', '.')) / 'miniapp_learning.sqlite3')).resolve()
    if not path.is_file():
        return False
    try:
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2) as db:
            return db.execute('PRAGMA quick_check').fetchone()[0] == 'ok' and bool(db.execute(
                'SELECT 1 FROM sqlite_master WHERE type="table" AND name="learning_materials"').fetchone())
    except (sqlite3.Error, OSError):
        return False


async def remote_ready(url, endpoint):
    try:
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            r = await client.get(url.rstrip('/') + endpoint, headers={'X-Vmeda-Sync-Token': os.environ.get('BOT_SYNC_TOKEN', '')})
        return r.status_code == 200 and r.json().get('status') == 'ready'
    except (httpx.HTTPError, ValueError, AttributeError):
        return False


async def checks():
    from ..sync_transport import mode
    current = mode()
    if current == 'gateway':
        storage, owner = await asyncio.gather(asyncio.to_thread(storage_ready), remote_ready(
            os.environ.get('BOT_SYNC_URL', ''), '/readyz'))
        return {'learning': storage, 'owner': owner}
    if current == 'owner':
        from ..bot_state import get_bot_module
        tb = get_bot_module()
        owner = bool(getattr(tb, '_sync_owner_running', False) and isinstance(tb.stats.get('total_users'), set))
        learning = await remote_ready(os.environ.get('LEARNING_BACKEND_URL', ''), '/internal/sync/storage')
        enabled = os.environ.get('CODEEPAY_ENABLED', 'false').lower().strip() in ('true', '1')
        billing = True
        if enabled:
            from services.payments.runtime import runtime
            service = runtime(tb)
            task = getattr(service, 'poll_task', None)
            billing = bool(service and task and not task.done() and service.provider.public_status()['available']
                           and service.provider_healthy and time.time() - service.last_poll_at < 90)
            if billing:
                try:
                    with service.ledger.connect() as db:
                        billing = db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
                except (sqlite3.Error, OSError):
                    billing = False
        return {'owner': owner, 'learning': learning, 'billing': billing}
    return {'learning': await asyncio.to_thread(storage_ready)}


@router.get('/internal/sync/storage')
async def storage(x_vmeda_sync_token: str = Header(default='')):
    token = os.environ.get('BOT_SYNC_TOKEN', '')
    if not token or not hmac.compare_digest(token.encode(), x_vmeda_sync_token.encode()):
        raise HTTPException(403, detail='Нет доступа')
    if os.environ.get('BOT_SYNC_MODE') != 'gateway':
        raise HTTPException(404, detail='Не найдено')
    good = await asyncio.to_thread(storage_ready)
    return JSONResponse({'status': 'ready' if good else 'unavailable'}, status_code=200 if good else 503)


@router.get('/healthz')
@router.get('/readyz')
async def readiness():
    try:
        result = await checks()
    except Exception:
        result = {'dependencies': False}
    ready = all(result.values())
    return JSONResponse({'status': 'ready' if ready else 'unavailable', 'checks': result},
                        status_code=200 if ready else 503, headers={'Cache-Control': 'no-store'})
