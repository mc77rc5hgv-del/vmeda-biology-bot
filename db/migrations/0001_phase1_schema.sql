-- Phase 1 critical-state schema (users / subscriptions / payments / manual_grants / referrals /
-- ai_usage_daily) — see docs/postgres_migration_design.md for the full design rationale.
--
-- Idempotent by construction (IF NOT EXISTS everywhere) — safe to run against a fresh database
-- or re-run against one that already has this schema applied. Applied automatically by
-- scripts/migrate_stats_to_postgres.py before it backfills any data; can also be applied by hand:
--   psql "$DATABASE_URL" -f db/migrations/0001_phase1_schema.sql

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
    UNIQUE (user_id, purchased_at)
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_current ON subscriptions (user_id, purchased_at DESC);
-- UNIQUE(user_id, purchased_at): у append-only таблицы без бизнес-ключа backfill-скрипт не может
-- быть идемпотентным без чего-то для ON CONFLICT -- purchased_at = time.time() в момент реальной
-- выдачи, две РАЗНЫЕ покупки одного юзера физически не могут совпасть с точностью до микросекунд,
-- так что это безопасный естественный ключ и для продовых данных, не только для дедупа бэкфилла.
-- "действующая подписка юзера" = первая строка при таком индексе -> дешёвый point-lookup:
--   SELECT * FROM subscriptions WHERE user_id = ? ORDER BY purchased_at DESC LIMIT 1

-- ==================== payments ====================
CREATE TABLE IF NOT EXISTS payments (
    charge_id  TEXT PRIMARY KEY,        -- Stars: telegram_payment_charge_id;
                                         -- рубли: синтетический 'rub_{user_id}_{tier}_{ts}'
    user_id    BIGINT NOT NULL REFERENCES users(user_id),
    kind       TEXT NOT NULL CHECK (kind IN
                   ('sub_stars', 'sub_rubles', 'sub_rubles_manual', 'donation_stars', 'donation_rubles')),
    amount     INT NOT NULL,
    tier       INT,                     -- NULL для донатов
    payload    TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- PRIMARY KEY уже даёт UNIQUE(charge_id) — прямая замена stats["processed_payment_charge_ids"],
-- ключевая гарантия идемпотентности платежей (design doc §9).

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
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals (referrer_id, created_at);
-- get_referral_count()             = COUNT(*) WHERE referrer_id = ?
-- get_referral_count_this_month()  = COUNT(*) WHERE referrer_id = ? AND created_at >= <МСК-начало месяца>
-- "кто пригласил этого юзера"      = SELECT referrer_id WHERE referred_id = ?

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
