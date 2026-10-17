"""Telegram presentation helpers; no user, payment or learning state writes."""
from html import escape

from aiogram.exceptions import TelegramBadRequest


async def safe_delete_message(message) -> bool:
    """Old/undeletable messages must not prevent delivery of the next screen."""
    try:
        await message.delete()
    except TelegramBadRequest:
        return False
    return True


def escaped_text_pages(text: str, limit: int = 3400) -> list[str]:
    """Escape untrusted plain text without splitting HTML entities or losing text."""
    if limit < 6:
        raise ValueError('Page budget must fit one escaped character')
    pages, parts, size = [], [], 0
    for char in text:
        encoded = escape(char)
        units = max(len(encoded), 2 if ord(char) > 0xFFFF else 1)
        if size + units > limit:
            pages.append(''.join(parts))
            parts, size = [], 0
        parts.append(encoded)
        size += units
    if parts or not pages:
        pages.append(''.join(parts))
    return pages
