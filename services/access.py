# -*- coding: utf-8 -*-
"""Реферальная система, платная подписка и гейты доступа к предметам/разделам.

Чистая предикатная/учётная логика (кто и на каком основании имеет доступ), без UI/текстов/
клавиатур и без aiogram-хендлеров — те остаются в telegram_bot.py и обращаются сюда через
плоский реэкспорт (см. блок рядом с исходным местом каждой секции в telegram_bot.py).
"""
import time
from datetime import datetime

import telegram_bot as tb


def _msk_deadline(year: int, month: int, day: int) -> float:
    """Полночь по МСК (tb.APP_TIMEZONE) указанной календарной даты, как unix-timestamp — а не
    time.mktime(date(...).timetuple()), который интерпретирует дату в часовом поясе КОНТЕЙНЕРА
    (Railway по умолчанию UTC). Меняет момент срабатывания константы-дедлайна для БУДУЩИХ выдач
    подписки на ~3 часа, но НИКОГДА не переписывает уже сохранённый sub["expires"] у существующих
    подписок — grant_subscription() лишь читает текущее значение константы в момент выдачи."""
    return datetime(year, month, day, tzinfo=tb.APP_TIMEZONE).timestamp()


def is_admin(user_id: int) -> bool:
    return user_id in tb.ADMIN_IDS

def is_assistant_admin(user_id: int) -> bool:
    return user_id in tb.stats["assistant_admins"]

def is_admin_or_assistant(user_id: int) -> bool:
    """Полный админ ИЛИ помощник администратора — используется только в гейтах доступа к
    контенту (Анатомия/Гистология/гейтящиеся предметы), НЕ в гейтах самой админ-панели.
    Помощник получает доступ ко всем разделам, но не получает права полного админа
    (выдача/отзыв доступа, рассылки, подписки и т.д. — только через отдельную,
    ограниченную панель помощника, см. секцию «ПОМОЩНИК АДМИНИСТРАТОРА»)."""
    return is_admin(user_id) or is_assistant_admin(user_id)

def is_payment_admin(user_id: int) -> bool:
    """Третья, отдельная от помощника роль — «админ платежей»: подтверждает рублёвые one-tap
    заявки (см. notify_admins_of_payment_request/cb_admin_confirm_sub в telegram_bot.py) и
    рассылает анонсы (подраздел «Анонсы», cb_admin_announcements_menu). НЕ пересекается с
    is_assistant_admin — у помощника свой контракт (доступ к разделам контента + урезанная
    панель "статистика + модерируемое сообщение"), сознательно без прав на платежи/рассылки;
    расширять его вместо создания отдельной роли значило бы менять уже задокументированный
    контракт помощника. stats["payment_admins"] — такой же плоский список user_id, как
    stats["assistant_admins"]."""
    return user_id in tb.stats["payment_admins"]


# ==================== ВРЕМЕННЫЕ ПРОМО-ОКНА ДОСТУПА ДЛЯ РАЗДЕЛОВ ====================
def start_section_promo(section: str, duration_seconds: int) -> float:
    """Делает раздел (по ключу, например "histology") бесплатным для всех до истечения окна."""
    until = time.time() + duration_seconds
    tb.stats.setdefault("section_promos", {})[section] = until
    tb.save_stats()
    return until

def is_section_promo_active(section: str) -> bool:
    return time.time() < tb.stats.get("section_promos", {}).get(section, 0)


# ==================== РЕФЕРАЛЬНАЯ СИСТЕМА ====================
BOT_USERNAME = "VMEDA_examen_bot"
# Раньше: разовый порог, открывающий доступ НАВСЕГДА после первого достижения. Теперь — порог
# ЕЖЕМЕСЯЧНО ОБНОВЛЯЕМЫХ рефералов: чтобы доступ оставался открытым, каждый календарный месяц
# нужно приводить заново REFERRAL_FULL_ACCESS_THRESHOLD НОВЫХ друзей (см. get_referral_count_this_month
# ниже) — рефералы прошлых месяцев в счёт текущего месяца не идут, "банковать" их нельзя.
# get_referral_count() (лифтайм-счётчик, ниже) при этом никуда не делся — им по-прежнему считаются
# лидерборд, битва рефералов и мгновенное уведомление "тебя пригласили N человек всего", просто ОН
# больше не решает вопрос доступа к контенту — этим теперь занимается ТОЛЬКО помесячный счётчик.
REFERRAL_FULL_ACCESS_THRESHOLD = 2  # столько НОВЫХ рефералов нужно каждый месяц, чтобы открыть доступ
REFERRAL_WARNING_THRESHOLD = 3  # столько предупреждений даём, прежде чем закрыть доступ
REFERRAL_WARNING_COOLDOWN_SECONDS = 4 * 60 * 60  # не чаще одного предупреждения раз в 4 часа
TEMP_ACCESS_GRANT_SECONDS = 7 * 24 * 60 * 60  # длительность временного восстановления доступа
GLOBAL_PROMO_SECONDS = 24 * 60 * 60  # длительность полного открытия всех разделов всем (раздел "global")
GLOBAL_PROMO_12H_SECONDS = 12 * 60 * 60  # укороченная версия того же промо, на 12 часов

def get_referral_link(user_id: int) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"

def get_referral_count(user_id: int) -> int:
    """Рефералы за ВСЁ ВРЕМЯ — для лидерборда/битвы рефералов/мгновенного уведомления о новом
    реферале. НЕ используется для гейта доступа к контенту — см. get_referral_count_this_month."""
    return len(tb.stats["referrals"].get(str(user_id), []))

def _current_referral_month_key() -> str:
    return tb.local_today().strftime("%Y-%m")

