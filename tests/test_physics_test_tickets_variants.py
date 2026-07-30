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
    def __init__(self, data, uid=111222333):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
        self._answers = []
    async def answer(self, text=None, show_alert=False):
        self._answers.append((text, show_alert))

def kb_data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]

NEW_VARIANTS = ["9", "16", "17", "23", "24", "32", "43", "44", "45", "55",
                "57", "75", "77", "78", "79", "87", "88", "90", "99"]
VARIANTS_WITH_TASKS = ["16", "17", "24", "32", "43", "45", "55", "57", "75",
                       "77", "78", "79", "87", "88", "90", "99"]
VARIANTS_WITHOUT_TASKS = ["9", "23", "44"]

async def main():
    # 0. every new variant is present with correct structural shape
    for num in NEW_VARIANTS:
        assert num in tb.PHYSICS_TEST_TICKETS, num
        ticket = tb.PHYSICS_TEST_TICKETS[num]
        assert ticket["title"] == f"Вариант {num}", ticket["title"]
        qs = ticket["questions"]
        assert len(qs) in (5, 10), (num, len(qs))
        for q in qs:
            assert set(q["options"].keys()) == {"A", "B", "C", "D"}, (num, q["num"])
            assert q["correct"] in "ABCD", (num, q["num"])
            assert q["text"], (num, q["num"])
            for letter in "ABCD":
                assert q["options"][letter], (num, q["num"], letter)
    print(f"all {len(NEW_VARIANTS)} new variants have valid MCQ structure: OK")

    # 0b. partial-recovery variants (32, 43) have exactly 5 questions; the rest have 10
    assert len(tb.PHYSICS_TEST_TICKETS["32"]["questions"]) == 5
    assert len(tb.PHYSICS_TEST_TICKETS["43"]["questions"]) == 5
    for num in set(NEW_VARIANTS) - {"32", "43"}:
        assert len(tb.PHYSICS_TEST_TICKETS[num]["questions"]) == 10, num
    print("question counts match recovered data (5 for partial variants, 10 otherwise): OK")

    # 1. variants with a recovered problem page carry a 5-task "tasks" field; the rest don't
    for num in VARIANTS_WITH_TASKS:
        assert tb.PHYSICS_TEST_TICKETS[num].get("tasks"), num
        assert len(tb.PHYSICS_TEST_TICKETS[num]["tasks"]) == 5, num
    for num in VARIANTS_WITHOUT_TASKS:
        assert not tb.PHYSICS_TEST_TICKETS[num].get("tasks"), num
    print("tasks field present only for variants with a recovered problem page: OK")

    # 2. physics_test_tickets list screen includes every new variant
    cb = FakeCB("physics_test_tickets")
    await tb.cb_physics_test_tickets(cb)
    text, kb = cb.message.edits[-1]
    check_html(text)
    data = kb_data(kb)
    for num in NEW_VARIANTS:
        assert f"phys_test_ticket:{num}" in data, num
    print("physics_test_tickets list includes all new variants: OK")

    # 3. each new variant renders its MCQ screen with exactly one ✅ marker per question
    for num in NEW_VARIANTS:
        cb2 = FakeCB(f"phys_test_ticket:{num}")
        await tb.cb_phys_test_ticket(cb2)
        assert cb2.message.edits, num
        text2, kb2 = cb2.message.edits[-1]
        check_html(text2)
        assert text2.count("✅") == len(tb.PHYSICS_TEST_TICKETS[num]["questions"]), num
        data2 = kb_data(kb2)
        if tb.PHYSICS_TEST_TICKETS[num].get("tasks"):
            assert f"phys_test_ticket_tasks:{num}" in data2, num
        else:
            assert f"phys_test_ticket_tasks:{num}" not in data2, num
    print("every new variant renders MCQ screen with exactly one ✅ per question, "
          "Часть 2 button only when tasks exist: OK")

    print("ALL PHYSICS TEST TICKET VARIANTS TESTS PASSED")

asyncio.run(main())
