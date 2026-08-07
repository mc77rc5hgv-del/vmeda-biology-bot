"""Structural checks over the bot's buttons and screens.

The dead-button test is the important one: every inline button the bot can render is matched
against the dispatcher's registered callback handlers, so a typo in callback_data fails here
instead of silently producing a button that does nothing when a student taps it.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import tb  # noqa: F401,E402

from aiogram.types import InlineKeyboardMarkup  # noqa: E402

import achievements  # noqa: E402
import bot as bot_module  # noqa: E402
import content  # noqa: E402
import keyboards as kb  # noqa: E402
import texts  # noqa: E402
from modules import MODULES  # noqa: E402

SAMPLE_STATE = {
    "xp": 1234,
    "streak": 6,
    "dayDone": 5,
    "dayGoal": 20,
    "lastActive": "Wed Aug 05 2026",
    "termLang": "ru",
    "progress": {
        "m1:1": {"bestPct": 100, "attempts": 2, "reps": 3, "due": 1, "studied": True},
        "m1:2": {"bestPct": 40, "attempts": 1, "reps": 1, "due": 10**13},
        "m4:3": {"bestPct": 80, "attempts": 1, "reps": 1},
    },
    "favorites": ["m1:1", "m4:3"],
    "mistakes": [{"q": "Вопрос?"}],
    "history": [
        {"mode": "test", "modeName": "Тест-зачёт", "topic": "Тема", "pct": 90,
         "correct": 9, "total": 10, "xp": 30, "ts": 1_760_000_000_000}
    ],
}


def collect_callback_data(markup) -> set[str]:
    if not isinstance(markup, InlineKeyboardMarkup):
        return set()
    return {
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    }


def registered_callback_handlers():
    return bot_module.dp.observers["callback_query"].handlers


class DeadButtonTests(unittest.TestCase):
    """Every rendered callback button must be accepted by some registered handler."""

    def _all_buttons(self) -> set[str]:
        module_rows = [
            {"id": m.id, "title": m.title, "icon": m.icon, "passed": 1, "total": m.topic_count, "pct": 10}
            for m in MODULES
        ]
        topics = content.topics_of("m1") or [{"num": 1, "name": "Тема"}]
        results = [{"module_id": "m1", "num": 1, "topic": {"num": 1, "name": "Тема"}}]

        markups = [
            kb.main_menu(),
            kb.back_home(),
            kb.learn_menu_keyboard(),
            kb.modules_keyboard(module_rows, "menu:module"),
            kb.module_actions_keyboard("m1"),
            kb.topics_keyboard("m1", topics, 0, {"m1:1"}),
            kb.topics_keyboard("m1", topics, 1, set()),
            kb.topic_actions_keyboard("m1", 5),
            kb.quiz_options_keyboard(["а", "б", "в", "г"]),
            kb.flash_reveal_keyboard(),
            kb.flash_grade_keyboard(),
            kb.next_question_keyboard(),
            kb.after_session_keyboard("learn:blitz"),
            kb.after_session_keyboard(None),
            kb.settings_keyboard(True, "ru", True, True),
            kb.timezone_keyboard(),
            kb.goal_keyboard(),
            kb.review_keyboard(True),
            kb.review_keyboard(False),
            kb.search_results_keyboard(results),
        ]
        found = set()
        for markup in markups:
            found |= collect_callback_data(markup)
        return found

    def test_every_button_has_a_handler(self):
        handlers = registered_callback_handlers()
        orphans = []
        for data in sorted(self._all_buttons()):
            event = type("FakeQuery", (), {"data": data})()
            if not any(self._matches(handler, event) for handler in handlers):
                orphans.append(data)
        self.assertEqual(orphans, [], f"buttons with no handler: {orphans}")

    @staticmethod
    def _matches(handler, event) -> bool:
        for flt in handler.filters or []:
            callback = getattr(flt, "callback", flt)
            try:
                if not callback(event):
                    return False
            except Exception:
                return False
        return True


class ReplyNavigationTests(unittest.TestCase):
    """The persistent buttons next to the input field must work from anywhere."""

    def _message_handlers(self):
        return bot_module.dp.observers["message"].handlers

    def _matching_index(self, text: str):
        """Index of the first message handler that accepts this text, or None."""
        event = type("FakeMessage", (), {"text": text})()
        for index, handler in enumerate(self._message_handlers()):
            ok = True
            for flt in handler.filters or []:
                callback = getattr(flt, "callback", flt)
                try:
                    if not callback(event):
                        ok = False
                        break
                except Exception:
                    ok = False
                    break
            if ok:
                return index
        return None

    def test_reply_keyboard_has_the_expected_buttons(self):
        rendered = [button.text for row in kb.reply_nav().keyboard for button in row]
        self.assertEqual(sorted(rendered), sorted(kb.NAV_BUTTONS))

    def test_every_nav_button_has_a_handler(self):
        orphans = [text for text in kb.NAV_BUTTONS if self._matching_index(text) is None]
        self.assertEqual(orphans, [], f"nav buttons with no handler: {orphans}")

    def test_nav_buttons_are_handled_before_the_search_fallback(self):
        """Otherwise tapping a button would just search for its own label."""
        fallback = self._matching_index("произвольный текст")
        self.assertIsNotNone(fallback, "the catch-all search handler disappeared")
        for text in kb.NAV_BUTTONS:
            self.assertLess(
                self._matching_index(text),
                fallback,
                f"'{text}' is shadowed by the search fallback",
            )

    def test_keyboard_stays_open_and_compact(self):
        markup = kb.reply_nav()
        self.assertTrue(markup.is_persistent, "keyboard would collapse behind the input icon")
        self.assertTrue(markup.resize_keyboard, "keyboard would eat half the screen")


class BotCommandMenuTests(unittest.TestCase):
    def test_commands_are_declared_for_the_menu_button(self):
        self.assertGreaterEqual(len(bot_module.BOT_COMMANDS), 10)

    def test_every_declared_command_has_a_handler(self):
        from aiogram.filters import Command

        registered = set()
        for handler in bot_module.dp.observers["message"].handlers:
            for flt in handler.filters or []:
                callback = getattr(flt, "callback", flt)
                if isinstance(callback, Command):
                    registered.update(str(c) for c in callback.commands)

        missing = [c.command for c in bot_module.BOT_COMMANDS if c.command not in registered]
        self.assertEqual(missing, [], f"commands listed in the menu but not implemented: {missing}")

    def test_command_descriptions_fit_telegram_limits(self):
        for command in bot_module.BOT_COMMANDS:
            self.assertLessEqual(len(command.command), 32, command.command)
            self.assertLessEqual(len(command.description), 256, command.command)


class AdminPanelTests(unittest.TestCase):
    def test_admin_button_only_on_the_admin_keyboard(self):
        plain = [b.text for row in kb.reply_nav().keyboard for b in row]
        as_admin = [b.text for row in kb.reply_nav(is_admin=True).keyboard for b in row]
        self.assertNotIn(kb.NAV_ADMIN, plain)
        self.assertIn(kb.NAV_ADMIN, as_admin)

    def test_admin_panel_buttons_all_have_handlers(self):
        import admin

        handlers = registered_callback_handlers()
        data = collect_callback_data(admin.admin_menu_keyboard())
        data |= collect_callback_data(admin.broadcast_confirm_keyboard("all", 10))
        orphans = []
        for item in sorted(data):
            event = type("FakeQuery", (), {"data": item})()
            if not any(DeadButtonTests._matches(handler, event) for handler in handlers):
                orphans.append(item)
        self.assertEqual(orphans, [], f"admin buttons with no handler: {orphans}")

    def test_is_admin_matches_configured_ids(self):
        import admin

        for admin_id in tb.ADMIN_IDS:
            self.assertTrue(admin.is_admin(admin_id))
        self.assertFalse(admin.is_admin(-1))

    def test_broadcast_preview_states_audience_and_size(self):
        import admin

        preview = admin.broadcast_preview_text("Привет всем!", "inactive", 137)
        self.assertIn("137", preview)
        self.assertIn("спящим", preview)
        self.assertIn("Привет всем!", preview)

    def test_broadcast_preview_truncates_long_text(self):
        import admin

        preview = admin.broadcast_preview_text("а" * 2000, "all", 5)
        self.assertLess(len(preview), 1200, "preview must stay inside Telegram's message limit")

    def test_confirm_button_carries_the_cohort(self):
        import admin

        data = collect_callback_data(admin.broadcast_confirm_keyboard("inactive", 3))
        self.assertIn("admin_bc_go:inactive", data)


class SiteLinkTests(unittest.TestCase):
    """The site link must appear on every screen — driving students to the web app is the point."""

    def _markups(self) -> dict[str, InlineKeyboardMarkup]:
        module_rows = [
            {"id": m.id, "title": m.title, "icon": m.icon, "passed": 1, "total": m.topic_count, "pct": 10}
            for m in MODULES
        ]
        topics = content.topics_of("m1") or [{"num": 1, "name": "Тема"}]
        results = [{"module_id": "m1", "num": 1, "topic": {"num": 1, "name": "Тема"}}]
        return {
            "main_menu": kb.main_menu(),
            "back_home": kb.back_home(),
            "learn_menu": kb.learn_menu_keyboard(),
            "modules": kb.modules_keyboard(module_rows, "menu:module"),
            "module_actions": kb.module_actions_keyboard("m1"),
            "topics": kb.topics_keyboard("m1", topics, 0, set()),
            "topic_actions": kb.topic_actions_keyboard("m1", 5),
            "quiz_options": kb.quiz_options_keyboard(["а", "б", "в", "г"]),
            "flash_reveal": kb.flash_reveal_keyboard(),
            "flash_grade": kb.flash_grade_keyboard(),
            "next_question": kb.next_question_keyboard(),
            "after_session": kb.after_session_keyboard("learn:blitz"),
            "settings": kb.settings_keyboard(True, "ru", True, True),
            "timezone": kb.timezone_keyboard(),
            "goal": kb.goal_keyboard(),
            "review": kb.review_keyboard(True),
            "search": kb.search_results_keyboard(results),
            "webapp": kb.webapp_keyboard(),
        }

    def test_every_screen_links_to_the_site(self):
        missing = [
            name
            for name, markup in self._markups().items()
            if not any(
                button.url == tb.WEBAPP_URL for row in markup.inline_keyboard for button in row
            )
        ]
        self.assertEqual(missing, [], f"screens with no link to the site: {missing}")

    def test_link_never_displaces_the_first_row(self):
        """It sits last so it can't be tapped by accident instead of an answer or a menu item."""
        for name, markup in self._markups().items():
            if name == "webapp":
                continue
            first_row = markup.inline_keyboard[0]
            self.assertFalse(
                all(button.url for button in first_row),
                f"{name}: the site link took over the first row",
            )