def get_referral_count_this_month(user_id: int) -> int:
    """Рефералы, приведённые ИМЕННО в текущем календарном месяце — то, что реально сравнивается с
    REFERRAL_FULL_ACCESS_THRESHOLD для доступа к контенту. Тот же паттерн месяц-ключ + бегущий
    счётчик, сбрасываемый при смене периода, что и у ai_used_monthly (telegram_bot.py) — см.
    _increment_referral_month_count ниже."""
    entry = tb.stats["referral_monthly"].get(str(user_id))
    if not entry or entry.get("month") != _current_referral_month_key():
        return 0
    return entry.get("count", 0)

def _increment_referral_month_count(user_id: int) -> None:
    month = _current_referral_month_key()
    entry = tb.stats["referral_monthly"].get(str(user_id))
    if not entry or entry.get("month") != month:
        entry = {"month": month, "count": 0}
    entry["count"] += 1
    tb.stats["referral_monthly"][str(user_id)] = entry

def get_temp_access_expiry(user_id: int) -> float:
    return tb.stats["temporary_access"].get(str(user_id), 0)

def has_temp_access(user_id: int) -> bool:
    return time.time() < get_temp_access_expiry(user_id)

# ==================== ПЛАТНАЯ ПОДПИСКА ====================
# Тарифы 1-11 — старая линейка (историческая, "subscription_version" не хранился в записи, что
# читается как version=1 через .get("subscription_version", 1)). ВСЕ сняты с продажи
# ("retired": True) — их условия НЕ меняются задним числом, они просто больше не показываются в
# магазине. У уже купивших их людей (и у уже выданных вручную/подарочных подписок) доступ
# продолжает работать ровно как был обещан на момент покупки — ни срок, ни права не трогаются
# задним числом, никакой миграции записей stats["subscriptions"] на новые tier id не производится.
# Тарифы 20-28 — новая линейка (актуальный прайс-лист, "subscription_version": 2 на новых выдачах).
# Никогда не переиспользуй id 1-19 для нового смысла — старые записи хранят только числовой tier id,
# и часть кода живьём резолвит его через SUBSCRIPTION_TIERS, так что переиспользование id задним
# числом переинтерпретировало бы то, что реальный покупатель уже оплатил.
TIER1_HISTOLOGY_DEADLINE = _msk_deadline(2027, 1, 1)  # легаси: гистология по СТАРЫМ выдачам тарифа 1 — до конца 2026 года
JULY_END_2026 = _msk_deadline(2026, 8, 1)  # тариф «Месяц» — предпросмотр Гистологии до конца июля 2026
OCT_2026_CUTOFF = _msk_deadline(2026, 10, 1)  # тариф 239₽ — до 1 октября 2026
NOV_END_2026_CUTOFF = _msk_deadline(2026, 12, 1)  # тариф 389₽ — до конца ноября 2026
FEB_2027_CUTOFF = _msk_deadline(2027, 2, 1)  # тариф 749₽ — до февраля 2027
# «До конца второго курса» — точная дата учебного календаря не была уточнена, взята оценка
# (конец лета 2027). Поправь SECOND_YEAR_END_2027, если известна точная дата окончания 2 курса.
# Используется и старым тарифом 9, и новым тарифом 26 — дата единая для обоих, менять с осторожностью:
# сдвиг задним числом изменил бы срок уже выданных подписок тарифа 9.
SECOND_YEAR_END_2027 = _msk_deadline(2027, 9, 1)

# --- Новая линейка (тарифы 20-28) ---
NOV_1_2026_CUTOFF = _msk_deadline(2026, 11, 1)  # тариф 22 «Все пересдачи» — до конца октября 2026
JAN_1_2027_CUTOFF = _msk_deadline(2027, 1, 1)  # тариф 23 «До зачёта по химии» — до конца декабря 2026
MAR_1_2027_CUTOFF = _msk_deadline(2027, 3, 1)  # тариф 24 «Зимняя сессия» — до конца февраля 2027
FIRST_YEAR_END_2027 = _msk_deadline(2027, 8, 1)  # тариф 25 «Весь первый курс» — до летних экзаменов 2027

# Старым платным подпискам (subscription_version 1, т.е. поле отсутствует в записи) — небольшой
# фиксированный AI-бонус поверх обычного бесплатного дневного лимита, не завязанный ни на один
# сохранённый в их записи тариф/поле (см. get_ai_plan() в telegram_bot.py). Контентные права такой
# подписки (anatomy/histology/scope/...) этот бонус никак не трогает.
LEGACY_PAID_AI_MONTHLY_BONUS = 60

