"""Audience-facing copy and shortcuts for the second-year announcement templates."""

from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.access import (
    ANATOMY_HISTOLOGY_TIER_ID,
    ANATOMY_TEST_TIER_ID,
    SUBSCRIPTION_TIERS,
    WINTER_TIER_ID,
)
from services.content_access import EXAM_TRIAL_HOURS


OFFER_TIER_IDS = (ANATOMY_TEST_TIER_ID, ANATOMY_HISTOLOGY_TIER_ID, WINTER_TIER_ID, 26)
QUICK_ACTIONS = {
    **{key: f'announce_offer:{tier_id}'
       for key, tier_id in zip(('тесты', 'комплект', 'сессия', 'весь-курс'), OFFER_TIER_IDS, strict=True)},
    'пробный': 'study_trial:histology',
    'пример-анатомия': 'study_sample:anatomy_tests:0',
    'пример-гистология': 'study_sample:histology:0',
    'тесты-анатомия': 'anatomy_exam_test_menu',
    'тесты-гистология': 'histology_tests',
}


def offer_prices():
    return tuple(SUBSCRIPTION_TIERS[tier_id]['price_rub'] for tier_id in OFFER_TIER_IDS)


def subscription_text():
    tests, bundle, winter, full = offer_prices()
    return (
        '💎 <b>Подписки VMEDA для 2 курса</b>\n'
        '<i>Выбери, к чему готовишься сейчас.</i>\n\n'
        f'🦴 <b>{tests} ₽ · Тесты по анатомии на 7 дней</b>\n'
        'Все экзаменационные тесты, карточки и работа над ошибками.\n\n'
        f'🔬 <b>{bundle} ₽ · Анатомия и гистология на 14 дней</b>\n'
        'Вся анатомия с билетами, теорией, практикой и тестами. По гистологии — теория, тесты, '
        'диагностики 1–5 и «Угадай препарат» по списку каждой диагностики.\n\n'
        f'📚 <b>{winter} ₽ · Зимняя сессия</b>\n'
        'Анатомия, гистология, биология, физика и химия до конца февраля 2027 года. '
        '450 запросов VMEDA AI на весь срок.\n\n'
        f'👑 <b>{full} ₽ · До конца 2 курса</b>\n'
        'Все пять предметов до 31 августа 2027 года включительно. Новые разделы второго курса '
        'по мере публикации, скачивание доступных материалов и 225 запросов VMEDA AI в месяц.\n\n'
        '<i>Выбери тариф, чтобы перейти к оплате. Доступ работает в боте и Mini App.</i>'
    )


def subscription_keyboard():
    tests, bundle, winter, full = offer_prices()
    builder = InlineKeyboardBuilder()
    builder.button(text=f'🦴 Тесты по анатомии · {tests} ₽', callback_data=QUICK_ACTIONS['тесты'])
    builder.button(text=f'🔬 Анатомия и гистология · {bundle} ₽', callback_data=QUICK_ACTIONS['комплект'])
    builder.button(text=f'📚 Зимняя сессия · {winter} ₽', callback_data=QUICK_ACTIONS['сессия'])
    builder.button(text=f'👑 До конца 2 курса · {full} ₽', callback_data=QUICK_ACTIONS['весь-курс'], style='primary')
    return builder.adjust(1).as_markup()


def trial_text():
    return (
        f'🎁 <b>Анатомия и гистология бесплатно на {EXAM_TRIAL_HOURS} часов</b>\n'
        '<i>Загляни внутрь и попробуй задания в своём темпе.</i>\n\n'
        '🦴 <b>Анатомия</b> — экзаменационные тесты, билеты, теория и практика.\n'
        '🔬 <b>Гистология</b> — тесты, теория, диагностики 1–5 и «Угадай препарат».\n\n'
        'Три вопроса по анатомии и один микропрепарат доступны сразу. '
        f'Общий таймер для бота и Mini App включится по кнопке <b>«Начать бесплатные {EXAM_TRIAL_HOURS} часов»</b>.\n\n'
        '<i>Пробный доступ выдаётся один раз. Для запуска не нужны оплата и приглашения.</i>'
    )


def trial_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text=f'🎁 Начать бесплатные {EXAM_TRIAL_HOURS} часов',
                   callback_data=QUICK_ACTIONS['пробный'], style='success')
    builder.button(text='🦴 3 пробных вопроса', callback_data=QUICK_ACTIONS['пример-анатомия'])
    builder.button(text='🔬 Угадай препарат · пример', callback_data=QUICK_ACTIONS['пример-гистология'])
    return builder.adjust(1).as_markup()
