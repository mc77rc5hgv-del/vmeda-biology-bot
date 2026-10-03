"""Тесты web_api/auth.py -- проверка подписи Telegram initData. Это единственное место, которое
решает, кто прислал запрос (см. docstring auth.py), поэтому здесь тестируется не только
"счастливый путь", но и все способы подделать/испортить initData, которые должны быть отклонены."""
import hashlib
import hmac
import json
import time

import pytest

from web_api.auth import InitDataError, verify_telegram_init_data

BOT_TOKEN = "123456789:AAFakeTokenForTestsOnlyNotReal0000000"


def build_init_data(bot_token: str, fields: dict, *, sign: bool = True, real_hash: str | None = None) -> str:
    """Собирает initData-строку тем же алгоритмом, что описан в auth.py, чтобы тесты не зависели
    от реального Telegram-клиента -- секрет известен только тесту и коду, который проверяем."""
    from urllib.parse import urlencode

    pairs = [(k, v) for k, v in fields.items()]
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs, key=lambda kv: kv[0]))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    all_fields = dict(fields)
    if sign:
        all_fields["hash"] = real_hash if real_hash is not None else computed_hash
    return urlencode(all_fields)


def default_fields(auth_date: int | None = None) -> dict:
    return {
        "user": json.dumps({"id": 555111222, "first_name": "Тест", "username": "test_user"}),
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAH_fake_query_id",
    }


def test_valid_init_data_round_trips():
    init_data = build_init_data(BOT_TOKEN, default_fields())
    result = verify_telegram_init_data(init_data, BOT_TOKEN)
    assert result["user"]["id"] == 555111222
    assert result["user"]["username"] == "test_user"
    assert isinstance(result["auth_date"], int)


def test_tampered_field_is_rejected():
    fields = default_fields()
    init_data = build_init_data(BOT_TOKEN, fields)
    # Подменяем user ПОСЛЕ подписи -- имитация подделки на клиенте.
    tampered = init_data.replace("555111222", "999999999")
    with pytest.raises(InitDataError, match="подпись"):
        verify_telegram_init_data(tampered, BOT_TOKEN)


def test_wrong_bot_token_is_rejected():
    init_data = build_init_data(BOT_TOKEN, default_fields())
    with pytest.raises(InitDataError, match="подпись"):
        verify_telegram_init_data(init_data, "999999999:WrongTokenEntirely00000000000000000")


def test_missing_hash_is_rejected():
    init_data = build_init_data(BOT_TOKEN, default_fields(), sign=False)
    with pytest.raises(InitDataError, match="hash"):
        verify_telegram_init_data(init_data, BOT_TOKEN)


def test_forged_hash_is_rejected():
    init_data = build_init_data(BOT_TOKEN, default_fields(), real_hash="deadbeef" * 8)
    with pytest.raises(InitDataError, match="подпись"):
        verify_telegram_init_data(init_data, BOT_TOKEN)


def test_expired_auth_date_is_rejected():
    old_auth_date = int(time.time()) - 999_999
    init_data = build_init_data(BOT_TOKEN, default_fields(auth_date=old_auth_date))
    with pytest.raises(InitDataError, match="протухла"):
        verify_telegram_init_data(init_data, BOT_TOKEN)


def test_future_auth_date_is_rejected():
    future_auth_date = int(time.time()) + 999_999
    init_data = build_init_data(BOT_TOKEN, default_fields(auth_date=future_auth_date))
    with pytest.raises(InitDataError, match="будущем"):
        verify_telegram_init_data(init_data, BOT_TOKEN)


def test_small_future_clock_skew_is_allowed():
    init_data = build_init_data(BOT_TOKEN, default_fields(auth_date=int(time.time()) + 15))
    verify_telegram_init_data(init_data, BOT_TOKEN)


def test_duplicate_fields_are_rejected():
    init_data = build_init_data(BOT_TOKEN, default_fields()) + "&auth_date=1"
    with pytest.raises(InitDataError, match="повторяющиеся"):
        verify_telegram_init_data(init_data, BOT_TOKEN)


@pytest.mark.parametrize("bad_id", [None, 0, -1, True, "123"])
def test_invalid_user_id_is_rejected(bad_id):
    fields = default_fields()
    fields["user"] = json.dumps({"id": bad_id, "first_name": "X"})
    init_data = build_init_data(BOT_TOKEN, fields)
    with pytest.raises(InitDataError, match="положительного id"):
        verify_telegram_init_data(init_data, BOT_TOKEN)


def test_oversized_init_data_is_rejected():
    with pytest.raises(InitDataError, match="размер"):
        verify_telegram_init_data("x" * 20_000, BOT_TOKEN)


def test_custom_max_age_is_respected():
    auth_date = int(time.time()) - 3700  # чуть больше часа назад
    init_data = build_init_data(BOT_TOKEN, default_fields(auth_date=auth_date))
    # по умолчанию (сутки) -- проходит
    verify_telegram_init_data(init_data, BOT_TOKEN)
    # с явным лимитом в час -- уже нет
    with pytest.raises(InitDataError, match="протухла"):
        verify_telegram_init_data(init_data, BOT_TOKEN, max_age_seconds=3600)


def test_missing_user_field_is_rejected():
    fields = default_fields()
    del fields["user"]
    init_data = build_init_data(BOT_TOKEN, fields)
    with pytest.raises(InitDataError, match="user"):
        verify_telegram_init_data(init_data, BOT_TOKEN)


def test_malformed_user_json_is_rejected():
    fields = default_fields()
    fields["user"] = "{not valid json"
    init_data = build_init_data(BOT_TOKEN, fields)
    with pytest.raises(InitDataError, match="JSON"):
        verify_telegram_init_data(init_data, BOT_TOKEN)


def test_empty_init_data_is_rejected():
    with pytest.raises(InitDataError, match="пустая"):
        verify_telegram_init_data("", BOT_TOKEN)


def test_missing_bot_token_is_rejected():
    init_data = build_init_data(BOT_TOKEN, default_fields())
    with pytest.raises(InitDataError, match="BOT_TOKEN"):
        verify_telegram_init_data(init_data, "")


def test_extra_unknown_fields_do_not_break_verification():
    """Telegram может добавлять новые поля в initData со временем -- алгоритм должен просто
    включать их в data_check_string, а не требовать точного списка известных ключей."""
    fields = default_fields()
    fields["start_param"] = "ref_123456"
    fields["chat_instance"] = "-6820612086415451059"
    init_data = build_init_data(BOT_TOKEN, fields)
    result = verify_telegram_init_data(init_data, BOT_TOKEN)
    assert result["start_param"] == "ref_123456"