SUBSCRIPTION_TIERS = {
    1: {
        "retired": True,
        "title": "Месяц — Биология, Физика, Химия",
        "short": "1 месяц, 3 экзамена",
        "emoji": "🔓",
        "price_rub": 89,
        "price_stars": 89,
        "duration_days": 30,
        "expires_at": None,
        "subject_choice_required": False,
        "histology_until_rule": JULY_END_2026,
        "anatomy": False,
        "biology_download": False,
        "cheat_sheets": False,
        "menu_number": 3,
        "joke": "ЭНЕРГЕТИК 🤮 или УСПЕШНАЯ СДАЧА ЭКЗАМЕНА 😇",
        "benefits": [
            "Полный доступ к Биологии, Физике и Химии на 30 дней",
            "🔬 Плюс предпросмотр Гистологии — доступен сейчас, до конца июля 2026 года",
            "Скачивание файлов с ответами — по Физике и Химии",
            "Не нужно ждать и звать друзей — доступ открывается сразу после оплаты",
            "Подходит и для подготовки к текущим практическим занятиям",
        ],
    },
    2: {
        "title": "Навсегда — Биология, Физика, Химия",
        "short": "навсегда, 3 экзамена",
        "scope": "gated",
        "duration_days": None,
        "price_rub": 239,
        "price_stars": 239,
        "emoji": "♾️",
        "early_histology": True,
        "retired": True,
        "joke": "маленькая шаверма 🥙 или УСПЕШНАЯ СДАЧА ЭКЗАМЕНОВ 😇",
        "benefits": [
            "Полный доступ к Биологии, Физике и Химии — один раз и навсегда",
            "🔬 Плюс ранний доступ к разделу Гистологии — она уже полностью готова",
            "Дешевле, чем 3 месячные подписки, а действует бессрочно",
        ],
    },
    3: {
        "title": "Год — все экзамены",
        "short": "1 год, все разделы",
        "scope": "all",
        "duration_days": 365,
        "price_rub": 899,
        "price_stars": 899,
        "emoji": "🚀",
        "retired": True,
        "joke": "2 шавермы 🥙🥙 или ПОДПИСКА НА ГОД 🚀",
        "benefits": [
            "Доступ вообще ко всем разделам бота на целый год",
            "Плюс Анатомия и уже полностью готовая Гистология — уже сейчас, до их открытия всем остальным",
        ],
    },
    4: {
        "title": "6 лет — все экзамены",
        "short": "6 лет, все разделы",
        "scope": "all",
        "duration_days": 6 * 365,
        "price_rub": 2499,
        "price_stars": 2499,
        "emoji": "👑",
        "retired": True,
        "joke": "2499₽ в кармане 💸 или успешно окончить академию 🎓",
        "benefits": [
            "Доступ ко всем разделам бота на весь срок обучения в академии",
            "Анатомия и уже полностью готовая Гистология, а также все будущие разделы — сразу, без ожиданий",
        ],
    },
    5: {
        # temporarily off sale (not a permanent retirement like 2/3/4) — flag removable later
        "retired": True,
        "title": "3 дня — один предмет на выбор",
        "short": "3 дня, 1 предмет",
        "emoji": "⚡",
        "price_rub": 49,
        "price_stars": 49,
        "duration_days": 3,
        "expires_at": None,
        "subject_choice_required": True,
        "histology_until_rule": None,
        "anatomy": False,
        "biology_download": False,
        "cheat_sheets": False,
        "menu_number": 4,
        "joke": "Меньше стакана кофе ☕ — но хватит ровно на один экзамен",
        "benefits": [
            "Доступ только к ОДНОМУ предмету на выбор — Биология, Физика или Химия — на 3 дня",
            "Идеально, если один-два экзамена уже сдал и остался последний рывок",
            "Не нужно ждать и звать друзей — доступ открывается сразу после оплаты",
            "Подходит и для подготовки к текущим практическим занятиям",
        ],
    },
    6: {
        "retired": True,
        "title": "До октября — Биология, Физика, Химия + Гистология",
        "short": "4 экзамена, до окт. 2026",
        "emoji": "🔬",
        "price_rub": 239,
        "price_stars": 239,
        "duration_days": None,
        "expires_at": OCT_2026_CUTOFF,
        "subject_choice_required": False,
        "histology_until_rule": "expiry",
        "anatomy": False,
        "biology_download": False,
        "cheat_sheets": False,
        "menu_number": 5,
        "benefits": [
            "Полный доступ к Биологии, Физике, Химии и уже готовой Гистологии — все 4 экзамена сразу",
            "Действует до 1 октября 2026 года",
            "Скачивание файлов с ответами — по Физике и Химии (кроме Биологии)",
            "Подходит и для подготовки к текущим практическим занятиям",
        ],
    },
    7: {
        "retired": True,
        "title": "До конца ноября — все 5 экзаменов",
        "short": "5 экзаменов, до нояб. 2026",
        "emoji": "🚀",
        "price_rub": 389,
        "price_stars": 389,
        "duration_days": None,
        "expires_at": NOV_END_2026_CUTOFF,
        "subject_choice_required": False,
        "histology_until_rule": "expiry",
        "anatomy": True,
        "biology_download": False,
        "cheat_sheets": False,
        "badge": "🔥 ХИТ ПРОДАЖ 🔥",
        "menu_number": 1,
        "benefits": [
            "Полный доступ ко всем 5 предметам — Биология, Физика, Химия, Гистология и досрочно Анатомия",
            "Действует до конца ноября 2026 года",
            "Скачивание файлов с ответами — по Физике и Химии (кроме Биологии)",
            "Подходит и для подготовки к текущим практическим занятиям",
        ],
    },
    8: {
        "retired": True,
        "title": "До февраля 2027 — все 5 экзаменов",
        "short": "5 экзаменов, до февр. 2027",
        "emoji": "🎯",
        "price_rub": 749,
        "price_stars": 749,
        "duration_days": None,
        "expires_at": FEB_2027_CUTOFF,
        "subject_choice_required": False,
        "histology_until_rule": "expiry",
        "anatomy": True,
        "biology_download": False,
        "cheat_sheets": False,
        "menu_number": 6,
        "benefits": [
            "Полный доступ ко всем 5 предметам — Биология, Физика, Химия, Гистология и досрочно Анатомия",
            "Действует до февраля 2027 года — хватит на весь учебный год без повторной оплаты",
            "Скачивание файлов с ответами — по Физике и Химии (кроме Биологии)",
            "Подходит и для подготовки к текущим практическим занятиям",
        ],
    },
    9: {
        "retired": True,
        "title": "До конца 2 курса — всё, включая зачёты и диагностики",
        "short": "всё + зачёты, до конца 2 курса",
        "emoji": "👑",
        "price_rub": 1119,
        "price_stars": 1119,
        "duration_days": None,
        "expires_at": SECOND_YEAR_END_2027,
        "subject_choice_required": False,
        "histology_until_rule": "expiry",
        "anatomy": True,
        "biology_download": True,
        "cheat_sheets": True,
        "badge": "🔥 РЕКОМЕНДОВАНО 🔥",
        "menu_number": 2,
        "benefits": [
            "Полный доступ ко всем предметам — Биология, Физика, Химия, Гистология, Анатомия",
            "Плюс текущие зачёты, контрольные и диагностики по мере их появления в боте",
            "Скачивание файлов с ответами — включая Биологию — и готовых шпаргалок для распечатки",
            "Действует до конца второго курса",
            "Подходит и для подготовки к текущим практическим занятиям",
        ],
    },
    10: {
        "retired": True,
        "title": "6 лет — абсолютно всё",
        "short": "6 лет, абсолютно всё",
        "emoji": "💎",
        "price_rub": 3899,
        "price_stars": 3899,
        "duration_days": 6 * 365,
        "expires_at": None,
        "subject_choice_required": False,
        "histology_until_rule": "expiry",
        "anatomy": True,
        "biology_download": True,
        "cheat_sheets": True,
        "badge": "🔥 HOT 🔥",
        "joke": "Дальше будет только дороже — бери, пока не подняли цену",
        "menu_number": 7,
        "benefits": [
            "АБСОЛЮТНО ПОЛНЫЙ и РАННИЙ доступ ко всем зачётам, экзаменам и контрольным по всем предметам",
            "Один платёж на все 6 лет учёбы в академии — включая всё, что появится в боте позже",
            "Скачивание всех файлов с ответами и шпаргалок для распечатки",
            "Подходит и для подготовки к текущим практическим занятиям",
            "⏫ Цена вырастет позже — сейчас это самая низкая стоимость этого тарифа",
        ],
    },
    11: {
        "retired": True,
        "title": "2 года — абсолютно всё",
        "short": "2 года, абсолютно всё",
        "emoji": "🏆",
        "price_rub": 1999,
        "price_stars": 1999,
        "duration_days": 2 * 365,
        "expires_at": None,
        "subject_choice_required": False,
        "histology_until_rule": "expiry",
        "anatomy": True,
        "biology_download": True,
        "cheat_sheets": True,
        "menu_number": 8,
        "joke": "Дешевле, чем повторная сдача пересдачи",
        "benefits": [
            "АБСОЛЮТНО ПОЛНЫЙ доступ ко всем предметам — Биология, Физика, Химия, Гистология, Анатомия",
            "Один платёж на 2 года учёбы — включая всё, что появится в боте позже",
            "Скачивание всех файлов с ответами и готовых шпаргалок для распечатки",
            "Подходит и для подготовки к текущим практическим занятиям",
        ],
    },
    # --- Новая линейка (2026/27 учебный год), tier id 20-28 ---
    20: {
        "title": "Пересдача — 7 дней, один предмет",
        "short": "7 дней, 1 предмет",
        "emoji": "⚡",
        "price_rub": 99,
        "price_stars": 99,
        "duration_days": 7,
        "expires_at": None,
        "subject_choice_required": True,
        "histology_until_rule": None,
        "anatomy": False,
        "biology_download": False,
        "cheat_sheets": False,
        "ai_limit_type": "period",
        "ai_limit": 30,
        "subscription_version": 2,
        "menu_number": 1,
        "benefits": [
            "Доступ только к ОДНОМУ предмету на выбор — Биология, Физика или Химия — на 7 дней",
            "Полный доступ к материалам, задачам, вопросам и билетам выбранного предмета",
            "VMedA AI (решение заданий по фото) — 30 запросов на весь срок подписки",
            "Идеально для подготовки к пересдаче одного экзамена",
        ],
    },
    21: {
        "title": "30 дней — Биология, Физика, Химия",
        "short": "30 дней",
        "emoji": "🔓",
        "price_rub": 129,
        "price_stars": 129,
        "duration_days": 30,
        "expires_at": None,
        "subject_choice_required": False,
        "histology_until_rule": None,
        "anatomy": False,
        "biology_download": False,
        "cheat_sheets": False,
        "ai_limit_type": "period",
        "ai_limit": 110,
        "subscription_version": 2,
        "menu_number": 2,
        "benefits": [
            "Полный доступ к Биологии, Физике и Химии на 30 дней",
            "Основные материалы, экзаменационные вопросы и задачи",
            "VMedA AI (решение заданий по фото) — 110 запросов на весь срок подписки",
            "Подходит и для подготовки к текущим практическим занятиям",
        ],
    },
    22: {
        "title": "Все пересдачи — Биология, Физика и Химия",
        "short": "до конца октября",
        "emoji": "🔥",
        "price_rub": 249,
        "price_stars": 249,
        "duration_days": None,
        "expires_at": NOV_1_2026_CUTOFF,
        "subject_choice_required": False,
        "histology_until_rule": None,
        "anatomy": False,
        "biology_download": False,
        "cheat_sheets": False,
        "ai_limit_type": "period",
        "ai_limit": 225,
        "subscription_version": 2,
        "badge": "РЕКОМЕНДОВАНО ДЛЯ ПЕРЕСДАЧ",
        "menu_number": 3,
        "benefits": [
            "Полный доступ к Биологии, Физике и Химии на весь период пересдач",
            "Действует до конца октября 2026 года",
            "VMedA AI (решение заданий по фото) — 225 запросов на весь срок подписки",
            "Для 2 курса — оптимально на весь сезон пересдач",
        ],
    },
    23: {
        "title": "До зачёта по химии — Биология, Физика, Химия",
        "short": "до зачёта по химии",
        "emoji": "🧪",
        "price_rub": 299,
        "price_stars": 299,
        "duration_days": None,
        "expires_at": JAN_1_2027_CUTOFF,
        "subject_choice_required": False,
        "histology_until_rule": None,
        "anatomy": False,
        "biology_download": False,
        "cheat_sheets": False,
        "ai_limit_type": "period",
        "ai_limit": 225,
        "subscription_version": 2,
        "menu_number": 4,
        "benefits": [
            "Полный доступ к Биологии, Физике и Химии — подготовка к зачёту по химии",
            "Действует до конца декабря 2026 года",
            "Текущие материалы первого семестра первого курса",
            "VMedA AI (решение заданий по фото) — 225 запросов на весь срок подписки",
        ],
    },
    24: {
        "title": "Зимняя сессия — Анатомия, Гистология, Биология, Физика, Химия",
        "short": "зимняя сессия",
        "emoji": "🧠",
        "price_rub": 599,
        "price_stars": 599,
        "duration_days": None,
        "expires_at": MAR_1_2027_CUTOFF,
        "subject_choice_required": False,
        "histology_until_rule": "expiry",
        "anatomy": True,
        "biology_download": False,
        "cheat_sheets": False,
        "ai_limit_type": "period",
        "ai_limit": 450,
        "subscription_version": 2,
        # Философия и другие будущие разделы 2 курса — как только появятся в боте, попадут сюда
        # автоматически (флаг ничего не открывает сам по себе, пока раздела физически нет).
        "future_second_year_sections": True,
        "menu_number": 5,
        "benefits": [
            "Анатомия, Гистология, Биология, Физика и Химия — текущие зачёты зимней сессии",
            "Действует до конца февраля 2027 года",
            "Философия и другие новые разделы 2 курса — автоматически, как только появятся в боте",
            "VMedA AI (решение заданий по фото) — 450 запросов на весь срок подписки",
        ],
    },
    25: {
        "title": "Весь первый курс — Биология, Физика, Химия",
        "short": "весь первый курс",
        "emoji": "🎓",
        "price_rub": 849,
        "price_stars": 849,
        "duration_days": None,
        "expires_at": FIRST_YEAR_END_2027,
        "subject_choice_required": False,
        "histology_until_rule": None,
        "anatomy": False,
        "biology_download": False,
        "cheat_sheets": False,
        "ai_limit_type": "monthly",
        "ai_limit": 150,
        "subscription_version": 2,
        "badge": "⭐ РЕКОМЕНДОВАНО ДЛЯ 1 КУРСА",
        "menu_number": 6,
        "benefits": [
            "Биология, Физика и Химия — зачёт по химии, летние экзамены, весь учебный год",
            "Действует до завершения экзаменов первого курса летом 2027 года",
            "Билеты, контрольные и все новые материалы первого курса по мере появления",
            "VMedA AI (решение заданий по фото) — 150 запросов в месяц",
        ],
    },
    26: {
        "title": "До конца второго курса — всё, включая зачёты и диагностики",
        "short": "всё, до конца 2 курса",
        "emoji": "👑",
        "price_rub": 1290,
        "price_stars": 1290,
        "duration_days": None,
        "expires_at": SECOND_YEAR_END_2027,
        "subject_choice_required": False,
        "histology_until_rule": "expiry",
        "anatomy": True,
        "biology_download": True,
        "cheat_sheets": True,
        "ai_limit_type": "monthly",
        "ai_limit": 225,
        "subscription_version": 2,
        "future_second_year_sections": True,
        "badge": "🔥 ЛУЧШИЙ ВЫБОР",
        "menu_number": 7,
        "benefits": [
            "Полный доступ ко всем предметам — Биология, Физика, Химия, Гистология, Анатомия",
            "Философия и другие новые разделы 1-2 курса — автоматически, как только появятся в боте",
            "Все текущие зачёты, контрольные и диагностики по мере их появления в боте",
            "Скачивание файлов с ответами и готовых шпаргалок для распечатки",
            "Действует до конца второго курса",
            "VMedA AI (решение заданий по фото) — 225 запросов в месяц",
        ],
    },
    27: {
        "title": "VMedA MAX — 2 года",
        "short": "2 года MAX",
        "emoji": "🏆",
        "price_rub": 1690,
        "price_stars": 1690,
        "duration_days": 2 * 365,
        "expires_at": None,
        "subject_choice_required": False,
        "histology_until_rule": "expiry",
        "anatomy": True,
        "biology_download": True,
        "cheat_sheets": True,
        "ai_limit_type": "monthly",
        "ai_limit": 375,
        "subscription_version": 2,
        "future_second_year_sections": True,
        "menu_number": 8,
        "benefits": [
            "Полный доступ ко всем существующим предметам — Биология, Физика, Химия, Гистология, Анатомия",
            "Все будущие предметы, зачёты, контрольные и экзамены — сразу, без ожидания и доплаты",
            "Скачивание всех файлов с ответами и шпаргалок для распечатки",
            "Ранний доступ (early access) к новым разделам бота",
            "VMedA AI (решение заданий по фото) — 375 запросов в месяц",
        ],
    },
    28: {
        "title": "Вся академия",
        "short": "вся академия",
        "emoji": "💎",
        "price_rub": 3899,
        "price_stars": 3899,
        "duration_days": 6 * 365,
        "expires_at": None,
        "subject_choice_required": False,
        "histology_until_rule": "expiry",
        "anatomy": True,
        "biology_download": True,
        "cheat_sheets": True,
        "ai_limit_type": "monthly",
        "ai_limit": 375,
        "subscription_version": 2,
        "future_second_year_sections": True,
        "menu_number": 10,
        "benefits": [
            "Абсолютно полный доступ ко всем существующим и будущим разделам бота",
            "Все экзамены, зачёты, контрольные и диагностики — на весь срок обучения в академии",
            "Скачивание всех файлов с ответами и шпаргалок для распечатки",
            "VMedA AI (решение заданий по фото) — 375 запросов в месяц (fair use)",
        ],
    },
    29: {
        "title": "5 лет",
        "short": "5 лет",
        "emoji": "🗓",
        "price_rub": 3299,
        "price_stars": 3299,
        "duration_days": 5 * 365,
        "expires_at": None,
        "subject_choice_required": False,
        "histology_until_rule": "expiry",
        "anatomy": True,
        "biology_download": True,
        "cheat_sheets": True,
        "ai_limit_type": "monthly",
        "ai_limit": 375,
        "subscription_version": 2,
        "future_second_year_sections": True,
        "menu_number": 9,
        "benefits": [
            "Полный доступ ко всем существующим и будущим разделам бота на 5 лет",
            "Все экзамены, зачёты, контрольные и диагностики — на весь срок действия подписки",
            "Скачивание всех файлов с ответами и шпаргалок для распечатки",
            "VMedA AI (решение заданий по фото) — 375 запросов в месяц (fair use)",
        ],
    },
    # 30 — не тариф магазина: "admin_only" держит его вне ACTIVE_SUBSCRIPTION_TIERS (ни одна
    # витрина/оплата его никогда не покажет и не продаст), но он всё равно доступен для ручной
    # выдачи через ADMIN_GRANTABLE_TIERS ниже — единственное текущее применение: приз "подписка на
    # год" в розыгрышах, когда среди продаваемых тарифов нет ни одного с ровно 365-дневной
    # длительностью. price_rub/price_stars = 0, т.к. это не платный тариф ни в каком смысле — это
    # не противоречит "деньги = 0" нигде в коде: выдача всё равно идёт методом "rubles_manual",
    # который и так исключён из выручки независимо от значения price (см. cb_admin_confirm_sub /
    # get_admin_content_search_text и комментарий про revenue в разделе Subscriptions CLAUDE.md).
    30: {
        "title": "Приз розыгрыша — год",
        "short": "приз: год",
        "emoji": "🎁",
        "price_rub": 0,
        "price_stars": 0,
        "duration_days": 365,
        "expires_at": None,
        "subject_choice_required": False,
        "histology_until_rule": "expiry",
        "anatomy": True,
        "biology_download": True,
        "cheat_sheets": True,
        "ai_limit_type": "monthly",
        "ai_limit": 375,
        "subscription_version": 2,
        "future_second_year_sections": True,
        "admin_only": True,
        "benefits": [
            "Полный доступ ко всем существующим и будущим разделам бота на 1 год",
            "Все экзамены, зачёты, контрольные и диагностики — на весь срок действия подписки",
            "Скачивание всех файлов с ответами и шпаргалок для распечатки",
            "VMedA AI (решение заданий по фото) — 375 запросов в месяц (fair use)",
        ],
    },
}
# Витрина/оплата/анонсы: только то, что реально продаётся (без retired и без admin_only).
ACTIVE_SUBSCRIPTION_TIERS = {
    t: cfg for t, cfg in SUBSCRIPTION_TIERS.items() if not cfg.get("retired") and not cfg.get("admin_only")
}
# Ручная выдача подписки админом (по username/ID) — единственное место, которому НУЖНЫ
# admin_only-тарифы (призы розыгрышей и т.п.) в дополнение к обычным активным; retired всё равно
# исключены — прошлые тарифы не переиспользуются даже вручную, см. правило в SUBSCRIPTION_TIERS
# выше про "никогда не переиспользовать id снятого с продажи тарифа".
ADMIN_GRANTABLE_TIERS = {t: cfg for t, cfg in SUBSCRIPTION_TIERS.items() if not cfg.get("retired")}

