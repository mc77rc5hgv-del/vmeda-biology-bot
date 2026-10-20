"""Badge order form. Separate storage; no changes to payments or subscriptions."""
import asyncio
import html
import secrets
import time
from weakref import WeakValueDictionary

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

import telegram_bot as tb
from services.badge_orders import (
    FIELDS, RECIPIENT_ID, ROLES, SCHEMA_VERSION, SPECIALTIES, customer_url, helper_url,
    order_template, preview, validate_value, validated_details,
)

router = Router()
_locks = WeakValueDictionary()


async def persist():
    result = tb.save_stats()
    if result is not None:
        await asyncio.shield(asyncio.wrap_future(result))


def draft_for(uid):
    draft = tb.stats.get("badge_drafts", {}).get(str(uid))
    if draft and not draft.get("submitted") and draft.get("schema_version") != SCHEMA_VERSION:
        old = draft["details"]
        draft["legacy_details"] = dict(old)
        draft["details"] = {
            "fio": " ".join(old.get(key, "") for key in ("surname", "name", "patronymic")).strip(),
            "role": old.get("role", ""), "quantity": old.get("quantity", ""),
        }
        draft["schema_version"] = SCHEMA_VERSION
        draft.pop("editing", None)
        draft["step"] = 0
        for index, field in enumerate(FIELDS):
            try:
                validate_value(index, draft["details"].get(field[0], ""))
            except ValueError:
                draft["step"] = index
                break
    return draft


def has_active_draft(uid):
    return bool((draft_for(uid) or {}).get("active"))


def keyboard(*rows):
    builder = InlineKeyboardBuilder()
    for text, callback in rows:
        builder.row(InlineKeyboardButton(text=text, callback_data=callback))
    return builder


def menu_keyboard(uid):
    builder = keyboard(("📝 Заполнить данные", "badges:start"))
    if draft_for(uid) and not draft_for(uid).get("submitted"):
        builder.row(InlineKeyboardButton(text="Продолжить заполнение", callback_data="badges:resume"))
    builder.row(InlineKeyboardButton(text="📋 Мои заявки", callback_data="badges:mine"))
    if uid == RECIPIENT_ID or tb.is_admin(uid) or tb.is_payment_admin(uid):
        builder.row(InlineKeyboardButton(text="📥 Заявки клиентов", callback_data="badges:admin:0"))
    builder.row(InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main"))
    return builder.as_markup()


async def show_menu(message, uid):
    await message.answer(
        "🪪 <b>Медицинские бейджики</b>\n\n"
        "Заполни данные точно так, как они должны быть напечатаны. "
        "В конце можно проверить и исправить каждое поле.\n\n"
        "<b>Образец заполнения</b>\n"
        "Фамилия Имя Отчество: Иванов Иван Иванович\n"
        "Статус: Курсант\nСпециальность: Лечебное дело\nКоличество: 1\n\n"
        "После подтверждения передадим заявку @vmeda_helper. "
        "Стоимость, макет и получение согласовываются отдельно. Это не оплата.",
        parse_mode="HTML", reply_markup=menu_keyboard(uid),
    )


async def show_step(message, draft):
    index = draft["step"]
    if index >= len(FIELDS):
        await show_review(message, draft)
        return
    key, label, example, _, _ = FIELDS[index]
    builder = InlineKeyboardBuilder()
    choices = ROLES if key == "role" else SPECIALTIES if key == "specialty" else ()
    for choice_index, choice in enumerate(choices):
        builder.row(InlineKeyboardButton(text=choice, callback_data=f"badges:choose:{key}:{choice_index}"))
    if key == "role":
        builder.row(InlineKeyboardButton(text="Свой вариант — ввести текстом", callback_data="badges:custom"))
    if index:
        builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="badges:back"))
    builder.row(InlineKeyboardButton(text="Сохранить и выйти", callback_data="badges:cancel"))
    await message.answer(f"🪪 Шаг {index + 1} из {len(FIELDS)}\n\n"
                         f"<b>{html.escape(label)}</b>\nПример: {html.escape(example)}\n\n"
                         "Выбери вариант кнопкой или отправь значение одним сообщением.", parse_mode="HTML", reply_markup=builder.as_markup())


