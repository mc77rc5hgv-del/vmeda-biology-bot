"""Regression checks use synthetic data only: navigation, durability, billing admission."""
import asyncio
import json
import logging
import sqlite3
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeleteMessage, EditMessageText
from fastapi import HTTPException

from web_api import learning
from web_api.auth import InitDataError, verify_telegram_init_data
from web_api.session import SessionTokenError, verify_session_token
from services.stats_writer import StatsWriter
from services.payments.contracts import ProviderNotReady
from web_api.tests.test_sbp_billing import service as service  # fixture, isolated storage


@pytest.mark.asyncio
async def test_navigation_noop_and_undeletable_fallback():
    import telegram_bot as tb
    message = AsyncMock()
    message.edit_text.side_effect = TelegramBadRequest(EditMessageText(chat_id=1, message_id=1, text='x'), 'message is not modified')
    await tb.safe_edit_text(message, 'x')
    message.delete.assert_not_awaited()
    message.answer.assert_not_awaited()
    message.edit_text.side_effect = TelegramBadRequest(EditMessageText(chat_id=1, message_id=1, text='x'), "message can't be edited")
    message.delete.side_effect = TelegramBadRequest(DeleteMessage(chat_id=1, message_id=1), "message can't be deleted for everyone")
    await tb.safe_edit_text(message, 'x')
    message.answer.assert_awaited_once_with('x')


def test_malformed_unicode_never_reaches_constant_time_string_comparison():
    with pytest.raises(InitDataError):
        verify_telegram_init_data('hash=%C3%A9', 'test')
    for token in ('é.' + 'a' * 64, 'e30.é', 'a' * 3000):
        with pytest.raises(SessionTokenError):
            verify_session_token(token, 'test')


def test_public_launcher_follows_same_mode_without_granting_entitlements(monkeypatch):
    import telegram_bot as tb
    monkeypatch.setenv('MINIAPP_ACCESS_MODE', 'public')
    assert tb.miniapp_launch_allowed(1239876)
    monkeypatch.setenv('MINIAPP_ACCESS_MODE', 'admin_only')
    assert not tb.miniapp_launch_allowed(1239876)


def test_calendar_preserves_both_days_and_counts_whole_section(tmp_path, monkeypatch):
    monkeypatch.setenv('MINIAPP_LEARNING_DB', str(tmp_path / 'test.sqlite3'))
    body = dict(subject_id='biology', section_id='tickets', material_id='one', total_in_section=300)
    for day in ('2026-10-07', '2026-10-08'):
        monkeypatch.setattr(learning, '_now', lambda d=day: d + 'T22:00:00+00:00')
        learning.touch_material(42, body)
    learning.set_material_flag(42, 'biology', 'tickets', 'one', 'completed', True)
    with sqlite3.connect(learning._db_path()) as db:
        days = db.execute('SELECT study_date FROM learning_activity_days ORDER BY study_date').fetchall()
    assert days == [('2026-10-08',), ('2026-10-09',)]  # Moscow, not UTC
    assert learning.get_dashboard(42)['readiness_percent'] < 1
    assert learning.get_dashboard(42)['xp'] == 40


def test_quiz_redelivery_once_and_changed_answer_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv('MINIAPP_LEARNING_DB', str(tmp_path / 'test.sqlite3'))
    for _ in range(2):
        learning.record_quiz_attempt(42, 'biology', 'tickets', 'one', False, 'attempt-123', 0)
    assert learning.get_state(42)['quiz_attempts'] == 1
    with pytest.raises(HTTPException) as error:
        learning.record_quiz_attempt(42, 'biology', 'tickets', 'one', False, 'attempt-123', 1)
    assert error.value.status_code == 409


def test_navigation_persists_across_new_database_connection(tmp_path, monkeypatch):
    monkeypatch.setenv('MINIAPP_LEARNING_DB', str(tmp_path / 'test.sqlite3'))
    entry = learning.set_navigation(42, '/histology/exam')
    assert learning.get_state(42)['last_step'] == entry
    assert learning.get_state(43)['last_step'] is None