SEPTEMBER_PRICE_INCREASE = 1.4  # с сентября цены на все тарифы вырастут на 40%

def september_price(price: int) -> int:
    return round(price * SEPTEMBER_PRICE_INCREASE)

DISCOUNT_RATE = 0.10  # разовая скидка 10% для пользователей без рефералов, промо-рассылкой

def discount_price(price: int) -> int:
    return round(price * (1 - DISCOUNT_RATE))

def get_tier_price_line(cfg: dict) -> str:
    """Текущая цена + зачёркнутая цена на 40% выше — с сентября будет дороже."""
    return (
        f"<b>{cfg['price_rub']}₽</b> <s>{september_price(cfg['price_rub'])}₽</s> / "
        f"<b>{cfg['price_stars']}⭐</b> <s>{september_price(cfg['price_stars'])}⭐</s>"
    )

def sorted_active_tiers() -> list[tuple[int, dict]]:
    """Тарифы в порядке показа (menu_number), а не в порядке ключей SUBSCRIPTION_TIERS —
    так самые выгодные для нас предложения можно выводить первыми, не трогая сами tier id."""
    return sorted(ACTIVE_SUBSCRIPTION_TIERS.items(), key=lambda kv: kv[1].get("menu_number", 999))

def cheapest_active_tier(predicate=lambda cfg: True) -> dict:
    """Самый дешёвый тариф из числа продающихся сейчас, подходящий под predicate — чтобы не
    хардкодить цены/тарифы в текстах отдельно от SUBSCRIPTION_TIERS (см. CLAUDE.md pitfalls)."""
    candidates = [cfg for cfg in ACTIVE_SUBSCRIPTION_TIERS.values() if predicate(cfg)]
    return min(candidates, key=lambda c: c["price_rub"])

