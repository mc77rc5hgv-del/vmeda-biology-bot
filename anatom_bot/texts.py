"""Message text for the bot's remaining surfaces: launching the app, reminders and digests.

Study screens live in the MiniApp now; what's left here is what the app cannot do for itself —
reach a student who isn't currently looking at it.
"""

from __future__ import annotations

import datetime as dt
import json
import random
from pathlib import Path
from typing import Any, Optional

from state_logic import topics_due_for_review

TERMS_PATH = Path(__file__).with_name("terms.json")

# Latin term -> meaning pairs, used only by the daily term push.
TERMS: list[dict[str, Any]] = []
if TERMS_PATH.exists():
    with TERMS_PATH.open(encoding="utf-8") as fh:
        TERMS = json.load(fh)


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def display_name(first_name: Optional[str], last_name: Optional[str], username: Optional[str]) -> str:
    name = " ".join(part for part in (first_name, last_name) if part).strip()
    if name:
        return name
    if username:
        return f"@{username}"
    return "Студент"


# ------------------------------------------------------------------ welcome / help


def welcome_text(name: str) -> str:
    return (
        f"👋 Привет, {name}!\n\n"
        "Это <b>АНАТОМ</b> — приложение для подготовки по нормальной анатомии: "
        "теория, атлас, тесты, флеш-карточки и латинские термины по всему курсу.\n\n"
        "Нажми кнопку ниже — приложение откроется прямо здесь, в Telegram. "
        "Прогресс, XP и серия сохраняются автоматически."
    )


def help_text(support_url: str) -> str:
    return (
        "<b>АНАТОМ</b>\n\n"
        "Всё обучение — в приложении: открывается по кнопке ниже, "
        "по кнопке <b>АНАТОМ</b> рядом с полем ввода или командой /app.\n\n"
        "<b>Команды</b>\n"
        "/app — открыть приложение\n"
        "/reminder — напоминания о занятиях\n"
        "/help — эта справка\n\n"
        f"Поддержка: {support_url}"
    )


def open_app_text() -> str:
    return (
        "🚀 <b>АНАТОМ</b>\n\n"
        "Нажми кнопку — приложение откроется внутри Telegram, ничего устанавливать не нужно."
    )


# ------------------------------------------------------------------ reminders


def reminder_status_text(enabled: bool, when: str, tz: str) -> str:
    if not enabled:
        return (
            "🔕 <b>Напоминания выключены</b>\n\n"
            "Включи их — буду напоминать о занятиях и спасать серию, если ты о ней забудешь.\n\n"
            "<i>Можно сразу прислать время в формате ЧЧ:ММ, например 19:00.</i>"
        )
    return (
        f"🔔 <b>Напоминания включены</b>\n\n"
        f"Время: <b>{when}</b>\nЧасовой пояс: {tz}\n\n"
        "<i>Чтобы изменить время, пришли новое в формате ЧЧ:ММ.</i>"
    )


def format_daily_reminder_text(due_count: int) -> str:
    if due_count <= 0:
        return "Пора закрепить анатомию 🦴 Пара минут в приложении — и день не пропал."
    return (
        f"Пора закрепить анатомию 🦴\n"
        f"{due_count} {plural(due_count, 'тема ждёт', 'темы ждут', 'тем ждут')} повторения."
    )


def format_streak_warning_text(streak: int) -> str:
    return (
        f"🔥 Серия {streak} {plural(streak, 'день', 'дня', 'дней')} под угрозой!\n"
        "5 минут в приложении — и она сохранится."
    )


def format_inactivity_text(last_topic: Optional[dict[str, Any]]) -> str:
    if isinstance(last_topic, dict) and last_topic.get("moduleId"):
        return "Скучаем! Ты остановился на середине — продолжи с того же места."
    return "Скучаем! Возвращайся к анатомии — начать можно с любой темы."


# ------------------------------------------------------------------ daily term


def term_of_the_day(today: Optional[dt.date] = None) -> Optional[dict[str, Any]]:
    """Same term for everyone on a given day, stable across restarts (seeded by the date)."""
    if not TERMS:
        return None
    today = today or dt.datetime.now(dt.timezone.utc).date()
    rng = random.Random(today.toordinal())
    return TERMS[rng.randrange(len(TERMS))]


def term_of_the_day_text(today: Optional[dt.date] = None) -> str:
    pair = term_of_the_day(today)
    if not pair:
        return "Термин дня пока недоступен."
    lines = ["📖 <b>Термин дня</b>", "", f"<i>{pair['term']}</i>", f"— {pair['def']}"]
    if pair.get("topic"):
        lines += ["", f"Тема: {pair['topic']}"]
    return "\n".join(lines)


# ------------------------------------------------------------------ digest


def weekly_digest_text(state: dict[str, Any], *, name: str) -> Optional[str]:
    """Summary of the last 7 days. Returns None when there was no activity worth reporting."""
    now_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    week_ago = now_ms - 7 * 86_400_000
    history = [
        item
        for item in (state.get("history") or [])
        if isinstance(item, dict) and isinstance(item.get("ts"), (int, float)) and item["ts"] >= week_ago
    ]
    if not history:
        return None

    sessions = len(history)
    xp = sum(int(item.get("xp") or 0) for item in history)
    answered = sum(int(item.get("total") or 0) for item in history)
    avg = round(sum(int(item.get("pct") or 0) for item in history) / sessions) if sessions else 0
    due = topics_due_for_review(state)

    lines = [
        f"📬 <b>Итоги недели, {name}</b>",
        "",
        f"Занятий: {sessions}",
        f"Вопросов пройдено: {answered}",
        f"Средний результат: {avg}%",
        f"Заработано XP: {xp}",
        f"🔥 Серия: {state.get('streak', 0)}",
    ]
    if due:
        lines += ["", f"🔁 К повторению на следующей неделе: {len(due)}"]
    return "\n".join(lines)
