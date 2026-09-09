# -*- coding: utf-8 -*-
"""Temporary VMEDA mug preorder flow.

Pending requests and confirmed orders are intentionally stored separately. Merely choosing a
model never makes a user appear in the admin order register; only an admin/payment-admin payment
confirmation moves the immutable request snapshot into the confirmed list. Nothing here writes to
subscriptions, payments, temporary access, or other user-entitlement data.
"""
import asyncio
import html
import time
import urllib.parse
from pathlib import Path

from aiogram import F, Router
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InputMediaPhoto
from aiogram.utils.keyboard import InlineKeyboardBuilder

import telegram_bot as tb

router = Router()

MUG_SALES_TARGET = 50
MUG_ADMIN_PAGE_SIZE = 20
MUG_MAX_QUANTITY = 50
MUG_MODELS = {
    "1": {
        "title": "Классика ВМедА",
        "price_rub": 799,
        "image": "images/mugs/vmeda-classic.png",
        "asset_version": 2,
        "description": "Герб, надпись «ВМедА · Санкт-Петербург · 1798» и фасад Академии.",
    },
    "2": {
        "title": "Наследие Академии",
        "price_rub": 849,
        "image": "images/mugs/academy-heritage.png",
        "description": "Парадная композиция с гербом, полным названием Академии, историческим фасадом и латинским девизом.",
    },
    "3": {
        "title": "Штаб ВМедА",
        "price_rub": 999,
        "image": "images/mugs/where-doctors-grow.png",
        "description": "Двусторонний дизайн: герб и девиз — с одной стороны, памятник и фасад Академии — с другой.",
    },
}


def get_mug_model(model_id: str) -> dict:
    return MUG_MODELS[model_id]


def get_mug_model_title(model_id: str) -> str:
    return get_mug_model(model_id)["title"]


def get_mug_image_path(model_id: str) -> Path:
    return Path(__file__).resolve().parents[1] / get_mug_model(model_id)["image"]


def get_mug_photo_cache_key(model_id: str) -> str:
    model = get_mug_model(model_id)
    return f"{model_id}:{model.get('asset_version', 1)}"


def get_mug_photo(model_id: str):
    cache_key = get_mug_photo_cache_key(model_id)
    return tb.stats.get("mug_file_ids", {}).get(cache_key) or FSInputFile(get_mug_image_path(model_id))


def cache_mug_photo(model_id: str, sent_message) -> bool:
    photo_sizes = getattr(sent_message, "photo", None)
    if not photo_sizes:
        return False
    file_id = photo_sizes[-1].file_id
    cache_key = get_mug_photo_cache_key(model_id)
    if tb.stats["mug_file_ids"].get(cache_key) == file_id:
        return False
    tb.stats["mug_file_ids"][cache_key] = file_id
    return True


def build_mug_album():
    return [
        InputMediaPhoto(
            media=get_mug_photo(model_id),
            caption=(
                f"<b>{position}/3 · {html.escape(spec['title'])}</b>\n"
                f"{html.escape(spec['description'])}\n\n<b>{spec['price_rub']} ₽</b>"
            ),
            parse_mode="HTML",
        )
        for position, (model_id, spec) in enumerate(MUG_MODELS.items(), start=1)
    ]


def cache_mug_album(sent_messages) -> None:
    changed = False
    for model_id, message in zip(MUG_MODELS, sent_messages or []):
        changed = cache_mug_photo(model_id, message) or changed
    if changed:
        tb.save_stats()


def get_mug_order_request_key(model_id: str, user_id: int) -> str:
    return f"{model_id}:{user_id}"


def get_confirmed_mug_order_count() -> int:
    return sum(max(1, int(order.get("quantity", 1))) for order in tb.stats.get("mug_orders", []))


def _has_confirmed_order(model_id: str, user_id: int) -> bool:
    return any(
        str(order.get("model_id")) == model_id and order.get("user_id") == user_id
        for order in tb.stats.get("mug_orders", [])
    )


def get_mugs_menu_text() -> str:
    confirmed = get_confirmed_mug_order_count()
    return (
        f"☕ <b>Кружки VMEDA — предзаказ</b>\n{tb.DIVIDER}\n\n"
        "Три авторские модели лимитированной коллекции VMEDA. Сейчас можно оставить предзаказ и "
        "связаться с менеджером для получения реквизитов.\n\n"
        "🎁 <b>Идеальный подарок ко Дню учителя.</b>\n\n"
        "Обрати внимание: к сожалению, после подтверждения оплаты заказ отменить нельзя. Сроки доставки "
        "уточняйте у менеджера @vmeda_helper.\n\n"
        "Фотография и цена откроются после выбора модели.\n\n"
        f"Подтверждено кружек: <b>{confirmed}</b> из <b>{MUG_SALES_TARGET}</b>\n\n"
        "Выбери модель:"
    )


