"""Scoring/progress rules shared with anatomapp.ru — pure functions, no DB or network.

This is a deliberate port of the website's own `finish()` handler (index.html). Studying in the
bot writes into the *same* state blob the site reads, so XP, streaks, due dates and mistakes stay
consistent whichever surface the student used. Anything here that looks arbitrary (the interval
ladder, the 10-XP grant, the `rewarded` key prefixes) is copied from the site on purpose — do not
"improve" one side without the other, or the two will disagree about the same student's progress.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Iterable, Optional

from state_logic import js_date_string

# Site's spaced-repetition ladder, in days, indexed by (reps - 1).
REVIEW_INTERVALS_DAYS = [1, 2, 4, 9, 18, 35, 60]
XP_PER_NEW_ITEM = 10
PASS_PCT = 75  # below this on a test, the topic comes back tomorrow instead of laddering up
MISTAKES_CAP = 60
HISTORY_CAP = 40

# `rewarded` key prefixes, per study mode — must match the site's, otherwise the same question
# would grant XP twice (once per surface).
REWARD_PREFIX = {"test": "q:", "flash": "f:", "match": "m:", "term": "t:"}

MODE_NAMES = {
    "flash": "Флэш-карты",
    "term": "Ввод термина",
    "match": "Сопоставление",
    "test": "Тест-зачёт",
    "exam": "Экзамен",
    "mistakes": "Работа над ошибками",
    "blitz": "Блиц",
}


def reward_key(mode: str, item_text: str) -> str:
    return f"{REWARD_PREFIX.get(mode, 'q:')}{item_text}"


def progress_key(module_id: str, topic_num: int) -> str:
    return f"{module_id}:{topic_num}"


def next_due_ms(reps: int, *, now_ms: int, passed: bool = True) -> int:
    level = min(max(reps, 1) - 1, len(REVIEW_INTERVALS_DAYS) - 1)
    days = 1 if not passed else REVIEW_INTERVALS_DAYS[level]
    return now_ms + days * 86_400_000


def touch_streak(state: dict[str, Any], *, today: Optional[dt.date] = None) -> tuple[int, str]:
    """Site's touchStreak(): same day keeps the streak, yesterday extends it, older resets to 1."""
    today = today or dt.datetime.now(dt.timezone.utc).date()
    today_key = js_date_string(today)
    last_active = state.get("lastActive") or ""
    streak = int(state.get("streak") or 0)

    if last_active == today_key:
        return streak, today_key
    if last_active == js_date_string(today - dt.timedelta(days=1)):
        return streak + 1, today_key
    return 1, today_key


def apply_session_result(
    state: dict[str, Any],
    *,
    mode: str,
    module_id: Optional[str],
    topic_num: Optional[int],
    topic_name: str,
    reward_keys: Iterable[str],
    correct: int,
    total: int,
    wrong_items: Optional[list[dict[str, Any]]] = None,
    solved_mistakes: Optional[Iterable[str]] = None,
    now_ms: Optional[int] = None,
    today: Optional[dt.date] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fold one finished study session into `state`.

    Returns `(new_state, summary)`; `state` itself is not mutated. `summary` carries what the
    result screen needs: earned XP, percentage, and whether the streak went up.
    """
    now_ms = now_ms if now_ms is not None else int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    new_state = dict(state)
    pct = round(correct / total * 100) if total else 0

    # XP is granted per *first-ever* encounter of an item, so replaying a topic can't farm it.
    rewarded = dict(new_state.get("rewarded") or {})
    newly_seen = 0
    for key in reward_keys:
        if key not in rewarded:
            rewarded[key] = 1
            newly_seen += 1
    earned_xp = newly_seen * XP_PER_NEW_ITEM

    progress = dict(new_state.get("progress") or {})
    if module_id and topic_num and mode not in ("mistakes", "exam", "blitz"):
        key = progress_key(module_id, topic_num)
        entry = dict(progress.get(key) or {"studied": False, "bestPct": 0, "attempts": 0})
        entry["studied"] = True
        entry["last"] = now_ms
        entry["reps"] = int(entry.get("reps") or 0) + 1
        if mode == "test":
            entry["bestPct"] = max(int(entry.get("bestPct") or 0), pct)
            entry["attempts"] = int(entry.get("attempts") or 0) + 1
        entry["due"] = next_due_ms(
            entry["reps"], now_ms=now_ms, passed=not (mode == "test" and pct < PASS_PCT)
        )
        progress[key] = entry

    mistakes = list(new_state.get("mistakes") or [])
    if mode in ("test", "blitz") and wrong_items:
        seen = {m.get("q") for m in mistakes if isinstance(m, dict)}
        for item in wrong_items:
            if item.get("q") in seen:
                continue
            mistakes.append(item)
            seen.add(item.get("q"))
        mistakes = mistakes[-MISTAKES_CAP:]
    if mode == "mistakes" and solved_mistakes is not None:
        solved = set(solved_mistakes)
        mistakes = [m for m in mistakes if isinstance(m, dict) and m.get("q") not in solved]

    streak, today_key = touch_streak(new_state, today=today)
    streak_up = streak > int(new_state.get("streak") or 0)

    day_goal = int(new_state.get("dayGoal") or 20)
    day_key = js_date_string(today or dt.datetime.now(dt.timezone.utc).date())
    day_done = int(new_state.get("dayDone") or 0) if new_state.get("dayKey") == day_key else 0
    day_done = min(day_goal, day_done + total)

    history = [
        {
            "mode": mode,
            "modeName": MODE_NAMES.get(mode, mode),
            "topic": topic_name or "Повторение",
            "pct": pct,
            "correct": correct,
            "total": total,
            "xp": earned_xp,
            "ts": now_ms,
            "via": "bot",  # bot-only marker; the site ignores unknown keys
        }
    ] + list(new_state.get("history") or [])

    new_state.update(
        {
            "rewarded": rewarded,
            "progress": progress,
            "mistakes": mistakes,
            "history": history[:HISTORY_CAP],
            "xp": int(new_state.get("xp") or 0) + earned_xp,
            "streak": streak,
            "lastActive": today_key,
            "dayDone": day_done,
            "dayKey": day_key,
            "dayGoal": day_goal,
        }
    )

    summary = {
        "pct": pct,
        "correct": correct,
        "total": total,
        "earned_xp": earned_xp,
        "streak": streak,
        "streak_up": streak_up,
        "day_done": day_done,
        "day_goal": day_goal,
    }
    return new_state, summary
