import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.anatomy_sync import scores
from services.content_access import enter, can_visit
from web_api import learning, attempt_tokens, bot_state
from web_api.data_safety import backup_stats, backup_sqlite
from fastapi.testclient import TestClient
from web_api.deps import get_current_user_id, get_fresh_bot_module
from web_api.main import app
import telegram_bot as tb


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv('BOT_SYNC_MODE', 'legacy')
    monkeypatch.setenv('MINIAPP_LEARNING_DB', str(tmp_path / 'learning.sqlite3'))
    monkeypatch.setattr(tb, 'stats', copy.deepcopy(tb.stats))
    monkeypatch.setattr(tb, 'save_stats', lambda: None)


def test_concurrent_answers_and_retry_count_once():
    run = learning.create_anatomy_run(123, 'miniapp', 'part', True, [1, 2])
    with ThreadPoolExecutor(max_workers=8) as workers:
        results = list(workers.map(lambda _: learning.answer_anatomy_run(123, run['id'], 0, 1, 'а', True), range(16)))
    assert sum(not result['duplicate'] for result in results) == 1
    assert learning.get_anatomy_run(123, run['id'])['answered'] == 1
    assert learning.get_anatomy_scores(123, 'part') == {}  # incomplete runs never enter rating
    with pytest.raises(HTTPException) as error:
        learning.answer_anatomy_run(123, run['id'], 0, 1, 'б', False)
    assert error.value.status_code == 409
    learning.answer_anatomy_run(123, run['id'], 1, 2, 'б', False)
    learning.answer_anatomy_run(123, run['id'], 1, 2, 'б', False)
    assert learning.get_anatomy_scores(123, 'part')['123'] == {'correct': 1, 'total': 2, 'attempts': 1}
    assert learning.get_anatomy_mistakes(123) == [2]
    with pytest.raises(HTTPException):
        learning.get_anatomy_run(456, run['id'])


def test_common_bot_and_miniapp_rating_preserves_baseline():
    tb.stats['usernames']['123'] = 'preserved_username'
    tb.stats['anatomy_exam_test_scores']['123'] = {'correct': 5, 'total': 10, 'attempts': 1}
    baseline = copy.deepcopy(tb.stats)
    for source in ('bot', 'miniapp'):
        run = learning.create_anatomy_run(123, source, 'part', True, [1])
        learning.answer_anatomy_run(123, run['id'], 0, 1, 'а', True)
    assert scores(tb, 'part', 123)['123'] == {'correct': 7, 'total': 12, 'attempts': 3}
    assert tb.stats == baseline
    assert learning.get_dashboard(123)['xp'] == 40


def test_histology_signed_attempt_is_bound_and_survives_registry_loss():
    token = attempt_tokens.issue(123, 'd1_01', 'all')
    attempt_tokens.verify(token, 123, 'd1_01', 'all')
    for uid, material, scope in [(456, 'd1_01', 'all'), (123, 'd1_02', 'all'), (123, 'd1_01', 'mistakes')]:
        with pytest.raises(HTTPException):
            attempt_tokens.verify(token, uid, material, scope)
    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(lambda _: learning.record_histology_attempt(123, 'd1_01', True, 'all', token), range(8)))
    assert learning.get_histology_stats(123, 71)['attempts'] == 1
    with pytest.raises(HTTPException):
        learning.record_histology_attempt(123, 'd1_01', False, 'all', token)


def test_grace_and_trial_use_one_state_without_regrant(monkeypatch):
    uid = 800123
    key = str(uid)
    monkeypatch.setattr(tb, 'has_subject_access', lambda *args: False)
    tb.stats['referral_warnings'].pop(key, None)
    assert can_visit(tb, uid, 'biology')
    assert enter(tb, uid, 'biology')['warning']
    assert not enter(tb, uid, 'chemistry')['warning']  # same shared cooldown
    tb.stats['referral_warnings'][key]['count'] = tb.REFERRAL_WARNING_THRESHOLD
    assert not can_visit(tb, uid, 'physics')
    assert not enter(tb, uid, 'biology')['allowed']
    tb.stats['histology_temp_access'].pop(key, None)
    tb.stats['histology_warnings'].pop(key, None)
    assert enter(tb, uid, 'histology')['trial_started']
    expiry = tb.stats['histology_temp_access'][key]
    assert not enter(tb, uid, 'histology')['trial_started']
    assert tb.stats['histology_temp_access'][key] == expiry
    tb.stats['histology_temp_access'][key] = 1
    tb.stats['histology_warnings'].pop(key, None)
    assert not enter(tb, uid, 'histology')['allowed']
    assert tb.stats['histology_temp_access'][key] == 1


