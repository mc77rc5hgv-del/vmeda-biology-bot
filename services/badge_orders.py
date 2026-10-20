"""Validated, bounded badge details and a shared human-readable order template."""
import html
import re
from urllib.parse import quote

RECIPIENT_ID = 8928384363
RECIPIENT_USERNAME = "vmeda_helper"
FIELDS = (
    ("surname", "Фамилия", "Иванов", 60, False),
    ("name", "Имя", "Иван", 60, False),
    ("patronymic", "Отчество", "Иванович", 60, True),
    ("role", "Должность / статус", "Курсант / Студент / Врач", 100, False),
    ("organization", "Организация", "Военно-медицинская академия", 150, False),
    ("quantity", "Количество", "1", 3, False),
    ("contact", "Контакт для связи", "@username или номер телефона", 80, False),
)


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
    if key in {"surname", "name", "patronymic"} and not any(c.isalpha() for c in value):
        raise ValueError("Укажи имя текстом, как оно должно быть напечатано.")
    if key == "contact":
        username = re.fullmatch(r"@[A-Za-z][A-Za-z0-9_]{4,31}", value)
        phone = re.fullmatch(r"\+?[\d ()-]{7,30}", value)
        if not username and not (phone and 7 <= sum(c.isdigit() for c in value) <= 15):
            raise ValueError("Укажи @username или номер телефона с кодом страны.")
    return value


def validated_details(details):
    return {field[0]: ("" if field[4] and not details.get(field[0]) else validate_value(i, details.get(field[0], "")))
            for i, field in enumerate(FIELDS)}


def order_template(order):
    details = validated_details(order["details"])
    lines = ["ЗАКАЗ МЕДИЦИНСКИХ БЕЙДЖИКОВ", f"Заявка: {order['id']}", ""]
    lines.extend(f"{label}: {details[key] or 'не указывать'}" for key, label, *_ in FIELDS)
    lines += ["", f"Заказчик: {order.get('full_name', '')}", f"Telegram ID: {order['user_id']}"]
    if order.get("username"):
        lines.append(f"Telegram: @{order['username']}")
    lines.append("Стоимость, макет и получение — по согласованию. Заявка не подтверждает оплату.")
    return "\n".join(lines)


def helper_url(order):
    return f"https://t.me/{RECIPIENT_USERNAME}?text={quote(order_template(order))}"


def customer_url(order):
    username = order.get("username")
    return f"https://t.me/{username}" if username and re.fullmatch(r"[A-Za-z0-9_]{5,32}", username) else f"tg://user?id={int(order['user_id'])}"


def preview(details):
    return "\n".join(f"<b>{html.escape(label)}:</b> {html.escape(str(details.get(key) or 'не указывать'))}"
                     for key, label, *_ in FIELDS)
