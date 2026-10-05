"""Billing runs inside the existing bot owner; no second bot and no second stats writer."""
import asyncio
import copy
import hmac
import os
import secrets
import time

from .config import CodeePayConfig
from .contracts import PaymentMismatch, PaymentOrder, PaymentStatus, ProviderNotReady, validate_confirmation
from .ledger import BillingLedger
from .providers.codeepay import CodeePayProvider


def runtime(tb):
    return getattr(tb, '_billing_runtime', None)


def available(tb):
    service = runtime(tb)
    return bool(service and service.provider.public_status()['available'])


class BillingRuntime:
    def __init__(self, tb, ledger, provider):
        self.tb, self.ledger, self.provider = tb, ledger, provider
        self._lock = asyncio.Lock()
        self._create_lock = asyncio.Lock()
        self._poll_gate = asyncio.Semaphore(2)
        self._checking = set()

    @staticmethod
    def order(row):
        return PaymentOrder(row['id'], row['user_id'], row['tier_id'], row['subject'], 'codeepay', row['amount_minor'], 'RUB', row['proof'])

    async def checkout(self, user_id, tier_id, subject, request_key, source):
        from web_api.subscriptions import purchase_reason, validate_tier
        # No await between reservation and durable record; duplicated clicks never create twice.
        async with self._create_lock:
            existing = self.ledger.existing(user_id, request_key)
            if existing:
                if existing['tier_id'] != tier_id or existing['subject'] != subject:
                    raise ValueError('Ключ запроса уже связан с другим тарифом')
                if existing['url']:
                    return existing
                raise ProviderNotReady('Создание этого счёта ещё не подтверждено. Проверь историю или напиши @vmeda_helper.')
            cfg = validate_tier(self.tb, tier_id, subject)
            reason = purchase_reason(self.tb, user_id, tier_id, subject)
            if reason:
                raise ValueError(reason)
            if not self.provider.public_status()['available']:
                raise ProviderNotReady('СБП временно недоступна')
            # Reuse a recent matching pending checkout even after an HTTP retry/new client nonce.
            for previous in self.ledger.history(user_id, limit=5):
                if previous['state'] == 'pending' and previous['tier_id'] == tier_id and previous['subject'] == subject and previous['created'] > time.time() - 900 and previous['url']:
                    return previous
            if any(previous['state'] in ('creating', 'creation_unknown') and previous['created'] > time.time() - 3600 for previous in self.ledger.history(user_id, limit=5)):
                raise ProviderNotReady('Предыдущий счёт требует проверки. Напиши @vmeda_helper перед повторной оплатой.')
            price = cfg.get('price_rub')
            if type(price) is not int or price <= 0:
                raise ValueError('Нет рублёвой цены тарифа')
            row = self.ledger.create({'id': 'sbp_' + secrets.token_hex(16), 'user_id': user_id, 'request_key': request_key,
                 'tier_id': tier_id, 'subject': subject, 'amount_minor': price * 100, 'proof': secrets.token_hex(24),
                 'source': source, 'username': self.tb.stats.get('user_username', {}).get(str(user_id))})
            try:
                session = await self.provider.create_checkout(self.order(row))
                self.ledger.update(row['id'], 'pending', provider_id=session.provider_payment_id, url=session.checkout_url)
            except Exception:
                # Provider has no documented idempotency endpoint. Do not retry an ambiguous creation.
                self.ledger.update(row['id'], 'creation_unknown', reason='Счёт не подтверждён провайдером. Обратись в поддержку перед повторной оплатой.')
                raise
            return self.ledger.get(row['id'])

    async def check(self, row, *, force=False):
        if not row or not row['provider_id'] or row['state'] in ('applied', 'review'):
            return row
        if row['id'] in self._checking or not force and row['checked'] > time.time() - 15:
            return self.ledger.get(row['id'])
        self._checking.add(row['id'])
        try:
            async with self._poll_gate:
                payment = await self.provider.fetch_payment(row['provider_id'])
            if payment.order_id != row['id'] or not hmac.compare_digest(str(payment.evidence.get('proof', '')), row['proof']):
                raise PaymentMismatch('Merchant binding does not match')
            if payment.status is PaymentStatus.PAID:
                validate_confirmation(self.order(row), payment, provider_payment_id=row['provider_id'])
                await self.settle(row, payment)
            else:
                state = payment.status.value if payment.status in (PaymentStatus.FAILED, PaymentStatus.CANCELLED) else row['state']
                self.ledger.update(row['id'], state, checked=time.time())
            return self.ledger.get(row['id'])
        finally:
            self._checking.discard(row['id'])

    async def settle(self, row, payment):
        from web_api.subscriptions import _persist, grant_preserving_history, purchase_reason
        tb = self.tb
        async with self._lock:
            validate_confirmation(self.order(row), payment, provider_payment_id=row['provider_id'])
            if not hmac.compare_digest(str(payment.evidence.get('proof', '')), row['proof']):
                raise PaymentMismatch('Merchant proof does not match')
            self.ledger.update(row['id'], 'confirmed', net_minor=payment.evidence['net_minor'],
                               fee_minor=payment.evidence['fee_minor'], charge_id=payment.event_id, checked=time.time())
            receipts = tb.stats.setdefault('processed_payment_charge_ids', {})
            charge_key = 'codeepay:' + payment.event_id
            previous = receipts.get(charge_key)
            if previous:
                if previous.get('payment_id') != row['id'] or previous.get('user_id') != row['user_id']:
                    raise PaymentMismatch('Charge already belongs to another order')
                await _persist(tb)  # recover a stats-write/ledger-write crash without regranting
                self.ledger.update(row['id'], previous['status'], reason=previous.get('reason'))
                return
            old = copy.deepcopy(tb.get_subscription(row['user_id']))
            try:
                reason = purchase_reason(tb, row['user_id'], row['tier_id'], row['subject'])
            except ValueError as exc:
                reason = str(exc)
            receipt = {'user_id': row['user_id'], 'payment_id': row['id'], 'tier': row['tier_id'],
                       'provider': 'codeepay', 'amount_minor': row['amount_minor'], 'currency': 'RUB',
                       'at': time.time(), 'source': row['source'], 'previous_subscription': old,
                       'status': 'review' if reason else 'applied', 'reason': reason}
            if not reason:
                grant_preserving_history(tb, row['user_id'], row['tier_id'], row['subject'], 'rubles', row['amount_minor'] // 100, old)
                tb.stats['subscription_purchase_log'][-1].update(provider='codeepay', payment_id=row['id'], source=row['source'])
            else:
                tb.stats.setdefault('subscription_purchase_log', []).append({'user_id': row['user_id'], 'tier': row['tier_id'],
                    'method': 'rubles', 'price': row['amount_minor'] // 100, 'ts': time.time(), 'status': 'review', 'provider': 'codeepay', 'payment_id': row['id']})
            receipts[charge_key] = receipt
            await _persist(tb)
            self.ledger.update(row['id'], receipt['status'], reason=reason)
        text = ('Оплата СБП получена. Текущая подписка сохранена; напиши @vmeda_helper для проверки платежа.' if reason
                else f'✅ Подписка «{tb.SUBSCRIPTION_TIERS[row["tier_id"]]["title"]}» активирована. Доступ обновлён в боте и miniapp.')
        for target in {row['user_id'], *tb.ADMIN_IDS}:
            try:
                admin_text = f'{text}\nСБП codeePay · {row["amount_minor"] / 100:g} ₽\nПользователь: {row["user_id"]}\nПлатёж: {row["id"]}'
                await tb.bot.send_message(target, text if target == row['user_id'] else admin_text)
            except Exception:
                tb.logger.warning('Could not deliver SBP notification for order %s', row['id'])

    async def poll(self):
        async def check_one(row):
            try:
                await self.check(row)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.tb.logger.warning('SBP check will retry for order %s', row['id'])
                self.ledger.update(row['id'], self.ledger.get(row['id'])['state'], checked=time.time())
        while True:
            try:
                await asyncio.gather(*(check_one(row) for row in self.ledger.pending()))
            except asyncio.CancelledError:
                raise
            except Exception:
                self.tb.logger.warning('SBP ledger temporarily unavailable; verification will retry')
            await asyncio.sleep(15)


def start(tb):
    try:
        config = CodeePayConfig.from_env()
        if not config.enabled:
            return None
        config.validate_checkout_configuration()
        if os.environ.get('BOT_SYNC_MODE') != 'owner':
            raise ValueError('Billing requires the existing synchronized owner')
        path = os.path.join(tb.STATS_DIR, 'billing.sqlite3')
        ledger = BillingLedger(path)
        if ledger.backup_info:
            tb.logger.info('SBP_BILLING_BACKUP_VERIFIED orders=%d', ledger.backup_info['orders'])
        gateway = os.environ.get('CODEEPAY_CALLBACK_BASE_URL', '').rstrip('/')
        if not gateway.startswith('https://') or len(config.webhook_secret) < 32:
            raise ValueError('Callback HTTPS URL and secret are required')
        provider = CodeePayProvider(config, notification_url=gateway + '/api/v1/subscriptions/codeepay/webhook/' + config.webhook_secret)
        tb._billing_runtime = BillingRuntime(tb, ledger, provider)
        tb.logger.info('SBP_BILLING_READY separate_owner_ledger=true')
        return asyncio.create_task(tb._billing_runtime.poll(), name='vmeda-sbp-confirmation')
    except Exception:
        tb.logger.warning('SBP initialization unavailable; existing payments and polling remain active')
        return None
