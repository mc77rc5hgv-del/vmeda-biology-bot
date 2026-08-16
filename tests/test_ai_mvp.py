# -*- coding: utf-8 -*-
import asyncio
from _bootstrap import tb
from aiogram.dispatcher.event.bases import SkipHandler

NON_ADMIN = 55501122

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

async def main():
    uid = NON_ADMIN
    tb.stats["ai_usage"].pop(str(uid), None)
    tb.end_ai_session(uid)

    # ---- 1. main menu always shows the AI entry point ----
    menu = tb.get_main_menu(user_id=uid)
    assert "ai_menu" in kb_data(menu), "AI button must be present in the main menu"
    assert any("VMedA AI" in t for t in kb_texts(menu))
    print("1. main menu AI button: OK")

    # ---- 2. ai_menu screen shows quota and doesn't touch any existing stats key ----
    other_keys_before = {k: v for k, v in tb.stats.items() if k != "ai_usage"}
    cb = FakeCB("ai_menu", uid=uid)
    await tb.cb_ai_menu(cb)
    text, kb = cb.message.edits[-1]
    assert f"{tb.AI_FREE_DAILY_LIMIT}/{tb.AI_FREE_DAILY_LIMIT}" in text
    assert "ai_solve_start" in kb_data(kb)
    assert {k: v for k, v in tb.stats.items() if k != "ai_usage"} == other_keys_before
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

    # ---- 7. a full text solve round trip: quota decrements, session STAYS open, answer is shown ----
    tb.start_ai_session(uid)
    calls = []
    async def fake_solve(*, image_bytes=None, text=None, history=None):
        calls.append((image_bytes, text, list(history or [])))
        return "Правильный ответ: Б", fake_user_turn(text=text, image_bytes=image_bytes)
    orig_solve = tb.solve_ai_request
    tb.solve_ai_request = fake_solve
    before = tb.ai_requests_left(uid)
    msg2 = FakeMsg(uid=uid, text="Реши задачу по химии")
    await tb.handle_ai_text_input(msg2)
    assert tb.is_ai_session_active(uid), "session must stay open for follow-ups after a successful answer"
    assert calls[-1] == (None, "Реши задачу по химии", [])
    assert tb.ai_requests_left(uid) == before - 1
    assert len(tb.AI_SESSIONS[uid]["messages"]) == 2, "user turn + assistant turn must be recorded"
    final_text, final_kb = msg2.last_child.edits[-1]
    assert "Правильный ответ: Б" in final_text
    assert f"{tb.ai_requests_left(uid)}/{tb.AI_FREE_DAILY_LIMIT}" in final_text
    assert "ai_session_end" in kb_data(final_kb), "must offer a way to end the still-open dialog"
    print("7. text solve round trip: session stays open + quota decrement: OK")

    # ---- 7b. a follow-up message (no button press!) continues the SAME session with history ----
    msg3 = FakeMsg(uid=uid, text="А теперь объясни подробнее")
    await tb.handle_ai_text_input(msg3)
    assert calls[-1][2] == [
        fake_user_turn(text="Реши задачу по химии"),
        {"role": "assistant", "content": "Правильный ответ: Б"},
    ], "the follow-up call must receive the prior exchange as history"
    assert len(tb.AI_SESSIONS[uid]["messages"]) == 4
    print("7b. follow-up text continues the dialog with memory, no button needed: OK")

    # ---- 8. a photo solve round trip (mocking bot.get_file/download_file) ----
    # reset just today's quota counter (not the session/history) so this round trip has room —
    # tests 7/7b already spent 2 of the 3 free requests in this same session.
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
    assert calls[-1][0] == b"fake-jpeg-bytes" and calls[-1][1] is None
    assert tb.ai_requests_left(uid) == before2 - 1
    assert "Правильный ответ: Б" in photo_msg.last_child.edits[-1][0]
    tb.bot.get_file = orig_get_file
    tb.bot.download_file = orig_download_file
    print("8. photo follow-up within the same session: OK")

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

    # ---- 10b. exhausting the quota MID-dialog auto-closes the session with a plain back button ----
    tb.stats["ai_usage"].pop(str(uid), None)
    tb.start_ai_session(uid)
    tb.stats["ai_usage"][str(uid)] = {"date": tb.date.today().isoformat(), "count": tb.AI_FREE_DAILY_LIMIT - 1}
    msg_last = FakeMsg(uid=uid, text="Последний бесплатный вопрос")
    await tb.handle_ai_text_input(msg_last)
    assert not tb.is_ai_session_active(uid), "session must auto-close once the daily quota hits 0"
    last_text, last_kb = msg_last.last_child.edits[-1]
    assert "ai_session_end" not in kb_data(last_kb)
    assert "ai_menu" in kb_data(last_kb)
    print("10b. quota hitting 0 mid-dialog auto-closes the session: OK")
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

    # cleanup
    tb.solve_ai_request = orig_solve
    tb.OPENAI_API_KEY = orig_key
    tb.end_ai_session(uid)
    tb.stats["ai_usage"].pop(str(uid), None)

    print("\nAll AI MVP tests passed!")

if __name__ == "__main__":
    asyncio.run(main())
