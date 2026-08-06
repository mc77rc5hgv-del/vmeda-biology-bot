"""Display formatting for the bot's screens. Pure functions over state/prefs — easy to unit test.

All user-visible text lives here rather than inline in handlers so wording can be reviewed in one
place, and so the scheduler (which sends the same digests) doesn't duplicate any of it.
"""

from __future__ import annotations

import datetime as dt
import random
from typing import Any, Optional

import content
from achievements import earned_badges, level_for_xp
from modules import MODULES, PASS_THRESHOLD
from state_logic import module_progress, topics_due_for_review

MAX_LEADERBOARD_ROWS = 10
MEDALS = ["🥇", "🥈", "🥉"]


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def progress_bar(pct: int, width: int = 10) -> str:
    filled = max(0, min(width, round(pct / 100 * width)))
    return "█" * filled + "░" * (width - filled)


def display_name(first_name: Optional[str], last_name: Optional[str], username: Optional[str]) -> str:
    name = " ".join(part for part in (first_name, last_name) if part).strip()
    if name:
        return name
    if username:
        return f"@{username}"
    return "Студент"


# ------------------------------------------------------------------ profile


def profile_text(state: dict[str, Any], prefs: dict[str, Any], *, name: str, referrals: int) -> str:
    xp = int(state.get("xp") or 0)
    level_no, level_title, into, needed = level_for_xp(xp)
    streak = int(state.get("streak") or 0)
    badges = earned_badges(state)

    rows = module_progress(state)
    passed = sum(row["passed"] for row in rows)
    total = sum(row["total"] for row in rows)
    overall = round(passed / total * 100) if total else 0

    lines = [
        f"👤 <b>{name}</b>",
        "",
        f"🎖 Уровень {level_no} — <b>{level_title}</b>",
    ]
    if needed:
        lines.append(f"⭐ XP: {xp}  ({into}/{needed} до следующего уровня)")
        lines.append(progress_bar(round(into / needed * 100)))
    else:
        lines.append(f"⭐ XP: {xp} (максимальный уровень)")

    lines += [
        "",
        f"📚 Курс пройден: {passed}/{total} ({overall}%)",
        progress_bar(overall),
        f"🔥 Серия: {streak} {plural(streak, 'день', 'дня', 'дней')}",
        f"🏅 Достижений: {len(badges)}",
    ]

    exam_line = exam_countdown_line(prefs, state)
    if exam_line:
        lines += ["", exam_line]
    if referrals:
        lines.append(f"🤝 Приглашено друзей: {referrals}")
    return "\n".join(lines)


# ------------------------------------------------------------------ stats


def stats_text(state: dict[str, Any]) -> str:
    progress = state.get("progress") or {}
    entries = [entry for entry in progress.values() if isinstance(entry, dict)]
    attempted = [entry for entry in entries if (entry.get("attempts") or 0) > 0]
    passed = [entry for entry in entries if (entry.get("bestPct") or 0) >= PASS_THRESHOLD]
    perfect = [entry for entry in entries if (entry.get("bestPct") or 0) >= 100]

    avg = round(sum(entry.get("bestPct") or 0 for entry in attempted) / len(attempted)) if attempted else 0
    total_reps = sum(int(entry.get("reps") or 0) for entry in entries)
    history = [h for h in (state.get("history") or []) if isinstance(h, dict)]
    mistakes = state.get("mistakes") or []
    due = topics_due_for_review(state)

    lines = [
        "📈 <b>Подробная статистика</b>",
        "",
        f"Изучено тем: {len(entries)}",
        f"Сдано (≥{PASS_THRESHOLD}%): {len(passed)}",
        f"На 100%: {len(perfect)}",
        f"Средний результат: {avg}%",
        f"Всего подходов: {total_reps}",
        f"Ошибок в работе: {len(mistakes)}",
        f"К повторению сейчас: {len(due)}",
    ]

    if history:
        lines += ["", "<b>Последние сессии:</b>"]
        for item in history[:5]:
            when = ""
            ts = item.get("ts")
            if isinstance(ts, (int, float)) and ts > 0:
                when = dt.datetime.fromtimestamp(ts / 1000, tz=dt.timezone.utc).strftime("%d.%m")
            mode_name = item.get("modeName", item.get("mode", ""))
            topic = (item.get("topic") or "")[:38]
            lines.append(f"• {when} {mode_name} — {item.get('pct', 0)}% ({topic})")

    weakest = weakest_modules(state)
    if weakest:
        lines += ["", "<b>Слабые места:</b>"]
        lines.extend(f"• {row['icon']} {row['title']} — {row['pct']}%" for row in weakest)
    return "\n".join(lines)


