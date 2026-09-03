# PostgreSQL: technical design (Phase 1 — критическое состояние)

Статус: **round 2 применён и провалидирован** (`db/migrations/0001_phase1_schema.sql`,
`scripts/migrate_stats_to_postgres.py`, `scripts/diff_json_vs_postgres.py`). Цель этого документа —
зафиксировать план перед тем, как трогать `stats.json`, который сегодня является единственным
persistence-слоем бота (см. CLAUDE.md → "Stats persistence").

Все три правки ниже (§2) уже в коде и проверены end-to-end против реального локального Postgres 16
(не production — синтетические тестовые данные, база создана и удалена в рамках проверки):
идемпотентность backfill'а через `source_legacy_key` (повторный прогон не задваивает строку и не
мешает живым покупкам с `NULL` в этой колонке), `referrals.created_at NULL` для legacy-строк +
`referral_monthly_legacy_credit` (переходная формула проверена явно: 2 legacy-реферала +
1 "живой" dual-write реферал корректно дают 3, без двойного счёта), и `payment_requests` +
`rub_req_{id}` как стабильный ключ дедупа RUB-платежей (смоделирована гонка двух админов,
подтверждающих одну заявку — выигрывает ровно один `INSERT`). `scripts/diff_json_vs_postgres.py`
(§5 ниже) реализован и тоже проверен на обоих исходах — 0 расхождений, когда JSON и Postgres
реально совпадают, и построчный отчёт при намеренно внесённом расхождении.

**Чего всё ещё нет** (следующие шаги, не в этом заходе): dual-write в реальном коде бота
(`grant_subscription()`/`register_referral()`/`handle_successful_payment()` пока пишут только в
`stats.json`), флага `PERSISTENCE_BACKEND`, и самого cutover — см. §6/§7 ниже, это по-прежнему
план, а не факт.

Скоуп сознательно ограничен: переносим только то, что действительно рискованно держать в одном
JSON-файле без транзакций и constraints — платежи, подписки, права доступа, рефералы, счётчики
AI-квоты и сами пользователи. Кэш (`ai_answer_cache`, `ai_raw_text_aliases`), вторичная
статистика (лидерборды, `broadcast_count`, `question_opened`, `donor_*` и т.п.) остаются в JSON —
их потеря не бьёт по деньгам и не ломает доступ, поэтому они не в Phase 1.

---

## 1. Что сейчас живёт в `stats.json`

Полная опись top-level ключей (`load_stats()`, `telegram_bot.py:148-232`) с пометкой,
переносим ли в Phase 1:

| Ключ | Форма | Phase 1? |
|---|---|---|
| `total_users` | `set[uid]` | ✅ → `users` |
| `user_names`, `user_username`, `usernames` | `{uid: name}`, `{uid: username}`, `{username: uid}` (три структуры ради одних и тех же двух фактов) | ✅ → `users` |
| `subscriptions` | `{uid: {...}}`, ОДНА запись на юзера, перезаписывается при новой покупке | ✅ → `subscriptions` |
| `processed_payment_charge_ids` | `{charge_id: {user_id, stars, payload, at}}` | ✅ → `payments` |
| `manual_access_granted`, `manual_anatomy_demo_granted` | `list[uid]`, булев флаг без срока | ✅ → `manual_grants` |
| `temporary_access`, `histology_temp_access` | `{uid: expires_ts}` | ✅ → `manual_grants` |
| `referrals`, `referred_by` | `{referrer: [referred,...]}`, `{referred: referrer}` — два представления одного факта | ✅ → `referrals` |
| `referral_monthly` | `{uid: {month, count}}` — ручной бегущий счётчик | ✅ (заменяется на `COUNT(*)`, см. §3) |
| `referral_warnings` | `{uid: {count, last_warn_at}}` | ✅ → `referral_warnings` |
| `ai_usage` | `{uid: {date, count}}` — только "сегодня" | ✅ → `ai_usage_daily` |
| `ai_cost_totals`, `ai_cost_windows` | глобальные агрегаты (не per-user) | ❌ остаётся в JSON |
| `ai_answer_cache`, `ai_raw_text_aliases` | кэш ответов AI | ❌ остаётся в JSON (аудит-пункт про versioning — отдельная задача) |
| `donor_stars`, `donor_rubles`, `donor_hide_name`, `donations_stars_total/count` | донаты/лидерборд | ❌ остаётся |
| `anatomy_latin_scores`, `anatomy_exam_test_scores`, `anatomy_exam_test_mode`, `anatomy_exam_flash_scores` | учебный прогресс/лидерборды | ❌ остаётся |
| `rollcall_confirmed`, `section_promos`, `referral_battle`, `helperchat_promo_seen`, `broadcast_count`, `question_opened`, `assistant_admins`, счётчики `start_count`/`random_*_used` | разное, не критично | ❌ остаётся |

