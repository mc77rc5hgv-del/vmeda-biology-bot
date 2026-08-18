# PostgreSQL: technical design (Phase 1 — критическое состояние)

Статус: **дизайн, кода миграции ещё нет**. Цель — зафиксировать план перед тем, как трогать
`stats.json`, который сегодня является единственным persistence-слоем бота (см. CLAUDE.md →
"Stats persistence").

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
на таблицу, весь Phase 1 разворачивается одним прогоном backfill-скрипта.

**Осознанные отступления от 1:1 копии JSON** (каждое — низкий риск, объясняю почему):

- **`subscriptions` становится append-only историей**, а не одной перезаписываемой записью.
  Сегодня покупка нового тарифа УНИЧТОЖАЕТ запись о предыдущем — это не баг, который нужно чинить
  прямо сейчас, но раз всё равно переносим в реляционную модель, дешевле сразу писать `INSERT`
  вместо `UPDATE ... WHERE user_id=?`. Действующая подписка — это `SELECT ... WHERE user_id=?
  ORDER BY purchased_at DESC LIMIT 1`, что для приложения ведёт себя ИДЕНТИЧНО сегодняшнему
  `stats["subscriptions"][uid]`. Если это кажется лишним расширением скоупа — можно откатить до
  чистого upsert-по-`user_id`, это отдельная строка в DDL, скажи и поменяю.
- **`manual_access_granted` / `manual_anatomy_demo_granted` / `temporary_access` /
  `histology_temp_access` схлопываются в одну таблицу `manual_grants(user_id, grant_type,
  expires_at)`.** Сегодня это четыре независимые структуры ради одного и того же факта ("у юзера
  X есть право Y до момента Z или навсегда") — везде разный код чтения (`in list` vs `dict.get`),
  везде отдельно нужно было не забыть завести ключ в `load_stats()`. Одна таблица с
  `PRIMARY KEY(user_id, grant_type)` и `expires_at NULL = навсегда`.
- **`referral_monthly` не переносится как структура** — сегодня это отдельный бегущий счётчик,
  который надо не забыть инкрементировать синхронно с `referrals` (источник настоящего бага,
  если где-то забыть). В Postgres это просто `COUNT(*) FROM referrals WHERE referrer_id=? AND
  created_at >= <начало месяца, МСК>` — тот же результат, но без риска рассинхронизации, потому
  что нет второго счётчика, который нужно поддерживать в ногу с первым.
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
    UNIQUE (user_id, purchased_at)  -- естественный ключ для идемпотентного backfill'а (§4/§5) —
                                     -- две РЕАЛЬНЫЕ покупки не могут совпасть до микросекунды
);
CREATE INDEX idx_subscriptions_current ON subscriptions (user_id, purchased_at DESC);
-- "действующая подписка юзера" = первая строка при таком индексе -> дешёвый point-lookup.

-- ==================== payments ====================
CREATE TABLE payments (
    charge_id   TEXT PRIMARY KEY,     -- Stars: telegram_payment_charge_id;
                                       -- рубли: синтетический 'rub_{user_id}_{tier}_{ts}' (см. §6)
    user_id     BIGINT NOT NULL REFERENCES users(user_id),
    kind        TEXT NOT NULL CHECK (kind IN
                    ('sub_stars', 'sub_rubles', 'sub_rubles_manual', 'donation_stars', 'donation_rubles')),
    amount      INT NOT NULL,
    tier        INT,                  -- NULL для донатов
    payload     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- UNIQUE уже даёт PRIMARY KEY. Это прямая замена stats["processed_payment_charge_ids"] —
-- ключевая гарантия идемпотентности платежей из твоего пункта 1.

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
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_referrals_referrer ON referrals (referrer_id, created_at);
-- get_referral_count()        = COUNT(*) WHERE referrer_id=?
-- get_referral_count_this_month() = COUNT(*) WHERE referrer_id=? AND created_at >= <МСК-начало месяца>
-- get_referral_link "кто меня пригласил"  = SELECT referrer_id WHERE referred_id=?

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
  запись в новой append-only истории). Дальнейшие покупки уже в Postgres добавляют новые строки.
- `payments`: `processed_payment_charge_ids` уже имеет `user_id`/`stars`/`payload`/`at` — прямое
  отображение полей, `kind` реконструируется из `payload` (`sub_stars_` → `sub_stars`, иначе
  `donation_stars`, рублёвые оплаты в этот dict сегодня не попадают вообще — см. §6 про их
  отдельный путь).
- `manual_grants`: четыре JSON-структуры → до четырёх строк на юзера, `expires_at` только у
  `temp_access`/`histology_temp`.

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

Про рублёвые платежи отдельно: у Stars есть `telegram_payment_charge_id` от Telegram, у ручного/
one-tap рублёвого подтверждения (`cb_admin_confirm_sub`) — нет внешнего ID вообще, сегодня
дедуп там держится на 10-минутном окне по времени + tier + user_id внутри одного процесса. В
`payments.charge_id` для этого пути пишем синтетический `f"rub_{user_id}_{tier}_{int(purchased_at)}"`,
сформированный ВНУТРИ той же транзакции, что и сама выдача (см. §8) — двойное нажатие кнопки
двумя админами одновременно теперь ловится настоящим `UNIQUE`-конфликтом на уровне БД, а не
эвристикой "искать похожую запись за последние 10 минут" в Python.

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

---

## Что дальше

Это чистый дизайн — прежде чем писать код (`scripts/migrate_stats_to_postgres.py`, слой доступа к
Postgres, флаг `PERSISTENCE_BACKEND`, замену `save_stats()`-вызовов в шести доменах), нужен твой
go/no-go по трём отмеченным "осознанным отступлениям" в §2 (append-only `subscriptions`,
схлопывание `manual_grants` в одну таблицу, замена `referral_monthly`-счётчика на `COUNT(*)`) —
если все три ок, начинаю с DDL-миграции и `scripts/migrate_stats_to_postgres.py`, самих продовых
данных ещё не касаясь (только читаю `stats.json`, ничего в него не пишу назад).
