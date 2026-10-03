"""Shared content admission; only explicit visits consume warnings or start a trial."""
import time


GATED = frozenset({'biology', 'physics', 'chemistry'})


def trial_available(tb, user_id):
    uid = str(user_id)
    return uid not in tb.stats['histology_temp_access'] and uid not in tb.stats['histology_warnings']


def can_visit(tb, user_id, subject):
    if subject in GATED:
        return tb.has_subject_access(user_id, subject) or tb.stats['referral_warnings'].get(str(user_id), {}).get('count', 0) < tb.REFERRAL_WARNING_THRESHOLD
    if subject == 'histology':
        return tb.histology_access_ok(user_id)
    return True


def enter(tb, user_id, subject):
    """Run on the bot event loop before awaiting. Never renews an existing trial."""
    uid = str(user_id)
    if subject == 'histology':
        if tb.histology_permanently_unlocked(user_id):
            return {'allowed': True, 'warning': False, 'trial_started': False}
        if trial_available(tb, user_id):
            tb.stats['histology_temp_access'][uid] = time.time() + tb.TEMP_ACCESS_GRANT_SECONDS
            tb.save_stats()
            return {'allowed': True, 'warning': False, 'trial_started': True}
        key = 'histology_warnings'
    elif subject in GATED:
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
