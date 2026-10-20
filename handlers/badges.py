"""Badge order form and physical-goods checkout; subscriptions stay separate."""
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
    BULK_THRESHOLD, BULK_UNIT_PRICE_RUB, FIELDS, RECIPIENT_ID, RECIPIENT_USERNAME, ROLES, SCHEMA_VERSION, SPECIALTIES, UNIT_PRICE_RUB, customer_url, helper_url,
    order_template, preview, price_quote, pricing_text, validate_value, validated_details,
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
    builder.row(InlineKeyboardButton(text=f"👥 Заказать на группу ({BULK_THRESHOLD} шт.)",
                                     url=f"https://t.me/{RECIPIENT_USERNAME}"))
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
        f"<b>Стоимость</b>\n1–{BULK_THRESHOLD - 1} шт. — {UNIT_PRICE_RUB} ₽ за штуку\n"
        f"От {BULK_THRESHOLD} шт. — {BULK_UNIT_PRICE_RUB} ₽ за каждую\n\n"
        "После проверки данных можно оплатить заказ через СБП CodeePay. "
        "Макет и получение согласовываются с @vmeda_helper.\n\n"
        "👥 Заказ на группу — сразу в чат @vmeda_helper, без заполнения формы.",
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
    for index, field in enumerate(FIELDS):
        try:
            validate_value(index, draft["details"].get(field[0], ""))
        except ValueError:
            draft["step"] = index
            draft.pop("editing", None)
            await persist()
            await show_step(message, draft)
            return
    builder = keyboard(("✅ Подтвердить заказ", f"badges:send:{draft['id']}"))
    for i, (_, label, *_) in enumerate(FIELDS):
        builder.row(InlineKeyboardButton(text=f"✏️ {label}", callback_data=f"badges:edit:{i}"))
    builder.row(InlineKeyboardButton(text="Сохранить и выйти", callback_data="badges:cancel"))
    await message.answer("🪪 <b>Проверь данные бейджика</b>\n\n" + preview(draft["details"]) +
                         "\n\n<b>К оплате: " + pricing_text(price_quote(draft["details"]["quantity"])) + "</b>" +
                         "\n\nНажимая «Подтвердить», ты передаёшь эти данные @vmeda_helper для оформления заказа. "
                         "Затем можно оплатить заказ через СБП. Макет и получение согласовываются отдельно.", parse_mode="HTML", reply_markup=builder.as_markup())


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
    if order.get("pricing") and order.get("payment", {}).get("status") != "paid":
        builder.row(InlineKeyboardButton(text=f"🏦 Оплатить СБП · {order['pricing']['total_rub']} ₽",
                                         callback_data=f"badges:pay:{order['id']}"))
    if order.get("payment", {}).get("id"):
        builder.row(InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"badges:check:{order['id']}"))
    if order["delivery"] == "failed":
        builder.row(InlineKeyboardButton(text="Повторить отправку", callback_data=f"badges:send:{order['id']}"))
    builder.row(InlineKeyboardButton(text="💬 Открыть готовое сообщение @vmeda_helper", url=helper_url(order)))
    builder.row(InlineKeyboardButton(text="🪪 К бейджикам", callback_data="badges:menu"))
    return builder.as_markup()


async def show_result(message, order):
    if not order.get("pricing") and "fio" in order["details"]:
        try:
            details = validated_details(order["details"])
        except ValueError:
            details = None
        if details:
            order["pricing"] = price_quote(details["quantity"])
            await persist()
    sent = order["delivery"] == "sent"
    status = ("✅ Заявка отправлена @vmeda_helper." if sent else
              "Заявка сохранена. Автоматическая доставка не подтверждена. "
              "Открой готовое сообщение по кнопке ниже и отправь его самостоятельно.")
    payment = order.get("payment", {})
    if payment.get("status") == "paid":
        status += "\n✅ Оплата СБП подтверждена. Повторно платить не нужно."
    elif order.get("pricing"):
        status += "\nЗаказ пока не оплачен. Оплати его по кнопке СБП ниже."
    pricing = "\n\n<b>Стоимость: " + pricing_text(order["pricing"]) + "</b>" if order.get("pricing") else ""
    await message.answer(f"{status}\nНомер: <code>{order['id']}</code>\n\n" + preview(order["details"]) + pricing,
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
                     "created_at": time.time(), "delivery": "prepared", "pricing": price_quote(details["quantity"])}
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
    if action in {"pay", "check"} and len(parts) == 3:
        await payment_action(callback, parts[2], check=action == "check")
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
        notifications = order.get("payment_notifications", {})
        notice_status = "\nУведомление об оплате: " + str(notifications.get(str(RECIPIENT_ID), "—")) if order.get("payment") else ""
        await callback.message.answer(html.escape(order_template(order)) + "\n\nДоставка заявки: " + order["delivery"] + notice_status,
                                      parse_mode="HTML")
    builder = InlineKeyboardBuilder()
    if page:
        builder.button(text="⬅️", callback_data=f"badges:admin:{page - 1}")
    if (page + 1) * 3 < len(orders):
        builder.button(text="➡️", callback_data=f"badges:admin:{page + 1}")
    builder.row(InlineKeyboardButton(text="Главное меню", callback_data="back_to_main"))
    await callback.message.answer(f"🪪 Заявки на бейджики: {len(orders)}", reply_markup=builder.as_markup())


