# -*- coding: utf-8 -*-
import asyncio
from _bootstrap import tb

class FakeUser:
    def __init__(self, uid, full_name, username=None):
        self.id = uid
        self.full_name = full_name
        self.username = username

async def main():
    # track_user_identity() must HTML-escape full_name before storing it, since
    # stats["user_names"] is later rendered with parse_mode="HTML" in public
    # battle leaderboards/results and admin notifications.
    uid = 900_000_001
    uid_str = str(uid)
    tb.stats["user_names"].pop(uid_str, None)
    tb.stats["user_username"].pop(uid_str, None)

    malicious_name = "<b>Hacker</b><script>alert(1)</script>"
    tb.track_user_identity(FakeUser(uid, malicious_name))
    stored = tb.stats["user_names"][uid_str]
    assert "<b>" not in stored and "<script>" not in stored, f"unescaped HTML stored: {stored!r}"
    assert "&lt;b&gt;" in stored and "&lt;script&gt;" in stored
    print("track_user_identity escapes HTML in full_name: OK")

    # get_referral_display_name / donor_display_name read straight from user_names,
    # so the escaped form must round-trip through them unharmed.
    assert "<b>" not in tb.donor_display_name(uid_str)
    print("donor_display_name never leaks raw HTML: OK")

    # plain names without HTML-special characters are stored unchanged (no double-escaping,
    # no mangling of legitimate names).
    uid2 = 900_000_002
    uid2_str = str(uid2)
    tb.stats["user_names"].pop(uid2_str, None)
    tb.track_user_identity(FakeUser(uid2, "Иван Иванов"))
    assert tb.stats["user_names"][uid2_str] == "Иван Иванов"
    print("plain names stored unchanged: OK")

    # empty/None full_name still falls back to the placeholder, not html.escape(None).
    uid3 = 900_000_003
    uid3_str = str(uid3)
    tb.stats["user_names"].pop(uid3_str, None)
    tb.track_user_identity(FakeUser(uid3, ""))
    assert tb.stats["user_names"][uid3_str] == f"Пользователь {uid3}"
    print("empty full_name falls back to placeholder: OK")

    tb.stats["user_names"].pop(uid_str, None)
    tb.stats["user_names"].pop(uid2_str, None)
    tb.stats["user_names"].pop(uid3_str, None)

    print("ALL SECURITY TESTS PASSED")

asyncio.run(main())
