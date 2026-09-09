# -*- coding: utf-8 -*-
import asyncio
import copy
import random
import urllib.parse

from aiogram.types import FSInputFile

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
        self.photos = []
        self.albums = []
        self.deleted = False

    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs))
        return self

    async def edit_caption(self, caption, **kwargs):
        self.edits.append((caption, kwargs))
        return self

    async def delete(self):
        self.deleted = True

    async def answer_photo(self, photo, **kwargs):
        self.photos.append((photo, kwargs))
        return type("SentPhoto", (), {"photo": []})()

    async def answer_media_group(self, media, **kwargs):
        self.albums.append((media, kwargs))
        return []


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
    assert {spec["title"] for spec in tb.MUG_MODELS.values()} == {
        "Классика ВМедА", "Наследие Академии", "Штаб ВМедА",
    }
    assert [spec["price_rub"] for spec in tb.MUG_MODELS.values()] == [799, 849, 999]
    assert all(tb.mugs_handlers.get_mug_image_path(model_id).is_file() for model_id in tb.MUG_MODELS)
    tb.stats["mug_file_ids"]["1"] = "stale-classic-photo"
    assert isinstance(tb.mugs_handlers.get_mug_photo("1"), FSInputFile)
    classic_cache_key = tb.mugs_handlers.get_mug_photo_cache_key("1")
    assert classic_cache_key == "1:2"
    tb.stats["mug_file_ids"][classic_cache_key] = "current-classic-photo"
    assert tb.mugs_handlers.get_mug_photo("1") == "current-classic-photo"
    del tb.stats["mug_file_ids"][classic_cache_key]
    classic_keyboard = tb.mugs_handlers.get_mug_model_keyboard("1", 1326779223, False, False)
    classic_url = next(button.url for row in classic_keyboard.inline_keyboard for button in row if button.url)
    classic_text = urllib.parse.parse_qs(urllib.parse.urlparse(classic_url).query)["text"][0]
    assert classic_text == (
        "Здравствуйте! Хочу заказать кружку VMEDA — Классика ВМедА. "
        "Количество: 1 шт. Пришлите, пожалуйста, реквизиты для перевода."
    )

    tb.MUG_PREORDER_ENABLED = False
    assert "mugs_menu" not in callback_data(tb.get_main_menu())
    closed = FakeCallback("mugs_menu", uid=random.randint(10_000_000, 99_999_999))
    await tb.cb_mugs_menu(closed)
    assert closed.answers and closed.answers[0][1] is True and not closed.message.edits
    tb.MUG_PREORDER_ENABLED = True

    sent = []
    sent_photos = []
    sent_albums = []
    original_send_message = tb.bot.send_message
    original_send_photo = tb.bot.send_photo
    original_send_media_group = tb.bot.send_media_group

    async def fake_send_message(chat_id, text, **kwargs):
        sent.append((chat_id, text, kwargs))

    async def fake_send_photo(chat_id, photo, **kwargs):
        sent_photos.append((chat_id, photo, kwargs))
        return type("SentPhoto", (), {"photo": []})()

    async def fake_send_media_group(chat_id, media, **kwargs):
        sent_albums.append((chat_id, media, kwargs))
        return []

    tb.bot.send_message = fake_send_message
    tb.bot.send_photo = fake_send_photo
    tb.bot.send_media_group = fake_send_media_group
    uid = random.randint(10_000_000, 99_999_999)
    select = FakeCallback("mugs_model:2", uid=uid, username="mugbuyer")
    await tb.cb_mugs_model(select)

    key = tb.get_mug_order_request_key("2", uid)
    assert key not in tb.stats["mug_order_requests"], "viewing a model must not create an order request"
    assert tb.stats["mug_orders"] == [], "pending request must not appear as a confirmed order"
    assert not sent_photos, "admins must not be notified when the user only views a model"
    assert "Подтверждённых заказов пока нет" in tb.get_admin_mug_orders_text()

    assert select.message.deleted and len(select.message.photos) == 1
    model_keyboard = select.message.photos[0][1]["reply_markup"]
    order_url = next(button.url for row in model_keyboard.inline_keyboard for button in row if button.url)
    parsed_url = urllib.parse.urlparse(order_url)
    helper_text = urllib.parse.parse_qs(parsed_url.query)["text"][0]
    assert parsed_url.netloc == "t.me" and parsed_url.path == "/vmeda_helper"
    assert helper_text == (
        "Здравствуйте! Хочу заказать кружку VMEDA — Наследие Академии. "
        "Количество: 1 шт. Пришлите, пожалуйста, реквизиты для перевода."
    )
    assert str(uid) not in helper_text and "После оплаты" not in helper_text
    assert "mugs_order:2:1" in callback_data(model_keyboard)
    assert "mugs_qty:2:2" in callback_data(model_keyboard)

    # Quantity controls update both the displayed total and the order snapshot.
    quantity_callback = FakeCallback("mugs_qty:2:3", uid=uid, username="mugbuyer")
    await tb.cb_mugs_quantity(quantity_callback)
    quantity_text, quantity_kwargs = quantity_callback.message.edits[-1]
    assert "Количество: <b>3 шт.</b>" in quantity_text and "Итого: <b>2547 ₽</b>" in quantity_text
    quantity_keyboard = quantity_kwargs["reply_markup"]
    quantity_url = next(button.url for row in quantity_keyboard.inline_keyboard for button in row if button.url)
    quantity_helper_text = urllib.parse.parse_qs(urllib.parse.urlparse(quantity_url).query)["text"][0]
    assert "Количество: 3 шт." in quantity_helper_text
    assert "mugs_order:2:3" in callback_data(quantity_keyboard)

    # Only the explicit user confirmation creates the request and notifies admins.
    order_callback = FakeCallback("mugs_order:2:3", uid=uid, username="mugbuyer")
    await tb.cb_mugs_order(order_callback)
    assert key in tb.stats["mug_order_requests"]
    assert tb.stats["mug_order_requests"][key]["user_confirmed_at"]
    assert tb.stats["mug_order_requests"][key]["quantity"] == 3
    assert tb.stats["mug_order_requests"][key]["unit_price_rub"] == 849
    assert tb.stats["mug_order_requests"][key]["price_rub"] == 2547
    assert len([row for row in sent_photos if row[0] in tb.ADMIN_IDS]) == len(tb.ADMIN_IDS)
    assert any(
        "Оплата проверяется" in button.text
        for row in order_callback.message.edits[-1][1]["reply_markup"].inline_keyboard
        for button in row
    )

    # Pressing confirmation again reuses the pending request instead of spamming admins.
    photos_before_repeat = len(sent_photos)
    await tb.cb_mugs_order(FakeCallback("mugs_order:2:3", uid=uid, username="mugbuyer"))
    assert len(sent_photos) == photos_before_repeat
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
    assert tb.stats["mug_orders"][0]["model_name"] == "Наследие Академии"
    assert tb.stats["mug_orders"][0]["quantity"] == 3
    assert tb.stats["mug_orders"][0]["price_rub"] == 2547
    assert tb.get_confirmed_mug_order_count() == 3
    assert "@mugbuyer" in confirm.message.edits[0][0]
    assert any(chat_id == uid and "Оплата заказа подтверждена" in text for chat_id, text, _ in sent)
    assert "Наследие Академии" in tb.get_admin_mug_orders_text() and "@mugbuyer" in tb.get_admin_mug_orders_text()

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
    assert reject_key not in tb.stats["mug_order_requests"]
    await tb.cb_mugs_order(FakeCallback("mugs_order:3:1", uid=reject_uid, username="rejectbuyer"))
    reject = FakeCallback(f"admin_mug_reject:3:{reject_uid}", uid=ADMIN_ID)
    await tb.cb_admin_mug_reject(reject)
    assert reject_key not in tb.stats["mug_order_requests"]
    assert all(order["user_id"] != reject_uid for order in tb.stats["mug_orders"])

    # Requests created by the old view-on-select flow cannot be approved until the user taps
    # the new explicit confirmation button.
    legacy_uid = random.randint(10_000_000, 99_999_999)
    legacy_key = tb.get_mug_order_request_key("1", legacy_uid)
    tb.stats["mug_order_requests"][legacy_key] = {
        "request_key": legacy_key,
        "model_id": "1",
        "model_name": "Модель 1",
        "user_id": legacy_uid,
        "username": "legacybuyer",
        "full_name": "Legacy Buyer",
        "requested_at": 1,
    }
    legacy_confirm = FakeCallback(f"admin_mug_confirm:1:{legacy_uid}", uid=ADMIN_ID)
    await tb.cb_admin_mug_confirm(legacy_confirm)
    assert legacy_key in tb.stats["mug_order_requests"]
    assert all(order["user_id"] != legacy_uid for order in tb.stats["mug_orders"])
    assert legacy_confirm.answers and "ещё не подтвердил" in legacy_confirm.answers[-1][0]

    # Announcement: admin gets a three-photo preview; only the explicit second tap broadcasts it.
    announcement_text = tb.get_mug_announcement_text()
    assert "ЛИМИТИРОВАННАЯ КОЛЛЕКЦИЯ" in announcement_text
    assert all(spec["title"] in announcement_text for spec in tb.MUG_MODELS.values())
    assert all(str(spec["price_rub"]) in announcement_text for spec in tb.MUG_MODELS.values())
    assert "50" in announcement_text and "Подтвердить оплату и заказать" in announcement_text
    assert "подарок ко Дню учителя" in announcement_text
    assert "заказ отменить нельзя" in announcement_text and "Сроки доставки" in announcement_text
    preview = FakeCallback("admin_announce_mugs_confirm", uid=ADMIN_ID)
    albums_before_preview = len(sent_albums)
    await tb.cb_admin_announce_mugs_confirm(preview)
    assert len(preview.message.albums) == 1 and len(preview.message.albums[0][0]) == 3
    assert len(sent_albums) == albums_before_preview, "preview must not broadcast"
    assert "admin_announce_mugs_go" in callback_data(preview.message.edits[-1][1]["reply_markup"])

    tb.stats["total_users"] = {700001, 700002}
    broadcasts_before = tb.stats.get("broadcast_count", 0)
    go = FakeCallback("admin_announce_mugs_go", uid=ADMIN_ID)
    await tb.cb_admin_announce_mugs_go(go)
    assert len(sent_albums) == 2
    assert all(len(media) == 3 for _, media, _ in sent_albums)
    assert len([row for row in sent if row[0] in tb.stats["total_users"] and "ЛИМИТИРОВАННАЯ" in row[1]]) == 2
    assert tb.stats["broadcast_count"] == broadcasts_before + 1

    assert tb.stats["subscriptions"] == subscriptions_before, "mug flow must never touch subscriptions"
    tb.bot.send_message = original_send_message
    tb.bot.send_photo = original_send_photo
    tb.bot.send_media_group = original_send_media_group
    print("ALL MUG ORDER TESTS PASSED")


asyncio.run(main())
