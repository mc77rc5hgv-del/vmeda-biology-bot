"""Financial integration and crash recovery on isolated storage, never real bank charges."""
import asyncio
import copy
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from services.payments.config import CodeePayConfig
from services.payments.contracts import CheckoutSession, PaymentMismatch, PaymentStatus, ProviderNotReady, VerifiedPayment
from services.payments.ledger import BillingLedger
from services.payments.providers.codeepay import CodeePayProvider
from services.payments.runtime import BillingRuntime


@pytest.fixture
def service(tmp_path, monkeypatch):
    import telegram_bot as tb
    stats = copy.deepcopy(tb.stats)
    stats['subscriptions'] = {}
    stats['subscription_purchase_log'] = []
    stats['processed_payment_charge_ids'] = {}
    stats['user_username']['777123'] = 'preserve_username'
    stats['total_users'].add(777123)
    stats['opaque_test_field'] = {'retain': ['all', 'original', 'data']}
    monkeypatch.setattr(tb, 'stats', stats)
    monkeypatch.setattr(tb.bot, 'send_message', AsyncMock())
    provider = CodeePayProvider(CodeePayConfig.from_env({'CODEEPAY_ENABLED': 'true', 'CODEEPAY_API_KEY': 'synthetic', 'CODEEPAY_WEBHOOK_SECRET': 'a' * 48}))
    async def create(order):
        return CheckoutSession(order.order_id, 'provider_' + order.order_id, 'https://payment.codeepay.xyz/transfer/test')
    provider.create_checkout = AsyncMock(side_effect=create)
    billing = BillingRuntime(tb, BillingLedger(tmp_path / 'billing.sqlite3'), provider)
    monkeypatch.setattr(tb, '_billing_runtime', billing, raising=False)
    yield billing
    tb._stats_executor.submit(lambda: None).result()


