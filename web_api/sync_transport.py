"""Opt-in gateway to the running bot; no copying or writing stats.json."""
from __future__ import annotations

import hmac
import os

import httpx
from starlette.responses import JSONResponse

HOP_HEADERS = {
    b'connection', b'keep-alive', b'proxy-authenticate', b'proxy-authorization',
    b'te', b'trailer', b'transfer-encoding', b'upgrade', b'host',
}


class BotGateway:
    def __init__(self, app, url: str, token: str):
        if not url.startswith(('http://', 'https://')) or not token:
            raise RuntimeError('BOT_SYNC_URL and BOT_SYNC_TOKEN are required for the gateway')
        self.app, self.url, self.token = app, url.rstrip('/'), token
        self._client = None
        self._active = 0
        self.requests = self.rejected = self.failures = 0

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            async def lifecycle_receive():
                message = await receive()
                if message['type'] == 'lifespan.shutdown' and self._client:
                    await self._client.aclose()
                return message
            return await self.app(scope, lifecycle_receive, send)
        if scope['type'] != 'http' or not scope['path'].startswith('/api/v1/'):
            return await self.app(scope, receive, send)
        self.requests += 1
        if self._active >= 64:
            self.rejected += 1
            return await JSONResponse({'detail': 'Сервис занят. Подожди и повтори запрос.'}, status_code=503, headers={'Retry-After': '5', 'Cache-Control': 'no-store'})(scope, receive, send)
        self._active += 1
        upstream = None
        try:
            chunks, size = [], 0
            while True:
                message = await receive()
                if message['type'] == 'http.disconnect':
                    return
                chunk = message.get('body', b'')
                size += len(chunk)
                if size > 10 * 1024 * 1024:
                    return await JSONResponse({'detail': 'Запрос слишком большой'}, status_code=413)(scope, receive, send)
                chunks.append(chunk)
                if not message.get('more_body', False):
                    break
            headers = [(k.decode('latin-1'), v.decode('latin-1')) for k, v in scope['headers'] if k.lower() not in HOP_HEADERS | {b'x-vmeda-sync-token', b'content-length', b'accept-encoding'}]
            headers.extend([('X-Vmeda-Sync-Token', self.token), ('Accept-Encoding', 'identity')])
            path = scope.get('raw_path', scope['path'].encode()).decode('ascii')
            query = scope.get('query_string', b'')
            url = self.url + path + (('?' + query.decode('ascii')) if query else '')
            if self._client is None:
                self._client = httpx.AsyncClient(timeout=httpx.Timeout(75, connect=5, pool=5), trust_env=False, limits=httpx.Limits(max_connections=64, max_keepalive_connections=32))
            request = self._client.build_request(scope['method'], url, headers=headers, content=b''.join(chunks))
            try:
                upstream = await self._client.send(request, stream=True)
            except httpx.HTTPError:
                self.failures += 1
                return await JSONResponse({'detail': 'Связь с ботом временно недоступна. Проверь историю оплаты перед повтором.'}, status_code=503, headers={'Cache-Control': 'no-store'})(scope, receive, send)
            response_headers = [(k.lower(), v) for k, v in upstream.headers.raw if k.lower() not in HOP_HEADERS | {b'cache-control'}]
            response_headers.append((b'cache-control', b'no-store'))
            await send({'type': 'http.response.start', 'status': upstream.status_code, 'headers': response_headers})
            if upstream.is_stream_consumed:  # in-process ASGI/mock transport already buffered
                await send({'type': 'http.response.body', 'body': upstream.content, 'more_body': True})
            else:
                async for chunk in upstream.aiter_raw():
                    await send({'type': 'http.response.body', 'body': chunk, 'more_body': True})
            await send({'type': 'http.response.body', 'body': b'', 'more_body': False})
        finally:
            if upstream:
                await upstream.aclose()
            self._active -= 1


class OwnerGuard:
    def __init__(self, app, token: str):
        if not token:
            raise RuntimeError('BOT_SYNC_TOKEN is required for owner mode')
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and scope['path'] not in ('/healthz', '/readyz', '/livez'):
            supplied = next((v.decode('latin-1') for k, v in scope['headers'] if k.lower() == b'x-vmeda-sync-token'), '')
            if not hmac.compare_digest(supplied.encode(), self.token.encode()):
                return await JSONResponse({'detail': 'Нет доступа к внутреннему API'}, status_code=403)(scope, receive, send)
        await self.app(scope, receive, send)


def mode() -> str:
    value = os.environ.get('BOT_SYNC_MODE', 'legacy').strip().lower()
    if value not in {'legacy', 'gateway', 'owner'}:
        raise RuntimeError('BOT_SYNC_MODE must be legacy, gateway or owner')
    return value
