# -*- coding: utf-8 -*-
import asyncio
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
    orig_broadcast = tb._broadcast
    broadcast_calls = []
    async def fake_broadcast(text, keyboard=None):
        broadcast_calls.append((text, keyboard))
    tb._broadcast = fake_broadcast

    # 1. No active battle -> button should be absent from keyboard, and callback should alert
    tb.stats["referral_battle"] = None
    kb = tb.get_admin_battle_keyboard()
    assert "📣 Разослать напоминание о битве" not in kb_texts(kb), kb_texts(kb)
    print("button hidden when no battle: OK")

    cb = FakeCB("admin_battle_remind_confirm")
    await tb.cb_admin_battle_remind_confirm(cb)
    assert cb._answers and cb._answers[0][1] is True and not cb.message.edits
    print("confirm blocked with no battle: OK")

    cb2 = FakeCB("admin_battle_remind_go")
    await tb.cb_admin_battle_remind_go(cb2)
    assert cb2._answers and cb2._answers[0][1] is True and not broadcast_calls
    print("go blocked with no battle: OK")

    # 2. Start a battle -> button appears, preview + broadcast work
    import random
    fresh_uid = str(random.randint(10_000_000, 99_999_999))
    tb.start_referral_battle()
    tb.stats["referrals"][fresh_uid] = ["a", "b", "c"]
    tb.stats["user_names"][fresh_uid] = "Тест Юзер"

    kb2 = tb.get_admin_battle_keyboard()
    assert "📣 Разослать напоминание о битве" in kb_texts(kb2)
    print("button visible during active battle: OK")

    text = tb.get_battle_remind_broadcast_text()
    c = C(); c.feed(text)
    assert not c.stack and not c.problems, (c.stack, c.problems)
    assert len(text) <= 4096
    assert "Тест Юзер" in text
    print("remind text HTML-balanced and includes leaderboard: OK")

    cb3 = FakeCB("admin_battle_remind_confirm")
    await tb.cb_admin_battle_remind_confirm(cb3)
    assert cb3.message.edits, "expected preview render"
    preview_text, preview_kb = cb3.message.edits[0]
    assert "Предпросмотр напоминания" in preview_text
    assert any("Отправить всем" in t for t in kb_texts(preview_kb))
    print("preview rendered: OK")

    cb4 = FakeCB("admin_battle_remind_go")
    await tb.cb_admin_battle_remind_go(cb4)
    assert broadcast_calls, "broadcast should have been called"
    sent_text, sent_kb = broadcast_calls[-1]
    assert "БИТВА РЕФЕРАЛОВ ПРОДОЛЖАЕТСЯ" in sent_text
    assert any("Битва рефералов" in t for t in kb_texts(sent_kb))
    assert cb4.message.edits and "отправлено" in cb4.message.edits[0][0]
    print("go broadcasts + confirms: OK")

    # 3. Non-admin access blocked
    cb5 = FakeCB("admin_battle_remind_confirm", uid=123456789)
    await tb.cb_admin_battle_remind_confirm(cb5)
    assert not cb5.message.edits
    print("non-admin blocked: OK")

    tb._broadcast = orig_broadcast
    print("ALL BATTLE REMIND TESTS PASSED")

asyncio.run(main())
