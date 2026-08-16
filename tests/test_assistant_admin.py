# -*- coding: utf-8 -*-
"""Assistant-admin role: grant/revoke by username/ID from the main admin panel, full content
access via is_admin_or_assistant() (7 gate checkpoints), a separate limited panel (stats
subset + DM-with-approval), and the main-admin approve/reject flow for that DM."""
import asyncio, random
from _bootstrap import tb
from aiogram.dispatcher.event.bases import SkipHandler

ADMIN_ID = next(iter(tb.ADMIN_IDS))

def fresh_uid():
    return random.randint(10_000_000, 99_999_999)

class FakeUser:
    def __init__(self, uid):
        self.id = uid

class FakeMsg:
    def __init__(self, uid=None, text=None):
        self.from_user = FakeUser(uid) if uid is not None else None
        self.text = text
        self.html_text = text
        self.edits = []
    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self
    async def delete(self):
        pass
    async def answer(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self

class FakeCB:
    def __init__(self, data, uid=ADMIN_ID):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
        self._answers = []
    async def answer(self, text=None, show_alert=False):
        self._answers.append((text, show_alert))

def kb_data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]

def register_user(username=None):
    uid = fresh_uid()
    while uid in tb.stats["total_users"]:
        uid = fresh_uid()
    tb.stats["total_users"].add(uid)
    if username:
        tb.stats["user_username"][str(uid)] = username
        tb.stats["usernames"][username] = uid
    return uid

