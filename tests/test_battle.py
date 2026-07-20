# -*- coding: utf-8 -*-
import os, sys, asyncio, random
from _bootstrap import tb
from html.parser import HTMLParser

ADMIN_ID = next(iter(tb.ADMIN_IDS))

class BalanceChecker(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.problems = []
    def handle_starttag(self, tag, attrs):
        self.stack.append(tag)
    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.problems.append(f"mismatch {tag}")
        else:
            self.stack.pop()

def check(name, text):
    c = BalanceChecker()
    c.feed(text)
    assert not c.stack and not c.problems, f"{name}: HTML broken {c.stack} {c.problems}"
    assert len(text) <= 4096, f"{name}: too long {len(text)}"
    print(f"OK {name} ({len(text)} chars)")
    print(text)
    print("=" * 60)

class FakeUser:
    def __init__(self, uid):
        self.id = uid

class FakeMsg:
    def __init__(self):
        self.edits = []
    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self
    async def delete(self):
        pass
    async def answer(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self

class FakeCB:
    def __init__(self, data, uid=ADMIN_ID):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
        self._answers = []
    async def answer(self, text=None, show_alert=False):
        self._answers.append((text, show_alert))

def kb_texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row]

def fresh_uid():
    return str(random.randint(10_000_000, 99_999_999))

# ==================== 1. Prize data / block ====================
assert len(tb.BATTLE_PRIZE_LABELS) == 5
assert len(tb.BATTLE_PRIZE_VALUES_RUB) == 5
assert tb.BATTLE_PRIZE_VALUES_RUB == [4500, 2300, 2300, 1599, 1599]
assert tb.BATTLE_TOP3_MIN_REFERRALS == 30

block = tb.format_battle_prizes_block()
check("prizes_block", block)
assert "VMEDA_examen_bot" in block and "Helperchat_bot" in block
assert "вечный" in block
assert "5 место" in block and "1 место" in block
assert "30" in block
for value in tb.BATTLE_PRIZE_VALUES_RUB:
    assert tb.format_rub(value) in block
print("prize data + block (5 places, threshold, savings for every place): OK")

# ==================== 2. get_battle_text idle/active ====================
tb.stats["referral_battle"] = None
check("idle_no_prev", tb.get_battle_text(12345))

# idle with previous results: 5-slot list, some places forfeited (None)
tb.stats["referral_battle"] = {"active": False, "results": [("111", 40), ("222", 35), None, ("333", 3), None]}
tb.stats["user_names"]["111"] = "Иван"
tb.stats["user_names"]["222"] = "Пётр"
tb.stats["user_names"]["333"] = "Анна"
idle_text = tb.get_battle_text(12345)
check("idle_with_results", idle_text)
# results lines render as "<icon> N место — name — <b>diff</b>" (unbolded "N место"),
# distinct from the generic prize block below it which always bolds "N место" for all 5.
assert "🥇 1 место — Иван" in idle_text
assert "🥈 2 место — Пётр" in idle_text
assert "🏅 4 место — Анна" in idle_text
assert "🥉 3 место —" not in idle_text and "🎖 5 место —" not in idle_text
print("idle_with_results skips forfeited (None) places: OK")

# all-None results (nobody won) must fall back to the "no previous winners" teaser, not an empty block
tb.stats["referral_battle"] = {"active": False, "results": [None, None, None, None, None]}
idle_none_text = tb.get_battle_text(12345)
check("idle_all_none", idle_none_text)
assert "Результаты последней битвы" not in idle_none_text
print("idle with all-None results falls back correctly: OK")

# active battle
tb.stats["referral_battle"] = None
tb.start_referral_battle()
tb.stats["referrals"]["111"] = ["a", "b", "c"]
active_text = tb.get_battle_text(12345)
check("active_battle", active_text)
assert "топ-5" in active_text
print("active battle text OK")

# admin idle / active text
tb.stats["referral_battle"] = None
admin_idle_text = tb.get_admin_battle_text()
check("admin_idle", admin_idle_text)
assert "топ-5" in admin_idle_text

tb.start_referral_battle()
tb.stats["referrals"]["111"] = ["a", "b", "c"]
check("admin_active", tb.get_admin_battle_text())
tb.stats["referral_battle"] = None

# ==================== 3. resolve_battle_winners() qualifying logic ====================
def set_battle_with_gains(gains: dict):
    """gains: {uid_str: referrals gained during the battle}. Snapshots ALL current referral
    counts first (like start_referral_battle does in production), then appends `n` new
    entries per uid, so the computed diff equals exactly `n` regardless of any pre-existing
    referral count left over from earlier assertions in this same test run."""
    snapshot = {uid: len(refs) for uid, refs in tb.stats["referrals"].items()}
    tb.stats["referral_battle"] = {
        "active": True, "start_ts": 0, "end_ts": 0,
        "snapshot": snapshot, "results": None,
    }
    for uid, n in gains.items():
        base = tb.stats["referrals"].get(uid, [])
        tb.stats["referrals"][uid] = base + [f"battle_{uid}_{i}" for i in range(n)]

u1, u2, u3, u4, u5, u6 = (fresh_uid() for _ in range(6))

# Case A: 2 qualify for top-3 (>=30), 3rd place forfeited, places 4-5 go to next best regardless of threshold
set_battle_with_gains({u1: 50, u2: 30, u3: 10, u4: 5, u5: 1})
winners = tb.resolve_battle_winners()
assert len(winners) == 5
assert winners[0] == (u1, 50)
assert winners[1] == (u2, 30)
assert winners[2] is None, "3rd place must be forfeited: nobody else has >=30"
assert winners[3] == (u3, 10)
assert winners[4] == (u4, 5)
print("case A: partial top-3 + places 4-5 filled without threshold: OK")

# Case B: nobody reaches 30 -> places 1-3 all forfeited, 4-5 go to the top 2 overall
set_battle_with_gains({u1: 10, u2: 8, u3: 2})
winners = tb.resolve_battle_winners()
assert winners[0] is None and winners[1] is None and winners[2] is None
assert winners[3] == (u1, 10)
assert winners[4] == (u2, 8)
print("case B: nobody qualifies for top-3, places 4-5 still awarded: OK")

# Case C: everybody qualifies (>=30) -> top3 filled from qualifiers, 4-5 from the remaining qualifiers
set_battle_with_gains({u1: 100, u2: 90, u3: 80, u4: 70, u5: 60, u6: 5})
winners = tb.resolve_battle_winners()
assert [w[0] for w in winners] == [u1, u2, u3, u4, u5]
print("case C: 5+ qualifiers fill all 5 places in ranked order: OK")

# Case D: nobody invited anyone during the battle -> all None
set_battle_with_gains({})
winners = tb.resolve_battle_winners()
assert winners == [None] * 5
print("case D: no participants -> all 5 places None: OK")

# ==================== 4. get_battle_results_announcement_text ====================
no_winners_text = tb.get_battle_results_announcement_text([None] * 5)
check("no_winners", no_winners_text)
assert "никто не пригласил" in no_winners_text

set_battle_with_gains({u1: 50, u2: 30, u3: 10, u4: 5})
winners = tb.resolve_battle_winners()
result_text = tb.get_battle_results_announcement_text(winners)
check("partial_winners", result_text)
assert "не разыграна" in result_text, "should warn that part of top-3 was forfeited"
for i, w in enumerate(winners):
    if w is not None:
        assert tb.format_rub(tb.BATTLE_PRIZE_VALUES_RUB[i]) in result_text
print("results announcement: no-winners fallback + partial-top3 warning + correct savings: OK")

# ==================== 5. resolve_referral_battle() end-to-end ====================
async def test_resolve_real():
    uid1, uid2, uid3, uid4, uid5 = (fresh_uid() for _ in range(5))
    tb.stats["user_names"][uid1] = "Победитель1"
    tb.stats["user_names"][uid2] = "Победитель2"
    tb.stats["user_names"][uid3] = "Победитель3"
    tb.stats["user_names"][uid4] = "Победитель4"
    tb.stats["user_names"][uid5] = "Победитель5"
    set_battle_with_gains({uid1: 100, uid2: 60, uid3: 30, uid4: 15, uid5: 2})
    tb.stats["referral_battle"]["active"] = True

    broadcasts = []
    orig_broadcast = tb._broadcast
    async def fake_broadcast(text, keyboard=None):
        broadcasts.append(text)
    tb._broadcast = fake_broadcast

    admin_msgs = []
    orig_send_message = tb.bot.send_message
    async def fake_send_message(chat_id, text, **kwargs):
        admin_msgs.append((chat_id, text))
    tb.bot.send_message = fake_send_message

    await tb.resolve_referral_battle()

    tb._broadcast = orig_broadcast
    tb.bot.send_message = orig_send_message

    assert broadcasts, "expected a broadcast with results"
    result_text = broadcasts[0]
    check("resolve_real_broadcast", result_text)
    for value in tb.BATTLE_PRIZE_VALUES_RUB:
        assert tb.format_rub(value) in result_text, f"missing savings figure {value} in {result_text}"
    assert "5 место" in result_text

    stored = tb.stats["referral_battle"]["results"]
    assert len(stored) == 5 and stored[0][0] == uid1 and stored[4][0] == uid5
    assert tb.stats["referral_battle"]["active"] is False

    assert admin_msgs, "expected admin notification"
    print("resolve_referral_battle() real broadcast + admin DM + stored results (5 places): OK")

asyncio.run(test_resolve_real())

# ==================== 6. Admin "last results" button/handler ====================
async def test_admin_last_results_button():
    tb.stats["referral_battle"] = None
    kb = tb.get_admin_battle_keyboard()
    assert not any("Итоги последней битвы" in t for t in kb_texts(kb))
    cb_none = FakeCB("admin_battle_last_results")
    await tb.cb_admin_battle_last_results(cb_none)
    assert cb_none._answers and cb_none._answers[0][1] is True and not cb_none.message.edits
    print("no saved results -> button hidden, handler alerts: OK")

    winners = [("111", 40), ("222", 35), None, ("333", 5), None]
    tb.stats["referral_battle"] = {"active": False, "results": winners}
    kb2 = tb.get_admin_battle_keyboard()
    assert any("Итоги последней битвы" in t for t in kb_texts(kb2))

    cb = FakeCB("admin_battle_last_results")
    await tb.cb_admin_battle_last_results(cb)
    assert cb.message.edits, "expected rendered results"
    text = cb.message.edits[0][0]
    check("admin_last_results", text)
    expected_announcement = tb.get_battle_results_announcement_text(winners)
    assert expected_announcement in text
    assert "скопируй" in text.lower()

    cb_na = FakeCB("admin_battle_last_results", uid=123456789)
    await tb.cb_admin_battle_last_results(cb_na)
    assert not cb_na.message.edits
    print("saved results (with forfeited places) -> button shown, handler renders publishable text: OK")

asyncio.run(test_admin_last_results_button())

print("ALL BATTLE TEXT TESTS PASSED")