@pytest.mark.asyncio
async def test_saves_coalesce_preserve_unknown_keys_and_cancelled_caller(tmp_path):
    data = {'total_users': {42}, 'unknown': {'nested': ['keep']}, 'subscription': {'42': {'tier': 21}}}
    writer = StatsWriter(lambda: data, str(tmp_path / 'stats.json'), logging.getLogger(__name__))
    futures = [writer.save() for _ in range(500)]
    futures[0].cancel()
    data['subscription']['42']['receipt'] = 'synthetic-paid'
    final = writer.save()
    await asyncio.wrap_future(final)
    saved = json.loads((tmp_path / 'stats.json').read_text())
    assert saved['unknown'] == data['unknown']
    assert saved['total_users'] == [42]
    assert saved['subscription'] == data['subscription']
    assert all(f.done() for f in futures)
    await writer.flush()
    writer.executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_stats_copy_yields_and_restart_includes_mutation(tmp_path):
    data = {'total_users': {42}, 'large': {str(i): {'a': list(range(30))} for i in range(10000)}}
    writer = StatsWriter(lambda: data, str(tmp_path / 'stats.json'), logging.getLogger(__name__))
    barrier = writer.save()
    await asyncio.sleep(.03)
    data['receipt'] = {'paid': True}
    last = writer.save()
    await asyncio.wrap_future(last)
    assert json.loads((tmp_path / 'stats.json').read_text())['receipt'] == {'paid': True}
    assert barrier.done()
    writer.executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_checkout_overload_before_any_reservation(service):
    entered = asyncio.Event()
    release = asyncio.Event()
    old = service.provider.create_checkout
    async def delayed(order):
        entered.set()
        await release.wait()
        return await old(order)
    service.provider.create_checkout = delayed
    tasks = [asyncio.create_task(service.checkout(777123+i, 21, None, f'scale-key-{i}', 'miniapp')) for i in range(8)]
    await entered.wait()
    while service._create_waiting < 8:
        await asyncio.sleep(0)
    with pytest.raises(ProviderNotReady):
        await service.checkout(999999, 21, None, 'rejected-key', 'miniapp')
    assert service.ledger.existing(999999, 'rejected-key') is None
    release.set()
    await asyncio.gather(*tasks)
    assert service._create_waiting == 0


def test_offsite_backup_restores_all_fields_and_never_overwrites(tmp_path):
    import copy
    from services.offsite_backup import snapshot, verify_restore
    folder = tmp_path / 'source'
    folder.mkdir()
    stats = {'total_users': [42, 43], 'user_username': {'42': 'synthetic'}, 'unknown': {'keep': [1, 2]}, 'payments': {'receipt': 'paid'}}
    (folder / 'stats.json').write_text(json.dumps(stats))
    for name in ['billing.sqlite3', 'miniapp_learning.sqlite3']:
        with sqlite3.connect(folder / name) as db:
            db.execute('CREATE TABLE preserved (data TEXT)')
            db.execute('INSERT INTO preserved VALUES (?)', ('opaque',))
    original = copy.deepcopy(stats)
    bundle = snapshot(folder, ['stats.json', 'billing.sqlite3', 'miniapp_learning.sqlite3'])
    result = verify_restore(bundle, tmp_path / 'restored')
    assert len(result) == 3
    assert json.loads((tmp_path / 'restored' / 'stats.json').read_text()) == original
    assert json.loads((folder / 'stats.json').read_text()) == original
    with pytest.raises(FileExistsError):
        verify_restore(bundle, folder)


def test_s3_verifies_download_and_is_private_authenticated(tmp_path):
    import httpx
    from services.offsite_backup import snapshot, S3Store
    (tmp_path / 'stats.json').write_text(json.dumps({'total_users': [42]}))
    objects = {}
    def respond(request):
        assert request.headers['authorization'].startswith('AWS4-HMAC-SHA256 Credential=synthetic/')
        assert request.url.scheme == 'https'
        if request.method == 'PUT':
            objects[str(request.url)] = request.content
            return httpx.Response(200)
        return httpx.Response(200, content=objects[str(request.url)])
    store = S3Store({'BACKUP_S3_ENDPOINT':'https://storage.test', 'BACKUP_S3_BUCKET':'private', 'BACKUP_S3_ACCESS_KEY_ID':'synthetic', 'BACKUP_S3_SECRET_ACCESS_KEY':'synthetic-secret'}, httpx.MockTransport(respond))
    store.verified_upload('vmeda/owner/test.tar.gz', snapshot(tmp_path, ['stats.json']))
    assert len(objects) == 1


@pytest.mark.asyncio
async def test_gateway_streams_and_reuses_one_bounded_pool():
    import httpx
    from web_api.sync_transport import BotGateway
    class Bytes(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'first'
            yield b'second'
    gateway = BotGateway(AsyncMock(), 'http://owner.test', 'synthetic-secret')
    gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Bytes())))
    client = gateway._client
    for _ in range(2):
        sent = []
        async def send(message):
            sent.append(message)
        await gateway({'type':'http','path':'/api/v1/test','method':'GET','headers':[],'query_string':b''}, AsyncMock(return_value={'type':'http.request','body':b''}), send)
        assert [m['body'] for m in sent if m['type']=='http.response.body'] == [b'first', b'second', b'']
    assert gateway._client is client and gateway._active == 0
    await client.aclose()


