"""Bounded process-local admission limits for the single owner/gateway deployment."""
import time
import os
import threading
from collections import OrderedDict
from starlette.responses import JSONResponse


class WindowLimiter:
    def __init__(self, capacity=20000):
        self.capacity = capacity
        self.windows = OrderedDict()
        self.lock = threading.Lock()

    def allow(self, key, limit):
        now = time.monotonic()
        with self.lock:
            while self.windows and next(iter(self.windows.values()))[0] <= now - 60:
                self.windows.popitem(last=False)
            start, count = self.windows.get(key, (now, 0))
            if start <= now - 60:
                start, count = now, 0
            if key not in self.windows and len(self.windows) >= self.capacity:
                return False  # never evict a hot abusive key to reset its quota
            if count >= limit:
                return False
            self.windows[key] = (start, count + 1)
            return True


user_limiter = WindowLimiter()


class RequestLimits:
    def __init__(self, app):
        self.app = app
        self.auth = WindowLimiter()

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope['path'].startswith('/api/v1/'):
            return await self.app(scope, receive, send)
        # Caller-controlled forwarded headers are deliberately not used.
        if scope['path'] == '/api/v1/auth/telegram':
            peer = str((scope.get('client') or ('unknown',))[0])
            if not self.auth.allow(peer, 3000 if os.environ.get('BOT_SYNC_MODE') == 'owner' else 120):
                return await JSONResponse({'detail': 'Слишком много попыток входа. Подожди минуту.'}, status_code=429, headers={'Retry-After': '60'})(scope, receive, send)
        size = 0
        async def limited_receive():
            nonlocal size
            message = await receive()
            size += len(message.get('body', b''))
            if size > 10 * 1024 * 1024:
                from starlette.exceptions import HTTPException
                raise HTTPException(413, 'Запрос слишком большой')
            return message
        await self.app(scope, limited_receive, send)
