"""Opt-in gateway to the running bot; no copying or writing stats.json."""
from __future__ import annotations

import hmac
import os

import httpx
from starlette.responses import JSONResponse, Response

HOP_HEADERS = {
    b'connection', b'keep-alive', b'proxy-authenticate', b'proxy-authorization',
    b'te', b'trailer', b'transfer-encoding', b'upgrade', b'host',
}


class BotGateway:
    def __init__(self, app, url: str, token: str):
        if not url.startswith(('http://', 'https://')) or not token:
            raise RuntimeError('BOT_SYNC_URL and BOT_SYNC_TOKEN are required for the gateway')
        self.app, self.url, self.token = app, url.rstrip('/'), token

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope['path'].startswith('/api/v1/'):
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            size += len(chunk)
            if size > 16 * 1024 * 1024:
                return await JSONResponse({'detail': 'Запрос слишком большой'}, status_code=413, headers={'Cache-Control': 'no-store'})(scope, receive, send)
            chunks.append(chunk)
            if not message.get('more_body', False):
                break
        headers = [(k.decode('latin-1'), v.decode('latin-1')) for k, v in scope['headers']
                   if k.lower() not in HOP_HEADERS | {b'x-vmeda-sync-token', b'content-length', b'accept-encoding'}]
        headers.extend([('X-Vmeda-Sync-Token', self.token), ('Accept-Encoding', 'identity')])
        path = scope.get('raw_path', scope['path'].encode()).decode('ascii')
        query = scope.get('query_string', b'')
        url = self.url + path + (('?' + query.decode('ascii')) if query else '')
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=5), trust_env=False) as client:
                upstream = await client.request(scope['method'], url, headers=headers, content=b''.join(chunks))
        except httpx.HTTPError:
            # Never fall back to a different, possibly empty stats.json.
            return await JSONResponse({'detail': 'Связь с ботом временно недоступна. Повтори запрос.'}, status_code=503, headers={'Cache-Control': 'no-store'})(scope, receive, send)
        response = Response(upstream.content, status_code=upstream.status_code)
        response.raw_headers = [(k.lower(), v) for k, v in upstream.headers.raw
                                if k.lower() not in HOP_HEADERS | {b'content-length', b'content-encoding', b'cache-control'}]
        response.raw_headers.append((b'content-length', str(len(upstream.content)).encode()))
        response.raw_headers.append((b'cache-control', b'no-store'))
        await response(scope, receive, send)


class OwnerGuard:
    def __init__(self, app, token: str):
        if not token:
            raise RuntimeError('BOT_SYNC_TOKEN is required for owner mode')
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and scope['path'] != '/healthz':
            supplied = next((v.decode('latin-1') for k, v in scope['headers'] if k.lower() == b'x-vmeda-sync-token'), '')
            if not hmac.compare_digest(supplied.encode(), self.token.encode()):
                return await JSONResponse({'detail': 'Нет доступа к внутреннему API'}, status_code=403)(scope, receive, send)
        await self.app(scope, receive, send)


def mode() -> str:
    value = os.environ.get('BOT_SYNC_MODE', 'legacy').strip().lower()
    if value not in {'legacy', 'gateway', 'owner'}:
        raise RuntimeError('BOT_SYNC_MODE must be legacy, gateway or owner')
    return value
