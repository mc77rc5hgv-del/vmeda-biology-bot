"""Preserve historical bot ratings and combine them with the new common journal."""
import copy


def scores(tb, kind: str, user_id: int = 1):
    from web_api import learning
    key = 'anatomy_exam_flash_scores' if kind == 'flash' else 'anatomy_exam_test_scores'
    result = copy.deepcopy(tb.stats.get(key, {}))
    for uid, new in learning.get_anatomy_scores(user_id, kind).items():
        old = result.setdefault(uid, {k: 0 for k in new})
        old['attempts'] = old.get('attempts', 0) + new['attempts']
        if kind == 'flash':
            old_ratio = old.get('best_correct', 0) / old['best_total'] if old.get('best_total') else 0
            if (new['best_correct'] / new['best_total'], new['best_total']) > (old_ratio, old.get('best_total', 0)):
                old.update(best_correct=new['best_correct'], best_total=new['best_total'])
        else:
            old['correct'] += new['correct']
            old['total'] += new['total']
    return result
