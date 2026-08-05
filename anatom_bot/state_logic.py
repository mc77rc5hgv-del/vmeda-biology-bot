"""Pure helpers over the frontend-owned `state` JSONB blob — no DB/network, unit-testable.

The top-level keys of `state` are fixed by the frontend (see docs/anatom-bot-spec.md):
progress, mistakes, favorites, notes, xp, streak, lastActive, history, dayDone, dayKey,
dayGoal, lastTopic, examDone, termLang, reminders.

The *nested* shape of `progress` isn't specified anywhere yet, so the helpers below make one
narrow assumption, isolated here so it's a one-place fix once the real frontend schema lands:
`state["progress"]` is a dict of `topic_id -> {"nextReview": <epoch seconds>, "percent": <0-100>}`.
Missing/malformed entries are skipped rather than raising.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional


def topics_due_for_review(state: dict[str, Any], *, now: Optional[int] = None) -> int:
    now = now if now is not None else int(dt.datetime.now(dt.timezone.utc).timestamp())
    progress = state.get("progress") or {}
    count = 0
    for entry in progress.values():
        if not isinstance(entry, dict):
            continue
        next_review = entry.get("nextReview")
        if isinstance(next_review, (int, float)) and next_review <= now:
            count += 1
    return count


def is_streak_at_risk(state: dict[str, Any]) -> bool:
    return bool(state.get("streak", 0)) and not state.get("dayDone", False)


def is_inactive(state: dict[str, Any], *, threshold_days: int, now: Optional[dt.datetime] = None) -> bool:
    last_active = state.get("lastActive")
    if not last_active:
        return False
    now = now or dt.datetime.now(dt.timezone.utc)
    if isinstance(last_active, (int, float)):
        last_active_dt = dt.datetime.fromtimestamp(last_active, tz=dt.timezone.utc)
    else:
        return False
    return (now - last_active_dt) > dt.timedelta(days=threshold_days)


def format_daily_reminder_text(due_count: int) -> str:
    if due_count <= 0:
        return "Пора закрепить анатомию 🦴 Загляни повторить пройденное."
    return f"Пора закрепить анатомию 🦴 {due_count} тем ждут повторения"


def format_streak_warning_text(streak: int) -> str:
    return f"🔥 Серия {streak} дней под угрозой! 5 минут — и она сохранится"


def format_inactivity_text(last_topic: Optional[str]) -> str:
    if last_topic:
        return f"Скучаем! Продолжи с темы «{last_topic}»."
    return "Скучаем! Возвращайся к учёбе."


def detect_new_achievements(old_state: dict[str, Any], new_state: dict[str, Any]) -> list[str]:
    """Diff two state snapshots and return achievement messages for newly-crossed 90% sections."""
    old_progress = old_state.get("progress") or {}
    new_progress = new_state.get("progress") or {}
    messages: list[str] = []
    for topic_id, entry in new_progress.items():
        if not isinstance(entry, dict):
            continue
        new_percent = entry.get("percent")
        if not isinstance(new_percent, (int, float)) or new_percent < 90:
            continue
        old_entry = old_progress.get(topic_id)
        old_percent = old_entry.get("percent") if isinstance(old_entry, dict) else None
        if isinstance(old_percent, (int, float)) and old_percent >= 90:
            continue
        title = entry.get("title", topic_id)
        messages.append(f"Ты сдал раздел {title} на {int(new_percent)}% 🎉")
    return messages
