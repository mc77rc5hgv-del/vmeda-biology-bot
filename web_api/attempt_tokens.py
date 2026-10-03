"""Signed, user/material/scope-bound retry keys. No in-memory attempt registry."""
import base64
import hashlib
import hmac
import json
import time
import uuid

from fastapi import HTTPException
from . import config


def issue(user_id: int, material: str, scope: str) -> str:
    payload = json.dumps([user_id, material, scope, int(time.time()) + 7200, uuid.uuid4().hex], separators=(',', ':')).encode()
    encoded = base64.urlsafe_b64encode(payload).rstrip(b'=')
    signature = hmac.new(config.SESSION_SECRET.encode(), encoded, hashlib.sha256).hexdigest()
    return encoded.decode() + '.' + signature


def verify(token: str | None, user_id: int, material: str, scope: str):
    try:
        encoded, signature = (token or '').split('.')
        expected = hmac.new(config.SESSION_SECRET.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        payload = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
        if not hmac.compare_digest(signature, expected) or payload[:3] != [user_id, material, scope] or payload[3] <= time.time():
            raise ValueError('invalid attempt')
    except (ValueError, TypeError, IndexError, UnicodeError) as exc:
        raise HTTPException(status_code=409, detail='Попытка истекла. Начни зачёт заново.') from exc
