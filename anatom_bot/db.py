"""Postgres models and async session helpers, shared by the bot process and the API process.

Both processes point at the same DATABASE_URL and talk to Postgres directly through this module —
there is no internal HTTP hop between the bot and the API server.
"""

from __future__ import annotations

import copy
import datetime as dt
import logging
from typing import Any, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Time, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from config import DATABASE_URL

logger = logging.getLogger(__name__)

# Structure of `UserState.state` — owned by the frontend (anatomapp.ru), mirrored exactly from
# its own `persist()` blob (do not rename/retype these keys without updating the site too):
#   progress: {"<moduleId>:<topicNum>": {bestPct, attempts, reps, studied, last, due}} —
#     `last`/`due` are JS epoch-millisecond timestamps (Date.now()); `due` drives spaced review.
#   mistakes: [{q, ...}]  (list, not a dict)
#   favorites: ["<moduleId>:<topicNum>", ...]
#   notes: {"<moduleId>:<topicNum>": "text"}
#   lastActive: JS `Date.toDateString()` string, e.g. "Wed Aug 05 2026" (not a timestamp)
#   dayDone: number of reps done today (not a bool); dayKey: toDateString() of that count
#   rewarded: {} — client-side reward/badge flags
DEFAULT_STATE: dict[str, Any] = {
    "progress": {},
    "mistakes": [],
    "favorites": [],
    "notes": {},
    "xp": 0,
    "streak": 0,
    "lastActive": "",
    "history": [],
    "dayDone": 0,
    "dayKey": "",
    "dayGoal": 20,
    "lastTopic": None,
    "examDone": False,
    "termLang": "ru",
    "reminders": True,
    "rewarded": {},
}


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram user id
    username: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    photo_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc)
    )
    # Bot-side preferences that aren't part of the website's shared state blob:
    # exam_date, tz, referred_by, announced_badges, digest_opt_out, term_of_day_opt_out.
    # JSONB so a new preference never needs a schema migration.
    prefs: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")

    state: Mapped[Optional["UserState"]] = relationship(back_populates="user", uselist=False)
    reminder: Mapped[Optional["Reminder"]] = relationship(back_populates="user", uselist=False)


class UserState(Base):
    __tablename__ = "user_state"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), primary_key=True)
    state: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc)
    )

    user: Mapped["User"] = relationship(back_populates="state")


class Reminder(Base):
    __tablename__ = "reminders"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    time: Mapped[dt.time] = mapped_column(Time, default=dt.time(19, 0))
    tz: Mapped[str] = mapped_column(String, default="Europe/Moscow")
    last_sent: Mapped[Optional[dt.date]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="reminder")


class LoginSession(Base):
    """Pending/confirmed login codes for the `/start <code>` deep-link auth flow."""

    __tablename__ = "login_sessions"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | confirmed
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc)
    )
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


_engine = None
_session_maker: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    return _engine


def get_session_maker() -> async_sessionmaker[AsyncSession]:
    global _session_maker
    if _session_maker is None:
        _session_maker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_maker


# create_all() only creates missing *tables*, never missing columns, so every column added to an
# existing model needs an explicit statement here. All must be IF NOT EXISTS: both processes run
# this on every boot, and they can start concurrently.
_MIGRATIONS = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS prefs JSONB NOT NULL DEFAULT '{}'::jsonb",
]

# Placeholder rows with no identity at all (no name, no username, no chat) can only be created by
# put_state's defensive get_or_create when a token's users row is missing — never by a real login
# or /start, both of which always carry a first_name. Left alone they surfaced in the leaderboard
# as nameless "Студент" entries. The one-hour cutoff keeps this from racing a row that is being
# populated right now.
_GHOST_CLEANUP = [
    """
    DELETE FROM user_state WHERE user_id IN (
        SELECT id FROM users
        WHERE first_name IS NULL AND username IS NULL AND chat_id IS NULL
          AND created_at < now() - interval '1 hour'
    )
    """,
    """
    DELETE FROM reminders WHERE user_id IN (
        SELECT id FROM users
        WHERE first_name IS NULL AND username IS NULL AND chat_id IS NULL
          AND created_at < now() - interval '1 hour'
    )
    """,
    """
    DELETE FROM users
    WHERE first_name IS NULL AND username IS NULL AND chat_id IS NULL
      AND created_at < now() - interval '1 hour'
    """,
]


