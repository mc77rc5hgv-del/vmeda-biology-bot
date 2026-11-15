"""Combine preserved bot history and the existing Mini App journal without migration."""
from __future__ import annotations

from services.histology_content import exam_progress
from web_api import learning


def summary(tb, user_id: int) -> dict:
    journal = learning.get_histology_stats(user_id)
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
    return exam_progress({
        'attempts': attempts, 'known': known,
        'wrong': attempts - known, 'accuracy_percent': round(known / attempts * 100) if attempts else 0,
        'mastered_ids': mastered, 'mistake_ids': mistakes,
    })


def entry(tb, user_id: int) -> dict:
    result = summary(tb, user_id)
    return {
        'attempts': result['attempts'], 'known': result['known'], 'wrong': result['wrong'],
        'mistakes': result['mistake_ids'], 'mastered': result['mastered_ids'],
    }