async def main():
    non_admin = register_user()
    assistant_id = register_user("helper1")
    target_id = register_user("student1")

    # ---- 1. before assignment: not an assistant, no elevated access ----
    assert not tb.is_assistant_admin(assistant_id)
    assert not tb.is_admin_or_assistant(assistant_id)
    print("1. not an assistant before assignment: OK")

    # ---- 2. main admin grants assistant role by username, via the standard ADMIN_PENDING flow ----
    cb = FakeCB("admin_grant_assistant_prompt", uid=ADMIN_ID)
    await tb.cb_admin_grant_assistant_prompt(cb)
    assert tb.ADMIN_PENDING[ADMIN_ID]["action"] == "grant_assistant_admin"
    sent_msgs = []
    orig_send = tb.bot.send_message
    async def fake_send(chat_id, text, **kwargs):
        sent_msgs.append((chat_id, text))
    tb.bot.send_message = fake_send
    msg = FakeMsg(uid=ADMIN_ID, text="@helper1")
    await tb.handle_admin_pending_action(msg)
    assert assistant_id in tb.stats["assistant_admins"]
    assert ADMIN_ID not in tb.ADMIN_PENDING
    assert any(chat_id == assistant_id for chat_id, _ in sent_msgs)
    print("2. main admin grants assistant role by username: OK")

    # ---- 3. assistant now has full content access via is_admin_or_assistant, without being a real admin ----
    assert tb.is_assistant_admin(assistant_id)
    assert tb.is_admin_or_assistant(assistant_id)
    assert not tb.is_admin(assistant_id)
    assert tb.has_free_access(assistant_id)
    assert tb.has_subject_access(assistant_id, "physics")
    assert tb.biology_tickets_download_ok(assistant_id)
    assert tb.chemistry_tickets_access_ok(assistant_id)
    assert tb.anatomy_access_ok(assistant_id)
    assert tb.histology_permanently_unlocked(assistant_id)
    assert not tb.has_free_access(non_admin)
    print("3. assistant gets access to every gated section: OK")

    # ---- 3b. assistant also bypasses the anatomy maintenance-mode closure, like a real admin ----
    orig_maint = tb.anatomy_handlers.ANATOMY_MAINTENANCE_MODE
    tb.anatomy_handlers.ANATOMY_MAINTENANCE_MODE = True
    cb_root = FakeCB("anatomy_root", uid=assistant_id)
    await tb.cb_anatomy_root(cb_root)
    text_root, kb_root = cb_root.message.edits[-1]
    assert "anatomy_menu" in kb_data(kb_root), "assistant must not be blocked by the maintenance screen"
    tb.anatomy_handlers.ANATOMY_MAINTENANCE_MODE = orig_maint
    print("3b. assistant bypasses anatomy maintenance mode: OK")

    # ---- 4. cmd_admin routes: real admin -> full panel, assistant -> limited panel, nobody else ----
    admin_msg = FakeMsg(uid=ADMIN_ID)
    await tb.cmd_admin(admin_msg)
    assert "Админ-панель" in admin_msg.edits[-1][0]
    assistant_msg = FakeMsg(uid=assistant_id)
    await tb.cmd_admin(assistant_msg)
    assert "Панель помощника" in assistant_msg.edits[-1][0]
    plain_msg = FakeMsg(uid=non_admin)
    await tb.cmd_admin(plain_msg)
    assert plain_msg.edits == []
    print("4. /admin routes by role: OK")

    # ---- 5. assistant stats screen is exactly the agreed subset, no subscriptions/payments ----
    cb_stats = FakeCB("assistant_stats", uid=assistant_id)
    await tb.cb_assistant_stats(cb_stats)
    stats_text = cb_stats.message.edits[-1][0]
    for label in (
        "👥 Уникальных пользователей", "▶️ Запусков бота", "❓ Вопросов просмотрено",
        "🎲 Случайных билетов открыто", "🎲 Случайных вопросов открыто", "📢 Рассылок отправлено",
        "🔗 Всего рефералов", "📉 Меньше", "🔓 Ручных доступов выдано",
        "🦴 Демо-доступов к Анатомии выдано", "🚫 Исчерпали бесплатные заходы без рефералов",
        "🪪 Известно username",
    ):
        assert label in stats_text, label
    assert "Подписки" not in stats_text and "Платежи" not in stats_text
    print("5. assistant stats screen matches the agreed subset: OK")

    # ---- 6. a non-assistant cannot reach any assistant screen ----
    cb_blocked = FakeCB("assistant_stats", uid=non_admin)
    await tb.cb_assistant_stats(cb_blocked)
    assert cb_blocked.message.edits == []
    print("6. non-assistant blocked from assistant panel: OK")

    # ---- 7. assistant DM flow: username -> message text -> request queued, NOT sent yet ----
    sent_msgs.clear()
    cb_dm = FakeCB("assistant_dm_prompt", uid=assistant_id)
    await tb.cb_assistant_dm_prompt(cb_dm)
    assert tb.ASSISTANT_PENDING[assistant_id]["action"] == "dm_username"

    msg_username = FakeMsg(uid=assistant_id, text="@student1")
    await tb.handle_assistant_pending_action(msg_username)
    assert tb.ASSISTANT_PENDING[assistant_id]["action"] == "dm_message"
    assert tb.ASSISTANT_PENDING[assistant_id]["target_id"] == target_id

    msg_text = FakeMsg(uid=assistant_id, text="Привет! Проверь домашку.")
    await tb.handle_assistant_pending_action(msg_text)
    assert assistant_id not in tb.ASSISTANT_PENDING
    assert not any(chat_id == target_id for chat_id, _ in sent_msgs), "must NOT be sent before admin approval"
    assert any(chat_id == ADMIN_ID for chat_id, _ in sent_msgs), "main admin must be notified"
    assert len(tb.ASSISTANT_DM_REQUESTS) == 1
    req_id = next(iter(tb.ASSISTANT_DM_REQUESTS))
    print("7. assistant DM queued for approval, not sent directly: OK")

    # ---- 8. a message from an assistant with no pending action falls through (SkipHandler) ----
    msg_idle = FakeMsg(uid=assistant_id, text="просто текст")
    try:
        await tb.handle_assistant_pending_action(msg_idle)
        raised = False
    except SkipHandler:
        raised = True
    assert raised
    print("8. idle assistant text falls through via SkipHandler: OK")

    # ---- 9. main admin approves -> message actually sent, assistant notified, request consumed ----
    sent_msgs.clear()
    cb_approve = FakeCB(f"assistant_dm_approve:{req_id}", uid=ADMIN_ID)
    await tb.cb_assistant_dm_approve(cb_approve)
    assert req_id not in tb.ASSISTANT_DM_REQUESTS
    assert any(chat_id == target_id for chat_id, _ in sent_msgs), "target must receive the message after approval"
    assert any(chat_id == assistant_id for chat_id, _ in sent_msgs), "assistant must be notified of approval"
    print("9. admin approval actually delivers the message: OK")

    # ---- 10. double-tap approve (race) is a harmless no-op on the second tap ----
    cb_approve2 = FakeCB(f"assistant_dm_approve:{req_id}", uid=ADMIN_ID)
    await tb.cb_assistant_dm_approve(cb_approve2)
    assert cb_approve2._answers[0][1] is True
    print("10. double-approve race-guarded: OK")

    # ---- 11. reject path: nothing sent to target, assistant notified of rejection ----
    cb_dm2 = FakeCB("assistant_dm_prompt", uid=assistant_id)
    await tb.cb_assistant_dm_prompt(cb_dm2)
    await tb.handle_assistant_pending_action(FakeMsg(uid=assistant_id, text="@student1"))
    await tb.handle_assistant_pending_action(FakeMsg(uid=assistant_id, text="Второе сообщение"))
    req_id2 = next(iter(tb.ASSISTANT_DM_REQUESTS))
    sent_msgs.clear()
    cb_reject = FakeCB(f"assistant_dm_reject:{req_id2}", uid=ADMIN_ID)
    await tb.cb_assistant_dm_reject(cb_reject)
    assert req_id2 not in tb.ASSISTANT_DM_REQUESTS
    assert not any(chat_id == target_id for chat_id, _ in sent_msgs)
    assert any(chat_id == assistant_id for chat_id, _ in sent_msgs)
    print("11. admin rejection: nothing sent, assistant notified: OK")

    # ---- 12. a non-admin cannot approve/reject even with a guessed request id ----
    cb_dm3 = FakeCB("assistant_dm_prompt", uid=assistant_id)
    await tb.cb_assistant_dm_prompt(cb_dm3)
    await tb.handle_assistant_pending_action(FakeMsg(uid=assistant_id, text="@student1"))
    await tb.handle_assistant_pending_action(FakeMsg(uid=assistant_id, text="Третье сообщение"))
    req_id3 = next(iter(tb.ASSISTANT_DM_REQUESTS))
    cb_forbidden = FakeCB(f"assistant_dm_approve:{req_id3}", uid=non_admin)
    await tb.cb_assistant_dm_approve(cb_forbidden)
    assert req_id3 in tb.ASSISTANT_DM_REQUESTS, "non-admin must not be able to approve"
    print("12. non-admin cannot approve/reject: OK")

    # ---- 13. main admin revokes the assistant role by ID; content access disappears ----
    tb.ASSISTANT_DM_REQUESTS.clear()
    cb_revoke = FakeCB("admin_revoke_assistant_prompt", uid=ADMIN_ID)
    await tb.cb_admin_revoke_assistant_prompt(cb_revoke)
    assert tb.ADMIN_PENDING[ADMIN_ID]["action"] == "revoke_assistant_admin"
    await tb.handle_admin_pending_action(FakeMsg(uid=ADMIN_ID, text=str(assistant_id)))
    assert assistant_id not in tb.stats["assistant_admins"]
    assert not tb.is_admin_or_assistant(assistant_id)
    assert not tb.has_free_access(assistant_id)
    print("13. revoke removes assistant role and access: OK")

    tb.bot.send_message = orig_send
    print("\nAll assistant-admin tests passed!")

if __name__ == "__main__":
    asyncio.run(main())
