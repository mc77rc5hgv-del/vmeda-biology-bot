"""Короткоживущая серверная сессия (ТЗ §5, шаг 7) -- выдаётся ПОСЛЕ успешной проверки initData
(auth.verify_telegram_init_data), обменивается на неё именно чтобы фронту не нужно было слать
initData заново в каждом запросе (initData годится максимум на MAX_INIT_DATA_AGE_SECONDS и не
предназначена для использования как bearer-токен на каждый чих).

Простой HMAC-подписанный токен, не JWT-библиотека -- формат и алгоритм settled и понятны без
внешней зависимости, то же самое соображение, что и решение не тащить @telegram-apps/sdk во
frontend (см. miniapp/index.html): маленький, предсказуемый примитив вместо чужого пакета ради
одной функции."""
import base64
import hashlib
import hmac
import json
import time

SESSION_TTL_SECONDS = 6 * 60 * 60  # 6 часов -- короче, чем максимальная жизнь initData, но
                                     # достаточно, чтобы не заставлять переавторизовываться на
                                     # каждое открытие экрана


class SessionTokenError(Exception):
    pass


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_session_token(user_id: int, secret: str, *, now: float | None = None) -> str:
    if not secret:
        raise SessionTokenError("SESSION_SECRET не задан на сервере")
    issued_at = now if now is not None else time.time()
    payload = {"uid": user_id, "iat": issued_at, "exp": issued_at + SESSION_TTL_SECONDS}
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64encode(payload_bytes)
    signature = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def verify_session_token(token: str, secret: str, *, now: float | None = None) -> int:
    """Возвращает user_id, если токен подлинный и не истёк, иначе бросает SessionTokenError."""
    if not secret:
        raise SessionTokenError("SESSION_SECRET не задан на сервере")
    if not token or "." not in token:
        raise SessionTokenError("некорректный формат токена")
    payload_b64, _, signature = token.partition(".")
    expected_signature = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_signature, signature):
        raise SessionTokenError("подпись токена не совпадает")
    try:
        payload = json.loads(_b64decode(payload_b64))
    except (ValueError, json.JSONDecodeError) as exc:
        raise SessionTokenError("не удалось разобрать тело токена") from exc

    current_time = now if now is not None else time.time()
    if current_time > payload.get("exp", 0):
        raise SessionTokenError("токен истёк")
    user_id = payload.get("uid")
    if not isinstance(user_id, int):
        raise SessionTokenError("в токене нет uid")
    return user_id