class TextRenderingTests(unittest.TestCase):
    """Every screen must render without raising, including from an empty state."""

    def test_profile(self):
        for state in (SAMPLE_STATE, {}):
            text = texts.profile_text(state, {}, name="Иван", referrals=2)
            self.assertIn("Уровень", text)

    def test_profile_with_exam_date(self):
        text = texts.profile_text(SAMPLE_STATE, {"exam_date": "2027-06-15"}, name="И", referrals=0)
        self.assertIn("экзамена", text)

    def test_stats(self):
        for state in (SAMPLE_STATE, {}):
            self.assertIn("статистика", texts.stats_text(state))

    def test_leaderboard_with_and_without_rows(self):
        rows = [{"id": 1, "first_name": "А", "last_name": None, "username": None, "xp": 500}]
        self.assertIn("Рейтинг", texts.leaderboard_text(rows, 1, 500, 1, viewer_id=1))
        self.assertIn("Стань первым", texts.leaderboard_text([], None, 0, 0, viewer_id=1))

    def test_exam_plan_without_date_prompts_for_one(self):
        self.assertIn("не задана", texts.exam_plan_text({}, SAMPLE_STATE))

    def test_exam_plan_computes_daily_load(self):
        future = "2099-01-01"
        self.assertIn("План", texts.exam_plan_text({"exam_date": future}, SAMPLE_STATE))

    def test_exam_plan_handles_past_date(self):
        self.assertIn("прошёл", texts.exam_plan_text({"exam_date": "2000-01-01"}, SAMPLE_STATE))

    def test_exam_plan_ignores_malformed_date(self):
        self.assertIn("не задана", texts.exam_plan_text({"exam_date": "не дата"}, SAMPLE_STATE))

    def test_weekly_digest_skipped_without_activity(self):
        self.assertIsNone(texts.weekly_digest_text({"history": []}, name="И"))

    def test_session_result(self):
        summary = {"pct": 80, "correct": 8, "total": 10, "earned_xp": 30,
                   "streak": 3, "streak_up": True, "day_done": 10, "day_goal": 20}
        text = texts.session_result_text(summary, "📝 Тест")
        self.assertIn("+30 XP", text)
        self.assertIn("Серия продлена", text)

    def test_session_result_without_xp_explains_why(self):
        summary = {"pct": 50, "correct": 1, "total": 2, "earned_xp": 0,
                   "streak": 1, "streak_up": False, "day_done": 2, "day_goal": 20}
        self.assertIn("уже были засчитаны", texts.session_result_text(summary, "📝 Тест"))

    def test_term_of_the_day_is_stable_per_date(self):
        import datetime as dt

        day = dt.date(2026, 8, 5)
        self.assertEqual(texts.term_of_the_day(day), texts.term_of_the_day(day))

    def test_progress_bar_bounds(self):
        self.assertEqual(len(texts.progress_bar(0)), 10)
        self.assertEqual(len(texts.progress_bar(100)), 10)
        self.assertEqual(len(texts.progress_bar(250)), 10)


