"""HTML-safe buyer identification for administrator payment notifications."""
import re
from html import escape


def buyer_label(tb, user_id: int, fallback_username=None) -> str:
    uid = str(user_id)
    username = tb.stats.get('user_username', {}).get(uid, fallback_username)
    if isinstance(username, str) and re.fullmatch(r'[A-Za-z0-9_]{1,32}', username):
        return f'{uid} · @{username}'
    name = tb.stats.get('user_names', {}).get(uid)
    label = escape(name if isinstance(name, str) and name.strip() else 'Профиль пользователя')
    return f'{uid} · <a href="tg://user?id={user_id}">{label}</a>'
