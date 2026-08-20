# -*- coding: utf-8 -*-
"""Оперативная хирургия — новый, свободный для всех раздел (см. CLAUDE.md). v1 честно неполный:
у каждого занятия реально заполнено только summary ("Что нужно знать"), остальные 12 граней
карточки ведут на явный "материал не добавлен" экран, а не на выдуманный контент — эти тесты
проверяют именно эту границу, а не притворяются, что там больше данных, чем есть."""
import asyncio, random
from _bootstrap import tb
from aiogram.dispatcher.event.bases import SkipHandler
from html.parser import HTMLParser

ADMIN_ID = next(iter(tb.ADMIN_IDS))


class C(HTMLParser):
    def __init__(self):
        super().__init__(); self.stack = []; self.problems = []
    def handle_starttag(self, tag, attrs): self.stack.append(tag)
    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag: self.problems.append(tag)
        else: self.stack.pop()


def check_html(text):
    c = C(); c.feed(text)
    assert not c.stack and not c.problems, (text[:300], c.stack, c.problems)
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
    def __init__(self, data, uid=ADMIN_ID):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
        self._answers = []
    async def answer(self, text=None, show_alert=False):
        self._answers.append((text, show_alert))


class FakeMessage:
    def __init__(self, text, uid):
        self.text = text
        self.from_user = FakeUser(uid)
        self.sent = []
    async def answer(self, text, **kwargs):
        self.sent.append((text, kwargs.get("reply_markup")))
        return self


def kb_data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def kb_texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


def fresh_uid():
    return random.randint(10_000_000, 99_999_999)


