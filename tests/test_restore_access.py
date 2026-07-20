# -*- coding: utf-8 -*-
import asyncio, time, random
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

async def main():
    orig_broadcast_to = tb._broadcast_to
    calls = []
    async def fake_broadcast_to(user_ids, text, keyboard=None):
        calls.append((list(user_ids), text, keyboard))
    tb._broadcast_to = fake_broadcast_to

    # text content check
    text = tb.get_access_restored_broadcast_text()
    c = C(); c.feed(text)
    assert not c.stack and not c.problems, (c.stack, c.problems)
    assert len(text) <= 4096
    assert "7 дней" in text
    assert "уведомлен" in text
    print("broadcast text HTML-balanced: OK")

    # setup: no exhausted users -> confirm should alert and not edit
    tb.stats["referral_warnings"] = {}
    tb.stats["manual_access_granted"] = set() if not isinstance(tb.stats.get("manual_access_granted"), set) else tb.stats["manual_access_granted"]
    tb.stats["temporary_access"] = {}

    cb0 = FakeCB("admin_restore_access_confirm")
    await tb.cb_admin_restore_access_confirm(cb0)
    assert cb0._answers and cb0._answers[0][1] is True and not cb0.message.edits
    print("confirm blocked with empty cohort: OK")

    cb0b = FakeCB("admin_restore_access_go")
    await tb.cb_admin_restore_access_go(cb0b)
    assert cb0b._answers and cb0b._answers[0][1] is True and not calls
    print("go blocked with empty cohort: OK")

    # create exhausted users
    uid1 = random.randint(10_000_000, 99_999_999)
    uid2 = random.randint(10_000_000, 99_999_999)
    while uid2 == uid1:
        uid2 = random.randint(10_000_000, 99_999_999)
    for uid in (uid1, uid2):
        tb.stats["referral_warnings"][str(uid)] = {"count": tb.REFERRAL_WARNING_THRESHOLD, "last_warn": 0}
    assert not tb.has_free_access(uid1) and not tb.has_free_access(uid2)
    cohort = tb.get_exhausted_users()
    assert uid1 in cohort and uid2 in cohort, cohort
    print("get_exhausted_users finds cohort: OK")

    # has_temp_access should be False before grant
    assert not tb.has_temp_access(uid1)

    cb1 = FakeCB("admin_restore_access_confirm")
    await tb.cb_admin_restore_access_confirm(cb1)
    assert cb1.message.edits, "expected preview render"
    preview_text, preview_kb = cb1.message.edits[0]
    assert "Предпросмотр рассылки" in preview_text
    assert any("Восстановить и отправить" in t for t in kb_texts(preview_kb))
    print("preview rendered: OK")

    cb2 = FakeCB("admin_restore_access_go")
    await tb.cb_admin_restore_access_go(cb2)
    assert calls, "broadcast should have been called"
    sent_ids, sent_text, sent_kb = calls[-1]
    assert uid1 in sent_ids and uid2 in sent_ids, sent_ids
    assert "Тебе восстановлен доступ" in sent_text
    assert cb2.message.edits and "восстановлен" in cb2.message.edits[0][0]
    print("go grants + broadcasts to cohort only: OK")

    # verify has_free_access / has_temp_access now true for the cohort
    assert tb.has_temp_access(uid1) and tb.has_temp_access(uid2)
    assert tb.has_free_access(uid1) and tb.has_free_access(uid2)
    print("temp access granted correctly: OK")

    # get_exhausted_users should now exclude them (since has_free_access is True)
    cohort2 = tb.get_exhausted_users()
    assert uid1 not in cohort2 and uid2 not in cohort2
    print("cohort excludes users with fresh temp access: OK")

    # referral status text should reflect temp access
    status_text = tb.get_referral_status_text(uid1)
    c2 = C(); c2.feed(status_text)
    assert not c2.stack and not c2.problems, (c2.stack, c2.problems)
    assert "временно открыт" in status_text
    print("get_referral_status_text shows temp access branch: OK")

    # simulate expiry
    tb.stats["temporary_access"][str(uid1)] = time.time() - 10
    assert not tb.has_temp_access(uid1)
    assert not tb.has_free_access(uid1)
    print("expiry works: OK")

    # non-admin blocked
    cb3 = FakeCB("admin_restore_access_confirm", uid=123456789)
    await tb.cb_admin_restore_access_confirm(cb3)
    assert not cb3.message.edits
    print("non-admin blocked: OK")

    tb._broadcast_to = orig_broadcast_to
    print("ALL RESTORE ACCESS TESTS PASSED")

asyncio.run(main())