async def payment_action(callback, token, *, check=False):
    from services.payments.runtime import runtime
    from services.payments.contracts import ProviderNotReady, PaymentMismatch
    uid = callback.from_user.id
    order = tb.stats.get("badge_orders", {}).get(token)
    if not order or order["user_id"] != uid:
        await callback.answer("Заказ недоступен", show_alert=True)
        return
    await callback.answer()
    service = runtime(tb)
    if not service:
        await callback.message.answer("СБП временно недоступна. Заказ сохранён. Попробуй позже или напиши @vmeda_helper.")
        return
    if order.get("payment", {}).get("status") == "paid":
        await show_result(callback.message, order)
        return
    try:
        if check:
            row = (service.ledger.get(order.get("payment", {}).get("id", ""))
                   or service.ledger.existing(uid, "badge_" + token))
            if not row or row['user_id'] != uid or row.get('kind') != 'badge' or row['subject'] != token:
                raise ValueError("Счёт не найден. Нажми «Оплатить СБП».")
            row = await service.check(row)
        else:
            # Freeze a server-calculated quote before any provider I/O, including old v2 orders.
            lock = _locks.get(uid)
            if lock is None:
                lock = asyncio.Lock()
                _locks[uid] = lock
            async with lock:
                details = validated_details(order["details"])
                order.setdefault("pricing", price_quote(details["quantity"]))
                await persist()
            row = await service.checkout_badge(uid, token)
        if order.get("payment", {}).get("status") != "paid":
            order["payment"] = {"id": row["id"], "status": row["state"]}
            await persist()
    except (ProviderNotReady, PaymentMismatch):
        existing = service.ledger.existing(uid, "badge_" + token)
        if existing and order.get("payment", {}).get("status") != "paid":
            order["payment"] = {"id": existing["id"], "status": existing["state"]}
            await persist()
        await callback.message.answer("Создание или проверка счёта не подтверждены. Не оплачивай повторно. "
                                      "Счёт продолжит проверяться; при необходимости напиши @vmeda_helper.")
        return
    except ValueError as exc:
        await callback.message.answer(str(exc))
        return
    except Exception:
        tb.logger.exception("Badge checkout unavailable for order %s", token)
        await callback.message.answer("Не удалось подготовить оплату. Заказ сохранён. Попробуй позже или напиши @vmeda_helper.")
        return
    if row["state"] in {"applied", "review", "resolved_keep"}:
        if row["state"] != "applied":
            await callback.message.answer("Оплата получена. Заказ требует сверки с @vmeda_helper; повторно платить не нужно.")
        else:
            await show_result(callback.message, order)
        return
    if row["state"] in {"cancelled", "failed", "creation_closed"}:
        await callback.message.answer("Счёт отменён, истёк или закрыт после сверки. Заказ сохранён. "
                                      "Не оплачивай старую ссылку; напиши @vmeda_helper для безопасного продолжения.")
        return
    builder = InlineKeyboardBuilder()
    if row["state"] == "pending" and row["url"]:
        builder.row(InlineKeyboardButton(text=f"🏦 Оплатить {row['amount_minor'] // 100} ₽", url=row["url"]))
    builder.row(InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"badges:check:{token}"))
    builder.row(InlineKeyboardButton(text="🪪 Мои заявки", callback_data="badges:mine"))
    await callback.message.answer("🪪 Заказ бейджиков\n" + pricing_text(order["pricing"]) +
                                  "\n\nОплата проверяется автоматически. После подтверждения уведомим тебя и @vmeda_helper."
                                  "\nНе создавай повторный заказ для оплаты этого же счёта.\nПлатёж: " + row["id"],
                                  reply_markup=builder.as_markup())