def cheapest_gated3_tier() -> dict:
    """Самый дешёвый тариф, открывающий все три предмета Био/Физ/Хим (не тариф с выбором
    одного предмета)."""
    return cheapest_active_tier(lambda cfg: not cfg.get("subject_choice_required"))

def cheapest_histology_tier() -> dict:
    return cheapest_active_tier(lambda cfg: cfg.get("histology_until_rule") is not None)

def cheapest_anatomy_tier() -> dict:
    return cheapest_active_tier(lambda cfg: cfg.get("anatomy"))

def cheapest_biology_download_tier() -> dict:
    return cheapest_active_tier(lambda cfg: cfg.get("biology_download"))

def get_subscription(user_id: int) -> dict:
    return tb.stats["subscriptions"].get(str(user_id))

def has_active_subscription(user_id: int) -> bool:
    sub = get_subscription(user_id)
    if not sub:
        return False
    expires = sub.get("expires")
    return expires is None or time.time() < expires

def has_subject_access(user_id: int, subject: str) -> bool:
    """Доступ к конкретному гейтящемуся предмету (biology/physics/chemistry) — в отличие от
    has_free_access() учитывает, что тариф «3 дня, 1 предмет» открывает только ОДИН предмет."""
    if (
        is_admin_or_assistant(user_id)
        or is_section_promo_active("global")
        or get_referral_count_this_month(user_id) >= REFERRAL_FULL_ACCESS_THRESHOLD
        or user_id in tb.stats["manual_access_granted"]
        or has_temp_access(user_id)
    ):
        return True
    sub = get_subscription(user_id)
    if not sub or not has_active_subscription(user_id):
        return False
    restricted = sub.get("restricted_subject")
    return restricted is None or restricted == subject

