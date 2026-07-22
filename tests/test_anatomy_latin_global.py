# -*- coding: utf-8 -*-
"""Global (whole-course) Latin terminology quiz + leaderboard, reachable from the main
Anatomy menu — pools latin_terms across every section, not a single topic/bone."""
import asyncio, random
from _bootstrap import tb

ADMIN_ID = next(iter(tb.ADMIN_IDS))

class FakeUser:
    def __init__(self, uid):
        self.id = uid

class FakeMsg:
    def __init__(self):
        self.edits = []
    async def edit_text(self, text, **kwargs):
        self.edits.append(text)
        return self
    async def delete(self):
        pass
    async def answer(self, text, **kwargs):
        self.edits.append(text)
        return self

class FakeCB:
    def __init__(self, data, uid=ADMIN_ID):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
        self._answers = []
    async def answer(self, text=None, show_alert=False):
        self._answers.append((text, show_alert))

def fresh_uid():
    return random.randint(10_000_000, 99_999_999)

async def run_full_session(uid, correct_answers: bool):
    """Drives a global session to completion, always answering correctly or always
    wrongly depending on correct_answers, and returns the final summary edit text."""
    cb = FakeCB("anatomy_latin_all_start", uid)
    await tb.cb_anatomy_latin_all_start(cb)
    assert cb.message.edits, "global session should render a question"
    sess = tb.ANATOMY_LATIN_SESSIONS[uid]
    n = len(sess["queue"])
    last_cb = None
    for _ in range(n):
        sess = tb.ANATOMY_LATIN_SESSIONS[uid]
        idx = sess["current_correct_idx"] if correct_answers else (sess["current_correct_idx"] + 1) % len(sess["current_options"])
        last_cb = FakeCB(f"anatomy_latin_answer:{idx}", uid)
        await tb.cb_anatomy_latin_answer(last_cb)
    assert uid not in tb.ANATOMY_LATIN_SESSIONS, "session should be cleaned up after the last question"
    return last_cb.message.edits[-1], n

async def main():
    errors = []

    # ---- pooled global term bank spans multiple sections ----
    all_terms = tb.get_all_latin_terms()
    assert len(all_terms) >= 300, f"expected 300+ pooled terms, got {len(all_terms)}"
    sections_covered = set()
    for section_key, section in tb.ANATOMY.items():
        for topic in section.get("topics", {}).values():
            if topic.get("latin_terms"):
                sections_covered.add(section_key)
    assert sections_covered, "expected at least one section with latin_terms"
    print(f"get_all_latin_terms(): {len(all_terms)} terms from sections {sorted(sections_covered)}")

    # ---- anatomy_menu shows both the quiz and leaderboard buttons ----
    kb = tb.get_anatomy_menu_keyboard()
    data = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "anatomy_latin_all_start" in data, "main menu missing global latin quiz button"
    assert "anatomy_latin_leaderboard" in data, "main menu missing latin leaderboard button"
    print("anatomy_menu buttons OK")

    # ---- access control ----
    cb = FakeCB("anatomy_latin_all_start", uid=123456789)
    await tb.cb_anatomy_latin_all_start(cb)
    assert not cb.message.edits and cb._answers and cb._answers[0][1] is True
    print("access-control OK")

    # ---- starting a session samples ANATOMY_LATIN_ALL_SESSION_SIZE terms, all_terms is the global pool ----
    uid1 = fresh_uid()
    tb.stats["total_users"].add(uid1)
    tb.stats["manual_anatomy_demo_granted"].append(uid1)
    cb = FakeCB("anatomy_latin_all_start", uid1)
    await tb.cb_anatomy_latin_all_start(cb)
    sess = tb.ANATOMY_LATIN_SESSIONS[uid1]
    assert sess["is_global"] is True
    assert sess["topic_key"] is None and sess["bone_id"] is None
    assert len(sess["queue"]) == min(tb.ANATOMY_LATIN_ALL_SESSION_SIZE, len(all_terms))
    assert len(sess["all_terms"]) == len(all_terms)
    cb_stop = FakeCB("anatomy_latin_stop", uid1)
    await tb.cb_anatomy_latin_stop(cb_stop)
    assert uid1 not in tb.ANATOMY_LATIN_SESSIONS
    print("global session sampling OK")

    # ---- aborted (stopped early) run does NOT record a leaderboard score ----
    uid2 = fresh_uid()
    tb.stats["total_users"].add(uid2)
    tb.stats["manual_anatomy_demo_granted"].append(uid2)
    assert str(uid2) not in tb.stats["anatomy_latin_scores"]
    cb = FakeCB("anatomy_latin_all_start", uid2)
    await tb.cb_anatomy_latin_all_start(cb)
    cb_stop = FakeCB("anatomy_latin_stop", uid2)
    await tb.cb_anatomy_latin_stop(cb_stop)
    assert str(uid2) not in tb.stats["anatomy_latin_scores"], "aborted run must not be scored"
    print("aborted run not scored OK")

    # ---- full completion records a score, shown on the summary screen ----
    uid3 = fresh_uid()
    tb.stats["total_users"].add(uid3)
    tb.stats["manual_anatomy_demo_granted"].append(uid3)
    summary_text, n_questions = await run_full_session(uid3, correct_answers=True)
    assert "Тренажёр пройден" in summary_text
    uid3_str = str(uid3)
    assert uid3_str in tb.stats["anatomy_latin_scores"]
    entry = tb.stats["anatomy_latin_scores"][uid3_str]
    assert entry["best_correct"] == n_questions and entry["best_total"] == n_questions
    assert entry["attempts"] == 1
    assert "Новый личный рекорд" in summary_text
    print(f"full completion (all correct, {n_questions} q) recorded personal best: OK")

    # ---- a worse repeat run does NOT overwrite the personal best, but does count as an attempt ----
    summary_text2, n_questions2 = await run_full_session(uid3, correct_answers=False)
    entry2 = tb.stats["anatomy_latin_scores"][uid3_str]
    assert entry2["best_correct"] == n_questions and entry2["best_total"] == n_questions, "worse run must not overwrite best"
    assert entry2["attempts"] == 2
    assert "Новый личный рекорд" not in summary_text2
    print("worse repeat run does not overwrite personal best: OK")

    # ---- leaderboard renders and includes the scored user ----
    cb = FakeCB("anatomy_latin_leaderboard", uid3)
    await tb.cb_anatomy_latin_leaderboard(cb)
    assert cb.message.edits
    text = cb.message.edits[-1]
    assert "Рейтинг по латинским терминам" in text
    assert tb.donor_display_name(uid3_str) in text or f"{n_questions}/{n_questions}" in text
    print("leaderboard renders and includes scored user: OK")

    # ---- leaderboard is reachable without playing first, even with zero scores ----
    tb.stats["anatomy_latin_scores"].clear()
    cb = FakeCB("anatomy_latin_leaderboard")
    await tb.cb_anatomy_latin_leaderboard(cb)
    assert cb.message.edits and "Пока никто" in cb.message.edits[-1]
    print("empty leaderboard renders gracefully: OK")

    if errors:
        print("ERRORS:")
        for e in errors[:20]:
            print(" -", e)
        raise SystemExit(1)
    print("ALL GLOBAL LATIN QUIZ TESTS PASSED")

asyncio.run(main())
