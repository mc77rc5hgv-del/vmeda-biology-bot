"""Общее окружение должно существовать до импорта любого тестового модуля/web_api.config."""
import json
import os
import tempfile


os.environ.setdefault("BOT_TOKEN", "123456789:AAIntegrationTestTokenNotReal00000000")
os.environ.setdefault("SESSION_SECRET", "integration-test-session-secret")

if not os.environ.get("STATS_DIR"):
    os.environ["STATS_DIR"] = tempfile.mkdtemp(prefix="web_api_test_stats_")

with open(os.path.join(os.environ["STATS_DIR"], "stats.json"), "w", encoding="utf-8") as stream:
    json.dump({}, stream)
