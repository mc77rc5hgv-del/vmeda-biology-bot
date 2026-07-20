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
    async def answer(self, text, **kwargs):
        self.answers.append(text)
        return self

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

    print("ALL ADMIN LOOKUP TESTS PASSED")

asyncio.run(main())
