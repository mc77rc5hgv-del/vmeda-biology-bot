"""Read existing physiology progress/favorites alongside the shared material journal."""
def merge(tb, user_id: int, state: dict):
    uid = str(user_id)
    completed = set(state['completed_keys'])
    favorites = {(r['subject_id'], r['section_id'], r['material_id']): r for r in state['favorites']}
    progress = tb.stats.get('physiology_progress', {}).get(uid, {})
    overrides = tb.stats.get('physiology_completion_overrides', {}).get(uid, {})
    native_favorites = set(tb.stats.get('physiology_favorites', {}).get(uid, {}).get('topics', []))
    for index, topic in enumerate(tb.PHYSIOLOGY.get('topics', [])):
        topic_id = topic['topic_id']
        key = f'physiology/course/{topic_id}'
        entry = progress.get(topic_id, {})
        if entry.get('total_cards', 0) > 0 and entry.get('completed_cards', 0) >= entry['total_cards']:
            completed.add(key)
        if overrides.get(topic_id) is True:
            completed.add(key)
        elif overrides.get(topic_id) is False:
            completed.discard(key)
        elif topic_id in overrides and entry.get('completed_cards', 0) < entry.get('total_cards', 1):
            completed.discard(key)  # a later native study action supersedes the old UI flag
        if topic_id in native_favorites:
            favorites[('physiology', 'course', topic_id)] = {
                'subject_id': 'physiology', 'section_id': 'course', 'material_id': topic_id,
                'subject_title': 'Нормальная физиология', 'section_title': 'Курс',
                'material_title': topic['title'], 'material_order': index+1,
                'total_in_section': len(tb.PHYSIOLOGY['topics']), 'completed': key in completed,
                'favorite': True, 'last_opened_at': None, 'completed_at': None,
            }
        # New explicit Mini App favorite actions also update the native list. Old journal
        # favorites stay preserved until an explicit action requests otherwise.
        override = tb.stats.get('physiology_favorite_overrides', {}).get(uid, {}).get(topic_id)
        if override is False and topic_id not in native_favorites:
            favorites.pop(('physiology', 'course', topic_id), None)
    counts = {}
    for key in completed:
        subject = key.split('/', 1)[0]
        counts[subject] = counts.get(subject, 0) + 1
    return {**state, 'completed_keys': sorted(completed), 'completed_by_subject': counts,
            'completed_total': len(completed), 'favorites': list(favorites.values())}
