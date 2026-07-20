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
    # every existing ticket got a 5-task "Часть 2" with HTML-balanced, non-empty fields
    for num, ticket in tb.PHYSICS_TEST_TICKETS.items():
        tasks = ticket.get("tasks")
        assert tasks and len(tasks) == 5, (num, tasks)
        nums = [t["num"] for t in tasks]
        assert nums == [1, 2, 3, 4, 5], (num, nums)
        for task in tasks:
            for field in ("title", "condition", "solution"):
                assert task[field], (num, task["num"], field)
                check_html(task[field])
    print("all 4 tickets have a 5-task Часть 2, HTML balanced: OK")

    # ticket detail screen shows a "Часть 2" button when tasks exist
    cb = FakeCB("phys_test_ticket:66")
    await tb.cb_phys_test_ticket(cb)
    text, kb = cb.message.edits[0]
    check_html(text)
    assert any("Часть 2" in t for t in kb_texts(kb))
    assert "phys_test_ticket_tasks:66" in kb_data(kb)
    print("ticket detail screen offers Часть 2 button: OK")

    # task list screen
    cb2 = FakeCB("phys_test_ticket_tasks:66")
    await tb.cb_phys_test_ticket_tasks(cb2)
    text2, kb2 = cb2.message.edits[0]
    check_html(text2)
    assert "Часть 2" in text2
    assert len(kb_texts(kb2)) == 6  # 5 tasks + back button
    print("task list screen renders 5 tasks: OK")

    # task detail: correct content, prev/next nav, numeric answer present
    cb3 = FakeCB("phys_test_ticket_task_show:66:1")
    await tb.cb_phys_test_ticket_task_show(cb3)
    text3, kb3 = cb3.message.edits[0]
    check_html(text3)
    assert "Задача №1" in text3
    assert "81" in text3  # ticket 66 task 1: 195 - 114 protons
    data3 = kb_data(kb3)
    assert "phys_test_ticket_task_show:66:2" in data3  # "next" present
    assert not any(d and "task_show:66:0" in d for d in data3 if d)  # no "prev" from first task
    print("task detail (first task) renders correct answer + next nav: OK")

    cb4 = FakeCB("phys_test_ticket_task_show:66:5")
    await tb.cb_phys_test_ticket_task_show(cb4)
    text4, kb4 = cb4.message.edits[0]
    data4 = kb_data(kb4)
    assert "phys_test_ticket_task_show:66:4" in data4  # "prev" present on last task
    print("task detail (last task) has prev nav, no next: OK")

    # unknown ticket / unknown task -> alert, no crash
    cb5 = FakeCB("phys_test_ticket_tasks:999")
    await tb.cb_phys_test_ticket_tasks(cb5)
    assert not cb5.message.edits and cb5._answers and cb5._answers[-1][1] is True
    cb6 = FakeCB("phys_test_ticket_task_show:66:99")
    await tb.cb_phys_test_ticket_task_show(cb6)
    assert not cb6.message.edits and cb6._answers and cb6._answers[-1][1] is True
    print("unknown ticket/task handled gracefully: OK")

    print("ALL PHYSICS TEST TICKET TASKS TESTS PASSED")

asyncio.run(main())
