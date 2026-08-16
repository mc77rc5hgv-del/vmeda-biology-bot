"""Подготовка фото перед отправкой в vision-модель — сжатие разрешения и выбор detail-режима."""
import io
import logging

logger = logging.getLogger(__name__)

MAX_DIM = 1280  # достаточно для чтения печатного/рукописного текста, дальше — лишние input-токены

# "detail": "low" у gpt-4o-mini — это ФИКСИРОВАННЫЕ 2833 токена на фото, а не 2833 + 5667×тайлы
# (до 36 835 токенов при auto/high на наш же ресайз в 1280px) — самая дорогая часть всего
# AI-запроса на порядок дороже, чем экономия от сжатия истории диалога. Риск — модель видит
# уменьшенную версию фото и может хуже прочитать мелкий текст/подстрочные индексы в формулах.
DETAIL = "low"


def resize_image(image_bytes: bytes) -> bytes:
    """Фото с телефона часто в разы больше, чем нужно vision-модели для распознавания текста —
    у OpenAI цена фото считается по числу тайлов, то есть растёт с разрешением. Сжимаем перед
    отправкой; при любой ошибке разбора шлём оригинал как есть, не роняя запрос."""
    try:
        from PIL import Image, ImageOps
        im = Image.open(io.BytesIO(image_bytes))
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
        w, h = im.size
        if max(w, h) > MAX_DIM:
            scale = MAX_DIM / max(w, h)
            im = im.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
        out = io.BytesIO()
        im.save(out, "JPEG", quality=82, optimize=True)
        return out.getvalue()
    except Exception:
        logger.exception("Не удалось сжать фото перед AI-запросом, отправляю оригинал")
        return image_bytes
