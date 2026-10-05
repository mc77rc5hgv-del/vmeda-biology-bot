"""Official https://codeepay.ru/openapi.json API. Webhooks are hints, never proof."""
import json
from decimal import Decimal, InvalidOperation
from typing import Mapping
from urllib.parse import urlsplit

import httpx

from ..config import CodeePayConfig
from ..contracts import CheckoutSession, PaymentMismatch, PaymentOrder, PaymentStatus, ProviderNotReady, VerifiedPayment


def minor(value) -> int:
    if isinstance(value, bool):
        raise PaymentMismatch('Invalid amount')
    try:
        amount = Decimal(str(value)) * 100
        if not amount.is_finite() or amount < 0 or amount != amount.to_integral_value():
            raise ValueError()
        return int(amount)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise PaymentMismatch('Invalid amount') from exc


class CodeePayProvider:
    name = 'codeepay'

    def __init__(self, config: CodeePayConfig, *, transport=None, notification_url='', return_url='https://t.me/VMEDA_examen_bot'):
        self.config, self.transport = config, transport
        self.notification_url, self.return_url = notification_url, return_url

    def public_status(self) -> dict:
        try:
            self.config.validate_checkout_configuration()
        except ValueError:
            return {'provider': self.name, 'available': False, 'reason': 'not_configured'}
        return {'provider': self.name, 'available': True, 'reason': None}

    async def _post(self, path, data):
        if not self.public_status()['available']:
            raise ProviderNotReady('СБП временно недоступна. Можно оплатить Stars или переводом на карту.')
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds, transport=self.transport, follow_redirects=False) as client:
                response = await client.post(self.config.api_url.rstrip('/') + path,
                                             headers={'X-Api-Key': self.config.api_key}, json=data)
                if response.status_code != 200:
                    # Do not expose provider bodies, URLs, API headers or exception request objects.
                    raise ProviderNotReady('codeePay не принял запрос. Попробуй позже или обратись в поддержку.')
                value = json.loads(response.content, parse_float=Decimal)
                if not isinstance(value, dict):
                    raise ValueError()
                return value
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderNotReady('Нет подтверждения codeePay. Платёж продолжит проверяться автоматически.') from exc

    async def create_checkout(self, order: PaymentOrder) -> CheckoutSession:
        if order.currency != 'RUB' or order.provider != self.name:
            raise PaymentMismatch('Unsupported currency or provider')
        metadata = {'vmeda_order': order.order_id, 'vmeda_proof': order.idempotency_key}
        if self.notification_url:
            metadata['notification_url'] = self.notification_url
        data = await self._post('/initiate_payment', {'method_slug': 'sbp', 'amount': order.amount_minor / 100,
                 'description': f'VMEDA: подписка {order.tier_id}', 'shop_name': 'VMEDA',
                 'shop_url': 'https://t.me/VMEDA_examen_bot', 'success_url': self.return_url,
                 'failure_url': self.return_url, 'metadata': metadata})
        url = urlsplit(data.get('url', ''))
        if (url.scheme != 'https' or url.hostname not in {'codeepay.ru', 'payment.codeepay.xyz'} or url.username or url.password
                or not url.path.startswith(('/payment/', '/transfer/')) or minor(data.get('amount')) != order.amount_minor
                or not isinstance(data.get('order_id'), str) or not data['order_id']):
            raise PaymentMismatch('Invalid checkout response')
        return CheckoutSession(order.order_id, data['order_id'], data['url'])

    async def fetch_payment(self, provider_payment_id: str) -> VerifiedPayment:
        data = await self._post('/get_payment', {'order_id': provider_payment_id})
        if data.get('payment_order_id') != provider_payment_id or data.get('payment_method') != 'sbp':
            raise PaymentMismatch('Different order or payment method')
        metadata = data.get('payment_metadata')
        if not isinstance(metadata, dict) or not isinstance(metadata.get('vmeda_order'), str):
            raise PaymentMismatch('Missing merchant order binding')
        amount = minor(data.get('payment_amount'))
        net, fee = minor(data.get('payment_deposited_amount')), minor(data.get('payment_commission_amount'))
        # Deposited is the official financial settlement flag. A browser SUCCESS is not enough.
        deposited = data.get('payment_deposited')
        if type(deposited) is not bool or not isinstance(data.get('payment_status'), str):
            raise PaymentMismatch('Invalid payment status')
        if deposited and (not data.get('payment_id') or net + fee != amount):
            raise PaymentMismatch('Invalid settlement totals')
        status = PaymentStatus.PAID if deposited else PaymentStatus.PENDING
        if not deposited and data['payment_status'].lower() in {'failed', 'fail', 'error'}:
            status = PaymentStatus.FAILED
        elif not deposited and data['payment_status'].lower() in {'cancelled', 'canceled', 'expired'}:
            status = PaymentStatus.CANCELLED
        return VerifiedPayment(self.name, str(data.get('payment_id') or provider_payment_id), provider_payment_id,
                 metadata['vmeda_order'], amount, 'RUB', status,
                 {'proof': metadata.get('vmeda_proof', ''), 'net_minor': net, 'fee_minor': fee,
                  'provider_status': data['payment_status'], 'charge_id': str(data.get('payment_id') or '')})

    async def verify_webhook(self, body: bytes, headers: Mapping[str, str]) -> VerifiedPayment:
        # Official API has no signature. Only a merchant-authenticated fresh query is proof.
        if len(body) > 16384:
            raise PaymentMismatch('Webhook too large')
        try:
            data = json.loads(body)
            order_id = data['order_id']
            if not isinstance(order_id, str) or not order_id or len(order_id) > 256:
                raise ValueError()
        except (ValueError, KeyError, TypeError) as exc:
            raise PaymentMismatch('Invalid webhook') from exc
        return await self.fetch_payment(order_id)
