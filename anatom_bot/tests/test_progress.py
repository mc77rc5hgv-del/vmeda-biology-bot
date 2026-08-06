"""Tests for progress.py — the scoring rules shared with the website.

These pin the behaviours that must match anatomapp.ru exactly; if one of these changes, the two
surfaces would start disagreeing about the same student's XP, streak or review schedule.
"""

import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import tb  # noqa: F401,E402

from progress import (  # noqa: E402
    REVIEW_INTERVALS_DAYS,
    XP_PER_NEW_ITEM,
    apply_session_result,
    next_due_ms,
    reward_key,
    touch_streak,
)
from state_logic import js_date_string  # noqa: E402

NOW_MS = 1_700_000_000_000
TODAY = dt.date(2026, 8, 5)


def base_state(**overrides):
    state = {
        "xp": 0,
        "streak": 0,
        "lastActive": "",
        "progress": {},
        "rewarded": {},
        "mistakes": [],
        "history": [],
        "dayDone": 0,
        "dayKey": "",
        "dayGoal": 20,
    }
    state.update(overrides)
    return state


class RewardKeyTests(unittest.TestCase):
    def test_prefixes_match_the_site(self):
        self.assertEqual(reward_key("test", "Вопрос?"), "q:Вопрос?")
        self.assertEqual(reward_key("flash", "Перед"), "f:Перед")
        self.assertEqual(reward_key("match", "cranium"), "m:cranium")
        self.assertEqual(reward_key("term", "os"), "t:os")


class DueDateTests(unittest.TestCase):
    def test_ladder_advances_with_reps(self):
        first = next_due_ms(1, now_ms=NOW_MS)
        second = next_due_ms(2, now_ms=NOW_MS)
        self.assertEqual(first, NOW_MS + REVIEW_INTERVALS_DAYS[0] * 86_400_000)
        self.assertEqual(second, NOW_MS + REVIEW_INTERVALS_DAYS[1] * 86_400_000)

    def test_ladder_caps_at_last_interval(self):
        self.assertEqual(
            next_due_ms(99, now_ms=NOW_MS), NOW_MS + REVIEW_INTERVALS_DAYS[-1] * 86_400_000
        )

    def test_failed_test_comes_back_tomorrow(self):
        self.assertEqual(next_due_ms(5, now_ms=NOW_MS, passed=False), NOW_MS + 86_400_000)


class StreakTests(unittest.TestCase):
    def test_same_day_keeps_streak(self):
        state = base_state(streak=4, lastActive=js_date_string(TODAY))
        self.assertEqual(touch_streak(state, today=TODAY), (4, js_date_string(TODAY)))

    def test_yesterday_extends_streak(self):
        state = base_state(streak=4, lastActive=js_date_string(TODAY - dt.timedelta(days=1)))
        streak, _ = touch_streak(state, today=TODAY)
        self.assertEqual(streak, 5)

    def test_gap_resets_streak(self):
        state = base_state(streak=9, lastActive=js_date_string(TODAY - dt.timedelta(days=3)))
        streak, _ = touch_streak(state, today=TODAY)
        self.assertEqual(streak, 1)