def get_mugs_menu_keyboard():
    builder = InlineKeyboardBuilder()
    for model_id, spec in MUG_MODELS.items():
        builder.button(
            text=f"{model_id}. {spec['title']} · {spec['price_rub']} ₽",
            callback_data=f"mugs_model:{model_id}",
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()


def get_mug_model_text(
    model_id: str,
    request_exists: bool,
    already_confirmed: bool,
    quantity: int = 1,
) -> str:
    model = get_mug_model(model_id)
    title = model["title"]
    quantity = min(max(int(quantity), 1), MUG_MAX_QUANTITY)
    total_price = model["price_rub"] * quantity
    if already_confirmed:
        status = "✅ <b>Оплата этого заказа уже подтверждена.</b>"
    elif request_exists:
        status = (
            "⏳ <b>Заявка отправлена.</b> Администратор проверяет перевод. После подтверждения "
            "бот сообщит, что заказ принят."
        )
    else:
        status = (
            "Сначала получи реквизиты у менеджера. После перевода вернись сюда и нажми "
            "«Подтвердить оплату и заказать»."
        )
    return (
        f"☕ <b>{title}</b>\n{tb.DIVIDER}\n\n"
        f"{html.escape(model['description'])}\n\n"
        "🎁 <b>Идеальный подарок ко Дню учителя.</b>\n\n"
        f"Количество: <b>{quantity} шт.</b>\n"
        f"Цена за одну: <b>{model['price_rub']} ₽</b>\n"
        f"Итого: <b>{total_price} ₽</b>\n\n"
        "К сожалению, после подтверждения оплаты заказ отменить нельзя. Сроки доставки уточняйте у "
        "менеджера @vmeda_helper.\n\n"
        f"{status}"
    )


def get_mug_model_keyboard(
    model_id: str,
    user_id: int,
    request_exists: bool,
    already_confirmed: bool,
    quantity: int = 1,
):
    quantity = min(max(int(quantity), 1), MUG_MAX_QUANTITY)
    title = get_mug_model_title(model_id)
    template = (
        f"Здравствуйте! Хочу заказать кружку VMEDA — {title}. "
        f"Количество: {quantity} шт. Пришлите, пожалуйста, реквизиты для перевода."
    )
    url = f"{tb.HELPER_ACCOUNT_URL}?text={urllib.parse.quote(template)}"
    builder = InlineKeyboardBuilder()
    if not request_exists and not already_confirmed:
        decrease_callback = (
            f"mugs_qty:{model_id}:{quantity - 1}" if quantity > 1 else "mugs_quantity_status"
        )
        increase_callback = (
            f"mugs_qty:{model_id}:{quantity + 1}"
            if quantity < MUG_MAX_QUANTITY
            else "mugs_quantity_status"
        )
        builder.row(
            InlineKeyboardButton(text="➖", callback_data=decrease_callback),
            InlineKeyboardButton(text=f"{quantity} шт.", callback_data="mugs_quantity_status"),
            InlineKeyboardButton(text="➕", callback_data=increase_callback),
        )
    builder.row(InlineKeyboardButton(text="💳 Получить реквизиты", url=url))
    if already_confirmed:
        builder.row(InlineKeyboardButton(text="✅ Заказ подтверждён", callback_data="mugs_order_status"))
    elif request_exists:
        builder.row(InlineKeyboardButton(text="⏳ Оплата проверяется", callback_data="mugs_order_status"))
    else:
        builder.row(
            InlineKeyboardButton(
                text="✅ Подтвердить оплату и заказать",
                callback_data=f"mugs_order:{model_id}:{quantity}",
            )
        )
    builder.row(InlineKeyboardButton(text="🔙 К моделям", callback_data="mugs_menu"))
    return builder.as_markup()


def get_admin_mug_request_text(request: dict) -> str:
    username = request.get("username")
    user_id = request["user_id"]
    label = tb.format_admin_target_label(username, user_id)
    return (
        f"☕ <b>Заявка на кружку VMEDA</b>\n{tb.DIVIDER}\n\n"
        f"Модель: <b>{html.escape(request['model_name'])}</b>\n"
        f"Количество: <b>{request.get('quantity', 1)} шт.</b>\n"
        f"Сумма: <b>{request['price_rub']} ₽</b>\n"
        f"Пользователь: {label}\n\n"
        "Пользователь нажал «Подтвердить оплату и заказать». Подтверди заказ только после "
        "проверки перевода в диалоге с @vmeda_helper. До админского подтверждения заявка не "
        "показывается в списке заказов."
    )


def get_admin_mug_request_keyboard(model_id: str, user_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить оплату", callback_data=f"admin_mug_confirm:{model_id}:{user_id}")
    builder.button(text="❌ Отклонить", callback_data=f"admin_mug_reject:{model_id}:{user_id}")
    builder.adjust(1)
    return builder.as_markup()


async def notify_mug_order_admins(request: dict) -> None:
    text = get_admin_mug_request_text(request)
    keyboard = get_admin_mug_request_keyboard(str(request["model_id"]), request["user_id"])
    for recipient_id in tb.ADMIN_IDS | set(tb.stats["payment_admins"]):
        try:
            sent = await tb.bot.send_photo(
                recipient_id,
                get_mug_photo(str(request["model_id"])),
                caption=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
            if cache_mug_photo(str(request["model_id"]), sent):
                tb.save_stats()
        except Exception:
            tb.logger.exception("Не удалось уведомить админа %s о заявке на кружку", recipient_id)


def get_admin_mug_orders_text(page: int = 0) -> str:
    orders = list(reversed(tb.stats.get("mug_orders", [])))
    total = len(orders)
    max_page = max(0, (total - 1) // MUG_ADMIN_PAGE_SIZE)
    page = min(max(page, 0), max_page)
    start = page * MUG_ADMIN_PAGE_SIZE
    page_orders = orders[start:start + MUG_ADMIN_PAGE_SIZE]
    lines = [
        f"☕ <b>Подтверждённые заказы кружек</b>\n{tb.DIVIDER}",
        f"\nЗаказов: <b>{total}</b> · кружек: <b>{get_confirmed_mug_order_count()}</b> "
        f"из цели <b>{MUG_SALES_TARGET}</b>",
    ]
    if not page_orders:
        lines.append("\nПодтверждённых заказов пока нет.")
    else:
        lines.append("")
        for offset, order in enumerate(page_orders, start=start + 1):
            label = tb.format_admin_target_label(order.get("username"), order["user_id"])
            spec = MUG_MODELS.get(str(order.get("model_id")), {})
            title = spec.get("title", order["model_name"])
            quantity = max(1, int(order.get("quantity", 1)))
            total_price = order.get("price_rub")
            if total_price is None and spec.get("price_rub") is not None:
                total_price = spec["price_rub"] * quantity
            price_text = f" · {quantity} шт. · {total_price} ₽" if total_price is not None else f" · {quantity} шт."
            lines.append(f"{offset}. <b>{html.escape(title)}</b>{price_text} — {label}")
    if max_page:
        lines.append(f"\nСтраница <b>{page + 1}</b> из <b>{max_page + 1}</b>")
    return "\n".join(lines)


def get_admin_mug_orders_keyboard(page: int, back_callback: str):
    total = len(tb.stats.get("mug_orders", []))
    max_page = max(0, (total - 1) // MUG_ADMIN_PAGE_SIZE)
    page = min(max(page, 0), max_page)
    builder = InlineKeyboardBuilder()
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"admin_mug_orders:{page - 1}"))
    if page < max_page:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"admin_mug_orders:{page + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔄 Обновить", callback_data=f"admin_mug_orders:{page}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=back_callback))
    return builder.as_markup()


@router.callback_query(F.data == "mugs_menu")
async def cb_mugs_menu(callback: CallbackQuery):
    if not tb.MUG_PREORDER_ENABLED:
        await callback.answer("Предзаказ завершён", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        get_mugs_menu_text(),
        parse_mode="HTML",
        reply_markup=get_mugs_menu_keyboard(),
    )


@router.callback_query(F.data.startswith("mugs_model:"))
async def cb_mugs_model(callback: CallbackQuery):
    if not tb.MUG_PREORDER_ENABLED:
        await callback.answer("Предзаказ завершён", show_alert=True)
        return
    model_id = callback.data.split(":", 1)[1]
    if model_id not in MUG_MODELS:
        await callback.answer("Модель не найдена", show_alert=True)
        return
    user = callback.from_user
    request_key = get_mug_order_request_key(model_id, user.id)
    already_confirmed = _has_confirmed_order(model_id, user.id)
    request = tb.stats["mug_order_requests"].get(request_key)
    request_exists = bool(request and request.get("user_confirmed_at"))
    quantity = max(1, int(request.get("quantity", 1))) if request_exists else 1
    if already_confirmed:
        confirmed_order = next(
            order
            for order in tb.stats.get("mug_orders", [])
            if str(order.get("model_id")) == model_id and order.get("user_id") == user.id
        )
        quantity = max(1, int(confirmed_order.get("quantity", 1)))
    await callback.answer()
    await callback.message.delete()
    sent = await callback.message.answer_photo(
        get_mug_photo(model_id),
        caption=get_mug_model_text(model_id, request_exists, already_confirmed, quantity),
        parse_mode="HTML",
        reply_markup=get_mug_model_keyboard(model_id, user.id, request_exists, already_confirmed, quantity),
    )
    if cache_mug_photo(model_id, sent):
        tb.save_stats()


@router.callback_query(F.data.startswith("mugs_qty:"))
async def cb_mugs_quantity(callback: CallbackQuery):
    if not tb.MUG_PREORDER_ENABLED:
        await callback.answer("Предзаказ завершён", show_alert=True)
        return
    _, model_id, quantity_raw = callback.data.split(":")
    if model_id not in MUG_MODELS:
        await callback.answer("Модель не найдена", show_alert=True)
        return
    quantity = min(max(int(quantity_raw), 1), MUG_MAX_QUANTITY)
    user = callback.from_user
    request_key = get_mug_order_request_key(model_id, user.id)
    request = tb.stats["mug_order_requests"].get(request_key)
    request_exists = bool(request and request.get("user_confirmed_at"))
    already_confirmed = _has_confirmed_order(model_id, user.id)
    if request_exists or already_confirmed:
        await callback.answer("Количество уже зафиксировано в заказе", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_caption(
        caption=get_mug_model_text(model_id, False, False, quantity),
        parse_mode="HTML",
        reply_markup=get_mug_model_keyboard(model_id, user.id, False, False, quantity),
    )


@router.callback_query(F.data.startswith("mugs_order:"))
async def cb_mugs_order(callback: CallbackQuery):
    if not tb.MUG_PREORDER_ENABLED:
        await callback.answer("Предзаказ завершён", show_alert=True)
        return
    parts = callback.data.split(":")
    model_id = parts[1]
    if model_id not in MUG_MODELS:
        await callback.answer("Модель не найдена", show_alert=True)
        return
    try:
        quantity = min(max(int(parts[2]), 1), MUG_MAX_QUANTITY) if len(parts) > 2 else 1
    except ValueError:
        await callback.answer("Некорректное количество", show_alert=True)
        return
    user = callback.from_user
    if _has_confirmed_order(model_id, user.id):
        await callback.answer("Этот заказ уже подтверждён", show_alert=True)
        return
    request_key = get_mug_order_request_key(model_id, user.id)
    request = tb.stats["mug_order_requests"].get(request_key)
    should_notify = not request or not request.get("user_confirmed_at")
    if should_notify:
        now = time.time()
        request = {
            "request_key": request_key,
            "model_id": model_id,
            "model_name": get_mug_model_title(model_id),
            "quantity": quantity,
            "unit_price_rub": get_mug_model(model_id)["price_rub"],
            "price_rub": get_mug_model(model_id)["price_rub"] * quantity,
            "user_id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "requested_at": request.get("requested_at", now) if request else now,
            "user_confirmed_at": now,
        }
        tb.stats["mug_order_requests"][request_key] = request
        tb.save_stats()
        await notify_mug_order_admins(request)
    await callback.answer(
        "Заявка отправлена администратору. Оплату проверят вручную.",
        show_alert=True,
    )
    await callback.message.edit_caption(
        caption=get_mug_model_text(model_id, True, False, request.get("quantity", 1)),
        parse_mode="HTML",
        reply_markup=get_mug_model_keyboard(model_id, user.id, True, False, request.get("quantity", 1)),
    )


@router.callback_query(F.data == "mugs_order_status")
async def cb_mugs_order_status(callback: CallbackQuery):
    await callback.answer("Статус заказа уже отображён на кнопке", show_alert=True)


@router.callback_query(F.data == "mugs_quantity_status")
async def cb_mugs_quantity_status(callback: CallbackQuery):
    await callback.answer("Выберите количество кнопками − и +")


def _parse_admin_order_callback(callback_data: str):
    _, model_id, user_id_raw = callback_data.split(":")
    return model_id, int(user_id_raw)


@router.callback_query(F.data.startswith("admin_mug_confirm:"))
async def cb_admin_mug_confirm(callback: CallbackQuery):
    if not (tb.is_admin(callback.from_user.id) or tb.is_payment_admin(callback.from_user.id)):
        await callback.answer()
        return
    model_id, user_id = _parse_admin_order_callback(callback.data)
    request_key = get_mug_order_request_key(model_id, user_id)
    request = tb.stats["mug_order_requests"].get(request_key)
    if request is None:
        if _has_confirmed_order(model_id, user_id):
            await callback.answer("Уже подтверждено другим администратором", show_alert=True)
            await tb.safe_edit_text(
                callback.message,
                f"✅ Заказ уже подтверждён — {tb.get_known_admin_target_label(user_id)}, "
                f"{html.escape(MUG_MODELS.get(model_id, {}).get('title', 'модель не найдена'))}.",
                parse_mode="HTML",
            )
        else:
            await callback.answer("Заявка не найдена или уже отклонена", show_alert=True)
        return

    if not request.get("user_confirmed_at"):
        await callback.answer("Пользователь ещё не подтвердил оплату и заказ", show_alert=True)
        return

    order = dict(request)
    order["model_name"] = get_mug_model_title(model_id)
    order["quantity"] = max(1, int(order.get("quantity", 1)))
    order["unit_price_rub"] = get_mug_model(model_id)["price_rub"]
    order["price_rub"] = order["unit_price_rub"] * order["quantity"]
    order["confirmed_at"] = time.time()
    order["confirmed_by"] = callback.from_user.id
    tb.stats["mug_orders"].append(order)
    del tb.stats["mug_order_requests"][request_key]
    tb.save_stats()
    await callback.answer("Оплата подтверждена ✅", show_alert=True)
    label = tb.format_admin_target_label(order.get("username"), user_id)
    await tb.safe_edit_text(
        callback.message,
        f"✅ Оплата подтверждена — <b>{html.escape(order['model_name'])}</b>, "
        f"<b>{order['quantity']} шт.</b>, <b>{order['price_rub']} ₽</b>, {label}. "
        "Заказ добавлен в панель кружек.",
        parse_mode="HTML",
    )
    try:
        await tb.bot.send_message(
            user_id,
            f"✅ <b>Оплата заказа подтверждена!</b>\n\n"
            f"Кружка VMEDA: <b>{html.escape(order['model_name'])}</b> — "
            f"<b>{order['quantity']} шт.</b>, <b>{order['price_rub']} ₽</b>.\n"
            "Заказ принят. Менеджер @vmeda_helper сообщит дальнейшие детали.",
            parse_mode="HTML",
        )
    except Exception:
        tb.logger.exception("Не удалось уведомить пользователя %s о подтверждении заказа кружки", user_id)


@router.callback_query(F.data.startswith("admin_mug_reject:"))
async def cb_admin_mug_reject(callback: CallbackQuery):
    if not (tb.is_admin(callback.from_user.id) or tb.is_payment_admin(callback.from_user.id)):
        await callback.answer()
        return
    model_id, user_id = _parse_admin_order_callback(callback.data)
    request_key = get_mug_order_request_key(model_id, user_id)
    request = tb.stats["mug_order_requests"].pop(request_key, None)
    if request is None:
        await callback.answer("Заявка уже обработана", show_alert=True)
        return
    tb.save_stats()
    await callback.answer("Заявка отклонена", show_alert=True)
    await tb.safe_edit_text(
        callback.message,
        f"❌ Заявка отклонена — <b>{html.escape(get_mug_model_title(model_id))}</b>, "
        f"{tb.format_admin_target_label(request.get('username'), user_id)}.",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_mug_orders:"))
async def cb_admin_mug_orders(callback: CallbackQuery):
    if not (tb.is_admin(callback.from_user.id) or tb.is_payment_admin(callback.from_user.id)):
        await callback.answer()
        return
    page = int(callback.data.split(":", 1)[1])
    await callback.answer()
    back_callback = "admin_panel" if tb.is_admin(callback.from_user.id) else "payment_admin_panel"
    await tb.safe_edit_text(
        callback.message,
        get_admin_mug_orders_text(page),
        parse_mode="HTML",
        reply_markup=get_admin_mug_orders_keyboard(page, back_callback),
    )


def get_mug_announcement_text() -> str:
    confirmed = get_confirmed_mug_order_count()
    return (
        f"☕ <b>ЛИМИТИРОВАННАЯ КОЛЛЕКЦИЯ VMEDA</b>\n{tb.DIVIDER}\n\n"
        "Три авторских дизайна, в которых узнаётся Академия: её герб, история, фасад и слова, "
        "понятные каждому, кто здесь учится.\n\n"
        "🎁 <b>Идеальный подарок ко Дню учителя.</b>\n\n"
        "<b>1 · Классика ВМедА — 799 ₽</b>\nЛаконичный герб и фасад Академии.\n\n"
        "<b>2 · Наследие Академии — 849 ₽</b>\nПарадная историческая композиция.\n\n"
        "<b>3 · Штаб ВМедА — 999 ₽</b>\nДвусторонний дизайн с символами ВМедА.\n\n"
        "Это ограниченный первый выпуск. Для запуска партии нужно минимум <b>50 подтверждённых "
        f"кружек</b>; уже подтверждено: <b>{confirmed}</b>.\n\n"
        "К сожалению, после подтверждения оплаты заказ отменить нельзя. Сроки доставки уточняйте у "
        "менеджера @vmeda_helper.\n\n"
        "Выбери свой дизайн в боте, получи реквизиты у менеджера и после перевода нажми "
        "«Подтвердить оплату и заказать»."
    )


def get_mug_announcement_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="Посмотреть коллекцию", callback_data="mugs_menu")
    return builder.as_markup()


def get_admin_mug_announcement_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить всем", callback_data="admin_announce_mugs_go")
    builder.button(text="❌ Отмена", callback_data="admin_announcements_menu")
    builder.adjust(1)
    return builder.as_markup()


async def send_mug_album_to_chat(chat_id: int) -> None:
    sent_messages = await tb.bot.send_media_group(chat_id, media=build_mug_album())
    cache_mug_album(sent_messages)


async def broadcast_mug_announcement() -> tuple[int, int]:
    sent_count = 0
    failed_count = 0
    text = get_mug_announcement_text()
    keyboard = get_mug_announcement_keyboard()
    for user_id in list(tb.stats["total_users"]):
        try:
            await send_mug_album_to_chat(user_id)
            await tb.bot.send_message(
                user_id,
                text,
                parse_mode="HTML",
                reply_markup=keyboard,
                disable_web_page_preview=True,
            )
            sent_count += 1
        except Exception:
            failed_count += 1
            tb.logger.exception("Не удалось отправить анонс кружек пользователю %s", user_id)
        await asyncio.sleep(0.05)
    return sent_count, failed_count


@router.callback_query(F.data == "admin_announce_mugs_confirm")
async def cb_admin_announce_mugs_confirm(callback: CallbackQuery):
    if not (tb.is_admin(callback.from_user.id) or tb.is_payment_admin(callback.from_user.id)):
        await callback.answer()
        return
    await callback.answer()
    try:
        sent_messages = await callback.message.answer_media_group(media=build_mug_album())
        cache_mug_album(sent_messages)
    except Exception:
        tb.logger.exception("Не удалось показать альбом кружек в предпросмотре анонса")
    await tb.safe_edit_text(
        callback.message,
        f"👀 <b>Предпросмотр анонса</b>\n{tb.DIVIDER}\n\n"
        f"{get_mug_announcement_text()}\n\n{tb.DIVIDER}\n"
        f"Отправить этот альбом и текст всем {len(tb.stats['total_users'])} пользователям?",
        parse_mode="HTML",
        reply_markup=get_admin_mug_announcement_keyboard(),
    )


@router.callback_query(F.data == "admin_announce_mugs_go")
async def cb_admin_announce_mugs_go(callback: CallbackQuery):
    if not (tb.is_admin(callback.from_user.id) or tb.is_payment_admin(callback.from_user.id)):
        await callback.answer()
        return
    await callback.answer("Рассылка запущена", show_alert=True)
    tb.stats["broadcast_count"] = tb.stats.get("broadcast_count", 0) + 1
    tb.save_stats()
    sent_count, failed_count = await broadcast_mug_announcement()
    back_callback = "admin_panel" if tb.is_admin(callback.from_user.id) else "payment_admin_panel"
    await tb.safe_edit_text(
        callback.message,
        f"✅ <b>Анонс коллекции отправлен</b>\n{tb.DIVIDER}\n\n"
        f"Доставлено: <b>{sent_count}</b>\nНе доставлено: <b>{failed_count}</b>",
        parse_mode="HTML",
        reply_markup=tb.get_admin_announcements_keyboard(back_callback),
    )