def weakest_modules(state: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    rows = [row for row in module_progress(state) if row["total"]]
    rows.sort(key=lambda row: row["pct"])
    return [row for row in rows if row["pct"] < 100][:limit]


# ------------------------------------------------------------------ leaderboard


def leaderboard_text(
    top: list[dict[str, Any]], rank: Optional[int], xp: int, total: int, viewer_id: int
) -> str:
    lines = ["🏆 <b>Рейтинг по XP</b>", ""]
    if not top:
        lines.append("Пока никто не набрал очков. Стань первым!")
        return "\n".join(lines)

    for index, row in enumerate(top[:MAX_LEADERBOARD_ROWS]):
        medal = MEDALS[index] if index < len(MEDALS) else f"{index + 1}."
        name = display_name(row.get("first_name"), row.get("last_name"), row.get("username"))
        _, level_title, _, _ = level_for_xp(row["xp"])
        marker = " ← ты" if row["id"] == viewer_id else ""
        lines.append(f"{medal} {name} — {row['xp']} XP · {level_title}{marker}")

    lines.append("")
    if rank:
        lines.append(f"Твоё место: <b>{rank}</b> из {total} · {xp} XP")
    else:
        lines.append("Ты ещё не в рейтинге — набери первые XP, чтобы попасть в таблицу.")
    return "\n".join(lines)


# ------------------------------------------------------------------ term of the day


def term_of_the_day(today: Optional[dt.date] = None) -> Optional[dict[str, Any]]:
    """Same term for everyone on a given day, stable across restarts (seeded by the date)."""
    pairs = content.all_pairs()
    if not pairs:
        return None
    today = today or dt.datetime.now(dt.timezone.utc).date()
    rng = random.Random(today.toordinal())
    return pairs[rng.randrange(len(pairs))]


def term_of_the_day_text(today: Optional[dt.date] = None) -> str:
    pair = term_of_the_day(today)
    if not pair:
        return "Термин дня пока недоступен."
    lines = [
        "📖 <b>Термин дня</b>",
        "",
        f"<i>{pair['term']}</i>",
        f"— {pair['def']}",
    ]
    if pair.get("topic"):
        lines += ["", f"Тема: {pair['topic']}"]
    return "\n".join(lines)


# ------------------------------------------------------------------ exam countdown


def parse_exam_date(prefs: dict[str, Any]) -> Optional[dt.date]:
    raw = prefs.get("exam_date")
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(str(raw))
    except ValueError:
        return None


def exam_countdown_line(prefs: dict[str, Any], state: dict[str, Any]) -> str:
    exam_date = parse_exam_date(prefs)
    if not exam_date:
        return ""
    days = (exam_date - dt.datetime.now(dt.timezone.utc).date()).days
    if days < 0:
        return "🎓 Экзамен позади — удачи с результатом!"
    if days == 0:
        return "🎓 Экзамен <b>сегодня</b>. Ни пуха!"
    return f"🎓 До экзамена: <b>{days}</b> {plural(days, 'день', 'дня', 'дней')}"


def exam_plan_text(prefs: dict[str, Any], state: dict[str, Any]) -> str:
    exam_date = parse_exam_date(prefs)
    if not exam_date:
        return (
            "🎓 <b>Экзамен</b>\n\n"
            "Дата экзамена не задана.\n"
            "Отправь дату в формате ДД.ММ.ГГГГ (например 15.06.2027), "
            "и я посчитаю, сколько тем нужно закрывать в день."
        )

    today = dt.datetime.now(dt.timezone.utc).date()
    days = (exam_date - today).days
    rows = module_progress(state)
    passed = sum(row["passed"] for row in rows)
    total = sum(row["total"] for row in rows)
    remaining = max(0, total - passed)

    lines = ["🎓 <b>Подготовка к экзамену</b>", "", f"Дата: {exam_date.strftime('%d.%m.%Y')}"]

    if days < 0:
        lines.append("Экзамен уже прошёл. Задай новую дату, отправив её сообщением.")
        return "\n".join(lines)

    lines.append(f"Осталось: <b>{days}</b> {plural(days, 'день', 'дня', 'дней')}")
    lines += ["", f"Пройдено: {passed}/{total}", f"Осталось тем: {remaining}"]

    if remaining == 0:
        lines += ["", "🎉 Весь курс сдан! Осталось повторять — загляни в «Повторить»."]
    elif days == 0:
        lines += ["", f"Сегодня последний день, а тем осталось {remaining}. Сфокусируйся на слабых местах."]
    else:
        per_day = -(-remaining // days)  # ceil
        lines += ["", f"📌 План: <b>{per_day}</b> {plural(per_day, 'тема', 'темы', 'тем')} в день"]
        weak = weakest_modules(state, limit=2)
        if weak:
            names = ", ".join(f"{row['icon']} {row['title']}" for row in weak)
            lines.append(f"Начни со слабого: {names}")
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
        f"Сессий: {sessions}",
        f"Вопросов пройдено: {answered}",
        f"Средний результат: {avg}%",
        f"Заработано XP: {xp}",
        f"🔥 Серия: {state.get('streak', 0)}",
    ]
    if due:
        lines += ["", f"🔁 На следующей неделе к повторению: {len(due)}"]
    return "\n".join(lines)


# ------------------------------------------------------------------ misc


def course_overview_text() -> str:
    stats = content.counts()
    lines = [
        "📚 <b>Курс нормальной анатомии</b>",
        "",
        f"Модулей: {len(MODULES)}",
        f"Тем: {stats['topics']}",
        f"Флеш-карточек: {stats['cards']}",
        f"Латинских терминов: {stats['pairs']}",
        f"Тестовых вопросов: {stats['tests']}",
        "",
        "Учись прямо здесь или открывай сайт для теории и атласа.",
    ]
    return "\n".join(lines)


def session_result_text(summary: dict[str, Any], mode_title: str) -> str:
    pct = summary["pct"]
    if pct >= 90:
        verdict = "🏆 Отлично!"
    elif pct >= 75:
        verdict = "✅ Зачёт!"
    elif pct >= 50:
        verdict = "📖 Есть над чем поработать."
    else:
        verdict = "🔁 Стоит повторить тему."

    lines = [
        f"{mode_title} — результат",
        "",
        f"{verdict}",
        f"Правильно: {summary['correct']}/{summary['total']} ({pct}%)",
        progress_bar(pct),
    ]
    if summary["earned_xp"]:
        lines.append(f"⭐ +{summary['earned_xp']} XP")
    else:
        lines.append("⭐ XP не начислен — эти вопросы уже были засчитаны раньше")
    if summary.get("streak_up"):
        lines.append(f"🔥 Серия продлена: {summary['streak']}!")
    lines.append(f"🎯 Цель дня: {summary['day_done']}/{summary['day_goal']}")
    return "\n".join(lines)
