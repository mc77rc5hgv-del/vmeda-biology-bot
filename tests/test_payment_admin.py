# -*- coding: utf-8 -*-
"""Payment-admin role (АДМИН ПЛАТЕЖЕЙ): a third role, separate from the assistant-admin (see
test_assistant_admin.py) — grant/revoke by username/ID from the main admin panel, one-tap RUB
payment confirmation (same admin_confirm_sub/admin_reject_sub flow real admins use), access to
the Announcements submenu via a dedicated limited panel, and explicitly NO content-access bypass
(unlike the assistant role) since the user asked for payments + announcements only."""
import asyncio, random
from _bootstrap import tb

ADMIN_ID = next(iter(tb.ADMIN_IDS))

def fresh_uid():
    return random.randint(10_000_000, 99_999_999)

class FakeUser:
    def __init__(self, uid, full_name="Тест Юзер", username=None):
        self.id = uid
        self.full_name = full_name
        self.username = username

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

def kb_texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row]

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
    payer_id = register_user("payadmin1")
    buyer_id = register_user("buyer1")

    # ---- 1. before assignment: not a payment admin, no elevated access whatsoever ----
    assert not tb.is_payment_admin(payer_id)
    print("1. not a payment admin before assignment: OK")

    # ---- 2. main admin grants the role by username, via the standard ADMIN_PENDING flow ----
    cb = FakeCB("admin_grant_payment_admin_prompt", uid=ADMIN_ID)
    await tb.cb_admin_grant_payment_admin_prompt(cb)
    assert tb.ADMIN_PENDING[ADMIN_ID]["action"] == "grant_payment_admin"
    sent_msgs = []
    orig_send = tb.bot.send_message
    async def fake_send(chat_id, text, **kwargs):
        sent_msgs.append((chat_id, text, kwargs.get("reply_markup")))
    tb.bot.send_message = fake_send
    msg = FakeMsg(uid=ADMIN_ID, text="@payadmin1")
    await tb.handle_admin_pending_action(msg)
    assert payer_id in tb.stats["payment_admins"]
    assert ADMIN_ID not in tb.ADMIN_PENDING
    assert any(chat_id == payer_id for chat_id, _, _ in sent_msgs)
    print("2. main admin grants payment-admin role by username: OK")

    # ---- 3. this is a genuinely separate role from the assistant — no content-access bypass ----
    assert not tb.is_assistant_admin(payer_id)
    assert not tb.is_admin_or_assistant(payer_id)
    assert not tb.is_admin(payer_id)
    assert not tb.has_free_access(payer_id), "payment admin must NOT get the assistant's content bypass"
    print("3. payment admin gets no content-access bypass (separate contract from assistant): OK")

    # ---- 4. /admin routes: real admin -> full panel, payment admin -> its own limited panel ----
    payadmin_msg = FakeMsg(uid=payer_id)
    await tb.cmd_admin(payadmin_msg)
    assert payadmin_msg.edits and "Панель админа платежей" in payadmin_msg.edits[-1][0]
    plain_msg = FakeMsg(uid=non_admin)
    await tb.cmd_admin(plain_msg)
    assert plain_msg.edits == []
    print("4. /admin routes payment admin to its own panel: OK")

    # ---- 5. the payment-admin panel only offers Анонсы (no full admin-panel actions) ----
    cb_panel = FakeCB("payment_admin_panel", uid=payer_id)
    await tb.cb_payment_admin_panel(cb_panel)
    panel_texts = kb_texts(cb_panel.message.edits[-1][1])
    assert panel_texts == ["📣 Анонсы"]
    cb_panel_blocked = FakeCB("payment_admin_panel", uid=non_admin)
    await tb.cb_payment_admin_panel(cb_panel_blocked)
    assert not cb_panel_blocked.message.edits, "non-payment-admin must be blocked"
    print("5. payment-admin panel exposes exactly one action (Анонсы), blocks non-payment-admins: OK")

    # ---- 6. payment admin can reach the Announcements submenu, back button routes to ITS panel ----
    cb_ann = FakeCB("admin_announcements_menu", uid=payer_id)
    await tb.cb_admin_announcements_menu(cb_ann)
    ann_text, ann_kb = cb_ann.message.edits[-1]
    assert "Анонсы" in ann_text
    assert "📣 Анонс VMedA AI" in kb_texts(ann_kb)
    back_data = ann_kb.inline_keyboard[-1][0].callback_data
    assert back_data == "payment_admin_panel", "payment admin's back button must not point at admin_panel"
    print("6. payment admin reaches Announcements submenu, back goes to its own panel: OK")

    # ---- 7. payment admin can actually send one of the announcements end to end ----
    orig_broadcast = tb._broadcast
    broadcast_calls = []
    async def fake_broadcast(text, keyboard=None):
        broadcast_calls.append((text, keyboard))
    tb._broadcast = fake_broadcast

    cb_supp_confirm = FakeCB("admin_announce_support_confirm", uid=payer_id)
    await tb.cb_admin_announce_support_confirm(cb_supp_confirm)
    assert cb_supp_confirm.message.edits and "Отправить" in cb_supp_confirm.message.edits[0][0]
    assert not broadcast_calls, "must not broadcast before confirmation"

    broadcasts_before = tb.stats.get("broadcast_count", 0)
    cb_supp_go = FakeCB("admin_announce_support_go", uid=payer_id)
    await tb.cb_admin_announce_support_go(cb_supp_go)
    assert broadcast_calls, "payment admin must be able to actually send the announcement"
    assert tb.stats["broadcast_count"] == broadcasts_before + 1
    result_kb = cb_supp_go.message.edits[-1][1]
    assert kb_data(result_kb)[-1] == "payment_admin_panel", "success screen back-button must match role"
    tb._broadcast = orig_broadcast
    print("7. payment admin can send an announcement end to end, result screen routes back correctly: OK")

    # ---- 8. notify_admins_of_payment_request pings payment admins too, not just ADMIN_IDS ----
    tb.stats["subscriptions"].pop(str(buyer_id), None)
    sent_msgs.clear()
    cb_rub = FakeCB("buy_sub_rubles:22", uid=buyer_id)
    await tb.cb_buy_sub_rubles(cb_rub)
    payer_requests = [(c, t, k) for c, t, k in sent_msgs if c == payer_id]
    assert payer_requests, "payment admin must receive the one-tap confirm request too"
    confirm_cb_data = payer_requests[0][2].inline_keyboard[0][0].callback_data
    assert confirm_cb_data == f"admin_confirm_sub:22:{buyer_id}:-:249"
    print("8. notify_admins_of_payment_request also notifies payment admins: OK")

    # ---- 9. payment admin can tap confirm and actually grant the subscription ----
    sent_msgs.clear()
    cb_confirm = FakeCB(confirm_cb_data, uid=payer_id)
    await tb.cb_admin_confirm_sub(cb_confirm)
    assert tb.get_subscription(buyer_id)["tier"] == 22
    assert cb_confirm.message.edits and "Подтверждено" in cb_confirm.message.edits[0][0]
    tb.stats["subscriptions"].pop(str(buyer_id), None)
    tb.bot.send_message = orig_send
    print("9. payment admin can confirm a rubles payment, same as a real admin: OK")

    # ---- 10. main admin revokes the role; every capability above disappears ----
    cb_revoke = FakeCB("admin_revoke_payment_admin_prompt", uid=ADMIN_ID)
    await tb.cb_admin_revoke_payment_admin_prompt(cb_revoke)
    assert tb.ADMIN_PENDING[ADMIN_ID]["action"] == "revoke_payment_admin"
    await tb.handle_admin_pending_action(FakeMsg(uid=ADMIN_ID, text=str(payer_id)))
    assert payer_id not in tb.stats["payment_admins"]
    assert not tb.is_payment_admin(payer_id)

    cb_ann_after = FakeCB("admin_announcements_menu", uid=payer_id)
    await tb.cb_admin_announcements_menu(cb_ann_after)
    assert not cb_ann_after.message.edits, "revoked payment admin must lose Announcements access"
    print("10. revoke removes the role and every capability it granted: OK")

    print("\nAll payment-admin tests passed!")

if __name__ == "__main__":
    asyncio.run(main())
