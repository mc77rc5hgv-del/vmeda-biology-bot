# -*- coding: utf-8 -*-
import asyncio
from _bootstrap import tb

class FakeUser:
    def __init__(self, uid):
        self.id = uid

class FakeMsg:
    def __init__(self):
        self.edits = []
        self.markups = []
    async def edit_text(self, text, **kwargs):
        self.edits.append(text)
        self.markups.append(kwargs.get("reply_markup"))
        return self
    async def delete(self):
        pass
    async def answer(self, text, **kwargs):
        self.edits.append(text)
        self.markups.append(kwargs.get("reply_markup"))
        return self

class FakeCB:
    def __init__(self, data, uid):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
    async def answer(self, text=None, show_alert=False):
        pass

def keyboard_texts(markup):
    return [btn.text for row in markup.inline_keyboard for btn in row]

async def main():
    UID = 777333
    uid_str = str(UID)
    tb.stats["referrals"][uid_str] = []
    tb.stats["manual_access_granted"] = [x for x in tb.stats["manual_access_granted"] if x != UID]

    # 0 referrals -> plain back keyboard, no battle button
    cb = FakeCB("referral_info", UID)
    await tb.cb_referral_info(cb)
    texts = keyboard_texts(cb.message.markups[0])
    assert "⚔️ Битва рефералов" not in texts, texts
    assert "🔙 Назад в меню" in texts
    print("0-ref keyboard OK:", texts)

    # 2 referrals -> battle button appears, subscription entry point stays reachable
    tb.stats["referrals"][uid_str] = ["a", "b"]
    cb = FakeCB("referral_info", UID)
    await tb.cb_referral_info(cb)
    texts = keyboard_texts(cb.message.markups[0])
    assert "⚔️ Битва рефералов" in texts, texts
    assert "💎 Подписка" in texts, "subscription entry point must not disappear once free access is granted"
    print("2-ref keyboard OK:", texts)

    print("ALL HANDLER TESTS PASSED")

asyncio.run(main())
