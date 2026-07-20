# -*- coding: utf-8 -*-
import os, sys, asyncio, random
from _bootstrap import tb
from html.parser import HTMLParser

ADMIN_ID = next(iter(tb.ADMIN_IDS))

class C(HTMLParser):
    def __init__(self):
        super().__init__(); self.stack=[]; self.problems=[]
    def handle_starttag(self, tag, attrs): self.stack.append(tag)
    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag: self.problems.append(tag)
        else: self.stack.pop()

def check_html(text):
    c = C(); c.feed(text)
    assert not c.stack and not c.problems, (text[:200], c.stack, c.problems)
    assert len(text) <= 4096, len(text)

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
    return random.randint(10_000_000, 99_999_999)

async def main():
    orig_broadcast_to = tb._broadcast_to
    calls = []
    async def fake_broadcast_to(user_ids, text, keyboard=None):
        calls.append((list(user_ids), text, keyboard))
    tb._broadcast_to = fake_broadcast_to

    # 1. broadcast text/keyboard: HTML-balanced, mentions both the referral and the subscription path
    text = tb.get_referral_reminder_broadcast_text()
    check_html(text)
    assert "Биология, Физика и Химия" in text
    assert str(tb.REFERRAL_FULL_ACCESS_THRESHOLD) in text
    assert f"{tb.SUBSCRIPTION_TIERS[1]['price_rub']}₽" in text
    kb = tb.get_referral_reminder_broadcast_keyboard()
    texts = kb_texts(kb)
    assert "👥 Пригласить друзей" in texts and "💎 Подписка" in texts
    print("reminder broadcast text/keyboard OK")

    # 2. get_below_threshold_users(): correct cohort membership
    uid_none = fresh_uid()          # 0 referrals, nothing else -> IN cohort
    uid_one = fresh_uid()           # 1 referral -> IN cohort
    uid_full = fresh_uid()          # 2 referrals -> free access -> NOT in cohort
    uid_sub = fresh_uid()           # subscribed -> NOT in cohort
    uid_manual = fresh_uid()        # manual access granted -> NOT in cohort
    uid_temp = fresh_uid()          # temp access -> NOT in cohort
    for uid in (uid_none, uid_one, uid_full, uid_sub, uid_manual, uid_temp):
        tb.stats["total_users"].add(uid)
    tb.stats["referrals"].pop(str(uid_none), None)
    tb.stats["referrals"][str(uid_one)] = ["a"]
    tb.stats["referrals"][str(uid_full)] = ["a", "b"]
    tb.grant_subscription(uid_sub, 1, "stars", 89)
    if uid_manual not in tb.stats["manual_access_granted"]:
        tb.stats["manual_access_granted"].append(uid_manual)
    tb.stats["temporary_access"][str(uid_temp)] = tb.time.time() + 3600

    cohort = tb.get_below_threshold_users()
    assert uid_none in cohort and uid_one in cohort
    assert uid_full not in cohort
    assert uid_sub not in cohort
    assert uid_manual not in cohort
    assert uid_temp not in cohort
    print("get_below_threshold_users() cohort membership correct: OK")

    # 3. confirm/go with an empty cohort (isolate: temporarily empty total_users) -> alert, no crash
    saved_total_users = tb.stats["total_users"]
    tb.stats["total_users"] = set()
    cb_empty1 = FakeCB("admin_referral_reminder_confirm")
    await tb.cb_admin_referral_reminder_confirm(cb_empty1)
    assert cb_empty1._answers and cb_empty1._answers[0][1] is True and not cb_empty1.message.edits
    cb_empty2 = FakeCB("admin_referral_reminder_go")
    await tb.cb_admin_referral_reminder_go(cb_empty2)
    assert cb_empty2._answers and cb_empty2._answers[0][1] is True and not calls
    tb.stats["total_users"] = saved_total_users
    print("confirm/go blocked with empty cohort: OK")

    # 4. preview renders, mentions cohort size, does NOT grant any access
    cb1 = FakeCB("admin_referral_reminder_confirm")
    await tb.cb_admin_referral_reminder_confirm(cb1)
    assert cb1.message.edits, "expected preview render"
    preview_text, preview_kb = cb1.message.edits[0]
    check_html(preview_text)
    assert "Предпросмотр рассылки" in preview_text
    assert any("Отправить напоминание" in t for t in kb_texts(preview_kb))
    print("preview rendered: OK")

    # 5. go: broadcasts to exactly the cohort, does not touch access/subscription state
    assert not tb.has_free_access(uid_none) and not tb.has_free_access(uid_one)
    broadcasts_before = tb.stats.get("broadcast_count", 0)
    cb2 = FakeCB("admin_referral_reminder_go")
    await tb.cb_admin_referral_reminder_go(cb2)
    assert calls, "broadcast should have been called"
    sent_ids, sent_text, sent_kb = calls[-1]
    assert uid_none in sent_ids and uid_one in sent_ids
    assert uid_full not in sent_ids and uid_sub not in sent_ids
    assert uid_manual not in sent_ids and uid_temp not in sent_ids
    assert sent_text == text
    assert tb.stats["broadcast_count"] == broadcasts_before + 1
    assert cb2.message.edits and "отправлено" in cb2.message.edits[0][0]
    # no access was granted by this action
    assert not tb.has_free_access(uid_none) and not tb.has_free_access(uid_one)
    print("go broadcasts to exact cohort only, grants no access: OK")

    # 6. non-admin blocked
    cb3 = FakeCB("admin_referral_reminder_confirm", uid=123456789)
    await tb.cb_admin_referral_reminder_confirm(cb3)
    assert not cb3.message.edits
    cb4 = FakeCB("admin_referral_reminder_go", uid=123456789)
    await tb.cb_admin_referral_reminder_go(cb4)
    assert not cb4.message.edits
    print("non-admin blocked: OK")

    tb._broadcast_to = orig_broadcast_to
    print("ALL REFERRAL REMINDER TESTS PASSED")

asyncio.run(main())
