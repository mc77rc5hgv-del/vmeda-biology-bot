# -*- coding: utf-8 -*-
import asyncio, random, time
from _bootstrap import tb
from html.parser import HTMLParser

ADMIN_ID = next(iter(tb.ADMIN_IDS))

class C(HTMLParser):
    def __init__(self):
        super().__init__(); self.stack=[]; self.problems=[]
    def handle_starttag(self, tag, attrs): self.stack.append(tag)
    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag: self.problems.append(tag)
        else: self.stack.pop()

def check_html(text):
    c = C(); c.feed(text)
    assert not c.stack and not c.problems, (text[:300], c.stack, c.problems)
    assert len(text) <= 4096, len(text)

class FakeUser:
    def __init__(self, uid, full_name="Тест Юзер", username=None):
        self.id = uid
        self.full_name = full_name
        self.username = username

class FakeMsg:
    def __init__(self):
        self.edits = []
        self.answers = []
    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self
    async def delete(self):
        pass
    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs.get("reply_markup")))
        return self

class FakeCB:
    def __init__(self, data, uid=ADMIN_ID, username=None):
        self.data = data
        self.from_user = FakeUser(uid, username=username)
        self.message = FakeMsg()
        self._answers = []
    async def answer(self, text=None, show_alert=False):
        self._answers.append((text, show_alert))

def kb_texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row]

def kb_data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]

