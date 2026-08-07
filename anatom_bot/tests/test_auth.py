"""Unit tests for auth.py — pure hash/token logic, no live bot token or network needed."""

import hashlib
import hmac
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import tb  # noqa: F401,E402

from auth import (  # noqa: E402
    create_session_token,
    decode_session_token,
    generate_login_code,
    verify_telegram_auth,
)

BOT_TOKEN = "123456:TEST-TOKEN"


def _signed_payload(**overrides):
    payload = {
        "id": 42,
        "first_name": "Иван",
        "auth_date": 1700000000,
    }
    payload.update(overrides)
    data_check_string = "\n".join(f"{k}={payload[k]}" for k in sorted(payload))
    secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
    payload["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return payload


class TelegramAuthTests(unittest.TestCase):
    def test_valid_payload_passes(self):
        payload = _signed_payload()
        self.assertTrue(
            verify_telegram_auth(payload, BOT_TOKEN, max_age_seconds=86400, now=1700000100)
        )

    def test_tampered_field_fails(self):
        payload = _signed_payload()
        payload["id"] = 999
        self.assertFalse(
            verify_telegram_auth(payload, BOT_TOKEN, max_age_seconds=86400, now=1700000100)
        )

    def test_wrong_bot_token_fails(self):
        payload = _signed_payload()
        self.assertFalse(
            verify_telegram_auth(payload, "999999:OTHER-TOKEN", max_age_seconds=86400, now=1700000100)
        )

    def test_stale_auth_date_fails(self):
        payload = _signed_payload()
        far_future = payload["auth_date"] + 90000
        self.assertFalse(
            verify_telegram_auth(payload, BOT_TOKEN, max_age_seconds=86400, now=far_future)
        )

    def test_missing_hash_fails(self):
        payload = _signed_payload()
        del payload["hash"]
        self.assertFalse(
            verify_telegram_auth(payload, BOT_TOKEN, max_age_seconds=86400, now=1700000100)
        )


def _signed_init_data(user: dict, auth_date: int = 1700000000, token: str = BOT_TOKEN) -> str:
    import hashlib
    import hmac as _hmac
    import json
    import urllib.parse

    fields = {"auth_date": str(auth_date), "user": json.dumps(user, separators=(",", ":"))}
    data_check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    # MiniApp scheme: the secret is HMAC("WebAppData", bot_token) — not sha256(bot_token).
    secret = _hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = _hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(fields)


class WebAppInitDataTests(unittest.TestCase):
    """Guards MiniApp login: a forged initData must never yield a session."""

    def test_valid_init_data_returns_the_user(self):
        from auth import verify_webapp_init_data

        raw = _signed_init_data({"id": 42, "first_name": "Иван"})
        user = verify_webapp_init_data(raw, BOT_TOKEN, max_age_seconds=86400, now=1700000100)
        self.assertIsNotNone(user)
        self.assertEqual(user["id"], 42)

    def test_tampered_user_is_rejected(self):
        from auth import verify_webapp_init_data
        import urllib.parse

        raw = _signed_init_data({"id": 42, "first_name": "Иван"})
        fields = dict(urllib.parse.parse_qsl(raw))
        fields["user"] = '{"id":999,"first_name":"Fake"}'
        forged = urllib.parse.urlencode(fields)
        self.assertIsNone(
            verify_webapp_init_data(forged, BOT_TOKEN, max_age_seconds=86400, now=1700000100)
        )

    def test_wrong_bot_token_is_rejected(self):
        from auth import verify_webapp_init_data

        raw = _signed_init_data({"id": 42})
        self.assertIsNone(
            verify_webapp_init_data(raw, "999:OTHER", max_age_seconds=86400, now=1700000100)
        )

    def test_widget_signature_scheme_is_not_accepted(self):
        """The two flows sign differently; accepting the widget's scheme here would be a hole."""
        from auth import verify_webapp_init_data
        import hashlib
        import hmac as _hmac
        import json
        import urllib.parse

        fields = {"auth_date": "1700000000", "user": json.dumps({"id": 42}, separators=(",", ":"))}
        data_check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
        widget_secret = hashlib.sha256(BOT_TOKEN.encode()).digest()
        fields["hash"] = _hmac.new(
            widget_secret, data_check_string.encode(), hashlib.sha256
        ).hexdigest()
        self.assertIsNone(
            verify_webapp_init_data(
                urllib.parse.urlencode(fields), BOT_TOKEN, max_age_seconds=86400, now=1700000100
            )
        )

    def test_stale_init_data_is_rejected(self):
        from auth import verify_webapp_init_data

        raw = _signed_init_data({"id": 42}, auth_date=1700000000)
        self.assertIsNone(
            verify_webapp_init_data(raw, BOT_TOKEN, max_age_seconds=3600, now=1700000000 + 7200)
        )

    def test_garbage_is_rejected(self):
        from auth import verify_webapp_init_data

        for raw in ("", "not-query-string", "hash=abc"):
            self.assertIsNone(
                verify_webapp_init_data(raw, BOT_TOKEN, max_age_seconds=86400, now=1700000100)
            )


class SessionTokenTests(unittest.TestCase):
    def test_round_trip(self):
        token = create_session_token(777, "secret", ttl_seconds=3600)
        self.assertEqual(decode_session_token(token, "secret"), 777)

    def test_wrong_secret_rejected(self):
        token = create_session_token(777, "secret", ttl_seconds=3600)
        self.assertIsNone(decode_session_token(token, "other-secret"))

    def test_expired_token_rejected(self):
        token = create_session_token(777, "secret", ttl_seconds=-10)
        self.assertIsNone(decode_session_token(token, "secret"))

    def test_garbage_token_rejected(self):
        self.assertIsNone(decode_session_token("not-a-jwt", "secret"))


class LoginCodeTests(unittest.TestCase):
    def test_codes_are_unique_and_nonempty(self):
        codes = {generate_login_code() for _ in range(50)}
        self.assertEqual(len(codes), 50)
        self.assertTrue(all(codes))


if __name__ == "__main__":
    unittest.main()
