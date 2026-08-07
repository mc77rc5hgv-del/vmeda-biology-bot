"""Pure helpers over the frontend-owned `state` JSON blob — no DB/network, unit-testable.

Mirrors anatomapp.ru's own `persist()`/`hydrateUser()` shape exactly (see db.py's DEFAULT_STATE
docstring for the field-by-field breakdown). Two frontend quirks worth calling out because they're
easy to get wrong:

- `progress[key].due`/`.last` are JS epoch-**millisecond** timestamps (`Date.now()`), not seconds.
- `lastActive` is a JS `Date.toDateString()` string (e.g. "Wed Aug 05 2026"), not a timestamp —
  `js_date_string()`/`parse_js_date_string()` below convert between that and a Python `date`
  without depending on the server's locale (Python's %a/%b are locale-sensitive; JS's are not).
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from modules import MODULES, PASS_THRESHOLD, describe_key, parse_key

_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def js_date_string(d: dt.date) -> str:
    return f"{_WEEKDAYS[d.weekday()]} {_MONTHS[d.month - 1]} {d.day:02d} {d.year}"


def parse_js_date_string(s: str) -> Optional[dt.date]:
    if not s:
        return None
    parts = s.split()
    if len(parts) != 4:
        return None
    _, mon_abbr, day_str, year_str = parts
    try:
        month = _MONTHS.index(mon_abbr) + 1
        return dt.date(int(year_str), month, int(day_str))
    except (ValueError, IndexError):
        return None


def topics_due_for_review(state: dict[str, Any], *, now_ms: Optional[int] = None) -> list[dict[str, Any]]:
    """Mirrors the site's own due-list (reviewList in index.html): entries with `due` in the past,
    sorted most-overdue first."""
    now_ms = now_ms if now_ms is not None else int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    progress = state.get("progress") or {}
    due: list[dict[str, Any]] = []
    for key, entry in progress.items():
        if not isinstance(entry, dict):
            continue
        due_at = entry.get("due")
        if not isinstance(due_at, (int, float)) or due_at <= 0 or due_at > now_ms:
            continue
        overdue_days = int((now_ms - due_at) // 86_400_000)
        due.append({"key": key, "overdue_days": overdue_days, "label": describe_key(key)})
    due.sort(key=lambda d: d["overdue_days"], reverse=True)
    return due


def is_streak_at_risk(state: dict[str, Any], *, today: Optional[dt.date] = None) -> bool:
    today = today or dt.datetime.now(dt.timezone.utc).date()
    streak = state.get("streak", 0)
    if not streak:
        return False
    return state.get("dayKey") != js_date_string(today)


def is_inactive(state: dict[str, Any], *, threshold_days: int, today: Optional[dt.date] = None) -> bool:
    last_active = parse_js_date_string(state.get("lastActive", ""))
    if last_active is None:
        return False
    today = today or dt.datetime.now(dt.timezone.utc).date()
    return (today - last_active) > dt.timedelta(days=threshold_days)


def module_progress(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-module passed/total counts, mirroring the site's `systemProgress` (bestPct >= 75)."""
    progress = state.get("progress") or {}
    passed_by_module: dict[str, int] = {}
    for key, entry in progress.items():
        if not isinstance(entry, dict) or (entry.get("bestPct") or 0) < PASS_THRESHOLD:
            continue
        parsed = parse_key(key)
        if parsed is None:
            continue
        module_id = parsed[0]
        passed_by_module[module_id] = passed_by_module.get(module_id, 0) + 1

    result = []
    for module in MODULES:
        passed = passed_by_module.get(module.id, 0)
        pct = round(passed / module.topic_count * 100) if module.topic_count else 0
        result.append(
            {
                "id": module.id,
                "title": module.title,
                "icon": module.icon,
                "passed": passed,
                "total": module.topic_count,
                "pct": pct,
            }
        )
    return result


