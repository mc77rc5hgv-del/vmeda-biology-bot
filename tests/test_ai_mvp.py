# -*- coding: utf-8 -*-
"""Тесты AI-режима после архитектурного редизайна конвейера (см. CLAUDE.md/обсуждение
недостатков старой версии): TaskRepresentation + одноразовый vision-парсер (ai/task.py,
ai/vision_parser.py), RAG до ПЕРВОГО ответа + гибридный keyword+embeddings поиск (ai/rag.py),
роутинг по разобранному заданию, а не по форме уже готового ответа (ai/router.route_bucket),
полный учёт стоимости всех попыток провайдера, включая отказы (ai/router.try_providers,
record_ai_attempts_cost)."""
import asyncio
import json
import os
import tempfile

from _bootstrap import tb
from aiogram.dispatcher.event.bases import SkipHandler
from ai import vision as ai_vision
from ai.task import TaskRepresentation

NON_ADMIN = 55501122
ADMIN_ID = next(iter(tb.ADMIN_IDS))

class FakeUser:
    def __init__(self, uid):
        self.id = uid

class FakePhotoSize:
    def __init__(self, file_id):
        self.file_id = file_id

class FakeMsg:
    def __init__(self, uid=NON_ADMIN, photo=None, text=None):
        self.from_user = FakeUser(uid)
        self.photo = photo
        self.text = text
        self.edits = []
        self.deleted = False
        self.last_child = None
        self.children = []  # every message ever sent via .answer(), in order — last_child only
        # keeps the MOST RECENT one, which hides earlier chunks when a long AI answer is split
        # across several messages (see send_ai_result/get_ai_result_chunks in telegram_bot.py)
    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self
    async def delete(self):
        self.deleted = True
    async def answer(self, text, **kwargs):
        m = FakeMsg(uid=self.from_user.id)
        m.edits.append((text, kwargs.get("reply_markup")))
        self.last_child = m
        self.children.append(m)
        return m

class FakeCB:
    def __init__(self, data, uid=NON_ADMIN):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg(uid=uid)
        self._answers = []
    async def answer(self, text=None, show_alert=False):
        self._answers.append((text, show_alert))

def kb_texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row]

def kb_data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]

class FakeBytesBuf:
    def __init__(self, data: bytes):
        self._data = data
    def read(self):
        return self._data

class FakeTgFile:
    def __init__(self, file_path):
        self.file_path = file_path

FAKE_USAGE = {"input_tokens": 1000, "output_tokens": 100}
FAKE_PARSE_USAGE = {"input_tokens": 50, "output_tokens": 10, "provider": "openai"}