def _sub_has_histology(sub: dict) -> bool:
    if "histology_access" in sub:
        if not sub["histology_access"]:
            return False
        until = sub.get("histology_until")
        return until is None or time.time() < until
    # легаси-подписки, выданные до введения этого поля
    if sub.get("scope") == "all" or sub.get("early_histology", False):
        return True
    return sub.get("tier") == 1 and time.time() < TIER1_HISTOLOGY_DEADLINE

def _sub_has_anatomy(sub: dict) -> bool:
    if "anatomy" in sub:
        return bool(sub["anatomy"])
    return sub.get("scope") == "all"

def _sub_has_biology_download(sub: dict) -> bool:
    if "biology_download" in sub:
        return bool(sub["biology_download"])
    return sub.get("scope") == "all"

def has_subscription_scope_all(user_id: int) -> bool:
    """Легаси-предикат для старых подписок (scope="all"). Новый код использует
    has_subscription_anatomy_access()/biology_tickets_download_ok() напрямую."""
    sub = get_subscription(user_id)
    return bool(sub) and sub.get("scope") == "all" and has_active_subscription(user_id)

def has_subscription_histology_access(user_id: int) -> bool:
    sub = get_subscription(user_id)
    if not sub or not has_active_subscription(user_id):
        return False
    return _sub_has_histology(sub)