class ApplySessionTests(unittest.TestCase):
    def test_xp_granted_per_new_item_only(self):
        state = base_state()
        state, _ = apply_session_result(
            state, mode="test", module_id="m1", topic_num=1, topic_name="T",
            reward_keys=["q:a", "q:b"], correct=2, total=2, now_ms=NOW_MS, today=TODAY,
        )
        self.assertEqual(state["xp"], 2 * XP_PER_NEW_ITEM)

        # Replaying the same questions must not pay out again.
        state, summary = apply_session_result(
            state, mode="test", module_id="m1", topic_num=1, topic_name="T",
            reward_keys=["q:a", "q:b"], correct=2, total=2, now_ms=NOW_MS, today=TODAY,
        )
        self.assertEqual(state["xp"], 2 * XP_PER_NEW_ITEM)
        self.assertEqual(summary["earned_xp"], 0)

    def test_best_pct_never_decreases(self):
        state = base_state()
        state, _ = apply_session_result(
            state, mode="test", module_id="m1", topic_num=1, topic_name="T",
            reward_keys=["q:a", "q:b"], correct=2, total=2, now_ms=NOW_MS, today=TODAY,
        )
        self.assertEqual(state["progress"]["m1:1"]["bestPct"], 100)

        state, _ = apply_session_result(
            state, mode="test", module_id="m1", topic_num=1, topic_name="T",
            reward_keys=["q:c", "q:d"], correct=0, total=2, now_ms=NOW_MS, today=TODAY,
        )
        self.assertEqual(state["progress"]["m1:1"]["bestPct"], 100)
        self.assertEqual(state["progress"]["m1:1"]["attempts"], 2)

    def test_failed_test_reschedules_for_tomorrow(self):
        state = base_state()
        state, _ = apply_session_result(
            state, mode="test", module_id="m1", topic_num=2, topic_name="T",
            reward_keys=["q:a"], correct=0, total=4, now_ms=NOW_MS, today=TODAY,
        )
        self.assertEqual(state["progress"]["m1:2"]["due"], NOW_MS + 86_400_000)

    def test_wrong_answers_recorded_as_mistakes(self):
        state = base_state()
        wrong = [{"q": "Вопрос", "options": ["a", "b"], "correct": 1}]
        state, _ = apply_session_result(
            state, mode="test", module_id="m1", topic_num=1, topic_name="T",
            reward_keys=["q:Вопрос"], correct=0, total=1, wrong_items=wrong,
            now_ms=NOW_MS, today=TODAY,
        )
        self.assertEqual(len(state["mistakes"]), 1)

        # The same question must not pile up twice.
        state, _ = apply_session_result(
            state, mode="test", module_id="m1", topic_num=1, topic_name="T",
            reward_keys=["q:Вопрос"], correct=0, total=1, wrong_items=wrong,
            now_ms=NOW_MS, today=TODAY,
        )
        self.assertEqual(len(state["mistakes"]), 1)

    def test_mistakes_mode_clears_solved_questions(self):
        state = base_state(mistakes=[{"q": "Вопрос"}, {"q": "Другой"}])
        state, _ = apply_session_result(
            state, mode="mistakes", module_id=None, topic_num=None, topic_name="Ошибки",
            reward_keys=["q:Вопрос"], correct=1, total=1, solved_mistakes=["Вопрос"],
            now_ms=NOW_MS, today=TODAY,
        )
        self.assertEqual([m["q"] for m in state["mistakes"]], ["Другой"])

    def test_blitz_does_not_write_topic_progress(self):
        state = base_state()
        state, _ = apply_session_result(
            state, mode="blitz", module_id="m1", topic_num=3, topic_name="Блиц",
            reward_keys=["q:a"], correct=1, total=1, now_ms=NOW_MS, today=TODAY,
        )
        self.assertEqual(state["progress"], {}, "blitz spans topics; it must not claim one")

    def test_day_counter_resets_on_a_new_day(self):
        yesterday = js_date_string(TODAY - dt.timedelta(days=1))
        state = base_state(dayDone=18, dayKey=yesterday, dayGoal=20)
        state, summary = apply_session_result(
            state, mode="test", module_id="m1", topic_num=1, topic_name="T",
            reward_keys=["q:a"], correct=1, total=3, now_ms=NOW_MS, today=TODAY,
        )
        self.assertEqual(summary["day_done"], 3)

    def test_day_counter_is_capped_at_goal(self):
        state = base_state(dayDone=19, dayKey=js_date_string(TODAY), dayGoal=20)
        _, summary = apply_session_result(
            state, mode="test", module_id="m1", topic_num=1, topic_name="T",
            reward_keys=["q:a"], correct=1, total=10, now_ms=NOW_MS, today=TODAY,
        )
        self.assertEqual(summary["day_done"], 20)

    def test_original_state_is_not_mutated(self):
        state = base_state()
        snapshot = {"xp": state["xp"], "progress": dict(state["progress"])}
        apply_session_result(
            state, mode="test", module_id="m1", topic_num=1, topic_name="T",
            reward_keys=["q:a"], correct=1, total=1, now_ms=NOW_MS, today=TODAY,
        )
        self.assertEqual(state["xp"], snapshot["xp"])
        self.assertEqual(state["progress"], snapshot["progress"])


if __name__ == "__main__":
    unittest.main()
