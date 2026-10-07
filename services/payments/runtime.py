"""Billing runs inside the existing bot owner; no second bot and no second stats writer."""
import asyncio
import copy
import hmac
import os
import secrets
import time

from .config import CodeePayConfig
from .contracts import CheckoutRejected, PaymentMismatch, PaymentOrder, PaymentStatus, ProviderNotReady, validate_confirmation
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
        self._create_gate = asyncio.Semaphore(4)
        self._checking = set()
        self.provider_healthy = True
        self.last_poll_at = 0

    async def fetch_provider(self, provider_id):
        try:
            payment = await self.provider.fetch_payment(provider_id)
        except Exception:
            self.provider_healthy = False
            raise
        self.provider_healthy = True
        return payment

    @staticmethod
    def order(row):
        return PaymentOrder(row['id'], row['user_id'], row['tier_id'], row['subject'], 'codeepay', row['amount_minor'], 'RUB', row['proof'])

    async def checkout(self, user_id, tier_id, subject, request_key, source):
        from web_api.subscriptions import purchase_reason, validate_tier
        # Reserve durably under the lock; never hold a global lock across provider I/O.
        async with self._create_lock:
            existing = self.ledger.existing(user_id, request_key)
            if existing:
                if existing['tier_id'] != tier_id or existing['subject'] != subject:
                    raise ValueError('Ключ запроса уже связан с другим тарифом')
                if existing['state'] == 'pending' and existing['url']:
                    return existing
                if existing['state'] == 'pending':
                    raise ProviderNotReady('Счёт найден у провайдера. Проверь статус или обратись в поддержку за ссылкой.')
                if existing['state'] in ('creating', 'creation_unknown'):
                    raise ProviderNotReady('Счёт требует сверки. Проверь историю или напиши @vmeda_helper. Повторно не оплачивай.')
                if existing['state'] != 'creation_rejected':
                    raise ValueError('Этот счёт завершён. Обнови историю и создай новый при необходимости.')
            cfg = validate_tier(self.tb, tier_id, subject)
            reason = purchase_reason(self.tb, user_id, tier_id, subject)
            if reason:
                raise ValueError(reason)
            if not self.provider.public_status()['available']:
                raise ProviderNotReady('СБП временно недоступна')
            for previous in self.ledger.history(user_id, limit=50):
                if previous['state'] == 'pending' and previous['tier_id'] == tier_id and previous['subject'] == subject and previous['created'] > time.time() - 900 and previous['url']:
                    return previous
            if self.ledger.uncertain_creation(user_id):
                raise ProviderNotReady('Предыдущий счёт требует сверки с codeePay. Напиши @vmeda_helper перед повторной оплатой.')
            price = cfg.get('price_rub')
            if type(price) is not int or price <= 0:
                raise ValueError('Нет рублёвой цены тарифа')
            if existing:
                if existing['amount_minor'] != price * 100:
                    raise ValueError('Цена изменилась. Создай новый счёт.')
                row = existing
                self.ledger.update(row['id'], 'creating', reason=None)
            else:
                row = self.ledger.create({'id': 'sbp_' + secrets.token_hex(16), 'user_id': user_id, 'request_key': request_key,
                     'tier_id': tier_id, 'subject': subject, 'amount_minor': price * 100, 'proof': secrets.token_hex(24),
                     'source': source, 'username': self.tb.stats.get('user_username', {}).get(str(user_id))})
        try:
            async with self._create_gate:
                session = await self.provider.create_checkout(self.order(row))
            self.provider_healthy = True
            async with self._lock:
                current = self.ledger.get(row['id'])
                if current['provider_id'] and current['provider_id'] != session.provider_payment_id:
                    raise PaymentMismatch('Different invoice recovered during creation')
                state = current['state'] if current['state'] in ('applied', 'review', 'resolved_keep', 'confirmed') else 'pending'
                self.ledger.update(row['id'], state, provider_id=session.provider_payment_id, url=session.checkout_url)
        except CheckoutRejected:
            self.provider_healthy = False
            self.ledger.update(row['id'], 'creation_rejected', reason='Провайдер отклонил создание без выпуска счёта. Можно повторить.')
            raise
        except BaseException:
            self.provider_healthy = False
            # Cancellation may also happen after the provider has issued an invoice.
            self.ledger.update(row['id'], 'creation_unknown', reason='Создание не подтверждено. Требуется сверка с codeePay, повторно не оплачивай.')
            raise
        return self.ledger.get(row['id'])

    def validate_binding(self, row, payment):
        if (payment.provider != 'codeepay' or payment.order_id != row['id']
                or payment.currency != 'RUB' or payment.amount_minor != row['amount_minor']
                or not hmac.compare_digest(str(payment.evidence.get('proof', '')).encode(), row['proof'].encode())):
            raise PaymentMismatch('Payment does not match the immutable quote')
        if row['provider_id'] and row['provider_id'] != payment.provider_payment_id:
            raise PaymentMismatch('Different provider invoice')

    async def recover_provider(self, provider_id, *, expected_order=None, actor=None, note=''):
        # User/callback supplied IDs are only hints. Fresh merchant-authenticated
        # metadata, proof, currency and amount must match an EXISTING local quote.
        async with self._poll_gate:
            payment = await self.fetch_provider(provider_id)
        if payment.provider_payment_id != provider_id:
            raise PaymentMismatch('Different provider invoice')
        row = self.ledger.get(payment.order_id)
        if not row or expected_order and row['id'] != expected_order:
            raise PaymentMismatch('Unknown or different merchant order')
        self.validate_binding(row, payment)
        async with self._lock:
            row = self.ledger.get(row['id'])
            self.validate_binding(row, payment)
            if not row['provider_id']:
                if row['state'] not in ('creating', 'creation_unknown', 'creation_closed'):
                    raise PaymentMismatch('Order cannot be rebound')
                self.ledger.update(row['id'], 'pending', provider_id=provider_id, reason=None)
                self.ledger.record_event(row['id'], 'provider_recovered', {'actor': actor, 'note': note, 'provider_id': provider_id})
        # Settle uses its own lock; no nested locks or duplicate grants.
        if payment.status is PaymentStatus.PAID:
            await self.settle(self.ledger.get(row['id']), payment)
        elif row['state'] not in ('applied', 'review', 'resolved_keep'):
            self.ledger.update(row['id'], payment.status.value, checked=time.time())
        return self.ledger.get(row['id'])

    async def reconcile(self, order_id, actor, action, *, provider_id=None, note=''):
        if not self.tb.is_admin(actor):
            raise PermissionError('Admin access required')
        if not isinstance(note, str) or not 10 <= len(note.strip()) <= 1000:
            raise ValueError('Укажи основание решения: от 10 до 1000 символов.')
        row = self.ledger.get(order_id)
        if not row:
            raise ValueError('Счёт не найден')
        if action == 'bind':
            if not isinstance(provider_id, str) or not 1 <= len(provider_id) <= 256:
                raise ValueError('Укажи ID счёта из кабинета codeePay')
            return await self.recover_provider(provider_id, expected_order=order_id, actor=actor, note=note)
        if action in ('apply_review', 'keep_existing'):
            if not row['provider_id']:
                raise ValueError('Сначала сверь счёт провайдера')
            async with self._poll_gate:
                payment = await self.fetch_provider(row['provider_id'])
            self.validate_binding(row, payment)
            validate_confirmation(self.order(row), payment, provider_payment_id=row['provider_id'])
            from web_api.subscriptions import _persist, grant_preserving_history, purchase_reason
            async with self._lock:
                row = self.ledger.get(order_id)
                receipt = self.tb.stats['processed_payment_charge_ids'].get('codeepay:' + payment.event_id)
                if not receipt or receipt.get('payment_id') != order_id:
                    raise ValueError('Нет подтверждённой квитанции для решения')
                target = 'applied' if action == 'apply_review' else 'resolved_keep'
                if receipt['status'] == target:
                    await _persist(self.tb)
                    self.ledger.update(order_id, target, resolve_review=True)
                    return self.ledger.get(order_id)
                if receipt['status'] != 'review':
                    raise ValueError('Счёт уже завершён другим решением')
                if action == 'apply_review':
                    reason = purchase_reason(self.tb, row['user_id'], row['tier_id'], row['subject'])
                    if reason:
                        raise ValueError('Безопасная выдача пока невозможна: ' + reason)
                    old = copy.deepcopy(self.tb.get_subscription(row['user_id']))
                    grant_preserving_history(self.tb, row['user_id'], row['tier_id'], row['subject'], 'admin_resolution', 0, old)
                    self.tb.stats['subscription_purchase_log'][-1].update(provider='codeepay', payment_id=order_id, source='admin_resolution', accounting='resolution_not_new_payment')
                resolution = {'actor': actor, 'action': action, 'note': note.strip(), 'at': time.time()}
                receipt.setdefault('resolution_history', []).append(resolution)
                receipt['status'] = target
                await _persist(self.tb)
                self.ledger.record_event(order_id, 'admin_resolution', resolution)
                self.ledger.update(order_id, target, resolve_review=True, reason=note.strip())
                return self.ledger.get(order_id)
        if action == 'close_not_created':
            # Explicit human reconciliation, NEVER automatic timeout expiry.
            # A delayed verified callback can still recover this historical quote.
            async with self._create_lock:
                row = self.ledger.get(order_id)
                if row['state'] != 'creation_unknown' or row['provider_id']:
                    raise ValueError('Закрыть можно только неизвестное создание без ID провайдера')
                self.ledger.record_event(order_id, 'admin_verified_no_invoice', {'actor': actor, 'note': note.strip(), 'at': time.time()})
                self.ledger.update(order_id, 'creation_closed', reason=note.strip())
            return self.ledger.get(order_id)
        raise ValueError('Неизвестное действие')

    async def check(self, row, *, force=False):
        if not row or not row['provider_id'] or row['state'] in ('applied', 'review', 'resolved_keep'):
            return row
        if row['id'] in self._checking or not force and row['checked'] > time.time() - 15:
            return self.ledger.get(row['id'])
        self._checking.add(row['id'])
        try:
            async with self._poll_gate:
                payment = await self.fetch_provider(row['provider_id'])
            self.validate_binding(row, payment)
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
        from html import escape
        from services.payment_notifications import buyer_label
        from web_api.subscriptions import _persist, grant_preserving_history, purchase_reason
        tb = self.tb
        async with self._lock:
            validate_confirmation(self.order(row), payment, provider_payment_id=row['provider_id'])
            self.validate_binding(row, payment)
            self.ledger.update(row['id'], 'confirmed', net_minor=payment.evidence['net_minor'],
                               fee_minor=payment.evidence['fee_minor'], charge_id=payment.event_id, checked=time.time())
            receipts = tb.stats.setdefault('processed_payment_charge_ids', {})
            charge_key = 'codeepay:' + payment.event_id
            previous = receipts.get(charge_key)
            if previous:
                if previous.get('payment_id') != row['id'] or previous.get('user_id') != row['user_id']:
                    raise PaymentMismatch('Charge already belongs to another order')
                await _persist(tb)  # recover a stats-write/ledger-write crash without regranting
                self.ledger.update(row['id'], previous['status'], resolve_review=previous['status'] in ('applied', 'resolved_keep'), reason=previous.get('reason'))
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
                admin_text = f'{escape(text)}\nСБП codeePay · {row["amount_minor"] / 100:g} ₽\nПользователь: {buyer_label(tb, row["user_id"], row.get("username"))}\nПлатёж: <code>{escape(row["id"])}</code>'
                if target == row['user_id']:
                    await tb.bot.send_message(target, text)
                else:
                    await tb.bot.send_message(target, admin_text, parse_mode='HTML')
            except Exception:
                tb.logger.warning('Could not deliver SBP notification for order %s', row['id'])

    async def poll(self):
        last_probe = 0
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
                self.last_poll_at = time.time()
                # Read-only status probe: never creates an invoice or bank charge.
                # Settled historical orders also keep provider health observable.
                if time.time() - last_probe >= 60:
                    sample = next((r for r in self.ledger.history(limit=50) if r['provider_id']), None)
                    try:
                        if sample:
                            async with self._poll_gate:
                                payment = await self.fetch_provider(sample['provider_id'])
                            self.validate_binding(sample, payment)
                    except Exception:
                        self.provider_healthy = False
                        self.tb.logger.warning('SBP provider readiness probe failed; pending verification continues')
                    last_probe = time.time()
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
        ledger.recover_interrupted_creation()
        if ledger.backup_info:
            tb.logger.info('SBP_BILLING_BACKUP_VERIFIED orders=%d', ledger.backup_info['orders'])
        gateway = os.environ.get('CODEEPAY_CALLBACK_BASE_URL', '').rstrip('/')
        if not gateway.startswith('https://') or len(config.webhook_secret) < 32:
            raise ValueError('Callback HTTPS URL and secret are required')
        provider = CodeePayProvider(config, notification_url=gateway + '/api/v1/subscriptions/codeepay/webhook/' + config.webhook_secret)
        tb._billing_runtime = BillingRuntime(tb, ledger, provider)
        tb.logger.info('SBP_BILLING_READY separate_owner_ledger=true')
        task = asyncio.create_task(tb._billing_runtime.poll(), name='vmeda-sbp-confirmation')
        tb._billing_runtime.poll_task = task
        return task
    except Exception:
        tb.logger.warning('SBP initialization unavailable; existing payments and polling remain active')
        return None
