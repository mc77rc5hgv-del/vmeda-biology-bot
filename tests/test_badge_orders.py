"""End-to-end badge form and delivery checks against the real bot module."""
import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

from _bootstrap import tb
from services.badge_orders import RECIPIENT_ID, FIELDS, order_template, validate_value

b = tb.badges_handlers


class User:
    def __init__(self, uid=1234567, username="badge_buyer"):
        self.id, self.username, self.full_name = uid, username, "Заказчик <пример>"
        self.is_bot = False


class Message:
    def __init__(self, user=None, text=None):
        self.from_user = user or User()
        self.text = text
        self.chat = SimpleNamespace(type="private", id=self.from_user.id)
        self.successful_payment = None
        self.sent = []

    async def answer(self, text, **kwargs):
        self.sent.append((text, kwargs))
        return self


class Callback:
    def __init__(self, action, user=None):
        self.data = "badges:" + action
        self.from_user = user or User()
        self.message = Message(self.from_user)
        self.answers = []

    async def answer(self, *args, **kwargs):
        self.answers.append((args, kwargs))


async def fill(user=None):
    user = user or User()
    await b.callback_badges(Callback("start", user))
    for value in ["Иванов Иван Иванович", "Курсант <1>", "Лечебное дело", "2"]:
        await b.handle_input(Message(user, value))
    draft = b.draft_for(user.id)
    assert draft["step"] == len(FIELDS)
    return draft


