import asyncio
import copy
from dataclasses import replace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from services.payments.contracts import CheckoutRejected, CheckoutSession, PaymentMismatch, ProviderNotReady
from services.payments.runtime import BillingRuntime
from services.payments.providers.codeepay import CodeePayProvider
from web_api.tests.test_sbp_billing import paid

pytest_plugins = ["web_api.tests.test_sbp_billing"]


@pytest.mark.asyncio
@pytest.mark.parametrize('status,rejected', [(401, True), (403, True), (422, True), (400, False), (500, False)])
async def test_only_definitive_provider_errors_allow_creation_retry(service, status, rejected):
    provider = CodeePayProvider(service.provider.config, transport=httpx.MockTransport(lambda request: httpx.Response(status)))
    error = CheckoutRejected if rejected else ProviderNotReady
    with pytest.raises(error) as exc:
        await provider._post('/initiate_payment', {})  # noqa: SLF001 - provider classification boundary
    assert isinstance(exc.value, CheckoutRejected) is rejected


@pytest.mark.asyncio
async def test_definitive_rejection_can_retry_same_key_without_changing_quote(service):
    service.provider.create_checkout.side_effect = CheckoutRejected('validation rejected')
    before = copy.deepcopy(service.tb.stats)
    with pytest.raises(CheckoutRejected):
        await service.checkout(777123, 21, None, 'retry-safe-key', 'miniapp')
    row = service.ledger.existing(777123, 'retry-safe-key')
    assert row['state'] == 'creation_rejected'
    service.provider.create_checkout.side_effect = None
    service.provider.create_checkout.return_value = CheckoutSession(row['id'], 'provider-test', 'https://codeepay.ru/payment/test')
    result = await service.checkout(777123, 21, None, 'retry-safe-key', 'miniapp')
    assert result['id'] == row['id'] and result['state'] == 'pending'
    assert result['proof'] == row['proof'] and service.tb.stats == before


@pytest.mark.asyncio
async def test_lost_creation_recovers_authenticated_callback_and_grants_once(service):
    before = copy.deepcopy(service.tb.stats)
    service.provider.create_checkout.side_effect = ProviderNotReady('response lost')
    with pytest.raises(ProviderNotReady):
        await service.checkout(777123, 21, None, 'unknown-key-1', 'miniapp')
    row = service.ledger.existing(777123, 'unknown-key-1')
    provider_row = {**row, 'provider_id': 'real-invoice'}
    service.provider.fetch_payment = AsyncMock(return_value=paid(provider_row))
    await asyncio.gather(service.recover_provider('real-invoice'), service.recover_provider('real-invoice'))
    assert service.ledger.get(row['id'])['state'] == 'applied'
    assert len(service.tb.stats['processed_payment_charge_ids']) == 1
    assert len(service.tb.stats['subscription_purchase_log']) == 1
    for key in before:
        if key not in ('subscriptions', 'subscription_purchase_log', 'processed_payment_charge_ids'):
            assert service.tb.stats[key] == before[key]


@pytest.mark.asyncio
async def test_recovery_rejects_amount_proof_and_other_order_without_binding(service):
    service.provider.create_checkout.side_effect = ProviderNotReady('lost')
    with pytest.raises(ProviderNotReady):
        await service.checkout(777123, 21, None, 'unknown-key-2', 'bot')
    row = service.ledger.existing(777123, 'unknown-key-2')
    payment = paid({**row, 'provider_id': 'candidate'})
    before = copy.deepcopy(service.tb.stats)
    for invalid in (replace(payment, amount_minor=1), replace(payment, order_id='foreign'),
                    replace(payment, evidence={**payment.evidence, 'proof': 'wrong'})):
        service.provider.fetch_payment = AsyncMock(return_value=invalid)
        with pytest.raises(PaymentMismatch):
            await service.recover_provider('candidate')
        assert service.ledger.get(row['id'])['provider_id'] is None
        assert service.tb.stats == before


@pytest.mark.asyncio
async def test_manual_closure_requires_admin_and_note_preserves_events_and_late_payment(service):
    service.provider.create_checkout.side_effect = ProviderNotReady('lost')
    with pytest.raises(ProviderNotReady):
        await service.checkout(777123, 21, None, 'unknown-key-3', 'bot')
    row = service.ledger.existing(777123, 'unknown-key-3')
    with pytest.raises(PermissionError):
        await service.reconcile(row['id'], 777123, 'close_not_created', note='Cabinet reconciliation')
    admin = next(iter(service.tb.ADMIN_IDS))
    with pytest.raises(ValueError):
        await service.reconcile(row['id'], admin, 'close_not_created', note='short')
    result = await service.reconcile(row['id'], admin, 'close_not_created', note='Cabinet checked, invoice absent; ticket 123')
    assert result['state'] == 'creation_closed'
    assert any('admin_verified_no_invoice' == e['state'] for e in service.ledger.events(row['id']))
    service.provider.fetch_payment = AsyncMock(return_value=paid({**row, 'provider_id': 'late-invoice'}))
    await service.recover_provider('late-invoice')
    assert service.ledger.get(row['id'])['state'] == 'applied'


