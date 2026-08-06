"""Import-time bootstrap for anatom_bot tests.

config.py reads required env vars at import, and db/bot/api all import it, so tests need
placeholder values before touching any of those modules. Import this first:

    from _bootstrap import tb   # noqa

Set a real DATABASE_URL in the environment to run the live-Postgres tests; otherwise a
throwaway value is used and those tests skip themselves.
"""

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

os.environ.setdefault("ANATOM_BOT_TOKEN", "123456:test-token-not-real")
os.environ.setdefault("ANATOM_SESSION_SECRET", "test-secret-not-real-at-least-32-chars-long")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("ANATOM_WEBAPP_URL", "https://anatomapp.ru")

import config  # noqa: E402

tb = config