def paid(row, **changes):
    result = VerifiedPayment('codeepay', 'charge-' + row['id'], row['provider_id'], row['id'], row['amount_minor'], 'RUB', PaymentStatus.PAID,
                             {'proof': row['proof'], 'net_minor': row['amount_minor'] * 95 // 100, 'fee_minor': row['amount_minor'] * 5 // 100})
    return replace(result, **changes)


@pytest.mark.asyncio
async def test_create_unpaid_quote_does_not_change_any_user_data_and_retries_reuse(service):
    before = copy.deepcopy(service.tb.stats)
    a, b = await asyncio.gather(service.checkout(777123, 21, None, 'request-0001', 'miniapp'), service.checkout(777123, 21, None, 'request-0001', 'miniapp'))
    c = await service.checkout(777123, 21, None, 'request-0002', 'bot')
    assert a['id'] == b['id'] == c['id']
    assert service.provider.create_checkout.await_count == 1
    assert a['amount_minor'] == service.tb.SUBSCRIPTION_TIERS[21]['price_rub'] * 100
    assert service.tb.stats == before
    assert a['username'] == 'preserve_username'
    with pytest.raises(ValueError):
        await service.checkout(777123, 30, None, 'request-0003', 'miniapp')
    with pytest.raises(ValueError):
        await service.checkout(777123, 20, None, 'request-0004', 'miniapp')


@pytest.mark.asyncio
async def test_callback_poll_repeats_and_restart_grant_exactly_once(service):
    before = copy.deepcopy(service.tb.stats)
    row = await service.checkout(777123, 21, None, 'request-0001', 'miniapp')
    service.provider.fetch_payment = AsyncMock(return_value=paid(row))
    await asyncio.gather(service.check(row, force=True), service.check(row, force=True))
    receipt = copy.deepcopy(service.tb.get_subscription(777123))
    await service.settle(row, paid(row))
    assert service.tb.get_subscription(777123) == receipt
    assert len(service.tb.stats['subscription_purchase_log']) == 1
    assert len(service.tb.stats['processed_payment_charge_ids']) == 1
    assert service.ledger.get(row['id'])['state'] == 'applied'
    for key in before:
        if key not in ('subscriptions', 'subscription_purchase_log', 'processed_payment_charge_ids'):
            assert service.tb.stats[key] == before[key], key
    # A crash after stats durability but before ledger status must not extend a second time.
    with service.ledger.connect() as db:
        db.execute('UPDATE orders SET state="confirmed" WHERE id=?', (row['id'],))
    restarted = BillingRuntime(service.tb, BillingLedger(service.ledger.path), service.provider)
    await restarted.check(restarted.ledger.get(row['id']), force=True)
    assert restarted.ledger.get(row['id'])['state'] == 'applied'
    assert service.tb.get_subscription(777123) == receipt
    assert len(service.tb.stats['subscription_purchase_log']) == 1


@pytest.mark.asyncio
async def test_renewal_preserves_unknown_fields_ai_counters_and_remaining_term(service):
    tb = service.tb
    tb.grant_subscription(777123, 21, 'rubles', tb.SUBSCRIPTION_TIERS[21]['price_rub'], persist=False)
    old = tb.get_subscription(777123)
    old.update(ai_used_monthly={'month': tb.local_today().strftime('%Y-%m'), 'used': 3}, ai_used_period=17, preserve_extra={'data': 8})
    before = copy.deepcopy(old)
    row = await service.checkout(777123, 21, None, 'request-renewal', 'bot')
    await service.settle(row, paid(row))
    updated = tb.get_subscription(777123)
    assert updated['expires'] == before['expires'] + tb.SUBSCRIPTION_TIERS[21]['duration_days'] * 86400
    assert updated['ai_used_period'] == 17 and updated['ai_used_monthly'] == before['ai_used_monthly']
    assert updated['preserve_extra'] == {'data': 8}


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [{'amount_minor': 1}, {'currency': 'USD'}, {'order_id': 'foreign'}, {'provider_payment_id': 'foreign'}, {'status': PaymentStatus.PENDING}, {'evidence': {'proof': 'foreign'}}])
async def test_wrong_payment_never_grants_or_changes_stats(service, changes):
    row = await service.checkout(777123, 21, None, 'request-0001', 'miniapp')
    before = copy.deepcopy(service.tb.stats)
    with pytest.raises(PaymentMismatch):
        await service.settle(row, paid(row, **changes))
    assert service.tb.stats == before
    assert service.ledger.get(row['id'])['state'] == 'pending'


@pytest.mark.asyncio
async def test_current_subscription_race_records_paid_review_without_downgrade(service):
    row = await service.checkout(777123, 20, 'biology', 'request-0001', 'miniapp')
    service.tb.grant_subscription(777123, 26, 'rubles', service.tb.SUBSCRIPTION_TIERS[26]['price_rub'], persist=False)
    previous = copy.deepcopy(service.tb.get_subscription(777123))
    await service.settle(row, paid(row))
    assert service.ledger.get(row['id'])['state'] == 'review'
    assert service.tb.get_subscription(777123) == previous


@pytest.mark.asyncio
async def test_write_failure_is_retryable_and_does_not_issue_double_subscription(service, monkeypatch):
    import web_api.subscriptions as subscriptions
    row = await service.checkout(777123, 21, None, 'request-0001', 'bot')
    persist = subscriptions._persist
    monkeypatch.setattr(subscriptions, '_persist', AsyncMock(side_effect=OSError('synthetic disk failure')))
    with pytest.raises(OSError):
        await service.settle(row, paid(row))
    assert service.ledger.get(row['id'])['state'] == 'confirmed'
    original = copy.deepcopy(service.tb.get_subscription(777123))
    monkeypatch.setattr(subscriptions, '_persist', persist)
    await service.settle(row, paid(row))
    assert service.ledger.get(row['id'])['state'] == 'applied'
    assert service.tb.get_subscription(777123) == original
    assert len(service.tb.stats['subscription_purchase_log']) == 1


@pytest.mark.asyncio
async def test_unknown_creation_does_not_blindly_retry(service):
    service.provider.create_checkout.side_effect = ProviderNotReady('synthetic timeout')
    with pytest.raises(ProviderNotReady):
        await service.checkout(777123, 21, None, 'request-0001', 'bot')
    with pytest.raises(ProviderNotReady):
        await service.checkout(777123, 21, None, 'request-0001', 'miniapp')
    with pytest.raises(ProviderNotReady):
        await service.checkout(777123, 21, None, 'request-0002', 'miniapp')
    assert service.provider.create_checkout.await_count == 1


def test_owner_routes_user_isolation_price_validation_and_forged_callback(service):
    from web_api.main import app
    from web_api.deps import get_current_user_id, get_fresh_bot_module
    app.dependency_overrides[get_current_user_id] = lambda: 777123
    app.dependency_overrides[get_fresh_bot_module] = lambda: service.tb
    service.provider.fetch_payment = AsyncMock()
    client = TestClient(app)
    try:
        assert client.get('/api/v1/subscriptions/catalog').json()['sbp_available'] is True
        body = {'tier_id': 21, 'request_key': 'request-0001'}
        for extra in ({'amount_minor': 1}, {'user_id': 1}, {'tier_id': True}):
            assert client.post('/api/v1/subscriptions/sbp', json={**body, **extra}).status_code == 422
        result = client.post('/api/v1/subscriptions/sbp', json=body)
        assert result.status_code == 200, result.text
        row = service.ledger.get(result.json()['payment_id'])
        service.provider.fetch_payment.return_value = paid(row, status=PaymentStatus.PENDING)
        url = '/api/v1/subscriptions/codeepay/webhook/' + 'a' * 48
        assert client.post(url, json={'order_id': row['provider_id'], 'amount': row['amount_minor'], 'status': 'paid'}).status_code == 200
        assert service.tb.get_subscription(777123) is None, 'Forged webhook granted access'
        assert client.post(url.replace('a' * 48, 'wrong'), json={'order_id': row['provider_id']}).status_code == 404
        assert client.get('/api/v1/subscriptions/admin/sbp').status_code == 403
        history = client.get('/api/v1/subscriptions/history').json()['payments']
        assert len(history) == 1 and 'proof' not in history[0] and 'username' not in history[0]
        app.dependency_overrides[get_current_user_id] = lambda: 777124
        assert client.get('/api/v1/subscriptions/payments/' + row['id']).status_code == 404
        assert client.get('/api/v1/subscriptions/history').json()['payments'] == []
    finally:
        app.dependency_overrides.clear()