async def main():
    data = tb.OPERATIVE_SURGERY

    # ---- 1. JSON structure sanity: 23 lessons, sequential ids, review lessons correctly flagged ----
    curriculum = data["curriculum"]
    assert len(curriculum) == 23
    assert [e["id"] for e in curriculum] == [f"{i:02d}" for i in range(1, 24)]
    review_ids = {e["id"] for e in curriculum if e["is_review"]}
    assert review_ids == {"15", "23"}
    for e in curriculum:
        assert e["source_pages"], e["id"]
        if e["is_review"]:
            assert e["summary"] is None and e.get("review_note")
        else:
            assert e["summary"] and len(e["summary"]) > 20, e["id"]
    print("1. JSON structure: 23 sequential lessons, review lessons correctly flagged: OK")

    # ---- 2. main menu exposes the section, ungated (no referral/subscription gate) ----
    non_admin = fresh_uid()
    main_menu = tb.get_main_menu(user_id=non_admin)
    assert "oh:menu" in kb_data(main_menu)
    assert any("Оперативная хирургия" in t for t in kb_texts(main_menu))
    assert not tb.is_gated_callback("oh:menu")
    assert not tb.is_gated_callback("oh:curriculum:0")
    print("2. main menu exposes the section, callbacks are ungated: OK")

    # ---- 3. cb_oh_menu renders the four sub-entries + back ----
    cb_menu = FakeCB("oh:menu", uid=non_admin)
    await tb.cb_oh_menu(cb_menu)
    menu_text, menu_kb = cb_menu.message.edits[-1]
    check_html(menu_text)
    menu_data = kb_data(menu_kb)
    assert "oh:curriculum:0" in menu_data
    assert "oh:projections" in menu_data
    assert "oh:instruments" in menu_data
    assert "oh:search_prompt" in menu_data
    assert "back_to_main" in menu_data
    print("3. cb_oh_menu renders all sub-entries: OK")

    # ---- 4. curriculum pagination: page 0 has 10 lessons + next only, last page has the rest + prev only ----
    cb_page0 = FakeCB("oh:curriculum:0", uid=non_admin)
    await tb.cb_oh_curriculum(cb_page0)
    page0_text, page0_kb = cb_page0.message.edits[-1]
    check_html(page0_text)
    page0_data = kb_data(page0_kb)
    lesson_buttons_p0 = [d for d in page0_data if d.startswith("oh:lesson:")]
    assert len(lesson_buttons_p0) == 10
    assert "oh:curriculum:1" in page0_data
    assert not any(d == "oh:curriculum:-1" for d in page0_data)

    cb_page2 = FakeCB("oh:curriculum:2", uid=non_admin)
    await tb.cb_oh_curriculum(cb_page2)
    page2_data = kb_data(cb_page2.message.edits[-1][1])
    lesson_buttons_p2 = [d for d in page2_data if d.startswith("oh:lesson:")]
    assert len(lesson_buttons_p2) == 3
    assert "oh:curriculum:1" in page2_data
    assert not any(d.startswith("oh:curriculum:3") for d in page2_data)
    print("4. curriculum pagination: 10+10+3 across 3 pages, correct nav buttons: OK")

    # ---- 5. a normal lesson shows the real summary + 12 facet buttons + back to its own page ----
    cb_lesson = FakeCB("oh:lesson:02", uid=non_admin)
    await tb.cb_oh_lesson(cb_lesson)
    lesson_text, lesson_kb = cb_lesson.message.edits[-1]
    check_html(lesson_text)
    assert "Топографическая анатомия верхней конечности" in lesson_text
    assert "Что нужно знать" in lesson_text
    assert "Практикум ВМедА 2017" in lesson_text and "33" in lesson_text
    lesson_data = kb_data(lesson_kb)
    assert len([d for d in lesson_data if d.startswith("oh:facet:02:")]) == 12
    assert "oh:curriculum:0" in lesson_data  # id 02 -> page 0
    print("5. lesson screen shows real summary, source citation, 12 facet buttons: OK")

    # ---- 5b. a REVIEW lesson shows its review note instead of a summary, and NO facet buttons ----
    cb_review = FakeCB("oh:lesson:15", uid=non_admin)
    await tb.cb_oh_lesson(cb_review)
    review_text, review_kb = cb_review.message.edits[-1]
    check_html(review_text)
    assert "Итог" in review_text and "повторение" in review_text
    assert "Что нужно знать" not in review_text
    review_data = kb_data(review_kb)
    assert not any(d.startswith("oh:facet:") for d in review_data)
    assert "oh:curriculum:1" in review_data  # id 15 -> page 1
    print("5b. review lesson shows the review note, no facet buttons: OK")

    # ---- 5c. unknown lesson id is rejected with an alert, no crash ----
    cb_bad_lesson = FakeCB("oh:lesson:99", uid=non_admin)
    await tb.cb_oh_lesson(cb_bad_lesson)
    assert not cb_bad_lesson.message.edits
    assert cb_bad_lesson._answers and cb_bad_lesson._answers[0][1] is True
    print("5c. unknown lesson id rejected with an alert: OK")

    # ---- 6. an unfilled facet shows the honest "not added yet" screen, not fabricated content ----
    cb_facet = FakeCB("oh:facet:02:layers", uid=non_admin)
    await tb.cb_oh_facet(cb_facet)
    facet_text, facet_kb = cb_facet.message.edits[-1]
    check_html(facet_text)
    assert "🧱 Слои" in facet_text
    assert "ещё не добавлен" in facet_text
    assert kb_data(facet_kb) == ["oh:lesson:02"]
    print("6. unfilled facet shows an honest placeholder, not fabricated content: OK")

    # ---- 7. instruments: group menu -> group contents, out-of-range group rejected ----
    cb_instr = FakeCB("oh:instruments", uid=non_admin)
    await tb.cb_oh_instruments(cb_instr)
    instr_text, instr_kb = cb_instr.message.edits[-1]
    check_html(instr_text)
    n_groups = len(data["instrument_groups"])
    instr_group_buttons = [d for d in kb_data(instr_kb) if d.startswith("oh:instr_group:")]
    assert len(instr_group_buttons) == n_groups

    cb_group0 = FakeCB("oh:instr_group:0", uid=non_admin)
    await tb.cb_oh_instrument_group(cb_group0)
    group0_text = cb_group0.message.edits[-1][0]
    check_html(group0_text)
    first_group = data["instrument_groups"][0]
    assert first_group["group"] in group0_text
    for item in first_group["items"]:
        assert item["name"] in group0_text

    cb_group_bad = FakeCB(f"oh:instr_group:{n_groups}", uid=non_admin)
    await tb.cb_oh_instrument_group(cb_group_bad)
    assert not cb_group_bad.message.edits
    assert cb_group_bad._answers and cb_group_bad._answers[0][1] is True
    print("7. instrument groups: menu, contents, out-of-range rejected: OK")

    # ---- 8. projections: all real entries present, valid HTML, fits one message ----
    cb_proj = FakeCB("oh:projections", uid=non_admin)
    await tb.cb_oh_projections(cb_proj)
    proj_text = cb_proj.message.edits[-1][0]
    check_html(proj_text)
    for p in data["projections"]:
        assert p["structure"] in proj_text
    print("8. projections reference screen: all real entries present, fits one message: OK")

    # ---- 9. search: prompt sets pending state, a real hit resolves it, empty state has no crash ----
    search_uid = fresh_uid()
    cb_search_prompt = FakeCB("oh:search_prompt", uid=search_uid)
    await tb.cb_oh_search_prompt(cb_search_prompt)
    assert search_uid in tb.OH_SEARCH_PENDING
    prompt_text = cb_search_prompt.message.edits[-1][0]
    check_html(prompt_text)

    msg_hit = FakeMessage("бедренная", search_uid)
    await tb.handle_oh_search_query(msg_hit)
    assert search_uid not in tb.OH_SEARCH_PENDING, "pending state must be cleared after the search fires"
    assert msg_hit.sent
    result_text, result_kb = msg_hit.sent[-1]
    check_html(result_text)
    assert "бедренная" in result_text.lower() or "Бедро и ягодичной области".lower() in result_text.lower() \
        or "Топографическая анатомия бедра" in result_text
    print("9. search: prompt sets pending, a real hit clears it and returns matches: OK")

    # ---- 9b. a user with no pending search state falls through via SkipHandler ----
    idle_uid = fresh_uid()
    msg_idle = FakeMessage("просто текст", idle_uid)
    try:
        await tb.handle_oh_search_query(msg_idle)
        raised = False
    except SkipHandler:
        raised = True
    assert raised
    print("9b. idle user (no pending search) falls through via SkipHandler: OK")

    # ---- 9c. empty search result still answers cleanly (no crash), pending cleared ----
    search_uid2 = fresh_uid()
    tb.OH_SEARCH_PENDING.add(search_uid2)
    msg_empty = FakeMessage("совершенно случайная непонятная строка xyzzy", search_uid2)
    await tb.handle_oh_search_query(msg_empty)
    assert search_uid2 not in tb.OH_SEARCH_PENDING
    assert msg_empty.sent and "ничего не найдено" in msg_empty.sent[-1][0]
    print("9c. empty search result handled cleanly: OK")

    # ---- 9d. navigating back to oh:menu clears any lingering pending-search state ----
    search_uid3 = fresh_uid()
    tb.OH_SEARCH_PENDING.add(search_uid3)
    cb_back = FakeCB("oh:menu", uid=search_uid3)
    await tb.cb_oh_menu(cb_back)
    assert search_uid3 not in tb.OH_SEARCH_PENDING
    print("9d. returning to the section root clears pending search state: OK")

    # ---- 10. RAG: operative_surgery content is actually indexed for VMedA AI grounding ----
    from ai import rag as ai_rag
    ai_rag.configure(
        questions=tb.QUESTIONS, physics_questions=tb.PHYSICS_QUESTIONS, chemistry_theory=tb.CHEMISTRY_THEORY,
        chemistry_theory_tickets=tb.CHEMISTRY_THEORY_TICKETS, chemistry_practice_tickets=tb.CHEMISTRY_PRACTICE_TICKETS,
        anatomy=tb.ANATOMY, operative_surgery=tb.OPERATIVE_SURGERY,
    )
    subjects = {e["subject"] for e in ai_rag._index}
    assert "оперативная хирургия" in subjects
    oh_entries = [e for e in ai_rag._index if e["subject"] == "оперативная хирургия"]
    # 21 занятий с summary (23 - 2 review) + 15 проекций
    assert len(oh_entries) == 21 + 15, len(oh_entries)
    assert any("Седалищный нерв" in e["title"] for e in oh_entries)
    # restore the real config other tests expect (AI_MVP tests configure this themselves too, but
    # leaving the module in a state consistent with telegram_bot's own real content is safest)
    ai_rag.configure(
        questions=tb.QUESTIONS, physics_questions=tb.PHYSICS_QUESTIONS, chemistry_theory=tb.CHEMISTRY_THEORY,
        chemistry_theory_tickets=tb.CHEMISTRY_THEORY_TICKETS, chemistry_practice_tickets=tb.CHEMISTRY_PRACTICE_TICKETS,
        anatomy=tb.ANATOMY, operative_surgery=tb.OPERATIVE_SURGERY,
    )
    print("10. RAG index includes operative_surgery lesson summaries + projections: OK")

    print("\nALL OPERATIVE SURGERY TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
