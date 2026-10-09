"""Shared launch policy. Public entry never bypasses subject entitlements."""
import os
from datetime import datetime, timezone

from services.miniapp_testers import has_test_access

PAID_SUBJECTS = frozenset({'biology', 'physics', 'chemistry', 'anatomy', 'histology'})


def public_launch():
    return os.environ.get('MINIAPP_ACCESS_MODE', 'admin_only').strip().lower() == 'public'


def promo_active(tb):
    return tb.stats.get('miniapp_public_promo', {}).get('active') is True


def full_content_access(tb, user_id):
    return promo_active(tb) or has_test_access(tb, user_id) or getattr(tb, 'is_admin_or_assistant', lambda _: False)(user_id)


def subscription_access(tb, user_id, subject):
    if not tb.has_active_subscription(user_id):
        return False
    if subject == 'histology':
        return tb.has_subscription_histology_access(user_id)
    if subject == 'anatomy':
        return tb.has_subscription_anatomy_access(user_id)
    sub = tb.get_subscription(user_id)
    return sub.get('restricted_subject') in (None, subject)


def subscription_required(tb, user_id, subject):
    return (public_launch() and subject in PAID_SUBJECTS
            and not full_content_access(tb, user_id)
            and not subscription_access(tb, user_id, subject))


def require_subject(tb, user_id, subject):
    if subscription_required(tb, user_id, subject):
        from fastapi import HTTPException
        raise HTTPException(403, 'Для этого предмета нужна соответствующая подписка.',
                            headers={'X-VMEDA-Subscription-Required': subject})


def set_promo(tb, admin_id, active):
    if not isinstance(active, bool):
        raise ValueError('Promo state must be boolean')
    if not tb.is_admin(admin_id):
        raise PermissionError('Only administrators can manage public promo')
    record = tb.stats.setdefault('miniapp_public_promo', {'active': False, 'history': []})
    if record.get('active') is not active:
        record.setdefault('history', []).append({'active': active, 'admin_id': admin_id,
                                               'at': datetime.now(timezone.utc).isoformat()})
        record['active'] = active
    return tb.save_stats()