def has_subscription_anatomy_access(user_id: int) -> bool:
    sub = get_subscription(user_id)
    if not sub or not has_active_subscription(user_id):
        return False
    return _sub_has_anatomy(sub)

def biology_tickets_download_ok(user_id: int) -> bool:
    if is_admin_or_assistant(user_id):
        return True
    sub = get_subscription(user_id)
    if not sub or not has_active_subscription(user_id):
        return False
    return _sub_has_biology_download(sub)

def grant_subscription(user_id: int, tier: int, method: str, price: int, subject: str | None = None) -> None:
    cfg = SUBSCRIPTION_TIERS[tier]
    now = time.time()
    if cfg.get("expires_at") is not None:
        expires = cfg["expires_at"]
    elif cfg.get("duration_days") is not None:
        expires = now + cfg["duration_days"] * 86400
    else:
        expires = None

    rule = cfg.get("histology_until_rule")
    histology_access = rule is not None
    histology_until = None if rule in (None, "expiry") else rule

    tb.stats["subscriptions"][str(user_id)] = {
        "tier": tier,
        "restricted_subject": subject if cfg.get("subject_choice_required") else None,
        "expires": expires,
        "histology_access": histology_access,
        "histology_until": histology_until,
        "anatomy": cfg.get("anatomy", False),
        "biology_download": cfg.get("biology_download", False),
        "cheat_sheets": cfg.get("cheat_sheets", False),
        # subscription_version у легаси-тарифов (1-11) в cfg отсутствует — .get(..., 1) даёт version 1,
        # ровно то же самое, что и старое поведение .get("subscription_version", 1) при чтении записи
        # без этого поля вообще. Явно писать его в запись безопасно и для старых tier id: их 100%
        # не продают заново, а если когда-то и продадут вручную — это и будет version 1, как раньше.
        "subscription_version": cfg.get("subscription_version", 1),
        "purchased_at": now,
        "method": method,
        "price": price,
    }
    tb.save_stats()

def has_free_access(user_id: int) -> bool:
    return (
        is_admin_or_assistant(user_id)
        or is_section_promo_active("global")
        or get_referral_count_this_month(user_id) >= REFERRAL_FULL_ACCESS_THRESHOLD
        or user_id in tb.stats["manual_access_granted"]
        or has_temp_access(user_id)
        or has_active_subscription(user_id)
    )

def get_exhausted_users() -> list:
    """ID пользователей, у которых счётчик предупреждений достиг порога и до сих пор нет доступа."""
    return [
        int(uid_str) for uid_str, entry in tb.stats["referral_warnings"].items()
        if entry.get("count", 0) >= REFERRAL_WARNING_THRESHOLD and not has_free_access(int(uid_str))
    ]

def get_below_threshold_users() -> list:
    """ID пользователей, у которых прямо сейчас нет бесплатного доступа к предметным разделам —
    меньше REFERRAL_FULL_ACCESS_THRESHOLD рефералов В ЭТОМ МЕСЯЦЕ и нет подписки/ручного
    доступа/временного доступа. Пересчитывается на лету от has_free_access(), поэтому автоматически
    актуализируется при смене месяца (пользователь, набравший норму в прошлом месяце и не
    приведший новых друзей, снова попадает в эту когорту)."""
    return [uid for uid in tb.stats["total_users"] if not has_free_access(uid)]


async def register_referral(referrer_id: int, referred_id: int) -> None:
    if referrer_id == referred_id:
        return
    if str(referred_id) in tb.stats["referred_by"]:
        return  # у этого пользователя уже есть реферер, повторно не засчитываем
    tb.stats["referred_by"][str(referred_id)] = referrer_id
    refs = tb.stats["referrals"].setdefault(str(referrer_id), [])
    if referred_id not in refs:
        refs.append(referred_id)
        _increment_referral_month_count(referrer_id)
        tb.save_stats()
        month_count = get_referral_count_this_month(referrer_id)
        month_line = (
            f"В этом месяце: <b>{month_count}</b> из {REFERRAL_FULL_ACCESS_THRESHOLD}, нужных для доступа.\n"
            if month_count < REFERRAL_FULL_ACCESS_THRESHOLD else
            "В этом месяце норма выполнена — доступ открыт до конца месяца! 🎉\n"
        )
        try:
            await tb.bot.send_message(
                referrer_id,
                "🎉 <b>По твоей ссылке в бота зашёл новый пользователь!</b>\n\n"
                f"{month_line}"
                f"Всего приглашено за всё время: <b>{len(refs)}</b>",
                parse_mode="HTML"
            )
        except Exception:
            tb.logger.exception("Не удалось уведомить реферера %s", referrer_id)
    else:
        tb.save_stats()


