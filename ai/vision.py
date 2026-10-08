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


MAX_IMAGE_BYTES = 6 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000


def resize_image(image_bytes: bytes) -> bytes:
    """Validate dimensions BEFORE decoding; never forward damaged originals."""
    if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError('Фото слишком большое: максимум 6 MB')
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            w, h = source.size
            if w <= 0 or h <= 0 or w * h > MAX_IMAGE_PIXELS:
                raise ValueError('Слишком большое разрешение фото: максимум 20 мегапикселей')
            source.thumbnail((MAX_DIM, MAX_DIM), Image.Resampling.LANCZOS)
            im = ImageOps.exif_transpose(source).convert('RGB')
            out = io.BytesIO()
            im.save(out, 'JPEG', quality=82, optimize=True)
            return out.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('Не удалось прочитать фото. Пришли JPEG или PNG меньшего размера.') from exc