def test_owner_refresh_never_replaces_live_unflushed_stats(monkeypatch):
    monkeypatch.setenv('BOT_SYNC_MODE', 'owner')
    monkeypatch.setattr(tb, '_sync_owner_running', True, raising=False)
    state = tb.stats
    state['subscriptions']['123'] = {'tier': 21, 'expires': 9999999999}
    bot_state.refresh_stats()
    assert bot_state.get_bot_module() is tb
    assert tb.stats is state


def test_verified_backups_preserve_bytes_rows_and_unknown_fields(tmp_path):
    path = tmp_path / 'stats.json'
    data = {'total_users': [123], 'usernames': {'123': 'username'}, 'future_field': {'keep': [1, 2]}}
    raw = json.dumps(data).encode()
    path.write_bytes(raw)
    snapshot = Path(backup_stats(str(path)))
    assert snapshot.read_bytes() == path.read_bytes() == raw
    learning.record_histology_attempt(123, 'd1_01', False)
    db_path = learning._db_path()
    snapshot_db = backup_sqlite(db_path)
    with sqlite3.connect(snapshot_db) as saved:
        assert saved.execute('SELECT user_id, specimen_id FROM histology_practical_attempts').fetchall() == [(123, 'd1_01')]
    assert learning.get_histology_stats(123, 71)['attempts'] == 1


def test_missing_gateway_db_is_not_created(monkeypatch, tmp_path):
    path = tmp_path / 'absent.sqlite3'
    monkeypatch.setenv('BOT_SYNC_MODE', 'gateway')
    monkeypatch.setenv('MINIAPP_LEARNING_DB', str(path))
    with pytest.raises(RuntimeError):
        learning.get_state(123)
    assert not path.exists()


def test_corrupt_bot_stats_cannot_be_replaced_with_empty_users(monkeypatch, tmp_path):
    path = tmp_path / 'stats.json'
    path.write_bytes(b'{corrupt but must remain untouched')
    monkeypatch.setattr(tb, 'STATS_FILE', str(path))
    with pytest.raises(RuntimeError):
        tb.load_stats()
    assert path.read_bytes() == b'{corrupt but must remain untouched'


def test_physiology_flags_are_shared_and_card_history_is_preserved(monkeypatch):
    monkeypatch.setenv('BOT_SYNC_MODE', 'owner')
    monkeypatch.setattr(tb, '_sync_owner_running', True, raising=False)
    uid = 85123
    topic = tb.PHYSIOLOGY['topics'][0]['topic_id']
    original = {'total_cards': 3, 'completed_cards': 1, 'correct_answers': 2, 'total_answers': 3,
                'mechanism_correct': 0, 'mechanism_total': 0, 'last_studied_at': 1}
    tb.stats['physiology_progress'][str(uid)] = {topic: copy.deepcopy(original)}
    app.dependency_overrides[get_current_user_id] = lambda: uid
    app.dependency_overrides[get_fresh_bot_module] = lambda: tb
    client = TestClient(app)
    try:
        path = f'/api/v1/learning/materials/physiology/course/{topic}'
        assert client.post(path+'/favorite', json={'value': True}).status_code == 200
        assert tb.phys_is_favorite(uid, topic)
        response = client.post(path+'/completed', json={'value': True})
        assert response.status_code == 200
        assert f'physiology/course/{topic}' in response.json()['completed_keys']
        assert tb.get_phys_progress(uid, topic)['completed_cards'] == 3
        assert tb.stats['physiology_progress'][str(uid)][topic] == original
        tb.phys_toggle_favorite(uid, topic)
        assert client.get('/api/v1/learning/state').json()['favorites'] == []
        assert client.post(path+'/completed', json={'value': False}).status_code == 200
        assert tb.get_phys_progress(uid, topic)['completed_cards'] == 0
        assert tb.stats['physiology_progress'][str(uid)][topic] == original
    finally:
        app.dependency_overrides.clear()


def test_run_retry_rejects_changed_queue_and_metadata():
    run = learning.create_anatomy_run(123, 'bot', 'part', True, [1, 2], 'same-key')
    assert learning.create_anatomy_run(123, 'bot', 'part', True, [1, 2], 'same-key')['id'] == run['id']
    with pytest.raises(HTTPException) as error:
        learning.create_anatomy_run(123, 'bot', 'part', True, [1, 3], 'same-key')
    assert error.value.status_code == 409
    assert learning.get_anatomy_run(123, 'same-key')['queue'] == [1, 2]
