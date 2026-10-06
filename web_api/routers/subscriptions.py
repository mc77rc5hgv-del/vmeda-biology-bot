"""Authenticated subscription storefront. Invoices do not grant access."""
import re

from services.miniapp_testers import has_test_access

from aiogram.exceptions import TelegramAPIError
from aiogram.types import LabeledPrice
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictInt

from ..deps import get_current_user_id, get_fresh_bot_module
from ..subscriptions import SUBJECTS, iso, make_payload, payment_receipt, purchase_reason, validate_tier
from .access import get_subject_access
from .subjects import list_subjects

router = APIRouter(prefix='/api/v1/subscriptions', tags=['subscriptions'])


class InvoiceRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tier_id: StrictInt
    subject: str | None = None


def _catalog(tb, user_id):
    from services.payments.runtime import available
    plans = []
    for tier_id, cfg in tb.access.sorted_active_tiers():
        try:
            validate_tier(tb, tier_id, None, require_subject=False)
        except ValueError:
            continue
        choices = [{'id': key, 'title': title, 'unavailable_reason': purchase_reason(tb, user_id, tier_id, key)}
                   for key, title in SUBJECTS.items()] if cfg.get('subject_choice_required') else []
        reason = purchase_reason(tb, user_id, tier_id, None) if not choices else (
            None if any(not choice['unavailable_reason'] for choice in choices) else choices[0]['unavailable_reason'])
        plans.append({'id': tier_id, 'title': cfg['title'], 'short': cfg['short'], 'price_stars': cfg['price_stars'], 'price_rub': cfg['price_rub'],
                      'duration_days': cfg.get('duration_days'), 'expires_at': iso(cfg.get('expires_at')),
                      'benefits': cfg.get('benefits', []), 'badge': cfg.get('badge'),
                      'ai_limit': cfg.get('ai_limit'), 'ai_period': cfg.get('ai_limit_type'),
                      'courses': [course for course, name in [(1, 'year1'), (2, 'year2')] if tier_id in tb._course_tier_ids(name)],
                      'subject_options': choices, 'unavailable_reason': reason, 'card_transfer_url': tb.get_sub_rubles_keyboard(tier_id).inline_keyboard[0][0].url})
    active = tb.has_active_subscription(user_id)
    sub = tb.get_subscription(user_id) if active else None
    cfg = tb.SUBSCRIPTION_TIERS.get(sub.get('tier'), {}) if sub else {}
    unlimited = has_test_access(tb, user_id) or tb.has_unlimited_ai(user_id)
    limit_type, limit = tb._sub_ai_plan(user_id)
    return {'plans': plans, 'sbp_available': available(tb), 'current': {'active': active, 'tier_id': sub.get('tier') if sub else None,
            'title': cfg.get('title'), 'expires_at': iso(sub.get('expires')) if sub else None,
            'restricted_subject': sub.get('restricted_subject') if sub else None,
            'benefits': cfg.get('benefits', []), 'ai_remaining': None if unlimited else tb.ai_requests_left(user_id),
            'ai_limit': limit, 'ai_period': limit_type,
            'access': [{'id': key, 'title': title, 'available': get_subject_access(key, user_id, tb).can_open_subject}
                       for key, title in ((s['id'], s['title']) for s in list_subjects(user_id, tb))]}}


@router.get('/catalog')
async def catalog(user_id: int = Depends(get_current_user_id), tb=Depends(get_fresh_bot_module)):
    return _catalog(tb, user_id)


@router.post('/invoice')
async def invoice(body: InvoiceRequest, user_id: int = Depends(get_current_user_id), tb=Depends(get_fresh_bot_module)):
    try:
        cfg = validate_tier(tb, body.tier_id, body.subject)
        reason = purchase_reason(tb, user_id, body.tier_id, body.subject)
        if reason:
            raise ValueError(reason)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    payload, payment_id = make_payload(tb, user_id, body.tier_id, body.subject)
    subject_line = f' — {SUBJECTS[body.subject]}' if body.subject else ''
    try:
        url = await tb.bot.create_invoice_link(title=cfg['short'][:32],
                description=(f'VMEDA: {cfg["title"]}{subject_line}. Доступ откроется после подтверждения оплаты Telegram.')[:255],
                payload=payload, provider_token='', currency='XTR',
                prices=[LabeledPrice(label=cfg['short'], amount=cfg['price_stars'])])
    except TelegramAPIError as exc:
        raise HTTPException(status_code=503, detail='Не удалось создать счёт Telegram. Попробуй ещё раз.') from exc
    return {'url': url, 'payment_id': payment_id, 'price_stars': cfg['price_stars'], 'price_rub': cfg['price_rub'], 'tier_id': body.tier_id}


