"""Badges and levels derived from the shared state — pure functions, no storage of their own.

Everything here is computed from the same state blob the website writes, so a badge earned by
studying on the site shows up in the bot immediately (and vice versa). Nothing is persisted
except the "already congratulated" set, which the caller keeps in user prefs so the bot doesn't
re-announce the same badge on every sync.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from modules import MODULES, PASS_THRESHOLD
from state_logic import module_progress


class Badge(NamedTuple):
    code: str
    icon: str
    title: str
    description: str


BADGES: list[Badge] = [
    Badge("first_steps", "🐣", "Первые шаги", "Сдать первую тему"),
    Badge("ten_topics", "📗", "Десятка", "Сдать 10 тем"),
    Badge("quarter", "📘", "Четверть пути", "Сдать 25% курса"),
    Badge("half", "📙", "Экватор", "Сдать половину курса"),
    Badge("all_topics", "🎓", "Анатом", "Сдать весь курс"),
    Badge("module_master", "🏛", "Магистр модуля", "Сдать модуль полностью"),
    Badge("streak_3", "🔥", "Разогрев", "Серия 3 дня"),
    Badge("streak_7", "🔥", "Неделя силы", "Серия 7 дней"),
    Badge("streak_30", "🌋", "Железная дисциплина", "Серия 30 дней"),
    Badge("xp_500", "⭐", "Пятьсот", "Набрать 500 XP"),
    Badge("xp_2000", "🌟", "Две тысячи", "Набрать 2000 XP"),
    Badge("xp_10000", "💎", "Легенда", "Набрать 10 000 XP"),
    Badge("perfectionist", "💯", "Перфекционист", "Сдать тему на 100%"),
    Badge("no_mistakes", "🧹", "Чистая работа", "Разобрать все свои ошибки"),
    Badge("night_owl", "🦉", "Сова", "Заниматься 5 дней подряд"),
]

BADGES_BY_CODE = {badge.code: badge for badge in BADGES}

LEVELS = [
    (0, "Абитуриент"),
    (200, "Первокурсник"),
    (600, "Студент"),
    (1500, "Ординатор"),
    (3000, "Ассистент кафедры"),
    (6000, "Доцент"),
    (12000, "Профессор"),
    (25000, "Академик"),
]


def level_for_xp(xp: int) -> tuple[int, str, int, int]:
    """Return (level_number, title, xp_into_level, xp_needed_for_next).

    The top level reports 0 remaining, which callers render as "макс." rather than a progress bar.
    """
    level_index = 0
    for index, (threshold, _) in enumerate(LEVELS):
        if xp >= threshold:
            level_index = index
    threshold, title = LEVELS[level_index]
    if level_index + 1 < len(LEVELS):
        next_threshold = LEVELS[level_index + 1][0]
        return level_index + 1, title, xp - threshold, next_threshold - threshold
    return level_index + 1, title, 0, 0


def earned_badges(state: dict[str, Any]) -> list[Badge]:
    xp = int(state.get("xp") or 0)
    streak = int(state.get("streak") or 0)
    progress = state.get("progress") or {}

    passed_entries = [
        entry
        for entry in progress.values()
        if isinstance(entry, dict) and (entry.get("bestPct") or 0) >= PASS_THRESHOLD
    ]
    passed = len(passed_entries)
    total_topics = sum(module.topic_count for module in MODULES)
    attempted = any(isinstance(e, dict) and (e.get("attempts") or 0) > 0 for e in progress.values())

    codes: list[str] = []
    if passed >= 1:
        codes.append("first_steps")
    if passed >= 10:
        codes.append("ten_topics")
    if total_topics and passed >= total_topics * 0.25:
        codes.append("quarter")
    if total_topics and passed >= total_topics * 0.5:
        codes.append("half")
    if total_topics and passed >= total_topics:
        codes.append("all_topics")

    if any(row["total"] and row["passed"] >= row["total"] for row in module_progress(state)):
        codes.append("module_master")

    if streak >= 3:
        codes.append("streak_3")
    if streak >= 5:
        codes.append("night_owl")
    if streak >= 7:
        codes.append("streak_7")
    if streak >= 30:
        codes.append("streak_30")

    if xp >= 500:
        codes.append("xp_500")
    if xp >= 2000:
        codes.append("xp_2000")
    if xp >= 10000:
        codes.append("xp_10000")

    if any((entry.get("bestPct") or 0) >= 100 for entry in passed_entries):
        codes.append("perfectionist")

    # Only meaningful once the student has actually taken a test — an untouched account has an
    # empty mistake list too, and that isn't an achievement.
    if attempted and not (state.get("mistakes") or []):
        codes.append("no_mistakes")

    return [BADGES_BY_CODE[code] for code in codes if code in BADGES_BY_CODE]


def newly_earned(state: dict[str, Any], already_announced: list[str]) -> list[Badge]:
    seen = set(already_announced or [])
    return [badge for badge in earned_badges(state) if badge.code not in seen]


def format_badges_text(state: dict[str, Any]) -> str:
    earned = earned_badges(state)
    earned_codes = {badge.code for badge in earned}

    lines = [f"🏅 Достижения: {len(earned)} из {len(BADGES)}", ""]
    if earned:
        lines.append("Получено:")
        lines.extend(f"{badge.icon} <b>{badge.title}</b> — {badge.description}" for badge in earned)
        lines.append("")

    locked = [badge for badge in BADGES if badge.code not in earned_codes]
    if locked:
        lines.append("Ещё не открыто:")
        lines.extend(f"🔒 {badge.title} — {badge.description}" for badge in locked)
    return "\n".join(lines)