async def main():
    uid = NON_ADMIN
    tb.stats["ai_usage"].pop(str(uid), None)
    tb.stats["ai_cost_totals"] = {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    tb.end_ai_session(uid)

    orig_solve = tb.solve_ai_request
    orig_parse_task = tb.ai_vision_parser.parse_task
    orig_search_for_task = tb.ai_rag.search_for_task
    orig_get_client = tb.ai_openai.get_client
    orig_get_grok_client = tb.ai_xai.get_client
    orig_bot_get_file = tb.bot.get_file
    orig_bot_download_file = tb.bot.download_file

    # ==================== ЧАСТЬ A: хендлеры сессии (мокаем границу vision/RAG/solve) ====================

    # ---- 1. main menu always shows the AI entry point ----
    menu = tb.get_main_menu(user_id=uid)
    assert "ai_menu" in kb_data(menu), "AI button must be present in the main menu"
    assert any("VMedA AI" in t for t in kb_texts(menu))
    print("1. main menu AI button: OK")

    # ---- 2. ai_menu screen shows quota and doesn't touch any existing stats key ----
    other_keys_before = {k: v for k, v in tb.stats.items() if k not in ("ai_usage", "ai_cost_totals")}
    cb = FakeCB("ai_menu", uid=uid)
    await tb.cb_ai_menu(cb)
    text, kb = cb.message.edits[-1]
    assert f"{tb.AI_FREE_DAILY_LIMIT}/{tb.AI_FREE_DAILY_LIMIT}" in text
    assert "ai_solve_start" in kb_data(kb)
    assert {k: v for k, v in tb.stats.items() if k not in ("ai_usage", "ai_cost_totals")} == other_keys_before
    print("2. ai_menu screen + no existing stats touched: OK")

    # ---- 3. without OPENAI_API_KEY, AI blocks with a clear error, not a crash ----
    orig_key = tb.OPENAI_API_KEY
    tb.OPENAI_API_KEY = None
    cb_no_key = FakeCB("ai_solve_start", uid=uid)
    await tb.cb_ai_solve_start(cb_no_key)
    assert not tb.is_ai_session_active(uid)
    assert cb_no_key._answers and cb_no_key._answers[0][1] is True  # show_alert
    print("3. AI unavailable without API key: OK")
    tb.OPENAI_API_KEY = "fake-key-for-tests"

    # ---- 4. starting a solve session opens an empty session (task not yet parsed) and shows
    # the cancel keyboard ----
    cb_start = FakeCB("ai_solve_start", uid=uid)
    await tb.cb_ai_solve_start(cb_start)
    assert tb.is_ai_session_active(uid)
    assert tb.AI_SESSIONS[uid]["messages"] == []
    assert tb.AI_SESSIONS[uid]["task"] is None, "task is only set once the first message is vision-parsed"
    text, kb = cb_start.message.edits[-1]
    assert "ai_solve_cancel" in kb_data(kb)
    print("4. ai_solve_start opens a session: OK")

    # ---- 5. cancel closes the session and returns to the menu ----
    cb_cancel = FakeCB("ai_solve_cancel", uid=uid)
    await tb.cb_ai_solve_cancel(cb_cancel)
    assert not tb.is_ai_session_active(uid)
    print("5. ai_solve_cancel closes the session: OK")

    # ---- 6. text message with NO active session must not be swallowed (SkipHandler) ----
    msg = FakeMsg(uid=uid, text="некоторый обычный текст")
    try:
        await tb.handle_ai_text_input(msg)
        raised = False
    except SkipHandler:
        raised = True
    assert raised, "handler must SkipHandler when there's no active AI session, so keyword search still runs"
    print("6. non-AI text falls through via SkipHandler: OK")

    # ---- test doubles for the handler-level round trip: solve_ai_request, vision_parser.parse_task
    # and rag.search_for_task are three SEPARATE seams in the new pipeline (see CLAUDE.md) — mock
    # each independently so handler tests can assert exactly what crosses each boundary ----
    solve_calls = []
    async def fake_solve(*, task=None, text=None, history=None, quick=False, bucket=None, rag_context=None):
        solve_calls.append({
            "task": task, "text": text, "history": list(history or []), "quick": quick,
            "bucket": bucket, "rag_context": rag_context,
        })
        content = task.to_prompt_text() if task is not None else (text or "")
        answer = "Ответ: Б" if quick else "Ответ: Б. Подробное решение по шагам: ..."
        user_turn = {"role": "user", "content": content}
        attempts_log = [{"provider": "openai", "status": "success", "usage": dict(FAKE_USAGE)}]
        return answer, user_turn, dict(FAKE_USAGE, provider="openai"), attempts_log

    parse_calls = []
    parsed_tasks = []
    FAKE_TASK_TYPE = {"type": "unknown", "complexity": None}
    async def fake_parse_task(*, image_bytes=None, text=None):
        parse_calls.append((image_bytes, text))
        task = TaskRepresentation(
            type=FAKE_TASK_TYPE["type"], complexity=FAKE_TASK_TYPE["complexity"],
            question=text or "", raw_text=text or ("фото задания" if image_bytes else ""),
            confidence=0.9,
        )
        parsed_tasks.append(task)
        return task, dict(FAKE_PARSE_USAGE)

    rag_search_calls = []
    FAKE_RAG_SNIPPETS = []
    async def fake_search_for_task(task, limit=3):
        rag_search_calls.append(task)
        return list(FAKE_RAG_SNIPPETS)

    tb.solve_ai_request = fake_solve
    tb.ai_vision_parser.parse_task = fake_parse_task
    tb.ai_rag.search_for_task = fake_search_for_task

    # ---- 7. FIRST message of a session -> vision-parsed into a TaskRepresentation, RAG + bucket
    # computed and cached on the session, task passed straight to solve() as quick=True ----
    tb.start_ai_session(uid)
    FAKE_TASK_TYPE.update(type="mcq", complexity="simple")  # -> route_bucket == "theory_simple"
    before = tb.ai_requests_left(uid)
    cost_before = tb.stats["ai_cost_totals"]["requests"]
    msg2 = FakeMsg(uid=uid, text="Реши задачу по химии")
    await tb.handle_ai_text_input(msg2)
    assert tb.is_ai_session_active(uid), "session must stay open for follow-ups after a successful answer"
    assert len(parse_calls) == 1 and parse_calls[0] == (None, "Реши задачу по химии")
    assert tb.AI_SESSIONS[uid]["task"] is parsed_tasks[-1]
    assert tb.AI_SESSIONS[uid]["bucket"] == "theory_simple"
    assert solve_calls[-1]["task"] is tb.AI_SESSIONS[uid]["task"]
    assert solve_calls[-1]["text"] is None, "on the first message, solve() gets task=, not text="
    assert solve_calls[-1]["quick"] is True
    assert solve_calls[-1]["history"] == []
    assert solve_calls[-1]["bucket"] == "theory_simple"
    assert tb.ai_requests_left(uid) == before - 1
    assert len(tb.AI_SESSIONS[uid]["messages"]) == 2, "user turn + assistant turn must be recorded"
    assert tb.AI_SESSIONS[uid]["quick_answer"] == "Ответ: Б"
    final_text, final_kb = msg2.last_child.edits[-1]
    assert "Ответ: Б" in final_text
    assert f"{tb.ai_requests_left(uid)}/{tb.AI_FREE_DAILY_LIMIT}" in final_text
    assert "ai_show_explanation" in kb_data(final_kb), "a quick answer must offer the step-by-step explanation button"
    assert "ai_session_end" in kb_data(final_kb)
    # cost must be tracked for BOTH the vision-parse call AND the solve attempt — two model calls
    # for the first message is a deliberate architectural tradeoff (see CLAUDE.md)
    assert tb.stats["ai_cost_totals"]["requests"] == cost_before + 2
    assert tb.stats["ai_cost_totals"]["input_tokens"] >= FAKE_USAGE["input_tokens"] + FAKE_PARSE_USAGE["input_tokens"]
    print("7. first message is vision-parsed once, quick-answered, records both calls' cost: OK")

    # ---- 7b. tapping "show explanation" makes a SEPARATE detailed (quick=False) call, spends 1
    # more request, reuses the bucket/rag_context computed at parse time, and does NOT re-parse ----
    before_explain = tb.ai_requests_left(uid)
    cost_before_7b = tb.stats["ai_cost_totals"]["requests"]
    cb_explain = FakeCB("ai_show_explanation", uid=uid)
    await tb.cb_ai_show_explanation(cb_explain)
    assert len(parse_calls) == 1, "the explanation step must NOT re-run vision parsing"
    assert solve_calls[-1]["quick"] is False
    assert solve_calls[-1]["text"] == tb.ai_prompts.explain_followup_text("Ответ: Б")
    assert solve_calls[-1]["bucket"] == "theory_simple", "must reuse the bucket computed at first-message parse time"
    assert solve_calls[-1]["history"] == [
        {"role": "user", "content": parsed_tasks[-1].to_prompt_text()},
        {"role": "assistant", "content": "Ответ: Б"},
    ]
    assert tb.ai_requests_left(uid) == before_explain - 1, "showing the explanation spends its own quota unit"
    assert len(tb.AI_SESSIONS[uid]["messages"]) == 4
    assert tb.stats["ai_cost_totals"]["requests"] == cost_before_7b + 1, "no vision-parse cost on this call"
    explain_text, explain_kb = cb_explain.message.last_child.edits[-1]
    assert "Подробное решение" in explain_text
    print("7b. explanation button makes a detailed request, reuses bucket, doesn't re-parse: OK")

    # ---- 7c. a genuine follow-up typed by the user (not the button) is NOT forced quick, and
    # also does NOT re-run vision parsing (session already has a task) ----
    tb.stats["ai_usage"].pop(str(uid), None)  # fresh quota room for this sub-test
    msg3 = FakeMsg(uid=uid, text="А если бы было другое вещество?")
    await tb.handle_ai_text_input(msg3)
    assert len(parse_calls) == 1, "a typed follow-up must not trigger another vision-parse call"
    assert solve_calls[-1]["quick"] is False, "a real follow-up question the user typed must get a normal (non-quick) answer"
    assert solve_calls[-1]["text"] == "А если бы было другое вещество?"
    assert solve_calls[-1]["task"] is None
    print("7c. typed follow-up questions are not forced into quick mode and skip re-parsing: OK")

    # ---- 8. a photo solve round trip (mocking bot.get_file/download_file), fresh session -> the
    # photo is vision-parsed once and the resulting task drives quick=True + RAG + bucket ----
    tb.end_ai_session(uid)
    tb.start_ai_session(uid)
    tb.stats["ai_usage"].pop(str(uid), None)
    parse_calls.clear()
    solve_calls.clear()
    FAKE_TASK_TYPE.update(type="calculation", complexity=None)  # -> route_bucket == "problem"
    async def fake_get_file(file_id):
        return FakeTgFile(f"path/{file_id}")
    async def fake_download_file(file_path):
        return FakeBytesBuf(b"fake-jpeg-bytes")
    tb.bot.get_file = fake_get_file
    tb.bot.download_file = fake_download_file
    before2 = tb.ai_requests_left(uid)
    photo_msg = FakeMsg(uid=uid, photo=[FakePhotoSize("f1"), FakePhotoSize("f2")])
    await tb.handle_ai_photo_input(photo_msg)
    assert tb.is_ai_session_active(uid)
    assert len(parse_calls) == 1
    assert parse_calls[0] == (b"fake-jpeg-bytes", None), "the resized photo bytes must reach the vision parser"
    assert tb.AI_SESSIONS[uid]["bucket"] == "problem"
    assert solve_calls[-1]["task"] is tb.AI_SESSIONS[uid]["task"]
    assert solve_calls[-1]["quick"] is True
    assert tb.ai_requests_left(uid) == before2 - 1
    assert "Ответ: Б" in photo_msg.last_child.edits[-1][0]
    print("8. fresh photo session is vision-parsed once and answered quick: OK")

    # ---- 8b. a SECOND photo sent within the SAME session is still vision-parsed (never resent as
    # raw bytes to the solver — one-pass vision applies PER photo), but no longer treated as the
    # first message: quick=False, and the session's bucket/rag_context from the FIRST message are
    # reused rather than recomputed ----
    before3 = tb.ai_requests_left(uid)
    parse_calls.clear()
    solve_calls.clear()
    photo_msg2 = FakeMsg(uid=uid, photo=[FakePhotoSize("f3")])
    await tb.handle_ai_photo_input(photo_msg2)
    assert len(parse_calls) == 1, "every photo still gets vision-parsed exactly once when it arrives"
    assert solve_calls[-1]["quick"] is False
    assert solve_calls[-1]["task"] is None, "not the first message anymore -> passed as text, not task"
    assert solve_calls[-1]["text"] == parsed_tasks[-1].to_prompt_text()
    assert solve_calls[-1]["bucket"] == "problem", "bucket from the FIRST message must be reused, not recomputed"
    assert tb.ai_requests_left(uid) == before3 - 1
    print("8b. a later photo in the same session is still parsed once but no longer treated as first: OK")

    # ---- 9. a photo sent OUTSIDE an AI session is silently ignored (no crash, nothing sent) ----
    # (the handler returns before touching bot.get_file/download_file at all, so this is safe to
    # run before restoring the real bot methods below)
    tb.end_ai_session(uid)
    parse_calls_before_9 = len(parse_calls)
    photo_msg3 = FakeMsg(uid=uid, photo=[FakePhotoSize("f4")])
    await tb.handle_ai_photo_input(photo_msg3)
    assert photo_msg3.edits == []
    assert len(parse_calls) == parse_calls_before_9, "no session -> must not even attempt vision parsing"
    print("9. photo outside AI session ignored: OK")

    tb.bot.get_file = orig_bot_get_file
    tb.bot.download_file = orig_bot_download_file

    # ---- 10. daily limit blocks starting a NEW session ----
    tb.stats["ai_usage"][str(uid)] = {"date": tb.date.today().isoformat(), "count": tb.AI_FREE_DAILY_LIMIT}
    assert tb.ai_requests_left(uid) == 0
    cb_limit = FakeCB("ai_solve_start", uid=uid)
    await tb.cb_ai_solve_start(cb_limit)
    assert not tb.is_ai_session_active(uid)
    assert cb_limit._answers[0][1] is True
    print("10. daily limit blocks new sessions: OK")

    # ---- 10b. exhausting the quota MID-dialog auto-closes the session, no explanation/continue buttons ----
    tb.stats["ai_usage"].pop(str(uid), None)
    tb.start_ai_session(uid)
    tb.stats["ai_usage"][str(uid)] = {"date": tb.date.today().isoformat(), "count": tb.AI_FREE_DAILY_LIMIT - 1}
    msg_last = FakeMsg(uid=uid, text="Последний бесплатный вопрос")
    await tb.handle_ai_text_input(msg_last)
    assert not tb.is_ai_session_active(uid), "session must auto-close once the daily quota hits 0"
    last_text, last_kb = msg_last.last_child.edits[-1]
    assert "ai_session_end" not in kb_data(last_kb)
    assert "ai_show_explanation" not in kb_data(last_kb), "no point offering an explanation with 0 quota left"
    assert "ai_menu" in kb_data(last_kb)
    print("10b. quota hitting 0 mid-dialog auto-closes the session: OK")
    tb.stats["ai_usage"].pop(str(uid), None)

    # ---- 10c. tapping "show explanation" with 0 quota left is blocked, not silently charged ----
    tb.start_ai_session(uid)
    tb.AI_SESSIONS[uid]["task"] = TaskRepresentation(question="x", raw_text="x")
    tb.AI_SESSIONS[uid]["quick_answer"] = "Ответ: А"
    tb.AI_SESSIONS[uid]["messages"] = [
        {"role": "user", "content": "x"}, {"role": "assistant", "content": "Ответ: А"},
    ]
    tb.stats["ai_usage"][str(uid)] = {"date": tb.date.today().isoformat(), "count": tb.AI_FREE_DAILY_LIMIT}
    calls_before_10c = len(solve_calls)
    cb_explain_blocked = FakeCB("ai_show_explanation", uid=uid)
    await tb.cb_ai_show_explanation(cb_explain_blocked)
    assert len(solve_calls) == calls_before_10c, "must not call the model when quota is already exhausted"
    assert cb_explain_blocked._answers[0][1] is True
    assert not tb.is_ai_session_active(uid)
    print("10c. explanation button blocked once quota is exhausted: OK")
    tb.stats["ai_usage"].pop(str(uid), None)

    # ---- 11. a slash command during an active session falls through untouched (e.g. /start) ----
    tb.start_ai_session(uid)
    cmd_msg = FakeMsg(uid=uid, text="/start")
    try:
        await tb.handle_ai_text_input(cmd_msg)
        raised = False
    except SkipHandler:
        raised = True
    assert raised
    assert tb.is_ai_session_active(uid), "a slash command must not consume/close the active session"
    print("11. slash command during session: SkipHandler, session untouched: OK")

    # ---- 12. a stale/expired session (idle timeout) is treated as inactive ----
    tb.AI_SESSIONS[uid]["last_active"] = tb.time.time() - tb.AI_SESSION_TIMEOUT_SECONDS - 1
    assert not tb.is_ai_session_active(uid)
    msg_stale = FakeMsg(uid=uid, text="привет спустя полчаса")
    try:
        await tb.handle_ai_text_input(msg_stale)
        raised = False
    except SkipHandler:
        raised = True
    assert raised, "an expired session must not intercept an unrelated later message"
    print("12. expired session no longer intercepts messages: OK")
    tb.end_ai_session(uid)

    # ---- 13. the "processing" flag stops a rapid duplicate message from firing a second call ----
    tb.start_ai_session(uid)
    tb.AI_SESSIONS[uid]["processing"] = True
    calls_before = len(solve_calls)
    dup_msg = FakeMsg(uid=uid, text="дубль, отправлен пока обрабатывается первый")
    try:
        await tb.handle_ai_text_input(dup_msg)
        raised = False
    except SkipHandler:
        raised = True
    assert raised
    assert len(solve_calls) == calls_before, "must not call the model while a previous message is still processing"
    print("13. concurrent duplicate message during processing is ignored: OK")
    tb.end_ai_session(uid)

    # ---- 14. record_ai_cost math is correct and cost block renders ----
    tb.stats["ai_cost_totals"] = {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    tb.record_ai_cost({"input_tokens": 1_000_000, "output_tokens": 1_000_000})
    expected_cost = tb.ai_openai.PRICE_INPUT_PER_1M + tb.ai_openai.PRICE_OUTPUT_PER_1M
    assert abs(tb.stats["ai_cost_totals"]["cost_usd"] - expected_cost) < 1e-9
    block = tb.get_ai_cost_stats_block()
    assert "VMedA AI" in block and "1" in block
    print("14. record_ai_cost math + stats block: OK")

    # ---- 14b. record_ai_attempts_cost: "failed" attempts (network/API error, zero usage) don't
    # add a request; "refused" attempts (content filter, but tokens WERE spent) and the final
    # "success" attempt both do — this is the fix for "cost of failed/refused attempts was never
    # tracked" from the architecture review ----
    tb.stats["ai_cost_totals"] = {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    sample_attempts_log = [
        {"provider": "grok", "status": "failed", "usage": {"input_tokens": 0, "output_tokens": 0}},
        {"provider": "grok", "status": "refused", "usage": {"input_tokens": 80, "output_tokens": 5}},
        {"provider": "openai", "status": "success", "usage": {"input_tokens": 120, "output_tokens": 40}},
    ]
    tb.record_ai_attempts_cost(sample_attempts_log)
    assert tb.stats["ai_cost_totals"]["requests"] == 2, "the zero-usage 'failed' attempt must not be counted"
    by_provider = tb.stats["ai_cost_totals"]["by_provider"]
    assert by_provider["grok"]["requests"] == 1 and by_provider["grok"]["input_tokens"] == 80
    assert by_provider["openai"]["requests"] == 1 and by_provider["openai"]["input_tokens"] == 120
    expected_14b = (
        80 * tb.ai_xai.PRICE_INPUT_PER_1M / 1_000_000 + 5 * tb.ai_xai.PRICE_OUTPUT_PER_1M / 1_000_000
        + 120 * tb.ai_openai.PRICE_INPUT_PER_1M / 1_000_000 + 40 * tb.ai_openai.PRICE_OUTPUT_PER_1M / 1_000_000
    )
    assert abs(tb.stats["ai_cost_totals"]["cost_usd"] - expected_14b) < 1e-9
    print("14b. record_ai_attempts_cost tracks refused/success cost, skips zero-usage failures: OK")

    # ---- 15. admin has unlimited AI requests, even at/over the daily quota ----
    FAKE_TASK_TYPE.update(type="unknown", complexity=None)
    tb.end_ai_session(ADMIN_ID)
    tb.stats["ai_usage"][str(ADMIN_ID)] = {"date": tb.date.today().isoformat(), "count": tb.AI_FREE_DAILY_LIMIT + 5}
    tb.stats["ai_usage"][str(uid)] = {"date": tb.date.today().isoformat(), "count": tb.AI_FREE_DAILY_LIMIT}
    assert tb.has_unlimited_ai(ADMIN_ID)
    assert tb.ai_quota_ok(ADMIN_ID)
    assert not tb.has_unlimited_ai(uid) and not tb.ai_quota_ok(uid), "regular user stays capped as before"
    assert "безлимит" in tb.get_ai_quota_label(ADMIN_ID)
    cb_admin_start = FakeCB("ai_solve_start", uid=ADMIN_ID)
    await tb.cb_ai_solve_start(cb_admin_start)
    assert tb.is_ai_session_active(ADMIN_ID), "admin must be able to start a session past the daily cap"
    admin_msg = FakeMsg(uid=ADMIN_ID, text="Ещё один вопрос сверх лимита")
    await tb.handle_ai_text_input(admin_msg)
    assert tb.is_ai_session_active(ADMIN_ID), "admin's session must not auto-close from quota exhaustion"
    admin_text, admin_kb = admin_msg.last_child.edits[-1]
    assert "безлимит" in admin_text
    assert "ai_session_end" in kb_data(admin_kb)
    tb.end_ai_session(ADMIN_ID)
    tb.stats["ai_usage"].pop(str(ADMIN_ID), None)
    print("15. admin has unlimited AI requests: OK")

    # ---- handler-level: AIRefusalError shows a clear message, does NOT charge the daily quota,
    # leaves the session alive to rephrase — and the partial-attempt cost attached to the
    # exception (.ai_attempts_log) IS still recorded, even though the user got no answer ----
    tb.end_ai_session(uid)
    tb.start_ai_session(uid)
    # not the first message of the session (task already set) -> vision parsing is skipped, so the
    # cost accounting below isolates exactly the refused solve() attempt, nothing else
    tb.AI_SESSIONS[uid]["task"] = TaskRepresentation(question="x", raw_text="x")
    tb.AI_SESSIONS[uid]["bucket"] = "theory_complex"
    tb.stats["ai_usage"].pop(str(uid), None)
    tb.stats["ai_cost_totals"] = {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    async def refusing_solve(**kwargs):
        exc = tb.AIRefusalError("simulated content-filter refusal")
        exc.ai_attempts_log = [{"provider": "openai", "status": "refused", "usage": {"input_tokens": 30, "output_tokens": 5}}]
        raise exc
    tb.solve_ai_request = refusing_solve
    before_r = tb.ai_requests_left(uid)
    msg_r = FakeMsg(uid=uid, text="анатомический вопрос про промежность")
    await tb.handle_ai_text_input(msg_r)
    assert tb.ai_requests_left(uid) == before_r, "a refused attempt must not spend the daily quota"
    assert tb.is_ai_session_active(uid), "session must stay open so the user can rephrase"
    assert tb.AI_SESSIONS[uid]["messages"] == [], "a refused attempt must not be recorded into history"
    final_text_r = msg_r.last_child.edits[-1][0]
    assert "фильтр" in final_text_r
    assert tb.stats["ai_cost_totals"]["requests"] == 1, "the refused attempt's real cost must still be tracked"
    assert tb.stats["ai_cost_totals"]["by_provider"]["openai"]["input_tokens"] == 30
    print("handler-level AIRefusalError: no quota charge, session survives, partial cost still tracked: OK")
    tb.solve_ai_request = fake_solve
    tb.stats["ai_usage"].pop(str(uid), None)
    tb.end_ai_session(uid)

    # ==================== ЧАСТЬ B: чистые функции (LaTeX, markdown, TaskRepresentation, роутинг) ====================

    # ---- 16. LaTeX cleanup: real formulas the model has actually produced, made readable ----
    raw = (
        r"\( i = 1 + 2 \cdot (0,96) = 2,92 \)."
        r" \( m = \frac{n}{m_{\text{растворителя, кг}}} \approx 0,246 \, \text{моль/кг} \)."
        r" Сульфат калия SO4^{2-} и K^{+}, \Delta T_b \approx 0,37 \, \text{°C}."
    )
    cleaned = tb.ai_service.clean_answer(raw)
    for bad in ("\\(", "\\)", "\\cdot", "\\frac", "\\text", "\\Delta", "\\,", "$"):
        assert bad not in cleaned, f"{bad!r} leaked into cleaned output: {cleaned!r}"
    assert "×" in cleaned  # \cdot -> ×
    assert "≈" in cleaned  # \approx -> ≈
    assert "SO4(2-)" in cleaned and "K(+)" in cleaned  # ^{...} -> (...)
    assert "Δ" in cleaned  # \Delta -> Δ
    assert "моль/кг" in cleaned and "°C" in cleaned  # \text{} unwrapped
    print("16. LaTeX cleanup strips backslash markup and produces readable text: OK")

    # ---- 17. lightweight markdown -> real Telegram HTML tags, always well-balanced ----
    from html.parser import HTMLParser

    class _BalanceChecker(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.ok = True
        def handle_starttag(self, tag, attrs):
            self.stack.append(tag)
        def handle_endtag(self, tag):
            if not self.stack or self.stack[-1] != tag:
                self.ok = False
            else:
                self.stack.pop()

    md = "1. **Молекулярная масса:**\n- K: 39,1 г/моль\n- S: 32,1 г/моль\n\nИтог: **174,3 г/моль**."
    formatted = tb.ai_service.format_answer_html(md)
    assert "<b>Молекулярная масса:</b>" in formatted
    assert "<b>174,3 г/моль</b>" in formatted
    assert "• K: 39,1 г/моль" in formatted and "• S: 32,1 г/моль" in formatted
    assert "**" not in formatted, "no raw markdown asterisks should remain"
    checker = _BalanceChecker()
    checker.feed(formatted)
    assert checker.ok and not checker.stack, f"unbalanced HTML: {formatted!r}"

    unsafe = "Если n < 5, реакция не идёт (K & Na реагируют иначе)."
    formatted_unsafe = tb.ai_service.format_answer_html(unsafe)
    assert "&lt;" in formatted_unsafe and "&amp;" in formatted_unsafe
    checker2 = _BalanceChecker()
    checker2.feed(formatted_unsafe)
    assert checker2.ok and not checker2.stack

    md_headers = "### 1. Брюшина\n• Определение: передняя стенка брюшной полости."
    formatted_headers = tb.ai_service.format_answer_html(md_headers)
    assert "#" not in formatted_headers, "raw markdown headers must not leak into the message"
    assert "<b>1. Брюшина</b>" in formatted_headers
    checker3 = _BalanceChecker()
    checker3.feed(formatted_headers)
    assert checker3.ok and not checker3.stack
    print("17. markdown-to-HTML formatting is real, balanced, and escape-safe: OK")

    # ---- 18. history compaction: only OLD assistant turns get shortened; user turns are always
    # plain strings now (images never enter history at all — see ai/vision_parser.py, the whole
    # class of "strip photo bytes from history" logic this used to need is gone by construction) ----
    long_answer = "Подробный ход решения. " * 30
    long_history = []
    for i in range(20):
        if i % 2 == 0:
            long_history.append({"role": "user", "content": f"вопрос {i}"})
        else:
            long_history.append({"role": "assistant", "content": long_answer + f" #{i}"})
    compacted = tb.ai_service._compact_history(long_history)
    assert len(compacted) == tb.ai_service.HISTORY_MAX_MESSAGES
    assert all(isinstance(m["content"], str) for m in compacted)
    assert not any("image_url" in m["content"] for m in compacted), "images must never appear in history"
    user_texts = [m["content"] for m in compacted if m["role"] == "user"]
    assert user_texts == [f"вопрос {i}" for i in range(20) if i % 2 == 0][-len(user_texts):]
    assistant_msgs = [m["content"] for m in compacted if m["role"] == "assistant"]
    assert len(assistant_msgs) >= 2
    assert assistant_msgs[-1] == long_answer + " #19", "the most recent assistant answer stays full"
    for shortened in assistant_msgs[:-1]:
        assert len(shortened) <= tb.ai_service.HISTORY_SUMMARY_CHARS + 1
        assert shortened.endswith("…")
    print("18. history compaction shortens old assistant answers, never carries images: OK")

    # restore the real implementations for the direct-pipeline/RAG/vision-parser tests below —
    # only Part A (handler-level tests above) needs the fakes at the solve/parse/search boundary
    tb.solve_ai_request = orig_solve
    tb.ai_vision_parser.parse_task = orig_parse_task
    tb.ai_rag.search_for_task = orig_search_for_task

    class FakeUsage:
        prompt_tokens = 42
        completion_tokens = 7
    class FakeChoiceMsg:
        content = "Ответ: А"
    class FakeChoice:
        message = FakeChoiceMsg()
    class FakeOpenAIResponse:
        choices = [FakeChoice()]
        usage = FakeUsage()

    # ---- 19. quick=True (short first answer) always stays on cheap OpenAI, even if Grok is configured ----
    captured19 = {}
    class FakeCompletions19:
        async def create(self, **kwargs):
            captured19["model"] = kwargs["model"]
            return FakeOpenAIResponse()
    class FakeChat19:
        completions = FakeCompletions19()
    class FakeOpenAIClient19:
        chat = FakeChat19()
    class GrokMustNotBeCalledCompletions:
        async def create(self, **kwargs):
            raise AssertionError("Grok must never be called for a quick=True request")
    class GrokMustNotBeCalledChat:
        completions = GrokMustNotBeCalledCompletions()
    class GrokMustNotBeCalledClient:
        chat = GrokMustNotBeCalledChat()

    tb.ai_openai.get_client = lambda: FakeOpenAIClient19()
    tb.ai_xai.get_client = lambda: GrokMustNotBeCalledClient()
    answer19, _, usage19, attempts19 = await orig_solve(text="краткий вопрос", quick=True)
    assert captured19["model"] == tb.ai_openai.MODEL
    assert usage19["provider"] == "openai"
    assert attempts19 == [{"provider": "openai", "status": "success", "usage": {"input_tokens": 42, "output_tokens": 7}}]
    print("19. quick=True always stays on OpenAI, even with Grok configured: OK")

    # ---- 19a. bucket=None (unclassified) stays on OpenAI even with Grok configured and
    # ai_router.USE_GROK_FOR_DETAILED on — Grok only engages for bucket=="theory_complex"
    # specifically, never as a catch-all ----
    assert tb.ai_router.USE_GROK_FOR_DETAILED is True, "Grok is enabled, scoped to theory_complex only"
    captured19a = {}
    class FakeCompletions19a:
        async def create(self, **kwargs):
            captured19a["model"] = kwargs["model"]
            return FakeOpenAIResponse()
    class FakeChat19a:
        completions = FakeCompletions19a()
    class FakeOpenAIClient19a:
        chat = FakeChat19a()
    class GrokMustNotBeCalledCompletions19a:
        async def create(self, **kwargs):
            raise AssertionError("Grok must not be called while bucket is not theory_complex")
    class GrokMustNotBeCalledChat19a:
        completions = GrokMustNotBeCalledCompletions19a()
    class GrokMustNotBeCalledClient19a:
        chat = GrokMustNotBeCalledChat19a()
    tb.ai_openai.get_client = lambda: FakeOpenAIClient19a()
    tb.ai_xai.get_client = lambda: GrokMustNotBeCalledClient19a()
    _, _, usage19a, _ = await orig_solve(text="подробный вопрос", quick=False)
    assert captured19a["model"] == tb.ai_openai.MODEL
    assert usage19a["provider"] == "openai"
    print("19a. bucket=None stays on OpenAI even with Grok enabled (scoped to theory_complex): OK")

    # ---- 19b. bucket="theory_complex" + ai_router.USE_GROK_FOR_DETAILED on -> routes to Grok ----
    tb.ai_router.USE_GROK_FOR_DETAILED = True
    captured_grok = {}
    class FakeGrokUsage:
        prompt_tokens = 300
        completion_tokens = 120
    class FakeGrokChoiceMsg:
        content = "Ответ: Б. Подробный разбор по шагам."
    class FakeGrokChoice:
        message = FakeGrokChoiceMsg()
    class FakeGrokResponse:
        choices = [FakeGrokChoice()]
        usage = FakeGrokUsage()
    class FakeGrokCompletions:
        async def create(self, **kwargs):
            captured_grok["model"] = kwargs["model"]
            return FakeGrokResponse()
    class FakeGrokChat:
        completions = FakeGrokCompletions()
    class FakeGrokClient:
        chat = FakeGrokChat()
    class OpenAIMustNotBeCalledCompletions:
        async def create(self, **kwargs):
            raise AssertionError("OpenAI must not be called when Grok is configured and succeeds")
    class OpenAIMustNotBeCalledChat:
        completions = OpenAIMustNotBeCalledCompletions()
    class OpenAIMustNotBeCalledClient:
        chat = OpenAIMustNotBeCalledChat()

    tb.ai_xai.get_client = lambda: FakeGrokClient()
    tb.ai_openai.get_client = lambda: OpenAIMustNotBeCalledClient()
    tb.stats["ai_cost_totals"] = {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    answer_g, user_turn_g, usage_g, attempts_g = await orig_solve(
        text="подробный вопрос", quick=False, bucket="theory_complex"
    )
    assert captured_grok["model"] == tb.ai_xai.MODEL
    assert usage_g == {"input_tokens": 300, "output_tokens": 120, "provider": "grok"}
    assert attempts_g == [{"provider": "grok", "status": "success", "usage": {"input_tokens": 300, "output_tokens": 120}}]
    tb.record_ai_attempts_cost(attempts_g)
    grok_totals = tb.stats["ai_cost_totals"]["by_provider"]["grok"]
    expected_cost = (
        300 * tb.ai_xai.PRICE_INPUT_PER_1M / 1_000_000 + 120 * tb.ai_xai.PRICE_OUTPUT_PER_1M / 1_000_000
    )
    assert grok_totals["requests"] == 1
    assert abs(grok_totals["cost_usd"] - expected_cost) < 1e-9, "Grok usage must be priced at Grok's own rates"
    assert "из них Grok" in tb.get_ai_cost_stats_block(), "admin stats must break out Grok spend separately"
    print("19b. bucket=theory_complex routes to Grok when configured, priced at Grok rates: OK")

    # ---- 19c. Grok failing falls back to OpenAI exactly once — no retry loop, no doubled token burn ----
    grok_call_count = []
    class FailingGrokCompletions:
        async def create(self, **kwargs):
            grok_call_count.append(1)
            raise RuntimeError("simulated xAI outage")
    class FailingGrokChat:
        completions = FailingGrokCompletions()
    class FailingGrokClient:
        chat = FailingGrokChat()
    fallback_models = []
    class FallbackCompletions:
        async def create(self, **kwargs):
            fallback_models.append(kwargs["model"])
            return FakeOpenAIResponse()
    class FallbackChat:
        completions = FallbackCompletions()
    class FallbackOpenAIClient:
        chat = FallbackChat()

    tb.ai_xai.get_client = lambda: FailingGrokClient()
    tb.ai_openai.get_client = lambda: FallbackOpenAIClient()
    answer_f, user_turn_f, usage_f, attempts_f = await orig_solve(
        text="подробный вопрос 2", quick=False, bucket="theory_complex"
    )
    assert len(grok_call_count) == 1, "must attempt Grok exactly once — not loop or retry it"
    assert fallback_models == [tb.ai_openai.MODEL], "must fall back to OpenAI exactly once after the Grok failure"
    assert usage_f["provider"] == "openai", "usage must be attributed to whichever provider actually answered"
    assert [a["status"] for a in attempts_f] == ["failed", "success"]
    assert attempts_f[0]["usage"] == {"input_tokens": 0, "output_tokens": 0}, "a failed attempt carries zero usage"
    print("19c. Grok failure falls back to OpenAI exactly once, no retry loop: OK")

    tb.ai_openai.get_client = orig_get_client
    tb.ai_xai.get_client = orig_get_grok_client
    tb.ai_router.USE_GROK_FOR_DETAILED = False

    # ---- 20. rag_context reaches the model but is NEVER baked into the returned/stored
    # user_turn — otherwise it would resend itself (and its own token cost) on every future turn
    # of the session; history doesn't compact user turns, so this would silently re-bill the same
    # grounding text forever (same class of bug as the old photo/history cost-runaway) ----
    captured20 = {}
    class FakeCompletions20:
        async def create(self, **kwargs):
            captured20["messages"] = kwargs["messages"]
            return FakeOpenAIResponse()
    class FakeChat20:
        completions = FakeCompletions20()
    class FakeOpenAIClient20:
        chat = FakeChat20()
    tb.ai_openai.get_client = lambda: FakeOpenAIClient20()
    tb.ai_xai.get_client = lambda: None
    fake_rag_context = "Материалы ВМедА по теме: «Пример» (биология): много текста сюда для проверки."

    _, user_turn_20, _, _ = await orig_solve(text="объясни подробнее", quick=False, rag_context=fake_rag_context)
    sent_text = captured20["messages"][-1]["content"]
    assert fake_rag_context in sent_text, "rag_context must reach the model"
    stored_text = user_turn_20["content"]
    assert fake_rag_context not in stored_text, "rag_context must NOT be baked into the stored user_turn"
    assert stored_text == "объясни подробнее"
    print("20. rag_context reaches the model but never gets baked into stored history: OK")

    _, user_turn_20b, _, _ = await orig_solve(text="краткий вопрос", quick=True, rag_context=fake_rag_context)
    sent_text_quick = captured20["messages"][-1]["content"]
    assert fake_rag_context in sent_text_quick, "rag_context now reaches quick answers too (see CLAUDE.md, item 2)"
    assert fake_rag_context not in user_turn_20b["content"], "still never baked into stored history on quick=True"
    print("20b. rag_context reaches quick answers too, still never stored in history: OK")

    tb.ai_openai.get_client = orig_get_client
    tb.ai_xai.get_client = orig_get_grok_client

    # ---- 21. ai_router.route_bucket: classifies by the PARSED TASK's type/complexity (filled in
    # by ai.vision_parser BEFORE any answer exists), not by the shape of an already-generated
    # answer as the old classify_quick_answer() used to — see CLAUDE.md, architecture item 3 ----
    assert tb.ai_router.route_bucket(TaskRepresentation(type="calculation")) == "problem"
    assert tb.ai_router.route_bucket(TaskRepresentation(type="list")) == "problem"
    assert tb.ai_router.route_bucket(TaskRepresentation(type="mcq", complexity="simple")) == "theory_simple"
    assert tb.ai_router.route_bucket(TaskRepresentation(type="theory", complexity="simple")) == "theory_simple"
    assert tb.ai_router.route_bucket(TaskRepresentation(type="mcq", complexity="complex")) == "theory_complex"
    assert tb.ai_router.route_bucket(TaskRepresentation(type="theory", complexity=None)) == "theory_complex"
    assert tb.ai_router.route_bucket(TaskRepresentation(type="unknown")) == "theory_complex"
    print("21. ai_router.route_bucket classifies from the parsed task, not the answer: OK")

    # ---- 21b. ai_router.looks_like_refusal: detects real refusal phrasing, not "не может"-style facts ----
    assert tb.ai_router.looks_like_refusal("Извините, но я не могу помочь с этой просьбой.")
    assert tb.ai_router.looks_like_refusal("I'm sorry, but I can't help with that request.")
    assert not tb.ai_router.looks_like_refusal("Молекула не может изменить свою конформацию без затрат энергии.")
    assert not tb.ai_router.looks_like_refusal("Ответ: Б")
    assert not tb.ai_router.looks_like_refusal("Температура кипения раствора составляет 100,378°C.")
    print("21b. ai_router.looks_like_refusal flags real refusals, not 3rd-person facts: OK")

    # ---- 22. ai_gemini._messages_to_contents: system extracted, roles mapped, images converted
    # (still a general-purpose converter, even though the live pipeline today never sends Gemini a
    # message with an image block — vision only ever goes through ai.vision_parser -> OpenAI) ----
    openai_style_messages = [
        {"role": "system", "content": "СИСТЕМНЫЙ ПРОМПТ"},
        {"role": "user", "content": "старый текстовый вопрос"},
        {"role": "assistant", "content": "старый ответ"},
        {"role": "user", "content": [
            {"type": "text", "text": "новый вопрос"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD", "detail": "low"}},
        ]},
    ]
    system_text, contents = tb.ai_gemini._messages_to_contents(openai_style_messages)
    assert system_text == "СИСТЕМНЫЙ ПРОМПТ"
    assert [c["role"] for c in contents] == ["user", "model", "user"], "assistant maps to model, system is separate"
    assert contents[0]["parts"] == [{"text": "старый текстовый вопрос"}]
    assert contents[1]["parts"] == [{"text": "старый ответ"}]
    last_parts = contents[2]["parts"]
    assert {"text": "новый вопрос"} in last_parts
    image_part = next(p for p in last_parts if "inline_data" in p)
    assert image_part["inline_data"] == {"mime_type": "image/jpeg", "data": "QUJD"}
    print("22. ai_gemini._messages_to_contents converts roles/system/images correctly: OK")

    # ---- 23. the REAL solve(): bucket="theory_simple" + ai_gemini.GEMINI_API_KEY set routes to
    # Gemini, priced at Gemini's own (cheaper) rates ----
    orig_gemini_key = tb.ai_gemini.GEMINI_API_KEY
    tb.ai_gemini.GEMINI_API_KEY = "fake-gemini-key-for-tests"
    gemini_calls = []
    async def fake_call_gemini_success(messages, max_tokens):
        gemini_calls.append((messages, max_tokens))
        return "Правильный вариант: В (эволюционная теория)", {"input_tokens": 150, "output_tokens": 40}
    orig_call_gemini = tb.ai_gemini.call
    tb.ai_gemini.call = fake_call_gemini_success
    class OpenAIMustNotBeCalledCompletions23:
        async def create(self, **kwargs):
            raise AssertionError("OpenAI must not be called when Gemini handles a theory question")
    class OpenAIMustNotBeCalledChat23:
        completions = OpenAIMustNotBeCalledCompletions23()
    class OpenAIMustNotBeCalledClient23:
        chat = OpenAIMustNotBeCalledChat23()
    tb.ai_openai.get_client = lambda: OpenAIMustNotBeCalledClient23()
    tb.stats["ai_cost_totals"] = {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    answer_th, _, usage_th, _ = await orig_solve(text="теоретический вопрос", quick=False, bucket="theory_simple")
    assert usage_th == {"input_tokens": 150, "output_tokens": 40, "provider": "gemini"}
    assert len(gemini_calls) == 1
    tb.record_ai_cost(usage_th)
    gemini_totals = tb.stats["ai_cost_totals"]["by_provider"]["gemini"]
    expected_cost_gemini = (
        150 * tb.ai_gemini.PRICE_INPUT_PER_1M / 1_000_000 + 40 * tb.ai_gemini.PRICE_OUTPUT_PER_1M / 1_000_000
    )
    assert abs(gemini_totals["cost_usd"] - expected_cost_gemini) < 1e-9, "Gemini usage must be priced at Gemini rates"
    assert "из них Gemini" in tb.get_ai_cost_stats_block(), "admin stats must break out Gemini spend separately"
    print("23. bucket=theory_simple + GEMINI_API_KEY routes to Gemini, priced correctly: OK")

    # ---- 23b. bucket="theory_simple" but NO GEMINI_API_KEY still stays on OpenAI ----
    tb.ai_gemini.GEMINI_API_KEY = None
    captured23b = {}
    class FakeCompletions23b:
        async def create(self, **kwargs):
            captured23b["model"] = kwargs["model"]
            return FakeOpenAIResponse()
    class FakeChat23b:
        completions = FakeCompletions23b()
    class FakeOpenAIClient23b:
        chat = FakeChat23b()
    tb.ai_openai.get_client = lambda: FakeOpenAIClient23b()
    gemini_calls.clear()
    _, _, usage_23b, _ = await orig_solve(text="теоретический вопрос", quick=False, bucket="theory_simple")
    assert len(gemini_calls) == 0, "must not call Gemini when GEMINI_API_KEY is unset"
    assert usage_23b["provider"] == "openai"
    assert captured23b["model"] == tb.ai_openai.MODEL
    print("23b. bucket=theory_simple without GEMINI_API_KEY still stays on OpenAI: OK")
    tb.ai_gemini.GEMINI_API_KEY = "fake-gemini-key-for-tests"

    # ---- 23c. bucket="problem" stays on OpenAI even when Gemini IS configured — self-consistency
    # guarantee for calculations ----
    captured23c = {}
    class FakeCompletions23c:
        async def create(self, **kwargs):
            captured23c["model"] = kwargs["model"]
            return FakeOpenAIResponse()
    class FakeChat23c:
        completions = FakeCompletions23c()
    class FakeOpenAIClient23c:
        chat = FakeChat23c()
    tb.ai_openai.get_client = lambda: FakeOpenAIClient23c()
    gemini_calls.clear()
    _, _, usage_23c, _ = await orig_solve(text="расчётная задача", quick=False, bucket="problem")
    assert len(gemini_calls) == 0, "calculation problems must never be routed to Gemini"
    assert usage_23c["provider"] == "openai"
    print("23c. bucket=problem stays on OpenAI even when Gemini is configured: OK")

    # ---- 23d. Gemini failing falls back to OpenAI exactly once — no retry loop ----
    async def fake_call_gemini_failing(messages, max_tokens):
        gemini_calls.append((messages, max_tokens))
        raise RuntimeError("simulated Gemini outage")
    tb.ai_gemini.call = fake_call_gemini_failing
    fallback_models_23d = []
    class FallbackCompletions23d:
        async def create(self, **kwargs):
            fallback_models_23d.append(kwargs["model"])
            return FakeOpenAIResponse()
    class FallbackChat23d:
        completions = FallbackCompletions23d()
    class FallbackOpenAIClient23d:
        chat = FallbackChat23d()
    tb.ai_openai.get_client = lambda: FallbackOpenAIClient23d()
    gemini_calls.clear()
    _, _, usage_23d, _ = await orig_solve(text="теоретический вопрос 2", quick=False, bucket="theory_simple")
    assert len(gemini_calls) == 1, "must attempt Gemini exactly once — not loop or retry it"
    assert fallback_models_23d == [tb.ai_openai.MODEL], "must fall back to OpenAI exactly once after Gemini fails"
    assert usage_23d["provider"] == "openai"
    print("23d. Gemini failure falls back to OpenAI exactly once, no retry loop: OK")

    tb.ai_gemini.call = orig_call_gemini
    tb.ai_openai.get_client = orig_get_client
    tb.ai_gemini.GEMINI_API_KEY = orig_gemini_key

    # ---- 24. refusal chains: a refusal from the primary (already-openai) provider raises
    # AIRefusalError, with the FULL attempts log attached so cost can still be recovered ----
    class RefusalChoiceMsg:
        content = "Извините, но я не могу помочь с этой просьбой."
    class RefusalChoice:
        message = RefusalChoiceMsg()
    class RefusalUsage:
        prompt_tokens = 50
        completion_tokens = 10
    class RefusalResponse:
        choices = [RefusalChoice()]
        usage = RefusalUsage()
    class RefusingOpenAICompletions:
        async def create(self, **kwargs):
            return RefusalResponse()
    class RefusingOpenAIChat:
        completions = RefusingOpenAICompletions()
    class RefusingOpenAIClient:
        chat = RefusingOpenAIChat()
    tb.ai_openai.get_client = lambda: RefusingOpenAIClient()
    tb.ai_xai.get_client = lambda: None
    try:
        await orig_solve(text="анатомический вопрос", quick=False)
        raised = False
    except tb.AIRefusalError as exc:
        raised = True
        assert exc.ai_attempts_log == [
            {"provider": "openai", "status": "refused", "usage": {"input_tokens": 50, "output_tokens": 10}},
        ]
    assert raised, "a refusal from OpenAI (no further fallback) must raise AIRefusalError with attempts attached"
    print("24. OpenAI refusal (no further fallback) raises AIRefusalError with attempts_log: OK")

    # ---- 24b. a refusal from Grok falls back to OpenAI once; if OpenAI then answers normally,
    # the caller gets a normal answer, not an error ----
    tb.ai_router.USE_GROK_FOR_DETAILED = True
    class GrokRefusalCompletions:
        async def create(self, **kwargs):
            return RefusalResponse()
    class GrokRefusalChat:
        completions = GrokRefusalCompletions()
    class GrokRefusalClient:
        chat = GrokRefusalChat()
    fallback_calls_24b = []
    class GoodFallbackCompletions24b:
        async def create(self, **kwargs):
            fallback_calls_24b.append(kwargs["model"])
            return FakeOpenAIResponse()
    class GoodFallbackChat24b:
        completions = GoodFallbackCompletions24b()
    class GoodFallbackClient24b:
        chat = GoodFallbackChat24b()
    tb.ai_xai.get_client = lambda: GrokRefusalClient()
    tb.ai_openai.get_client = lambda: GoodFallbackClient24b()
    _, _, usage_24b, attempts_24b = await orig_solve(text="анатомический вопрос", quick=False, bucket="theory_complex")
    assert len(fallback_calls_24b) == 1, "must fall back to OpenAI exactly once after Grok refuses"
    assert usage_24b["provider"] == "openai"
    assert [a["status"] for a in attempts_24b] == ["refused", "success"]
    print("24b. Grok refusal falls back to OpenAI once, which then answers normally: OK")

    # ---- 24c. if BOTH the primary provider and the OpenAI fallback refuse, AIRefusalError still
    # propagates — exactly 2 attempts total, no infinite retry loop ----
    class BadFallbackCompletions24c:
        async def create(self, **kwargs):
            return RefusalResponse()
    class BadFallbackChat24c:
        completions = BadFallbackCompletions24c()
    class BadFallbackClient24c:
        chat = BadFallbackChat24c()
    tb.ai_xai.get_client = lambda: GrokRefusalClient()
    tb.ai_openai.get_client = lambda: BadFallbackClient24c()
    try:
        await orig_solve(text="анатомический вопрос", quick=False, bucket="theory_complex")
        raised24c = False
    except tb.AIRefusalError as exc:
        raised24c = True
        assert len(exc.ai_attempts_log) == 2
    assert raised24c, "must still raise AIRefusalError if even the OpenAI fallback refuses"
    print("24c. both primary and fallback refusing still raises AIRefusalError, no loop: OK")
    tb.ai_router.USE_GROK_FOR_DETAILED = True
    tb.ai_openai.get_client = orig_get_client
    tb.ai_xai.get_client = orig_get_grok_client

    # ---- 24d. OpenAI refusing on an already-openai primary attempt (e.g. bucket="problem", where
    # Gemini normally isn't used) tries Gemini as a genuine LAST RESORT if configured — a refusal
    # is worse for the user than a slightly less polished but real answer ----
    orig_gemini_key_24d = tb.ai_gemini.GEMINI_API_KEY
    tb.ai_gemini.GEMINI_API_KEY = "fake-gemini-key-for-tests"
    class RefusingOpenAICompletions24d:
        async def create(self, **kwargs):
            return RefusalResponse()
    class RefusingOpenAIChat24d:
        completions = RefusingOpenAICompletions24d()
    class RefusingOpenAIClient24d:
        chat = RefusingOpenAIChat24d()
    tb.ai_openai.get_client = lambda: RefusingOpenAIClient24d()
    gemini_calls_24d = []
    async def fake_call_gemini_success_24d(messages, max_tokens):
        gemini_calls_24d.append(1)
        return "Реальный ответ от Gemini, не отказ.", {"input_tokens": 80, "output_tokens": 30}
    orig_call_gemini_24d = tb.ai_gemini.call
    tb.ai_gemini.call = fake_call_gemini_success_24d
    answer_24d, _, usage_24d, _ = await orig_solve(text="анатомический вопрос", quick=False)
    assert len(gemini_calls_24d) == 1, "must try Gemini exactly once after OpenAI refuses"
    assert usage_24d["provider"] == "gemini"
    assert answer_24d == "Реальный ответ от Gemini, не отказ."
    print("24d. OpenAI refusal falls back to Gemini as last resort, which answers for real: OK")

    # ---- 24e. if Gemini ALSO refuses after OpenAI, AIRefusalError still propagates ----
    async def fake_call_gemini_refuses_24e(messages, max_tokens):
        gemini_calls_24d.append(1)
        return "Извините, но я не могу помочь с этой просьбой.", {"input_tokens": 40, "output_tokens": 10}
    tb.ai_gemini.call = fake_call_gemini_refuses_24e
    gemini_calls_24d.clear()
    try:
        await orig_solve(text="анатомический вопрос", quick=False)
        raised24e = False
    except tb.AIRefusalError:
        raised24e = True
    assert raised24e, "must still raise AIRefusalError if Gemini also refuses"
    assert len(gemini_calls_24d) == 1, "must try Gemini exactly once, not loop"
    print("24e. Gemini also refusing after OpenAI still raises AIRefusalError, no loop: OK")

    tb.ai_gemini.call = orig_call_gemini_24d
    tb.ai_openai.get_client = orig_get_client
    tb.ai_gemini.GEMINI_API_KEY = orig_gemini_key_24d

    # ==================== ЧАСТЬ C: RAG (гибридный keyword+embeddings поиск) ====================

    # ---- 25. RAG regression against the REAL production index (built at import from the bot's
    # own content): the reported anatomy question grounds on real anatomy material, not the old
    # noisy biology false-positives ----
    anatomy_regression_query = (
        "Перикард — серозная оболочка сердца. Полость перикарда — пространство между слоями "
        "перикарда. Средостение — пространство между лёгкими. Грудная полость — пространство, в "
        "котором находятся лёгкие и сердце. Забрюшинное пространство — область за брюшиной, "
        "содержащая жировую ткань и сосуды. Полость малого таза — пространство, в котором "
        "находятся органы мочеполовой системы. Промежность — область между анусом и половыми "
        "органами. Семенной каналикул — трубочки в яичках, где происходит сперматогенез."
    )
    task_regr = TaskRepresentation(type="theory", question=anatomy_regression_query, raw_text=anatomy_regression_query)
    anatomy_matches = await tb.ai_rag.search_for_task(task_regr)
    matched_titles = {s["title"] for s in anatomy_matches}
    assert "Эволюция органов дыхания у беспозвоночных (Типы Annelides, Mollusca, Arthropoda)" not in matched_titles
    assert "Гисто- и органогенез. Производные зародышевых листков" not in matched_titles
    assert anatomy_matches, "the reported real anatomy question should ground on real anatomy material"
    assert all(s["subject"] == "анатомия" for s in anatomy_matches)
    print("25. RAG drops the old noisy biology matches and grounds anatomy questions on ANATOMY: OK")

    # ---- 25b. a focused anatomy question grounds on real anatomy content with correct spelling ----
    idx = tb.ai_rag._index
    assert any(e["subject"] == "анатомия" for e in idx), "ANATOMY must be part of the RAG index"
    task_pleura = TaskRepresentation(
        type="theory", question="Что такое плевра, средостение и полость плевры?",
        raw_text="Что такое плевра, средостение и полость плевры?",
    )
    pleura_snippets = await tb.ai_rag.search_for_task(task_pleura)
    assert any("плевр" in s["title"].lower() or "плевр" in s["text"].lower() for s in pleura_snippets), (
        "a focused anatomy question must ground on real anatomy content with the correct term spelling"
    )
    print("25b. RAG index includes real Anatomy material and grounds focused questions: OK")

    # ---- 25c. task.type=="list" + subquestions: search_for_task queries each item SEPARATELY and
    # unions the results — a single-blob query over all 13 items is too diffuse to match anything
    # (real bug that motivated this: the model kept writing "Плева" instead of "Плевра" because no
    # grounding material ever got hit). Structured subquestions come from ai.vision_parser now,
    # not from splitting the model's own answer text like the old search_snippets_multi did. ----
    numbered_anatomy_items = [
        "Брюшина — складка брюшины, соединяющая органы с задней стенкой живота.",
        "Полость брюшины — пространство между стенками брюшной полости и органами.",
        "Брюшная полость — часть тела, содержащая органы пищеварения, печени, селезёнки и почек.",
        "Плевра — серозная оболочка, покрывающая легкие и внутреннюю поверхность грудной клетки.",
        "Полость плевры — пространство между листками плевры, заполненное плевральной жидкостью.",
        "Перикард — серозная оболочка, окружающая сердце.",
        "Полость перикарда — пространство между слоями перикарда, содержащая перикардиальную жидкость.",
        "Средостение — пространство между легкими, содержащее сердце, трахею и другие структуры.",
        "Грудная полость — часть тела, содержащая легкие и сердце.",
        "Забрюшинное пространство — область, расположенная за брюшной полостью.",
        "Полость малого таза — пространство, содержащее органы мочеполовой системы и прямую кишку.",
        "Промежность — область между анусом и половыми органами.",
        "Семенной каналикул — трубочки в яичках, где происходит образование сперматозоидов.",
    ]
    blob_task = TaskRepresentation(type="theory", question=" ".join(numbered_anatomy_items))
    assert await tb.ai_rag.search_for_task(blob_task) == [], (
        "sanity check: the whole 13-item blob as ONE query is too diffuse to match anything — "
        "confirms the per-item fix below is actually needed"
    )
    list_task = TaskRepresentation(type="list", subquestions=numbered_anatomy_items)
    multi_matches = await tb.ai_rag.search_for_task(list_task, limit=10)
    assert multi_matches, "searching each list item separately must find real anatomy grounding"
    assert all(s["subject"] == "анатомия" for s in multi_matches)
    matched_blob = " ".join(s["title"] + " " + s["text"] for s in multi_matches).lower()
    assert "плевр" in matched_blob, "must ground the pleura term specifically (the one the model got wrong live)"
    print("25c. task.type=='list'+subquestions finds per-item matches a single blob query misses: OK")

    # ---- 26. RAG index build + generic keyword retrieval on a small controlled index (no OpenAI
    # key configured in tests -> search_for_task degrades to pure keyword/IDF matching, same
    # deterministic behavior as before the embeddings layer existed) ----
    fake_questions = {"1": {
        "title": "Митохондрии и клеточное дыхание",
        "answer": "Митохондрии — органоиды клеточного дыхания, синтезируют АТФ путём окисления органических веществ.",
    }}
    fake_physics_q = {"1": {
        "title": "Закон Ома для участка цепи",
        "answer": "Сила тока прямо пропорциональна напряжению и обратно пропорциональна сопротивлению участка цепи.",
    }}
    fake_chem_theory = {"1": {
        "title": "Окислительно-восстановительные реакции",
        "content": "ОВР — реакции с переносом электронов между окислителем и восстановителем.",
    }}
    small_index = tb.ai_rag.build_index(
        questions=fake_questions, physics_questions=fake_physics_q, chemistry_theory=fake_chem_theory,
        chemistry_theory_tickets={}, chemistry_practice_tickets={}, anatomy=tb.ANATOMY,
    )
    assert any(e["subject"] == "биология" and "Митохондрии" in e["title"] for e in small_index)
    assert any(e["subject"] == "физика" and "Ома" in e["title"] for e in small_index)
    assert any(e["subject"] == "химия" and "восстановительные" in e["title"] for e in small_index)
    assert all("key" in e and isinstance(e["key"], str) for e in small_index), (
        "each entry must carry a stable content-addressed key for the embeddings cache"
    )

    orig_rag_index, orig_rag_idf = tb.ai_rag._index, tb.ai_rag._idf
    tb.ai_rag._index = small_index
    tb.ai_rag._idf = tb.ai_rag.build_stem_idf(small_index)
    assert tb.ai_openai.get_client() is None, "sanity: no OpenAI key configured, semantic layer must be inert here"

    task_mito = TaskRepresentation(question="расскажи про митохондрии и клеточное дыхание в клетке")
    mito_matches = await tb.ai_rag.search_for_task(task_mito)
    assert mito_matches and mito_matches[0]["title"] == "Митохондрии и клеточное дыхание"
    task_unrelated = TaskRepresentation(question="совершенно не связанный запрос про космос и звёзды")
    no_match = await tb.ai_rag.search_for_task(task_unrelated)
    assert no_match == [], "must not return noisy single-word-overlap matches (MIN_SCORE gate)"
    context = tb.ai_rag.format_context(mito_matches)
    assert "Митохондрии и клеточное дыхание" in context and "биология" in context
    assert tb.ai_rag.format_context([]) == "", "no snippets -> empty context, no wasted tokens"
    print("26. RAG index build + keyword-only retrieval (no OpenAI key) + formatting: OK")

    # ---- 27. _entry_key: stable content-addressed identifier — same content -> same key, any
    # content change -> a different key (this is what makes embeddings caching incremental) ----
    k1 = tb.ai_rag._entry_key("биология", "Заголовок", "Текст записи")
    k2 = tb.ai_rag._entry_key("биология", "Заголовок", "Текст записи")
    k3 = tb.ai_rag._entry_key("биология", "Заголовок", "Другой текст")
    assert k1 == k2
    assert k1 != k3
    assert isinstance(k1, str) and len(k1) == 24
    print("27. _entry_key is stable and content-addressed: OK")

    # ---- 28. _cosine: plain cosine similarity, safe on empty/mismatched/zero vectors ----
    assert tb.ai_rag._cosine([1, 0], [1, 0]) == 1.0
    assert abs(tb.ai_rag._cosine([1, 0], [0, 1])) < 1e-9
    assert tb.ai_rag._cosine([], [1, 2]) == 0.0
    assert tb.ai_rag._cosine([1, 2], [1, 2, 3]) == 0.0, "mismatched dimensions must not crash, just score 0"
    assert tb.ai_rag._cosine([0, 0], [1, 1]) == 0.0, "a zero vector must not cause division by zero"
    print("28. _cosine handles identical/orthogonal/empty/mismatched/zero vectors safely: OK")

    # ---- 29. _embed_query: no OpenAI client -> None, no network attempt, no crash (RAG degrades
    # to keyword-only, exactly like when the semantic layer was never built at all) ----
    tb.ai_openai.get_client = lambda: None
    embed_result = await tb.ai_rag._embed_query("любой текст запроса")
    assert embed_result is None
    tb.ai_openai.get_client = orig_get_client
    print("29. _embed_query degrades to None without an OpenAI client: OK")

    # ---- 30. _hybrid_score_entries without a query embedding is IDENTICAL to plain keyword
    # scoring — the semantic layer only ever ADDS matches, never changes keyword-only behavior ----
    keyword_only = tb.ai_rag._score_entries(
        "расскажи про митохондрии и клеточное дыхание в клетке", small_index, tb.ai_rag._idf
    )
    hybrid_no_embedding = tb.ai_rag._hybrid_score_entries(
        "расскажи про митохондрии и клеточное дыхание в клетке", None, small_index, tb.ai_rag._idf
    )
    assert {e["title"] for _, e in keyword_only} == {e["title"] for _, e in hybrid_no_embedding}
    kw_by_title = {e["title"]: s for s, e in keyword_only}
    hy_by_title = {e["title"]: s for s, e in hybrid_no_embedding}
    for title, score in kw_by_title.items():
        assert abs(score - hy_by_title[title]) < 1e-9
    print("30. _hybrid_score_entries without an embedding matches pure keyword scoring exactly: OK")

    # ---- 31. _hybrid_score_entries WITH a query embedding: a semantic-only match (zero keyword
    # overlap) surfaces if cosine >= MIN_COSINE, and is excluded below that threshold ----
    fake_entry = {
        "subject": "биология", "title": "Синонимичная тема", "text": "Другими словами то же самое.",
        "stems": set(), "key": "fakekey1234567890123456",
    }
    query_embedding = [1.0, 0.0]
    tb.ai_rag._embeddings[fake_entry["key"]] = [1.0, 0.0]  # identical -> cosine 1.0
    scored_hit = tb.ai_rag._hybrid_score_entries("нет пересечения по словам вообще", query_embedding, [fake_entry], {})
    assert scored_hit and scored_hit[0][1] is fake_entry
    expected_score = 1.0 * tb.ai_rag.SEMANTIC_SCORE_SCALE
    assert abs(scored_hit[0][0] - expected_score) < 1e-9

    tb.ai_rag._embeddings[fake_entry["key"]] = [0.0, 1.0]  # orthogonal -> cosine 0.0, below MIN_COSINE
    scored_miss = tb.ai_rag._hybrid_score_entries("нет пересечения по словам вообще", query_embedding, [fake_entry], {})
    assert scored_miss == []
    del tb.ai_rag._embeddings[fake_entry["key"]]
    print("31. semantic-only matches surface above MIN_COSINE, are excluded below it: OK")

    tb.ai_rag._index, tb.ai_rag._idf = orig_rag_index, orig_rag_idf

    # ---- 32. embeddings cache: save/load round trip on disk, missing file -> empty dict, no crash ----
    tmp_dir = tempfile.mkdtemp()
    cache_path = os.path.join(tmp_dir, "emb_cache.json")
    sample_cache = {"key1": [0.1, 0.2], "key2": [0.3, 0.4]}
    tb.ai_rag._save_embeddings_cache(cache_path, sample_cache)
    loaded = tb.ai_rag._load_embeddings_cache(cache_path)
    assert loaded == sample_cache
    missing = tb.ai_rag._load_embeddings_cache(os.path.join(tmp_dir, "does_not_exist.json"))
    assert missing == {}
    print("32. embeddings cache save/load round trip works, missing file degrades to {}: OK")

    # ---- 33. build_embeddings(): a safe no-op without an OpenAI client (no key/network) ----
    orig_embeddings_state = dict(tb.ai_rag._embeddings)
    tb.ai_openai.get_client = lambda: None
    await tb.ai_rag.build_embeddings()
    assert tb.ai_rag._embeddings == orig_embeddings_state, "must be a safe no-op without a client"
    tb.ai_openai.get_client = orig_get_client
    print("33. build_embeddings() no-ops safely without an OpenAI client: OK")

    # ---- 34. build_embeddings(): incremental — only entries MISSING from the cache get embedded;
    # already-cached entries are neither re-requested nor overwritten (this is what makes repeat
    # bot restarts cheap — see CLAUDE.md) ----
    class FakeEmbeddingItem:
        def __init__(self, embedding):
            self.embedding = embedding
    class FakeEmbeddingsResponse:
        def __init__(self, vectors):
            self.data = [FakeEmbeddingItem(v) for v in vectors]
    class FakeEmbeddingsAPI:
        def __init__(self):
            self.calls = []
        async def create(self, model, input):
            self.calls.append(list(input))
            return FakeEmbeddingsResponse([[0.1, 0.2, 0.3] for _ in input])
    class FakeEmbeddingsClient:
        def __init__(self):
            self.embeddings = FakeEmbeddingsAPI()

    fake_emb_client = FakeEmbeddingsClient()
    tb.ai_openai.get_client = lambda: fake_emb_client
    tiny_index = [
        {"subject": "биология", "title": "A", "text": "текст А", "key": "keyA", "stems": set()},
        {"subject": "биология", "title": "B", "text": "текст Б", "key": "keyB", "stems": set()},
    ]
    tb.ai_rag._index = tiny_index
    tb.ai_rag._embeddings = {"keyA": [9, 9, 9]}
    await tb.ai_rag.build_embeddings()
    assert fake_emb_client.embeddings.calls, "must call the embeddings API for the missing entry"
    assert len(fake_emb_client.embeddings.calls[0]) == 1, "only the MISSING entry (keyB) must be embedded"
    assert "keyB" in tb.ai_rag._embeddings
    assert tb.ai_rag._embeddings["keyA"] == [9, 9, 9], "an already-cached entry must not be re-embedded/overwritten"
    tb.ai_rag._index, tb.ai_rag._idf = orig_rag_index, orig_rag_idf
    tb.ai_rag._embeddings = {}
    tb.ai_openai.get_client = orig_get_client
    print("34. build_embeddings() is incremental: skips cached keys, embeds only missing ones: OK")

    # ==================== ЧАСТЬ D: ai.vision_parser (одноразовый разбор фото/текста) ====================

    # ---- 35. parse_task(): no OpenAI client configured -> degrades to a raw-text task, zero
    # usage, no exception, no network attempt ----
    tb.ai_openai.get_client = lambda: None
    task_nokey, usage_nokey = await tb.ai_vision_parser.parse_task(text="Сколько хромосом у человека?")
    assert task_nokey.raw_text == "Сколько хромосом у человека?"
    assert task_nokey.confidence == 0.0
    assert task_nokey.is_usable()
    assert usage_nokey == {"input_tokens": 0, "output_tokens": 0, "provider": "openai"}
    tb.ai_openai.get_client = orig_get_client
    print("35. parse_task() degrades to raw text without an OpenAI client: OK")

    # ---- 36. parse_task(): the model returns non-JSON garbage -> degrades gracefully, keeps the
    # original text as raw_text instead of crashing the whole AI request ----
    class GarbageChoiceMsg:
        content = "это совсем не json, а обычный текст"
    class GarbageChoice:
        message = GarbageChoiceMsg()
    class GarbageResponse:
        choices = [GarbageChoice()]
        usage = None
    class GarbageCompletions:
        async def create(self, **kwargs):
            return GarbageResponse()
    class GarbageChat:
        completions = GarbageCompletions()
    class GarbageClient:
        chat = GarbageChat()
    tb.ai_openai.get_client = lambda: GarbageClient()
    task_garbage, usage_garbage = await tb.ai_vision_parser.parse_task(text="исходный текст задания")
    assert task_garbage.raw_text == "исходный текст задания"
    assert task_garbage.confidence == 0.0
    tb.ai_openai.get_client = orig_get_client
    print("36. parse_task() degrades gracefully on a non-JSON model response: OK")

    # ---- 37. parse_task(): a well-formed JSON response is parsed correctly, with defensive
    # coercion (confidence clamped to [0,1], unknown enum values dropped to None/"unknown") ----
    payload37 = json.dumps({
        "subject": "chemistry", "type": "calculation", "complexity": None,
        "question": "Найти молярную массу вещества", "options": [],
        "values": {"m": "10", "V": "2"}, "units": {"m": "г", "V": "л"},
        "subquestions": [], "confidence": 1.5,  # out of range -> must clamp to 1.0
        "raw_text": "исходный текст",
    })
    class GoodUsage37:
        prompt_tokens = 200
        completion_tokens = 60
    class GoodChoiceMsg37:
        content = payload37
    class GoodChoice37:
        message = GoodChoiceMsg37()
    class GoodResponse37:
        choices = [GoodChoice37()]
        usage = GoodUsage37()
    captured37 = {}
    class GoodCompletions37:
        async def create(self, **kwargs):
            captured37["messages"] = kwargs["messages"]
            return GoodResponse37()
    class GoodChat37:
        completions = GoodCompletions37()
    class GoodClient37:
        chat = GoodChat37()
    tb.ai_openai.get_client = lambda: GoodClient37()
    task37, usage37 = await tb.ai_vision_parser.parse_task(text="ignored — the fake response is what matters")
    assert task37.subject == "chemistry" and task37.type == "calculation"
    assert task37.confidence == 1.0, "confidence must be clamped to [0, 1]"
    assert task37.values == {"m": "10", "V": "2"} and task37.units == {"m": "г", "V": "л"}
    assert usage37 == {"input_tokens": 200, "output_tokens": 60, "provider": "openai"}
    print("37. parse_task() parses valid JSON correctly with defensive coercion: OK")

    # ---- 38. parse_task(): a photo is sent at "detail": "low" — gpt-4o-mini bills high/auto
    # detail at up to 36 835 tokens per photo vs a flat 2833 at low, by far the single biggest
    # cost lever in the whole feature ----
    await tb.ai_vision_parser.parse_task(image_bytes=b"fake-jpeg-bytes")
    sent_content38 = captured37["messages"][-1]["content"]
    image_block = next(p for p in sent_content38 if p["type"] == "image_url")
    assert image_block["image_url"]["detail"] == ai_vision.DETAIL == "low"
    tb.ai_openai.get_client = orig_get_client
    print("38. photos are sent to the vision parser at detail=low: OK")

    # ---- 38b. parse_task(): OpenAI unavailable (no client) but Gemini configured -> falls back
    # to Gemini and succeeds, instead of degrading straight to confidence=0 raw text (the real fix
    # for "a photo with only OpenAI down used to get almost no useful answer") ----
    orig_gemini_key_38b = tb.ai_gemini.GEMINI_API_KEY
    orig_gemini_call_38b = tb.ai_gemini.call
    tb.ai_gemini.GEMINI_API_KEY = "fake-gemini-key-for-tests"
    tb.ai_openai.get_client = lambda: None
    payload38b = json.dumps({
        "subject": "biology", "type": "theory", "complexity": "simple",
        "question": "Что такое митоз?", "options": [], "values": {}, "units": {},
        "subquestions": [], "confidence": 0.8, "raw_text": "Что такое митоз?",
    })
    gemini_calls_38b = []
    async def fake_gemini_call_38b(messages, max_tokens):
        gemini_calls_38b.append((messages, max_tokens))
        return payload38b, {"input_tokens": 120, "output_tokens": 45}
    tb.ai_gemini.call = fake_gemini_call_38b
    task38b, usage38b = await tb.ai_vision_parser.parse_task(text="Что такое митоз?")
    assert len(gemini_calls_38b) == 1
    assert task38b.subject == "biology" and task38b.type == "theory"
    assert usage38b == {"input_tokens": 120, "output_tokens": 45, "provider": "gemini"}
    print("38b. parse_task() falls back to Gemini when OpenAI has no client configured: OK")

    # ---- 38c. parse_task(): OpenAI raises (network/API failure, not just "no client") — Gemini
    # still catches it, same fallback path ----
    class FailingOpenAICompletions38c:
        async def create(self, **kwargs):
            raise RuntimeError("simulated OpenAI outage")
    class FailingOpenAIChat38c:
        completions = FailingOpenAICompletions38c()
    class FailingOpenAIClient38c:
        chat = FailingOpenAIChat38c()
    tb.ai_openai.get_client = lambda: FailingOpenAIClient38c()
    gemini_calls_38b.clear()
    task38c, usage38c = await tb.ai_vision_parser.parse_task(text="Что такое митоз?")
    assert len(gemini_calls_38b) == 1
    assert usage38c["provider"] == "gemini"
    print("38c. parse_task() falls back to Gemini when OpenAI raises, not just when unconfigured: OK")

    # ---- 38d. parse_task(): Gemini has no response_format=json_object guarantee (unlike OpenAI,
    # this is a raw HTTP call) and sometimes wraps its JSON in a ``` fence despite the prompt
    # instruction — must still parse correctly ----
    async def fake_gemini_call_fenced(messages, max_tokens):
        return f"```json\n{payload38b}\n```", {"input_tokens": 100, "output_tokens": 40}
    tb.ai_gemini.call = fake_gemini_call_fenced
    task38d, usage38d = await tb.ai_vision_parser.parse_task(text="Что такое митоз?")
    assert task38d.subject == "biology" and task38d.type == "theory"
    assert usage38d["provider"] == "gemini"
    print("38d. parse_task() strips a Gemini ``` json fence before parsing: OK")

    # ---- 38e. parse_task(): both OpenAI and Gemini fail -> still degrades gracefully to a
    # raw-text task instead of raising ----
    async def failing_gemini_call_38e(messages, max_tokens):
        raise RuntimeError("simulated Gemini outage too")
    tb.ai_gemini.call = failing_gemini_call_38e
    task38e, usage38e = await tb.ai_vision_parser.parse_task(text="Что такое митоз?")
    assert task38e.raw_text == "Что такое митоз?"
    assert task38e.confidence == 0.0
    assert usage38e == {"input_tokens": 0, "output_tokens": 0, "provider": "openai"}
    print("38e. parse_task() degrades gracefully when both OpenAI and Gemini fail: OK")

    tb.ai_gemini.call = orig_gemini_call_38b
    tb.ai_gemini.GEMINI_API_KEY = orig_gemini_key_38b
    tb.ai_openai.get_client = orig_get_client

    # ==================== ЧАСТЬ E: ai.task.TaskRepresentation ====================

    # ---- 39. TaskRepresentation: prompt rendering, round trip, and fingerprint semantics —
    # canonical (case/punctuation-insensitive) but ORDER-preserving, so opposite-meaning questions
    # sharing the same word set never collide (see CLAUDE.md: "A вызывает B?" vs "B вызывает A?") ----
    t = TaskRepresentation(
        subject="biology", type="calculation", question="Найти массу",
        values={"m": "10"}, units={"m": "г"}, options=[], subquestions=["пункт 1", "пункт 2"],
        confidence=0.8, raw_text="исходный текст",
    )
    assert t.is_usable()
    assert t.question_text() == "Найти массу"
    prompt_text = t.to_prompt_text()
    assert "Найти массу" in prompt_text
    assert "Дано: m = 10 г" in prompt_text
    assert "пункт 1" in prompt_text and "пункт 2" in prompt_text
    d = t.to_dict()
    t2 = TaskRepresentation.from_dict(d)
    assert t2.to_dict() == d

    fp_base = TaskRepresentation(question="Найти массу", values={"m": "10"}).fingerprint()
    fp_case = TaskRepresentation(question="НАЙТИ МАССУ", values={"m": "10"}).fingerprint()
    fp_punct = TaskRepresentation(question="Найти,  массу!", values={"m": "10"}).fingerprint()
    assert fp_base == fp_case == fp_punct, (
        "case/punctuation/whitespace-only differences must still collide into the same fingerprint"
    )

    fp_reordered = TaskRepresentation(question="массу найти", values={"m": "10"}).fingerprint()
    assert fp_base != fp_reordered, (
        "word ORDER must now be preserved, not sorted away — a regression here would resurrect the "
        "cross-collision bug between differently-ordered, differently-meaning questions"
    )
    fp_cause_ab = TaskRepresentation(question="Вещество A вызывает реакцию вещества B").fingerprint()
    fp_cause_ba = TaskRepresentation(question="Вещество B вызывает реакцию вещества A").fingerprint()
    assert fp_cause_ab != fp_cause_ba, (
        "opposite-meaning questions built from the same word set must never share a fingerprint — "
        "the exact-match cache would otherwise serve one question's approved answer to the other"
    )

    fp_values_reordered = TaskRepresentation(question="Найти массу", values={"V": "2", "m": "10"}).fingerprint()
    fp_values_same_order = TaskRepresentation(question="Найти массу", values={"m": "10", "V": "2"}).fingerprint()
    assert fp_values_reordered == fp_values_same_order, (
        "values are independent key/value facts, not sequential text — their dict insertion order "
        "must NOT affect the fingerprint, unlike word order in the question itself"
    )

    fp3 = TaskRepresentation(question="Найти массу", values={"m": "20"}).fingerprint()
    assert fp_base != fp3, "different condition values must change the fingerprint, even with the same wording"

    assert not TaskRepresentation().is_usable(), "an empty task (no question, no raw_text) is not usable"
    print("39. TaskRepresentation: prompt rendering, round trip, order-preserving fingerprint: OK")

    # ==================== ЧАСТЬ F: кэш точных совпадений с модерацией ====================

    # ---- 40. get_cached_ai_answer: only an APPROVED entry is ever served; pending/rejected are
    # not, since a wrong AI-generated answer must never propagate to other students unreviewed
    # ("Модерация перед раздачей" — see CLAUDE.md) ----
    tb.stats["ai_answer_cache"].clear()
    task40 = TaskRepresentation(question="Тестовый вопрос для кэша 40", raw_text="Тестовый вопрос для кэша 40")
    fp40 = task40.fingerprint()
    assert tb.get_cached_ai_answer(fp40) is None, "missing fingerprint -> no cached answer"
    tb.stats["ai_answer_cache"][fp40] = {
        "question_preview": "x", "answer": "кэшированный ответ", "subject": "biology",
        "status": "pending", "created_at": tb.time.time(), "hits": 0,
    }
    assert tb.get_cached_ai_answer(fp40) is None, "a pending entry must not be served"
    tb.stats["ai_answer_cache"][fp40]["status"] = "rejected"
    assert tb.get_cached_ai_answer(fp40) is None, "a rejected entry must not be served"
    tb.stats["ai_answer_cache"][fp40]["status"] = "approved"
    assert tb.get_cached_ai_answer(fp40) == "кэшированный ответ"
    assert tb.stats["ai_answer_cache"][fp40]["hits"] == 1
    assert tb.get_cached_ai_answer(fp40) == "кэшированный ответ"
    assert tb.stats["ai_answer_cache"][fp40]["hits"] == 2
    print("40. get_cached_ai_answer serves only approved entries, counts hits: OK")

    # ---- 41. submit_ai_answer_for_moderation: queues a fresh candidate, refreshes a still-pending
    # (or rejected) entry with the newest generation, but NEVER overwrites an already-approved
    # answer — the approved version stays the source of truth until an admin explicitly changes it ----
    tb.stats["ai_answer_cache"].clear()
    task41 = TaskRepresentation(question="Второй тестовый вопрос", raw_text="Второй тестовый вопрос", subject="chemistry")
    fp41 = task41.fingerprint()
    tb.submit_ai_answer_for_moderation(task41, "первый сгенерированный ответ")
    entry41 = tb.stats["ai_answer_cache"][fp41]
    assert entry41["status"] == "pending"
    assert entry41["answer"] == "первый сгенерированный ответ"
    assert entry41["subject"] == "chemistry"
    assert entry41["hits"] == 0

    entry41["hits"] = 3  # simulate accumulated hits before the candidate gets refreshed
    tb.submit_ai_answer_for_moderation(task41, "второй сгенерированный ответ")
    assert tb.stats["ai_answer_cache"][fp41]["answer"] == "второй сгенерированный ответ"
    assert tb.stats["ai_answer_cache"][fp41]["hits"] == 3, "hits must survive a pending entry being refreshed"

    tb.moderate_ai_cache_entry(fp41, approve=True)
    tb.submit_ai_answer_for_moderation(task41, "ответ, который не должен попасть в кэш")
    assert tb.stats["ai_answer_cache"][fp41]["answer"] == "второй сгенерированный ответ"
    assert tb.stats["ai_answer_cache"][fp41]["status"] == "approved"
    print("41. submit_ai_answer_for_moderation queues candidates, never overwrites an approved answer: OK")

    # ---- 42. moderate_ai_cache_entry: approve/reject transitions, False for an unknown fingerprint ----
    assert tb.moderate_ai_cache_entry("несуществующий_фингерпринт", approve=True) is False
    task42 = TaskRepresentation(question="Третий тестовый вопрос", raw_text="Третий тестовый вопрос")
    tb.submit_ai_answer_for_moderation(task42, "ответ")
    fp42 = task42.fingerprint()
    assert tb.moderate_ai_cache_entry(fp42, approve=False) is True
    assert tb.stats["ai_answer_cache"][fp42]["status"] == "rejected"
    assert tb.moderate_ai_cache_entry(fp42, approve=True) is True
    assert tb.stats["ai_answer_cache"][fp42]["status"] == "approved"
    print("42. moderate_ai_cache_entry transitions state, False for an unknown fingerprint: OK")

    # ---- 43. get_pending_ai_cache_count / get_next_pending_ai_cache_entry: oldest-first, only
    # counts entries still awaiting moderation ----
    tb.stats["ai_answer_cache"].clear()
    t_old = TaskRepresentation(question="Старый вопрос", raw_text="Старый вопрос")
    t_new = TaskRepresentation(question="Новый вопрос", raw_text="Новый вопрос")
    tb.submit_ai_answer_for_moderation(t_old, "ответ старый")
    tb.stats["ai_answer_cache"][t_old.fingerprint()]["created_at"] = tb.time.time() - 100
    tb.submit_ai_answer_for_moderation(t_new, "ответ новый")
    assert tb.get_pending_ai_cache_count() == 2
    fp_first, entry_first = tb.get_next_pending_ai_cache_entry()
    assert fp_first == t_old.fingerprint(), "the oldest pending entry must come first"
    tb.moderate_ai_cache_entry(t_old.fingerprint(), approve=True)
    assert tb.get_pending_ai_cache_count() == 1
    fp_second, entry_second = tb.get_next_pending_ai_cache_entry()
    assert fp_second == t_new.fingerprint()
    tb.moderate_ai_cache_entry(t_new.fingerprint(), approve=True)
    assert tb.get_pending_ai_cache_count() == 0
    assert tb.get_next_pending_ai_cache_entry() == (None, None)
    print("43. get_pending_ai_cache_count/get_next_pending_ai_cache_entry: oldest-first, correct filtering: OK")

    # ---- 44. get_first_message_ai_answer: on a cache MISS, calls the model exactly like a normal
    # first message, spends quota/cost, and queues the fresh answer for moderation ----
    tb.stats["ai_answer_cache"].clear()
    tb.stats["ai_usage"].pop(str(uid), None)
    tb.stats["ai_cost_totals"] = {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    solve_calls_44 = []
    async def fake_solve_44(*, task=None, text=None, history=None, quick=False, bucket=None, rag_context=None):
        solve_calls_44.append({"task": task, "quick": quick, "bucket": bucket, "rag_context": rag_context})
        text_part = task.to_prompt_text() + tb.ai_prompts.QUICK_SUFFIX
        return (
            "свежий ответ", {"role": "user", "content": text_part}, dict(FAKE_USAGE, provider="openai"),
            [{"provider": "openai", "status": "success", "usage": dict(FAKE_USAGE)}],
        )
    tb.solve_ai_request = fake_solve_44

    task44 = TaskRepresentation(
        question="Уникальный вопрос для проверки кэш-промаха",
        raw_text="Уникальный вопрос для проверки кэш-промаха",
    )
    session44 = {"messages": [], "bucket": "theory_complex", "rag_context": None, "quick_answer": None}
    before44 = tb.ai_requests_left(uid)
    cost_before44 = tb.stats["ai_cost_totals"]["requests"]
    answer44, user_turn44 = await tb.get_first_message_ai_answer(uid, session44, task44)
    assert len(solve_calls_44) == 1, "a cache miss must call the model"
    assert answer44 == "свежий ответ"
    assert session44["quick_answer"] == "свежий ответ"
    assert tb.ai_requests_left(uid) == before44 - 1
    assert tb.stats["ai_cost_totals"]["requests"] == cost_before44 + 1
    fp44 = task44.fingerprint()
    assert tb.stats["ai_answer_cache"][fp44]["status"] == "pending"
    assert tb.stats["ai_answer_cache"][fp44]["answer"] == "свежий ответ"
    print("44. get_first_message_ai_answer on a cache miss calls the model and queues moderation: OK")

    # ---- 44b. once approved, the SAME task is served from cache: no model call, no quota/cost
    # spent, and the stored user_turn matches what a real solve() call would have produced ----
    tb.moderate_ai_cache_entry(fp44, approve=True)
    session44b = {"messages": [], "bucket": "theory_complex", "rag_context": None, "quick_answer": None}
    before44b = tb.ai_requests_left(uid)
    cost_before44b = tb.stats["ai_cost_totals"]["requests"]
    answer44b, user_turn44b = await tb.get_first_message_ai_answer(uid, session44b, task44)
    assert len(solve_calls_44) == 1, "a cache hit must NOT call the model again"
    assert answer44b == "свежий ответ"
    assert session44b["quick_answer"] == "свежий ответ"
    assert tb.ai_requests_left(uid) == before44b, "a cache hit must not spend quota"
    assert tb.stats["ai_cost_totals"]["requests"] == cost_before44b, "a cache hit must not record any cost"
    assert user_turn44b["content"] == task44.to_prompt_text() + tb.ai_prompts.QUICK_SUFFIX, (
        "the stored user_turn on a cache hit must match what a real solve() call would have produced"
    )
    print("44b. get_first_message_ai_answer on a cache hit skips the model entirely, spends nothing: OK")

    # ---- 45. end-to-end handler regression: a fresh question is answered by the model and queued;
    # once an admin approves it, a COMPLETELY SEPARATE session asking the exact same question gets
    # served from cache — no model call, no quota spent, session/history still populate normally ----
    tb.stats["ai_answer_cache"].clear()
    tb.stats["ai_usage"].pop(str(uid), None)
    tb.end_ai_session(uid)
    solve_calls_45 = []
    async def fake_solve_45(*, task=None, text=None, history=None, quick=False, bucket=None, rag_context=None):
        solve_calls_45.append(1)
        text_part = task.to_prompt_text() if task is not None else (text or "")
        answer = "Ответ: 46 хромосом" if quick else "Подробно: ..."
        return answer, {"role": "user", "content": text_part}, dict(FAKE_USAGE, provider="openai"), [
            {"provider": "openai", "status": "success", "usage": dict(FAKE_USAGE)},
        ]
    tb.solve_ai_request = fake_solve_45

    tb.start_ai_session(uid)
    before45 = tb.ai_requests_left(uid)
    msg45 = FakeMsg(uid=uid, text="Сколько хромосом в соматической клетке человека?")
    await tb.handle_ai_text_input(msg45)
    assert len(solve_calls_45) == 1
    assert tb.ai_requests_left(uid) == before45 - 1, "a fresh (uncached) question must spend quota"
    fingerprint_45 = tb.AI_SESSIONS[uid]["task"].fingerprint()
    assert tb.stats["ai_answer_cache"][fingerprint_45]["status"] == "pending"
    tb.end_ai_session(uid)

    assert tb.moderate_ai_cache_entry(fingerprint_45, approve=True)

    tb.stats["ai_usage"].pop(str(uid), None)
    tb.start_ai_session(uid)
    before45b = tb.ai_requests_left(uid)
    msg45b = FakeMsg(uid=uid, text="Сколько хромосом в соматической клетке человека?")
    await tb.handle_ai_text_input(msg45b)
    assert len(solve_calls_45) == 1, "must NOT call the model again — served from the approved cache"
    assert tb.ai_requests_left(uid) == before45b, "a cache hit must not spend quota"
    final_text_45b, final_kb_45b = msg45b.last_child.edits[-1]
    assert "Ответ: 46 хромосом" in final_text_45b
    assert "ai_show_explanation" in kb_data(final_kb_45b), "a cached quick answer still offers the explanation button"
    assert tb.stats["ai_answer_cache"][fingerprint_45]["hits"] == 1
    tb.end_ai_session(uid)
    tb.stats["ai_usage"].pop(str(uid), None)
    print("45. end-to-end: fresh question queued for moderation, approved answer served for free to a new session: OK")

    tb.solve_ai_request = orig_solve

    # ---- 46. admin moderation queue UI: pending count on the menu button, question/answer shown,
    # approve/reject transition state and re-render, non-admin blocked from every action ----
    tb.stats["ai_answer_cache"].clear()
    menu_no_pending = tb.get_admin_menu()
    assert "admin_ai_cache_queue" in kb_data(menu_no_pending)
    assert any(t.startswith("🤖 Модерация AI-кэша") for t in kb_texts(menu_no_pending))

    cb_queue_empty = FakeCB("admin_ai_cache_queue", uid=ADMIN_ID)
    await tb.cb_admin_ai_cache_queue(cb_queue_empty)
    empty_text = cb_queue_empty.message.edits[-1][0]
    assert "пуста" in empty_text

    task46 = TaskRepresentation(
        question="Вопрос для проверки админ-очереди", raw_text="Вопрос для проверки админ-очереди",
        subject="physics",
    )
    tb.submit_ai_answer_for_moderation(task46, "ответ на модерации")
    fp46 = task46.fingerprint()

    menu_with_pending = tb.get_admin_menu()
    assert any("Модерация AI-кэша (1)" in t for t in kb_texts(menu_with_pending))

    cb_queue = FakeCB("admin_ai_cache_queue", uid=ADMIN_ID)
    await tb.cb_admin_ai_cache_queue(cb_queue)
    queue_text, queue_kb = cb_queue.message.edits[-1]
    assert "Вопрос для проверки админ-очереди" in queue_text
    assert "ответ на модерации" in queue_text
    assert f"admin_ai_cache_approve:{fp46}" in kb_data(queue_kb)
    assert f"admin_ai_cache_reject:{fp46}" in kb_data(queue_kb)

    cb_non_admin = FakeCB("admin_ai_cache_queue", uid=uid)
    await tb.cb_admin_ai_cache_queue(cb_non_admin)
    assert cb_non_admin.message.edits == [], "non-admin must not see the moderation queue"

    cb_approve = FakeCB(f"admin_ai_cache_approve:{fp46}", uid=ADMIN_ID)
    await tb.cb_admin_ai_cache_approve(cb_approve)
    assert tb.stats["ai_answer_cache"][fp46]["status"] == "approved"
    approve_text = cb_approve.message.edits[-1][0]
    assert "пуста" in approve_text, "after approving the only pending entry, the queue must show empty"

    task46b = TaskRepresentation(question="Второй вопрос для отклонения", raw_text="Второй вопрос для отклонения")
    tb.submit_ai_answer_for_moderation(task46b, "плохой ответ")
    fp46b = task46b.fingerprint()
    cb_reject = FakeCB(f"admin_ai_cache_reject:{fp46b}", uid=ADMIN_ID)
    await tb.cb_admin_ai_cache_reject(cb_reject)
    assert tb.stats["ai_answer_cache"][fp46b]["status"] == "rejected"

    cb_non_admin_approve = FakeCB(f"admin_ai_cache_approve:{fp46b}", uid=uid)
    await tb.cb_admin_ai_cache_approve(cb_non_admin_approve)
    assert tb.stats["ai_answer_cache"][fp46b]["status"] == "rejected", "non-admin must not be able to approve"
    print("46. admin AI-cache moderation queue: pending count, approve/reject, non-admin blocked: OK")

    tb.stats["ai_answer_cache"].clear()

    # ==================== ЧАСТЬ G: ai.validator + ai.confidence (детерминированная проверка) ====================

    # ---- 47. validate_answer: structural checks per task type, none of them requiring a model call ----
    calc_task = TaskRepresentation(type="calculation", question="Найти массу вещества")
    no_digits = tb.ai_validator.validate_answer(calc_task, "Масса вещества равна примерно нескольким граммам")
    assert not no_digits.passed and "цифры" in no_digits.warnings[0]
    assert abs(no_digits.confidence_adjustment - (-0.4)) < 1e-9
    with_digits = tb.ai_validator.validate_answer(calc_task, "Масса вещества составляет 4,5 г")
    assert with_digits.passed and with_digits.warnings == []

    mcq_task = TaskRepresentation(
        type="mcq", question="Выберите правильный ответ",
        options=["Митохондрия", "Рибосома", "Лизосома"],
    )
    mentions_option = tb.ai_validator.validate_answer(mcq_task, "Правильный ответ: Митохондрия, она производит энергию")
    assert mentions_option.passed
    unrelated = tb.ai_validator.validate_answer(mcq_task, "Совершенно не относящийся к вариантам ответ про космос")
    assert not unrelated.passed and "не ссылается" in unrelated.warnings[0]

    list_task = TaskRepresentation(type="list", subquestions=[f"пункт {i}" for i in range(6)])
    too_short = tb.ai_validator.validate_answer(list_task, "Один единственный короткий ответ без деталей")
    assert not too_short.passed and "пропущена" in too_short.warnings[0]
    enough_lines = tb.ai_validator.validate_answer(
        list_task, "\n".join(f"пункт {i} — ответ" for i in range(6))
    )
    assert enough_lines.passed

    empty_result = tb.ai_validator.validate_answer(calc_task, "")
    assert not empty_result.passed and abs(empty_result.confidence_adjustment - (-1.0)) < 1e-9
    refusal_result = tb.ai_validator.validate_answer(calc_task, "Извините, но я не могу помочь с этой просьбой.")
    assert not refusal_result.passed and abs(refusal_result.confidence_adjustment - (-1.0)) < 1e-9

    theory_task = TaskRepresentation(type="theory", question="Объясни явление диффузии")
    theory_result = tb.ai_validator.validate_answer(theory_task, "Диффузия — самопроизвольное перемешивание частиц.")
    assert theory_result.passed, "theory/open-ended answers have no type-specific structural check"
    print("47. validate_answer: structural checks per task type, zero model calls: OK")

    # ---- 48. ai.confidence.decide: combines parse confidence + RAG grounding + validator into
    # SERVE / VERIFY / ESCALATE — from_cache=True always short-circuits to SERVE ----
    confident_task = TaskRepresentation(type="mcq", question="x", options=["A", "B"], confidence=0.9)
    clean_validation = tb.ai_validator.validate_answer(confident_task, "Правильный вариант: A")
    serve_decision = tb.ai_confidence.decide(confident_task, clean_validation, rag_grounded=True)
    assert serve_decision.action == tb.ai_confidence.SERVE
    assert serve_decision.score > 1.0, "RAG grounding must be a small positive signal, not just a penalty source"

    verify_decision = tb.ai_confidence.decide(mcq_task, unrelated)
    assert verify_decision.action == tb.ai_confidence.VERIFY

    escalate_decision = tb.ai_confidence.decide(calc_task, empty_result)
    assert escalate_decision.action == tb.ai_confidence.ESCALATE

    cache_decision = tb.ai_confidence.decide(calc_task, empty_result, from_cache=True)
    assert cache_decision.action == tb.ai_confidence.SERVE, (
        "an answer already served from the moderated cache must always be SERVE, "
        "regardless of what a fresh validation run would say"
    )
    assert cache_decision.score == 1.0
    print("48. ai.confidence.decide: SERVE/VERIFY/ESCALATE from combined signals, cache always SERVE: OK")

    # ---- 49. get_next_pending_ai_cache_entry prioritizes by confidence_action (escalate first,
    # then verify, then serve), oldest-first within each tier — this is the real lever ESCALATE has
    # today: no stronger provider to retry with, but a human moderator sees the riskiest answers
    # first instead of in arrival order ----
    tb.stats["ai_answer_cache"].clear()
    t_serve = TaskRepresentation(question="Вопрос без замечаний")
    t_verify = TaskRepresentation(question="Вопрос под вопросом")
    t_escalate = TaskRepresentation(question="Самый рискованный вопрос")
    tb.submit_ai_answer_for_moderation(t_serve, "ok", confidence_action=tb.ai_confidence.SERVE)
    tb.submit_ai_answer_for_moderation(t_verify, "ok", confidence_action=tb.ai_confidence.VERIFY)
    tb.submit_ai_answer_for_moderation(t_escalate, "ok", confidence_action=tb.ai_confidence.ESCALATE)
    fp_next, entry_next = tb.get_next_pending_ai_cache_entry()
    assert fp_next == t_escalate.fingerprint(), "ESCALATE-flagged entries must surface first, regardless of arrival order"
    tb.moderate_ai_cache_entry(fp_next, approve=True)
    fp_next2, _ = tb.get_next_pending_ai_cache_entry()
    assert fp_next2 == t_verify.fingerprint(), "VERIFY comes next, ahead of the plain SERVE entry"
    tb.moderate_ai_cache_entry(fp_next2, approve=True)
    fp_next3, _ = tb.get_next_pending_ai_cache_entry()
    assert fp_next3 == t_serve.fingerprint()
    tb.moderate_ai_cache_entry(fp_next3, approve=True)
    print("49. get_next_pending_ai_cache_entry prioritizes ESCALATE > VERIFY > SERVE: OK")
    tb.stats["ai_answer_cache"].clear()

    # ---- 50. end-to-end: get_first_message_ai_answer appends AI_LOW_CONFIDENCE_NOTE to what's
    # DISPLAYED when the answer doesn't pass validation, but session["quick_answer"] (the
    # canonical anchor for "Показать решение по шагам") stays the ORIGINAL answer, unmarked — the
    # warning must not contaminate the model's own memory of what it previously answered ----
    tb.stats["ai_usage"].pop(str(uid), None)
    async def fake_solve_50(*, task=None, text=None, history=None, quick=False, bucket=None, rag_context=None):
        return (
            "Б", {"role": "user", "content": task.to_prompt_text() + tb.ai_prompts.QUICK_SUFFIX},
            dict(FAKE_USAGE, provider="openai"),
            [{"provider": "openai", "status": "success", "usage": dict(FAKE_USAGE)}],
        )
    tb.solve_ai_request = fake_solve_50
    mcq_task_50 = TaskRepresentation(
        type="mcq", question="Вопрос с вариантами, отвечен буквой без совпадения",
        options=["Кислород", "Азот", "Углекислый газ"], confidence=0.9,
    )
    session50 = {"messages": [], "bucket": "theory_simple", "rag_context": None, "quick_answer": None}
    display50, _ = await tb.get_first_message_ai_answer(uid, session50, mcq_task_50)
    assert tb.AI_LOW_CONFIDENCE_NOTE in display50, "a validator-failing answer must carry the warning when displayed"
    assert session50["quick_answer"] == "Б", "the canonical anchor must stay the original, unmarked answer"
    fp50 = mcq_task_50.fingerprint()
    assert tb.stats["ai_answer_cache"][fp50]["confidence_action"] in (tb.ai_confidence.VERIFY, tb.ai_confidence.ESCALATE)
    assert tb.stats["ai_answer_cache"][fp50]["confidence_reasons"], "the moderation entry must carry the reasons for admin triage"
    print("50. get_first_message_ai_answer: low-confidence answers are flagged for the user and prioritized for review: OK")
    tb.stats["ai_answer_cache"].clear()
    tb.stats["ai_usage"].pop(str(uid), None)
    tb.solve_ai_request = orig_solve

    # ==================== ЧАСТЬ H: разбиение длинных ответов на несколько сообщений ====================

    # ---- 51. split_answer_into_chunks: short answers pass through untouched, no truncation ----
    short_answer = "Короткий ответ, меньше лимита."
    assert tb.ai_service.split_answer_into_chunks(short_answer) == [short_answer]
    assert tb.ai_service.split_answer_into_chunks("") == [""]

    # paragraph-boundary splitting: two paragraphs individually well under the limit, but too
    # long together -> two chunks, every word preserved (only whitespace at the exact cut point
    # may differ, never actual content)
    para_a = "Абзац один. " * 200
    para_b = "Абзац два. " * 200
    two_paragraphs = para_a + "\n\n" + para_b
    chunks51 = tb.ai_service.split_answer_into_chunks(two_paragraphs, max_chars=3000)
    assert len(chunks51) == 2
    assert all(len(c) <= 3000 for c in chunks51)
    assert " ".join(chunks51).split() == two_paragraphs.split(), "no word may be lost or duplicated"

    # a single paragraph/line with no natural break points still splits on WORD boundaries, never
    # mid-word
    no_breaks = "слово " * 3000
    chunks51b = tb.ai_service.split_answer_into_chunks(no_breaks, max_chars=3000)
    assert len(chunks51b) >= 2
    assert all(len(c) <= 3000 for c in chunks51b)
    assert " ".join(chunks51b).split() == no_breaks.split()
    for c in chunks51b:
        assert not c.startswith(" ") and not c.endswith(" "), "must not cut in the middle of a word"

    # pathological case: a single unbreakable "word" longer than the whole chunk limit — the
    # ONLY place actual character-level cutting happens, and it must not silently drop the tail
    unbreakable = "а" * 5000
    chunks51c = tb.ai_service.split_answer_into_chunks(unbreakable, max_chars=3000)
    assert "".join(chunks51c) == unbreakable, "an oversized unbreakable token must never lose characters"
    assert all(len(c) <= 3000 for c in chunks51c)
    print("51. split_answer_into_chunks: paragraph/line/word splitting, no data loss, no mid-word cuts: OK")

    # ---- 52. get_ai_result_chunks: header only on the first chunk, footer+quota only on the
    # last, each chunk independently valid HTML (never a torn tag) ----
    long_markdown_answer = "\n\n".join(f"**Пункт {i}:** подробное объяснение пункта номер {i}. " * 20 for i in range(6))
    chunks52 = tb.get_ai_result_chunks(long_markdown_answer, uid, session_active=True, offer_explanation=True)
    assert len(chunks52) > 1, "sanity check: this answer must actually need splitting for the test to mean anything"
    assert chunks52[0].startswith("🤖 <b>Ответ AI</b>")
    assert not any(c.startswith("🤖 <b>Ответ AI</b>") for c in chunks52[1:]), "header must appear exactly once"
    assert "Осталось бесплатных запросов сегодня" in chunks52[-1]
    assert "показать решение по шагам" not in chunks52[-1].lower() or "🧠" in chunks52[-1]
    assert not any("Осталось бесплатных запросов сегодня" in c for c in chunks52[:-1]), "footer must appear exactly once, on the last chunk"
    for chunk in chunks52:
        checker_ai = _BalanceChecker()
        checker_ai.feed(chunk)
        assert checker_ai.ok and not checker_ai.stack, f"chunk is not balanced HTML on its own: {chunk!r}"
    print("52. get_ai_result_chunks: header on first chunk only, footer on last, every chunk independently balanced HTML: OK")

    # ---- 53. send_ai_result: a long answer is delivered as several real Telegram messages —
    # edits the "thinking" placeholder with the first chunk, sends the rest as new messages, and
    # attaches the action keyboard ONLY to the very last one ----
    thinking53 = FakeMsg(uid=uid)
    await tb.send_ai_result(thinking53, long_markdown_answer, uid, session_active=True, offer_explanation=True)
    assert len(thinking53.edits) == 1, "the thinking placeholder itself is edited exactly once (the first chunk)"
    assert thinking53.edits[0][1] is None, "no keyboard on the first (non-final) chunk"
    assert len(thinking53.children) == len(chunks52) - 1, "every chunk after the first must be a separate new message"
    for child in thinking53.children[:-1]:
        assert child.edits[-1][1] is None, "no keyboard on any non-final chunk"
    assert thinking53.children[-1].edits[-1][1] is not None, "the keyboard must be attached to the very last message"
    assert "ai_show_explanation" in kb_data(thinking53.children[-1].edits[-1][1])
    all_sent_text = thinking53.edits[0][0] + "".join(c.edits[-1][0] for c in thinking53.children)
    assert "решение по шагам" in all_sent_text.lower()
    print("53. send_ai_result splits a long answer across several messages, keyboard on the last one only: OK")

    # ---- 53b. send_ai_result: a SHORT answer is still delivered exactly like before this change
    # — one edit, no extra messages, keyboard attached immediately (regression guard) ----
    thinking53b = FakeMsg(uid=uid)
    await tb.send_ai_result(thinking53b, "Короткий ответ", uid, session_active=True, offer_explanation=True)
    assert len(thinking53b.edits) == 1
    assert thinking53b.children == []
    assert thinking53b.edits[0][1] is not None, "keyboard must still be attached immediately for a single-chunk answer"
    print("53b. send_ai_result leaves short answers exactly as a single edited message: OK")

    tb.stats["ai_answer_cache"].clear()
    tb.stats["ai_usage"].pop(str(uid), None)
    tb.solve_ai_request = orig_solve

    # ==================== cleanup ====================
    tb.solve_ai_request = orig_solve
    tb.ai_vision_parser.parse_task = orig_parse_task
    tb.ai_rag.search_for_task = orig_search_for_task
    tb.ai_openai.get_client = orig_get_client
    tb.ai_xai.get_client = orig_get_grok_client
    tb.OPENAI_API_KEY = orig_key
    tb.end_ai_session(uid)
    tb.stats["ai_usage"].pop(str(uid), None)

    print("\nAll AI MVP tests passed!")

if __name__ == "__main__":
    asyncio.run(main())
