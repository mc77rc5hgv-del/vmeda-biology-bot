"""Unit tests for state_logic.py — pure helpers over the frontend `state` blob."""

import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from state_logic import (  # noqa: E402
    detect_new_achievements,
    format_daily_reminder_text,
    is_inactive,
    is_streak_at_risk,
    js_date_string,
    module_progress,
    parse_js_date_string,
    section_progress,
    topics_due_for_review,
)


class DateStringTests(unittest.TestCase):
    def test_round_trip(self):
        d = dt.date(2026, 8, 5)
        s = js_date_string(d)
        self.assertEqual(s, "Wed Aug 05 2026")
        self.assertEqual(parse_js_date_string(s), d)

    def test_parse_invalid(self):
        self.assertIsNone(parse_js_date_string(""))
        self.assertIsNone(parse_js_date_string("garbage"))


class TopicsDueForReviewTests(unittest.TestCase):
    def test_counts_only_due_topics(self):
        now_ms = 1_000_000_000_000
        state = {
            "progress": {
                "m1:1": {"due": now_ms - 1000},
                "m1:2": {"due": now_ms + 1000},
                "m2:3": {"due": now_ms - 500},
            }
        }
        due = topics_due_for_review(state, now_ms=now_ms)
        self.assertEqual({d["key"] for d in due}, {"m1:1", "m2:3"})

    def test_ignores_malformed_entries(self):
        state = {"progress": {"m1:1": "not-a-dict", "m1:2": {"due": None}}}
        self.assertEqual(topics_due_for_review(state, now_ms=100), [])

    def test_missing_progress_key(self):
        self.assertEqual(topics_due_for_review({}, now_ms=100), [])

    def test_sorted_most_overdue_first(self):
        now_ms = 1_000_000_000_000
        state = {
            "progress": {
                "m1:1": {"due": now_ms - 86_400_000},  # 1 day overdue
                "m1:2": {"due": now_ms - 5 * 86_400_000},  # 5 days overdue
            }
        }
        due = topics_due_for_review(state, now_ms=now_ms)
        self.assertEqual([d["key"] for d in due], ["m1:2", "m1:1"])


class StreakRiskTests(unittest.TestCase):
    def test_at_risk_when_not_touched_today(self):
        today = dt.date(2026, 8, 5)
        state = {"streak": 5, "dayKey": "Tue Aug 04 2026"}
        self.assertTrue(is_streak_at_risk(state, today=today))

    def test_not_at_risk_when_touched_today(self):
        today = dt.date(2026, 8, 5)
        state = {"streak": 5, "dayKey": js_date_string(today)}
        self.assertFalse(is_streak_at_risk(state, today=today))

    def test_not_at_risk_with_zero_streak(self):
        self.assertFalse(is_streak_at_risk({"streak": 0, "dayKey": ""}))


class InactivityTests(unittest.TestCase):
    def test_inactive_past_threshold(self):
        today = dt.date(2026, 1, 16)
        state = {"lastActive": js_date_string(dt.date(2026, 1, 1))}
        self.assertTrue(is_inactive(state, threshold_days=14, today=today))

    def test_not_inactive_within_threshold(self):
        today = dt.date(2026, 1, 5)
        state = {"lastActive": js_date_string(dt.date(2026, 1, 1))}
        self.assertFalse(is_inactive(state, threshold_days=14, today=today))

    def test_missing_last_active(self):
        self.assertFalse(is_inactive({}, threshold_days=14))


class ModuleProgressTests(unittest.TestCase):
    def test_counts_passed_topics_per_module(self):
        state = {
            "progress": {
                "m1:1": {"bestPct": 80},
                "m1:2": {"bestPct": 50},
                "m2:1": {"bestPct": 100},
            }
        }
        rows = {r["id"]: r for r in module_progress(state)}
        self.assertEqual(rows["m1"]["passed"], 1)
        self.assertEqual(rows["m2"]["passed"], 1)
        self.assertEqual(rows["m3"]["passed"], 0)

    def test_empty_state_all_zero(self):
        rows = module_progress({})
        self.assertTrue(all(r["passed"] == 0 for r in rows))


class SectionProgressTests(unittest.TestCase):
    def test_passed_topic_counted_in_its_section(self):
        state = {"progress": {"m1:6": {"bestPct": 90}}}  # falls in "Кости черепа" (5-24)
        rows = {r["name"]: r for r in section_progress(state, "m1")}
        self.assertEqual(rows["Кости черепа"]["passed"], 1)
        self.assertEqual(rows["Общая остеология. Скелет туловища"]["passed"], 0)

    def test_unknown_module_returns_empty(self):
        self.assertEqual(section_progress({}, "does-not-exist"), [])


class AchievementDiffTests(unittest.TestCase):
    def test_newly_passed_topic_fires(self):
        old = {"progress": {"m1:5": {"bestPct": 60}}}
        new = {"progress": {"m1:5": {"bestPct": 92}}}
        messages = detect_new_achievements(old, new)
        self.assertEqual(len(messages), 1)
        self.assertIn("92", messages[0])

    def test_already_passed_does_not_refire(self):
        old = {"progress": {"m1:5": {"bestPct": 80}}}
        new = {"progress": {"m1:5": {"bestPct": 96}}}
        self.assertEqual(detect_new_achievements(old, new), [])

    def test_below_threshold_no_message(self):
        old = {"progress": {"m1:5": {"bestPct": 30}}}
        new = {"progress": {"m1:5": {"bestPct": 50}}}
        self.assertEqual(detect_new_achievements(old, new), [])

    def test_perfect_score_gets_extra_marker(self):
        old = {"progress": {"m1:5": {"bestPct": 60}}}
        new = {"progress": {"m1:5": {"bestPct": 100}}}
        messages = detect_new_achievements(old, new)
        self.assertIn("💯", messages[0])


class MessageTemplateTests(unittest.TestCase):
    def test_zero_due_topics_still_friendly(self):
        text = format_daily_reminder_text(0)
        self.assertNotIn("0 тем", text)

    def test_positive_due_topics(self):
        self.assertIn("3 тем", format_daily_reminder_text(3))


if __name__ == "__main__":
    unittest.main()
