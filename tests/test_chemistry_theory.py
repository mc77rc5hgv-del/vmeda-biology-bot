# -*- coding: utf-8 -*-
import asyncio
from _bootstrap import tb
from html.parser import HTMLParser

class C(HTMLParser):
    def __init__(self):
        super().__init__(); self.stack = []; self.problems = []
    def handle_starttag(self, tag, attrs): self.stack.append(tag)
    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag: self.problems.append(tag)
        else: self.stack.pop()

def check_html(text):
    c = C(); c.feed(text)
    assert not c.stack and not c.problems, (text[:200], c.stack, c.problems)

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
    def __init__(self, data, uid=111222333):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
        self._answers = []
    async def answer(self, text=None, show_alert=False):
        self._answers.append((text, show_alert))

def kb_data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]

async def main():
    assert len(tb.CHEMISTRY_THEORY) == 16

    # 1. every topic renders, valid HTML, under Telegram's message limit
    for num in range(1, 17):
        cb = FakeCB(f"chem_theory:{num}")
        await tb.cb_show_theory_topic(cb)
        assert cb.message.edits, f"topic {num} did not render"
        text, kb = cb.message.edits[-1]
        check_html(text)
        assert len(text) <= 4096, f"topic {num} too long: {len(text)} chars"
        assert tb.CHEMISTRY_THEORY[str(num)]["content"] in text
        assert tb.CHEMISTRY_THEORY[str(num)]["title"] in text
    print("all 16 chemistry theory topics render OK (HTML-balanced, under 4096 chars)")

    # 2. prev/next navigation at the boundaries and in the middle
    cb = FakeCB("chem_theory:1")
    await tb.cb_show_theory_topic(cb)
    _, kb = cb.message.edits[-1]
    assert "chem_theory:0" not in kb_data(kb)
    assert "chem_theory:2" in kb_data(kb)
    print("first topic has no 'previous' button OK")

    cb = FakeCB("chem_theory:16")
    await tb.cb_show_theory_topic(cb)
    _, kb = cb.message.edits[-1]
    assert "chem_theory:15" in kb_data(kb)
    assert "chem_theory:17" not in kb_data(kb)
    print("last topic has no 'next' button OK")

    # 3. unknown topic number -> alert, no crash
    cb = FakeCB("chem_theory:999")
    await tb.cb_show_theory_topic(cb)
    assert not cb.message.edits
    assert cb._answers and cb._answers[-1][1] is True
    print("unknown topic -> alert OK")

    print("ALL CHEMISTRY THEORY TESTS PASSED")

asyncio.run(main())
