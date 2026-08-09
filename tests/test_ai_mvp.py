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

async def main():
    uid = NON_ADMIN
    tb.stats["ai_usage"].pop(str(uid), None)
    tb.AI_PENDING.discard(uid)

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

    # ---- 3. without OPENAI_API_KEY, solve_ai_request blocks with a clear error, not a crash ----
    orig_key = tb.OPENAI_API_KEY
    tb.OPENAI_API_KEY = None
    cb_no_key = FakeCB("ai_solve_start", uid=uid)
    await tb.cb_ai_solve_start(cb_no_key)
    assert uid not in tb.AI_PENDING
    assert cb_no_key._answers and cb_no_key._answers[0][1] is True  # show_alert
    print("3. AI unavailable without API key: OK")
    tb.OPENAI_API_KEY = "fake-key-for-tests"

    # ---- 4. starting a solve session sets AI_PENDING and shows the cancel keyboard ----
    cb_start = FakeCB("ai_solve_start", uid=uid)
    await tb.cb_ai_solve_start(cb_start)
    assert uid in tb.AI_PENDING
    text, kb = cb_start.message.edits[-1]
    assert "ai_solve_cancel" in kb_data(kb)
    print("4. ai_solve_start sets AI_PENDING: OK")

    # ---- 5. cancel clears AI_PENDING and returns to the menu ----
    cb_cancel = FakeCB("ai_solve_cancel", uid=uid)
    await tb.cb_ai_solve_cancel(cb_cancel)
    assert uid not in tb.AI_PENDING
    print("5. ai_solve_cancel clears AI_PENDING: OK")

    # ---- 6. text message from a user NOT in AI_PENDING must not be swallowed (SkipHandler) ----
    msg = FakeMsg(uid=uid, text="некоторый обычный текст")
    try:
        await tb.handle_ai_text_input(msg)
        raised = False
    except SkipHandler:
        raised = True
    assert raised, "handler must SkipHandler when the user isn't in an AI session, so keyword search still runs"
    print("6. non-AI text falls through via SkipHandler: OK")

    # ---- 7. a full text solve round trip: quota increments, AI_PENDING clears, answer is shown ----
    tb.AI_PENDING.add(uid)
    calls = []
    async def fake_solve(*, image_bytes=None, text=None):
        calls.append((image_bytes, text))
        return "Правильный ответ: Б"
    orig_solve = tb.solve_ai_request
    tb.solve_ai_request = fake_solve
    before = tb.ai_requests_left(uid)
    msg2 = FakeMsg(uid=uid, text="Реши задачу по химии")
    await tb.handle_ai_text_input(msg2)
    assert uid not in tb.AI_PENDING
    assert calls == [(None, "Реши задачу по химии")]
    assert tb.ai_requests_left(uid) == before - 1
    final_text = msg2.last_child.edits[-1][0]
    assert "Правильный ответ: Б" in final_text
    assert f"{tb.ai_requests_left(uid)}/{tb.AI_FREE_DAILY_LIMIT}" in final_text
    print("7. text solve round trip + quota decrement: OK")

    # ---- 8. a photo solve round trip (mocking bot.get_file/download_file) ----
    tb.AI_PENDING.add(uid)
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
    assert uid not in tb.AI_PENDING
    assert calls[-1] == (b"fake-jpeg-bytes", None)
    assert tb.ai_requests_left(uid) == before2 - 1
    assert "Правильный ответ: Б" in photo_msg.last_child.edits[-1][0]
    tb.bot.get_file = orig_get_file
    tb.bot.download_file = orig_download_file
    print("8. photo solve round trip: OK")

    # ---- 9. a photo sent OUTSIDE an AI session is silently ignored (no crash, nothing sent) ----
    photo_msg2 = FakeMsg(uid=uid, photo=[FakePhotoSize("f3")])
    await tb.handle_ai_photo_input(photo_msg2)
    assert photo_msg2.edits == []
    print("9. photo outside AI session ignored: OK")

    # ---- 10. daily limit actually blocks further requests ----
    tb.stats["ai_usage"][str(uid)] = {"date": tb.date.today().isoformat(), "count": tb.AI_FREE_DAILY_LIMIT}
    assert tb.ai_requests_left(uid) == 0
    cb_limit = FakeCB("ai_solve_start", uid=uid)
    await tb.cb_ai_solve_start(cb_limit)
    assert uid not in tb.AI_PENDING
    assert cb_limit._answers[0][1] is True
    print("10. daily limit blocks new sessions: OK")

    # ---- 11. a slash command while pending still falls through untouched (e.g. /start) ----
    tb.AI_PENDING.add(uid)
    tb.stats["ai_usage"].pop(str(uid), None)
    cmd_msg = FakeMsg(uid=uid, text="/start")
    try:
        await tb.handle_ai_text_input(cmd_msg)
        raised = False
    except SkipHandler:
        raised = True
    assert raised
    assert uid in tb.AI_PENDING, "a slash command must not consume/clear the pending AI session"
    print("11. slash command while pending: SkipHandler, session untouched: OK")

    # cleanup
    tb.solve_ai_request = orig_solve
    tb.OPENAI_API_KEY = orig_key
    tb.AI_PENDING.discard(uid)
    tb.stats["ai_usage"].pop(str(uid), None)

    print("\nAll AI MVP tests passed!")

if __name__ == "__main__":
    asyncio.run(main())
