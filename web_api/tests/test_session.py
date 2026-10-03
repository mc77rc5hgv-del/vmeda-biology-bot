import pytest

from web_api.session import (
    SESSION_TTL_SECONDS,
    SessionTokenError,
    create_session_token,
    verify_session_token,
)

SECRET = "test-session-secret-do-not-use-in-prod"


def test_round_trip():
    token = create_session_token(555111222, SECRET)
    assert verify_session_token(token, SECRET) == 555111222


def test_expired_token_is_rejected():
    now = 1_700_000_000.0
    token = create_session_token(555111222, SECRET, now=now)
    with pytest.raises(SessionTokenError, match="истёк"):
        verify_session_token(token, SECRET, now=now + SESSION_TTL_SECONDS + 1)


def test_token_valid_just_before_expiry():
    now = 1_700_000_000.0
    token = create_session_token(555111222, SECRET, now=now)
    # На самой границе допустимо -- expiry строго "позже", а не "не раньше".
    verify_session_token(token, SECRET, now=now + SESSION_TTL_SECONDS - 1)


def test_tampered_payload_is_rejected():
    token = create_session_token(555111222, SECRET)
    payload_b64, _, signature = token.partition(".")
    forged_token = f"{payload_b64}AAAA.{signature}"
    with pytest.raises(SessionTokenError, match="подпись"):
        verify_session_token(forged_token, SECRET)


def test_wrong_secret_is_rejected():
    token = create_session_token(555111222, SECRET)
    with pytest.raises(SessionTokenError, match="подпись"):
        verify_session_token(token, "a-completely-different-secret")


def test_malformed_token_is_rejected():
    with pytest.raises(SessionTokenError, match="формат"):
        verify_session_token("not-a-valid-token-at-all", SECRET)


def test_empty_token_is_rejected():
    with pytest.raises(SessionTokenError):
        verify_session_token("", SECRET)


def test_missing_secret_is_rejected_on_create():
    with pytest.raises(SessionTokenError, match="SESSION_SECRET"):
        create_session_token(1, "")


def test_missing_secret_is_rejected_on_verify():
    token = create_session_token(555111222, SECRET)
    with pytest.raises(SessionTokenError, match="SESSION_SECRET"):
        verify_session_token(token, "")


def test_different_users_get_different_tokens():
    token_a = create_session_token(1, SECRET)
    token_b = create_session_token(2, SECRET)
    assert token_a != token_b
    assert verify_session_token(token_a, SECRET) == 1
    assert verify_session_token(token_b, SECRET) == 2


def test_token_with_extra_separator_is_rejected():
    token = create_session_token(1, SECRET)
    with pytest.raises(SessionTokenError, match="формат"):
        verify_session_token(token + ".extra", SECRET)


@pytest.mark.parametrize("bad_user_id", [0, -1, True])
def test_invalid_user_id_is_rejected_on_create(bad_user_id):
    with pytest.raises(SessionTokenError, match="user_id"):
        create_session_token(bad_user_id, SECRET)