@router.get('/payments/{payment_id}')
async def payment(payment_id: str, user_id: int = Depends(get_current_user_id), tb=Depends(get_fresh_bot_module)):
    if re.fullmatch(r'sbp_[a-f0-9]{32}', payment_id):
        from services.payments.runtime import runtime
        service = runtime(tb)
        row = service.ledger.get(payment_id) if service else None
        if not row or row['user_id'] != user_id:
            raise HTTPException(status_code=404, detail='Платёж не найден')
        return {'status': row['state'] if row['state'] in ('applied', 'review', 'failed', 'cancelled') else 'processing', 'tier_id': row['tier_id']}
    if not re.fullmatch(r'[a-f0-9]{12}', payment_id):
        raise HTTPException(status_code=404, detail='Платёж не найден')
    receipt = payment_receipt(tb, user_id, payment_id)
    return {'status': receipt['status'] if receipt else 'processing',
            'tier_id': receipt.get('tier') if receipt else None}


class SbpRequest(InvoiceRequest):
    request_key: str


@router.post('/sbp')
async def sbp(body: SbpRequest, user_id: int = Depends(get_current_user_id), tb=Depends(get_fresh_bot_module)):
    from services.payments.contracts import ProviderNotReady, PaymentMismatch
    from services.payments.runtime import runtime
    service = runtime(tb)
    if not service:
        raise HTTPException(503, detail='СБП временно недоступна. Можно оплатить Stars или переводом на карту.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', body.request_key):
        raise HTTPException(422, detail='Некорректный ключ запроса')
    try:
        row = await service.checkout(user_id, body.tier_id, body.subject, body.request_key, 'miniapp')
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    except (ProviderNotReady, PaymentMismatch) as exc:
        raise HTTPException(503, detail='Не удалось подтвердить создание счёта. Проверь историю платежей или напиши @vmeda_helper.') from exc
    return {'url': row['url'], 'payment_id': row['id'], 'price_rub': row['amount_minor'] // 100, 'tier_id': row['tier_id']}


@router.get('/history')
async def history(user_id: int = Depends(get_current_user_id), tb=Depends(get_fresh_bot_module)):
    from services.payments.runtime import runtime
    service = runtime(tb)
    return {'payments': [service.ledger.public(row) for row in service.ledger.history(user_id)] if service else []}


@router.get('/admin/sbp')
async def sbp_statistics(offset: int = 0, user_id: int = Depends(get_current_user_id), tb=Depends(get_fresh_bot_module)):
    from services.payments.runtime import runtime
    if not tb.is_admin(user_id):
        raise HTTPException(403, detail='Нет доступа')
    service = runtime(tb)
    if not service:
        return {'summary': [], 'payments': []}
    return {'summary': service.ledger.summary(), 'payments': [{**service.ledger.public(row),
            'user_id': row['user_id'], 'username': row['username'], 'provider_id': row['provider_id'], 'charge_id': row['charge_id']}
            for row in service.ledger.history(limit=50, offset=max(0, offset))]}


@router.post('/codeepay/webhook/{secret}')
async def codeepay_webhook(secret: str, request: Request, tb=Depends(get_fresh_bot_module)):
    import hmac
    import json
    from services.payments.runtime import runtime
    from services.payments.contracts import ProviderNotReady, PaymentMismatch
    service = runtime(tb)
    if not service or not hmac.compare_digest(secret, service.provider.config.webhook_secret):
        raise HTTPException(404, detail='Не найдено')
    body = await request.body()
    if len(body) > 16384:
        raise HTTPException(413, detail='Запрос слишком большой')
    try:
        data = json.loads(body)
        provider_id = data['order_id']
        if not isinstance(provider_id, str) or len(provider_id) > 256:
            raise ValueError()
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(400, detail='Некорректное уведомление') from exc
    row = service.ledger.by_provider(provider_id)
    if row:
        try:
            await service.check(row, force=True)
        except ProviderNotReady as exc:
            raise HTTPException(503, detail='Повтори уведомление') from exc
        except PaymentMismatch as exc:
            raise HTTPException(409, detail='Платёж не соответствует счёту') from exc
    # Unknown orders cannot be registered or granted by a callback. Provider retries safely.
    return {'ok': True}
