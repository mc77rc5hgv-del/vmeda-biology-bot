# -*- coding: utf-8 -*-
import asyncio, random
from _bootstrap import tb

ADMIN_ID = next(iter(tb.ADMIN_IDS))

class FakeUser:
    def __init__(self, uid):
        self.id = uid

class FakeMsg:
    def __init__(self, from_user=None):
        self.edits = []
        self.answers = []
        self.from_user = from_user
        self.text = None
        self.html_text = None
    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self
    async def delete(self):
        pass
    async def answer(self, text, **kwargs):
        self.answers.append(text)
        return self

class FakeCB:
    def __init__(self, data, uid):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
        self._answers = []
    async def answer(self, text=None, show_alert=False):
        self._answers.append((text, show_alert))

def kb_data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]

def fresh_uid():
    return random.randint(10_000_000, 99_999_999)

async def main():
    # ==================== resolve_user_by_username(): username + ID paths ====================
    uid_no_username = fresh_uid()
    tb.stats["total_users"].add(uid_no_username)
    tb.stats["user_username"].pop(str(uid_no_username), None)

    uid_with_username = fresh_uid()
    tb.stats["total_users"].add(uid_with_username)
    tb.stats["user_username"][str(uid_with_username)] = "ivanov"
    tb.stats["usernames"]["ivanov"] = uid_with_username

    # resolve by username (with and without @)
    assert tb.resolve_user_by_username("@ivanov") == ("ivanov", uid_with_username)
    assert tb.resolve_user_by_username("ivanov") == ("ivanov", uid_with_username)
    assert tb.resolve_user_by_username("IVANOV") == ("ivanov", uid_with_username)

    # resolve by numeric ID -> known user with a username on record
    assert tb.resolve_user_by_username(str(uid_with_username)) == ("ivanov", uid_with_username)

    # resolve by numeric ID -> known user with NO username on record
    assert tb.resolve_user_by_username(str(uid_no_username)) == (None, uid_no_username)

    # resolve by numeric ID -> unknown user (never interacted with the bot)
    unknown_id = fresh_uid()
    while unknown_id in tb.stats["total_users"]:
        unknown_id = fresh_uid()
    assert tb.resolve_user_by_username(str(unknown_id)) == (None, None)

    # resolve by unknown username
    assert tb.resolve_user_by_username("@nobody_has_this_handle") == ("nobody_has_this_handle", None)

    print("resolve_user_by_username: username + numeric ID (found/not found) all correct: OK")

    # ==================== format_admin_target_label() ====================
    assert tb.format_admin_target_label("ivanov", uid_with_username) == f"@ivanov (ID {uid_with_username})"
    assert tb.format_admin_target_label(None, uid_no_username) == f"ID {uid_no_username}"
    print("format_admin_target_label: OK")

    # ==================== end-to-end: grant access by raw numeric ID ====================
    if uid_no_username in tb.stats["manual_access_granted"]:
        tb.stats["manual_access_granted"].remove(uid_no_username)

    orig_send_message = tb.bot.send_message
    sent = []
    async def fake_send_message(chat_id, text, **kwargs):
        sent.append((chat_id, text))
    tb.bot.send_message = fake_send_message

    tb.ADMIN_PENDING[ADMIN_ID] = {"action": "grant"}
    m = FakeMsg(from_user=FakeUser(ADMIN_ID))
    m.text = str(uid_no_username)
    await tb.handle_admin_pending_action(m)
    assert uid_no_username in tb.stats["manual_access_granted"]
    assert ADMIN_ID not in tb.ADMIN_PENDING
    assert m.answers and f"ID {uid_no_username}" in m.answers[0]
    assert sent and sent[0][0] == uid_no_username

    tb.stats["manual_access_granted"].remove(uid_no_username)
    tb.bot.send_message = orig_send_message
    print("grant access by raw numeric ID (no username needed) works end-to-end: OK")

    # ==================== end-to-end: grant/revoke Anatomy demo access ====================
    if uid_no_username in tb.stats["manual_anatomy_demo_granted"]:
        tb.stats["manual_anatomy_demo_granted"].remove(uid_no_username)
    assert not tb.anatomy_access_ok(uid_no_username)

    orig_send_message4 = tb.bot.send_message
    sent4 = []
    async def fake_send_message4(chat_id, text, **kwargs):
        sent4.append((chat_id, text))
    tb.bot.send_message = fake_send_message4

    tb.ADMIN_PENDING[ADMIN_ID] = {"action": "grant_anatomy_demo"}
    m5 = FakeMsg(from_user=FakeUser(ADMIN_ID))
    m5.text = str(uid_no_username)
    await tb.handle_admin_pending_action(m5)
    assert uid_no_username in tb.stats["manual_anatomy_demo_granted"]
    assert ADMIN_ID not in tb.ADMIN_PENDING
    assert m5.answers and f"ID {uid_no_username}" in m5.answers[0]
    assert sent4 and sent4[0][0] == uid_no_username
    assert tb.anatomy_access_ok(uid_no_username)
    assert uid_no_username not in tb.stats["manual_access_granted"], "anatomy demo grant must not unlock other subjects"

    tb.ADMIN_PENDING[ADMIN_ID] = {"action": "revoke_anatomy_demo"}
    m6 = FakeMsg(from_user=FakeUser(ADMIN_ID))
    m6.text = str(uid_no_username)
    await tb.handle_admin_pending_action(m6)
    assert uid_no_username not in tb.stats["manual_anatomy_demo_granted"]
    assert ADMIN_ID not in tb.ADMIN_PENDING
    assert not tb.anatomy_access_ok(uid_no_username)

    tb.bot.send_message = orig_send_message4
    print("grant/revoke Anatomy demo access by raw numeric ID works end-to-end: OK")

    # ==================== end-to-end: DM a user by raw numeric ID ====================
    orig_send_message2 = tb.bot.send_message
    sent2 = []
    async def fake_send_message3(chat_id, text, **kwargs):
        sent2.append((chat_id, text))
    tb.bot.send_message = fake_send_message3

    tb.ADMIN_PENDING[ADMIN_ID] = {"action": "dm_username"}
    m1 = FakeMsg(from_user=FakeUser(ADMIN_ID))
    m1.text = str(uid_no_username)
    await tb.handle_admin_pending_action(m1)
    assert tb.ADMIN_PENDING[ADMIN_ID]["action"] == "dm_message"
    assert tb.ADMIN_PENDING[ADMIN_ID]["target_id"] == uid_no_username
    assert tb.ADMIN_PENDING[ADMIN_ID]["target_label"] == f"ID {uid_no_username}"

    m2 = FakeMsg(from_user=FakeUser(ADMIN_ID))
    m2.text = "Привет!"
    m2.html_text = "Привет!"
    await tb.handle_admin_pending_action(m2)
    assert ADMIN_ID not in tb.ADMIN_PENDING
    assert sent2 and sent2[0][0] == uid_no_username and "Привет!" in sent2[0][1]

    tb.bot.send_message = orig_send_message2
    print("DM a userless-username account by raw numeric ID works end-to-end: OK")

    # ==================== not-found messages differ for ID vs username input ====================
    tb.ADMIN_PENDING[ADMIN_ID] = {"action": "grant"}
    m3 = FakeMsg(from_user=FakeUser(ADMIN_ID))
    m3.text = str(unknown_id)
    await tb.handle_admin_pending_action(m3)
    assert m3.answers and str(unknown_id) in m3.answers[0] and "ID" in m3.answers[0]
    assert ADMIN_ID in tb.ADMIN_PENDING, "not-found must not clear pending state"

    tb.ADMIN_PENDING[ADMIN_ID] = {"action": "grant"}
    m4 = FakeMsg(from_user=FakeUser(ADMIN_ID))
    m4.text = "@totally_unknown_handle_xyz"
    await tb.handle_admin_pending_action(m4)
    assert m4.answers and "@totally_unknown_handle_xyz" in m4.answers[0]
    del tb.ADMIN_PENDING[ADMIN_ID]
    print("not-found error message adapts to ID vs username input: OK")

    # ==================== user card: prompt entry point ====================
    cb_prompt = FakeCB("admin_lookup_prompt", ADMIN_ID)
    await tb.cb_admin_lookup_prompt(cb_prompt)
    assert tb.ADMIN_PENDING[ADMIN_ID] == {"action": "lookup_username"}
    assert cb_prompt.message.edits
    del tb.ADMIN_PENDING[ADMIN_ID]

    non_admin_id = fresh_uid()
    cb_prompt_denied = FakeCB("admin_lookup_prompt", non_admin_id)
    await tb.cb_admin_lookup_prompt(cb_prompt_denied)
    assert non_admin_id not in tb.ADMIN_PENDING, "non-admin must not be able to start a lookup"
    print("admin_lookup_prompt: sets pending state, denies non-admin: OK")

    # ==================== user card: content reflects real state ====================
    card_uid = fresh_uid()
    tb.stats["total_users"].add(card_uid)
    tb.stats["user_username"][str(card_uid)] = "cardtest"
    tb.stats["usernames"]["cardtest"] = card_uid
    tb.stats["user_names"][str(card_uid)] = "Тестовый Студент"
    tb.stats["referrals"][str(card_uid)] = ["a", "b", "c"]
    tb.stats["referral_monthly"][str(card_uid)] = {"month": tb._current_referral_month_key(), "count": 1}
    tb.stats["manual_access_granted"] = [x for x in tb.stats["manual_access_granted"] if x != card_uid]
    tb.stats["manual_anatomy_demo_granted"] = [x for x in tb.stats["manual_anatomy_demo_granted"] if x != card_uid]
    tb.stats["subscriptions"].pop(str(card_uid), None)

    text = tb.get_admin_user_card_text(card_uid)
    assert "@cardtest" in text and str(card_uid) in text
    assert "Тестовый Студент" in text
    assert "Рефералов всего: <b>3</b>" in text
    assert "в этом месяце: <b>1</b>" in text
    assert "Ручной доступ: ❌" in text
    assert "Демо-доступ Анатомия: ❌" in text
    assert "Подписка: нет" in text

    kb = tb.get_admin_user_card_keyboard(card_uid)
    data = kb_data(kb)
    assert f"admin_card_access:{card_uid}:grant" in data
    assert f"admin_card_anatomy_demo:{card_uid}:grant" in data
    assert f"admin_card_dm:{card_uid}" in data
    assert f"admin_card_sub:{card_uid}" in data
    assert "admin_panel" in data
    print("get_admin_user_card_text/_keyboard reflect real user state: OK")

    # a subscription shows up on the card
    tb.grant_subscription(card_uid, 20, "rubles_manual", 99, "biology")
    text2 = tb.get_admin_user_card_text(card_uid)
    assert "Подписка: нет" not in text2
    assert tb.SUBSCRIPTION_TIERS[20]["title"] in text2
    tb.stats["subscriptions"].pop(str(card_uid), None)
    print("active subscription is reflected on the card: OK")

    # ==================== user card: lookup_username end-to-end via text flow ====================
    tb.ADMIN_PENDING[ADMIN_ID] = {"action": "lookup_username"}
    m_lookup = FakeMsg(from_user=FakeUser(ADMIN_ID))
    m_lookup.text = "cardtest"
    await tb.handle_admin_pending_action(m_lookup)
    assert ADMIN_ID not in tb.ADMIN_PENDING
    assert m_lookup.answers and "@cardtest" in m_lookup.answers[0]
    print("lookup_username end-to-end by username resolves to the card: OK")

    # ==================== user card: one-tap access toggle ====================
    assert card_uid not in tb.stats["manual_access_granted"]
    orig_send = tb.bot.send_message
    sent_toggle = []
    async def fake_send_toggle(chat_id, text, **kwargs):
        sent_toggle.append(chat_id)
    tb.bot.send_message = fake_send_toggle

    cb_grant = FakeCB(f"admin_card_access:{card_uid}:grant", ADMIN_ID)
    await tb.cb_admin_card_access(cb_grant)
    assert card_uid in tb.stats["manual_access_granted"]
    assert sent_toggle == [card_uid]
    _, kb_after_grant = cb_grant.message.edits[-1]
    assert f"admin_card_access:{card_uid}:revoke" in kb_data(kb_after_grant), "keyboard must flip to revoke after grant"

    cb_revoke = FakeCB(f"admin_card_access:{card_uid}:revoke", ADMIN_ID)
    await tb.cb_admin_card_access(cb_revoke)
    assert card_uid not in tb.stats["manual_access_granted"]
    _, kb_after_revoke = cb_revoke.message.edits[-1]
    assert f"admin_card_access:{card_uid}:grant" in kb_data(kb_after_revoke), "keyboard must flip back to grant after revoke"

    cb_grant_denied = FakeCB(f"admin_card_access:{card_uid}:grant", non_admin_id)
    await tb.cb_admin_card_access(cb_grant_denied)
    assert card_uid not in tb.stats["manual_access_granted"], "non-admin must not be able to toggle access"

    tb.bot.send_message = orig_send
    print("admin_card_access one-tap toggle grants/revokes and denies non-admin: OK")

    # ==================== user card: one-tap Anatomy demo toggle ====================
    assert card_uid not in tb.stats["manual_anatomy_demo_granted"]
    tb.bot.send_message = fake_send_toggle
    cb_demo_grant = FakeCB(f"admin_card_anatomy_demo:{card_uid}:grant", ADMIN_ID)
    await tb.cb_admin_card_anatomy_demo(cb_demo_grant)
    assert card_uid in tb.stats["manual_anatomy_demo_granted"]
    assert tb.anatomy_access_ok(card_uid)

    cb_demo_revoke = FakeCB(f"admin_card_anatomy_demo:{card_uid}:revoke", ADMIN_ID)
    await tb.cb_admin_card_anatomy_demo(cb_demo_revoke)
    assert card_uid not in tb.stats["manual_anatomy_demo_granted"]
    assert not tb.anatomy_access_ok(card_uid)
    tb.bot.send_message = orig_send
    print("admin_card_anatomy_demo one-tap toggle grants/revokes: OK")

    # ==================== user card: DM / subscription buttons hand off to existing flows ====================
    cb_dm = FakeCB(f"admin_card_dm:{card_uid}", ADMIN_ID)
    await tb.cb_admin_card_dm(cb_dm)
    assert tb.ADMIN_PENDING[ADMIN_ID] == {
        "action": "dm_message", "target_id": card_uid, "target_label": "@cardtest (ID %d)" % card_uid,
    }
    del tb.ADMIN_PENDING[ADMIN_ID]

    cb_sub = FakeCB(f"admin_card_sub:{card_uid}", ADMIN_ID)
    await tb.cb_admin_card_sub(cb_sub)
    assert tb.ADMIN_PENDING[ADMIN_ID]["action"] == "record_subscription_tier"
    assert tb.ADMIN_PENDING[ADMIN_ID]["target_id"] == card_uid
    assert cb_sub.message.answers, "tier picker must be sent as a new message (ReplyKeyboardMarkup)"
    del tb.ADMIN_PENDING[ADMIN_ID]
    print("admin_card_dm/admin_card_sub prime the existing DM/subscription pending flows: OK")

    # ==================== admin DM: sending a sticker instead of text ====================
    class FakeSticker:
        def __init__(self, file_id):
            self.file_id = file_id

    dm_target = fresh_uid()
    tb.stats["total_users"].add(dm_target)

    sticker_calls = []
    async def fake_send_message_dm(chat_id, text, **kwargs):
        sticker_calls.append(("message", chat_id, text))
    async def fake_send_sticker_dm(chat_id, file_id, **kwargs):
        sticker_calls.append(("sticker", chat_id, file_id))
    orig_send_message = tb.bot.send_message
    orig_send_sticker = getattr(tb.bot, "send_sticker", None)
    tb.bot.send_message = fake_send_message_dm
    tb.bot.send_sticker = fake_send_sticker_dm

    tb.ADMIN_PENDING[ADMIN_ID] = {"action": "dm_message", "target_id": dm_target, "target_label": "@stickertarget"}
    msg_sticker = FakeMsg(from_user=FakeUser(ADMIN_ID))
    msg_sticker.sticker = FakeSticker("STICKER_FILE_ID_123")
    await tb.handle_admin_dm_sticker(msg_sticker)
    assert ADMIN_ID not in tb.ADMIN_PENDING, "pending state must be consumed"
    assert any(kind == "message" and chat_id == dm_target and "Личное сообщение" in text for kind, chat_id, text in sticker_calls)
    assert ("sticker", dm_target, "STICKER_FILE_ID_123") in sticker_calls
    assert msg_sticker.answers and "Стикер отправлен" in msg_sticker.answers[0]
    print("admin DM: sending a sticker delivers header text + sticker to the target: OK")

    # non-admin sender must be ignored (no pending state exists for them anyway)
    sticker_calls.clear()
    non_admin_dm = fresh_uid()
    msg_sticker_denied = FakeMsg(from_user=FakeUser(non_admin_dm))
    msg_sticker_denied.sticker = FakeSticker("SHOULD_NOT_SEND")
    await tb.handle_admin_dm_sticker(msg_sticker_denied)
    assert not sticker_calls, "non-admin must not be able to trigger a sticker DM"
    print("admin DM sticker: non-admin ignored: OK")

    # admin with no pending "dm_message" action -> sticker is a no-op, nothing sent
    sticker_calls.clear()
    tb.ADMIN_PENDING.pop(ADMIN_ID, None)
    msg_sticker_idle = FakeMsg(from_user=FakeUser(ADMIN_ID))
    msg_sticker_idle.sticker = FakeSticker("SHOULD_NOT_SEND_EITHER")
    await tb.handle_admin_dm_sticker(msg_sticker_idle)
    assert not sticker_calls, "sticker outside the dm_message flow must be a no-op"
    print("admin DM sticker: no-op without a pending dm_message action: OK")

    tb.bot.send_message = orig_send_message
    if orig_send_sticker is not None:
        tb.bot.send_sticker = orig_send_sticker
    else:
        del tb.bot.send_sticker

    print("ALL ADMIN LOOKUP TESTS PASSED")

asyncio.run(main())
