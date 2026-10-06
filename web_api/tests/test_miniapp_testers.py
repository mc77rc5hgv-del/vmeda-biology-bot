"""Tester admission, paid material/media gates and revocation on an existing token."""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

import telegram_bot as tb
from services.miniapp_testers import has_test_access, set_test_access
from web_api import bot_state, config
from web_api.main import app
from web_api.session import create_session_token
from web_api.routers import subjects, ai

USER = 87654321
ADMIN = next(iter(tb.ADMIN_IDS))


@pytest.fixture
def tester_state(monkeypatch):
    state = deepcopy(tb.stats)
    state['total_users'].add(USER)
    state['user_username'][str(USER)] = 'tester'
    state['usernames']['tester'] = USER
    state['miniapp_tester_access'] = {}
    state['referral_warnings'][str(USER)] = {'count': 100, 'last_warn_at': 0}
    state['histology_warnings'][str(USER)] = {'count': 100, 'last_warn_at': 0}
    state['histology_temp_access'][str(USER)] = 1
    monkeypatch.setattr(tb, 'stats', state)
    monkeypatch.setattr(tb, 'save_stats', lambda: None)
    monkeypatch.setattr(bot_state, 'refresh_stats', lambda: None)
    monkeypatch.setattr(bot_state, 'get_bot_module', lambda: tb)
    monkeypatch.setattr(config, 'MINIAPP_ACCESS_MODE', 'admin_only')
    return state


def test_grant_revoke_preserves_paid_data_and_rejects_old_token(tester_state):
    state = tester_state
    before = deepcopy(state)
    token = create_session_token(USER, config.SESSION_SECRET)
    headers = {'Authorization': f'Bearer {token}'}
    client = TestClient(app)
    assert client.get('/api/v1/sync/state', headers=headers).status_code == 403
    with pytest.raises(PermissionError):
        set_test_access(tb, USER, USER, active=True)
    set_test_access(tb, ADMIN, USER, active=True)
    assert has_test_access(tb, USER)
    response = client.get('/api/v1/sync/state', headers=headers)
    assert response.status_code == 200
    snapshot = response.json()
    assert snapshot['tester_access'] is True
    assert snapshot['chemistry_tickets'] is True
    assert all(snapshot['anatomy_modules'].values())
    for subject in ('biology', 'chemistry', 'physics', 'histology', 'anatomy'):
        assert snapshot['subjects'][subject]['can_open_subject'] is True
    assert client.get('/api/v1/me', headers=headers).json()['is_admin'] is False
    assert client.get('/api/v1/subscriptions/admin/sbp', headers=headers).status_code == 403
    assert not tb.has_active_subscription(USER)
    assert not tb.has_subject_access(USER, 'physics')
    assert not tb.histology_access_ok(USER)  # grant is miniapp-only
    first = next(s for g in tb.HISTOLOGY.values() for s in g['specimens'])
    url = f"/api/v1/materials/histology/specimens/{first['id']}"
    assert client.get(url, headers=headers).status_code == 200
    assert client.get(url+'/media/0', headers=headers).status_code == 200
    enter = client.post('/api/v1/access/histology/enter', headers=headers)
    assert enter.status_code == 200 and enter.json()['trial_started'] is False
    for check in (subjects._biology_locked_reason, subjects._chemistry_locked_reason,
                  subjects._chemistry_tickets_locked_reason, subjects._physics_locked_reason,
                  subjects._histology_locked_reason):
        assert check(tb, USER) is None
    assert ai._requests_left(tb, USER) is None
    set_test_access(tb, ADMIN, USER, active=False)
    assert not has_test_access(tb, USER)
    assert client.get(url, headers=headers).status_code == 403
    assert client.get(url+'/media/0', headers=headers).status_code == 403
    assert client.get('/api/v1/sync/state', headers=headers).status_code == 403
    assert len(state['miniapp_tester_access'][str(USER)]['history']) == 2
    assert {k:v for k,v in state.items() if k != 'miniapp_tester_access'} == {
        k:v for k,v in before.items() if k != 'miniapp_tester_access'}


def test_public_mode_revoke_restores_material_gate(tester_state, monkeypatch):
    monkeypatch.setattr(config, 'MINIAPP_ACCESS_MODE', 'public')
    token = create_session_token(USER, config.SESSION_SECRET)
    headers = {'Authorization': f'Bearer {token}'}
    client = TestClient(app)
    set_test_access(tb, ADMIN, USER, active=True)
    assert client.get('/api/v1/access/histology', headers=headers).json()['can_open_subject'] is True
    set_test_access(tb, ADMIN, USER, active=False)
    assert client.get('/api/v1/access/histology', headers=headers).json()['can_open_subject'] is False
    assert client.get('/api/v1/histology/exam/catalog', headers=headers).status_code == 403
