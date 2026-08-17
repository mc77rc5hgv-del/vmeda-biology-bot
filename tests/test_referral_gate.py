# -*- coding: utf-8 -*-
"""Referral access gate — now based on referrals brought THIS CALENDAR MONTH, not a lifetime
total (see CLAUDE.md/services/access.py: REFERRAL_FULL_ACCESS_THRESHOLD is recurring, not a
one-time-forever unlock). set_month_referrals() below sets BOTH the lifetime list (still used for
the leaderboard/battle and for display) and the monthly counter that actually drives the gate."""
from _bootstrap import tb

UID = 555999
uid_str = str(UID)
T = tb.REFERRAL_FULL_ACCESS_THRESHOLD


def set_month_referrals(n: int) -> None:
    tb.stats["referrals"][uid_str] = [f"ref{i}" for i in range(n)]
    tb.stats["referral_monthly"][uid_str] = {"month": tb._current_referral_month_key(), "count": n}


tb.stats["referrals"][uid_str] = []
tb.stats["referral_monthly"].pop(uid_str, None)
tb.stats["manual_access_granted"] = [x for x in tb.stats["manual_access_granted"] if x != UID]
tb.stats["referral_warnings"].pop(uid_str, None)

# 0 referrals -> no free access, "invite friends" text with T remaining
assert not tb.has_free_access(UID)
text0 = tb.get_referral_status_text(UID)
print(text0)
assert (f"{T} друзьям" if T != 2 else "двум друзьям") in text0
assert f"0</b> из {T}" in text0
assert "Доступ ко всем разделам бота открыт" not in text0
print("=" * 60)

# T-1 referrals this month -> still no free access, "1 more friend" (одного друга)
set_month_referrals(T - 1)
assert not tb.has_free_access(UID)
text1 = tb.get_referral_status_text(UID)
print(text1)
assert "одному другу" in text1
assert f"{T - 1}</b> из {T}" in text1
assert "Доступ ко всем разделам бота открыт" not in text1
print("=" * 60)

# T referrals this month -> full access, battle CTA present, monthly-reset note shown
set_month_referrals(T)
assert tb.has_free_access(UID)
text2 = tb.get_referral_status_text(UID)
print(text2)
assert "Доступ ко всем разделам бота открыт" in text2
assert "битве рефералов" in text2
assert "каждый месяц" in text2, "must warn that the referral condition renews monthly"
print("=" * 60)

# a NEW month with zero referrals -> access closes again even though the lifetime list is untouched
tb.stats["referral_monthly"][uid_str] = {"month": "2001-01", "count": T}
assert not tb.has_free_access(UID), "referrals from a past month must not count toward the current month"
text2b = tb.get_referral_status_text(UID)
assert "Доступ ко всем разделам бота открыт" not in text2b
print("month rollover correctly closes access again: OK")
print("=" * 60)

# manual grant also counts as full access even with 0 referrals this month
tb.stats["referral_monthly"].pop(uid_str, None)
tb.stats["manual_access_granted"].append(UID)
assert tb.has_free_access(UID)
text3 = tb.get_referral_status_text(UID)
print(text3)
assert "Доступ ко всем разделам бота открыт" in text3
assert "каждый месяц" not in text3, "a manual grant is not subject to the monthly-renewal note"
tb.stats["manual_access_granted"].remove(UID)

# admin always has access regardless of referrals
admin_id = next(iter(tb.ADMIN_IDS))
assert tb.has_free_access(admin_id)

print("ALL REFERRAL GATE TESTS PASSED")
