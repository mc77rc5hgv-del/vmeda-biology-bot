"""Public launcher is permanent; promo revocation never edits paid entitlements."""
from concurrent.futures import Future
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio
import time

import pytest
from fastapi.testclient import TestClient

import telegram_bot as tb
from services.miniapp_policy import PAID_SUBJECTS, set_promo, subscription_access
from web_api import bot_state, config
from web_api.main import app
from web_api.session import create_session_token
from web_api.routers.subscriptions import _plan_subjects

USER = 87654001
ADMIN = next(iter(tb.ADMIN_IDS))


@pytest.fixture
def public_state(monkeypatch):
    state = deepcopy(tb.stats)
    state['total_users'].add(USER)
    state['user_username'][str(USER)] = 'public_user'
    state['subscriptions'].pop(str(USER), None)
    state['miniapp_tester_access'] = {}
    state.pop('miniapp_public_promo', None)
    state['unknown_future_key'] = {'must': 'survive'}
    monkeypatch.setattr(tb, 'stats', state)
    def save():
        result = Future()
        result.set_result(None)
        return result
    monkeypatch.setattr(tb, 'save_stats', save)
    monkeypatch.setattr(bot_state, 'refresh_stats', lambda: None)
    monkeypatch.setattr(bot_state, 'get_bot_module', lambda: tb)
    monkeypatch.setattr(config, 'MINIAPP_ACCESS_MODE', 'public')
    monkeypatch.setenv('MINIAPP_ACCESS_MODE', 'public')
    return state


def client():
    return TestClient(app), {'Authorization': f'Bearer {create_session_token(USER, config.SESSION_SECRET)}'}


def test_promo_all_subjects_off_revokes_on_existing_token_preserves_everything(public_state):
    before = deepcopy(public_state)
    c, h = client()
    assert c.get('/api/v1/me', headers=h).status_code == 200
    for subject in PAID_SUBJECTS:
        access = c.get(f'/api/v1/access/{subject}', headers=h).json()
        assert access['subscription_required'] is (subject != 'histology')
        assert access['trial_available'] is (subject == 'histology')
    set_promo(tb, ADMIN, True).result()
    set_promo(tb, ADMIN, True).result()  # idempotent button retry
    sync = c.get('/api/v1/sync/state', headers=h).json()
    assert all(v['can_open_subject'] for v in sync['subjects'].values())
    assert all(sync['anatomy_modules'].values()) and sync['chemistry_tickets']
    assert sync['promo_access'] and not sync['tester_access']
    assert not tb.has_active_subscription(USER)
    first = next(s for g in tb.HISTOLOGY.values() for s in g['specimens'])
    url = f"/api/v1/materials/histology/specimens/{first['id']}"
    assert c.get(url, headers=h).status_code == 200
    assert c.get(url + '/media/0', headers=h).status_code == 200
    assert c.get('/api/v1/histology/exam/catalog', headers=h).status_code == 200
    assert c.get('/api/v1/anatomy/exam/parts', headers=h).status_code == 200
    for subject in PAID_SUBJECTS:
        enter = c.post(f'/api/v1/access/{subject}/enter', headers=h).json()
        assert enter['allowed'] and not enter['warning'] and not enter['trial_started']
    set_promo(tb, ADMIN, False).result()
    for path in (url, url + '/media/0', '/api/v1/histology/exam/catalog', '/api/v1/anatomy/exam/parts'):
        response = c.get(path, headers=h)
        assert response.status_code == 403, (path, response.text)
        assert response.headers['X-VMEDA-Subscription-Required'] == ('anatomy_tests' if '/anatomy/' in path else 'histology')
    assert c.get('/api/v1/me', headers=h).status_code == 200
    assert len(public_state['miniapp_public_promo']['history']) == 2
    assert {k: v for k, v in public_state.items() if k != 'miniapp_public_promo'} == before


