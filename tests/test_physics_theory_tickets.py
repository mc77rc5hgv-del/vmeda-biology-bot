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
    assert "26" in tb.PHYSICS_THEORY_TICKETS, "ticket 26 must be present"
    ticket26 = tb.PHYSICS_THEORY_TICKETS["26"]
    assert len(ticket26["questions"]) == 2

    # 1. physics_theory_tickets renders the ticket list (not the "coming soon" stub)
    cb = FakeCB("physics_theory_tickets")
    await tb.cb_physics_theory_tickets(cb)
    assert cb.message.edits, "physics_theory_tickets did not render"
    text, kb = cb.message.edits[-1]
    check_html(text)
    assert "Скоро будут добавлены" not in text
    assert "phys_theory_ticket:26" in kb_data(kb)
    print("physics_theory_tickets list screen OK")

    # 2. ticket detail lists a button per question
    cb = FakeCB("phys_theory_ticket:26")
    await tb.cb_phys_theory_ticket(cb)
    assert cb.message.edits, "ticket detail did not render"
    text, kb = cb.message.edits[-1]
    check_html(text)
    data = kb_data(kb)
    assert "phys_theory_q:26:0" in data
    assert "phys_theory_q:26:1" in data
    print("phys_theory_ticket detail screen OK")

    # 3. unknown ticket number -> alert, no crash
    cb = FakeCB("phys_theory_ticket:999")
    await tb.cb_phys_theory_ticket(cb)
    assert not cb.message.edits
    assert cb._answers and cb._answers[-1][1] is True
    print("unknown ticket -> alert OK")

    # 4. each question renders non-empty title+answer, valid HTML, under Telegram's message limit
    for idx, q in enumerate(ticket26["questions"]):
        cb = FakeCB(f"phys_theory_q:26:{idx}")
        await tb.cb_phys_theory_question(cb)
        assert cb.message.edits, f"question {idx} did not render"
        text, kb = cb.message.edits[-1]
        check_html(text)
        assert len(text) <= 4096, f"question {idx} answer too long: {len(text)} chars"
        assert q["title"] in text and q["answer"] in text
    print("both ticket-26 questions render OK (HTML-balanced, under 4096 chars)")

    # 5. prev/next navigation at the boundaries
    cb = FakeCB("phys_theory_q:26:0")
    await tb.cb_phys_theory_question(cb)
    _, kb = cb.message.edits[-1]
    texts = kb_texts(kb)
    data = kb_data(kb)
    assert not any("Предыдущий" in t for t in texts)
    assert "phys_theory_q:26:1" in data
    assert "phys_theory_ticket:26" in data
    print("first question has no 'previous' button OK")

    cb = FakeCB("phys_theory_q:26:1")
    await tb.cb_phys_theory_question(cb)
    _, kb = cb.message.edits[-1]
    texts = kb_texts(kb)
    data = kb_data(kb)
    assert not any("Следующий" in t for t in texts)
    assert "phys_theory_q:26:0" in data
    print("last question has no 'next' button OK")

    # 6. unknown question index -> alert, no crash
    cb = FakeCB("phys_theory_q:26:99")
    await tb.cb_phys_theory_question(cb)
    assert not cb.message.edits
    assert cb._answers and cb._answers[-1][1] is True
    print("unknown question index -> alert OK")

    # 7. gate: phys_theory_ticket:/phys_theory_q: must be classified as physics-gated
    assert tb.get_gated_subject("phys_theory_ticket:26") == "physics"
    assert tb.get_gated_subject("phys_theory_q:26:0") == "physics"
    print("gating classification OK")

    print("ALL PHYSICS THEORY TICKETS TESTS PASSED")

asyncio.run(main())
