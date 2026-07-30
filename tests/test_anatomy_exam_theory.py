# -*- coding: utf-8 -*-
"""Anatomy -> «Экзамен» -> «Вопросы теории»: official essay-style theory exam question
bank (Гайворонский и др.), browsable by section -> question list -> question detail.
Section I (СИСТЕМА ОРГАНОВ ОПОРЫ И ДВИЖЕНИЯ, 45 questions) is live; sections II-IV are
stub placeholders pending future content."""
import asyncio
from _bootstrap import tb
from html.parser import HTMLParser

NON_ADMIN = 918273645

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
    def __init__(self, data, uid=NON_ADMIN):
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
    sections = tb.ANATOMY_EXAM_THEORY_SECTIONS

    # 0. data integrity
    assert len(sections) == 4
    assert [s["id"] for s in sections] == [1, 2, 3, 4]
    titles = [s["title"] for s in sections]
    assert "СИСТЕМА ОРГАНОВ ОПОРЫ И ДВИЖЕНИЯ" in titles[0]
    s1 = sections[0]
    assert len(s1["questions"]) == 45
    seen_nums = set()
    for q in s1["questions"]:
        assert q["question"].strip()
        assert q["answer"].strip()
        assert q["num"] not in seen_nums
        seen_nums.add(q["num"])
        check_html(q["question"])
        # combined question+answer as rendered on the detail screen must fit one message
        combined = tb.get_anatomy_exam_theory_question_text(s1, q["num"])
        check_html(combined)
    assert seen_nums == set(range(1, 46))
    # sections II-IV are stub placeholders for now
    for s in sections[1:]:
        assert s["questions"] == []
    print(f"data integrity: 4 sections, section I has {len(s1['questions'])} well-formed questions, sections II-IV are stubs: OK")

    # 1. anatomy_exam_menu still lists theory as a live entry point (not a stub anymore)
    cb0 = FakeCB("anatomy_exam_menu")
    await tb.cb_anatomy_exam_menu(cb0)
    assert "anatomy_exam_theory" in kb_data(cb0.message.edits[-1][1])
    print("anatomy_exam_menu still links to anatomy_exam_theory: OK")

    # 2. anatomy_exam_theory renders the section list, free for a non-admin user
    cb1 = FakeCB("anatomy_exam_theory", uid=NON_ADMIN)
    await tb.cb_anatomy_exam_theory(cb1)
    text1, kb1 = cb1.message.edits[-1]
    check_html(text1)
    data1 = kb_data(kb1)
    for s in sections:
        assert f"anatomy_exam_theory_section:{s['id']}" in data1
    assert "anatomy_exam_menu" in data1
    labels1 = kb_texts(kb1)
    assert any("СИСТЕМА ОРГАНОВ ОПОРЫ И ДВИЖЕНИЯ" in t and "(45)" in t for t in labels1)
    assert any("СПЛАНХНОЛОГИЯ" in t and "🚧" in t for t in labels1)
    print("anatomy_exam_theory renders 4 sections, live section shows count, stub sections marked 🚧: OK")

    # 3. tapping a stub section (II-IV) -> alert, no crash, no navigation
    cb2 = FakeCB("anatomy_exam_theory_section:2", uid=NON_ADMIN)
    await tb.cb_anatomy_exam_theory_section(cb2)
    assert not cb2.message.edits
    assert cb2._answers and cb2._answers[0][1] is True
    print("tapping a stub section alerts instead of crashing: OK")

    # 4. unknown section id -> alert
    cb_bad_section = FakeCB("anatomy_exam_theory_section:999", uid=NON_ADMIN)
    await tb.cb_anatomy_exam_theory_section(cb_bad_section)
    assert not cb_bad_section.message.edits
    assert cb_bad_section._answers and cb_bad_section._answers[0][1] is True
    print("unknown section -> alert, no crash: OK")

    # 5. section I renders the question list, one button per question, numbered
    cb3 = FakeCB("anatomy_exam_theory_section:1", uid=NON_ADMIN)
    await tb.cb_anatomy_exam_theory_section(cb3)
    text3, kb3 = cb3.message.edits[-1]
    check_html(text3)
    data3 = kb_data(kb3)
    for q in s1["questions"]:
        assert f"anatomy_exam_theory_q:1:{q['num']}" in data3
    assert "anatomy_exam_theory" in data3
    print("section I question list shows all 45 questions + back button: OK")

    # 6. opening question 1 shows the question text and full answer, with forward-only nav
    cb4 = FakeCB("anatomy_exam_theory_q:1:1", uid=NON_ADMIN)
    await tb.cb_anatomy_exam_theory_question(cb4)
    text4, kb4 = cb4.message.edits[-1]
    check_html(text4)
    q1 = next(q for q in s1["questions"] if q["num"] == 1)
    assert q1["question"] in text4
    assert q1["answer"] in text4
    data4 = kb_data(kb4)
    assert "anatomy_exam_theory_q:1:2" in data4
    assert not any(d == "anatomy_exam_theory_q:1:0" for d in data4)
    assert "anatomy_exam_theory_section:1" in data4
    assert "anatomy_exam_theory" in data4
    print("question 1 detail: full text shown, no ⬅️ Назад (first question), ➡️ Вперёд present: OK")

    # 7. middle question has both prev/next nav; last question has no next
    cb5 = FakeCB("anatomy_exam_theory_q:1:20", uid=NON_ADMIN)
    await tb.cb_anatomy_exam_theory_question(cb5)
    data5 = kb_data(cb5.message.edits[-1][1])
    assert "anatomy_exam_theory_q:1:19" in data5
    assert "anatomy_exam_theory_q:1:21" in data5

    cb6 = FakeCB("anatomy_exam_theory_q:1:45", uid=NON_ADMIN)
    await tb.cb_anatomy_exam_theory_question(cb6)
    data6 = kb_data(cb6.message.edits[-1][1])
    assert "anatomy_exam_theory_q:1:44" in data6
    assert not any(d == "anatomy_exam_theory_q:1:46" for d in data6)
    print("middle question has both nav buttons; last question has no ➡️ Вперёд: OK")

    # 8. unknown question number / section -> alert, no crash
    cb_bad_q = FakeCB("anatomy_exam_theory_q:1:999", uid=NON_ADMIN)
    await tb.cb_anatomy_exam_theory_question(cb_bad_q)
    assert not cb_bad_q.message.edits
    assert cb_bad_q._answers and cb_bad_q._answers[0][1] is True

    cb_bad_q2 = FakeCB("anatomy_exam_theory_q:2:1", uid=NON_ADMIN)
    await tb.cb_anatomy_exam_theory_question(cb_bad_q2)
    assert not cb_bad_q2.message.edits
    assert cb_bad_q2._answers and cb_bad_q2._answers[0][1] is True
    print("unknown question number / question in a still-stub section -> alert, no crash: OK")

    print("ALL ANATOMY EXAM THEORY TESTS PASSED")

asyncio.run(main())
