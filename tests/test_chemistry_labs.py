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

def kb_texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row]

def kb_data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]

async def main():
    labs = {lab["number"]: lab for lab in tb.CHEMISTRY_LABS["labs"]}
    labs_with_summary = [1, 2, 3, 4, 5]
    for n in labs_with_summary:
        assert labs[n].get("summary"), f"lab {n} must have a summary"
    print(f"{len(labs_with_summary)} labs carry a 'summary' field")

    # 1. lab detail screen shows the "Кратко" button only when a summary exists
    for n, lab in labs.items():
        cb = FakeCB(f"lab:{n}")
        await tb.cb_show_lab(cb)
        assert cb.message.edits, f"lab {n} detail did not render"
        text, kb = cb.message.edits[-1]
        check_html(text)
        has_button = "lab_summary:" + str(n) in kb_data(kb)
        assert has_button == bool(lab.get("summary")), f"lab {n} button mismatch"
        if has_button:
            idx = kb_data(kb).index(f"lab_summary:{n}")
            assert kb_texts(kb)[idx] == "📝 Кратко (конспект)"
    print("lab:N screens show 'Кратко (конспект)' button iff summary exists: OK")

    # 2. each summary renders fully, valid HTML, under Telegram's message limit,
    #    and back button returns to the lab detail screen
    for n in labs_with_summary:
        cb = FakeCB(f"lab_summary:{n}")
        await tb.cb_lab_summary(cb)
        assert cb.message.edits, f"lab_summary {n} did not render"
        text, kb = cb.message.edits[-1]
        check_html(text)
        assert len(text) <= 4096, f"lab {n} summary too long: {len(text)} chars"
        assert labs[n]["summary"] in text
        assert f"Лабораторная работа {n}" in text
        assert kb_data(kb) == [f"lab:{n}"]
    print(f"all {len(labs_with_summary)} lab summaries render OK (HTML-balanced, under 4096 chars)")

    # 3. lab without a summary (lab 6) -> alert, no crash
    cb = FakeCB("lab_summary:6")
    await tb.cb_lab_summary(cb)
    assert not cb.message.edits
    assert cb._answers and cb._answers[-1][1] is True
    print("lab without summary -> alert OK")

    # 4. unknown lab number -> alert, no crash
    cb = FakeCB("lab_summary:999")
    await tb.cb_lab_summary(cb)
    assert not cb.message.edits
    assert cb._answers and cb._answers[-1][1] is True
    print("unknown lab -> alert OK")

    # 5. gate: lab_summary: must be classified as chemistry-gated
    assert tb.get_gated_subject("lab_summary:1") == "chemistry"
    print("gating classification OK")

    print("ALL CHEMISTRY LABS SUMMARY TESTS PASSED")

asyncio.run(main())
