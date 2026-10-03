"""Combine preserved bot history and the existing Mini App journal without migration."""
from __future__ import annotations

from web_api import learning


def summary(tb, user_id: int) -> dict:
    total = sum(len(g.get('specimens', [])) for g in tb.HISTOLOGY.values())
    journal = learning.get_histology_stats(user_id, total)
    baseline = tb.stats.get('histology_learning', {}).get(str(user_id), {})
    attempts = int(baseline.get('attempts', 0)) + journal['attempts']
    known = int(baseline.get('known', 0)) + journal['known']
    mastered = set(baseline.get('mastered', [])) | set(journal.get('mastered_ids', []))
    # Legacy bot history has no timestamps. Keep all unresolved legacy mistakes; only a
    # new shared-journal answer may resolve one. No historical record is removed.
    mistakes = set(baseline.get('mistakes', [])) | set(journal['mistake_ids'])
    for specimen_id, is_known in journal.get('synchronized_results', {}).items():
        if is_known:
            mistakes.discard(specimen_id)
        else:
            mistakes.add(specimen_id)
    return {
        'total_specimens': total, 'attempts': attempts, 'known': known,
        'wrong': attempts - known, 'accuracy_percent': round(known / attempts * 100) if attempts else 0,
        'mastered_specimens': len(mastered), 'mastered_ids': sorted(mastered),
        'active_mistakes': len(mistakes), 'mistake_ids': sorted(mistakes),
    }


def entry(tb, user_id: int) -> dict:
    result = summary(tb, user_id)
    return {
        'attempts': result['attempts'], 'known': result['known'], 'wrong': result['wrong'],
        'mistakes': result['mistake_ids'], 'mastered': result['mastered_ids'],
    }
