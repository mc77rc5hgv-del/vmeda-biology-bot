"""Shared content admission; only explicit visits consume warnings or start a trial."""
import time


GATED = frozenset({'biology', 'physics', 'chemistry'})
EXAM_TRIAL_SUBJECTS = frozenset({'anatomy', 'anatomy_tests', 'histology'})
EXAM_TRIAL_HOURS = 12
EXAM_TRIAL_CLOSED = 'Для доступа нужна подходящая подписка или два новых однокурсника по твоей ссылке в этом месяце.'


def trial_expiry(tb, user_id):
    """Honor the original deadline for users who already tried histology."""
    uid = str(user_id)
    stored = tb.stats.get('exam_trial_access', {}).get(uid)
    if stored is not None:
        return stored
    return tb.stats.get('histology_temp_access', {}).get(uid, 0)


def trial_active(tb, user_id):
    return time.time() < trial_expiry(tb, user_id)


def exam_entitled(tb, user_id, subject):
    if subject == 'histology':
        return tb.histology_permanently_unlocked(user_id)
    if subject == 'anatomy':
        return tb.anatomy_permanently_unlocked(user_id)
    return (
        tb.is_admin_or_assistant(user_id)
        or tb.is_section_promo_active('global')
        or tb.is_section_promo_active('anatomy')
        or tb.has_subscription_anatomy_tests_access(user_id)
        or tb.get_referral_count_this_month(user_id) >= tb.REFERRAL_FULL_ACCESS_THRESHOLD
    )


def trial_available(tb, user_id):
    uid = str(user_id)
    return all(uid not in tb.stats.get(key, {}) for key in ('exam_trial_access', 'histology_temp_access'))


def can_visit(tb, user_id, subject):
    if subject in GATED:
        return tb.has_subject_access(user_id, subject) or tb.stats['referral_warnings'].get(str(user_id), {}).get('count', 0) < tb.REFERRAL_WARNING_THRESHOLD
    if subject in EXAM_TRIAL_SUBJECTS:
        return exam_entitled(tb, user_id, subject) or trial_active(tb, user_id)
    return True


def enter(tb, user_id, subject):
    """Run on the bot event loop before awaiting. Never renews an existing trial."""
    uid = str(user_id)
    if subject in EXAM_TRIAL_SUBJECTS:
        allowed = can_visit(tb, user_id, subject)
        started = not allowed and trial_available(tb, user_id)
        if started:
            tb.stats.setdefault('exam_trial_access', {})[uid] = time.time() + EXAM_TRIAL_HOURS * 3600
            tb.save_stats()
        return {'allowed': allowed or started, 'warning': False, 'trial_started': started}
    if subject in GATED:
        if tb.has_subject_access(user_id, subject):
            return {'allowed': True, 'warning': False, 'trial_started': False}
        key = 'referral_warnings'
    else:
        return {'allowed': True, 'warning': False, 'trial_started': False}
    if not can_visit(tb, user_id, subject):
        return {'allowed': False, 'warning': False, 'trial_started': False}
    entry = dict(tb.stats[key].get(uid, {'count': 0, 'last_warn_at': 0}))
    now = time.time()
    warn = now - entry.get('last_warn_at', 0) >= tb.REFERRAL_WARNING_COOLDOWN_SECONDS
    if warn:
        entry['count'] += 1
        entry['last_warn_at'] = now
        tb.stats[key][uid] = entry
        tb.save_stats()
    return {'allowed': True, 'warning': warn, 'trial_started': False,
            'warnings_remaining': max(0, tb.REFERRAL_WARNING_THRESHOLD - entry['count'])}
