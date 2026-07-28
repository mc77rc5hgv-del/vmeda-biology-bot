# -*- coding: utf-8 -*-
from _bootstrap import tb

UID = 555999
uid_str = str(UID)
T = tb.REFERRAL_FULL_ACCESS_THRESHOLD
tb.stats["referrals"][uid_str] = []
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

# T-1 referrals -> still no free access, "1 more friend" (одного друга)
tb.stats["referrals"][uid_str] = [f"ref{i}" for i in range(T - 1)]
assert not tb.has_free_access(UID)
text1 = tb.get_referral_status_text(UID)
print(text1)
assert "одному другу" in text1
assert f"{T - 1}</b> из {T}" in text1
assert "Доступ ко всем разделам бота открыт" not in text1
print("=" * 60)

# T referrals -> full access, battle CTA present
tb.stats["referrals"][uid_str] = [f"ref{i}" for i in range(T)]
assert tb.has_free_access(UID)
text2 = tb.get_referral_status_text(UID)
print(text2)
assert "Доступ ко всем разделам бота открыт" in text2
assert "битве рефералов" in text2
print("=" * 60)

# manual grant also counts as full access even with 0 referrals
tb.stats["referrals"][uid_str] = []
tb.stats["manual_access_granted"].append(UID)
assert tb.has_free_access(UID)
text3 = tb.get_referral_status_text(UID)
print(text3)
assert "Доступ ко всем разделам бота открыт" in text3
tb.stats["manual_access_granted"].remove(UID)

# admin always has access regardless of referrals
admin_id = next(iter(tb.ADMIN_IDS))
assert tb.has_free_access(admin_id)

print("ALL REFERRAL GATE TESTS PASSED")
