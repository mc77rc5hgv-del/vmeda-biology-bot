# -*- coding: utf-8 -*-
import asyncio
from _bootstrap import tb
from aiogram.dispatcher.event.bases import SkipHandler

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
    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self
    async def delete(self):
        self.deleted = True
    async def answer(self, text, **kwargs):
        m = FakeMsg(uid=self.from_user.id)
        m.edits.append((text, kwargs.get("reply_markup")))
        self.last_child = m
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

def fake_user_turn(text=None, image_bytes=None):
    content = []
    if text:
        content.append({"type": "text", "text": text})
    if image_bytes:
        content.append({"type": "image_url", "image_url": {"url": "fake"}})
    return {"role": "user", "content": content}

FAKE_USAGE = {"input_tokens": 1000, "output_tokens": 100}

async def main():
    uid = NON_ADMIN
    tb.stats["ai_usage"].pop(str(uid), None)
    tb.stats["ai_cost_totals"] = {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    tb.end_ai_session(uid)

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

    # ---- 4. starting a solve session opens an empty session and shows the cancel keyboard ----
    cb_start = FakeCB("ai_solve_start", uid=uid)
    await tb.cb_ai_solve_start(cb_start)
    assert tb.is_ai_session_active(uid)
    assert tb.AI_SESSIONS[uid]["messages"] == []
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

    # ---- 7. FIRST message of a session -> quick=True, short answer, offers "show solution" ----
    tb.start_ai_session(uid)
    calls = []
    async def fake_solve(*, image_bytes=None, text=None, history=None, quick=False):
        calls.append((image_bytes, text, list(history or []), quick))
        answer = "Ответ: Б" if quick else "Ответ: Б. Подробное решение по шагам: ..."
        return answer, fake_user_turn(text=text, image_bytes=image_bytes), dict(FAKE_USAGE)
    orig_solve = tb.solve_ai_request
    tb.solve_ai_request = fake_solve
    before = tb.ai_requests_left(uid)
    cost_before = tb.stats["ai_cost_totals"]["requests"]
    msg2 = FakeMsg(uid=uid, text="Реши задачу по химии")
    await tb.handle_ai_text_input(msg2)
    assert tb.is_ai_session_active(uid), "session must stay open for follow-ups after a successful answer"
    assert calls[-1] == (None, "Реши задачу по химии", [], True), "the very first message of a session must be quick=True"
    assert tb.ai_requests_left(uid) == before - 1
    assert len(tb.AI_SESSIONS[uid]["messages"]) == 2, "user turn + assistant turn must be recorded"
    final_text, final_kb = msg2.last_child.edits[-1]
    assert "Ответ: Б" in final_text
    assert f"{tb.ai_requests_left(uid)}/{tb.AI_FREE_DAILY_LIMIT}" in final_text
    assert "ai_show_explanation" in kb_data(final_kb), "a quick answer must offer the step-by-step explanation button"
    assert "ai_session_end" in kb_data(final_kb)
    assert tb.stats["ai_cost_totals"]["requests"] == cost_before + 1, "usage must be recorded into the cost totals"
    assert tb.stats["ai_cost_totals"]["input_tokens"] >= FAKE_USAGE["input_tokens"]
    print("7. first message is quick + records cost + offers explanation button: OK")

    # ---- 7b. tapping "show explanation" makes a SEPARATE detailed (quick=False) call, spends 1 more request ----
    before_explain = tb.ai_requests_left(uid)
    cb_explain = FakeCB("ai_show_explanation", uid=uid)
    await tb.cb_ai_show_explanation(cb_explain)
    assert calls[-1][3] is False, "the explanation call must be quick=False (full step-by-step)"
    assert calls[-1][1] == tb.AI_EXPLAIN_FOLLOWUP_TEXT
    assert calls[-1][2] == [
        fake_user_turn(text="Реши задачу по химии"),
        {"role": "assistant", "content": "Ответ: Б"},
    ], "the explanation call must carry the quick answer as history, so it doesn't re-explain from scratch"
    assert tb.ai_requests_left(uid) == before_explain - 1, "showing the explanation spends its own quota unit"
    assert len(tb.AI_SESSIONS[uid]["messages"]) == 4
    explain_text, explain_kb = cb_explain.message.last_child.edits[-1]
    assert "Подробное решение" in explain_text
    print("7b. explanation button makes a separate detailed request + spends quota: OK")

    # ---- 7c. a genuine follow-up typed by the user (not the button) is NOT forced quick ----
    tb.stats["ai_usage"].pop(str(uid), None)  # fresh quota room for this sub-test
    msg3 = FakeMsg(uid=uid, text="А если бы было другое вещество?")
    await tb.handle_ai_text_input(msg3)
    assert calls[-1][3] is False, "a real follow-up question the user typed must get a normal (non-quick) answer"
    print("7c. typed follow-up questions are not forced into quick mode: OK")

    # ---- 8. a photo solve round trip (mocking bot.get_file/download_file), fresh session -> quick again ----
    tb.end_ai_session(uid)
    tb.start_ai_session(uid)
    tb.stats["ai_usage"].pop(str(uid), None)
    orig_get_file = tb.bot.get_file
    orig_download_file = tb.bot.download_file
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
    assert calls[-1][0] == b"fake-jpeg-bytes" and calls[-1][1] is None and calls[-1][3] is True
    assert tb.ai_requests_left(uid) == before2 - 1
    assert "Ответ: Б" in photo_msg.last_child.edits[-1][0]
    tb.bot.get_file = orig_get_file
    tb.bot.download_file = orig_download_file
    print("8. fresh photo session is quick too: OK")

    # ---- 9. a photo sent OUTSIDE an AI session is silently ignored (no crash, nothing sent) ----
    tb.end_ai_session(uid)
    photo_msg2 = FakeMsg(uid=uid, photo=[FakePhotoSize("f3")])
    await tb.handle_ai_photo_input(photo_msg2)
    assert photo_msg2.edits == []
    print("9. photo outside AI session ignored: OK")

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
    tb.AI_SESSIONS[uid]["messages"] = [fake_user_turn(text="x"), {"role": "assistant", "content": "Ответ: А"}]
    tb.stats["ai_usage"][str(uid)] = {"date": tb.date.today().isoformat(), "count": tb.AI_FREE_DAILY_LIMIT}
    calls_before_10c = len(calls)
    cb_explain_blocked = FakeCB("ai_show_explanation", uid=uid)
    await tb.cb_ai_show_explanation(cb_explain_blocked)
    assert len(calls) == calls_before_10c, "must not call the model when quota is already exhausted"
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
    calls_before = len(calls)
    dup_msg = FakeMsg(uid=uid, text="дубль, отправлен пока обрабатывается первый")
    try:
        await tb.handle_ai_text_input(dup_msg)
        raised = False
    except SkipHandler:
        raised = True
    assert raised
    assert len(calls) == calls_before, "must not call the model while a previous message is still processing"
    print("13. concurrent duplicate message during processing is ignored: OK")

    # ---- 14. record_ai_cost math is correct and cost block renders ----
    tb.stats["ai_cost_totals"] = {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    tb.record_ai_cost({"input_tokens": 1_000_000, "output_tokens": 1_000_000})
    expected_cost = tb.AI_PRICE_INPUT_PER_1M + tb.AI_PRICE_OUTPUT_PER_1M
    assert abs(tb.stats["ai_cost_totals"]["cost_usd"] - expected_cost) < 1e-9
    block = tb.get_ai_cost_stats_block()
    assert "VMedA AI" in block and "1" in block
    print("14. record_ai_cost math + stats block: OK")

    # ---- 15. admin has unlimited AI requests, even at/over the daily quota ----
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

    # ---- 16. LaTeX cleanup: real formulas the model has actually produced, made readable ----
    raw = (
        r"\( i = 1 + 2 \cdot (0,96) = 2,92 \)."
        r" \( m = \frac{n}{m_{\text{растворителя, кг}}} \approx 0,246 \, \text{моль/кг} \)."
        r" Сульфат калия SO4^{2-} и K^{+}, \Delta T_b \approx 0,37 \, \text{°C}."
    )
    cleaned = tb._clean_ai_answer(raw)
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
    formatted = tb._format_ai_answer_html(md)
    assert "<b>Молекулярная масса:</b>" in formatted
    assert "<b>174,3 г/моль</b>" in formatted
    assert "• K: 39,1 г/моль" in formatted and "• S: 32,1 г/моль" in formatted
    assert "**" not in formatted, "no raw markdown asterisks should remain"
    checker = _BalanceChecker()
    checker.feed(formatted)
    assert checker.ok and not checker.stack, f"unbalanced HTML: {formatted!r}"

    # a stray "<"/"&" from the model must be escaped, never treated as a real tag
    unsafe = "Если n < 5, реакция не идёт (K & Na реагируют иначе)."
    formatted_unsafe = tb._format_ai_answer_html(unsafe)
    assert "&lt;" in formatted_unsafe and "&amp;" in formatted_unsafe
    checker2 = _BalanceChecker()
    checker2.feed(formatted_unsafe)
    assert checker2.ok and not checker2.stack
    print("17. markdown-to-HTML formatting is real, balanced, and escape-safe: OK")

    # cleanup
    tb.solve_ai_request = orig_solve
    tb.OPENAI_API_KEY = orig_key
    tb.end_ai_session(uid)
    tb.stats["ai_usage"].pop(str(uid), None)

    print("\nAll AI MVP tests passed!")

if __name__ == "__main__":
    asyncio.run(main())