def test_paid_subject_scope_and_expiry_survive_promo(public_state):
    sub = {'tier': 20, 'expires': 4_000_000_000, 'restricted_subject': 'biology',
           'histology_access': False, 'anatomy': False, 'payment_id': 'synthetic-paid'}
    public_state['subscriptions'][str(USER)] = sub
    before = deepcopy(public_state)
    c, h = client()
    for active in (True, False):
        set_promo(tb, ADMIN, active).result()
        for subject in PAID_SUBJECTS:
            status = c.get(f'/api/v1/access/{subject}', headers=h).json()
            assert status['can_open_subject'] is (active or subject == 'biology')
    assert {k: v for k, v in public_state.items() if k != 'miniapp_public_promo'} == before
    sub['restricted_subject'] = None
    sub['histology_access'] = True
    sub['histology_until'] = 4_000_000_000
    sub['anatomy'] = True
    assert all(subscription_access(tb, USER, subject) for subject in PAID_SUBJECTS)
    sub['expires'] = 1
    assert all(not subscription_access(tb, USER, subject) for subject in PAID_SUBJECTS)


def test_non_admin_and_invalid_state_cannot_change_promo(public_state):
    before = deepcopy(public_state)
    with pytest.raises(PermissionError):
        set_promo(tb, USER, True)
    with pytest.raises(ValueError):
        set_promo(tb, ADMIN, 'true')
    assert public_state == before


def test_subscription_header_exposed_to_cross_origin_client(public_state):
    c, h = client()
    response = c.get('/api/v1/histology/exam/catalog', headers={**h, 'Origin': config.ALLOWED_ORIGINS[0]})
    assert response.status_code == 403
    assert 'x-vmeda-subscription-required' in response.headers.get('access-control-expose-headers', '').lower()


def test_contextual_plan_coverage():
    assert _plan_subjects({'histology_until_rule': 'expiry', 'anatomy': True}) == ['biology', 'physics', 'chemistry', 'histology', 'anatomy']
    assert _plan_subjects({'histology_until_rule': 1, 'anatomy': False}) == ['biology', 'physics', 'chemistry']


def test_exam_trial_shared_by_bot_and_public_api_without_extending(public_state, monkeypatch):
    from handlers.anatomy import anatomy_exam_access_middleware
    from services.content_access import can_visit

    c, h = client()
    key = str(USER)
    anatomy = '/api/v1/access/anatomy_tests'
    histology = '/api/v1/access/histology'
    anatomy_bank = '/api/v1/anatomy/exam/parts'
    histology_bank = '/api/v1/histology/exam/catalog'
    guard_paths = (anatomy_bank, histology_bank, '/api/v1/anatomy/exam/runs/active', '/api/v1/anatomy/exam/mistakes')
    old_button = SimpleNamespace(
        data='anatomy_exam_feedback_next', from_user=SimpleNamespace(id=USER), answer=AsyncMock(), message=object(),
    )
    handler = AsyncMock()
    monkeypatch.setattr(tb, 'safe_edit_text', AsyncMock())

    assert all(c.get(path, headers=h).json()['trial_available'] for path in (anatomy, histology))
    assert all(c.get(path, headers=h).status_code == 403 for path in guard_paths)
    assert key not in public_state['exam_trial_access']

    start = c.post(histology + '/enter', headers=h).json()
    assert start['trial_started'] and start['access']['trial_duration_hours'] == 24
    deadline = public_state['exam_trial_access'][key]
    assert 86390 < deadline - time.time() <= 86400
    assert c.get(anatomy, headers=h).json()['trial_expires_at'] == start['access']['trial_expires_at']
    assert c.get(anatomy_bank, headers=h).status_code == 200
    assert c.get(histology_bank, headers=h).status_code == 200
    asyncio.run(anatomy_exam_access_middleware(handler, old_button, {}))
    handler.assert_awaited_once()
    assert not c.post(anatomy + '/enter', headers=h).json()['trial_started']
    assert public_state['exam_trial_access'][key] == deadline
    assert c.get('/api/v1/subjects/anatomy/sections/course', headers=h).status_code == 403

    public_state['exam_trial_access'][key] = time.time() - 1
    assert all(c.get(path, headers=h).status_code == 403 for path in guard_paths)
    denied = c.post('/api/v1/anatomy/exam/runs/example/answer', json={'position': 0, 'selected_index': 0}, headers=h)
    assert denied.status_code == 403
    trial = c.post(histology + '/enter', headers=h).json()
    assert not trial['allowed'] and not trial['access']['trial_available']
    asyncio.run(anatomy_exam_access_middleware(handler, old_button, {}))
    handler.assert_awaited_once()
    assert 'Пробный доступ закончился' in tb.safe_edit_text.await_args.args[1]

    public_state['referral_monthly'][key] = {'month': tb._current_referral_month_key(), 'count': 1}
    assert not can_visit(tb, USER, 'anatomy_tests')
    public_state['referral_monthly'][key]['count'] = 2
    assert c.get(anatomy_bank, headers=h).status_code == 200
    assert c.get(histology_bank, headers=h).status_code == 200
    assert public_state['exam_trial_access'][key] < time.time()
    assert key not in public_state['subscriptions']


