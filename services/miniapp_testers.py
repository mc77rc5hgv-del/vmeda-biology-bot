"""Miniapp-only grants, keyed by immutable Telegram ID; paid/bot roles stay unchanged."""
from concurrent.futures import Future
from datetime import datetime, timezone


def has_test_access(tb, user_id: int) -> bool:
    record = getattr(tb, "stats", {}).get("miniapp_tester_access", {}).get(str(user_id), {})
    return isinstance(record, dict) and record.get("active") is True


def set_test_access(tb, admin_id: int, user_id: int, *, active: bool) -> Future | None:
    if not tb.is_admin(admin_id):
        raise PermissionError("Only administrators can manage testers")
    if user_id not in tb.stats.get("total_users", set()):
        raise ValueError("User must first start the bot")
    records = tb.stats.setdefault("miniapp_tester_access", {})
    record = records.setdefault(str(user_id), {"active": False, "history": []})
    event = {
        "action": "grant" if active else "revoke",
        "admin_id": admin_id,
        "at": datetime.now(timezone.utc).isoformat(),
        "username": tb.stats.get("user_username", {}).get(str(user_id)),
    }
    record["history"].append(event)
    record["active"] = active
    return tb.save_stats()