async def show_review(message, draft):
    builder = keyboard(("✅ Подтвердить и отправить @vmeda_helper", f"badges:send:{draft['id']}"))
    for i, (_, label, *_) in enumerate(FIELDS):
        builder.row(InlineKeyboardButton(text=f"✏️ {label}", callback_data=f"badges:edit:{i}"))
    builder.row(InlineKeyboardButton(text="Сохранить и выйти", callback_data="badges:cancel"))
    await message.answer("🪪 <b>Проверь данные бейджика</b>\n\n" + preview(draft["details"]) +
                         "\n\nНажимая «Подтвердить», ты передаёшь эти данные @vmeda_helper для оформления заказа. "
                         "Стоимость и макет согласовываются отдельно.", parse_mode="HTML", reply_markup=builder.as_markup())


async def handle_input(message):
    draft = draft_for(message.from_user.id)
    if not draft or not draft.get("active"):
        return
    if (message.text or "").startswith("/"):
        draft["active"] = False
        await persist()
        from aiogram.dispatcher.event.bases import SkipHandler
        raise SkipHandler
    if draft["step"] >= len(FIELDS):
        await show_review(message, draft)
        return
    try:
        value = validate_value(draft["step"], message.text)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await accept_value(message, draft, value)


async def accept_value(message, draft, value):
    draft["details"][FIELDS[draft["step"]][0]] = value
    draft["step"] = len(FIELDS) if draft.pop("editing", False) else draft["step"] + 1
    await persist()
    await show_step(message, draft)


async def navigation_middleware(handler, event, data):
    draft = draft_for(event.from_user.id)
    if draft and draft.get("active") and not (event.data or "").startswith("badges:"):
        draft["active"] = False
        await persist()
    return await handler(event, data)


def result_keyboard(order):
    builder = InlineKeyboardBuilder()
    if order["delivery"] == "failed":
        builder.row(InlineKeyboardButton(text="Повторить отправку", callback_data=f"badges:send:{order['id']}"))
    builder.row(InlineKeyboardButton(text="💬 Открыть готовое сообщение @vmeda_helper", url=helper_url(order)))
    builder.row(InlineKeyboardButton(text="🪪 К бейджикам", callback_data="badges:menu"))
    return builder.as_markup()


async def show_result(message, order):
    sent = order["delivery"] == "sent"
    status = ("✅ Заявка отправлена @vmeda_helper." if sent else
              "Заявка сохранена. Автоматическая доставка не подтверждена. "
              "Открой готовое сообщение по кнопке ниже и отправь его самостоятельно.")
    await message.answer(f"{status}\nНомер: <code>{order['id']}</code>\n\n" + preview(order["details"]),
                         parse_mode="HTML", reply_markup=result_keyboard(order))


async def submit(callback, token):
    uid = callback.from_user.id
    lock = _locks.get(uid)
    if lock is None:
        lock = asyncio.Lock()
        _locks[uid] = lock
    async with lock:
        orders = tb.stats.setdefault("badge_orders", {})
        order = orders.get(token)
        if order and order["user_id"] != uid:
            await callback.answer("Заявка недоступна", show_alert=True)
            return
        if not order:
            draft = draft_for(uid)
            if not draft or draft["id"] != token or draft.get("step") != len(FIELDS):
                await callback.answer("Сначала заполни и проверь данные", show_alert=True)
                return
            try:
                details = validated_details(draft["details"])
            except ValueError:
                await callback.answer("Проверь заполнение всех полей", show_alert=True)
                return
            order = {"id": token, "user_id": uid, "username": callback.from_user.username,
                     "full_name": callback.from_user.full_name, "details": details, "schema_version": SCHEMA_VERSION,
                     "created_at": time.time(), "delivery": "prepared"}
            orders[token] = order
        await callback.answer()
        if order["delivery"] not in {"sent", "sending", "unknown"}:
            order["delivery"] = "sending"
            try:
                await persist()  # durable intent before any outgoing Telegram request
            except Exception:
                order["delivery"] = "prepared"
                tb.logger.exception("Не удалось сохранить заявку на бейджик %s", token)
                await callback.message.answer("Не удалось сохранить заявку. Отправка не выполнялась. Попробуй ещё раз.")
                return
            try:
                builder = InlineKeyboardBuilder()
                builder.row(InlineKeyboardButton(text="💬 Написать заказчику", url=customer_url(order)))
                sent = await tb.bot.send_message(RECIPIENT_ID, html.escape(order_template(order)),
                                                parse_mode="HTML", reply_markup=builder.as_markup())
            except (TelegramBadRequest, TelegramForbiddenError):
                order["delivery"] = "failed"
                tb.logger.warning("Telegram отклонил доставку заявки на бейджик %s", token)
            except Exception:
                order["delivery"] = "unknown"  # no blind retries after a timeout
                tb.logger.exception("Доставка заявки на бейджик %s не подтверждена", token)
            else:
                order["delivery"] = "sent"
                order["sent_at"] = time.time()
                order["message_id"] = getattr(sent, "message_id", None)
        draft = draft_for(uid)
        if draft and draft.get("id") == token:
            draft["active"] = False
            draft["submitted"] = True
        try:
            await persist()
        except Exception:
            tb.logger.exception("Не удалось сохранить статус доставки бейджика %s", token)
        await show_result(callback.message, order)