class AchievementTests(unittest.TestCase):
    def test_levels_increase_with_xp(self):
        self.assertEqual(achievements.level_for_xp(0)[0], 1)
        self.assertGreater(achievements.level_for_xp(30000)[0], achievements.level_for_xp(100)[0])

    def test_top_level_reports_no_remaining_xp(self):
        self.assertEqual(achievements.level_for_xp(10**9)[3], 0)

    def test_badges_unlock_from_state(self):
        codes = {badge.code for badge in achievements.earned_badges(SAMPLE_STATE)}
        self.assertIn("first_steps", codes)
        self.assertIn("perfectionist", codes)
        self.assertIn("streak_3", codes)

    def test_no_badges_for_empty_state(self):
        self.assertEqual(achievements.earned_badges({}), [])

    def test_clean_sheet_requires_actual_attempts(self):
        # An untouched account has no mistakes, but that is not an achievement.
        codes = {b.code for b in achievements.earned_badges({"progress": {}, "mistakes": []})}
        self.assertNotIn("no_mistakes", codes)

    def test_newly_earned_respects_announced_list(self):
        first = achievements.newly_earned(SAMPLE_STATE, [])
        self.assertTrue(first)
        again = achievements.newly_earned(SAMPLE_STATE, [b.code for b in first])
        self.assertEqual(again, [])


if __name__ == "__main__":
    unittest.main()
