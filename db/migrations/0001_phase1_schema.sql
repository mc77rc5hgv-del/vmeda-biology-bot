-- Phase 1 critical-state schema (users / subscriptions / payment_requests / payments /
-- manual_grants / referrals / ai_usage_daily) — see docs/postgres_migration_design.md for the
-- full design rationale.
--
-- Idempotent by construction (IF NOT EXISTS everywhere) — safe to run against a fresh database
-- or re-run against one that already has this schema applied. Applied automatically by
-- scripts/migrate_stats_to_postgres.py before it backfills any data; can also be applied by hand:
--   psql "$DATABASE_URL" -f db/migrations/0001_phase1_schema.sql
--
-- Round 2 of design review (see docs/postgres_migration_design.md, "Что дальше") — this version
-- closes the 3 gaps that round found relative to the schema round 1 shipped:
--   1. subscriptions dedups backfill via source_legacy_key, not UNIQUE(user_id, purchased_at).
--   2. referrals.created_at is nullable (historical rows), + referral_monthly_legacy_credit for
--      the transition-period monthly-count formula.
--   3. payment_requests exists, so the RUB one-tap confirm dedup key is stable across which admin
--      clicks first, not derived from the click timestamp.

-- ==================== users ====================
CREATE TABLE IF NOT EXISTS users (
    user_id       BIGINT PRIMARY KEY,
    username      TEXT UNIQUE,          -- заменяет stats["user_username"] + stats["usernames"] разом
    full_name     TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- username бывает NULL (не у всех в Telegram он есть) и МЕНЯЕТСЯ — UNIQUE держит уникальность
-- на текущий момент; апдейт делает UPDATE users SET username=? WHERE user_id=?, старое значение
-- просто перезаписывается (ровно как сегодня в stats["usernames"]).

-- ==================== subscriptions (append-only история — см. design doc §2) ====================
CREATE TABLE IF NOT EXISTS subscriptions (
    id                    BIGSERIAL PRIMARY KEY,
    user_id               BIGINT NOT NULL REFERENCES users(user_id),
    tier                  INT NOT NULL,
    restricted_subject    TEXT,                        -- NULL если тариф не subject_choice_required
    expires               TIMESTAMPTZ,                 -- NULL = навсегда
    histology_access      BOOLEAN NOT NULL DEFAULT FALSE,
    histology_until       TIMESTAMPTZ,                 -- NULL = "как expires"
    anatomy               BOOLEAN NOT NULL DEFAULT FALSE,
    biology_download      BOOLEAN NOT NULL DEFAULT FALSE,
    cheat_sheets          BOOLEAN NOT NULL DEFAULT FALSE,
    subscription_version  INT NOT NULL DEFAULT 1,
    purchased_at          TIMESTAMPTZ NOT NULL,
    method                TEXT NOT NULL,               -- 'stars' | 'rubles' | 'rubles_manual'
    price                 INT NOT NULL,
    ai_used_period        INT NOT NULL DEFAULT 0,
    ai_used_monthly_month TEXT,                         -- "YYYY-MM", МСК (см. APP_TIMEZONE)
    ai_used_monthly_count INT NOT NULL DEFAULT 0,
    source_legacy_key     TEXT UNIQUE                  -- ТОЛЬКО для backfill: 'legacy_subscription_{user_id}'.
                                                         -- Живые продовые INSERT'ы ВСЕГДА оставляют NULL —
                                                         -- несколько NULL в UNIQUE-колонке друг другу не
                                                         -- конфликтуют (стандартное поведение Postgres), так
                                                         -- что прод от этой колонки не зависит вообще.
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_current ON subscriptions (user_id, purchased_at DESC);
-- "действующая подписка юзера" = первая строка при таком индексе -> дешёвый point-lookup:
--   SELECT * FROM subscriptions WHERE user_id = ? ORDER BY purchased_at DESC LIMIT 1
--
-- ПОЧЕМУ не UNIQUE(user_id, purchased_at) (round 1 этой схемы): бэкфилл-скрипт можно запускать
-- повторно (например, после починки бага в самом скрипте, ДО реального cutover, когда stats.json
-- всё ещё источник истины) — при повторном прогоне purchased_at читается заново из ТОГО ЖЕ поля
-- JSON и получается БУКВАЛЬНО тем же самым значением, так что теоретически он должен был бы
-- ловиться этим UNIQUE... но на практике это подтверждённо задваивало строку при двух прогонах
-- подряд (см. design doc §2) — то ли из-за микросекундного округления при сериализации float ->
-- TIMESTAMPTZ, то ли из-за гонки, в любом случае это было ненадёжно. source_legacy_key — явный,
-- не зависящий от округления бизнес-ключ ИМЕННО для одной легаси-подписки на юзера.

-- ==================== payment_requests (RUB-заявки — см. design doc §6/§9) ====================
CREATE TABLE IF NOT EXISTS payment_requests (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(user_id),
    tier        INT NOT NULL,
    subject     TEXT,                 -- см. subject_choice_required в SUBSCRIPTION_TIERS
    price       INT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Заводится РОВНО ОДИН РАЗ в момент, когда покупатель жмёт "💵 Оплатить X₽" (там же, где сегодня
-- notify_admins_of_payment_request() рассылает кнопки всем ADMIN_IDS) — id этой строки (короткое
-- целое, безопасно помещается в 64-байтный лимит callback_data Telegram, в отличие от полного
-- UUID4) идёт в callback_data КАЖДОЙ admin_confirm_sub-кнопки у КАЖДОГО админа. Оба админа видят
-- кнопки, ссылающиеся на ОДНУ и ту же строку — а не каждый порождает свой идентификатор по факту
-- клика (см. payments.charge_id ниже за тем, как это закрывает гонку двух админов).
-- Нет исторических данных для backfill'а — таблица только заводится этой миграцией, наполняется
-- только вперёд, с момента появления реального one-tap flow поверх Postgres.

-- ==================== payments ====================
CREATE TABLE IF NOT EXISTS payments (
    charge_id           TEXT PRIMARY KEY,     -- Stars: telegram_payment_charge_id (от Telegram);
                                               -- рубли: 'rub_req_{payment_requests.id}' — НЕ
                                               -- производное от времени клика админа, единое для
                                               -- всех попыток подтвердить ОДНУ и ту же заявку.
    user_id             BIGINT NOT NULL REFERENCES users(user_id),
    kind                TEXT NOT NULL CHECK (kind IN
                            ('sub_stars', 'sub_rubles', 'sub_rubles_manual', 'donation_stars', 'donation_rubles')),
    amount              INT NOT NULL,
    tier                INT,                  -- NULL для донатов
    payload             TEXT,
    payment_request_id  BIGINT REFERENCES payment_requests(id),  -- NULL для Stars/донатов/ручных выдач
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- PRIMARY KEY уже даёт UNIQUE(charge_id) — прямая замена stats["processed_payment_charge_ids"]
-- для Stars, ключевая гарантия идемпотентности платежей (design doc §9). Для RUB это тот же
-- constraint, но теперь семантически корректный: оба админа, подтверждающие ОДНУ заявку,
-- порождают ОДИНАКОВЫЙ charge_id ('rub_req_' || payment_requests.id), так что второй INSERT
-- гарантированно ловится ON CONFLICT, а не проходит как "новый, но похожий" платёж — раньше
-- (round 1 этой схемы) charge_id для RUB строился от int(purchased_at) В МОМЕНТ КЛИКА, и два
-- клика двух админов в разные секунды давали два РАЗНЫХ "уникальных" id, т.е. UNIQUE ничего не
-- ловил. Механизм подтверждения (кнопка у покупателя → одна кнопка каждому админу → первый клик
-- выигрывает) при этом не меняется — меняется только то, что физически кладётся в charge_id.

-- ==================== manual_grants (схлопывает 4 JSON-структуры — см. design doc §2) ====================
CREATE TABLE IF NOT EXISTS manual_grants (
    user_id     BIGINT NOT NULL REFERENCES users(user_id),
    grant_type  TEXT NOT NULL CHECK (grant_type IN
                    ('full_access', 'anatomy_demo', 'temp_access', 'histology_temp')),
    expires_at  TIMESTAMPTZ,            -- NULL = навсегда (только full_access/anatomy_demo)
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    granted_by  BIGINT,                 -- admin user_id, NULL для авто-выдач (перекличка и т.п.)
    PRIMARY KEY (user_id, grant_type)
);

-- ==================== referrals ====================
CREATE TABLE IF NOT EXISTS referrals (
    referred_id BIGINT PRIMARY KEY REFERENCES users(user_id),  -- 1 реферер на юзера — гарантируется схемой
    referrer_id BIGINT NOT NULL REFERENCES users(user_id),
    created_at  TIMESTAMPTZ         -- NULL = дата неизвестна (legacy backfill, см. design doc §2/§4).
                                     -- Новые рефералы (dual-write и далее) ВСЕГДА пишут now().
);
CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals (referrer_id, created_at);
-- get_referral_count()             = COUNT(*) WHERE referrer_id = ? (NULL created_at не мешает —
--                                     COUNT(*) считает строки, а не непустые значения колонки)
-- get_referral_count_this_month()  = переходная формула — см. referral_monthly_legacy_credit ниже
--                                     и design doc §2 за полным разбором.
-- "кто пригласил этого юзера"      = SELECT referrer_id WHERE referred_id = ?
--
-- ПОЧЕМУ не NOT NULL DEFAULT now() (round 1 этой схемы): у исторических stats["referrals"][uid]
-- нет даты каждого конкретного реферала — это плоский список без таймстампов. Проставить всем
-- backfilled-строкам "время миграции" сломало бы get_referral_count_this_month() сразу после
-- cutover: реферер с 50 рефералами за год внезапно получил бы 50 "новых в этом месяце" и открыл
-- бы доступ, которого у него по факту не было. NULL — явное "неизвестно", а не угаданная дата.

-- Одноразовый снимок stats["referral_monthly"] на момент backfill'а — см. design doc §2 (переходная
-- схема) и §4. Актуален только пока month = текущий календарный месяц; после смены месяца больше
-- не участвует ни в одном запросе (условие "legacy_credit.month = текущий месяц" перестаёт
-- выполняться само по себе, без отдельной миграции/крона), можно спокойно дропнуть.
CREATE TABLE IF NOT EXISTS referral_monthly_legacy_credit (
    user_id BIGINT PRIMARY KEY REFERENCES users(user_id),
    month   TEXT NOT NULL,   -- "YYYY-MM", МСК — тот же формат, что stats["referral_monthly"][uid]["month"]
    count   INT NOT NULL
);
-- Переходная формула месячного счёта (действует только пока month здесь = текущий МСК-месяц):
--   legacy_credit.count (если legacy_credit.month = текущий месяц, иначе 0)
--   + COUNT(*) FROM referrals WHERE referrer_id = ? AND created_at >= <МСК-начало текущего месяца>
-- Двойного счёта нет: legacy_credit покрывает период "до миграции", COUNT(*) — период "с момента
-- миграции и позже" (у старых строк created_at IS NULL, в сравнение >= они никогда не попадают).

CREATE TABLE IF NOT EXISTS referral_warnings (
    user_id      BIGINT PRIMARY KEY REFERENCES users(user_id),
    count        INT NOT NULL DEFAULT 0,
    last_warn_at TIMESTAMPTZ
);

-- ==================== ai_usage_daily ====================
CREATE TABLE IF NOT EXISTS ai_usage_daily (
    user_id BIGINT NOT NULL REFERENCES users(user_id),
    day     DATE NOT NULL,              -- local_today(), МСК
    count   INT NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);
-- get_ai_usage_today() = count WHERE user_id = ? AND day = local_today() (0, если строки нет).
