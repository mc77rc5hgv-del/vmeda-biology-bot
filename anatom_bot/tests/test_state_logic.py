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
    topics_due_for_review,
)


class TopicsDueForReviewTests(unittest.TestCase):
    def test_counts_only_due_topics(self):
        state = {
            "progress": {
                "skull": {"nextReview": 100},
                "pelvis": {"nextReview": 200},
                "ribs": {"nextReview": 50},
            }
        }
        self.assertEqual(topics_due_for_review(state, now=150), 2)

    def test_ignores_malformed_entries(self):
        state = {"progress": {"skull": "not-a-dict", "pelvis": {"nextReview": None}}}
        self.assertEqual(topics_due_for_review(state, now=100), 0)

    def test_missing_progress_key(self):
        self.assertEqual(topics_due_for_review({}, now=100), 0)


class StreakRiskTests(unittest.TestCase):
    def test_at_risk_when_streak_positive_and_not_done(self):
        self.assertTrue(is_streak_at_risk({"streak": 5, "dayDone": False}))

    def test_not_at_risk_when_done(self):
        self.assertFalse(is_streak_at_risk({"streak": 5, "dayDone": True}))

    def test_not_at_risk_with_zero_streak(self):
        self.assertFalse(is_streak_at_risk({"streak": 0, "dayDone": False}))


class InactivityTests(unittest.TestCase):
    def test_inactive_past_threshold(self):
        now = dt.datetime(2026, 1, 16, tzinfo=dt.timezone.utc)
        last_active = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc).timestamp()
        self.assertTrue(is_inactive({"lastActive": last_active}, threshold_days=14, now=now))

    def test_not_inactive_within_threshold(self):
        now = dt.datetime(2026, 1, 5, tzinfo=dt.timezone.utc)
        last_active = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc).timestamp()
        self.assertFalse(is_inactive({"lastActive": last_active}, threshold_days=14, now=now))

    def test_missing_last_active(self):
        self.assertFalse(is_inactive({}, threshold_days=14))


class AchievementDiffTests(unittest.TestCase):
    def test_newly_crossed_90_percent_fires(self):
        old = {"progress": {"skull": {"percent": 80, "title": "Череп"}}}
        new = {"progress": {"skull": {"percent": 95, "title": "Череп"}}}
        messages = detect_new_achievements(old, new)
        self.assertEqual(len(messages), 1)
        self.assertIn("Череп", messages[0])
        self.assertIn("95", messages[0])

    def test_already_above_90_does_not_refire(self):
        old = {"progress": {"skull": {"percent": 92, "title": "Череп"}}}
        new = {"progress": {"skull": {"percent": 96, "title": "Череп"}}}
        self.assertEqual(detect_new_achievements(old, new), [])

    def test_below_90_no_message(self):
        old = {"progress": {"skull": {"percent": 50, "title": "Череп"}}}
        new = {"progress": {"skull": {"percent": 70, "title": "Череп"}}}
        self.assertEqual(detect_new_achievements(old, new), [])


class MessageTemplateTests(unittest.TestCase):
    def test_zero_due_topics_still_friendly(self):
        text = format_daily_reminder_text(0)
        self.assertNotIn("0 тем", text)

    def test_positive_due_topics(self):
        self.assertIn("3 тем", format_daily_reminder_text(3))


if __name__ == "__main__":
    unittest.main()
