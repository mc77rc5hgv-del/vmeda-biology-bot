# -*- coding: utf-8 -*-
"""Shared setup for the hand-rolled test scripts in this directory (no pytest —
each test_*.py is a standalone script run with `python3 tests/test_foo.py`).

Import `tb` from here instead of `import telegram_bot as tb` directly, e.g.:

    from _bootstrap import tb

This makes sure telegram_bot's module-level env reads (BOT_TOKEN, STATS_DIR) and
JSON file loads (relative to the repo root) happen correctly regardless of the
current working directory, and that each test run gets a fresh, isolated
STATS_DIR so tests never read or write the real stats.json.
"""
import os
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

os.environ.setdefault("BOT_TOKEN", "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
os.environ.setdefault("STATS_DIR", tempfile.mkdtemp(prefix="vmeda_test_stats_"))

# telegram_bot.py loads its JSON content files with relative paths (e.g. open("tickets.json")),
# so it must be imported with the repo root as the current working directory.
_prev_cwd = os.getcwd()
os.chdir(REPO_ROOT)
try:
    import telegram_bot as tb  # noqa: E402, F401
finally:
    os.chdir(_prev_cwd)
