import pytest
from fastapi import HTTPException

from web_api import bot_state, config
from web_api.deps import ensure_miniapp_access


class FakeBot:
    def __init__(self, admins=()):
        self.admins = set(admins)

    def is_admin(self, user_id):
        return user_id in self.admins


def test_public_mode_does_not_load_bot_state(monkeypatch):
    monkeypatch.setattr(config, "MINIAPP_ACCESS_MODE", "public")
    monkeypatch.setattr(bot_state, "refresh_stats", lambda: pytest.fail("state must not be loaded"))
    ensure_miniapp_access(123)


def test_admin_only_mode_allows_real_admin(monkeypatch):
    monkeypatch.setattr(config, "MINIAPP_ACCESS_MODE", "admin_only")
    monkeypatch.setattr(bot_state, "refresh_stats", lambda: None)
    monkeypatch.setattr(bot_state, "get_bot_module", lambda: FakeBot({123}))
    ensure_miniapp_access(123)


def test_admin_only_mode_rejects_other_users(monkeypatch):
    monkeypatch.setattr(config, "MINIAPP_ACCESS_MODE", "admin_only")
    monkeypatch.setattr(bot_state, "refresh_stats", lambda: None)
    monkeypatch.setattr(bot_state, "get_bot_module", lambda: FakeBot({123}))
    with pytest.raises(HTTPException) as exc_info:
        ensure_miniapp_access(456)
    assert exc_info.value.status_code == 403
    assert "только администратору" in exc_info.value.detail
