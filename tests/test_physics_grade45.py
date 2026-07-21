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
    nums = sorted(tb.PHYSICS_GRADE45_QUESTIONS.keys(), key=int)
    assert len(nums) == 60, f"expected exactly 60 questions, got {len(nums)}"
    print(f"loaded {len(nums)} questions for the 4/5 section")

    # 1. menu buttons present on the Physics menu (list screen + docx download)
    menu = tb.get_physics_menu()
    assert "physics_grade45" in kb_data(menu), "menu_physics должен вести к новому разделу"
    idx = kb_data(menu).index("physics_grade45")
    assert kb_texts(menu)[idx] == "❓ (60 вопросов) на 4/5"
    assert "download_physics_grade45" in kb_data(menu), "menu_physics должен предлагать файл со всеми вопросами"
    print("physics menu buttons OK")

    # 2. list screen renders a button for every question, each with correct callback_data
    cb = FakeCB("physics_grade45")
    await tb.cb_physics_grade45(cb)
    assert cb.message.edits, "physics_grade45 list did not render"
    text, kb = cb.message.edits[-1]
    check_html(text)
    data = kb_data(kb)
    for n in nums:
        assert f"physics45_q:{n}" in data, f"missing button for question {n}"
    print("physics_grade45 list screen OK")

    # 3. every question renders non-empty title+answer, valid HTML, under Telegram's message limit
    for n in nums:
        cb = FakeCB(f"physics45_q:{n}")
        await tb.cb_physics_grade45_question(cb)
        assert cb.message.edits, f"question {n} did not render"
        text, kb = cb.message.edits[-1]
        check_html(text)
        assert len(text) <= 4096, f"question {n} answer too long: {len(text)} chars"
        q = tb.PHYSICS_GRADE45_QUESTIONS[n]
        assert q.get("title"), f"question {n} missing title"
        assert q.get("answer"), f"question {n} missing answer"
        assert q["title"] in text and q["answer"] in text
    print(f"all {len(nums)} questions render OK (HTML-balanced, under 4096 chars)")

    # 4. prev/next navigation is correct at the boundaries and in the middle
    cb = FakeCB(f"physics45_q:{nums[0]}")
    await tb.cb_physics_grade45_question(cb)
    _, kb = cb.message.edits[-1]
    texts = kb_texts(kb)
    data = kb_data(kb)
    assert f"physics45_q:{nums[1]}" in data
    assert not any("Предыдущий" in t for t in texts)
    print("first question has no 'previous' button OK")

    cb = FakeCB(f"physics45_q:{nums[-1]}")
    await tb.cb_physics_grade45_question(cb)
    _, kb = cb.message.edits[-1]
    data = kb_data(kb)
    assert f"physics45_q:{nums[-2]}" in data
    print("last question has no 'next' button OK")

    mid = nums[len(nums) // 2]
    idx = nums.index(mid)
    cb = FakeCB(f"physics45_q:{mid}")
    await tb.cb_physics_grade45_question(cb)
    _, kb = cb.message.edits[-1]
    data = kb_data(kb)
    assert f"physics45_q:{nums[idx - 1]}" in data
    assert f"physics45_q:{nums[idx + 1]}" in data
    assert "physics_grade45" in data
    print("middle question has both prev/next buttons OK")

    # 5. unknown question number -> alert, not a crash
    cb = FakeCB("physics45_q:99999")
    await tb.cb_physics_grade45_question(cb)
    assert not cb.message.edits, "unknown question must not render a screen"
    assert cb._answers and cb._answers[-1][1] is True
    print("unknown question -> alert OK")

    # 6. gate: physics_grade45 / physics45_q: must be classified as physics-gated
    assert tb.get_gated_subject("physics_grade45") == "physics"
    assert tb.get_gated_subject("physics45_q:1") == "physics"
    print("gating classification OK")

    print("ALL PHYSICS GRADE45 TESTS PASSED")

asyncio.run(main())
