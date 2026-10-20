"""Validated, bounded badge details and a shared human-readable order template."""
import html
import re
from urllib.parse import quote

RECIPIENT_ID = 8928384363
RECIPIENT_USERNAME = "vmeda_helper"
LEGACY_FIELDS = (
    ("surname", "Фамилия", "Иванов", 60, False),
    ("name", "Имя", "Иван", 60, False),
    ("patronymic", "Отчество", "Иванович", 60, True),
    ("role", "Должность / статус", "Курсант / Студент / Врач", 100, False),
    ("organization", "Организация", "Военно-медицинская академия", 150, False),
    ("quantity", "Количество", "1", 3, False),
    ("contact", "Контакт для связи", "@username или номер телефона", 80, False),
)


SCHEMA_VERSION = 2
UNIT_PRICE_RUB = 530
BULK_UNIT_PRICE_RUB = 430
BULK_THRESHOLD = 15
SPECIALTIES = ("Лечебное дело", "Стоматология", "Медико-профилактическое дело")
ROLES = ("Студент", "Курсант")
FIELDS = (
    ("fio", "Фамилия Имя Отчество", "Иванов Иван Иванович", 180, False),
    ("role", "Статус", "Студент / Курсант / свой вариант", 100, False),
    ("specialty", "Специальность", " / ".join(SPECIALTIES), 60, False),
    ("quantity", "Количество", "1", 3, False),
)


def display_fields(details):
    return LEGACY_FIELDS if "surname" in details and "fio" not in details else FIELDS


def validate_value(index, raw):
    key, label, _, limit, optional = FIELDS[index]
    value = " ".join((raw or "").split())
    if optional and value in {"-", "—"}:
        return ""
    if not value or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(f"{label}: от 1 до {limit} символов.")
    if key == "quantity":
        if not value.isascii() or not value.isdigit() or not 1 <= int(value) <= 100:
            raise ValueError("Количество: целое число от 1 до 100.")
        return str(int(value))
    if key == "fio" and not any(c.isalpha() for c in value):
        raise ValueError("Укажи имя текстом, как оно должно быть напечатано.")
    if key == "specialty":
        for specialty in SPECIALTIES:
            if value.casefold() == specialty.casefold():
                return specialty
        raise ValueError("Выбери специальность: " + ", ".join(SPECIALTIES) + ".")
    return value


def validated_details(details):
    return {field[0]: ("" if field[4] and not details.get(field[0]) else validate_value(i, details.get(field[0], "")))
            for i, field in enumerate(FIELDS)}


def order_template(order):
    details = order["details"]
    lines = ["ЗАКАЗ МЕДИЦИНСКИХ БЕЙДЖИКОВ", f"Заявка: {order['id']}", ""]
    lines.extend(f"{label}: {details[key] or 'не указывать'}" for key, label, *_ in display_fields(details))
    lines += ["", f"Заказчик: {order.get('full_name', '')}", f"Telegram ID: {order['user_id']}"]
    if order.get("username"):
        lines.append(f"Telegram: @{order['username']}")
    if order.get("pricing"):
        lines.append("Стоимость: " + pricing_text(order["pricing"]))
    payment = order.get("payment", {})
    if payment.get("status") == "paid":
        lines += ["ОПЛАЧЕНО · СБП CodeePay", f"Платёж: {payment['id']}"]
        lines.append("Макет и получение согласовываются отдельно.")
    else:
        lines.append("Макет и получение согласовываются отдельно. Заявка не подтверждает оплату.")
    return "\n".join(lines)


def helper_url(order):
    return f"https://t.me/{RECIPIENT_USERNAME}?text={quote(order_template(order))}"


def customer_url(order):
    username = order.get("username")
    return f"https://t.me/{username}" if username and re.fullmatch(r"[A-Za-z0-9_]{5,32}", username) else f"tg://user?id={int(order['user_id'])}"


def preview(details):
    return "\n".join(f"<b>{html.escape(label)}:</b> {html.escape(str(details.get(key) or 'не указывать'))}"
                     for key, label, *_ in display_fields(details))


def price_quote(quantity):
    count = int(validate_value(3, str(quantity)))
    unit = BULK_UNIT_PRICE_RUB if count >= BULK_THRESHOLD else UNIT_PRICE_RUB
    return {"quantity": count, "unit_price_rub": unit, "total_rub": count * unit}


def pricing_text(pricing):
    return f"{pricing['quantity']} шт. × {pricing['unit_price_rub']} ₽ = {pricing['total_rub']} ₽"