@pytest.mark.asyncio
async def test_review_resolution_cannot_downgrade_or_count_revenue_twice(service):
    tb = service.tb
    row = await service.checkout(777123, 21, None, 'review-key-1', 'bot')
    tb.grant_subscription(777123, 24, 'synthetic', 0)
    service.provider.fetch_payment = AsyncMock(return_value=paid(row))
    await service.check(row, force=True)
    original = copy.deepcopy(tb.get_subscription(777123))
    admin = next(iter(tb.ADMIN_IDS))
    with pytest.raises(ValueError):
        await service.reconcile(row['id'], admin, 'apply_review', note='Verify paid subscription safely')
    assert tb.get_subscription(777123) == original
    # Simulate the conflicting entitlement expiring; do not erase any history.
    tb.stats['subscriptions']['777123']['expires'] = 1
    before_total = sum(e['price'] for e in tb.stats['subscription_purchase_log'] if e['method'] == 'rubles')
    resolved = await service.reconcile(row['id'], admin, 'apply_review', note='Conflict expired, apply the confirmed payment')
    assert resolved['state'] == 'applied'
    subscription = copy.deepcopy(tb.get_subscription(777123))
    await service.reconcile(row['id'], admin, 'apply_review', note='Retry the same administrative operation')
    assert tb.get_subscription(777123) == subscription
    assert sum(e['price'] for e in tb.stats['subscription_purchase_log'] if e['method'] == 'rubles') == before_total
    assert len(tb.stats['processed_payment_charge_ids']) == 1


@pytest.mark.asyncio
async def test_keep_existing_does_not_grant_or_erase_original_receipt(service):
    row = await service.checkout(777123, 21, None, 'review-key-2', 'bot')
    service.tb.grant_subscription(777123, 24, 'synthetic', 0)
    service.provider.fetch_payment = AsyncMock(return_value=paid(row))
    await service.check(row, force=True)
    original = copy.deepcopy(service.tb.get_subscription(777123))
    admin = next(iter(service.tb.ADMIN_IDS))
    result = await service.reconcile(row['id'], admin, 'keep_existing', note='Customer agreed to preserve current access, ticket 456')
    assert result['state'] == 'resolved_keep'
    await service.settle(row, paid(row))
    assert service.tb.get_subscription(777123) == original
    assert len(service.tb.stats['processed_payment_charge_ids']) == 1


@pytest.mark.asyncio
async def test_one_slow_customer_does_not_serialize_other_customers(service):
    started, release = asyncio.Event(), asyncio.Event()
    async def create(order):
        if order.user_id == 777123:
            started.set()
            await release.wait()
        return CheckoutSession(order.order_id, 'provider-' + order.order_id, 'https://codeepay.ru/payment/test')
    service.provider.create_checkout.side_effect = create
    first = asyncio.create_task(service.checkout(777123, 21, None, 'concurrent-key', 'bot'))
    try:
        await asyncio.wait_for(started.wait(), 1)
        second = await asyncio.wait_for(service.checkout(777124, 21, None, 'concurrent-key', 'miniapp'), 1)
        assert second['state'] == 'pending'
    finally:
        release.set()
        await first


def test_cancelled_checkout_never_returns_payment_url(service):
    from web_api.main import app
    from web_api.deps import get_current_user_id, get_fresh_bot_module
    app.dependency_overrides[get_current_user_id] = lambda: 777123
    app.dependency_overrides[get_fresh_bot_module] = lambda: service.tb
    try:
        client = TestClient(app)
        payload = {'tier_id': 21, 'request_key': 'cancelled-key'}
        response = client.post('/api/v1/subscriptions/sbp', json=payload)
        service.ledger.update(response.json()['payment_id'], 'cancelled')
        result = client.post('/api/v1/subscriptions/sbp', json=payload)
        assert result.status_code == 409 and 'url' not in result.json()
        assert client.post('/api/v1/subscriptions/admin/sbp/x/reconcile', json={'action': 'bind', 'note': 'unauthorized attempt'}).status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_restart_classifies_interrupted_creation_without_deleting_journal(service):
    row = service.ledger.create({'id': 'sbp_interrupted', 'user_id': 777123, 'request_key': 'interrupted-key',
                                'tier_id': 21, 'subject': None, 'amount_minor': 100, 'proof': 'preserved', 'source': 'bot', 'username': 'preserved'})
    service.ledger.recover_interrupted_creation()
    assert service.ledger.get(row['id'])['state'] == 'creation_unknown'
    assert service.ledger.get(row['id'])['username'] == 'preserved'
    assert len(service.ledger.events(row['id'])) == 2
    assert BillingRuntime(service.tb, service.ledger, service.provider).ledger.get(row['id'])['proof'] == 'preserved'


@pytest.mark.asyncio
async def test_callback_can_arrive_before_checkout_response_without_losing_paid_state(service):
    async def create(order):
        row = service.ledger.get(order.order_id)
        service.provider.fetch_payment = AsyncMock(return_value=paid({**row, 'provider_id': 'early-invoice'}))
        await service.recover_provider('early-invoice')
        return CheckoutSession(order.order_id, 'early-invoice', 'https://codeepay.ru/payment/early')
    service.provider.create_checkout.side_effect = create
    row = await service.checkout(777123, 21, None, 'early-callback', 'miniapp')
    assert row['state'] == 'applied' and row['url'] == 'https://codeepay.ru/payment/early'
    assert len(service.tb.stats['processed_payment_charge_ids']) == 1
