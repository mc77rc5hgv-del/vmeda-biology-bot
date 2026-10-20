"""Badge prices, authenticated settlement, crash recovery and historical data safety."""
import asyncio
import copy
import sqlite3
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.badge_orders import RECIPIENT_ID, price_quote
from services.payments.contracts import CheckoutSession, PaymentMismatch, PaymentStatus, ProviderNotReady, VerifiedPayment
from services.payments.ledger import BillingLedger
from services.payments.runtime import BillingRuntime


@pytest.fixture
def service(tmp_path, monkeypatch):
    import telegram_bot as tb
    stats = copy.deepcopy(tb.stats)
    stats['badge_orders'] = {}
    stats['processed_payment_charge_ids'] = {}
    monkeypatch.setattr(tb, 'stats', stats)
    monkeypatch.setattr(tb.bot, 'send_message', AsyncMock())
    provider = SimpleNamespace(config=SimpleNamespace(timeout_seconds=15), public_status=lambda: {'available': True})
    async def create(order):
        assert order.kind == 'badge' and order.tier_id == 0
        return CheckoutSession(order.order_id, 'provider_' + order.order_id, 'https://payment.codeepay.xyz/transfer/test')
    provider.create_checkout = AsyncMock(side_effect=create)
    billing = BillingRuntime(tb, BillingLedger(tmp_path / 'billing.sqlite3'), provider)
    monkeypatch.setattr(tb, '_billing_runtime', billing, raising=False)
    yield billing
    tb._stats_executor.submit(lambda: None).result()


def badge(service, quantity='15', order_id='badge-test'):
    order = {'id': order_id, 'user_id': 777123, 'username': None, 'full_name': '<Buyer>',
             'details': {'fio': 'Иванов Иван Иванович', 'role': 'Студент', 'specialty': 'Лечебное дело', 'quantity': quantity},
             'created_at': 1, 'delivery': 'sent', 'pricing': price_quote(quantity)}
    service.tb.stats['badge_orders'][order_id] = order
    return order


def paid(row):
    return VerifiedPayment('codeepay', 'charge-' + row['id'], row['provider_id'], row['id'], row['amount_minor'], 'RUB', PaymentStatus.PAID,
                           {'proof': row['proof'], 'net_minor': row['amount_minor'] - 100, 'fee_minor': 100})


@pytest.mark.parametrize('quantity,total,unit', [(1,530,530),(14,7420,530),(15,6450,430),(16,6880,430),(100,43000,430)])
def test_volume_discount(quantity,total,unit):
    assert price_quote(quantity) == {'quantity': quantity, 'unit_price_rub': unit, 'total_rub': total}


@pytest.mark.parametrize('quantity', ['0','101','-1','1.5','True','١'])
def test_bad_quantity(quantity):
    with pytest.raises(ValueError):
        price_quote(quantity)


@pytest.mark.asyncio
async def test_checkout_reuse_ownership_and_immutable_price(service):
    order = badge(service)
    before = copy.deepcopy(service.tb.stats)
    results = await asyncio.gather(service.checkout_badge(777123, order['id']), service.checkout_badge(777123, order['id']))
    assert results[0]['id'] == results[1]['id'] and results[0]['amount_minor'] == 645000
    assert results[0]['kind'] == 'badge'
    assert service.provider.create_checkout.await_count == 1
    assert service.tb.stats == before
    with pytest.raises(ValueError):
        await service.checkout_badge(999999, order['id'])
    other = badge(service, order_id='forged')
    other['pricing']['total_rub'] = 1
    with pytest.raises(ValueError):
        await service.checkout_badge(777123, other['id'])
    assert service.provider.create_checkout.await_count == 1