@pytest.mark.asyncio
async def test_slow_batch_keeps_readiness_and_all_stats(service, monkeypatch):
    import copy
    import time
    import telegram_bot as tb
    from dataclasses import replace
    from services.payments.contracts import PaymentStatus
    from web_api.tests.test_sbp_billing import paid
    from web_api.routers import readiness
    before = copy.deepcopy(tb.stats)
    for i in range(50):
        await service.checkout(888000+i, 21, None, f'batch-key-{i}', 'miniapp')
    async def slow(provider_id):
        await asyncio.sleep(.01)
        return replace(paid(service.ledger.by_provider(provider_id)), status=PaymentStatus.PENDING)
    service.provider.fetch_payment = slow
    monkeypatch.setenv('BOT_SYNC_MODE', 'owner')
    monkeypatch.setenv('CODEEPAY_ENABLED', 'true')
    monkeypatch.setattr(tb, '_sync_owner_running', True, raising=False)
    monkeypatch.setattr(readiness, 'remote_ready', AsyncMock(return_value=True))
    start, base = time.monotonic(), time.time()
    monkeypatch.setattr(time, 'time', lambda: base + (time.monotonic()-start)*1000)
    task = asyncio.create_task(service.poll())
    service.poll_task = task
    try:
        await asyncio.sleep(.12)
        result = await readiness.checks(include_learning=False)
        assert not task.done() and result['billing'] is True
        assert tb.stats == before
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_continuous_mutation_cannot_starve_payment_durability(tmp_path):
    data = {'total_users': {42}, 'counter': 0}
    writer = StatsWriter(lambda: data, str(tmp_path / 'stats.json'), logging.getLogger(__name__))
    from services.stats_writer import ChangedDuringCopy
    writer._snapshot = AsyncMock(side_effect=ChangedDuringCopy())
    barrier = writer.save()
    await asyncio.wait_for(asyncio.wrap_future(barrier), timeout=2)
    assert writer._snapshot.await_count == 3
    assert json.loads((tmp_path / 'stats.json').read_text())['total_users'] == [42]
    writer.executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_native_and_shared_progress_have_same_xp_without_double_count(monkeypatch, tmp_path):
    import copy
    import telegram_bot as tb
    from web_api.routers.learning import dashboard
    monkeypatch.setenv('MINIAPP_LEARNING_DB', str(tmp_path / 'progress.sqlite3'))
    monkeypatch.setenv('BOT_SYNC_MODE', 'legacy')
    monkeypatch.setattr(tb, 'stats', copy.deepcopy(tb.stats))
    topic = tb.PHYSIOLOGY['topics'][0]['topic_id']
    tb.stats['physiology_progress']['424242'] = {topic: {'completed_cards': 3, 'total_cards': 3}}
    first = await dashboard(424242, tb)
    assert first.xp == 40
    learning.touch_material(424242, {'subject_id':'physiology','section_id':'course','material_id':topic,'total_in_section':len(tb.PHYSIOLOGY['topics'])})
    learning.set_material_flag(424242, 'physiology', 'course', topic, 'completed', True)
    assert (await dashboard(424242, tb)).xp == 40


def test_invalid_or_oversized_ai_photo_is_not_forwarded():
    from ai.vision import resize_image, MAX_IMAGE_BYTES
    with pytest.raises(ValueError):
        resize_image(b'not-a-real-image')
    with pytest.raises(ValueError):
        resize_image(b'x' * (MAX_IMAGE_BYTES + 1))


def test_public_callback_still_requires_fresh_merchant_proof(service):
    from fastapi.testclient import TestClient
    from web_api.main import app
    from web_api.deps import get_fresh_bot_module
    from web_api.tests.test_sbp_billing import paid
    from dataclasses import replace
    # No secret pathname is required, but a fake paid field never grants access.
    row = asyncio.run(service.checkout(777123, 21, None, 'public-callback-key', 'miniapp'))
    service.provider.fetch_payment = AsyncMock(return_value=replace(paid(row), amount_minor=row['amount_minor']-1))
    app.dependency_overrides[get_fresh_bot_module] = lambda: service.tb
    try:
        response = TestClient(app).post('/api/v1/subscriptions/codeepay/webhook', json={'order_id':row['provider_id'],'paid':True})
        assert response.status_code == 409
        assert service.tb.get_subscription(777123) is None
    finally:
        app.dependency_overrides.clear()
