"""Secret-protected, read-only rollout checks; never returns user records."""
import hmac
import os

import httpx
from fastapi import APIRouter, Header, HTTPException

from ..data_safety import backup_status

router = APIRouter(prefix='/internal/sync', tags=['internal'])


@router.get('/status')
async def status(x_vmeda_sync_token: str = Header(default='')):
    token = os.environ.get('BOT_SYNC_TOKEN', '')
    if not token or not hmac.compare_digest(token.encode(), x_vmeda_sync_token.encode()):
        raise HTTPException(status_code=403, detail='Нет доступа')
    mode = os.environ.get('BOT_SYNC_MODE')
    result = {'mode': mode, 'backups': backup_status}
    if mode == 'gateway':
        try:
            async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
                response = await client.get(os.environ['BOT_SYNC_URL'].rstrip('/')+'/internal/sync/status', headers={'X-Vmeda-Sync-Token': token})
                response.raise_for_status()
                result['owner'] = response.json()
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=503, detail='Владелец статистики недоступен') from exc
    elif mode == 'owner':
        from ..bot_state import get_bot_module
        tb = get_bot_module()
        result['users'] = len(tb.stats['total_users'])
        result['content_revision'] = os.environ.get('RAILWAY_GIT_COMMIT_SHA')
    else:
        raise HTTPException(status_code=404, detail='Синхронизация отключена')
    return result
