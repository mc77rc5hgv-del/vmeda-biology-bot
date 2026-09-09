# -*- coding: utf-8 -*-
"""Temporary VMEDA mug preorder flow.

Pending requests and confirmed orders are intentionally stored separately. Merely choosing a
model never makes a user appear in the admin order register; only an admin/payment-admin payment
confirmation moves the immutable request snapshot into the confirmed list. Nothing here writes to
subscriptions, payments, temporary access, or other user-entitlement data.
"""
import html
import time
import urllib.parse

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

import telegram_bot as tb

router = Router()

MUG_SALES_TARGET = 50
MUG_ADMIN_PAGE_SIZE = 20
MUG_MODELS = {
    "1": "Модель 1",
    "2": "Модель 2",
    "3": "Модель 3",
}


def get_mug_order_request_key(model_id: str, user_id: int) -> str:
    return f"{model_id}:{user_id}"


def get_confirmed_mug_order_count() -> int:
    return len(tb.stats.get("mug_orders", []))


def _has_confirmed_order(model_id: str, user_id: int) -> bool:
    return any(
        str(order.get("model_id")) == model_id and order.get("user_id") == user_id
        for order in tb.stats.get("mug_orders", [])
    )


def get_mugs_menu_text() -> str:
    confirmed = get_confirmed_mug_order_count()
    return (
        f"☕ <b>Кружки VMEDA — предзаказ</b>\n{tb.DIVIDER}\n\n"
        "Мы готовим три авторские модели кружек VMEDA. Сейчас можно оставить предзаказ и "
        "связаться с менеджером для получения реквизитов.\n\n"
        "📸 Фотографии и 💳 цены добавим позже.\n\n"
        f"Подтверждено заказов: <b>{confirmed}</b> из <b>{MUG_SALES_TARGET}</b>\n\n"
        "Выбери модель:"
    )


def get_mugs_menu_keyboard():
    builder = InlineKeyboardBuilder()
    for model_id, title in MUG_MODELS.items():
        builder.button(text=f"☕ {title}", callback_data=f"mugs_model:{model_id}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()


def get_mug_model_text(model_id: str, request_exists: bool, already_confirmed: bool) -> str:
    title = MUG_MODELS[model_id]
    if already_confirmed:
        status = "✅ <b>Оплата этого заказа уже подтверждена.</b>"
    elif request_exists:
        status = (
            "📝 Заявка сохранена. Нажми кнопку ниже: менеджер пришлёт реквизиты, а после "
            "проверки перевода администратор подтвердит заказ."
        )
    else:
        status = "Нажми кнопку ниже, чтобы получить реквизиты у менеджера."
    return (
        f"☕ <b>{title}</b>\n{tb.DIVIDER}\n\n"
        "📸 Фото модели: <b>скоро</b>\n"
        "💳 Цена: <b>будет добавлена позже</b>\n\n"
        f"{status}"
    )


def get_mug_model_keyboard(model_id: str, user_id: int):
    title = MUG_MODELS[model_id]
    template = (
        f"Здравствуйте! Хочу заказать кружку VMEDA — {title}. "
        "Пришлите, пожалуйста, реквизиты для перевода. После оплаты отправлю подтверждение. "
        f"Мой Telegram ID: {user_id}."
    )
    url = f"{tb.HELPER_ACCOUNT_URL}?text={urllib.parse.quote(template)}"
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🛒 Заказать и подтвердить оплату", url=url))
    builder.row(InlineKeyboardButton(text="🔙 К моделям", callback_data="mugs_menu"))
    return builder.as_markup()


def get_admin_mug_request_text(request: dict) -> str:
    username = request.get("username")
    user_id = request["user_id"]
    label = tb.format_admin_target_label(username, user_id)
    return (
        f"☕ <b>Заявка на кружку VMEDA</b>\n{tb.DIVIDER}\n\n"
        f"Модель: <b>{html.escape(request['model_name'])}</b>\n"
        f"Пользователь: {label}\n\n"
        "Пользователь выбрал модель и получил кнопку перехода к @vmeda_helper. Подтверди заказ "
        "только после проверки перевода в диалоге. До подтверждения заявка не показывается "
        "в списке заказов."
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
            await tb.bot.send_message(recipient_id, text, parse_mode="HTML", reply_markup=keyboard)
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
        f"\nВсего: <b>{total}</b> из цели <b>{MUG_SALES_TARGET}</b>",
    ]
    if not page_orders:
        lines.append("\nПодтверждённых заказов пока нет.")
    else:
        lines.append("")
        for offset, order in enumerate(page_orders, start=start + 1):
            label = tb.format_admin_target_label(order.get("username"), order["user_id"])
            lines.append(f"{offset}. <b>{html.escape(order['model_name'])}</b> — {label}")
    if max_page:
        lines.append(f"\nСтраница <b>{page + 1}</b> из <b>{max_page + 1}</b>")
    return "\n".join(lines)


def get_admin_mug_orders_keyboard(page: int, back_callback: str):
    total = get_confirmed_mug_order_count()
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
    if not already_confirmed and request is None:
        request = {
            "request_key": request_key,
            "model_id": model_id,
            "model_name": MUG_MODELS[model_id],
            "user_id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "requested_at": time.time(),
        }
        tb.stats["mug_order_requests"][request_key] = request
        tb.save_stats()
        await notify_mug_order_admins(request)
    await callback.answer("Заявка уже подтверждена" if already_confirmed else "Заявка сохранена ✅")
    await tb.safe_edit_text(
        callback.message,
        get_mug_model_text(model_id, request is not None, already_confirmed),
        parse_mode="HTML",
        reply_markup=get_mug_model_keyboard(model_id, user.id),
        disable_web_page_preview=True,
    )


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
                f"{html.escape(MUG_MODELS.get(model_id, 'модель не найдена'))}.",
                parse_mode="HTML",
            )
        else:
            await callback.answer("Заявка не найдена или уже отклонена", show_alert=True)
        return

    order = dict(request)
    order["confirmed_at"] = time.time()
    order["confirmed_by"] = callback.from_user.id
    tb.stats["mug_orders"].append(order)
    del tb.stats["mug_order_requests"][request_key]
    tb.save_stats()
    await callback.answer("Оплата подтверждена ✅", show_alert=True)
    label = tb.format_admin_target_label(order.get("username"), user_id)
    await tb.safe_edit_text(
        callback.message,
        f"✅ Оплата подтверждена — <b>{html.escape(order['model_name'])}</b>, {label}. "
        "Заказ добавлен в панель кружек.",
        parse_mode="HTML",
    )
    try:
        await tb.bot.send_message(
            user_id,
            f"✅ <b>Оплата заказа подтверждена!</b>\n\n"
            f"Кружка VMEDA: <b>{html.escape(order['model_name'])}</b>.\n"
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
        f"❌ Заявка отклонена — <b>{html.escape(request['model_name'])}</b>, "
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
