"""Structural checks over the bot's buttons and screens.

The bot's whole job is to open the MiniApp, so the launch-button tests are the important ones:
they assert that every screen offers a way in, and that those buttons really are WebApp buttons
(a plain URL button would open a browser instead of the MiniApp).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import tb  # noqa: F401,E402

from aiogram.types import InlineKeyboardMarkup  # noqa: E402

import admin  # noqa: E402
import bot as bot_module  # noqa: E402
import keyboards as kb  # noqa: E402
import texts  # noqa: E402


def collect_callback_data(markup) -> set[str]:
    if not isinstance(markup, InlineKeyboardMarkup):
        return set()
    return {b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data}


def registered_callback_handlers():
    return bot_module.dp.observers["callback_query"].handlers


def matches(handler, event) -> bool:
    for flt in handler.filters or []:
        callback = getattr(flt, "callback", flt)
        try:
            if not callback(event):
                return False
        except Exception:
            return False
    return True


class MiniAppLaunchTests(unittest.TestCase):
    """Every route into the app must be a WebApp button pointing at the configured URL."""

    def _inline_screens(self) -> dict[str, InlineKeyboardMarkup]:
        return {
            "open_app": kb.open_app(),
            "with_app": kb.with_app(),
            "reminders_on": kb.reminder_keyboard(True),
            "reminders_off": kb.reminder_keyboard(False),
        }

    def test_every_inline_screen_opens_the_miniapp(self):
        missing = [
            name
            for name, markup in self._inline_screens().items()
            if not any(
                b.web_app and b.web_app.url == tb.WEBAPP_URL
                for row in markup.inline_keyboard
                for b in row
            )
        ]
        self.assertEqual(missing, [], f"screens with no MiniApp button: {missing}")

    def test_launch_button_comes_first(self):
        """It is the point of the screen, so nothing should sit above it."""
        for name, markup in self._inline_screens().items():
            self.assertTrue(
                any(b.web_app for b in markup.inline_keyboard[0]),
                f"{name}: first row does not launch the app",
            )

    def test_reply_keyboard_launches_the_app_directly(self):
        button = kb.reply_nav().keyboard[0][0]
        self.assertEqual(button.text, kb.NAV_APP)
        self.assertIsNotNone(button.web_app, "must open the MiniApp, not send text")
        self.assertEqual(button.web_app.url, tb.WEBAPP_URL)

    def test_chat_menu_button_opens_the_app(self):
        menu = kb.menu_button()
        self.assertEqual(menu.web_app.url, tb.WEBAPP_URL)

    def test_keyboard_stays_open_and_compact(self):
        markup = kb.reply_nav()
        self.assertTrue(markup.is_persistent)
        self.assertTrue(markup.resize_keyboard)

    def test_admin_button_only_on_the_admin_keyboard(self):
        plain = [b.text for row in kb.reply_nav().keyboard for b in row]
        as_admin = [b.text for row in kb.reply_nav(is_admin=True).keyboard for b in row]
        self.assertNotIn(kb.NAV_ADMIN, plain)
        self.assertIn(kb.NAV_ADMIN, as_admin)


class DeadButtonTests(unittest.TestCase):
    def _all_callback_data(self) -> set[str]:
        data = set()
        for markup in (
            kb.reminder_keyboard(True),
            kb.timezone_keyboard(),
            admin.admin_menu_keyboard(),
            admin.broadcast_confirm_keyboard("all", 5),
        ):
            data |= collect_callback_data(markup)
        return data

    def test_every_button_has_a_handler(self):
        handlers = registered_callback_handlers()
        orphans = []
        for item in sorted(self._all_callback_data()):
            event = type("FakeQuery", (), {"data": item})()
            if not any(matches(handler, event) for handler in handlers):
                orphans.append(item)
        self.assertEqual(orphans, [], f"buttons with no handler: {orphans}")

    def test_check_is_not_vacuous(self):
        event = type("FakeQuery", (), {"data": "definitely:not:a:real:button"})()
        self.assertFalse(any(matches(h, event) for h in registered_callback_handlers()))


class NavigationTests(unittest.TestCase):
    def _message_handlers(self):
        return bot_module.dp.observers["message"].handlers

    def _matching_index(self, text: str):
        event = type("FakeMessage", (), {"text": text})()
        for index, handler in enumerate(self._message_handlers()):
            if matches(handler, event):
                return index
        return None

    def test_reply_buttons_have_handlers(self):
        for text in (kb.NAV_REMINDER, kb.NAV_ADMIN):
            self.assertIsNotNone(self._matching_index(text), f"no handler for {text}")

    def test_reply_buttons_resolve_before_the_catch_all(self):
        fallback = self._matching_index("произвольный текст")
        self.assertIsNotNone(fallback)
        for text in (kb.NAV_REMINDER, kb.NAV_ADMIN):
            self.assertLess(self._matching_index(text), fallback, f"'{text}' is shadowed")

    def test_declared_commands_all_have_handlers(self):
        from aiogram.filters import Command

        registered = set()
        for handler in self._message_handlers():
            for flt in handler.filters or []:
                callback = getattr(flt, "callback", flt)
                if isinstance(callback, Command):
                    registered.update(str(c) for c in callback.commands)

        missing = [c.command for c in bot_module.BOT_COMMANDS if c.command not in registered]
        self.assertEqual(missing, [], f"commands in the menu with no handler: {missing}")

    def test_command_menu_is_short(self):
        """The app is the product; the command list should not compete with it."""
        self.assertLessEqual(len(bot_module.BOT_COMMANDS), 5)


class NoDuplicatedStudyFeaturesTests(unittest.TestCase):
    """Studying belongs to the MiniApp — the bot must not grow a parallel copy of it."""

    def test_study_modules_are_gone(self):
        for name in ("quiz", "progress", "achievements", "content"):
            with self.assertRaises(ImportError, msg=f"{name} came back"):
                __import__(name)

    def test_no_study_commands_are_advertised(self):
        advertised = {c.command for c in bot_module.BOT_COMMANDS}
        for command in ("blitz", "review", "stats", "profile", "top", "term", "streak", "exam"):
            self.assertNotIn(command, advertised)


class TextTests(unittest.TestCase):
    def test_welcome_mentions_the_app(self):
        self.assertIn("АНАТОМ", texts.welcome_text("Иван"))

    def test_reminder_status_reflects_state(self):
        self.assertIn("выключены", texts.reminder_status_text(False, "19:00", "Europe/Moscow"))
        self.assertIn("19:00", texts.reminder_status_text(True, "19:00", "Europe/Moscow"))

    def test_daily_reminder_avoids_a_zero_count(self):
        self.assertNotIn("0 тем", texts.format_daily_reminder_text(0))
        self.assertIn("3", texts.format_daily_reminder_text(3))

    def test_term_of_the_day_is_stable_per_date(self):
        import datetime as dt

        day = dt.date(2026, 8, 5)
        self.assertEqual(texts.term_of_the_day(day), texts.term_of_the_day(day))

    def test_terms_dataset_is_loaded(self):
        self.assertGreater(len(texts.TERMS), 500)

    def test_weekly_digest_skipped_without_activity(self):
        self.assertIsNone(texts.weekly_digest_text({"history": []}, name="И"))


class AdminPanelTests(unittest.TestCase):
    def test_is_admin_matches_configured_ids(self):
        for admin_id in tb.ADMIN_IDS:
            self.assertTrue(admin.is_admin(admin_id))
        self.assertFalse(admin.is_admin(-1))

    def test_broadcast_preview_states_audience_and_size(self):
        preview = admin.broadcast_preview_text("Привет!", "inactive", 137)
        self.assertIn("137", preview)
        self.assertIn("спящим", preview)

    def test_broadcast_preview_truncates_long_text(self):
        self.assertLess(len(admin.broadcast_preview_text("а" * 2000, "all", 5)), 1200)

    def test_confirm_button_carries_the_cohort(self):
        data = collect_callback_data(admin.broadcast_confirm_keyboard("inactive", 3))
        self.assertIn("admin_bc_go:inactive", data)


class UserLookupTests(unittest.TestCase):
    class FakeSession:
        def __init__(self, found=None):
            self.found = found
            self.get_args = None
            self.executed_sql = None

        async def get(self, model, pk):
            self.get_args = (model, pk)
            return self.found

        async def execute(self, statement):
            from sqlalchemy.dialects import postgresql

            self.executed_sql = str(statement.compile(dialect=postgresql.dialect()))
            outer = self

            class Result:
                def scalar_one_or_none(self):
                    return outer.found

                def scalars(self):
                    return self

                def all(self):
                    return [outer.found] if outer.found else []

            return Result()

    def _run(self, coro):
        import asyncio

        return asyncio.run(coro)

    def test_numeric_input_looks_up_by_primary_key(self):
        import db

        session = self.FakeSession(found="user")
        self.assertEqual(self._run(db.resolve_user(session, " 1326779223 ")), "user")
        self.assertEqual(session.get_args[1], 1326779223)

    def test_at_prefix_is_stripped_and_matched_case_insensitively(self):
        import db

        session = self.FakeSession(found="user")
        self._run(db.resolve_user(session, "@SomeUser"))
        self.assertIn("lower(users.username)", session.executed_sql)

    def test_blank_input_resolves_to_nothing(self):
        import db

        for value in ("", "   ", "@"):
            session = self.FakeSession(found="user")
            self.assertIsNone(self._run(db.resolve_user(session, value)))

    def test_fuzzy_search_needs_two_characters(self):
        import db

        session = self.FakeSession(found="user")
        self.assertEqual(self._run(db.search_users(session, "a")), [])
        self.assertIsNone(session.executed_sql)


if __name__ == "__main__":
    unittest.main()


class AllowedOriginTests(unittest.TestCase):
    """A host that redirects apex -> www (Vercel's default) changes the page origin, so both
    forms must be allowed or every state sync fails CORS after the migration."""

    def test_both_apex_and_www_are_allowed(self):
        import config

        self.assertIn("https://anatomapp.ru", config._origin_variants("https://anatomapp.ru"))
        self.assertIn("https://www.anatomapp.ru", config._origin_variants("https://anatomapp.ru"))

    def test_www_input_also_yields_the_apex(self):
        import config

        variants = config._origin_variants("https://www.anatomapp.ru")
        self.assertIn("https://anatomapp.ru", variants)
        self.assertIn("https://www.anatomapp.ru", variants)

    def test_trailing_slash_is_stripped(self):
        import config

        for origin in config._origin_variants("https://anatomapp.ru/"):
            self.assertFalse(origin.endswith("/"), origin)

    def test_blank_url_yields_nothing(self):
        import config

        self.assertEqual(config._origin_variants(""), [])
