"""Tests for the scheduled jobs.

The coroutine-function check is a regression guard: APScheduler only *awaits* jobs it recognises
as coroutine functions. Registering a plain lambda that returns a coroutine makes every job
"succeed" instantly while doing nothing, and the only symptom is a RuntimeWarning in the log —
so no reminder, digest or streak warning would ever be delivered.
"""

import asyncio
import inspect
import logging
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import tb  # noqa: F401,E402

import scheduler  # noqa: E402

EXPECTED_JOB_IDS = {
    "daily_reminders",
    "streak_protection",
    "term_of_the_day",
    "inactivity_winback",
    "badge_sweep",
    "weekly_digest",
}


class FakeScheduler:
    """Stands in for AsyncIOScheduler so start_scheduler can be exercised without a loop."""

    def __init__(self):
        self.jobs = {}

    def add_job(self, func, trigger, *, id, **kwargs):
        self.jobs[id] = {"func": func, "trigger": trigger, "kwargs": kwargs}

    def start(self):
        self.started = True

    def get_jobs(self):
        return list(self.jobs.values())


class JobRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeScheduler()
        self._real = scheduler.AsyncIOScheduler
        scheduler.AsyncIOScheduler = lambda **kwargs: self.fake
        scheduler.start_scheduler(bot=object())

    def tearDown(self):
        scheduler.AsyncIOScheduler = self._real

    def test_all_expected_jobs_registered(self):
        self.assertEqual(set(self.fake.jobs), EXPECTED_JOB_IDS)

    def test_every_job_is_a_coroutine_function(self):
        for job_id, job in self.fake.jobs.items():
            self.assertTrue(
                inspect.iscoroutinefunction(job["func"]),
                f"job {job_id} would never be awaited by APScheduler",
            )

    def test_jobs_do_not_pile_up(self):
        for job_id, job in self.fake.jobs.items():
            self.assertEqual(job["kwargs"].get("max_instances"), 1, job_id)
            self.assertTrue(job["kwargs"].get("coalesce"), job_id)

    def test_job_failure_is_contained(self):
        """A raising job must not propagate — one bad sweep shouldn't take down the scheduler."""

        async def boom(_bot):
            raise RuntimeError("kaboom")

        async def scenario():
            await scheduler._guarded("test_job", lambda: boom(None))

        # The failure is logged on purpose; silence it so the suite's output stays readable.
        logging.disable(logging.CRITICAL)
        try:
            asyncio.run(scenario())  # must not raise
        finally:
            logging.disable(logging.NOTSET)


class LocalTimeTests(unittest.TestCase):
    def test_unknown_timezone_falls_back_instead_of_raising(self):
        import datetime as dt

        now = dt.datetime(2026, 8, 5, 12, 0, tzinfo=dt.timezone.utc)
        self.assertEqual(scheduler._local_now("Not/AZone", now).hour, 12)

    def test_known_timezone_shifts_the_hour(self):
        import datetime as dt

        now = dt.datetime(2026, 8, 5, 12, 0, tzinfo=dt.timezone.utc)
        self.assertEqual(scheduler._local_now("Europe/Moscow", now).hour, 15)


if __name__ == "__main__":
    unittest.main()
