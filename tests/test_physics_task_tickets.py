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
    assert len(tb.PHYSICS_TASK_TICKETS) == 8

    # 0. every ticket has exactly 5 non-empty, HTML-balanced tasks
    for num, ticket in tb.PHYSICS_TASK_TICKETS.items():
        tasks = ticket["tasks"]
        assert len(tasks) == 5, num
        nums = [t["num"] for t in tasks]
        assert nums == [1, 2, 3, 4, 5], (num, nums)
        for task in tasks:
            for field in ("title", "condition", "solution"):
                assert task[field], (num, task["num"], field)
                check_html(task[field])
    print("all 8 task tickets have 5 non-empty, HTML-balanced tasks: OK")

    # 1. physics_tickets menu exposes the new entry point
    menu = tb.get_physics_tickets_menu()
    assert "physics_task_tickets" in kb_data(menu)
    print("physics tickets menu exposes 'Билеты с задачами': OK")

    # 2. physics_task_tickets renders the ticket list
    cb = FakeCB("physics_task_tickets")
    await tb.cb_physics_task_tickets(cb)
    assert cb.message.edits
    text, kb = cb.message.edits[-1]
    check_html(text)
    data = kb_data(kb)
    for num in tb.PHYSICS_TASK_TICKETS:
        assert f"phys_task_ticket:{num}" in data
    print("physics_task_tickets list screen: OK")

    # 3. ticket detail shows the 5-task list directly (no intermediate MCQ step)
    cb2 = FakeCB("phys_task_ticket:1")
    await tb.cb_phys_task_ticket(cb2)
    assert cb2.message.edits
    text2, kb2 = cb2.message.edits[-1]
    check_html(text2)
    data2 = kb_data(kb2)
    for i in range(1, 6):
        assert f"phys_task_ticket_show:1:{i}" in data2
    print("phys_task_ticket detail lists 5 tasks: OK")

    # 4. unknown ticket -> alert, no crash
    cb3 = FakeCB("phys_task_ticket:999")
    await tb.cb_phys_task_ticket(cb3)
    assert not cb3.message.edits
    assert cb3._answers and cb3._answers[-1][1] is True
    print("unknown ticket -> alert OK")

    # 5. every task in every ticket renders correctly with condition+solution present
    for num, ticket in tb.PHYSICS_TASK_TICKETS.items():
        for task in ticket["tasks"]:
            cb_t = FakeCB(f"phys_task_ticket_show:{num}:{task['num']}")
            await tb.cb_phys_task_ticket_show(cb_t)
            assert cb_t.message.edits, (num, task["num"])
            text_t, _ = cb_t.message.edits[-1]
            check_html(text_t)
            assert tb.strip_html_tags(task["condition"]) in text_t or task["condition"] in text_t
    print("every task in every ticket renders OK")

    # 6. prev/next navigation at the boundaries for ticket 1
    cb4 = FakeCB("phys_task_ticket_show:1:1")
    await tb.cb_phys_task_ticket_show(cb4)
    _, kb4 = cb4.message.edits[-1]
    texts4 = kb_texts(kb4)
    data4 = kb_data(kb4)
    assert not any("Предыдущая" in t for t in texts4)
    assert "phys_task_ticket_show:1:2" in data4
    print("first task has no 'previous' button OK")

    cb5 = FakeCB("phys_task_ticket_show:1:5")
    await tb.cb_phys_task_ticket_show(cb5)
    _, kb5 = cb5.message.edits[-1]
    texts5 = kb_texts(kb5)
    data5 = kb_data(kb5)
    assert not any("Следующая" in t for t in texts5)
    assert "phys_task_ticket_show:1:4" in data5
    print("last task has no 'next' button OK")

    # 7. unknown task index -> alert, no crash
    cb6 = FakeCB("phys_task_ticket_show:1:99")
    await tb.cb_phys_task_ticket_show(cb6)
    assert not cb6.message.edits
    assert cb6._answers and cb6._answers[-1][1] is True
    print("unknown task index -> alert OK")

    # 8. gate: all new callbacks must be classified as physics-gated
    assert tb.get_gated_subject("physics_task_tickets") == "physics"
    assert tb.get_gated_subject("phys_task_ticket:1") == "physics"
    assert tb.get_gated_subject("phys_task_ticket_show:1:1") == "physics"
    print("gating classification OK")

    print("ALL PHYSICS TASK TICKETS TESTS PASSED")

asyncio.run(main())
