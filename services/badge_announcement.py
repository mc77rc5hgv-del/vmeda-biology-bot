"""Ready-to-preview badge advertisement. Construction never sends a message."""
import secrets
from pathlib import Path

from aiogram.types import FSInputFile, InputMediaPhoto
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .admin_broadcast import Draft
from .badge_orders import BULK_THRESHOLD, BULK_UNIT_PRICE_RUB, RECIPIENT_USERNAME, UNIT_PRICE_RUB

PHOTOS = tuple(Path(__file__).resolve().parents[1] / 'images' / 'badges' / name
               for name in ('sample.jpg', 'on-uniform.jpg'))


def build_preset():
    if not all(path.is_file() for path in PHOTOS):
        raise FileNotFoundError('Badge announcement requires both original photos')
    text = (
        '🪪 <b>Медицинские бейджики ВМедА</b>\n\n'
        'Именной бейджик для учёбы и практики — как на фото.\n'
        'Укажи ФИО, статус «Студент» / «Курсант» или свой вариант и специальность.\n\n'
        f'💳 <b>{UNIT_PRICE_RUB} ₽ за штуку</b>\n'
        f'👥 От {BULK_THRESHOLD} шт. — <b>{BULK_UNIT_PRICE_RUB} ₽ за каждую</b>\n'
        f'Заказ на {BULK_THRESHOLD} шт. — <b>{BULK_THRESHOLD * BULK_UNIT_PRICE_RUB} ₽</b>.\n\n'
        'Индивидуальный заказ можно оформить и оплатить через СБП прямо в боте.\n'
        f'Групповой заказ, макет и получение — в чате @{RECIPIENT_USERNAME}.\n\n'
        'Нажми кнопку ниже, чтобы заказать 👇'
    )
    builder = InlineKeyboardBuilder()
    builder.button(text='🪪 Заказать бейджик', callback_data='badges:menu')
    builder.button(text=f'👥 Заказать на группу ({BULK_THRESHOLD} шт.)', url=f'https://t.me/{RECIPIENT_USERNAME}')
    builder.adjust(1)
    return Draft(secrets.token_hex(8), text, [InputMediaPhoto(media=FSInputFile(path)) for path in PHOTOS],
                 reply_markup=builder.as_markup(), allow_payment_admin=True)
