# -*- coding: utf-8 -*-
import asyncio
import copy
import random
import urllib.parse

from _bootstrap import tb

ADMIN_ID = next(iter(tb.ADMIN_IDS))


class FakeUser:
    def __init__(self, uid, full_name="Тестовый Покупатель", username=None):
        self.id = uid
        self.full_name = full_name
        self.username = username


class FakeMessage:
    def __init__(self):
        self.edits = []

    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs))
        return self


class FakeCallback:
    def __init__(self, data, uid=ADMIN_ID, username=None):
        self.data = data
        self.from_user = FakeUser(uid, username=username)
        self.message = FakeMessage()
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


def callback_data(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row if button.callback_data]


async def main():
    assert tb.stats["mug_order_requests"] == {}
    assert tb.stats["mug_orders"] == []
    subscriptions_before = copy.deepcopy(tb.stats["subscriptions"])

    menu = tb.get_mugs_menu_keyboard()
    assert callback_data(menu) == ["mugs_model:1", "mugs_model:2", "mugs_model:3", "back_to_main"]
    assert "0" in tb.get_mugs_menu_text() and str(tb.MUG_SALES_TARGET) in tb.get_mugs_menu_text()
    assert "mugs_menu" in callback_data(tb.get_main_menu())
    assert "admin_mug_orders:0" in callback_data(tb.get_admin_menu())

    tb.MUG_PREORDER_ENABLED = False
    assert "mugs_menu" not in callback_data(tb.get_main_menu())
    closed = FakeCallback("mugs_menu", uid=random.randint(10_000_000, 99_999_999))
    await tb.cb_mugs_menu(closed)
    assert closed.answers and closed.answers[0][1] is True and not closed.message.edits
    tb.MUG_PREORDER_ENABLED = True

    sent = []
    original_send_message = tb.bot.send_message

    async def fake_send_message(chat_id, text, **kwargs):
        sent.append((chat_id, text, kwargs))

    tb.bot.send_message = fake_send_message
    uid = random.randint(10_000_000, 99_999_999)
    select = FakeCallback("mugs_model:2", uid=uid, username="mugbuyer")
    await tb.cb_mugs_model(select)

    key = tb.get_mug_order_request_key("2", uid)
    assert key in tb.stats["mug_order_requests"]
    assert tb.stats["mug_orders"] == [], "pending request must not appear as a confirmed order"
    assert len([row for row in sent if row[0] in tb.ADMIN_IDS]) == len(tb.ADMIN_IDS)
    assert "Подтверждённых заказов пока нет" in tb.get_admin_mug_orders_text()

    model_keyboard = select.message.edits[0][1]["reply_markup"]
    order_url = next(button.url for row in model_keyboard.inline_keyboard for button in row if button.url)
    decoded_url = urllib.parse.unquote(order_url)
    assert "t.me/vmeda_helper" in decoded_url
    assert "Модель 2" in decoded_url and str(uid) in decoded_url

    # Opening the same model again reuses the pending request instead of spamming admins.
    sent_before_repeat = len(sent)
    await tb.cb_mugs_model(FakeCallback("mugs_model:2", uid=uid, username="mugbuyer"))
    assert len(sent) == sent_before_repeat
    assert len(tb.stats["mug_order_requests"]) == 1

    non_admin = random.randint(10_000_000, 99_999_999)
    denied = FakeCallback(f"admin_mug_confirm:2:{uid}", uid=non_admin)
    await tb.cb_admin_mug_confirm(denied)
    assert key in tb.stats["mug_order_requests"] and tb.stats["mug_orders"] == []

    sent.clear()
    confirm = FakeCallback(f"admin_mug_confirm:2:{uid}", uid=ADMIN_ID)
    await tb.cb_admin_mug_confirm(confirm)
    assert key not in tb.stats["mug_order_requests"]
    assert len(tb.stats["mug_orders"]) == 1
    assert tb.stats["mug_orders"][0]["model_name"] == "Модель 2"
    assert "@mugbuyer" in confirm.message.edits[0][0]
    assert any(chat_id == uid and "Оплата заказа подтверждена" in text for chat_id, text, _ in sent)
    assert "Модель 2" in tb.get_admin_mug_orders_text() and "@mugbuyer" in tb.get_admin_mug_orders_text()

    # A second admin tap is idempotent and does not add or notify twice.
    sent.clear()
    duplicate = FakeCallback(f"admin_mug_confirm:2:{uid}", uid=ADMIN_ID)
    await tb.cb_admin_mug_confirm(duplicate)
    assert len(tb.stats["mug_orders"]) == 1
    assert not sent

    # Rejection removes only a pending mug request.
    reject_uid = random.randint(10_000_000, 99_999_999)
    reject_select = FakeCallback("mugs_model:3", uid=reject_uid, username="rejectbuyer")
    await tb.cb_mugs_model(reject_select)
    reject_key = tb.get_mug_order_request_key("3", reject_uid)
    reject = FakeCallback(f"admin_mug_reject:3:{reject_uid}", uid=ADMIN_ID)
    await tb.cb_admin_mug_reject(reject)
    assert reject_key not in tb.stats["mug_order_requests"]
    assert all(order["user_id"] != reject_uid for order in tb.stats["mug_orders"])

    assert tb.stats["subscriptions"] == subscriptions_before, "mug flow must never touch subscriptions"
    tb.bot.send_message = original_send_message
    print("ALL MUG ORDER TESTS PASSED")


asyncio.run(main())
