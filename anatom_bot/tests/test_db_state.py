"""State-persistence tests against a real Postgres if DATABASE_URL is set, else skipped.

Regression cover for two bugs that made the website unable to save progress at all:
  1. `PUT /api/state` opened a second transaction on a session whose read had already
     autobegun one -> InvalidRequestError -> HTTP 500 on every save.
  2. `get_state` handed back the live attached JSONB dict, so a read-modify-write ended up
     assigning the object to itself and SQLAlchemy flushed nothing.
"""

import asyncio
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import tb  # noqa: F401,E402  (sets env + sys.path before importing db)

import db  # noqa: E402

# The bootstrap installs a throwaway localhost URL; only a real one means "run live DB tests".
HAS_DB = "localhost:5432/test" not in os.environ.get("DATABASE_URL", "")


TEST_USER_ID = 999_000_222


@unittest.skipUnless(HAS_DB, "DATABASE_URL not set — skipping live-Postgres tests")
class StatePersistenceTests(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_read_modify_write_round_trip(self):
        async def scenario():
            await db.init_models()
            session_maker = db.get_session_maker()

            async with session_maker() as session:
                await db.get_or_create_user(session, telegram_id=TEST_USER_ID)
                await db.put_state(session, TEST_USER_ID, {"xp": 0, "progress": {}})
                await session.commit()

            # The exact shape that used to raise InvalidRequestError: read first, then write,
            # then commit, all on one session.
            async with session_maker() as session:
                state = await db.get_state(session, TEST_USER_ID)
                state["xp"] = 123
                state["progress"]["m1:5"] = {"bestPct": 90}
                await db.put_state(session, TEST_USER_ID, state)
                await session.commit()

            async with session_maker() as session:
                reloaded = await db.get_state(session, TEST_USER_ID)

            async with session_maker() as session:
                row = await session.get(db.UserState, TEST_USER_ID)
                if row:
                    await session.delete(row)
                user = await session.get(db.User, TEST_USER_ID)
                reminder = await session.get(db.Reminder, TEST_USER_ID)
                if reminder:
                    await session.delete(reminder)
                if user:
                    await session.delete(user)
                await session.commit()

            return reloaded

        reloaded = self._run(scenario())
        self.assertEqual(reloaded["xp"], 123)
        self.assertEqual(reloaded["progress"]["m1:5"]["bestPct"], 90)


class DefaultStateIsolationTests(unittest.TestCase):
    """No DB needed — guards the shallow-copy bug where every new user shared one nested dict."""

    def test_nested_containers_are_not_shared(self):
        a = db.default_state()
        b = db.default_state()
        a["progress"]["m1:1"] = {"bestPct": 100}
        a["favorites"].append("m1:1")
        self.assertEqual(b["progress"], {}, "progress dict leaked between users")
        self.assertEqual(b["favorites"], [], "favorites list leaked between users")
        self.assertEqual(db.DEFAULT_STATE["progress"], {}, "the module-level default was mutated")


if __name__ == "__main__":
    unittest.main()
