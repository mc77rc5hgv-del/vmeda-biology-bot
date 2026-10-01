"""Persistent learning state for the Mini App.

This database is deliberately separate from ``stats.json`` and the subscription tables.  The
Mini App can therefore write progress without risking the bot's users, payments or access data.
SQLite supplies transactions and locking for the single Railway web service, while the file is
kept in ``STATS_DIR`` so an attached persistent volume survives deployments.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone


def _db_path() -> str:
    explicit = os.environ.get("MINIAPP_LEARNING_DB")
    if explicit:
        return explicit
    stats_dir = os.environ.get("STATS_DIR") or os.getcwd()
    os.makedirs(stats_dir, exist_ok=True)
    return os.path.join(stats_dir, "miniapp_learning.sqlite3")


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(_db_path(), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS learning_materials (
            user_id INTEGER NOT NULL,
            subject_id TEXT NOT NULL,
            section_id TEXT NOT NULL,
            material_id TEXT NOT NULL,
            subject_title TEXT NOT NULL DEFAULT '',
            section_title TEXT NOT NULL DEFAULT '',
            material_title TEXT NOT NULL DEFAULT '',
            material_order INTEGER NOT NULL DEFAULT 1,
            total_in_section INTEGER NOT NULL DEFAULT 1,
            completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
            favorite INTEGER NOT NULL DEFAULT 0 CHECK (favorite IN (0, 1)),
            last_opened_at TEXT NOT NULL,
            completed_at TEXT,
            PRIMARY KEY (user_id, subject_id, section_id, material_id)
        );
        CREATE INDEX IF NOT EXISTS learning_materials_user_recent
            ON learning_materials(user_id, last_opened_at DESC);
        CREATE INDEX IF NOT EXISTS learning_materials_user_favorite
            ON learning_materials(user_id, favorite, last_opened_at DESC);

        CREATE TABLE IF NOT EXISTS learning_quiz_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            subject_id TEXT NOT NULL,
            section_id TEXT NOT NULL,
            material_id TEXT NOT NULL,
            correct INTEGER NOT NULL CHECK (correct IN (0, 1)),
            answered_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS learning_quiz_user
            ON learning_quiz_attempts(user_id, answered_at DESC);

        CREATE TABLE IF NOT EXISTS histology_practical_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            specimen_id TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT 'all',
            known INTEGER NOT NULL CHECK (known IN (0, 1)),
            answered_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS histology_practical_user
            ON histology_practical_attempts(user_id, answered_at DESC);
        CREATE INDEX IF NOT EXISTS histology_practical_user_specimen
            ON histology_practical_attempts(user_id, specimen_id, answered_at DESC);
        """
    )
    return connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def touch_material(user_id: int, payload: dict) -> None:
    now = _now()
    with closing(_connect()) as connection, connection:
        connection.execute(
            """
            INSERT INTO learning_materials (
                user_id, subject_id, section_id, material_id, subject_title, section_title,
                material_title, material_order, total_in_section, last_opened_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, subject_id, section_id, material_id) DO UPDATE SET
                subject_title=excluded.subject_title,
                section_title=excluded.section_title,
                material_title=excluded.material_title,
                material_order=excluded.material_order,
                total_in_section=excluded.total_in_section,
                last_opened_at=excluded.last_opened_at
            """,
            (
                user_id, payload["subject_id"], payload["section_id"], payload["material_id"],
                payload.get("subject_title", ""), payload.get("section_title", ""),
                payload.get("material_title", ""), payload.get("material_order", 1),
                payload.get("total_in_section", 1), now,
            ),
        )


def set_material_flag(user_id: int, subject_id: str, section_id: str, material_id: str, flag: str, value: bool) -> None:
    if flag not in {"completed", "favorite"}:
        raise ValueError("unsupported learning flag")
    now = _now()
    completed_sql = ", completed_at=?" if flag == "completed" else ""
    completed_value = now if value else None
    with closing(_connect()) as connection, connection:
        connection.execute(
            """INSERT INTO learning_materials
               (user_id, subject_id, section_id, material_id, last_opened_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id, subject_id, section_id, material_id) DO NOTHING""",
            (user_id, subject_id, section_id, material_id, now),
        )
        args = [1 if value else 0]
        if flag == "completed":
            args.append(completed_value)
        args.extend([user_id, subject_id, section_id, material_id])
        connection.execute(
            f"UPDATE learning_materials SET {flag}=?{completed_sql} "
            "WHERE user_id=? AND subject_id=? AND section_id=? AND material_id=?",
            args,
        )


def record_quiz_attempt(user_id: int, subject_id: str, section_id: str, material_id: str, correct: bool) -> None:
    with closing(_connect()) as connection, connection:
        connection.execute(
            """INSERT INTO learning_quiz_attempts
               (user_id, subject_id, section_id, material_id, correct, answered_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, subject_id, section_id, material_id, int(correct), _now()),
        )


def record_histology_attempt(user_id: int, specimen_id: str, known: bool, scope: str = "all") -> None:
    with closing(_connect()) as connection, connection:
        connection.execute(
            """INSERT INTO histology_practical_attempts
               (user_id, specimen_id, scope, known, answered_at)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, specimen_id, scope, int(known), _now()),
        )


