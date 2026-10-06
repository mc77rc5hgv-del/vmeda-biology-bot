"""One authoritative view of profile, referrals, subscription and subject permissions."""
from __future__ import annotations

import os
from services.miniapp_testers import has_test_access

from fastapi import APIRouter, Depends

from ..deps import get_current_user_id, get_fresh_bot_module
from .access import SUBJECT_IDS, get_subject_access

router = APIRouter(prefix='/api/v1/sync', tags=['sync'])


@router.get('/state')
def sync_state(user_id: int = Depends(get_current_user_id), tb=Depends(get_fresh_bot_module)) -> dict:
    active = tb.has_active_subscription(user_id)
    sub = tb.get_subscription(user_id) if active else None
    return {
        'user_id': user_id,
        'tester_access': has_test_access(tb, user_id),
        'source': 'running_bot' if os.environ.get('BOT_SYNC_MODE') == 'owner' else 'legacy_local_file',
        'content_revision': os.environ.get('RAILWAY_GIT_COMMIT_SHA'),
        'subscription': {
            'active': active,
            'tier': sub.get('tier') if sub else None,
            'restricted_subject': sub.get('restricted_subject') if sub else None,
            'expires': sub.get('expires') if sub else None,
            'histology': tb.has_subscription_histology_access(user_id),
            'anatomy': tb.has_subscription_anatomy_access(user_id),
            'biology_download': tb.biology_tickets_download_ok(user_id),
        },
        'referrals': {
            'total': tb.get_referral_count(user_id),
            'this_month': tb.get_referral_count_this_month(user_id),
            'required_this_month': tb.REFERRAL_FULL_ACCESS_THRESHOLD,
        },
        'subjects': {subject: get_subject_access(subject, user_id, tb).model_dump() for subject in sorted(SUBJECT_IDS)},
        'anatomy_modules': {
            key: (not tb.anatomy_maintenance_mode_enabled() or tb.is_admin_or_assistant(user_id) or has_test_access(tb, user_id))
                 and (has_test_access(tb, user_id) or tb.anatomy_section_access_ok(user_id, key))
            for key in tb.ANATOMY
        },
        'chemistry_tickets': has_test_access(tb, user_id) or tb.chemistry_tickets_access_ok(user_id),
    }
