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
    task_type_calls = []
    rag_context_calls = []
    async def fake_solve(*, image_bytes=None, text=None, history=None, quick=False, task_type=None, rag_context=None):
        calls.append((image_bytes, text, list(history or []), quick))
        task_type_calls.append(task_type)
        rag_context_calls.append(rag_context)
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

    # regression: "### Заголовок" (Gemini uses these despite the system prompt saying not to)
    # must not leak as raw "###" into the Telegram message
    md_headers = "### 1. Брюшина\n• Определение: передняя стенка брюшной полости."
    formatted_headers = tb._format_ai_answer_html(md_headers)
    assert "#" not in formatted_headers, "raw markdown headers must not leak into the message"
    assert "<b>1. Брюшина</b>" in formatted_headers
    checker3 = _BalanceChecker()
    checker3.feed(formatted_headers)
    assert checker3.ok and not checker3.stack
    print("17. markdown-to-HTML formatting is real, balanced, and escape-safe: OK")

    # ---- 18. the REAL solve_ai_request compacts history before resending (cost-runaway guard) ----
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
    captured = {}
    class FakeCompletions:
        async def create(self, **kwargs):
            captured["messages"] = kwargs["messages"]
            return FakeOpenAIResponse()
    class FakeChat:
        completions = FakeCompletions()
    class FakeOpenAIClient:
        chat = FakeChat()

    orig_get_client = tb.get_openai_client
    orig_get_grok_client = tb.get_grok_client
    tb.get_openai_client = lambda: FakeOpenAIClient()
    tb.get_grok_client = lambda: None  # Grok не настроен в этом под-тесте — чистая проверка сжатия истории
    long_answer = "Подробный ход решения. " * 30  # заведомо длиннее AI_HISTORY_SUMMARY_CHARS
    long_history = []
    for i in range(20):
        if i % 2 == 0:
            content = [{"type": "text", "text": f"вопрос {i}"}]
            if i == 16:  # внутри окна AI_HISTORY_MAX_MESSAGES — проверяем, что фото тут вырезается
                content.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}})
            long_history.append({"role": "user", "content": content})
        else:
            long_history.append({"role": "assistant", "content": long_answer + f" #{i}"})

    answer_r, user_turn_r, usage_r = await orig_solve(text="новый вопрос", history=long_history)
    sent = captured["messages"]
    assert sent[0]["role"] == "system"
    assert len(sent) == 1 + tb.AI_HISTORY_MAX_MESSAGES + 1, "must be system + compacted history + current turn"
    compacted = sent[1:-1]
    assert sent[-1] == user_turn_r

    # ни один сохранённый ход истории, КРОМЕ самого последнего пользовательского, не тащит
    # картинку — самое дорогое по входным токенам. Последний пользовательский ход (вопрос 18,
    # без фото в этом тесте) намеренно проходит без изменений — см. тест 18b для случая, когда у
    # него ЕСТЬ фото.
    user_msgs_all = [m for m in compacted if m["role"] == "user"]
    older_user_msgs = user_msgs_all[:-1]
    for msg in older_user_msgs:
        content = msg["content"]
        assert isinstance(content, str), "older history entries must be compacted to plain text"
        assert "image_url" not in content and "base64" not in content

    older_texts = [m["content"] for m in older_user_msgs]
    assert any("вопрос 16" in c and "[ранее приложено фото задания]" in c for c in older_texts), (
        "an OLDER user turn that had an image must keep a short text marker instead"
    )
    assert any(c == "вопрос 14" for c in older_texts), "user turns without an image are passed through as-is"

    for msg in compacted:
        if msg["role"] == "assistant":
            assert "image_url" not in msg["content"] and "base64" not in msg["content"]

    # самый последний ответ ассистента в окне остаётся полным (может понадобиться модели целиком),
    # более ранние в этом же окне — обрезаны до AI_HISTORY_SUMMARY_CHARS
    assistant_msgs = [m["content"] for m in compacted if m["role"] == "assistant"]
    assert len(assistant_msgs) >= 2
    assert assistant_msgs[-1] == long_answer + " #19"
    for shortened in assistant_msgs[:-1]:
        assert len(shortened) <= tb.AI_HISTORY_SUMMARY_CHARS + 1
        assert shortened.endswith("…")

    assert usage_r == {"input_tokens": 42, "output_tokens": 7, "provider": "openai"}
    print("18. long history is compacted (images stripped, old answers shortened) before resending: OK")

    # ---- 18b. the MOST RECENT user turn's photo must survive compaction (regression guard) ----
    # "Показать решение" and typed follow-ups never resend the photo themselves — they rely on
    # it still being in history for the round being explained. Stripping it there made the model
    # answer "не вижу фото задания" instead of solving.
    history_with_recent_photo = [
        {"role": "user", "content": [
            {"type": "text", "text": "старый вопрос"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,OLD"}},
        ]},
        {"role": "assistant", "content": "старый ответ " * 20},
        {"role": "user", "content": [
            {"type": "text", "text": ""},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,RECENT"}},
        ]},
        {"role": "assistant", "content": "Краткий ответ на свежее фото"},
    ]
    compacted_recent = tb._compact_history(history_with_recent_photo)
    user_msgs_recent = [m for m in compacted_recent if m["role"] == "user"]
    assert isinstance(user_msgs_recent[-1]["content"], list), "the most recent user turn's photo must stay intact"
    assert any(p.get("type") == "image_url" for p in user_msgs_recent[-1]["content"])
    assert isinstance(user_msgs_recent[0]["content"], str), "an OLDER user turn's photo must still be stripped"
    assert "RECENT" not in str(user_msgs_recent[0]) and "image_url" not in str(user_msgs_recent[0])
    print("18b. most recent user turn keeps its photo intact, older ones still stripped: OK")

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

    tb.get_openai_client = lambda: FakeOpenAIClient19()
    tb.get_grok_client = lambda: GrokMustNotBeCalledClient()
    answer19, _, usage19 = await orig_solve(text="краткий вопрос", quick=True)
    assert captured19["model"] == tb.AI_MODEL_VISION
    assert usage19["provider"] == "openai"
    print("19. quick=True always stays on OpenAI, even with Grok configured: OK")

    # ---- 19a. by default (AI_USE_GROK_FOR_DETAILED=False) quick=False ALSO stays on OpenAI —
    # Grok's routing is fully wired but switched off, since a different model answering the
    # detailed explanation than the quick answer could round a multi-step calculation slightly
    # differently within the SAME session (e.g. 100,5°C vs 100,4°C on the same problem) ----
    assert tb.AI_USE_GROK_FOR_DETAILED is False, "Grok routing for detailed answers must default to off"
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
            raise AssertionError("Grok must not be called while AI_USE_GROK_FOR_DETAILED is off")
    class GrokMustNotBeCalledChat19a:
        completions = GrokMustNotBeCalledCompletions19a()
    class GrokMustNotBeCalledClient19a:
        chat = GrokMustNotBeCalledChat19a()
    tb.get_openai_client = lambda: FakeOpenAIClient19a()
    tb.get_grok_client = lambda: GrokMustNotBeCalledClient19a()
    _, _, usage19a = await orig_solve(text="подробный вопрос", quick=False)
    assert captured19a["model"] == tb.AI_MODEL_VISION
    assert usage19a["provider"] == "openai"
    print("19a. by default, quick=False also stays on OpenAI — Grok wired but switched off: OK")

    # ---- 19b. with AI_USE_GROK_FOR_DETAILED explicitly on, quick=False routes to Grok ----
    tb.AI_USE_GROK_FOR_DETAILED = True
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

    tb.get_grok_client = lambda: FakeGrokClient()
    tb.get_openai_client = lambda: OpenAIMustNotBeCalledClient()
    tb.stats["ai_cost_totals"] = {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    answer_g, user_turn_g, usage_g = await orig_solve(text="подробный вопрос", quick=False)
    assert captured_grok["model"] == tb.AI_MODEL_GROK
    assert usage_g == {"input_tokens": 300, "output_tokens": 120, "provider": "grok"}
    tb.record_ai_cost(usage_g)
    grok_totals = tb.stats["ai_cost_totals"]["by_provider"]["grok"]
    expected_cost = (
        300 * tb.AI_GROK_PRICE_INPUT_PER_1M / 1_000_000 + 120 * tb.AI_GROK_PRICE_OUTPUT_PER_1M / 1_000_000
    )
    assert grok_totals["requests"] == 1
    assert abs(grok_totals["cost_usd"] - expected_cost) < 1e-9, "Grok usage must be priced at Grok's own rates"
    assert "из них Grok" in tb.get_ai_cost_stats_block(), "admin stats must break out Grok spend separately"
    print("19b. quick=False routes to Grok when configured, priced at Grok rates: OK")

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

    tb.get_grok_client = lambda: FailingGrokClient()
    tb.get_openai_client = lambda: FallbackOpenAIClient()
    answer_f, user_turn_f, usage_f = await orig_solve(text="подробный вопрос 2", quick=False)
    assert len(grok_call_count) == 1, "must attempt Grok exactly once — not loop or retry it"
    assert fallback_models == [tb.AI_MODEL_VISION], "must fall back to OpenAI exactly once after the Grok failure"
    assert usage_f["provider"] == "openai", "usage must be attributed to whichever provider actually answered"
    print("19c. Grok failure falls back to OpenAI exactly once, no retry loop: OK")

    tb.get_openai_client = orig_get_client
    tb.get_grok_client = orig_get_grok_client
    tb.AI_USE_GROK_FOR_DETAILED = False

    # ---- 20. photos are sent at "detail": "low" — gpt-4o-mini bills high/auto detail at up to
    # 36 835 tokens per photo (2833 base + 5667 per 512px tile) vs a flat 2833 at low, by far the
    # single biggest cost lever in the whole feature (much bigger than history compaction) ----
    captured20 = {}
    class FakeCompletions20:
        async def create(self, **kwargs):
            captured20["messages"] = kwargs["messages"]
            return FakeOpenAIResponse()
    class FakeChat20:
        completions = FakeCompletions20()
    class FakeOpenAIClient20:
        chat = FakeChat20()
    tb.get_openai_client = lambda: FakeOpenAIClient20()
    tb.get_grok_client = lambda: None
    await orig_solve(image_bytes=b"fake-jpeg-bytes", quick=True)
    sent_user_turn = captured20["messages"][-1]
    image_block = next(p for p in sent_user_turn["content"] if p["type"] == "image_url")
    assert image_block["image_url"]["detail"] == tb.AI_IMAGE_DETAIL == "low"
    print("20. photos are sent at detail=low to cut the dominant image-token cost: OK")

    tb.get_openai_client = orig_get_client
    tb.get_grok_client = orig_get_grok_client

    # ---- 21. _classify_quick_answer: cheap heuristic that gates Gemini eligibility ----
    assert tb._classify_quick_answer("Ответ: Б") == "theory"
    assert tb._classify_quick_answer("3) Верно") == "theory"
    assert tb._classify_quick_answer("Ответ: В") == "theory"
    assert tb._classify_quick_answer("Температура кипения раствора составляет 100,5°C.") == "problem"
    assert tb._classify_quick_answer("Масса вещества ≈ 42 г") == "problem"
    assert tb._classify_quick_answer("pH раствора равен 3,2") == "problem"
    # многопунктный список (3+ пунктов) остаётся на OpenAI целиком НЕЗАВИСИМО от содержимого —
    # по реальным наблюдениям Gemini на таком контенте путает термины ("Плева" вместо "Плевра")
    # и даёт более куцые формулировки, чем OpenAI на том же вопросе
    numbered_list_answer = (
        "9. Грудная полость — пространство, в котором находятся лёгкие и сердце.\n"
        "10. Забрюшинное пространство — область за брюшиной, содержащая жировую ткань и сосуды.\n"
        "11. Полость малого таза — пространство, в котором находятся органы мочеполовой системы.\n"
        "12. Промежность — область между анусом и половыми органами.\n"
        "13. Семенной каналикул — трубочки в яичках, где происходит сперматогенез."
    )
    assert tb._classify_quick_answer(numbered_list_answer) == "problem", (
        "a multi-item (3+) list must stay on OpenAI regardless of content — Gemini was observed "
        "to be less accurate/terser on this kind of answer"
    )
    # регрессия отдельно: номер пункта САМ ПО СЕБЕ (не число-результат) не должен путать
    # классификатор даже в КОРОТКОМ списке (< 3 пунктов, не задета правилом выше)
    short_list_no_numbers = "9. Грудная полость — пространство, в котором находятся лёгкие и сердце."
    assert tb._classify_quick_answer(short_list_no_numbers) == "theory", (
        "list-item numbering (\"9.\") alone must not be mistaken for a calculated result"
    )
    # но реальное число-результат СРЕДИ пунктов короткого списка всё ещё должно быть "problem"
    short_list_with_number = "1. Первый пункт\n2. Масса раствора составляет 15,7 г"
    assert tb._classify_quick_answer(short_list_with_number) == "problem"
    print("21. _classify_quick_answer tells theory/test answers from calculated ones: OK")

    # ---- 22. _openai_messages_to_gemini_contents: system extracted, roles mapped, images converted ----
    openai_style_messages = [
        {"role": "system", "content": "СИСТЕМНЫЙ ПРОМПТ"},
        {"role": "user", "content": "старый текстовый вопрос"},
        {"role": "assistant", "content": "старый ответ"},
        {"role": "user", "content": [
            {"type": "text", "text": "новый вопрос"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD", "detail": "low"}},
        ]},
    ]
    system_text, contents = tb._openai_messages_to_gemini_contents(openai_style_messages)
    assert system_text == "СИСТЕМНЫЙ ПРОМПТ"
    assert [c["role"] for c in contents] == ["user", "model", "user"], "assistant maps to model, system is separate"
    assert contents[0]["parts"] == [{"text": "старый текстовый вопрос"}]
    assert contents[1]["parts"] == [{"text": "старый ответ"}]
    last_parts = contents[2]["parts"]
    assert {"text": "новый вопрос"} in last_parts
    image_part = next(p for p in last_parts if "inline_data" in p)
    assert image_part["inline_data"] == {"mime_type": "image/jpeg", "data": "QUJD"}
    print("22. _openai_messages_to_gemini_contents converts roles/system/images correctly: OK")

    # ---- 23. task_type is classified from the quick answer's shape and passed through to the
    # detailed explanation call — this is what lets solve_ai_request route theory/test questions
    # to Gemini while calc problems stay on OpenAI ----
    tb.end_ai_session(uid)
    tb.start_ai_session(uid)
    tb.stats["ai_usage"].pop(str(uid), None)
    task_type_calls.clear()
    msg23 = FakeMsg(uid=uid, text="Что такое диффузия?")
    await tb.handle_ai_text_input(msg23)  # fake_solve's quick answer is the bare-letter "Ответ: Б"
    assert tb.AI_SESSIONS[uid]["task_type"] == "theory", "a bare-letter quick answer must classify as theory"
    cb_explain23 = FakeCB("ai_show_explanation", uid=uid)
    await tb.cb_ai_show_explanation(cb_explain23)
    assert task_type_calls[-1] == "theory", "the detailed call must receive the classified task_type"
    print("23. task_type is classified from the quick answer and passed to the detailed call: OK")
    tb.stats["ai_usage"].pop(str(uid), None)

    # ---- 24. the REAL solve_ai_request: quick=False + task_type="theory" + GEMINI_API_KEY set
    # routes to Gemini, priced at Gemini's own (cheaper) rates ----
    orig_gemini_key = tb.GEMINI_API_KEY
    tb.GEMINI_API_KEY = "fake-gemini-key-for-tests"
    gemini_calls = []
    async def fake_call_gemini_success(messages, max_tokens):
        gemini_calls.append((messages, max_tokens))
        return "Правильный вариант: В (эволюционная теория)", {"input_tokens": 150, "output_tokens": 40}
    orig_call_gemini = tb._call_gemini
    tb._call_gemini = fake_call_gemini_success
    class OpenAIMustNotBeCalledCompletions24:
        async def create(self, **kwargs):
            raise AssertionError("OpenAI must not be called when Gemini handles a theory question")
    class OpenAIMustNotBeCalledChat24:
        completions = OpenAIMustNotBeCalledCompletions24()
    class OpenAIMustNotBeCalledClient24:
        chat = OpenAIMustNotBeCalledChat24()
    tb.get_openai_client = lambda: OpenAIMustNotBeCalledClient24()
    tb.stats["ai_cost_totals"] = {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    answer_th, _, usage_th = await orig_solve(text="теоретический вопрос", quick=False, task_type="theory")
    assert usage_th == {"input_tokens": 150, "output_tokens": 40, "provider": "gemini"}
    assert len(gemini_calls) == 1
    tb.record_ai_cost(usage_th)
    gemini_totals = tb.stats["ai_cost_totals"]["by_provider"]["gemini"]
    expected_cost_gemini = (
        150 * tb.AI_GEMINI_PRICE_INPUT_PER_1M / 1_000_000 + 40 * tb.AI_GEMINI_PRICE_OUTPUT_PER_1M / 1_000_000
    )
    assert abs(gemini_totals["cost_usd"] - expected_cost_gemini) < 1e-9, "Gemini usage must be priced at Gemini rates"
    assert "из них Gemini" in tb.get_ai_cost_stats_block(), "admin stats must break out Gemini spend separately"
    print("24. quick=False + task_type=theory + GEMINI_API_KEY routes to Gemini, priced correctly: OK")

    # ---- 24b. task_type="theory" but NO GEMINI_API_KEY still stays on OpenAI ----
    tb.GEMINI_API_KEY = None
    captured24b = {}
    class FakeCompletions24b:
        async def create(self, **kwargs):
            captured24b["model"] = kwargs["model"]
            return FakeOpenAIResponse()
    class FakeChat24b:
        completions = FakeCompletions24b()
    class FakeOpenAIClient24b:
        chat = FakeChat24b()
    tb.get_openai_client = lambda: FakeOpenAIClient24b()
    gemini_calls.clear()
    _, _, usage_24b = await orig_solve(text="теоретический вопрос", quick=False, task_type="theory")
    assert len(gemini_calls) == 0, "must not call Gemini when GEMINI_API_KEY is unset"
    assert usage_24b["provider"] == "openai"
    assert captured24b["model"] == tb.AI_MODEL_VISION
    print("24b. task_type=theory without GEMINI_API_KEY still stays on OpenAI: OK")
    tb.GEMINI_API_KEY = "fake-gemini-key-for-tests"

    # ---- 24c. task_type="problem" stays on OpenAI even when Gemini IS configured — this is the
    # self-consistency guarantee for calculations ----
    captured24c = {}
    class FakeCompletions24c:
        async def create(self, **kwargs):
            captured24c["model"] = kwargs["model"]
            return FakeOpenAIResponse()
    class FakeChat24c:
        completions = FakeCompletions24c()
    class FakeOpenAIClient24c:
        chat = FakeChat24c()
    tb.get_openai_client = lambda: FakeOpenAIClient24c()
    gemini_calls.clear()
    _, _, usage_24c = await orig_solve(text="расчётная задача", quick=False, task_type="problem")
    assert len(gemini_calls) == 0, "calculation problems must never be routed to Gemini"
    assert usage_24c["provider"] == "openai"
    print("24c. task_type=problem stays on OpenAI even when Gemini is configured: OK")

    # ---- 24d. Gemini failing falls back to OpenAI exactly once — no retry loop ----
    async def fake_call_gemini_failing(messages, max_tokens):
        gemini_calls.append((messages, max_tokens))
        raise RuntimeError("simulated Gemini outage")
    tb._call_gemini = fake_call_gemini_failing
    fallback_models_24d = []
    class FallbackCompletions24d:
        async def create(self, **kwargs):
            fallback_models_24d.append(kwargs["model"])
            return FakeOpenAIResponse()
    class FallbackChat24d:
        completions = FallbackCompletions24d()
    class FallbackOpenAIClient24d:
        chat = FallbackChat24d()
    tb.get_openai_client = lambda: FallbackOpenAIClient24d()
    gemini_calls.clear()
    _, _, usage_24d = await orig_solve(text="теоретический вопрос 2", quick=False, task_type="theory")
    assert len(gemini_calls) == 1, "must attempt Gemini exactly once — not loop or retry it"
    assert fallback_models_24d == [tb.AI_MODEL_VISION], "must fall back to OpenAI exactly once after Gemini fails"
    assert usage_24d["provider"] == "openai"
    print("24d. Gemini failure falls back to OpenAI exactly once, no retry loop: OK")

    tb._call_gemini = orig_call_gemini
    tb.get_openai_client = orig_get_client
    tb.GEMINI_API_KEY = orig_gemini_key

    # ---- 25. AI RAG: builds a searchable index from the bot's own Q&A banks (Biology/Physics/
    # Chemistry only — matches the AI feature's stated scope) and retrieves relevant snippets by
    # keyword overlap, all zero-token pure Python (no model call for retrieval itself) ----
    orig_questions, orig_physics_q = tb.QUESTIONS, tb.PHYSICS_QUESTIONS
    orig_chem_theory = tb.CHEMISTRY_THEORY
    orig_chem_theory_tickets, orig_chem_practice_tickets = tb.CHEMISTRY_THEORY_TICKETS, tb.CHEMISTRY_PRACTICE_TICKETS
    tb.QUESTIONS = {"1": {
        "title": "Митохондрии и клеточное дыхание",
        "answer": "Митохондрии — органоиды клеточного дыхания, синтезируют АТФ путём окисления органических веществ.",
    }}
    tb.PHYSICS_QUESTIONS = {"1": {
        "title": "Закон Ома для участка цепи",
        "answer": "Сила тока прямо пропорциональна напряжению и обратно пропорциональна сопротивлению участка цепи.",
    }}
    tb.CHEMISTRY_THEORY = {"1": {
        "title": "Окислительно-восстановительные реакции",
        "content": "ОВР — реакции с переносом электронов между окислителем и восстановителем.",
    }}
    tb.CHEMISTRY_THEORY_TICKETS = {}
    tb.CHEMISTRY_PRACTICE_TICKETS = {}
    index = tb._build_ai_rag_index()
    assert any(e["subject"] == "биология" and "Митохондрии" in e["title"] for e in index)
    assert any(e["subject"] == "физика" and "Ома" in e["title"] for e in index)
    assert any(e["subject"] == "химия" and "восстановительные" in e["title"] for e in index)

    orig_get_index = tb.get_ai_rag_index
    tb.get_ai_rag_index = lambda: index
    snippets = tb._search_ai_rag_snippets("расскажи про митохондрии и клеточное дыхание в клетке")
    assert snippets and snippets[0]["title"] == "Митохондрии и клеточное дыхание"
    no_match = tb._search_ai_rag_snippets("совершенно не связанный запрос про космос и звёзды")
    assert no_match == [], "must not return noisy single-word-overlap matches (AI_RAG_MIN_SCORE gate)"
    context = tb._format_ai_rag_context(snippets)
    assert "Митохондрии и клеточное дыхание" in context and "биология" in context
    assert tb._format_ai_rag_context([]) == "", "no snippets -> empty context, no wasted tokens"
    print("25. AI RAG index build + keyword retrieval + formatting: OK")

    tb.get_ai_rag_index = orig_get_index
    tb.QUESTIONS, tb.PHYSICS_QUESTIONS = orig_questions, orig_physics_q
    tb.CHEMISTRY_THEORY = orig_chem_theory
    tb.CHEMISTRY_THEORY_TICKETS, tb.CHEMISTRY_PRACTICE_TICKETS = orig_chem_theory_tickets, orig_chem_practice_tickets

    # ---- 26. the REAL solve_ai_request: rag_context reaches the model on quick=False, but is
    # NEVER baked into the returned/stored user_turn — otherwise it would resend itself (and its
    # own token cost) on every future turn of the session, same class of bug as the photo/history
    # cost-runaway fixed earlier ----
    captured26 = {}
    class FakeCompletions26:
        async def create(self, **kwargs):
            captured26["messages"] = kwargs["messages"]
            return FakeOpenAIResponse()
    class FakeChat26:
        completions = FakeCompletions26()
    class FakeOpenAIClient26:
        chat = FakeChat26()
    tb.get_openai_client = lambda: FakeOpenAIClient26()
    tb.get_grok_client = lambda: None
    fake_rag_context = "Материалы ВМедА по теме: «Пример» (биология): много текста сюда для проверки."

    _, user_turn_26, _ = await orig_solve(text="объясни подробнее", quick=False, rag_context=fake_rag_context)
    sent_text = captured26["messages"][-1]["content"][0]["text"]
    assert fake_rag_context in sent_text, "rag_context must reach the model"
    stored_text = user_turn_26["content"][0]["text"]
    assert fake_rag_context not in stored_text, "rag_context must NOT be baked into the stored user_turn"
    assert stored_text == "объясни подробнее"
    print("26. rag_context reaches the model but never gets baked into stored history: OK")

    _, user_turn_26b, _ = await orig_solve(text="краткий вопрос", quick=True, rag_context=fake_rag_context)
    sent_text_quick = captured26["messages"][-1]["content"][0]["text"]
    assert fake_rag_context not in sent_text_quick, "rag_context must be ignored on quick=True calls"
    print("26b. rag_context is ignored on quick=True (short answers stay lean): OK")

    tb.get_openai_client = orig_get_client
    tb.get_grok_client = orig_get_grok_client

    # ---- 27. _looks_like_ai_refusal: detects real refusal phrasing, not "не может"-style facts ----
    assert tb._looks_like_ai_refusal("Извините, но я не могу помочь с этой просьбой.")
    assert tb._looks_like_ai_refusal("I'm sorry, but I can't help with that request.")
    assert not tb._looks_like_ai_refusal("Молекула не может изменить свою конформацию без затрат энергии.")
    assert not tb._looks_like_ai_refusal("Ответ: Б")
    assert not tb._looks_like_ai_refusal("Температура кипения раствора составляет 100,378°C.")
    print("27. _looks_like_ai_refusal flags real refusals, not 3rd-person facts: OK")

    # ---- 28. the REAL solve_ai_request: a refusal from the primary (already-openai) provider
    # raises AIRefusalError instead of being silently shown as a normal answer ----
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
    tb.get_openai_client = lambda: RefusingOpenAIClient()
    tb.get_grok_client = lambda: None
    try:
        await orig_solve(text="анатомический вопрос", quick=False)
        raised = False
    except tb.AIRefusalError:
        raised = True
    assert raised, "a refusal from OpenAI (no further fallback) must raise AIRefusalError"
    print("28. OpenAI refusal (no further fallback available) raises AIRefusalError: OK")

    # ---- 28b. a refusal from Grok falls back to OpenAI once; if OpenAI then answers normally,
    # the caller gets a normal answer, not an error ----
    tb.AI_USE_GROK_FOR_DETAILED = True
    class GrokRefusalCompletions:
        async def create(self, **kwargs):
            return RefusalResponse()
    class GrokRefusalChat:
        completions = GrokRefusalCompletions()
    class GrokRefusalClient:
        chat = GrokRefusalChat()
    fallback_calls_28b = []
    class GoodFallbackCompletions28b:
        async def create(self, **kwargs):
            fallback_calls_28b.append(kwargs["model"])
            return FakeOpenAIResponse()
    class GoodFallbackChat28b:
        completions = GoodFallbackCompletions28b()
    class GoodFallbackClient28b:
        chat = GoodFallbackChat28b()
    tb.get_grok_client = lambda: GrokRefusalClient()
    tb.get_openai_client = lambda: GoodFallbackClient28b()
    _, _, usage_28b = await orig_solve(text="анатомический вопрос", quick=False)
    assert len(fallback_calls_28b) == 1, "must fall back to OpenAI exactly once after Grok refuses"
    assert usage_28b["provider"] == "openai"
    print("28b. Grok refusal falls back to OpenAI once, which then answers normally: OK")

    # ---- 28c. if BOTH the primary provider and the OpenAI fallback refuse, AIRefusalError still
    # propagates — exactly 2 attempts total, no infinite retry loop ----
    class BadFallbackCompletions28c:
        async def create(self, **kwargs):
            return RefusalResponse()
    class BadFallbackChat28c:
        completions = BadFallbackCompletions28c()
    class BadFallbackClient28c:
        chat = BadFallbackChat28c()
    tb.get_grok_client = lambda: GrokRefusalClient()
    tb.get_openai_client = lambda: BadFallbackClient28c()
    try:
        await orig_solve(text="анатомический вопрос", quick=False)
        raised28c = False
    except tb.AIRefusalError:
        raised28c = True
    assert raised28c, "must still raise AIRefusalError if even the OpenAI fallback refuses"
    print("28c. both primary and fallback refusing still raises AIRefusalError, no loop: OK")
    tb.AI_USE_GROK_FOR_DETAILED = False
    tb.get_openai_client = orig_get_client
    tb.get_grok_client = orig_get_grok_client

    # ---- 29. handler level: AIRefusalError shows a clear message, does NOT charge the daily
    # quota, and leaves the session alive so the user can rephrase and retry ----
    tb.end_ai_session(uid)
    tb.start_ai_session(uid)
    tb.stats["ai_usage"].pop(str(uid), None)
    async def refusing_solve(**kwargs):
        raise tb.AIRefusalError("simulated content-filter refusal")
    tb.solve_ai_request = refusing_solve
    before29 = tb.ai_requests_left(uid)
    msg29 = FakeMsg(uid=uid, text="анатомический вопрос про промежность")
    await tb.handle_ai_text_input(msg29)
    assert tb.ai_requests_left(uid) == before29, "a refused attempt must not spend the daily quota"
    assert tb.is_ai_session_active(uid), "session must stay open so the user can rephrase"
    assert tb.AI_SESSIONS[uid]["messages"] == [], "a refused attempt must not be recorded into history"
    final_text29 = msg29.last_child.edits[-1][0]
    assert "фильтр" in final_text29
    print("29. AIRefusalError shows a clear message, doesn't charge quota, session stays alive: OK")
    tb.solve_ai_request = fake_solve
    tb.stats["ai_usage"].pop(str(uid), None)

    # ---- 30. RAG regression: the actual reported anatomy question no longer pulls in the OLD
    # noisy false-positive biology matches (respiratory-organ-evolution content for a body-cavity
    # anatomy list) — and now that ANATOMY is indexed too, it should instead ground on genuinely
    # relevant anatomy material, with the correct spelling of terms the model got wrong live
    # ("Плева"/"Брыжжа" instead of "Плевра"/"Брюшина") ----
    anatomy_regression_query = (
        "Перикард — серозная оболочка сердца. Полость перикарда — пространство между слоями "
        "перикарда. Средостение — пространство между лёгкими. Грудная полость — пространство, в "
        "котором находятся лёгкие и сердце. Забрюшинное пространство — область за брюшиной, "
        "содержащая жировую ткань и сосуды. Полость малого таза — пространство, в котором "
        "находятся органы мочеполовой системы. Промежность — область между анусом и половыми "
        "органами. Семенной каналикул — трубочки в яичках, где происходит сперматогенез."
    )
    anatomy_matches = tb._search_ai_rag_snippets(anatomy_regression_query)
    matched_titles = {s["title"] for s in anatomy_matches}
    assert "Эволюция органов дыхания у беспозвоночных (Типы Annelides, Mollusca, Arthropoda)" not in matched_titles
    assert "Гисто- и органогенез. Производные зародышевых листков" not in matched_titles
    assert anatomy_matches, "the reported real anatomy question should now ground on real anatomy material"
    assert all(s["subject"] == "анатомия" for s in anatomy_matches)
    print("30. RAG drops the old noisy biology matches and grounds anatomy questions on ANATOMY: OK")

    # ---- 30b. RAG index now also covers Anatomy (real material + flashcards from ANATOMY) ----
    idx = tb.get_ai_rag_index()
    assert any(e["subject"] == "анатомия" for e in idx), "ANATOMY must be part of the RAG index"
    pleura_snippets = tb._search_ai_rag_snippets("Что такое плевра, средостение и полость плевры?")
    assert any("плевр" in s["title"].lower() or "плевр" in s["text"].lower() for s in pleura_snippets), (
        "a focused anatomy question must ground on real anatomy content with the correct term spelling"
    )
    print("30b. RAG index includes real Anatomy material/flashcards and grounds focused questions: OK")

    # ---- 30c. RAG regression: _search_ai_rag_snippets_multi finds matches for a REAL-shaped
    # numbered list (one item per line, the actual quick-answer format the bot generates) where a
    # single-blob search over the whole 13-item list finds NOTHING — this was the live bug: the
    # model still wrote "Плева" instead of "Плевра" because no grounding material ever got hit ----
    numbered_anatomy_list = (
        "1. Брюшина — складка брюшины, соединяющая органы с задней стенкой живота.\n"
        "2. Полость брюшины — пространство между стенками брюшной полости и органами.\n"
        "3. Брюшная полость — часть тела, содержащая органы пищеварения, печени, селезёнки и почек.\n"
        "4. Плевра — серозная оболочка, покрывающая легкие и внутреннюю поверхность грудной клетки.\n"
        "5. Полость плевры — пространство между листками плевры, заполненное плевральной жидкостью.\n"
        "6. Перикард — серозная оболочка, окружающая сердце.\n"
        "7. Полость перикарда — пространство между слоями перикарда, содержащая перикардиальную жидкость.\n"
        "8. Средостение — пространство между легкими, содержащее сердце, трахею и другие структуры.\n"
        "9. Грудная полость — часть тела, содержащая легкие и сердце.\n"
        "10. Забрюшинное пространство — область, расположенная за брюшной полостью.\n"
        "11. Полость малого таза — пространство, содержащее органы мочеполовой системы и прямую кишку.\n"
        "12. Промежность — область между анусом и половыми органами.\n"
        "13. Семенной каналикул — трубочки в яичках, где происходит образование сперматозоидов."
    )
    assert tb._search_ai_rag_snippets(numbered_anatomy_list) == [], (
        "sanity check: the whole 13-item blob as ONE query is too diffuse to match anything — "
        "this is exactly the live bug, confirming the per-item fix below is actually needed"
    )
    multi_matches = tb._search_ai_rag_snippets_multi(numbered_anatomy_list)
    assert multi_matches, "searching each list item separately must find real anatomy grounding"
    assert all(s["subject"] == "анатомия" for s in multi_matches)
    matched_blob = " ".join(s["title"] + " " + s["text"] for s in multi_matches).lower()
    assert "плевр" in matched_blob, "must ground the pleura term specifically (the one the model got wrong live)"
    print("30c. _search_ai_rag_snippets_multi finds per-item matches a single blob query misses: OK")

    # cleanup
    tb.solve_ai_request = orig_solve
    tb.OPENAI_API_KEY = orig_key
    tb.end_ai_session(uid)
    tb.stats["ai_usage"].pop(str(uid), None)

    print("\nAll AI MVP tests passed!")

if __name__ == "__main__":
    asyncio.run(main())