async def main():
    original_send = tb.bot.send_message
    original_save = tb.save_stats
    send = AsyncMock(return_value=SimpleNamespace(message_id=888))
    tb.bot.send_message = send
    protected = {k: copy.deepcopy(tb.stats[k]) for k in ["subscriptions", "total_users", "mug_orders", "mug_order_requests"]}
    assert not tb.MUG_PREORDER_ENABLED
    buttons = [button for row in tb.get_main_menu().inline_keyboard for button in row]
    assert any(button.callback_data == "badges:menu" for button in buttons)
    assert not any(button.callback_data == "mugs_menu" for button in buttons)
    assert "admin_mug_orders:0" not in str(tb.get_admin_menu())
    assert "admin_announce_mugs" not in str(tb.get_admin_announcements_keyboard())

    for value in ["0", "101", "-1", "1.5", "abc", "١"]:
        try:
            validate_value(3, value)
        except ValueError as exc:
            assert str(exc)
        else:
            raise AssertionError("quantity must be a bounded ASCII integer")
    assert validate_value(2, "стоматология") == "Стоматология"
    for index, value in [(0, "123"), (1, ""), (2, "Другая"), (2, "")]:
        try:
            validate_value(index, value)
        except ValueError as exc:
            assert str(exc)
        else:
            raise AssertionError("invalid field accepted")

    # Choices, custom role and stale buttons cannot skip required fields.
    await b.callback_badges(Callback("start"))
    await b.handle_input(Message(text="Иванов Иван Иванович"))
    await b.callback_badges(Callback("choose:role:0"))
    assert b.draft_for(User().id)["details"]["role"] == "Студент"
    await b.callback_badges(Callback("choose:role:1"))
    assert b.draft_for(User().id)["step"] == 2
    await b.callback_badges(Callback("choose:specialty:2"))
    await b.handle_input(Message(text="3"))
    assert b.draft_for(User().id)["details"]["specialty"] == "Медико-профилактическое дело"
    await b.callback_badges(Callback("edit:1"))
    await b.callback_badges(Callback("custom"))
    await b.handle_input(Message(text="Врач"))
    assert b.draft_for(User().id)["details"]["role"] == "Врач"

    # Old drafts retain original inputs and require the newly requested specialty.
    old_details = {"surname": "Иванов", "name": "Иван", "patronymic": "Иванович",
                   "role": "Курсант", "organization": "ВМедА", "quantity": "2", "contact": "@badge_buyer"}
    tb.stats.setdefault("badge_drafts", {})["4444444"] = {
        "id": "legacy", "details": copy.deepcopy(old_details), "step": 7, "active": True}
    migrated = b.draft_for(4444444)
    assert migrated["step"] == 2 and migrated["legacy_details"] == old_details
    assert migrated["details"]["fio"] == "Иванов Иван Иванович"
    legacy = {"id": "old", "user_id": 4444444, "details": copy.deepcopy(old_details)}
    snapshot = copy.deepcopy(legacy)
    assert "Организация: ВМедА" in order_template(legacy)
    assert "Контакт для связи" in b.preview(legacy["details"])
    assert legacy == snapshot

    draft = await fill()
    assert not send.called, "filling/previewing must not notify the recipient"
    assert not tb.stats["badge_orders"]
    token = draft["id"]
    await b.callback_badges(Callback("edit:2"))
    await b.handle_input(Message(text="Стоматология"))
    assert draft["details"]["specialty"] == "Стоматология"
    assert draft["step"] == len(FIELDS)
    await b.callback_badges(Callback("cancel"))
    assert not b.has_active_draft(User().id)
    await b.callback_badges(Callback("resume"))
    assert b.has_active_draft(User().id)

    await asyncio.gather(b.submit(Callback("send:" + token), token), b.submit(Callback("send:" + token), token))
    assert send.await_count == 1, "double-tap must not duplicate the notification"
    args, kwargs = send.call_args
    assert args[0] == RECIPIENT_ID
    assert "Курсант &lt;1&gt;" in args[1] and "<пример>" not in args[1]
    assert "не подтверждает оплату" in args[1]
    order = tb.stats["badge_orders"][token]
    assert order["delivery"] == "sent"
    assert set(order["details"]) == {"fio", "role", "specialty", "quantity"}
    assert "Организация" not in order_template(order) and "Контакт для связи" not in order_template(order)
    assert not b.has_active_draft(User().id)
    url = next(button.url for row in b.result_keyboard(order).inline_keyboard for button in row if button.url)
    assert urlparse(url).path == "/vmeda_helper"
    assert parse_qs(urlparse(url).query)["text"][0] == order_template(order)
    assert kwargs["reply_markup"].inline_keyboard[0][0].url == "https://t.me/badge_buyer"
    await b.submit(Callback("send:" + token, User(999999)), token)
    assert send.await_count == 1, "cannot replay someone else's order"
    await b.callback_badges(Callback("admin:0", User(999999)))
    assert send.await_count == 1

    # A timeout can mean Telegram accepted the notification. Never retry blindly.
    send.reset_mock()
    send.side_effect = TimeoutError("synthetic timeout")
    user = User(2222222, None)
    draft = await fill(user)
    token = draft["id"]
    await b.submit(Callback("send:" + token, user), token)
    await b.submit(Callback("send:" + token, user), token)
    assert send.await_count == 1
    order = tb.stats["badge_orders"][token]
    assert order["delivery"] == "unknown"
    assert "Повторить отправку" not in str(b.result_keyboard(order))

    # A failed durable write must never send a notification or erase the draft.
    send.reset_mock()
    send.side_effect = None
    user = User(3333333)
    draft = await fill(user)
    token = draft["id"]
    def failed_save():
        raise OSError("synthetic disk error")
    tb.save_stats = failed_save
    await b.submit(Callback("send:" + token, user), token)
    assert not send.called
    assert tb.stats["badge_orders"][token]["delivery"] == "prepared"
    assert b.has_active_draft(user.id)
    tb.save_stats = original_save

    # Navigating away suspends form input; /start can reach its normal handler.
    handler = AsyncMock()
    await b.navigation_middleware(handler, Callback("unused", user), {})
    assert b.has_active_draft(user.id)
    outside = Callback("unused", user)
    outside.data = "course_menu:1"
    await b.navigation_middleware(handler, outside, {})
    assert not b.has_active_draft(user.id)

    # New order data is separate from historical purchases and entitlements.
    assert all(tb.stats[k] == v for k, v in protected.items())
    # Badge form text must bypass the educational subscription gate.
    await b.callback_badges(Callback("resume", user))
    event = SimpleNamespace(message=Message(user, "Иванов"), callback_query=None)
    called = AsyncMock()
    await tb.referral_gate_middleware(called, event, {})
    called.assert_awaited_once()
    tb.bot.send_message = original_send
    await b.persist()
    print("badge orders: form, durable delivery, duplicate/ownership guards and data preservation OK")


asyncio.run(main())