---

## 2. Что переносим первым (Phase 1)

users → subscriptions → payments → manual_grants → referrals(+warnings) → ai_usage_daily

Порядок важен только для FK (`user_id` везде ссылается на `users`), сам перенос — одна транзакция
на таблицу, весь Phase 1 разворачивается одним прогоном backfill-скрипта. `payment_requests` и
`referral_monthly_legacy_credit` (новые вспомогательные таблицы, см. §3) в этот список не входят
отдельными доменами: для первой в JSON нет исторических данных вообще (backfill её не наполняет,
только создаёт — см. §3/§9), вторая наполняется как часть переноса `referrals`.

**Осознанные отступления от 1:1 копии JSON** (каждое — низкий риск, объясняю почему):

- **`subscriptions` становится append-only историей**, а не одной перезаписываемой записью.
  Сегодня покупка нового тарифа УНИЧТОЖАЕТ запись о предыдущем — это не баг, который нужно чинить
  прямо сейчас, но раз всё равно переносим в реляционную модель, дешевле сразу писать `INSERT`
  вместо `UPDATE ... WHERE user_id=?`. Действующая подписка — это `SELECT ... WHERE user_id=?
  ORDER BY purchased_at DESC LIMIT 1`, что для приложения ведёт себя ИДЕНТИЧНО сегодняшнему
  `stats["subscriptions"][uid]`.
  **Идемпотентность backfill'а через `source_legacy_key`, не через `(user_id, purchased_at)`.**
  У append-only таблицы без бизнес-ключа `BIGSERIAL id` сам по себе НЕ мешает повторному запуску
  `migrate_stats_to_postgres.py` вставить одну и ту же legacy-подписку второй раз — это реальная
  дыра, а не гипотетическая (проявилась на практике при первом тестовом прогоне скрипта: 2
  вызова подряд задвоили строку). Решение — отдельная колонка
  `source_legacy_key TEXT UNIQUE`, которую backfill проставляет как `legacy_subscription_{user_id}`
  (в JSON ровно одна подписка на юзера, так что этого достаточно для уникальности), а обычный
  `grant_subscription()` в проде НИКОГДА её не трогает (значение остаётся `NULL`) — постгресовый
  `UNIQUE` не считает несколько `NULL` конфликтующими, так что колонка не создаёт для живых покупок
  никаких новых ограничений и полностью изолирует "это строка из одноразового бэкфилла" от "это
  реальная покупка". См. схему в §3.
