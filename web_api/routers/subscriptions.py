"""Authenticated subscription storefront. Invoices do not grant access."""
import re

from aiogram.exceptions import TelegramAPIError
from aiogram.types import LabeledPrice
from fastapi import APIRouter, Depends, HTTPException
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
        plans.append({'id': tier_id, 'title': cfg['title'], 'short': cfg['short'], 'price_stars': cfg['price_stars'],
                      'duration_days': cfg.get('duration_days'), 'expires_at': iso(cfg.get('expires_at')),
                      'benefits': cfg.get('benefits', []), 'badge': cfg.get('badge'),
                      'ai_limit': cfg.get('ai_limit'), 'ai_period': cfg.get('ai_limit_type'),
                      'courses': [course for course, name in [(1, 'year1'), (2, 'year2')] if tier_id in tb._course_tier_ids(name)],
                      'subject_options': choices, 'unavailable_reason': reason})
    active = tb.has_active_subscription(user_id)
    sub = tb.get_subscription(user_id) if active else None
    cfg = tb.SUBSCRIPTION_TIERS.get(sub.get('tier'), {}) if sub else {}
    unlimited = tb.has_unlimited_ai(user_id)
    limit_type, limit = tb._sub_ai_plan(user_id)
    return {'plans': plans, 'current': {'active': active, 'tier_id': sub.get('tier') if sub else None,
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
    return {'url': url, 'payment_id': payment_id, 'price_stars': cfg['price_stars'], 'tier_id': body.tier_id}


@router.get('/payments/{payment_id}')
async def payment(payment_id: str, user_id: int = Depends(get_current_user_id), tb=Depends(get_fresh_bot_module)):
    if not re.fullmatch(r'[a-f0-9]{12}', payment_id):
        raise HTTPException(status_code=404, detail='Платёж не найден')
    receipt = payment_receipt(tb, user_id, payment_id)
    return {'status': receipt['status'] if receipt else 'processing',
            'tier_id': receipt.get('tier') if receipt else None}