# Без нужного числа рефералов закрыты только 3 раздела — Биология, Физика, Химия.
# Всё остальное (админка, рефералы, битва, поддержка автора, анатомия) доступно всегда.
# Разбито по предметам (а не одним плоским множеством) — с тарифа «3 дня, один предмет»
# подписка может закрывать доступ только к одному конкретному предмету, и гейту нужно знать,
# какому именно предмету принадлежит каждый callback, а не просто «гейтится ли он вообще».
GATED_CALLBACKS_BIOLOGY = {
    "menu_biology", "menu_tickets", "menu_questions",
    "quiz_start", "quiz_show_answer", "quiz_know", "quiz_dont_know", "quiz_stop",
    "random_ticket", "question_random", "question_by_number", "question_search",
    # download_biology_tickets гейтится отдельно, biology_tickets_download_ok().
}
GATED_PREFIXES_BIOLOGY = ("ticket:", "ticket_q:", "qpage:", "q:")

GATED_CALLBACKS_PHYSICS = {
    "menu_physics", "physics_tickets", "physics_theory_tickets", "physics_test_tickets",
    "physics_task_tickets",
    "physics_test", "physics_tasks", "download_physics_full", "download_physics_ticket_tasks",
    "physics_grade45", "download_physics_grade45", "download_physics_tasks_cheatsheet", "physics_extra",
}
GATED_PREFIXES_PHYSICS = (
    "phys_test_ticket:", "phys_test_ticket_tasks:", "phys_test_ticket_task_show:", "physics_page:", "physics_q:",
    "phystask_topic:", "phystask_formulas:", "phystask_list:", "phystask_show:", "physics45_q:",
    "phys_theory_ticket:", "phys_theory_q:", "physics_extra_q:",
    "phys_task_ticket:", "phys_task_ticket_show:",
)

GATED_CALLBACKS_CHEMISTRY = {
    "menu_chemistry", "chemistry_theory", "chemistry_theory_list",
    "chemistry_tasks", "chemistry_labs", "download_chemistry_labs", "download_chemistry_tasks",
    "chemistry_tickets", "chem_theory_tickets", "chem_practice_tickets",
}
GATED_PREFIXES_CHEMISTRY = (
    "chem_theory:", "chemtask_topic:", "chemtask_formulas:", "chemtask_list:", "chemtask_show:",
    "lab:", "lab_exp:", "lab_calc:", "lab_summary:",
    "chem_theory_ticket:", "chem_theory_q:", "chem_practice_ticket:",
)

GATED_CALLBACKS = GATED_CALLBACKS_BIOLOGY | GATED_CALLBACKS_PHYSICS | GATED_CALLBACKS_CHEMISTRY
GATED_PREFIXES = GATED_PREFIXES_BIOLOGY + GATED_PREFIXES_PHYSICS + GATED_PREFIXES_CHEMISTRY

def get_gated_subject(data: str) -> str | None:
    """Возвращает 'biology'/'physics'/'chemistry', если callback относится к одному из закрытых
    разделов, иначе None (раздел не гейтится вообще)."""
    if data in GATED_CALLBACKS_BIOLOGY or data.startswith(GATED_PREFIXES_BIOLOGY):
        return "biology"
    if data in GATED_CALLBACKS_PHYSICS or data.startswith(GATED_PREFIXES_PHYSICS):
        return "physics"
    if data in GATED_CALLBACKS_CHEMISTRY or data.startswith(GATED_PREFIXES_CHEMISTRY):
        return "chemistry"
    return None

def is_gated_callback(data: str) -> bool:
    return get_gated_subject(data) is not None


def chemistry_tickets_access_ok(user_id: int) -> bool:
    """Дополнительное, более строгое ограничение только для раздела «Билеты» химии — обычного
    гейта по предмету (референт REFERRAL_FULL_ACCESS_THRESHOLD рефералов ИЛИ любой доступ к
    Химии, включая ручной/временный доступ и промо) недостаточно. Сюда пускают только по
    REFERRAL_FULL_ACCESS_THRESHOLD рефералам либо по активной подписке ценой от 89₽ — то есть
    ручной/временный доступ и промо-акции ("Снять все ограничения") здесь не считаются. Порог
    89₽ — историческая цена самого дешёвого тарифа, открывавшего все три гейтящихся предмета
    разом (не привязан к текущему каталогу тарифов) — новый тариф 20 (99₽) уже проходит его
    без изменений. Дополнительно уважает restricted_subject: тариф с выбором ОДНОГО предмета
    (например 20 или легаси 5) открывает билеты по химии, только если выбрана именно химия —
    без этой проверки подписка на Биологию/Физику той же ценовой категории ошибочно тоже
    открывала бы билеты по химии (пред-существовавший пробел, здесь же и закрытый)."""
    if is_admin_or_assistant(user_id):
        return True
    if get_referral_count_this_month(user_id) >= REFERRAL_FULL_ACCESS_THRESHOLD:
        return True
    sub = get_subscription(user_id)
    if sub and has_active_subscription(user_id):
        cfg = SUBSCRIPTION_TIERS.get(sub.get("tier"), {})
        restricted = sub.get("restricted_subject")
        if cfg.get("price_rub", 0) >= 89 and (restricted is None or restricted == "chemistry"):
            return True
    return False
