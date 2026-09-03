"""Проверка Telegram initData на сервере — см. ТЗ раздел 5 "Авторизация Telegram".

Официальный алгоритм (https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app):
secret_key = HMAC-SHA256(key="WebAppData", data=BOT_TOKEN)
data_check_string = все поля initData, КРОМЕ hash, отсортированные по имени ключа, склеенные "\n"
                     в формате "key=value"
ожидаемый hash = hex(HMAC-SHA256(key=secret_key, data=data_check_string))

Это ЕДИНСТВЕННОЕ место в web_api, где решается, кто прислал запрос — все остальные модули
получают уже провалидированный `user_id`, а не сырую initData-строку. Никогда не читай
`user`/`auth_date`/что угодно из initData где-либо ещё в этом пакете без прохождения через
verify_telegram_init_data() ниже — непроверенная строка от клиента не должна влиять ни на какое
решение о правах, тарифе или личности пользователя (см. ТЗ: "нельзя доверять initDataUnsafe").
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

MAX_INIT_DATA_AGE_SECONDS = 24 * 60 * 60  # initData Telegram сам переиздаёт при каждом открытии
                                            # Mini App — сутки с запасом достаточно, но не бесконечно


class InitDataError(Exception):
    """Подпись не сошлась, initData протухла, или структура не такая, как ожидалось."""


def _build_data_check_string(pairs: list[tuple[str, str]]) -> str:
    sorted_pairs = sorted(pairs, key=lambda kv: kv[0])
    return "\n".join(f"{key}={value}" for key, value in sorted_pairs)


def verify_telegram_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = MAX_INIT_DATA_AGE_SECONDS,
    now: float | None = None,
) -> dict:
    """Возвращает распарсенные поля initData (включая распарсенный `user` как dict), только
    если подпись подлинная и `auth_date` не протухла. Бросает InitDataError во всех остальных
    случаях — вызывающий код (web_api/routers/auth.py) обязан превращать это в HTTP 401, а не
    молча возвращать "гостевой" доступ."""
    if not bot_token:
        raise InitDataError("BOT_TOKEN не задан на сервере — проверка невозможна")
    if not init_data:
        raise InitDataError("пустая initData")

    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=False)
    fields = dict(pairs)

    received_hash = fields.pop("hash", None)
    if not received_hash:
        raise InitDataError("в initData нет поля hash")

    data_check_string = _build_data_check_string([(k, v) for k, v in pairs if k != "hash"])
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    # constant-time сравнение -- не даём различию времени выполнения течь информацию о том,
    # сколько первых символов совпало (timing attack на подпись).
    if not hmac.compare_digest(expected_hash, received_hash):
        raise InitDataError("подпись initData не совпадает — данные подделаны или BOT_TOKEN неверный")

    auth_date_raw = fields.get("auth_date")
    if not auth_date_raw or not auth_date_raw.isdigit():
        raise InitDataError("в initData нет валидного auth_date")
    auth_date = int(auth_date_raw)
    current_time = now if now is not None else time.time()
    age = current_time - auth_date
    if age < 0:
        raise InitDataError("auth_date в будущем — подозрительно, отклоняем")
    if age > max_age_seconds:
        raise InitDataError(f"initData протухла ({age:.0f}с > {max_age_seconds}с)")

    user_raw = fields.get("user")
    if not user_raw:
        raise InitDataError("в initData нет поля user")
    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError as exc:
        raise InitDataError("поле user в initData — не валидный JSON") from exc
    if "id" not in user:
        raise InitDataError("в user нет id")

    fields["user"] = user
    fields["auth_date"] = auth_date
    return fields
