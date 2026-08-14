"""FastAPI server: Telegram auth + progress-state sync for the web app.

Run with: uvicorn api:app --host 0.0.0.0 --port $PORT
Shares Postgres with the bot process (bot.py) via db.py — no internal HTTP calls between them.
"""

from __future__ import annotations

import datetime as dt
import logging

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
import db
from auth import (
    create_session_token,
    decode_session_token,
    generate_login_code,
    verify_telegram_auth,
    verify_webapp_init_data,
)
from texts import display_name

logger = logging.getLogger(__name__)

app = FastAPI(title="anatom-bot auth/state API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Authorization", "Content-Type"],
)


class TelegramAuthPayload(BaseModel):
    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str


class AuthResponse(BaseModel):
    token: str
    user_id: int


class StartSessionResponse(BaseModel):
    code: str
    deep_link: str


class SessionStatusResponse(BaseModel):
    status: str
    token: str | None = None
    user_id: int | None = None


@app.on_event("startup")
async def on_startup() -> None:
    await db.init_models()


async def current_user_id(authorization: str = Header(default="")) -> int:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    user_id = decode_session_token(token, config.SESSION_SECRET)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user_id


@app.post("/auth/telegram", response_model=AuthResponse)
async def auth_telegram(payload: TelegramAuthPayload) -> AuthResponse:
    data = payload.model_dump()
    if not verify_telegram_auth(data, config.BOT_TOKEN, max_age_seconds=config.TELEGRAM_AUTH_MAX_AGE_SECONDS):
        raise HTTPException(status_code=403, detail="Telegram auth verification failed")

    session_maker = db.get_session_maker()
    async with session_maker() as session:
        async with session.begin():
            await db.get_or_create_user(
                session,
                telegram_id=payload.id,
                username=payload.username,
                first_name=payload.first_name,
                last_name=payload.last_name,
                photo_url=payload.photo_url,
            )

    token = create_session_token(payload.id, config.SESSION_SECRET, config.SESSION_TTL_SECONDS)
    return AuthResponse(token=token, user_id=payload.id)


class WebAppAuthPayload(BaseModel):
    init_data: str


@app.post("/auth/telegram-webapp", response_model=AuthResponse)
async def auth_telegram_webapp(payload: WebAppAuthPayload) -> AuthResponse:
    """Log a student in from inside the Telegram MiniApp.

    The MiniApp has no Login Widget: it posts `Telegram.WebApp.initData` here, which is signed
    with a different scheme (see auth.verify_webapp_init_data). Returns the same session token
    as the widget flow, so the app's existing /api/state calls work unchanged.
    """
    user = verify_webapp_init_data(
        payload.init_data, config.BOT_TOKEN, max_age_seconds=config.TELEGRAM_AUTH_MAX_AGE_SECONDS
    )
    if user is None:
        raise HTTPException(status_code=403, detail="initData verification failed")

    user_id = int(user["id"])
    session_maker = db.get_session_maker()
    async with session_maker() as session:
        async with session.begin():
            await db.get_or_create_user(
                session,
                telegram_id=user_id,
                username=user.get("username"),
                first_name=user.get("first_name"),
                last_name=user.get("last_name"),
                photo_url=user.get("photo_url"),
            )

    token = create_session_token(user_id, config.SESSION_SECRET, config.SESSION_TTL_SECONDS)
    return AuthResponse(token=token, user_id=user_id)


@app.post("/auth/start", response_model=StartSessionResponse)
async def auth_start() -> StartSessionResponse:
    """Website calls this before showing a `t.me/<bot>?start=<code>` deep-link / QR code."""
    code = generate_login_code()
    expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=config.LOGIN_CODE_TTL_SECONDS)

    session_maker = db.get_session_maker()
    async with session_maker() as session:
        async with session.begin():
            session.add(db.LoginSession(code=code, status="pending", expires_at=expires_at))

    return StartSessionResponse(code=code, deep_link=f"https://t.me/{config.BOT_USERNAME}?start={code}")


@app.get("/auth/session/{code}", response_model=SessionStatusResponse)
async def auth_session_status(code: str) -> SessionStatusResponse:
    session_maker = db.get_session_maker()
    async with session_maker() as session:
        login_session = await db.find_login_session(session, code)
        if login_session is None:
            raise HTTPException(status_code=404, detail="Unknown or expired code")
        if login_session.expires_at < dt.datetime.now(dt.timezone.utc):
            raise HTTPException(status_code=410, detail="Code expired")
        if login_session.status != "confirmed" or login_session.user_id is None:
            return SessionStatusResponse(status="pending")

        token = create_session_token(login_session.user_id, config.SESSION_SECRET, config.SESSION_TTL_SECONDS)
        return SessionStatusResponse(status="confirmed", token=token, user_id=login_session.user_id)


class StateEnvelope(BaseModel):
    state: dict


@app.get("/api/leaderboard")
async def get_leaderboard(limit: int = 20, authorization: str = Header(default="")) -> dict:
    """Ranking over the shared Postgres state, so the site and the bot can show the same table.

    The site currently ranks from its own Supabase profiles, which only ever sees students who
    opened the website — anyone who studies solely in Telegram is invisible there, and the two
    leaderboards disagree. Pointing the site at this endpoint makes both read one source.

    Open on purpose (no token required): it returns only display names and XP, exactly what a
    leaderboard shows anyway. Passing a bearer token additionally reports that user's own rank.
    """
    limit = max(1, min(limit, 100))
    session_maker = db.get_session_maker()
    async with session_maker() as session:
        top = await db.top_users_by_xp(session, limit=limit)

        me = None
        if authorization.startswith("Bearer "):
            token = authorization.removeprefix("Bearer ").strip()
            user_id = decode_session_token(token, config.SESSION_SECRET)
            if user_id is not None:
                rank, xp, total = await db.user_rank_by_xp(session, user_id)
                me = {"user_id": user_id, "rank": rank, "xp": xp, "total": total}

    return {
        "leaderboard": [
            {
                "user_id": row["id"],
                "name": display_name(row.get("first_name"), row.get("last_name"), row.get("username")),
                "username": row.get("username"),
                "xp": row["xp"],
            }
            for row in top
        ],
        "me": me,
    }


@app.get("/api/state")
async def get_state(user_id: int = Depends(current_user_id)) -> dict:
    session_maker = db.get_session_maker()
    async with session_maker() as session:
        state = await db.get_state(session, user_id)
    return {"state": state}


@app.put("/api/state")
async def put_state(payload: StateEnvelope, user_id: int = Depends(current_user_id)) -> dict:
    state = payload.state
    session_maker = db.get_session_maker()
    async with session_maker() as session:
        # No explicit session.begin(): get_or_create autobegins the transaction, and opening a
        # second one on the same session raises InvalidRequestError. Commit once at the end.
        # user_state.user_id is an FK, so a token that outlives its users row (DB reset, manual
        # delete) would fail the insert instead of just saving state — reinstate the row first.
        await db.get_or_create_user(session, telegram_id=user_id)
        await db.put_state(session, user_id, state)
        await session.commit()

    return {"ok": True}