async def main():
    # isolate: clear any confirmed groups a previous test run might have left behind
    tb.stats["rollcall_confirmed"].clear()

    # 1. Group naming + keyboard shape
    assert tb.rollcall_group_name(1) == "25-ЛД/СТ-1"
    assert tb.rollcall_group_name(45) == "25-ЛД/СТ-45"
    menu_kb = tb.get_rollcall_menu_keyboard()
    data = kb_data(menu_kb)
    for n in range(1, tb.ROLLCALL_GROUP_COUNT + 1):
        assert f"rollcall_group:{n}" in data
    assert "back_to_main" in data
    assert len(kb_texts(menu_kb)) == tb.ROLLCALL_GROUP_COUNT + 1  # 45 groups + back button
    print("45 group buttons + back button, correct callback_data: OK")

    # 2. Menu text carries the "be first" banner + live confirmed count
    menu_text = tb.get_rollcall_menu_text()
    check_html(menu_text)
    assert "ПЕРВЫМ ВЫБЕРИ СВОЮ ГРУППУ" in menu_text
    assert "0" in menu_text and str(tb.ROLLCALL_GROUP_COUNT) in menu_text
    print("rollcall menu text has banner + confirmed-count: OK")

    # 3. Main menu shows a rollcall entry with live progress, always visible
    non_admin = random.randint(10_000_000, 99_999_999)
    main_menu = tb.get_main_menu(user_id=non_admin)
    assert any(t.startswith(f"📋 Перекличка (0/{tb.ROLLCALL_GROUP_COUNT})") for t in kb_texts(main_menu))
    print("main menu shows rollcall entry with progress: OK")

    # 4. cb_rollcall_menu renders
    cb_menu = FakeCB("rollcall_menu", uid=non_admin)
    await tb.cb_rollcall_menu(cb_menu)
    assert cb_menu.message.edits
    print("cb_rollcall_menu renders: OK")

    # 5. Tapping an unclaimed group renders the @vmeda_helper deep-link screen and pings admins
    admin_sent = []
    orig_send_message = tb.bot.send_message
    async def fake_send_message(chat_id, text, **kwargs):
        admin_sent.append((chat_id, text, kwargs.get("reply_markup")))
    tb.bot.send_message = fake_send_message

    picker_uid = random.randint(10_000_000, 99_999_999)
    cb_group = FakeCB("rollcall_group:7", uid=picker_uid, username="picker7")
    await tb.cb_rollcall_group(cb_group)
    assert cb_group.message.edits
    group_text, group_kb = cb_group.message.edits[0]
    check_html(group_text)
    assert "25-ЛД/СТ-7" in group_text
    assert any(b.url for row in group_kb.inline_keyboard for b in row if b.url)

    admin_requests = [(c, t, k) for c, t, k in admin_sent if c in tb.ADMIN_IDS]
    assert len(admin_requests) == len(tb.ADMIN_IDS)
    req_chat, req_text, req_kb = admin_requests[0]
    check_html(req_text)
    assert "25-ЛД/СТ-7" in req_text and "@picker7" in req_text and str(picker_uid) in req_text
    confirm_cb_data = req_kb.inline_keyboard[0][0].callback_data
    assert confirm_cb_data == f"rollcall_confirm:7:{picker_uid}"
    print("tapping an unclaimed group renders deep-link screen + pings admins: OK")

    # 6. Out-of-range group index rejected
    cb_bad = FakeCB("rollcall_group:99", uid=non_admin)
    await tb.cb_rollcall_group(cb_bad)
    assert not cb_bad.message.edits
    assert cb_bad._answers and cb_bad._answers[0][1] is True
    print("out-of-range group index rejected: OK")

    # 7. Admin confirms -> group locked, buyer gets 7-day bonus access, buyer notified
    admin_sent.clear()
    cb_confirm = FakeCB(confirm_cb_data, uid=ADMIN_ID)
    await tb.cb_rollcall_confirm(cb_confirm)
    assert tb.stats["rollcall_confirmed"]["25-ЛД/СТ-7"]["user_id"] == picker_uid
    expected_expiry = time.time() + tb.TEMP_ACCESS_GRANT_SECONDS
    assert abs(tb.stats["temporary_access"][str(picker_uid)] - expected_expiry) < 5
    assert tb.has_free_access(picker_uid)
    assert cb_confirm.message.edits and "Подтверждено" in cb_confirm.message.edits[0][0]
    buyer_notified = [(c, t) for c, t, _ in admin_sent if c == picker_uid]
    assert buyer_notified and "подтверждён" in buyer_notified[0][1]
    print("admin confirm grants 7-day bonus access, locks the group, notifies the rep: OK")

    # 8. The group now shows as taken in the menu keyboard
    menu_kb2 = tb.get_rollcall_menu_keyboard()
    data2 = kb_data(menu_kb2)
    assert "rollcall_group:7" not in data2
    texts2 = kb_texts(menu_kb2)
    assert any("✅ 25-ЛД/СТ-7" in t for t in texts2)
    print("confirmed group shows as taken in the menu: OK")

    # 9. Tapping the now-taken group directly shows the "taken" alert and re-renders the menu
    cb_group_taken = FakeCB("rollcall_group:7", uid=random.randint(10_000_000, 99_999_999))
    await tb.cb_rollcall_group(cb_group_taken)
    assert cb_group_taken._answers and cb_group_taken._answers[0][1] is True
    assert cb_group_taken.message.edits and "Перекличка групп" in cb_group_taken.message.edits[0][0]
    print("tapping an already-confirmed group shows alert + re-renders menu: OK")

    # 10. The dedicated "taken" button also just answers with an alert
    cb_taken = FakeCB("rollcall_taken", uid=non_admin)
    await tb.cb_rollcall_taken(cb_taken)
    assert not cb_taken.message.edits
    assert cb_taken._answers and cb_taken._answers[0][1] is True
    print("rollcall_taken button answers with an alert only: OK")

    # 11. Double-confirm (race between two admins) does not re-grant or re-notify
    admin_sent.clear()
    tb.stats["temporary_access"].pop(str(picker_uid), None)  # simulate it having since expired
    cb_confirm2 = FakeCB(confirm_cb_data, uid=ADMIN_ID)
    await tb.cb_rollcall_confirm(cb_confirm2)
    assert str(picker_uid) not in tb.stats["temporary_access"], "must not re-grant once the group is locked"
    assert cb_confirm2.message.edits and "Уже подтверждено" in cb_confirm2.message.edits[0][0]
    assert not admin_sent, "must not re-notify the rep"
    print("double-confirm on an already-locked group is a harmless no-op: OK")

    # 12. Non-admin cannot confirm
    other_uid = random.randint(10_000_000, 99_999_999)
    tb.stats["rollcall_confirmed"].pop("25-ЛД/СТ-8", None)
    cb_bad_admin = FakeCB(f"rollcall_confirm:8:{other_uid}", uid=non_admin)
    await tb.cb_rollcall_confirm(cb_bad_admin)
    assert "25-ЛД/СТ-8" not in tb.stats["rollcall_confirmed"]
    assert str(other_uid) not in tb.stats["temporary_access"]
    print("non-admin cannot confirm a rollcall request: OK")

    tb.bot.send_message = orig_send_message
    tb.stats["rollcall_confirmed"].pop("25-ЛД/СТ-7", None)
    tb.stats["temporary_access"].pop(str(picker_uid), None)

    # 13. is_gated_callback exempts every rollcall_* callback (must always be reachable)
    assert not tb.is_gated_callback("rollcall_menu")
    assert not tb.is_gated_callback("rollcall_group:1")
    assert not tb.is_gated_callback("rollcall_taken")
    assert not tb.is_gated_callback("rollcall_confirm:1:123")
    print("rollcall callbacks exempt from the referral gate: OK")

    # 14. Admin announcement broadcast: preview -> confirm -> broadcast, non-admin blocked
    orig_broadcast = tb._broadcast
    broadcast_calls = []
    async def fake_broadcast(text, keyboard=None):
        broadcast_calls.append((text, keyboard))
    tb._broadcast = fake_broadcast

    ann_text = tb.get_rollcall_announcement_text()
    check_html(ann_text)
    assert "ПЕРВЫМ ВЫБЕРИ СВОЮ ГРУППУ" in ann_text
    ann_kb = tb.get_rollcall_announcement_keyboard()
    assert ann_kb.inline_keyboard[0][0].callback_data == "rollcall_menu"

    cb_ann1 = FakeCB("admin_announce_rollcall_confirm")
    await tb.cb_admin_announce_rollcall_confirm(cb_ann1)
    assert cb_ann1.message.edits and "Отправить" in cb_ann1.message.edits[0][0]
    assert not broadcast_calls, "must not broadcast before confirmation"

    broadcasts_before = tb.stats.get("broadcast_count", 0)
    cb_ann2 = FakeCB("admin_announce_rollcall_go")
    await tb.cb_admin_announce_rollcall_go(cb_ann2)
    assert broadcast_calls and broadcast_calls[0][0] == ann_text
    assert tb.stats["broadcast_count"] == broadcasts_before + 1
    assert cb_ann2.message.edits and "отправлен" in cb_ann2.message.edits[0][0]

    cb_ann3 = FakeCB("admin_announce_rollcall_confirm", uid=non_admin)
    await tb.cb_admin_announce_rollcall_confirm(cb_ann3)
    assert not cb_ann3.message.edits, "non-admin must be blocked"

    tb._broadcast = orig_broadcast
    print("admin rollcall-announcement broadcast (preview/confirm/go, non-admin blocked): OK")

    # 15. admin_panel keyboard exposes the new announce button
    admin_panel_data = kb_data(tb.get_admin_menu())
    assert "admin_announce_rollcall_confirm" in admin_panel_data
    print("admin panel exposes the rollcall announcement button: OK")

    print("ALL ROLLCALL TESTS PASSED")

asyncio.run(main())
