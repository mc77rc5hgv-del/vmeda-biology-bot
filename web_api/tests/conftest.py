"""Общее окружение должно существовать до импорта любого тестового модуля/web_api.config."""
import json
import os
import tempfile


os.environ["BOT_TOKEN"] = "123456789:AAIntegrationTestTokenNotReal00000000"
os.environ["SESSION_SECRET"] = "integration-test-session-secret"
os.environ["MINIAPP_ACCESS_MODE"] = "public"
os.environ["BOT_SYNC_MODE"] = "legacy"

os.environ["STATS_DIR"] = tempfile.mkdtemp(prefix="web_api_test_stats_")
os.environ["MINIAPP_LEARNING_DB"] = os.path.join(os.environ["STATS_DIR"], "learning.sqlite3")

with open(os.path.join(os.environ["STATS_DIR"], "stats.json"), "w", encoding="utf-8") as stream:
    json.dump({}, stream)