- **`manual_access_granted` / `manual_anatomy_demo_granted` / `temporary_access` /
  `histology_temp_access` схлопываются в одну таблицу `manual_grants(user_id, grant_type,
  expires_at)`.** Сегодня это четыре независимые структуры ради одного и того же факта ("у юзера
  X есть право Y до момента Z или навсегда") — везде разный код чтения (`in list` vs `dict.get`),
  везде отдельно нужно было не забыть завести ключ в `load_stats()`. Одна таблица с
  `PRIMARY KEY(user_id, grant_type)` и `expires_at NULL = навсегда`.
- **`referral_monthly` в конечном виде заменяется на `COUNT(*) FROM referrals WHERE
  created_at >= <начало месяца, МСК>`** — тот же результат, но без риска рассинхронизации между
  двумя счётчиками, которые сегодня нужно инкрементировать синхронно вручную. **Но у backfill'а
  здесь есть дыра, которую нельзя закрывать наивно.** У исторических `stats["referrals"][referrer]`
  НЕТ даты каждого конкретного реферала — это плоский список `referred_id` без таймстампов. Если
  проставить всем backfilled-строкам `created_at = <время миграции>`, то сразу после cutover
  `COUNT(*) WHERE created_at >= начало месяца` посчитает вообще ВСЕ рефералы каждого юзера за всё
  время как "рефералы этого месяца" — например, у реферера с 50 рефералами за год внезапно
  окажется 50 "новых" в месяц миграции, хотя по факту в этом месяце их могло не быть вообще.
  Решение — двухчастная **transition-схема**, а не мгновенная замена:
  - `referrals.created_at` становится **`NULLABLE`**. Исторические (backfilled) строки получают
    `created_at = NULL` — явное "неизвестно", а не угаданная дата. Новые рефералы (dual-write и
    далее) всегда пишут настоящий `created_at = now()`.
  - Текущее значение `stats["referral_monthly"][uid] = {month, count}` переносится ОДИН РАЗ как
    снимок в отдельную таблицу `referral_monthly_legacy_credit(user_id, month, count)` — "вот
    сколько рефералов уже было засчитано за месяц `month` ДО того, как появились точные даты".
  - На весь переходный период (до конца ТОГО САМОГО месяца, что записан в `month`) месячный счёт
    считается как **`legacy_credit.count (если legacy_credit.month = текущий месяц, иначе 0) +
    COUNT(*) FROM referrals WHERE referrer_id=? AND created_at >= начало текущего месяца`** —
    старые рефералы (без даты) в `COUNT(*)` не попадают вообще (их `created_at IS NULL` не
    проходит сравнение `>=`), а всё, что было НАКОПЛЕНО в счётчике до бэкфилла, учтено ровно один
    раз через legacy-снимок. Двойного счёта нет: legacy-снимок покрывает период "до миграции", а
    `COUNT(*)` — период "с момента миграции и позже", это непересекающиеся окна одного месяца.
  - Как только реальный календарный месяц меняется, условие `legacy_credit.month = текущий месяц`
    перестаёт выполняться само по себе (без единой миграции/крона) — legacy-credit перестаёт что-
    либо давать, и формула сама по себе становится чистым `COUNT(*) FROM referrals WHERE
    created_at >= начало месяца`, что и есть целевая steady-state архитектура. Таблицу
    `referral_monthly_legacy_credit` после этого можно спокойно дропнуть (не обязательно сразу).
  - **Инвариант, который это должно гарантировать**: ни один пользователь не должен ни получить,
    ни потерять реферальный доступ из-за отсутствующих исторических таймстампов — ровно то число,
    что сегодня отдаёт `get_referral_count_this_month()`, должно совпадать с формулой выше в
    момент cutover (это должен проверять `diff_json_vs_postgres.py`, см. §5).
- **`referred_by` не отдельная таблица** — это тот же `referrals`, прочитанный в обратную
  сторону (`SELECT referrer_id FROM referrals WHERE referred_id=?`), и заодно `referred_id` как
  `PRIMARY KEY` — это ровно та проверка анти-фрода ("у пользователя уже есть реферер"), которая
  сегодня руками делается в `register_referral()` веткой `if str(referred_id) in
  stats["referred_by"]: return`. В Postgres это `INSERT ... ON CONFLICT (referred_id) DO NOTHING`,
  и по числу задетых строк (0 или 1) сразу видно, была это новая запись или дубль — без отдельного
  SELECT перед INSERT.

Если какое-то из этих решений выглядит как overreach для Phase 1 — это единственные места, где я
осознанно отступил от чистого переноса, специально их выделил, чтобы можно было выкинуть по
отдельности.

---

## 3. Схема

Реализовано в `db/migrations/0001_phase1_schema.sql` (идемпотентно, `IF NOT EXISTS` везде) —
при расхождении с блоком ниже актуален файл, не этот документ.

```sql
-- ==================== users ====================
CREATE TABLE users (
    user_id     BIGINT PRIMARY KEY,
    username    TEXT UNIQUE,          -- заменяет user_username + usernames разом
    full_name   TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- username бывает NULL (не у всех в Telegram он есть) и МЕНЯЕТСЯ — UNIQUE держит уникальность
-- на текущий момент, апдейт делает UPDATE users SET username=? WHERE user_id=?, старое значение
-- просто перезаписывается (ровно как сегодня в stats["usernames"]).

-- ==================== subscriptions (append-only, см. §2) ====================
CREATE TABLE subscriptions (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES users(user_id),
    tier                INT NOT NULL,
    restricted_subject  TEXT,                 -- NULL если тариф не subject_choice_required
    expires             TIMESTAMPTZ,          -- NULL = навсегда
    histology_access    BOOLEAN NOT NULL DEFAULT FALSE,
    histology_until     TIMESTAMPTZ,          -- NULL = "как sub.expires"
    anatomy             BOOLEAN NOT NULL DEFAULT FALSE,
    biology_download    BOOLEAN NOT NULL DEFAULT FALSE,
    cheat_sheets        BOOLEAN NOT NULL DEFAULT FALSE,
    subscription_version INT NOT NULL DEFAULT 1,
    purchased_at        TIMESTAMPTZ NOT NULL,
    method              TEXT NOT NULL,        -- 'stars' | 'rubles' | 'rubles_manual'
    price               INT NOT NULL,
    ai_used_period      INT NOT NULL DEFAULT 0,
    ai_used_monthly_month TEXT,                -- "YYYY-MM", МСК (см. APP_TIMEZONE)
    ai_used_monthly_count INT NOT NULL DEFAULT 0,
    source_legacy_key TEXT UNIQUE            -- ТОЛЬКО для backfill: 'legacy_subscription_{user_id}'.
                                              -- Живые продовые INSERT'ы всегда оставляют NULL —
                                              -- несколько NULL в UNIQUE-колонке друг другу не
                                              -- конфликтуют, так что прод от этой колонки не зависит.
);
CREATE INDEX idx_subscriptions_current ON subscriptions (user_id, purchased_at DESC);
-- "действующая подписка юзера" = первая строка при таком индексе -> дешёвый point-lookup.

-- ==================== payment_requests (RUB-заявки — см. §6/§9) ====================
CREATE TABLE payment_requests (
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
-- UUID4) идёт в callback_data КАЖДОЙ admin_confirm_sub-кнопки у КАЖДОГО админа. Это и есть
-- стабильный payment_request_id: оба админа ссылаются на одну и ту же строку, а не каждый
-- генерирует свой идентификатор в момент собственного клика.

-- ==================== payments ====================
CREATE TABLE payments (
    charge_id   TEXT PRIMARY KEY,     -- Stars: telegram_payment_charge_id (от Telegram);
                                       -- рубли: 'rub_req_{payment_requests.id}' (см. §6/§9) —
                                       -- НЕ производное от времени клика, единое для всех попыток
                                       -- подтвердить одну и ту же заявку.
    user_id     BIGINT NOT NULL REFERENCES users(user_id),
    kind        TEXT NOT NULL CHECK (kind IN
                    ('sub_stars', 'sub_rubles', 'sub_rubles_manual', 'donation_stars', 'donation_rubles')),
    amount      INT NOT NULL,
    tier        INT,                  -- NULL для донатов
    payload     TEXT,
    payment_request_id BIGINT REFERENCES payment_requests(id),  -- NULL для Stars/донатов
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- UNIQUE уже даёт PRIMARY KEY. Для Stars это прямая замена stats["processed_payment_charge_ids"].
-- Для RUB это то же самое constraint'ом на charge_id, но теперь СЕМАНТИЧЕСКИ корректное — оба
-- админа, подтверждающие ОДНУ заявку, порождают ОДИНАКОВЫЙ charge_id, так что второй INSERT
-- гарантированно ловится ON CONFLICT, а не проходит как "новый, но с виду похожий" платёж.

-- ==================== manual_grants (см. §2) ====================
CREATE TABLE manual_grants (
    user_id     BIGINT NOT NULL REFERENCES users(user_id),
    grant_type  TEXT NOT NULL CHECK (grant_type IN
                    ('full_access', 'anatomy_demo', 'temp_access', 'histology_temp')),
    expires_at  TIMESTAMPTZ,          -- NULL = навсегда (только full_access/anatomy_demo)
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    granted_by  BIGINT,               -- admin user_id, NULL для авто-выдач (перекличка и т.п.)
    PRIMARY KEY (user_id, grant_type)
);

-- ==================== referrals ====================
CREATE TABLE referrals (
    referred_id BIGINT PRIMARY KEY REFERENCES users(user_id),  -- 1 реферер на юзера — сама схема это гарантирует
    referrer_id BIGINT NOT NULL REFERENCES users(user_id),
    created_at  TIMESTAMPTZ         -- NULL = дата неизвестна (legacy backfill, см. §2/§4).
                                     -- Новые рефералы (dual-write и далее) ВСЕГДА пишут now().
);
CREATE INDEX idx_referrals_referrer ON referrals (referrer_id, created_at);
-- get_referral_count()             = COUNT(*) WHERE referrer_id=? (NULL created_at не мешает —
--                                     COUNT(*) считает строки, а не непустые значения колонки)
-- get_referral_count_this_month()  = см. transition-формулу в §2 (legacy_credit + COUNT(*) WHERE
--                                     created_at >= МСК-начало месяца — NULL в это сравнение не
--                                     попадает никогда, ровно то поведение, которое нужно)
-- get_referral_link "кто меня пригласил" = SELECT referrer_id WHERE referred_id=?

-- Одноразовый снимок stats["referral_monthly"] на момент backfill'а — см. §2 (transition-схема)
-- и §4. Актуален только пока month = текущий календарный месяц; после смены месяца больше не
-- участвует ни в одном запросе, можно дропнуть.
CREATE TABLE referral_monthly_legacy_credit (
    user_id BIGINT PRIMARY KEY REFERENCES users(user_id),
    month   TEXT NOT NULL,   -- "YYYY-MM", МСК — тот же формат, что stats["referral_monthly"][uid]["month"]
    count   INT NOT NULL
);

CREATE TABLE referral_warnings (
    user_id     BIGINT PRIMARY KEY REFERENCES users(user_id),
    count       INT NOT NULL DEFAULT 0,
    last_warn_at TIMESTAMPTZ
);

-- ==================== ai_usage_daily ====================
CREATE TABLE ai_usage_daily (
    user_id BIGINT NOT NULL REFERENCES users(user_id),
    day     DATE NOT NULL,             -- local_today(), МСК
    count   INT NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);
-- get_ai_usage_today() = count WHERE user_id=? AND day=local_today() (0 если строки нет).
-- В отличие от сегодняшнего stats["ai_usage"] (только "текущий день"), тут остаётся история —
-- это не используется приложением сейчас, но ничего не стоит и не меняет поведение.
```

Все FK на `users(user_id)` требуют, чтобы юзер уже существовал — приложение и так сегодня
регистрирует пользователя (`stats["total_users"].add(...)`) раньше, чем что-либо ещё пишет по
нему, так что порядок вставки не меняется, только формализуется constraint'ом.

---

## 4. Перенос существующих записей (backfill)

Один скрипт, `scripts/migrate_stats_to_postgres.py`, читает текущий `stats.json` и пишет в
Postgres. Требования к скрипту:

- **Идемпотентен** — каждый `INSERT` через `ON CONFLICT (<natural PK>) DO UPDATE SET ...`
  (или `DO NOTHING` там, где повторная запись точно не может отличаться, например `payments`).
  Скрипт можно запускать сколько угодно раз подряд без риска задвоить данные — это и есть
  механизм "прогнать ещё раз после починки бага в самом скрипте".
- **Порядок** ровно как в §2 (FK на `users` первыми).
- **Не трогает `stats.json`** — файл остаётся источником истины до момента cutover (§7), скрипт
  только читает.
- Один прогон = одна связка транзакций (по одной на таблицу, не на всю БД сразу — так частичный
  сбой на середине не откатывает уже успешно перенесённые таблицы, а просто чинится повторным
  запуском благодаря идемпотентности выше).

Особые случаи при переносе:
- `subscriptions`: в JSON только последняя подписка на юзера — переносим как ОДНУ строку (первая
  запись в новой append-only истории), `source_legacy_key = 'legacy_subscription_{user_id}'`.
  `INSERT ... ON CONFLICT (source_legacy_key) DO NOTHING` — повторный прогон скрипта не задваивает
  строку. Дальнейшие покупки уже в Postgres добавляют новые строки с `source_legacy_key = NULL`.
- `payments`: `processed_payment_charge_ids` уже имеет `user_id`/`stars`/`payload`/`at` — прямое
  отображение полей, `kind` реконструируется из `payload` (`sub_stars_` → `sub_stars`, иначе
  `donation_stars`, рублёвые оплаты в этот dict сегодня не попадают вообще — см. §6 про их
  отдельный путь через `payment_requests`, для которого исторических данных в JSON просто нет: до
  этой правки рублёвые платежи не оставляли в `stats.json` НИКАКОГО журнала отдельных транзакций,
  только текущее состояние в `subscriptions[uid]["method"]`).
- `manual_grants`: четыре JSON-структуры → до четырёх строк на юзера, `expires_at` только у
  `temp_access`/`histology_temp`.
- `referrals`: список `referred_id` на реферера переносится в хронологическом порядке (порядок
  списка сохраняет `register_referral()`, всегда `append`), но `created_at = NULL` для всех строк
  — backfill НЕ пытается угадать дату. `referral_monthly` переносится отдельно, один снимок на
  юзера, в `referral_monthly_legacy_credit` — см. §2 за тем, как оба факта вместе восстанавливают
  корректный месячный счёт на переходный период.

---

## 5. Как проверяем совпадение JSON ↔ DB

`scripts/diff_json_vs_postgres.py` — read-only, гоняется вручную/по крону в течение всего периода
двойной записи (§6). На каждый прогон:

1. Загружает `stats.json`, коннектится к Postgres.
2. Для каждой из 6 доменных областей сравнивает **множество ключей** (кто в JSON есть, а в БД
   нет, и наоборот) и **посчитанные значения** там, где логика перенесена не 1:1 (например,
   `get_referral_count_this_month(uid)` из JSON-пути должен совпасть с `COUNT(*) ...` из
   Postgres-пути для каждого uid, у кого есть рефералы).
3. Печатает отчёт: `0 diffs` или построчный список расхождений с `user_id`/полем/JSON-значением/
   DB-значением.

Критерий готовности к cutover — **0 расхождений на протяжении N дней подряд под реальной
нагрузкой** (предлагаю N=3 для payments/subscriptions, поскольку там мало событий в день и любое
расхождение сразу заметно; N=7 для referrals/ai_usage, где событий больше и разовое совпадение
могло быть случайностью).

---

## 6. Двойная запись вместо жёсткого cutover

Флаг окружения `PERSISTENCE_BACKEND` (`json` по умолчанию → `dual` → `postgres`), читается один
раз при старте, как остальные env-переменные бота.

- **`json`** (сегодняшнее поведение) — ничего не меняется.
- **`dual`** — каждая точка записи для 6 Phase-1-доменов (сегодня это `save_stats()`-вызовы после
  мутации `stats["subscriptions"]`/`stats["referrals"]`/`stats["manual_access_granted"]`/т.п.)
  ПОСЛЕ успешной записи в JSON дополнительно, best-effort, зеркалирует то же самое в Postgres. Обёрнуто в
  `try/except`, ошибка похода в БД только логируется — бот не должен упасть или отказать в доступе
  из-за временной недоступности Postgres, пока JSON остаётся источником истины для ЧТЕНИЯ. Чтение
  (`get_subscription`, `has_free_access`, `ai_requests_left`, ...) в этом режиме всё ещё идёт из
  `stats` в памяти, как сегодня — Postgres в `dual` только копится и сверяется, ни на что не
  влияет.
- **`postgres`** — и чтение, и запись идут в Postgres; `stats.json` для этих 6 доменов больше не
  трогается (для остальных доменов — кэш/вторичная статистика — JSON продолжает быть
  единственным хранилищем, ничего не меняется).

**Про рублёвые платежи отдельно — сам механизм оплаты (ручное подтверждение админом в чате,
кнопка "💵 Оплатить X₽" → всем ADMIN_IDS уходит one-tap-кнопка подтверждения) НЕ меняется.**
Меняется только то, ЧТО в Postgres становится ключом дедупликации.

У Stars есть `telegram_payment_charge_id` от Telegram — готовый внешний ID, дедуп тривиален
(§9). У рублёвого one-tap подтверждения (`cb_admin_confirm_sub`) внешнего ID нет вообще — сегодня
дедуп держится на 10-минутном окне по времени + tier + user_id внутри одного процесса (эвристика,
не гарантия). **Синтетический `rub_{user_id}_{tier}_{int(purchased_at)}` (первая версия этого
документа) НЕ решает проблему** — если два админа тапают "подтвердить" в разные секунды, каждый
формирует id в момент СВОЕГО клика, получает два РАЗНЫХ значения `int(purchased_at)`, и оба
`INSERT` проходят как два разных платежа: `UNIQUE(charge_id)` тут ничего не ловит, потому что
"уникальные" id и должны были быть разными для одного и того же события.

Правильный источник стабильности — не момент подтверждения, а момент СОЗДАНИЯ заявки. Когда
покупатель жмёт "💵 Оплатить X₽" (тот же самый момент, когда сегодня `notify_admins_of_payment_request()`
рассылает кнопки), заводится ОДНА строка в `payment_requests` (см. §3), и её `id` подставляется в
callback_data КАЖДОЙ отправленной админам кнопки — оба админа видят кнопки, ссылающиеся на один и
тот же `payment_requests.id`, а не каждый порождает свой идентификатор по факту клика.
`payments.charge_id` для этого пути = `f"rub_req_{payment_requests.id}"` — стабильно независимо от
того, кто из админов кликнул первым и с какой задержкой. Двойное нажатие теперь ловится настоящим
`UNIQUE`-конфликтом на уровне БД (см. транзакцию в §9), а не эвристикой "похожая запись за
последние 10 минут" в Python.

---

## 7. Момент cutover

1. `dual` держится живым минимум до выполнения критерия из §5 по всем 6 доменам.
2. Разворачивается флаг `postgres` **одним обычным Railway-деплоем** в тихие часы (по МСК —
   см. APP_TIMEZONE) — без даунтайма и без maintenance-окна, поскольку Postgres к этому моменту
   уже тёплый и подтверждённо совпадает с JSON.
3. Сразу после флипа `dual` НЕ выключается ещё несколько дней — JSON продолжает писаться
   параллельно (уже не как источник чтения, а просто как живой бэкап на случай отката), диффер
   из §5 продолжает гонять сверку в обратную сторону (БД теперь источник, JSON — резерв).
4. Только после спокойного периода без единого отката (предлагаю неделю) JSON-запись для этих 6
   доменов отключается насовсем; сам `stats.json` продолжает существовать для оставшихся
   некритичных доменов (кэш, лидерборды и т.д.) — полная замена JSON целиком не входит и не
   должна входить в Phase 1.

## 8. Откат

Поскольку JSON не переставал писаться вплоть до конца переходного периода (§7, шаг 3), откат —
это просто возврат `PERSISTENCE_BACKEND` на `json` тем же способом (Railway env var + redeploy).
Данные не теряются: любые Postgres-only изменения, случившиеся в узком окне `postgres`-режима до
отката, просто перестают быть видны приложению (JSON откатывается к своему последнему
согласованному состоянию), но остаются в БД для последующего ручного разбора — ничего не
удаляется, откат не деструктивен.

## 9. Транзакционность платежей (ключевое требование)

Сегодня `handle_successful_payment` — это последовательность независимых операций поверх
JSON-словаря в памяти (проверить `charge_id`, записать `charge_id`, вызвать
`grant_subscription()`, `save_stats()`). В Postgres-режиме связка "платёж + выдача подписки"
становится ОДНОЙ транзакцией:

```sql
BEGIN;
INSERT INTO payments (charge_id, user_id, kind, amount, tier, payload)
VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (charge_id) DO NOTHING;
-- если INSERT вернул 0 затронутых строк -> это повтор, ROLLBACK, ничего не выдаём (см. приложение)
INSERT INTO subscriptions (user_id, tier, ..., purchased_at, method, price)
VALUES ($2, $5, ..., now(), $7, $4);
COMMIT;
```

Приложение читает `INSERT ... ON CONFLICT DO NOTHING` через `RETURNING charge_id` — пустой
результат означает дубликат, код в этом случае делает `ROLLBACK` и ведёт себя как сегодняшний
ранний `return` в `handle_successful_payment`, только гарантию теперь даёт сама СУБД, а не
Python-проверка `if charge_id in stats[...]` с отдельным последующим `save_stats()`, между
которыми в JSON-модели теоретически мог быть промежуток без надёжной атомарности при двух
параллельных вызовах.

**Тот же паттерн для RUB one-tap подтверждения** (`cb_admin_confirm_sub`, см. §6) — единственное
отличие от Stars-пути в том, что здесь `charge_id` не приходит от Telegram, а строится из уже
существующей заявки:

```sql
BEGIN;
INSERT INTO payments (charge_id, user_id, kind, amount, tier, payload, payment_request_id)
VALUES ('rub_req_' || $1, $2, 'sub_rubles', $3, $4, NULL, $1)
ON CONFLICT (charge_id) DO NOTHING;
-- 0 затронутых строк -> это НЕ первое подтверждение этой заявки (второй админ), ROLLBACK, ничего
-- не выдаём, второй тап становится обычным "уже подтверждено" в UI, как и сегодня
INSERT INTO subscriptions (user_id, tier, ..., purchased_at, method, price)
VALUES ($2, $4, ..., now(), 'rubles', $3);
COMMIT;
```

Оба админа могут нажать "подтвердить" на СВОЙ экземпляр кнопки в любой момент, в любом порядке,
с любой задержкой — обе попытки бьются об один и тот же `payment_requests.id = $1`, и ровно ОДНА
из двух транзакций реально доходит до `INSERT INTO subscriptions`; какая именно — решает СУБД, а
не порядок обращения к Python-словарю в памяти, так что гарантия не зависит ни от количества
процессов бота, ни от рестарта между двумя кликами.

Ручной flow (`method="rubles_manual"` — админ через `ADMIN_PENDING` дарит подписку без покупателя,
проходящего через кнопки, см. CLAUDE.md → "Manual flow") этой схемой не затронут вообще: там нет
`payment_requests`, нет гонки двух админов (действие совершает один админ последовательным вводом
текста), поэтому нечего дедуплицировать. Такая выдача просто пишет `subscriptions` без
соответствующей строки в `payments` (либо со строкой без `payment_request_id`, если аудит важнее)
— в точности как сегодня `"rubles_manual"` уже сознательно исключён из `sub_revenue_rubles`, см.
CLAUDE.md.

---

## Что дальше

**Review round 2 закрывает три пункта, поднятых по итогам round 1:**
1. `subscriptions` — идемпотентность backfill'а теперь через `source_legacy_key`, а не через
   совпадение `(user_id, purchased_at)`.
2. `referrals` — исторические `created_at` теперь `NULL`, а не время миграции; месячный счёт на
   переходный период = `referral_monthly_legacy_credit` + `COUNT(*)` по известным датам,
   автоматически перестающий учитывать legacy-снимок после смены календарного месяца.
3. RUB-платежи — дедуп-ключ теперь строится от `payment_requests.id`, заводимого один раз в
   момент создания заявки, а не от `int(purchased_at)` в момент клика админа — это была реальная
   P0-дыра в исходном дизайне (два клика двух админов в разные секунды раньше давали два разных
   "уникальных" id и потенциально двойную выдачу). Механизм ручного подтверждения оплаты (кнопка
   у покупателя → одна кнопка каждому админу → первый клик выигрывает) не меняется, меняется
   только то, что физически кладётся в `charge_id`.

**Код обновлён под все три правки и провалидирован** — см. статус в начале документа. `DDL`
(`db/migrations/0001_phase1_schema.sql`), `migrate_stats_to_postgres.py` и `diff_json_vs_postgres.py`
(§5) все существуют и прогонялись против реального локального Postgres 16 на синтетических данных
(идемпотентность backfill'а, переходная формула месячных рефералов, гонка двух админов на RUB —
все три сценария явно воспроизведены и дали ожидаемый результат).

Следующий шаг — не в этом документе: dual-write в реальном коде бота (§6) и флаг
`PERSISTENCE_BACKEND`, начиная с самого маленького домена (`ai_usage_daily` или `manual_grants` —
меньше всего связанных инвариантов) прежде чем переходить к платежам/подпискам.
