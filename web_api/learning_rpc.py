"""Use the EXISTING Mini App SQLite through a narrowly scoped internal API."""
from __future__ import annotations

import functools
import hmac
import inspect
import os
import atexit
import threading

import httpx
from fastapi import APIRouter, Header, HTTPException

_client = None
_client_lock = threading.Lock()

def rpc_client():
    global _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(timeout=httpx.Timeout(10, pool=2), trust_env=False, limits=httpx.Limits(max_connections=32, max_keepalive_connections=16))
            atexit.register(_client.close)
        return _client

OPERATIONS = frozenset({
    'touch_material', 'set_material_flag', 'record_quiz_attempt', 'record_histology_attempt',
    'set_navigation', 'get_histology_mistake_ids', 'get_histology_stats', 'get_state', 'get_dashboard',
    'create_anatomy_run', 'get_anatomy_run', 'active_anatomy_run', 'answer_anatomy_run',
    'get_anatomy_mistakes', 'get_anatomy_scores',
})
router = APIRouter(prefix='/internal/sync/learning', tags=['internal'])


@router.post('/{operation}')
def invoke(operation: str, payload: dict, x_vmeda_sync_token: str = Header(default='')):
    secret = os.environ.get('BOT_SYNC_TOKEN', '')
    if not secret or not hmac.compare_digest(secret.encode(), x_vmeda_sync_token.encode()):
        raise HTTPException(status_code=403, detail='Нет доступа')
    if os.environ.get('BOT_SYNC_MODE') != 'gateway' or operation not in OPERATIONS:
        raise HTTPException(status_code=404, detail='Операция не найдена')
    from . import learning
    function = getattr(learning, operation)
    try:
        bound = inspect.signature(function).bind(**payload)
    except TypeError as exc:
        raise HTTPException(status_code=422, detail='Некорректные аргументы') from exc
    uid = bound.arguments.get('user_id')
    if type(uid) is not int or uid <= 0:
        raise HTTPException(status_code=422, detail='Некорректный пользователь')
    return {'result': function(*bound.args, **bound.kwargs)}


def install_remote_backend(namespace: dict) -> None:
    if os.environ.get('BOT_SYNC_MODE') != 'owner':
        return
    url, token = os.environ.get('LEARNING_BACKEND_URL', ''), os.environ.get('BOT_SYNC_TOKEN', '')
    if not url.startswith(('http://', 'https://')) or not token:
        raise RuntimeError('Owner requires LEARNING_BACKEND_URL and BOT_SYNC_TOKEN; no empty learning DB fallback')
    for name in OPERATIONS:
        original = namespace[name]
        signature = inspect.signature(original)

        def remote(*args, _name=name, _signature=signature, **kwargs):
            payload = dict(_signature.bind(*args, **kwargs).arguments)
            try:
                response = rpc_client().post(
                    url.rstrip('/') + '/internal/sync/learning/' + _name,
                    json=payload, headers={'X-Vmeda-Sync-Token': token},
                )
                if response.status_code in (400, 404, 409, 422):
                    raise HTTPException(status_code=response.status_code, detail=response.json().get('detail', 'Некорректный запрос'))
                response.raise_for_status()
                return response.json()['result']
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                raise HTTPException(status_code=503, detail='Учебный прогресс временно недоступен; данные сохранены.') from exc

        namespace[name] = functools.wraps(original)(remote)