def get_histology_mistake_ids(user_id: int) -> list[str]:
    """Препараты, последний ответ по которым был ошибочным.

    Успешное повторение автоматически убирает препарат из активной работы над ошибками, но
    вся история попыток остаётся в БД и продолжает участвовать в общей статистике.
    """
    with closing(_connect()) as connection:
        rows = connection.execute(
            """SELECT h.specimen_id, h.known
               FROM histology_practical_attempts h
               JOIN (
                   SELECT specimen_id, MAX(id) AS last_id
                   FROM histology_practical_attempts
                   WHERE user_id=?
                   GROUP BY specimen_id
               ) latest ON latest.last_id=h.id
               WHERE h.user_id=? AND h.known=0
               ORDER BY h.answered_at DESC""",
            (user_id, user_id),
        ).fetchall()
    return [row["specimen_id"] for row in rows]


def get_histology_stats(user_id: int, total_specimens: int = 71) -> dict:
    with closing(_connect()) as connection:
        totals = connection.execute(
            """SELECT COUNT(*) AS attempts, COALESCE(SUM(known), 0) AS known
               FROM histology_practical_attempts WHERE user_id=?""",
            (user_id,),
        ).fetchone()
        mastered = connection.execute(
            """SELECT COUNT(DISTINCT specimen_id) AS count
               FROM histology_practical_attempts WHERE user_id=? AND known=1""",
            (user_id,),
        ).fetchone()["count"]
    attempts = int(totals["attempts"])
    known = int(totals["known"])
    mistakes = get_histology_mistake_ids(user_id)
    return {
        "total_specimens": total_specimens,
        "attempts": attempts,
        "known": known,
        "wrong": attempts - known,
        "accuracy_percent": round(known / attempts * 100) if attempts else 0,
        "mastered_specimens": int(mastered),
        "active_mistakes": len(mistakes),
        "mistake_ids": mistakes,
    }


def get_state(user_id: int) -> dict:
    with closing(_connect()) as connection:
        materials = connection.execute(
            """SELECT * FROM learning_materials WHERE user_id=?
               ORDER BY last_opened_at DESC""",
            (user_id,),
        ).fetchall()
        quiz = connection.execute(
            """SELECT COUNT(*) AS attempts, COALESCE(SUM(correct), 0) AS correct
               FROM learning_quiz_attempts WHERE user_id=?""",
            (user_id,),
        ).fetchone()

    serialized = [dict(row) for row in materials]
    completed = [row for row in serialized if row["completed"]]
    favorites = [row for row in serialized if row["favorite"]]
    by_subject: dict[str, int] = {}
    for row in completed:
        by_subject[row["subject_id"]] = by_subject.get(row["subject_id"], 0) + 1
    return {
        "completed_keys": [f'{r["subject_id"]}/{r["section_id"]}/{r["material_id"]}' for r in completed],
        "favorites": favorites,
        "last_material": serialized[0] if serialized else None,
        "completed_by_subject": by_subject,
        "completed_total": len(completed),
        "quiz_attempts": quiz["attempts"],
        "quiz_correct": quiz["correct"],
    }



def _activity_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None


def get_dashboard(user_id: int) -> dict:
    """Real profile metrics derived only from persisted Mini App activity."""
    with closing(_connect()) as connection:
        materials = connection.execute(
            """SELECT completed, last_opened_at FROM learning_materials WHERE user_id=?""",
            (user_id,),
        ).fetchall()
        attempts = connection.execute(
            """SELECT correct, answered_at FROM learning_quiz_attempts WHERE user_id=?""",
            (user_id,),
        ).fetchall()

    completed = sum(int(row["completed"]) for row in materials)
    correct = sum(int(row["correct"]) for row in attempts)
    wrong = len(attempts) - correct
    xp = completed * 40 + correct * 20 + wrong * 5

    completion_percent = round(completed / len(materials) * 100) if materials else None
    accuracy_percent = round(correct / len(attempts) * 100) if attempts else None
    if completion_percent is not None and accuracy_percent is not None:
        readiness = round(completion_percent * 0.4 + accuracy_percent * 0.6)
    elif completion_percent is not None:
        readiness = completion_percent
    elif accuracy_percent is not None:
        readiness = accuracy_percent
    else:
        readiness = 0

    material_dates = [_activity_date(row["last_opened_at"]) for row in materials]
    attempt_dates = [_activity_date(row["answered_at"]) for row in attempts]
    activity_dates = {day for day in material_dates + attempt_dates if day is not None}
    today = datetime.now(timezone.utc).date()
    cursor = today if today in activity_dates else today - timedelta(days=1)
    streak = 0
    while cursor in activity_dates:
        streak += 1
        cursor -= timedelta(days=1)

    today_actions = sum(day == today for day in material_dates + attempt_dates if day is not None)
    daily_goal = 30
    return {
        "streak_days": streak,
        "xp": xp,
        "readiness_percent": max(0, min(100, readiness)),
        "daily_goal_minutes": daily_goal,
        "minutes_left_today": max(0, daily_goal - today_actions * 5),
    }