@pytest.mark.asyncio
async def test_paid_exactly_once_separate_from_subscriptions_and_notifies_helper(service):
    order = badge(service)
    protected = {k: copy.deepcopy(v) for k,v in service.tb.stats.items() if k not in ('badge_orders','processed_payment_charge_ids')}
    row = await service.checkout_badge(777123, order['id'])
    await asyncio.gather(service.settle(row, paid(row)), service.settle(row, paid(row)))
    assert order['payment']['status'] == 'paid' and order['payment']['amount_minor'] == 645000
    assert len(service.tb.stats['processed_payment_charge_ids']) == 1
    assert service.ledger.get(row['id'])['state'] == 'applied'
    assert all(service.tb.stats[k] == v for k,v in protected.items())
    targets = [call.args[0] for call in service.tb.bot.send_message.call_args_list]
    assert targets.count(RECIPIENT_ID) == 1 and targets.count(777123) == 1
    helper_message = next(call.args[1] for call in service.tb.bot.send_message.call_args_list if call.args[0] == RECIPIENT_ID)
    assert '15 шт. × 430 ₽ = 6450 ₽' in helper_message
    assert 'ОПЛАЧЕНО' in helper_message and '&lt;Buyer&gt;' in helper_message
    assert 'tg://user?id=777123' in helper_message
    assert 'не подтверждает оплату' not in helper_message
    with pytest.raises(ValueError):
        await service.checkout_badge(777123, order['id'])
    # Durable receipt survives a stats/ledger boundary crash with no second notification.
    with service.ledger.connect() as db:
        db.execute('UPDATE orders SET state="confirmed" WHERE id=?', (row['id'],))
    restarted = BillingRuntime(service.tb, BillingLedger(service.ledger.path), service.provider)
    count = service.tb.bot.send_message.await_count
    await restarted.settle(restarted.ledger.get(row['id']), paid(row))
    assert restarted.ledger.get(row['id'])['state'] == 'applied'
    assert service.tb.bot.send_message.await_count == count


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [{'amount_minor':1},{'currency':'USD'},{'order_id':'foreign'},{'provider_payment_id':'foreign'},{'status':PaymentStatus.PENDING},{'evidence':{'proof':'forged'}}])
async def test_unverified_payment_changes_nothing(service,change):
    order = badge(service)
    row = await service.checkout_badge(777123, order['id'])
    before = copy.deepcopy(service.tb.stats)
    with pytest.raises(PaymentMismatch):
        await service.settle(row, replace(paid(row),**change))
    assert service.tb.stats == before
    assert service.ledger.get(row['id'])['state'] == 'pending'
    assert not service.tb.bot.send_message.called


@pytest.mark.asyncio
async def test_paid_but_missing_order_goes_to_review_without_grant(service):
    order = badge(service)
    row = await service.checkout_badge(777123, order['id'])
    del service.tb.stats['badge_orders'][order['id']]
    before = copy.deepcopy(service.tb.stats['subscriptions'])
    await service.settle(row, paid(row))
    assert service.ledger.get(row['id'])['state'] == 'review'
    assert service.tb.stats['subscriptions'] == before
    assert not service.tb.bot.send_message.called
    # Restore the original immutable order and resolve through authenticated provider evidence.
    service.tb.stats['badge_orders'][order['id']] = order
    service.provider.fetch_payment = AsyncMock(return_value=paid(row))
    admin = next(iter(service.tb.ADMIN_IDS))
    await service.reconcile(row['id'], admin, 'apply_review', note='Исходный заказ восстановлен и проверен')
    assert order['payment']['status'] == 'paid'
    assert service.ledger.get(row['id'])['state'] == 'applied'
    assert service.tb.stats['subscriptions'] == before


@pytest.mark.asyncio
async def test_unknown_creation_never_creates_second_invoice(service):
    order = badge(service)
    service.provider.create_checkout.side_effect = TimeoutError('synthetic timeout')
    with pytest.raises(TimeoutError):
        await service.checkout_badge(777123, order['id'])
    with pytest.raises(ProviderNotReady):
        await service.checkout_badge(777123, order['id'])
    assert service.provider.create_checkout.await_count == 1


