# -*- coding: utf-8 -*-
import asyncio, os
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
    assert len(text) <= 4096, f"too long: {len(text)} chars"

class FakeUser:
    def __init__(self, uid):
        self.id = uid

class FakeMsg:
    def __init__(self):
        self.edits = []
        self.answers = []
        self.deleted = False
    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self
    async def delete(self):
        self.deleted = True
    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs.get("reply_markup")))
        return self
    async def answer_photo(self, photo, **kwargs):
        self.answers.append((kwargs.get("caption"), kwargs.get("reply_markup")))
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
    nums = sorted(tb.PHYSICS_EXTRA_QUESTIONS.keys(), key=int)
    assert len(nums) == 13, f"expected exactly 13 questions, got {len(nums)}"
    print(f"loaded {len(nums)} extra questions from teachers")

    # 1. menu button present on the Physics menu
    menu = tb.get_physics_menu()
    assert "physics_extra" in kb_data(menu), "menu_physics должен вести к разделу доп. вопросов"
    idx = kb_data(menu).index("physics_extra")
    assert kb_texts(menu)[idx] == "⭐ Доп. вопросы от преподавателей"
    print("physics menu button OK")

    # 2. list screen renders a button for every question
    cb = FakeCB("physics_extra")
    await tb.cb_physics_extra(cb)
    assert cb.message.edits, "physics_extra list did not render"
    text, kb = cb.message.edits[-1]
    check_html(text)
    data = kb_data(kb)
    for n in nums:
        assert f"physics_extra_q:{n}" in data, f"missing button for question {n}"
    assert "menu_physics" in data
    print("physics_extra list screen OK")

    # 3. every question renders (either as edited text, or as photo+caption/text for the ones
    # with an "image" field), valid HTML, under Telegram's message/caption limits, referencing
    # the real title/answer, and every referenced image file actually exists on disk.
    for n in nums:
        q = tb.PHYSICS_EXTRA_QUESTIONS[n]
        assert q.get("title"), f"question {n} missing title"
        assert q.get("answer"), f"question {n} missing answer"
        image = q.get("image")
        if image:
            assert os.path.exists(os.path.join(tb.IMAGES_DIR, image)), f"missing image file: {image}"

        cb = FakeCB(f"physics_extra_q:{n}")
        await tb.cb_physics_extra_question(cb)
        if image:
            assert cb.message.deleted, f"question {n} has an image but didn't take the photo path"
            assert cb.message.answers, f"question {n} sent nothing"
            full_text = "\n".join(t for t, _ in cb.message.answers if t)
        else:
            assert cb.message.edits, f"question {n} did not render"
            full_text, _ = cb.message.edits[-1]
        check_html(full_text)
        assert q["title"] in full_text
    print(f"all {len(nums)} questions render OK (HTML-balanced, under limits, images verified)")

    # 4. prev/next navigation is correct at the boundaries and in the middle
    cb = FakeCB(f"physics_extra_q:{nums[0]}")
    await tb.cb_physics_extra_question(cb)
    _, kb = cb.message.edits[-1] if cb.message.edits else cb.message.answers[-1]
    texts = kb_texts(kb)
    data = kb_data(kb)
    assert f"physics_extra_q:{nums[1]}" in data
    assert not any("Предыдущий" in t for t in texts)
    print("first question has no 'previous' button OK")

    cb = FakeCB(f"physics_extra_q:{nums[-1]}")
    await tb.cb_physics_extra_question(cb)
    _, kb = cb.message.edits[-1] if cb.message.edits else cb.message.answers[-1]
    data = kb_data(kb)
    assert f"physics_extra_q:{nums[-2]}" in data
    texts = kb_texts(kb)
    assert not any("Следующий" in t for t in texts)
    print("last question has no 'next' button OK")

    mid = nums[len(nums) // 2]
    idx = nums.index(mid)
    cb = FakeCB(f"physics_extra_q:{mid}")
    await tb.cb_physics_extra_question(cb)
    _, kb = cb.message.edits[-1] if cb.message.edits else cb.message.answers[-1]
    data = kb_data(kb)
    assert f"physics_extra_q:{nums[idx - 1]}" in data
    assert f"physics_extra_q:{nums[idx + 1]}" in data
    assert "physics_extra" in data
    print("middle question has both prev/next buttons OK")

    # 5. unknown question number -> alert, not a crash
    cb = FakeCB("physics_extra_q:99999")
    await tb.cb_physics_extra_question(cb)
    assert not cb.message.edits and not cb.message.answers, "unknown question must not render a screen"
    assert cb._answers and cb._answers[-1][1] is True
    print("unknown question -> alert OK")

    # 6. gate: physics_extra / physics_extra_q: must be classified as physics-gated
    assert tb.get_gated_subject("physics_extra") == "physics"
    assert tb.get_gated_subject("physics_extra_q:1") == "physics"
    print("gating classification OK")

    print("ALL PHYSICS EXTRA QUESTIONS TESTS PASSED")

asyncio.run(main())