@router.callback_query(F.data.startswith("badges:"))
async def callback_badges(callback):
    if not callback.message or callback.message.chat.type != "private":
        await callback.answer("Заказ оформляется в личном чате с ботом", show_alert=True)
        return
    uid = callback.from_user.id
    parts = callback.data.split(":")
    action = parts[1]
    if action == "send" and len(parts) == 3:
        await submit(callback, parts[2])
        return
    if action == "admin":
        await show_admin_orders(callback, parts[-1])
        return
    draft = draft_for(uid)
    await callback.answer()
    if action == "menu":
        if draft:
            draft["active"] = False
            await persist()
        await show_menu(callback.message, uid)
    elif action == "start":
        draft = {"id": secrets.token_hex(8), "details": {}, "step": 0, "active": True, "schema_version": SCHEMA_VERSION}
        tb.stats.setdefault("badge_drafts", {})[str(uid)] = draft
        await persist()
        await show_step(callback.message, draft)
    elif action == "mine":
        orders = [o for o in tb.stats.get("badge_orders", {}).values() if o["user_id"] == uid]
        if not orders:
            await callback.message.answer("Заявок пока нет.", reply_markup=menu_keyboard(uid))
        for order in sorted(orders, key=lambda o: o["created_at"], reverse=True)[:10]:
            await show_result(callback.message, order)
    elif action == "cancel":
        if draft:
            draft["active"] = False
            await persist()
        await show_menu(callback.message, uid)
    elif draft and not draft.get("submitted"):
        if action == "resume":
            draft["active"] = True
        elif action == "back":
            draft["step"] = max(0, draft["step"] - 1)
        elif action == "choose" and len(parts) == 4 and parts[3].isdigit():
            index = draft["step"]
            if index >= len(FIELDS) or FIELDS[index][0] != parts[2]:
                await show_step(callback.message, draft)
                return
            choices = ROLES if parts[2] == "role" else SPECIALTIES if parts[2] == "specialty" else ()
            choice = int(parts[3])
            if choice >= len(choices):
                return
            draft["active"] = True
            await accept_value(callback.message, draft, validate_value(index, choices[choice]))
            return
        elif action == "custom" and draft["step"] == 1:
            draft["active"] = True
            await persist()
            await callback.message.answer("Введи свой статус одним сообщением, как он должен быть напечатан на бейдже.")
            return
        elif action == "edit" and len(parts) == 3 and parts[2].isdigit() and int(parts[2]) < len(FIELDS):
            draft["step"] = int(parts[2])
            draft["editing"] = True
            draft["active"] = True
        else:
            await show_menu(callback.message, uid)
            return
        draft["active"] = True
        await persist()
        await show_step(callback.message, draft)
    else:
        await show_menu(callback.message, uid)


async def show_admin_orders(callback, raw_page):
    if not (tb.is_admin(callback.from_user.id) or tb.is_payment_admin(callback.from_user.id)
            or callback.from_user.id == RECIPIENT_ID):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    orders = sorted(tb.stats.get("badge_orders", {}).values(), key=lambda o: o["created_at"], reverse=True)
    page = min(max(int(raw_page) if raw_page.isdigit() else 0, 0), max((len(orders) - 1) // 3, 0))
    for order in orders[page * 3:page * 3 + 3]:
        await callback.message.answer(html.escape(order_template(order)) + "\n\nДоставка: " + order["delivery"],
                                      parse_mode="HTML")
    builder = InlineKeyboardBuilder()
    if page:
        builder.button(text="⬅️", callback_data=f"badges:admin:{page - 1}")
    if (page + 1) * 3 < len(orders):
        builder.button(text="➡️", callback_data=f"badges:admin:{page + 1}")
    builder.row(InlineKeyboardButton(text="Главное меню", callback_data="back_to_main"))
    await callback.message.answer(f"🪪 Заявки на бейджики: {len(orders)}", reply_markup=builder.as_markup())
