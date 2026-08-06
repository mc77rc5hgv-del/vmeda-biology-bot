"""Postgres models and async session helpers, shared by the bot process and the API process.

Both processes point at the same DATABASE_URL and talk to Postgres directly through this module —
there is no internal HTTP hop between the bot and the API server.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Time, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from config import DATABASE_URL

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


async def init_models() -> None:
    """Create tables if they don't exist. Call once at process startup."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_or_create_user(session: AsyncSession, *, telegram_id: int, **fields: Any) -> User:
    user = await session.get(User, telegram_id)
    if user is None:
        user = User(id=telegram_id, **fields)
        session.add(user)
        session.add(UserState(user_id=telegram_id, state=dict(DEFAULT_STATE)))
        session.add(Reminder(user_id=telegram_id))
    else:
        for key, value in fields.items():
            if value is not None:
                setattr(user, key, value)
    await session.flush()
    return user


async def get_state(session: AsyncSession, user_id: int) -> dict:
    row = await session.get(UserState, user_id)
    if row is None:
        return dict(DEFAULT_STATE)
    return row.state


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