@pytest.mark.asyncio
async def test_notification_timeout_never_duplicates_paid_order(service):
    order = badge(service)
    row = await service.checkout_badge(777123, order['id'])
    service.tb.bot.send_message.side_effect = TimeoutError('synthetic Telegram timeout')
    await service.settle(row, paid(row))
    count = service.tb.bot.send_message.await_count
    await service.settle(row, paid(row))
    from services.payments.badges import flush_notifications
    await flush_notifications(service)
    assert service.tb.bot.send_message.await_count == count
    assert set(order['payment_notifications'].values()) == {'unknown'}
    assert order['payment']['status'] == 'paid'


@pytest.mark.asyncio
async def test_durable_write_failure_and_restart_outbox(service,monkeypatch):
    import web_api.subscriptions as sub
    from services.payments.badges import flush_notifications
    order = badge(service)
    row = await service.checkout_badge(777123, order['id'])
    persist = sub._persist
    monkeypatch.setattr(sub, '_persist', AsyncMock(side_effect=OSError('synthetic write failure')))
    with pytest.raises(OSError):
        await service.settle(row, paid(row))
    assert not service.tb.bot.send_message.called
    monkeypatch.setattr(sub, '_persist', persist)
    restarted = BillingRuntime(service.tb,BillingLedger(service.ledger.path),service.provider)
    await restarted.settle(restarted.ledger.get(row['id']), paid(row))
    assert restarted.ledger.get(row['id'])['state'] == 'applied'
    assert order['payment_notifications'][str(RECIPIENT_ID)] == 'sent'
    # A process killed between durable 'sending' and Telegram acknowledgement is ambiguous.
    order['payment_notifications'][str(RECIPIENT_ID)] = 'sending'
    count = service.tb.bot.send_message.await_count
    await flush_notifications(restarted)
    assert order['payment_notifications'][str(RECIPIENT_ID)] == 'unknown'
    assert service.tb.bot.send_message.await_count == count


def test_legacy_ledger_migration_preserves_every_original_value(tmp_path):
    path=tmp_path/'old.sqlite3'
    ledger=BillingLedger(path)
    original=ledger.create(dict(id='old',user_id=777123,request_key='old',tier_id=21,subject=None,
                               amount_minor=12900,proof='original-proof',source='bot',username='original_username'))
    with ledger.connect() as db:
        db.execute('ALTER TABLE orders DROP COLUMN kind')
        rows_before=db.execute('SELECT * FROM orders').fetchall()
        events_before=db.execute('SELECT * FROM events').fetchall()
    migrated=BillingLedger(path)
    restored=migrated.get('old')
    assert restored == original and restored['kind']=='subscription'
    with sqlite3.connect(migrated.backup_info['path']) as backup:
        assert backup.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert backup.execute('SELECT * FROM orders').fetchall()==[tuple(row) for row in rows_before]
        assert backup.execute('SELECT * FROM events').fetchall()==[tuple(row) for row in events_before]


@pytest.mark.asyncio
async def test_provider_receives_physical_goods_description_and_exact_total():
    import json
    import httpx
    from services.payments.config import CodeePayConfig
    from services.payments.contracts import PaymentOrder
    from services.payments.providers.codeepay import CodeePayProvider
    def respond(request):
        payload = json.loads(request.content)
        assert payload['amount'] == 6450 and payload['method_slug'] == 'sbp'
        assert 'бейджики' in payload['description'] and 'подписка' not in payload['description']
        assert set(payload['metadata']) == {'vmeda_order', 'vmeda_proof'}
        return httpx.Response(200, json={'order_id':'provider', 'url':'https://payment.codeepay.xyz/transfer/test','amount':6450})
    config = CodeePayConfig.from_env({'CODEEPAY_ENABLED':'true','CODEEPAY_API_KEY':'synthetic','CODEEPAY_WEBHOOK_SECRET':'a'*48})
    provider = CodeePayProvider(config, transport=httpx.MockTransport(respond))
    order = PaymentOrder('sbp_test', 777123, 0, 'badge-test', 'codeepay', 645000, 'RUB', 'synthetic-proof', 'badge')
    session = await provider.create_checkout(order)
    assert session.provider_payment_id == 'provider'
