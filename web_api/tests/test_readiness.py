from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from web_api.main import app
from web_api.routers import readiness


def test_health_is_503_when_dependency_fails_but_process_is_alive(monkeypatch):
    monkeypatch.setattr(readiness, 'checks', AsyncMock(return_value={'owner': False, 'learning': True}))
    client = TestClient(app)
    assert client.get('/healthz').status_code == 503
    assert client.get('/readyz').status_code == 503
    assert client.get('/livez').status_code == 200


def test_gateway_requires_both_existing_learning_and_owner(monkeypatch):
    monkeypatch.setenv('BOT_SYNC_MODE', 'gateway')
    monkeypatch.setattr(readiness, 'remote_ready', AsyncMock(return_value=False))
    monkeypatch.setattr(readiness, 'storage_ready', lambda: True)
    result = TestClient(app).get('/readyz')
    assert result.status_code == 503
    assert result.json()['checks'] == {'learning': True, 'owner': False}


def test_readiness_never_creates_missing_database(monkeypatch, tmp_path):
    path = tmp_path / 'absent.sqlite3'
    monkeypatch.setenv('MINIAPP_LEARNING_DB', str(path))
    assert readiness.storage_ready() is False
    assert not path.exists()


def test_owner_requires_running_billing_when_sbp_enabled(monkeypatch):
    import telegram_bot as tb
    monkeypatch.setenv('BOT_SYNC_MODE', 'owner')
    monkeypatch.setenv('CODEEPAY_ENABLED', 'true')
    monkeypatch.setattr(tb, '_sync_owner_running', True, raising=False)
    monkeypatch.setattr(tb, '_billing_runtime', None, raising=False)
    monkeypatch.setattr(readiness, 'remote_ready', AsyncMock(return_value=True))
    result = TestClient(app).get('/readyz')
    assert result.status_code == 503 and result.json()['checks']['billing'] is False


def test_owner_admission_does_not_require_gateway_routing_during_rollout(monkeypatch):
    import telegram_bot as tb
    monkeypatch.setenv('BOT_SYNC_MODE', 'owner')
    monkeypatch.setenv('BOT_SYNC_TOKEN', 'synthetic-readiness-token')
    monkeypatch.setenv('CODEEPAY_ENABLED', 'false')
    monkeypatch.setattr(tb, '_sync_owner_running', True, raising=False)
    remote = AsyncMock(return_value=False)
    monkeypatch.setattr(readiness, 'remote_ready', remote)
    client = TestClient(app)
    result = client.get('/internal/sync/owner-ready', headers={'X-Vmeda-Sync-Token': 'synthetic-readiness-token'})
    assert result.status_code == 200
    remote.assert_not_awaited()
    assert client.get('/readyz').status_code == 503
