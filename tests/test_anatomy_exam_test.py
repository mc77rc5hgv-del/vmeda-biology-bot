# -*- coding: utf-8 -*-
"""Anatomy -> «Экзамен» -> «ТЕСТ»: 1040-question official test bank (Гайворонский и др.,
2021), split into 10 parts, full sequential run-through per part, early-stop + mistake
review. Also covers the anatomy_root top-level split (ВЕСЬ КУРС АНАТОМИИ / ЭКЗАМЕН)."""
import asyncio
from _bootstrap import tb
from html.parser import HTMLParser

ADMIN_ID = next(iter(tb.ADMIN_IDS))
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
    # 0. data integrity: 10 parts, 1040 questions total, every question well-formed
    parts = tb.ANATOMY_EXAM_TEST_PARTS
    assert len(parts) == 10
    total = sum(len(p["questions"]) for p in parts)
    assert total == 1040, total
    seen_nums = set()
    for part in parts:
        assert part["questions"], part["id"]
        for q in part["questions"]:
            assert q["question"].strip()
            assert 4 <= len(q["options"]) <= 5, (part["id"], q["num"], q["options"])
            assert q["correct"] in q["options"], (part["id"], q["num"])
            assert q["num"] not in seen_nums, q["num"]
            seen_nums.add(q["num"])
    assert seen_nums == set(range(1, 1041))
    print(f"data integrity: 10 parts, {total} questions, all numbered 1..1040 with a valid answer key: OK")

    # 1. anatomy_root is the new top-level split (ВЕСЬ КУРС АНАТОМИИ / ЭКЗАМЕН)
    cb = FakeCB("anatomy_root")
    await tb.cb_anatomy_root(cb)
    text, kb = cb.message.edits[-1]
    check_html(text)
    data = kb_data(kb)
    assert "anatomy_menu" in data and "anatomy_exam_menu" in data and "back_to_main" in data
    print("anatomy_root renders the course/exam split: OK")

    # 2. main-menu and admin-announcement entry points now point at anatomy_root, not anatomy_menu
    main_menu_data = kb_data(tb.get_main_menu(user_id=NON_ADMIN))
    assert "anatomy_root" in main_menu_data and "anatomy_menu" not in main_menu_data
    ann_data = kb_data(tb.get_anatomy_announcement_keyboard())
    assert "anatomy_root" in ann_data
    print("main menu + admin announcement point at anatomy_root: OK")

    # 3. anatomy_menu (ВЕСЬ КУРС АНАТОМИИ) still renders the module list, now one level
    # deeper — its own back button returns to anatomy_root, not back_to_main
    cb2 = FakeCB("anatomy_menu")
    await tb.cb_anatomy_menu(cb2)
    text2, kb2 = cb2.message.edits[-1]
    check_html(text2)
    assert "Весь курс анатомии" in text2
    assert "anatomy_root" in kb_data(kb2)
    print("anatomy_menu (course list) still works, back button now anatomy_root: OK")

    # 4. anatomy_exam_menu offers practice/theory/test entry points
    cb3 = FakeCB("anatomy_exam_menu")
    await tb.cb_anatomy_exam_menu(cb3)
    text3, kb3 = cb3.message.edits[-1]
    check_html(text3)
    exam_data = kb_data(kb3)
    assert "anatomy_exam_practice" in exam_data
    assert "anatomy_exam_theory" in exam_data
    assert "anatomy_exam_test_menu" in exam_data
    assert "anatomy_root" in exam_data
    print("anatomy_exam_menu renders practice/theory/test entries: OK")

    # 5. Вопросы практики and Вопросы теории are real features now, free for everyone —
    # see test_anatomy_exam_practice.py / test_anatomy_exam_theory.py.
    cb4 = FakeCB("anatomy_exam_practice")
    await tb.cb_anatomy_exam_practice(cb4)
    assert cb4.message.edits
    print("Вопросы практики renders (not a stub anymore): OK")

    # 6. ТЕСТ part list shows all 10 parts, free for a non-admin user
    cb5 = FakeCB("anatomy_exam_test_menu", uid=NON_ADMIN)
    await tb.cb_anatomy_exam_test_menu(cb5)
    text5, kb5 = cb5.message.edits[-1]
    check_html(text5)
    test_menu_data = kb_data(kb5)
    for part in parts:
        assert f"anatomy_exam_test_start:{part['id']}" in test_menu_data
        assert part["topics"].strip(), part["id"]
        assert part["topics"] in text5, f"part {part['id']} topics missing from menu text"
    assert "anatomy_exam_menu" in test_menu_data
    print("ТЕСТ part-list menu lists all 10 parts with topic labels, reachable by a non-admin: OK")

    # 7. starting a part renders the first question with lettered option buttons + stop
    cb6 = FakeCB("anatomy_exam_test_start:1", uid=NON_ADMIN)
    await tb.cb_anatomy_exam_test_start(cb6)
    text6, kb6 = cb6.message.edits[-1]
    check_html(text6)
    part1 = tb.get_anatomy_exam_test_part(1)
    q1 = part1["questions"][0]
    assert q1["question"] in text6
    for letter, opt in q1["options"].items():
        assert opt in text6
    btn_data6 = kb_data(kb6)
    for letter in q1["options"]:
        assert f"anatomy_exam_test_answer:{letter}" in btn_data6
    assert "anatomy_exam_test_stop" in btn_data6
    print("starting a part renders question 1 with option buttons + stop: OK")

    # 8. unknown part -> alert, no session created
    cb_bad = FakeCB("anatomy_exam_test_start:999", uid=NON_ADMIN)
    await tb.cb_anatomy_exam_test_start(cb_bad)
    assert not cb_bad.message.edits
    assert cb_bad._answers and cb_bad._answers[0][1] is True
    print("unknown part -> alert, no crash: OK")

    # 9. answering with no active session -> alert
    cb_stale = FakeCB("anatomy_exam_test_answer:а", uid=555111222)
    await tb.cb_anatomy_exam_test_answer(cb_stale)
    assert not cb_stale.message.edits
    assert cb_stale._answers and cb_stale._answers[0][1] is True
    print("answering without an active session -> alert: OK")

    # 10. full sequential run-through of the smallest part (102 questions, part 1) —
    # deliberately answer the first 3 wrong (to populate mistakes) and the rest correctly
    uid = 700100200
    cb7 = FakeCB("anatomy_exam_test_start:1", uid=uid)
    await tb.cb_anatomy_exam_test_start(cb7)
    assert cb7.message.edits
    n_questions = len(part1["questions"])
    n_wrong = 3
    for i in range(n_questions):
        session = tb.ANATOMY_EXAM_TEST_SESSIONS[uid]
        q = session["queue"][session["index"]]
        correct = q["correct"]
        if i < n_wrong:
            chosen = next(letter for letter in q["options"] if letter != correct)
        else:
            chosen = correct
        cb_ans = FakeCB(f"anatomy_exam_test_answer:{chosen}", uid=uid)
        await tb.cb_anatomy_exam_test_answer(cb_ans)
        if chosen == correct:
            assert cb_ans._answers[0][1] is False, "correct answer should not use show_alert"
        else:
            assert cb_ans._answers[0][1] is True
            assert f"{correct})" in (cb_ans._answers[0][0] or "")
        if i < n_questions - 1:
            assert cb_ans.message.edits, f"question {i+2} should render"
            check_html(cb_ans.message.edits[-1][0])
        else:
            last_cb = cb_ans
    assert uid not in tb.ANATOMY_EXAM_TEST_SESSIONS, "session must be cleared after the last question"
    summary_text, summary_kb = last_cb.message.edits[-1]
    check_html(summary_text)
    assert "Тест завершён" in summary_text
    assert f"{n_questions - n_wrong}" in summary_text
    assert f"{n_wrong}" in summary_text
    summary_data = kb_data(summary_kb)
    assert "anatomy_exam_test_mistakes:0" in summary_data
    assert "anatomy_exam_test_start:1" in summary_data
    assert "anatomy_exam_test_menu" in summary_data
    print(f"full sequential run ({n_questions} q, {n_wrong} deliberate mistakes) -> correct summary: OK")

    # 11. mistake review: paginated, shows correct/chosen markers, nav respects boundaries
    cb_m0 = FakeCB("anatomy_exam_test_mistakes:0", uid=uid)
    await tb.cb_anatomy_exam_test_mistakes(cb_m0)
    m0_text, m0_kb = cb_m0.message.edits[-1]
    check_html(m0_text)
    assert "✅" in m0_text and "❌" in m0_text
    m0_data = kb_data(m0_kb)
    assert not any(d and "mistakes:-1" in d for d in m0_data if d)
    assert "anatomy_exam_test_mistakes:1" in m0_data
    assert "anatomy_exam_test_start:1" in m0_data

    cb_m_last = FakeCB(f"anatomy_exam_test_mistakes:{n_wrong - 1}", uid=uid)
    await tb.cb_anatomy_exam_test_mistakes(cb_m_last)
    m_last_data = kb_data(cb_m_last.message.edits[-1][1])
    assert not any(d == f"anatomy_exam_test_mistakes:{n_wrong}" for d in m_last_data)

    cb_m_oob = FakeCB(f"anatomy_exam_test_mistakes:{n_wrong}", uid=uid)
    await tb.cb_anatomy_exam_test_mistakes(cb_m_oob)
    assert not cb_m_oob.message.edits
    assert cb_m_oob._answers and cb_m_oob._answers[0][1] is True
    print("mistake review paginates correctly with boundary nav: OK")

    # 12. mistakes for an unknown/expired user -> alert
    cb_no_mistakes = FakeCB("anatomy_exam_test_mistakes:0", uid=999888777)
    await tb.cb_anatomy_exam_test_mistakes(cb_no_mistakes)
    assert not cb_no_mistakes.message.edits
    assert cb_no_mistakes._answers and cb_no_mistakes._answers[0][1] is True
    print("mistake review for a user with none -> alert: OK")

    # 13. early stop mid-test renders an aborted summary and clears the session
    uid2 = 700100201
    cb8 = FakeCB("anatomy_exam_test_start:6", uid=uid2)  # Лечебное дело, часть 1/5
    await tb.cb_anatomy_exam_test_start(cb8)
    session2 = tb.ANATOMY_EXAM_TEST_SESSIONS[uid2]
    q = session2["queue"][0]
    cb_ans2 = FakeCB(f"anatomy_exam_test_answer:{q['correct']}", uid=uid2)
    await tb.cb_anatomy_exam_test_answer(cb_ans2)
    cb_stop = FakeCB("anatomy_exam_test_stop", uid=uid2)
    await tb.cb_anatomy_exam_test_stop(cb_stop)
    assert uid2 not in tb.ANATOMY_EXAM_TEST_SESSIONS
    stop_text, stop_kb = cb_stop.message.edits[-1]
    check_html(stop_text)
    assert "прерван" in stop_text
    assert "Отвечено: <b>1</b> из 106" in stop_text
    print("early stop shows an aborted summary and clears the session: OK")

    # 14. stopping with no active session is a silent no-op (not an error)
    cb_stop_stale = FakeCB("anatomy_exam_test_stop", uid=uid2)
    await tb.cb_anatomy_exam_test_stop(cb_stop_stale)
    assert not cb_stop_stale.message.edits
    print("stop with no active session is a silent no-op: OK")

    # 15. mode defaults to normal; the toggle button flips it and re-renders the menu
    uid3 = 700100202
    assert tb.get_anatomy_exam_test_mode(uid3) == "normal"
    cb_menu0 = FakeCB("anatomy_exam_test_menu", uid=uid3)
    await tb.cb_anatomy_exam_test_menu(cb_menu0)
    menu0_text, menu0_kb = cb_menu0.message.edits[-1]
    assert "обычный режим" in menu0_text
    assert "anatomy_exam_test_mode_toggle" in kb_data(menu0_kb)
    assert "anatomy_exam_test_leaderboard" in kb_data(menu0_kb)

    cb_toggle1 = FakeCB("anatomy_exam_test_mode_toggle", uid=uid3)
    await tb.cb_anatomy_exam_test_mode_toggle(cb_toggle1)
    assert tb.get_anatomy_exam_test_mode(uid3) == "rating"
    assert cb_toggle1._answers and "Рейтинговый" in (cb_toggle1._answers[0][0] or "")
    toggled_text, _ = cb_toggle1.message.edits[-1]
    assert "рейтинговый режим" in toggled_text

    cb_toggle2 = FakeCB("anatomy_exam_test_mode_toggle", uid=uid3)
    await tb.cb_anatomy_exam_test_mode_toggle(cb_toggle2)
    assert tb.get_anatomy_exam_test_mode(uid3) == "normal"
    print("mode toggle flips normal<->rating and re-renders the menu: OK")

    # 16. a session snapshots the mode at start time, shown via a 🏆/🎯 icon on each question
    tb.set_anatomy_exam_test_mode(uid3, "rating")
    cb_start_rating = FakeCB("anatomy_exam_test_start:2", uid=uid3)
    await tb.cb_anatomy_exam_test_start(cb_start_rating)
    assert tb.ANATOMY_EXAM_TEST_SESSIONS[uid3]["is_rating"] is True
    rating_q_text, _ = cb_start_rating.message.edits[-1]
    assert rating_q_text.startswith("🏆")
    # switching mode mid-session must not retroactively change the running session
    tb.set_anatomy_exam_test_mode(uid3, "normal")
    assert tb.ANATOMY_EXAM_TEST_SESSIONS[uid3]["is_rating"] is True
    print("session snapshots is_rating at start; mode changes don't affect a running session: OK")

    # 17. completing a part in rating mode records the score; the leaderboard shows it,
    # and completing another part accumulates on top of the first
    part2 = tb.get_anatomy_exam_test_part(2)
    for q in part2["questions"]:
        session = tb.ANATOMY_EXAM_TEST_SESSIONS[uid3]
        cb_a = FakeCB(f"anatomy_exam_test_answer:{q['correct']}", uid=uid3)
        await tb.cb_anatomy_exam_test_answer(cb_a)
    rating_summary_text, rating_summary_kb = cb_a.message.edits[-1]
    assert "добавлен в общий рейтинг" in rating_summary_text
    assert "anatomy_exam_test_leaderboard" in kb_data(rating_summary_kb)
    uid3_str = str(uid3)
    assert tb.stats["anatomy_exam_test_scores"][uid3_str]["correct"] == len(part2["questions"])
    assert tb.stats["anatomy_exam_test_scores"][uid3_str]["total"] == len(part2["questions"])
    assert tb.stats["anatomy_exam_test_scores"][uid3_str]["attempts"] == 1

    cb_lb = FakeCB("anatomy_exam_test_leaderboard", uid=uid3)
    await tb.cb_anatomy_exam_test_leaderboard(cb_lb)
    lb_text, lb_kb = cb_lb.message.edits[-1]
    check_html(lb_text)
    assert tb.donor_display_name(uid3_str) in lb_text
    assert "anatomy_exam_test_menu" in kb_data(lb_kb)

    # a second, normal-mode part completion must NOT add to the rating score
    tb.set_anatomy_exam_test_mode(uid3, "normal")
    part3 = tb.get_anatomy_exam_test_part(3)
    cb_start3 = FakeCB("anatomy_exam_test_start:3", uid=uid3)
    await tb.cb_anatomy_exam_test_start(cb_start3)
    assert tb.ANATOMY_EXAM_TEST_SESSIONS[uid3]["is_rating"] is False
    for q in part3["questions"]:
        cb_b = FakeCB(f"anatomy_exam_test_answer:{q['correct']}", uid=uid3)
        await tb.cb_anatomy_exam_test_answer(cb_b)
    normal_summary_text, _ = cb_b.message.edits[-1]
    assert "рейтинг" not in normal_summary_text.lower()
    assert tb.stats["anatomy_exam_test_scores"][uid3_str]["correct"] == len(part2["questions"]), \
        "a normal-mode completion must not change the accumulated rating score"
    print("rating-mode completion records + accumulates the score; normal-mode completion doesn't: OK")

    # 18. aborting a rating-mode run does not count toward the rating
    tb.set_anatomy_exam_test_mode(uid3, "rating")
    before = dict(tb.stats["anatomy_exam_test_scores"][uid3_str])
    cb_start_abort = FakeCB("anatomy_exam_test_start:4", uid=uid3)
    await tb.cb_anatomy_exam_test_start(cb_start_abort)
    session4 = tb.ANATOMY_EXAM_TEST_SESSIONS[uid3]
    q4 = session4["queue"][0]
    cb_ans4 = FakeCB(f"anatomy_exam_test_answer:{q4['correct']}", uid=uid3)
    await tb.cb_anatomy_exam_test_answer(cb_ans4)
    cb_stop4 = FakeCB("anatomy_exam_test_stop", uid=uid3)
    await tb.cb_anatomy_exam_test_stop(cb_stop4)
    abort_text, _ = cb_stop4.message.edits[-1]
    assert "не засчитано" in abort_text
    assert tb.stats["anatomy_exam_test_scores"][uid3_str] == before, \
        "aborting a rating-mode run must not change the accumulated score"
    print("aborting a rating-mode run is not scored: OK")

    # 19. empty leaderboard (no one has ever completed a rating-mode part) renders gracefully
    tb.stats["anatomy_exam_test_scores"].clear()
    cb_lb_empty = FakeCB("anatomy_exam_test_leaderboard", uid=555444333)
    await tb.cb_anatomy_exam_test_leaderboard(cb_lb_empty)
    empty_lb_text, _ = cb_lb_empty.message.edits[-1]
    assert "Пока никто" in empty_lb_text
    print("empty rating leaderboard renders gracefully: OK")

    print("ALL ANATOMY EXAM TEST TESTS PASSED")

asyncio.run(main())
