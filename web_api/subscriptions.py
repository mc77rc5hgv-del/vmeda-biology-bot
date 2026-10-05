"""Stars invoices and additive receipts, handled by the existing bot owner only."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timezone

PREFIX = 'vmeda-miniapp:'
SUBJECTS = {'biology': 'Биология', 'physics': 'Физика', 'chemistry': 'Химия'}
_pending_checkouts: dict[int, tuple[str, float]] = {}


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


def _signature(tb, body: str) -> str:
    return hmac.new(tb.BOT_TOKEN.encode(), body.encode(), hashlib.sha256).hexdigest()[:24]


def make_payload(tb, user_id: int, tier_id: int, subject: str | None) -> tuple[str, str]:
    payment_id = secrets.token_hex(6)
    body = f'{user_id}:{tier_id}:{subject or "-"}:{tb.SUBSCRIPTION_TIERS[tier_id]["price_stars"]}:{int(time.time())}:{payment_id}'
    return PREFIX + body + ':' + _signature(tb, body), payment_id


def parse_payload(tb, payload: str) -> dict:
    if not payload.startswith(PREFIX):
        raise ValueError('Некорректный счёт')
    fields = payload[len(PREFIX):].split(':')
    if len(fields) != 7:
        raise ValueError('Некорректный счёт')
    uid, tier, subject, amount, issued, payment_id, signature = fields
    if not hmac.compare_digest(signature, _signature(tb, ':'.join(fields[:-1]))):
        raise ValueError('Некорректная подпись счёта')
    if len(payment_id) != 12 or any(c not in '0123456789abcdef' for c in payment_id):
        raise ValueError('Некорректный счёт')
    result = {'user_id': int(uid), 'tier_id': int(tier), 'subject': None if subject == '-' else subject,
              'amount': int(amount), 'issued': int(issued), 'payment_id': payment_id}
    if result['user_id'] <= 0 or result['amount'] <= 0:
        raise ValueError('Некорректный счёт')
    return result


def validate_tier(tb, tier_id: int, subject: str | None, *, require_subject=True) -> dict:
    cfg = tb.ACTIVE_SUBSCRIPTION_TIERS.get(tier_id)
    if not cfg or cfg.get('price_stars', 0) <= 0:
        raise ValueError('Тариф больше не продаётся')
    if cfg.get('expires_at') is not None and cfg['expires_at'] <= time.time():
        raise ValueError('Срок этого тарифа уже закончился')
    if cfg.get('subject_choice_required'):
        if require_subject and subject not in SUBJECTS:
            raise ValueError('Выбери биологию, физику или химию')
    elif subject is not None:
        raise ValueError('Этот тариф не требует выбора предмета')
    return cfg


def purchase_reason(tb, user_id: int, tier_id: int, subject: str | None) -> str | None:
    cfg = validate_tier(tb, tier_id, subject, require_subject=False)
    current = tb.get_subscription(user_id)
    if not current or not tb.has_active_subscription(user_id):
        return None
    same = current.get('tier') == tier_id and current.get('restricted_subject') == subject
    renewal = bool(same and cfg.get('duration_days'))
    if renewal and current.get('expires') is None:
        return 'Текущая подписка уже бессрочная'
    if same and not renewal:
        return 'Этот тариф уже активен'
    old_end = current.get('expires')
    new_end = cfg.get('expires_at')
    if new_end is None and cfg.get('duration_days'):
        new_end = max(current.get('expires') or 0, time.time()) + cfg['duration_days'] * 86400 if renewal else time.time() + cfg['duration_days'] * 86400
    if old_end is None and new_end is not None or old_end is not None and new_end is not None and new_end < old_end:
        return 'Этот тариф сократит уже оплаченный срок'
    old_subjects = {current['restricted_subject']} if current.get('restricted_subject') else set(SUBJECTS)
    new_subjects = {subject} if cfg.get('subject_choice_required') else set(SUBJECTS)
    if not old_subjects <= new_subjects:
        return 'Этот тариф уменьшит доступ к предметам'
    old_cfg = tb.SUBSCRIPTION_TIERS.get(current.get('tier'), {})
    for name in ('anatomy', 'biology_download', 'cheat_sheets', 'future_second_year_sections'):
        old = current.get(name, current.get('scope') == 'all' or old_cfg.get(name, False))
        if old and not cfg.get(name):
            return 'Этот тариф уменьшит возможности текущей подписки'
    if tb.has_subscription_histology_access(user_id) and not cfg.get('histology_until_rule'):
        return 'Этот тариф не включает действующий доступ к гистологии'
    old_type, old_limit = tb._sub_ai_plan(user_id)
    new_type, new_limit = cfg.get('ai_limit_type'), cfg.get('ai_limit', 0)
    if old_type == 'monthly' and (new_type != 'monthly' or new_limit < old_limit):
        return 'Этот тариф уменьшит ежемесячный лимит AI'
    new_remaining = new_limit
    if renewal and new_type == 'period':
        new_remaining += tb.sub_ai_requests_left(user_id) or 0
    if new_type == 'monthly':
        new_remaining -= tb._get_sub_ai_used(current, 'monthly')
    if old_type == 'period' and new_remaining < (tb.sub_ai_requests_left(user_id) or 0):
        return 'Этот тариф уменьшит оставшийся оплаченный лимит AI'
    return None


def payment_receipt(tb, user_id: int, payment_id: str):
    return next((r for r in tb.stats.get('processed_payment_charge_ids', {}).values()
                 if r.get('user_id') == user_id and r.get('payment_id') == payment_id), None)


async def pre_checkout(tb, query):
    try:
        data = parse_payload(tb, query.invoice_payload)
        if data['user_id'] != query.from_user.id:
            raise ValueError('Счёт предназначен другому пользователю')
        age = time.time() - data['issued']
        if age < -30 or age > 15 * 60:
            raise ValueError('Счёт устарел — открой подписки и создай новый')
        cfg = validate_tier(tb, data['tier_id'], data['subject'])
        if query.currency != 'XTR' or query.total_amount != data['amount'] or data['amount'] != cfg['price_stars']:
            raise ValueError('Цена изменилась — создай новый счёт')
        if payment_receipt(tb, query.from_user.id, data['payment_id']):
            raise ValueError('Этот счёт уже оплачен')
        reason = purchase_reason(tb, query.from_user.id, data['tier_id'], data['subject'])
        if reason:
            raise ValueError(reason)
        pending = _pending_checkouts.get(query.from_user.id)
        if pending and pending[1] > time.time() and pending[0] != query.id:
            raise ValueError('Другой платёж ещё обрабатывается. Повтори через минуту')
        _pending_checkouts[query.from_user.id] = (query.id, time.time() + 90)
    except (ValueError, TypeError, KeyError) as exc:
        await query.answer(ok=False, error_message=str(exc))
        return
    await query.answer(ok=True)



async def _persist(tb):
    # A transient volume-write failure must not drop a confirmed paid update.
    for attempt in range(3):
        try:
            await asyncio.wrap_future(tb.save_stats())
            return
        except OSError:
            if attempt == 2:
                raise
            tb.logger.exception('Retrying miniapp payment snapshot')
            await asyncio.sleep(0.2 * (attempt + 1))


async def successful_payment(tb, message):
    payment = message.successful_payment
    charge_id = payment.telegram_payment_charge_id
    if not charge_id:
        raise ValueError('Telegram payment has no charge id')
    if charge_id in tb.stats['processed_payment_charge_ids']:
        await _persist(tb)  # Retry a failed disk write without granting twice.
        return
    data = parse_payload(tb, payment.invoice_payload)
    if data['user_id'] != message.from_user.id or payment.currency != 'XTR' or payment.total_amount != data['amount']:
        raise ValueError('Telegram payment does not match its signed invoice')
    old = copy.deepcopy(tb.get_subscription(message.from_user.id))
    receipt = {'user_id': message.from_user.id, 'stars': payment.total_amount, 'payload': payment.invoice_payload,
               'at': time.time(), 'payment_id': data['payment_id'], 'tier': data['tier_id'],
               'source': 'miniapp', 'previous_subscription': old}
    try:
        reason = purchase_reason(tb, message.from_user.id, data['tier_id'], data['subject'])
    except ValueError as exc:
        reason = str(exc)
    if payment_receipt(tb, message.from_user.id, data['payment_id']):
        reason = 'Повторная оплата одного счёта'
    receipt['status'] = 'review' if reason else 'applied'
    if reason:
        receipt['reason'] = reason
        tb.stats['subscription_purchase_log'].append({'user_id': message.from_user.id, 'tier': data['tier_id'],
                'method': 'stars', 'price': payment.total_amount, 'ts': time.time(), 'status': 'review'})
    else:
        cfg = tb.SUBSCRIPTION_TIERS[data['tier_id']]
        active = bool(old and tb.has_active_subscription(message.from_user.id))
        tb.grant_subscription(message.from_user.id, data['tier_id'], 'stars', payment.total_amount,
                              data['subject'], persist=False)
        granted = tb.get_subscription(message.from_user.id)
        merged = {**(old or {}), **granted}
        if active and old.get('tier') == data['tier_id'] and cfg.get('duration_days'):
            merged['expires'] = max(old['expires'] or time.time(), time.time()) + cfg['duration_days'] * 86400
            if cfg.get('ai_limit_type') == 'period':
                merged['miniapp_ai_bonus'] = old.get('miniapp_ai_bonus', 0) + cfg['ai_limit']
        elif not active or tb.SUBSCRIPTION_TIERS.get((old or {}).get('tier'), {}).get('ai_limit_type') != 'period':
            merged['miniapp_ai_period_start'] = (old or {}).get('ai_used_period', 0)
            merged['miniapp_ai_bonus'] = 0
        else:
            merged['miniapp_ai_period_start'] = (old or {}).get('ai_used_period', 0)
            merged['miniapp_ai_bonus'] = 0
        tb.stats['subscriptions'][str(message.from_user.id)] = merged
    tb.stats['processed_payment_charge_ids'][charge_id] = receipt
    await _persist(tb)  # Single atomic snapshot: entitlement, receipt and purchase history.
    _pending_checkouts.pop(message.from_user.id, None)
    text = 'Оплата получена. Текущая подписка сохранена; напиши @vmeda_helper для проверки платежа.' if reason else (
        f'Подписка «{tb.SUBSCRIPTION_TIERS[data["tier_id"]]["title"]}» активирована. Доступ обновлён в боте и miniapp.'
    )
    for target in {message.from_user.id, *tb.ADMIN_IDS}:
        try:
            await tb.bot.send_message(target, text if target == message.from_user.id else f'{text}\nПользователь: {message.from_user.id}\nПлатёж: {data["payment_id"]}\nСумма: {payment.total_amount} Stars')
        except Exception:
            tb.logger.exception('Could not deliver miniapp payment notification')