def test_legacy_trial_and_paid_access_are_preserved(public_state):
    key = str(USER)
    deadline = time.time() + 100
    public_state['histology_temp_access'][key] = deadline
    c, h = client()
    histology = '/api/v1/access/histology'
    anatomy = '/api/v1/access/anatomy_tests'
    assert c.get(histology, headers=h).json()['trial_expires_at'] == c.get(anatomy, headers=h).json()['trial_expires_at']
    assert not c.post(anatomy + '/enter', headers=h).json()['trial_started']
    assert public_state['histology_temp_access'][key] == deadline and key not in public_state['exam_trial_access']

    public_state['histology_temp_access'][key] = 1
    public_state['subscriptions'][key] = {
        'tier': 24, 'expires': 4_000_000_000, 'histology_access': True,
        'histology_until': 4_000_000_000, 'anatomy': True,
    }
    before = deepcopy(public_state)
    for scope in (histology, anatomy):
        decision = c.post(scope + '/enter', headers=h).json()
        assert decision['allowed'] and decision['access']['trial_expires_at'] is None
        assert not decision['trial_started']
    assert public_state == before


def test_start_greets_and_keeps_channel_check_without_spending_trial(public_state, monkeypatch):
    message = SimpleNamespace(from_user=SimpleNamespace(id=USER), text='/start', answer=AsyncMock())
    monkeypatch.setattr(tb, 'is_subscribed', AsyncMock(side_effect=[False, True]))
    asyncio.run(tb.cmd_start(message))
    welcome = message.answer.await_args.args[0]
    assert 'VMedA AI' in welcome and '24 часов' in welcome and 'гистологию' in welcome
    button = message.answer.await_args.kwargs['reply_markup'].inline_keyboard[0][0]
    assert button.url == 'https://t.me/Vmeda_examen'
    asyncio.run(tb.cmd_start(message))
    assert 'Выбери предмет для подготовки' in message.answer.await_args.args[0]
    assert str(USER) not in public_state['exam_trial_access']


@pytest.mark.parametrize('subject', sorted(PAID_SUBJECTS))
def test_direct_sections_media_and_learning_writes_require_paid_scope(public_state, subject):
    c, h = client()
    for path in (f'/api/v1/subjects/{subject}/sections/course',
                 f'/api/v1/materials/{subject}/course/1',
                 f'/api/v1/materials/{subject}/course/1/media/0'):
        response = c.get(path, headers=h)
        assert response.status_code == 403
        assert response.headers['x-vmeda-subscription-required'] == subject
    for flag in ('completed', 'favorite'):
        response = c.post(f'/api/v1/learning/materials/{subject}/course/1/{flag}', headers=h, json={'value': True})
        assert response.status_code == 403
        assert response.headers['x-vmeda-subscription-required'] == subject
    response = c.post('/api/v1/learning/materials/touch', headers=h,
                      json={'subject_id': subject, 'section_id': 'course', 'material_id': '1', 'subject_title': 'Synthetic', 'section_title': 'Synthetic'})
    assert response.status_code == 403, response.text
    assert response.headers['x-vmeda-subscription-required'] == subject
