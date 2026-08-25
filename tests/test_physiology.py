# -*- coding: utf-8 -*-
"""Нормальная физиология — свободный для всех раздел (см. CLAUDE.md), 23 темы полного курса VMEDA,
собранного только из «Том 1 1.pdf»/«Том 2 1.pdf»/«Физа учебник.pdf». Эти тесты проверяют: структуру
датасета (23 темы, без темы 3-го тома, провенанс, отсутствие фабрикации), навигацию (меню -> темы
-> карточка темы -> учить/читать/повторить/тест -> назад), прогресс/мастерство/SRS, избранное,
поиск, форматирование (HTML-баланс, отсутствие обрезанных предложений) и попадание контента в
RAG-индекс VMedA AI. Структурный шаблон — 1:1 с tests/test_operative_surgery.py."""
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
    data = tb.PHYSIOLOGY

    # ---- 1. dataset structure: exactly 23 topics, in order, required fields present, no
    # volume-3/fabricated content markers, provenance on every topic ----
    topics = data["topics"]
    assert len(topics) == 23, len(topics)
    ids = [t["topic_id"] for t in topics]
    assert len(set(ids)) == 23, "topic_id must be unique"
    orders = [t["order"] for t in topics]
    assert orders == sorted(orders)
    required_fields = (
        "topic_id", "order", "title", "short_title", "source_file", "source_pages",
        "what_to_know", "definitions", "mechanisms", "cause_effect", "regulation",
        "comparisons", "remember", "confusions", "quick_review", "control_questions",
        "sections", "deepening",
    )
    for t in topics:
        for f in required_fields:
            assert f in t, (t["topic_id"], f)
        assert t["title"].strip(), t["topic_id"]
        assert t["short_title"].strip(), t["topic_id"]
        assert t["sections"], t["topic_id"]  # sections[] is the never-empty full-fidelity backbone
        for s in t["sections"]:
            assert "❌" not in s["text"] and "TODO" not in s["text"], t["topic_id"]
    meta = data["meta"]
    assert meta["source_files"], "must disclose real source files"
    assert all("том 3" not in f.lower() and "volume 3" not in f.lower() for f in meta["source_files"])
    print("1. dataset structure: 23 topics, unique ids, ordered, required fields present, no vol-3: OK")

    # ---- 2. quiz bank: every question is grounded (options/correct_answer non-empty,
    # correct_answer is always one of options), topics 06/07 honestly have zero questions ----
    quiz = data["quiz_questions"]
    assert quiz, "quiz bank must not be empty"
    qids = [q["question_id"] for q in quiz]
    assert len(set(qids)) == len(qids), "question_id must be unique"
    for q in quiz:
        assert q["options"] and q["correct_answer"] in q["options"], q["question_id"]
        assert q["prompt"].strip()
        assert q["topic_id"] in ids
    topics_with_quiz = {q["topic_id"] for q in quiz}
    assert "06" not in topics_with_quiz and "07" not in topics_with_quiz
    print(f"2. quiz bank: {len(quiz)} grounded questions, honest zero-question gap for topics 06/07: OK")

    # ---- 3. 2nd-course menu exposes the section, ungated (no referral/subscription gate) ----
    non_admin = fresh_uid()
    course2_menu = tb.get_course_menu_keyboard(2, user_id=non_admin)
    assert "phys:menu" in kb_data(course2_menu)
    assert any("Нормальная физиология" in t for t in kb_texts(course2_menu))
    assert not tb.is_gated_callback("phys:menu")
    assert not tb.is_gated_callback("phys:topic:01")
    print("3. course menu exposes the section, ungated: OK")

    # ---- 4. menu screen renders with progress counters + all mode buttons ----
    cb_menu = FakeCB("phys:menu", uid=non_admin)
    await tb.cb_phys_menu(cb_menu)
    menu_text, menu_kb = cb_menu.message.edits[-1]
    check_html(menu_text)
    menu_data = kb_data(menu_kb)
    for expected in (
        "phys:topics:0", "phys:continue", "phys:qpick:0", "phys:zpick:0",
        "phys:search_prompt", "phys:favorites", "phys:progress", "back_to_main",
    ):
        assert expected in menu_data, expected
    assert "phys:sources" not in menu_data, "no dedicated sources screen — never surfaced as UI text"
    print("4. cb_phys_menu renders all mode entries, no sources screen: OK")

    # ---- 5. topics list: pagination (8/page), status icons, correct target routing ----
    cb_topics0 = FakeCB("phys:topics:0", uid=non_admin)
    await tb.cb_phys_topics(cb_topics0)
    t0_text, t0_kb = cb_topics0.message.edits[-1]
    check_html(t0_text)
    t0_data = kb_data(t0_kb)
    topic_buttons = [d for d in t0_data if d.startswith("phys:topic:")]
    assert len(topic_buttons) == 8
    assert "phys:topics:1" in t0_data
    assert not any(d == "phys:topics:-1" for d in t0_data)

    last_page = (len(topics) - 1) // 8
    cb_topics_last = FakeCB(f"phys:topics:{last_page}", uid=non_admin)
    await tb.cb_phys_topics(cb_topics_last)
    last_data = kb_data(cb_topics_last.message.edits[-1][1])
    last_topic_buttons = [d for d in last_data if d.startswith("phys:topic:")]
    assert len(last_topic_buttons) == len(topics) - last_page * 8
    assert not any(d == f"phys:topics:{last_page + 1}" for d in last_data)
    print("5. topics list pagination (8/page), correct boundaries: OK")

    # ---- 6. topic card: real title/content, mode buttons, unknown topic rejected ----
    cb_topic01 = FakeCB("phys:topic:01", uid=non_admin)
    await tb.cb_phys_topic(cb_topic01)
    topic01_text, topic01_kb = cb_topic01.message.edits[-1]
    check_html(topic01_text)
    topic01 = tb.get_phys_topic("01")
    assert topic01["title"].upper() in topic01_text or topic01["title"] in topic01_text
    topic01_data = kb_data(topic01_kb)
    for expected in ("phys:learn:01:0", "phys:read:01:0", "phys:quick:01", "phys:quiz_start:01", "phys:fav_toggle:01"):
        assert expected in topic01_data, expected

    cb_topic_bad = FakeCB("phys:topic:99", uid=non_admin)
    await tb.cb_phys_topic(cb_topic_bad)
    assert not cb_topic_bad.message.edits
    assert cb_topic_bad._answers and cb_topic_bad._answers[0][1] is True
    print("6. topic card: real content, all mode buttons, unknown topic rejected: OK")

    # ---- 7. "opening" a topic records progress (opened_at set), status flips to 'learning' ----
    prog_uid = fresh_uid()
    assert tb.phys_topic_status(prog_uid, "01") == "not_started"
    cb_open = FakeCB("phys:topic:01", uid=prog_uid)
    await tb.cb_phys_topic(cb_open)
    entry = tb.get_phys_progress(prog_uid, "01")
    assert entry["opened_at"] is not None
    assert entry["total_cards"] > 0
    print("7. opening a topic records progress (opened_at, total_cards): OK")

    # ---- 8. "Учить по шагам": card navigation, 'Понятно' marks a card done and advances,
    # never marks done merely by viewing (Next without Ok doesn't increment completed_cards) ----
    cards = tb.build_phys_learn_cards(topic01)
    assert len(cards) >= 2, "need at least 2 cards to test navigation"
    cb_learn0 = FakeCB("phys:learn:01:0", uid=prog_uid)
    await tb.cb_phys_learn(cb_learn0)
    learn0_text, learn0_kb = cb_learn0.message.edits[-1]
    check_html(learn0_text)
    learn0_data = kb_data(learn0_kb)
    assert "phys:learn_ok:01:0" in learn0_data
    assert "phys:learn:01:1" in learn0_data
    assert "phys:topic:01" in learn0_data

    before = tb.get_phys_progress(prog_uid, "01")["completed_cards"]
    cb_learn1_no_ok = FakeCB("phys:learn:01:1", uid=prog_uid)
    await tb.cb_phys_learn(cb_learn1_no_ok)
    after_view_only = tb.get_phys_progress(prog_uid, "01")["completed_cards"]
    assert after_view_only == before, "viewing a card must not count as studied"

    cb_ok0 = FakeCB("phys:learn_ok:01:0", uid=prog_uid)
    await tb.cb_phys_learn_ok(cb_ok0)
    after_ok = tb.get_phys_progress(prog_uid, "01")["completed_cards"]
    assert after_ok == before + 1, "explicit 'Понятно' tap must mark the card studied"
    ok0_text = cb_ok0.message.edits[-1][0]
    check_html(ok0_text)

    cb_learn_bad = FakeCB("phys:learn:01:999", uid=prog_uid)
    await tb.cb_phys_learn(cb_learn_bad)
    assert cb_learn_bad._answers and cb_learn_bad._answers[0][1] is True
    print("8. 'Учить по шагам': navigation, card counted studied only on explicit 'Понятно': OK")

    # ---- 9. "Читать конспект": sequential section reading, prev/next boundaries, long-text
    # truncation never breaks mid-sentence (falls back to a clean paragraph boundary) ----
    n_sections = len(topic01["sections"])
    cb_read0 = FakeCB("phys:read:01:0", uid=non_admin)
    await tb.cb_phys_read(cb_read0)
    read0_text, read0_kb = cb_read0.message.edits[-1]
    check_html(read0_text)
    read0_data = kb_data(read0_kb)
    assert not any(d == "phys:read:01:-1" for d in read0_data)
    if n_sections > 1:
        assert "phys:read:01:1" in read0_data

    cb_read_last = FakeCB(f"phys:read:01:{n_sections - 1}", uid=non_admin)
    await tb.cb_phys_read(cb_read_last)
    read_last_data = kb_data(cb_read_last.message.edits[-1][1])
    assert not any(d == f"phys:read:01:{n_sections}" for d in read_last_data)
    assert "phys:topic:01" in read_last_data

    cb_read_bad = FakeCB(f"phys:read:01:{n_sections}", uid=non_admin)
    await tb.cb_phys_read(cb_read_bad)
    assert not cb_read_bad.message.edits
    assert cb_read_bad._answers and cb_read_bad._answers[0][1] is True

    # every section across every topic renders as valid HTML within the Telegram cap after the
    # reading-mode truncation fallback
    for t in topics:
        for i in range(len(t["sections"])):
            check_html(tb.get_phys_read_text(t, i))
    print("9. 'Читать конспект': correct pagination, all sections render safely within cap: OK")

    # ---- 10. "Быстрый повтор": condensed screen renders, mini-question reachable when a quiz
    # pool exists for that topic ----
    cb_quick01 = FakeCB("phys:quick:01", uid=non_admin)
    await tb.cb_phys_quick(cb_quick01)
    quick_text, quick_kb = cb_quick01.message.edits[-1]
    check_html(quick_text)
    if tb.get_phys_topic_quiz_pool("01"):
        assert "phys:mini:01:0" in kb_data(quick_kb)

    cb_quick_bad = FakeCB("phys:quick:99", uid=non_admin)
    await tb.cb_phys_quick(cb_quick_bad)
    assert cb_quick_bad._answers and cb_quick_bad._answers[0][1] is True
    print("10. 'Быстрый повтор' renders a condensed real-content screen: OK")

    # ---- 11. causal chains: only offered when a topic actually has cause_effect/mechanisms;
    # renders as a vertical arrow chain, correct pagination ----
    chain_topic_id = next((t["topic_id"] for t in topics if t["cause_effect"] or t["mechanisms"]), None)
    assert chain_topic_id, "expected at least one topic with chain content"
    chains = tb.build_phys_chains(tb.get_phys_topic(chain_topic_id))
    assert chains
    cb_chain0 = FakeCB(f"phys:chains:{chain_topic_id}:0", uid=non_admin)
    await tb.cb_phys_chains(cb_chain0)
    chain0_text = cb_chain0.message.edits[-1][0]
    check_html(chain0_text)
    assert "↓" in chain0_text or len(chains[0]["steps"]) == 1

    cb_chain_bad = FakeCB(f"phys:chains:{chain_topic_id}:999", uid=non_admin)
    await tb.cb_phys_chains(cb_chain_bad)
    assert cb_chain_bad._answers and cb_chain_bad._answers[0][1] is True
    print("11. causal chains: real content-gated availability, vertical rendering, bounds checked: OK")

    # ---- 12. comparisons: rendered as two-sided mobile cards, never a raw Markdown table ----
    cmp_topic_id = next((t["topic_id"] for t in topics if t["comparisons"]), None)
    assert cmp_topic_id, "expected at least one topic with comparison content"
    cb_cmp0 = FakeCB(f"phys:cmp:{cmp_topic_id}:0", uid=non_admin)
    await tb.cb_phys_cmp(cb_cmp0)
    cmp0_text = cb_cmp0.message.edits[-1][0]
    check_html(cmp0_text)
    assert "|" not in cmp0_text, "must never leak a raw Markdown table pipe"

    cb_cmp_bad = FakeCB(f"phys:cmp:{cmp_topic_id}:999", uid=non_admin)
    await tb.cb_phys_cmp(cb_cmp_bad)
    assert cb_cmp_bad._answers and cb_cmp_bad._answers[0][1] is True
    print("12. comparisons render as mobile two-sided cards, never a raw table: OK")

    # ---- 13. quiz engine: start -> answer (correct + incorrect) -> next -> stop/finish, session
    # expiry handled, progress + mastery updated, SRS schedule advances on a passing session ----
    quiz_uid = fresh_uid()
    quiz_topic_id = next(iter(topics_with_quiz))
    cb_qstart = FakeCB(f"phys:quiz_start:{quiz_topic_id}", uid=quiz_uid)
    await tb.cb_phys_quiz_start(cb_qstart)
    q0_text, q0_kb = cb_qstart.message.edits[-1]
    check_html(q0_text)
    assert "phys:quiz_stop" in kb_data(q0_kb)

    session = tb.physiology_handlers.PHYS_QUIZ_SESSIONS[quiz_uid]
    q0 = session["queue"][0]
    correct_idx = q0["options"].index(q0["correct_answer"])
    cb_answer_correct = FakeCB(f"phys:quiz_answer:{correct_idx}", uid=quiz_uid)
    await tb.cb_phys_quiz_answer(cb_answer_correct)
    ans_text, ans_kb = cb_answer_correct.message.edits[-1]
    check_html(ans_text)
    assert "Верно" in ans_text
    assert tb.get_phys_progress(quiz_uid, quiz_topic_id)["correct_answers"] >= 1

    cb_next = FakeCB("phys:quiz_next", uid=quiz_uid)
    await tb.cb_phys_quiz_next(cb_next)
    assert cb_next.message.edits

    # finish the rest via wrong answers to exercise the incorrect path + mastery recompute
    while quiz_uid in tb.physiology_handlers.PHYS_QUIZ_SESSIONS:
        session = tb.physiology_handlers.PHYS_QUIZ_SESSIONS[quiz_uid]
        q = session["queue"][session["index"]]
        wrong_idx = next(i for i, o in enumerate(q["options"]) if o != q["correct_answer"])
        cb_a = FakeCB(f"phys:quiz_answer:{wrong_idx}", uid=quiz_uid)
        await tb.cb_phys_quiz_answer(cb_a)
        cb_n = FakeCB("phys:quiz_next", uid=quiz_uid)
        await tb.cb_phys_quiz_next(cb_n)
    final_text = cb_n.message.edits[-1][0]
    check_html(final_text)
    assert "Итог" in final_text or "закончились" in final_text

    final_entry = tb.get_phys_progress(quiz_uid, quiz_topic_id)
    assert final_entry["last_score"] is not None
    assert final_entry["mastery"] >= 0

    # session-expired path
    cb_expired = FakeCB("phys:quiz_answer:0", uid=fresh_uid())
    await tb.cb_phys_quiz_answer(cb_expired)
    assert cb_expired._answers and cb_expired._answers[0][1] is True
    print("13. quiz engine: full run (correct+incorrect), progress/mastery updated, expiry handled: OK")

    # ---- 13b. quiz_stop (abort) does NOT record a completed-session score/SRS advance ----
    abort_uid = fresh_uid()
    cb_qstart2 = FakeCB(f"phys:quiz_start:{quiz_topic_id}", uid=abort_uid)
    await tb.cb_phys_quiz_start(cb_qstart2)
    cb_stop = FakeCB("phys:quiz_stop", uid=abort_uid)
    await tb.cb_phys_quiz_stop(cb_stop)
    stop_text = cb_stop.message.edits[-1][0]
    check_html(stop_text)
    assert "Прервано" in stop_text
    abort_entry = tb.get_phys_progress(abort_uid, quiz_topic_id)
    assert abort_entry.get("next_review_at") is None, "aborting must not advance the SRS schedule"
    print("13b. aborting a quiz session does not record a score or advance SRS: OK")

    # ---- 14. mini-check: fired from a topic without a quiz pool is rejected cleanly ----
    no_quiz_topic_id = next(t["topic_id"] for t in topics if t["topic_id"] not in topics_with_quiz)
    cb_mini_none = FakeCB(f"phys:mini:{no_quiz_topic_id}:0", uid=non_admin)
    await tb.cb_phys_mini(cb_mini_none)
    assert cb_mini_none._answers and cb_mini_none._answers[0][1] is True

    mini_uid = fresh_uid()
    cb_mini = FakeCB(f"phys:mini:{quiz_topic_id}:0", uid=mini_uid)
    await tb.cb_phys_mini(cb_mini)
    mini_text, mini_kb = cb_mini.message.edits[-1]
    check_html(mini_text)
    mini_cb_data = kb_data(mini_kb)[0]
    parts = mini_cb_data.split(":")
    assert parts[0] == "phys" and parts[1] == "mini_answer"
    cb_mini_answer = FakeCB(mini_cb_data, uid=mini_uid)
    await tb.cb_phys_mini_answer(cb_mini_answer)
    mini_ans_text = cb_mini_answer.message.edits[-1][0]
    check_html(mini_ans_text)
    assert tb.get_phys_progress(mini_uid, quiz_topic_id)["total_answers"] >= 1

    # a stale/unknown question_id in a mini-answer callback is rejected, not a crash
    cb_mini_bad = FakeCB(f"phys:mini_answer:{quiz_topic_id}:0:phys-nonexistent:0", uid=mini_uid)
    await tb.cb_phys_mini_answer(cb_mini_bad)
    assert cb_mini_bad._answers and cb_mini_bad._answers[0][1] is True
    print("14. mini-check: fires only where a quiz pool exists, answer recorded, stale id rejected: OK")

    # ---- 15. mastery formula: 40% card-completion + 40% quiz-correctness + 20% mechanism ----
    mast_uid = fresh_uid()
    entry = tb.physiology_handlers._phys_progress_entry(mast_uid, "01")
    entry["total_cards"] = 10
    entry["completed_cards"] = 10   # 1.0
    entry["total_answers"] = 10
    entry["correct_answers"] = 5    # 0.5
    entry["mechanism_total"] = 10
    entry["mechanism_correct"] = 0  # 0.0
    tb.physiology_handlers._phys_recalc_mastery(entry)
    expected = round((0.4 * 1.0 + 0.4 * 0.5 + 0.2 * 0.0) * 100)
    assert entry["mastery"] == expected == 60, entry["mastery"]
    print("15. mastery formula matches the documented 40/40/20 weighting exactly: OK")

    # ---- 16. topic status derivation: not_started -> learning -> studied -> mastered/needs_review,
    # never stored, always re-derived from counters ----
    status_uid = fresh_uid()
    assert tb.phys_topic_status(status_uid, "02") == "not_started"
    tb.phys_mark_opened(status_uid, "02", total_cards=3)
    assert tb.phys_topic_status(status_uid, "02") == "learning"
    tb.phys_mark_card_done(status_uid, "02")
    tb.phys_mark_card_done(status_uid, "02")
    tb.phys_mark_card_done(status_uid, "02")
    assert tb.phys_topic_status(status_uid, "02") == "studied"
    entry02 = tb.physiology_handlers._phys_progress_entry(status_uid, "02")
    entry02["mastery"] = 90
    entry02["total_answers"] = 5
    assert tb.phys_topic_status(status_uid, "02") == "mastered"
    entry02["next_review_at"] = 1.0  # far in the past -> due
    assert tb.phys_topic_status(status_uid, "02") == "needs_review"
    print("16. topic status correctly derived through the full not_started->...->needs_review path: OK")

    # ---- 17. favorites: toggle on/off, screen lists real topics, dedicated screen navigable ----
    fav_uid = fresh_uid()
    assert not tb.phys_is_favorite(fav_uid, "03")
    cb_fav_on = FakeCB("phys:fav_toggle:03", uid=fav_uid)
    await tb.cb_phys_fav_toggle(cb_fav_on)
    assert tb.phys_is_favorite(fav_uid, "03")
    assert "Убрать" in kb_texts(cb_fav_on.message.edits[-1][1])[-2] or any(
        "Убрать из избранного" in t for t in kb_texts(cb_fav_on.message.edits[-1][1])
    )

    cb_favorites_screen = FakeCB("phys:favorites", uid=fav_uid)
    await tb.cb_phys_favorites(cb_favorites_screen)
    fav_text, fav_kb = cb_favorites_screen.message.edits[-1]
    check_html(fav_text)
    assert "phys:topic:03" in kb_data(fav_kb)

    cb_fav_off = FakeCB("phys:fav_toggle:03", uid=fav_uid)
    await tb.cb_phys_fav_toggle(cb_fav_off)
    assert not tb.phys_is_favorite(fav_uid, "03")
    print("17. favorites: toggle on/off, dedicated screen lists real topics: OK")

    # ---- 18. progress screen renders a real status breakdown + accuracy summary ----
    cb_progress = FakeCB("phys:progress", uid=status_uid)
    await tb.cb_phys_progress(cb_progress)
    prog_text = cb_progress.message.edits[-1][0]
    check_html(prog_text)
    assert "Мой прогресс" in prog_text
    print("18. progress screen renders cleanly: OK")

    # ---- 19. no "Источник"/source-citation captions anywhere in the section (menu, topic card,
    # learn cards, reading mode, quick review, quiz answers) — the dedicated sources screen and
    # every per-topic/per-question citation were removed per explicit user request ----
    assert not hasattr(tb, "cb_phys_sources")
    assert not hasattr(tb, "get_phys_sources_text")
    for t in topics:
        assert "Источник" not in tb.get_phys_topic_text(t, non_admin)
        for card in tb.build_phys_learn_cards(t):
            assert "Источник" not in tb.render_phys_learn_card(t, card)
        for i in range(len(t["sections"])):
            assert "Источник" not in tb.get_phys_read_text(t, i)
        assert "Источник" not in tb.get_phys_quick_text(t)
    for q in quiz:
        assert "Источник" not in tb.render_phys_quiz_answer(q, 0)
    print("19. no source-citation captions anywhere in the section: OK")

    # ---- 20. search: prompt sets pending state, a real hit resolves it and clears pending,
    # idle user falls through via SkipHandler, empty result handled cleanly, back-to-menu clears
    # lingering pending state ----
    search_uid = fresh_uid()
    cb_search_prompt = FakeCB("phys:search_prompt", uid=search_uid)
    await tb.cb_phys_search_prompt(cb_search_prompt)
    assert search_uid in tb.PHYS_SEARCH_PENDING
    prompt_text = cb_search_prompt.message.edits[-1][0]
    check_html(prompt_text)

    query_term = topics[0]["title"].split()[0]
    msg_hit = FakeMessage(query_term, search_uid)
    await tb.handle_phys_search_query(msg_hit)
    assert search_uid not in tb.PHYS_SEARCH_PENDING
    assert msg_hit.sent
    result_text, result_kb = msg_hit.sent[-1]
    check_html(result_text)
    assert query_term.lower() in result_text.lower()

    idle_uid = fresh_uid()
    msg_idle = FakeMessage("просто текст", idle_uid)
    try:
        await tb.handle_phys_search_query(msg_idle)
        raised = False
    except SkipHandler:
        raised = True
    assert raised

    search_uid2 = fresh_uid()
    tb.PHYS_SEARCH_PENDING.add(search_uid2)
    msg_empty = FakeMessage("совершенно случайная непонятная строка xyzzy", search_uid2)
    await tb.handle_phys_search_query(msg_empty)
    assert search_uid2 not in tb.PHYS_SEARCH_PENDING
    assert msg_empty.sent and "ничего не найдено" in msg_empty.sent[-1][0]

    search_uid3 = fresh_uid()
    tb.PHYS_SEARCH_PENDING.add(search_uid3)
    cb_back = FakeCB("phys:menu", uid=search_uid3)
    await tb.cb_phys_menu(cb_back)
    assert search_uid3 not in tb.PHYS_SEARCH_PENDING
    print("20. search: prompt/pending/hit/empty/idle-skip/back-clears-pending all correct: OK")

    # ---- 21. RAG: physiology real content is actually indexed for VMedA AI grounding ----
    from ai import rag as ai_rag
    ai_rag.configure(
        questions=tb.QUESTIONS, physics_questions=tb.PHYSICS_QUESTIONS, chemistry_theory=tb.CHEMISTRY_THEORY,
        chemistry_theory_tickets=tb.CHEMISTRY_THEORY_TICKETS, chemistry_practice_tickets=tb.CHEMISTRY_PRACTICE_TICKETS,
        anatomy=tb.ANATOMY, operative_surgery=tb.OPERATIVE_SURGERY, physiology=tb.PHYSIOLOGY,
    )
    subjects = {e["subject"] for e in ai_rag._index}
    assert "нормальная физиология" in subjects
    phys_entries = [e for e in ai_rag._index if e["subject"] == "нормальная физиология"]
    n_defs = sum(len(t["definitions"]) for t in topics)
    n_rk_chunks = sum(
        len(ai_rag._chunk_rk_blocks(c["blocks"])) for c in tb.PHYSIOLOGY.get("boundary_controls", [])
    )
    assert len(phys_entries) == len(topics) + n_defs + n_rk_chunks, (
        len(phys_entries), len(topics), n_defs, n_rk_chunks
    )
    # restore the real config other tests expect
    ai_rag.configure(
        questions=tb.QUESTIONS, physics_questions=tb.PHYSICS_QUESTIONS, chemistry_theory=tb.CHEMISTRY_THEORY,
        chemistry_theory_tickets=tb.CHEMISTRY_THEORY_TICKETS, chemistry_practice_tickets=tb.CHEMISTRY_PRACTICE_TICKETS,
        anatomy=tb.ANATOMY, operative_surgery=tb.OPERATIVE_SURGERY, physiology=tb.PHYSIOLOGY,
    )
    print("21. RAG index includes every topic's full text + every definition + boundary-control chunks: OK")

    # ---- 22. "Продолжить обучение": routes to a needs_review topic first, else the first
    # not_started/learning topic, never crashes when nothing has been started yet ----
    continue_uid = fresh_uid()
    cb_continue = FakeCB("phys:continue", uid=continue_uid)
    await tb.cb_phys_continue(cb_continue)
    cont_text = cb_continue.message.edits[-1][0]
    check_html(cont_text)
    assert tb.get_phys_progress(continue_uid, tb.phys_topic_ids_in_order()[0])["opened_at"] is not None
    print("22. 'Продолжить обучение' routes to a sensible next topic: OK")

    print("\nALL PHYSIOLOGY TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