async def init_models() -> None:
    """Create tables if missing, apply additive migrations, drop identity-less rows. Call at startup."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for statement in _MIGRATIONS:
            await conn.execute(text(statement))
        removed = 0
        for statement in _GHOST_CLEANUP:
            result = await conn.execute(text(statement))
            removed = max(removed, result.rowcount or 0)
        if removed:
            logger.info("Removed %s placeholder user rows with no identity", removed)


def default_state() -> dict:
    """A fresh, fully-independent copy of DEFAULT_STATE.

    Must be a *deep* copy: DEFAULT_STATE's nested containers (progress/notes/rewarded/...)
    would otherwise be shared by every user created in this process, so one user's writes
    would leak into every other new user's starting state.
    """
    return copy.deepcopy(DEFAULT_STATE)


async def get_or_create_user(session: AsyncSession, *, telegram_id: int, **fields: Any) -> User:
    user = await session.get(User, telegram_id)
    if user is None:
        user = User(id=telegram_id, **fields)
        session.add(user)
        session.add(UserState(user_id=telegram_id, state=default_state()))
        session.add(Reminder(user_id=telegram_id))
    else:
        for key, value in fields.items():
            if value is not None:
                setattr(user, key, value)
    await session.flush()
    return user


async def get_state(session: AsyncSession, user_id: int) -> dict:
    """Return a detached deep copy of the user's state.

    Deliberately a copy, not the live `row.state`: callers routinely read-modify-write, and
    handing back the attached object means (a) in-place edits silently bypass SQLAlchemy's
    change detection on the JSONB column, and (b) `put_state(row.state)` would assign the
    object to itself, which SQLAlchemy sees as "unchanged" and never flushes.
    """
    row = await session.get(UserState, user_id)
    if row is None:
        return default_state()
    return copy.deepcopy(row.state or {})


async def put_state(session: AsyncSession, user_id: int, state: dict) -> None:
    row = await session.get(UserState, user_id)
    if row is None:
        row = UserState(user_id=user_id, state=state)
        session.add(row)
    else:
        row.state = state
        row.updated_at = dt.datetime.now(dt.timezone.utc)
    await session.flush()


async def find_login_session(session: AsyncSession, code: str) -> Optional[LoginSession]:
    result = await session.execute(select(LoginSession).where(LoginSession.code == code))
    return result.scalar_one_or_none()


async def count_users(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(User))
    return result.scalar_one()


async def count_reminders_enabled(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count()).select_from(Reminder).where(Reminder.enabled.is_(True))
    )
    return result.scalar_one()


async def list_chat_ids(session: AsyncSession) -> list[int]:
    result = await session.execute(select(User.chat_id).where(User.chat_id.is_not(None)))
    return [row[0] for row in result.all()]


async def get_user_full(session: AsyncSession, user_id: int) -> Optional[dict[str, Any]]:
    user = await session.get(User, user_id)
    if user is None:
        return None
    return {
        "user": user,
        "state": await get_state(session, user_id),
        "reminder": await session.get(Reminder, user_id),
    }


# ---------------------------------------------------------------- preferences


async def get_prefs(session: AsyncSession, user_id: int) -> dict[str, Any]:
    user = await session.get(User, user_id)
    return copy.deepcopy(user.prefs or {}) if user else {}


async def set_prefs(session: AsyncSession, user_id: int, prefs: dict[str, Any]) -> None:
    """Replace a user's prefs. Reassigns the whole dict so SQLAlchemy sees the JSONB change."""
    user = await get_or_create_user(session, telegram_id=user_id)
    user.prefs = dict(prefs)
    await session.flush()


async def update_prefs(session: AsyncSession, user_id: int, **changes: Any) -> dict[str, Any]:
    prefs = await get_prefs(session, user_id)
    prefs.update(changes)
    await set_prefs(session, user_id, prefs)
    return prefs


# ---------------------------------------------------------------- leaderboard

# XP lives inside the shared JSONB state, so ranking is done in SQL rather than by loading every
# user's blob into Python — at a few thousand students that difference matters.
_XP_EXPR = func.coalesce(func.nullif(UserState.state["xp"].astext, ""), "0").cast(BigInteger)

# A real participant always has a name: Telegram requires first_name, and both the Login Widget
# payload and /start carry it. A row with no name and no chat is a placeholder created by
# put_state's defensive get_or_create for a token whose users row was missing — it has no human
# behind it, so it must never occupy a place in the ranking (it used to show up as "Студент").
_IS_REAL_USER = User.first_name.is_not(None) | User.username.is_not(None) | User.chat_id.is_not(None)


async def top_users_by_xp(session: AsyncSession, limit: int = 10) -> list[dict[str, Any]]:
    result = await session.execute(
        select(User.id, User.first_name, User.last_name, User.username, _XP_EXPR.label("xp"))
        .join(UserState, UserState.user_id == User.id)
        .where(_XP_EXPR > 0, _IS_REAL_USER)
        .order_by(_XP_EXPR.desc())
        .limit(limit)
    )
    return [
        {"id": row.id, "first_name": row.first_name, "last_name": row.last_name,
         "username": row.username, "xp": int(row.xp or 0)}
        for row in result.all()
    ]


async def user_rank_by_xp(session: AsyncSession, user_id: int) -> tuple[Optional[int], int, int]:
    """Return (rank, xp, total_ranked). Rank is 1-based among users with any XP."""
    state = await get_state(session, user_id)
    xp = int(state.get("xp") or 0)

    total_result = await session.execute(
        select(func.count())
        .select_from(UserState)
        .join(User, User.id == UserState.user_id)
        .where(_XP_EXPR > 0, _IS_REAL_USER)
    )
    total = int(total_result.scalar_one() or 0)

    if xp <= 0:
        return None, 0, total

    ahead_result = await session.execute(
        select(func.count())
        .select_from(UserState)
        .join(User, User.id == UserState.user_id)
        .where(_XP_EXPR > xp, _IS_REAL_USER)
    )
    return int(ahead_result.scalar_one() or 0) + 1, xp, total


async def count_referrals(session: AsyncSession, user_id: int) -> int:
    result = await session.execute(
        select(func.count()).select_from(User).where(User.prefs["referred_by"].astext == str(user_id))
    )
    return int(result.scalar_one() or 0)


async def list_users_with_state(session: AsyncSession) -> list[tuple[User, dict[str, Any]]]:
    """Every user paired with their state — used by the nightly/weekly sweeps."""
    result = await session.execute(
        select(User, UserState.state).outerjoin(UserState, UserState.user_id == User.id)
    )
    return [(row[0], copy.deepcopy(row[1] or {})) for row in result.all()]
