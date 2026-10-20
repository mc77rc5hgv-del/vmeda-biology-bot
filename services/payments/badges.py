"""Physical badge purchases: immutable pricing, separate receipts, durable notifications."""
import html
import time

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.badge_orders import RECIPIENT_ID, customer_url, helper_url, order_template, price_quote, validated_details
from .contracts import PaymentMismatch, validate_confirmation


def checkout_quote(tb, user_id, token):
    order = tb.stats.get('badge_orders', {}).get(token)
    if not order or order['user_id'] != user_id:
        raise ValueError('Заказ не найден')
    if order.get('payment', {}).get('status') == 'paid':
        raise ValueError('Заказ уже оплачен. Повторно платить не нужно.')
    details = validated_details(order['details'])
    quote = order.get('pricing')
    if not quote or quote != price_quote(details['quantity']):
        raise ValueError('Сначала проверь и подтверди стоимость заказа')
    return quote


def settlement_order(tb, row):
    order = tb.stats.get('badge_orders', {}).get(row['subject'])
    if not order or order['user_id'] != row['user_id']:
        raise ValueError('Не найден исходный заказ бейджиков. Требуется проверка поддержки.')
    details = validated_details(order['details'])
    pricing = order.get('pricing')
    if (not pricing or pricing != price_quote(details['quantity'])
            or pricing['total_rub'] * 100 != row['amount_minor']):
        raise ValueError('Заказ не соответствует зафиксированной стоимости. Требуется проверка поддержки.')
    current = order.get('payment', {})
    if current.get('status') == 'paid' and current.get('id') != row['id']:
        raise ValueError('Заказ уже оплачен другим платежом. Требуется проверка поддержки.')
    return order


async def settle_badge(service, row, payment, *, resolution=None):
    from web_api.subscriptions import _persist
    tb = service.tb
    async with service._lock:
        validate_confirmation(service.order(row), payment, provider_payment_id=row['provider_id'])
        service.validate_binding(row, payment)
        receipts = tb.stats.setdefault('processed_payment_charge_ids', {})
        key = 'codeepay:' + payment.event_id
        previous = receipts.get(key)
        if previous and (previous.get('payment_id') != row['id'] or previous.get('user_id') != row['user_id']):
            raise PaymentMismatch('Charge already belongs to another order')
        if previous and previous['status'] in ('applied', 'resolved_keep'):
            await _persist(tb)
            service.ledger.update(row['id'], previous['status'], resolve_review=True)
        else:
            service.ledger.update(row['id'], 'confirmed', net_minor=payment.evidence['net_minor'],
                                  fee_minor=payment.evidence['fee_minor'], charge_id=payment.event_id, checked=time.time())
            try:
                order = settlement_order(tb, row)
            except ValueError as exc:
                order, reason = None, str(exc)
            else:
                reason = previous.get('reason') if previous and previous['status'] == 'review' and not resolution else None
            if resolution and reason:
                raise ValueError(reason)
            receipt = previous or {
                'user_id': row['user_id'], 'payment_id': row['id'], 'provider': 'codeepay',
                'kind': 'badge', 'badge_order_id': row['subject'], 'amount_minor': row['amount_minor'],
                'currency': 'RUB', 'at': time.time(), 'source': row['source'],
            }
            receipt.update(status='review' if reason else 'applied', reason=reason,
                           net_minor=payment.evidence['net_minor'], fee_minor=payment.evidence['fee_minor'])
            if resolution:
                receipt.setdefault('resolution_history', []).append(resolution)
            if not reason:
                order['payment'] = {'id': row['id'], 'status': 'paid', 'provider': 'codeepay',
                                    'amount_minor': row['amount_minor'], 'net_minor': payment.evidence['net_minor'],
                                    'fee_minor': payment.evidence['fee_minor'], 'paid_at': receipt['at']}
                targets = {row['user_id'], RECIPIENT_ID, *tb.ADMIN_IDS}
                order.setdefault('payment_notifications', {str(target): 'pending' for target in targets})
            receipts[key] = receipt
            await _persist(tb)
            if resolution:
                service.ledger.record_event(row['id'], 'admin_resolution', resolution)
            service.ledger.update(row['id'], receipt['status'], resolve_review=bool(resolution), reason=reason)
    await flush_notifications(service)


async def flush_notifications(service):
    """Retry pending work after restarts; never resend an ambiguous Telegram delivery."""
    from web_api.subscriptions import _persist
    from services.payment_notifications import buyer_label
    tb = service.tb
    async with service._badge_notice_lock:
        orders = [order for order in tb.stats.get('badge_orders', {}).values()
                  if order.get('payment', {}).get('status') == 'paid'
                  and any(state in ('pending', 'sending') for state in order.get('payment_notifications', {}).values())]
        for order in orders[:50]:
            states = order['payment_notifications']
            for target, state in list(states.items()):
                if state == 'sending':
                    states[target] = 'unknown'
                    await _persist(tb)
                    continue
                if state != 'pending':
                    continue
                states[target] = 'sending'
                try:
                    await _persist(tb)
                except Exception:
                    states[target] = 'pending'
                    raise
                if int(target) == order['user_id']:
                    text = html.escape('✅ Оплата бейджиков подтверждена.\n\n' + order_template(order))
                else:
                    text = (html.escape('✅ ОПЛАЧЕННЫЙ ЗАКАЗ БЕЙДЖИКОВ\n\n' + order_template(order))
                            + '\nПользователь: ' + buyer_label(tb, order['user_id'], order.get('username')))
                builder = InlineKeyboardBuilder()
                customer = int(target) == order['user_id']
                builder.row(InlineKeyboardButton(text='💬 Связаться с @vmeda_helper' if customer else '💬 Написать заказчику',
                                                 url=helper_url(order) if customer else customer_url(order)))
                try:
                    await tb.bot.send_message(int(target), text, parse_mode='HTML', reply_markup=builder.as_markup())
                except (TelegramBadRequest, TelegramForbiddenError):
                    states[target] = 'failed'
                    tb.logger.warning('Badge paid notification rejected for order %s', order['id'])
                except Exception:
                    states[target] = 'unknown'
                    tb.logger.warning('Badge paid notification uncertain for order %s', order['id'])
                else:
                    states[target] = 'sent'
                await _persist(tb)
