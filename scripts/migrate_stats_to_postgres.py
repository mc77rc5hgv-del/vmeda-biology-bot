#!/usr/bin/env python3
"""One-shot backfill: stats.json -> PostgreSQL (Phase 1 critical-state tables only).

See docs/postgres_migration_design.md for the full design. This script is READ-ONLY against
stats.json — it never writes back to it — and is idempotent: every insert goes through
ON CONFLICT, so re-running after fixing a bug in this script (or after new activity landed in
stats.json) never double-counts or crashes on a row that's already there.

DELIBERATELY NOT part of the bot (telegram_bot.py / requirements.txt) or the deployed process on
Railway -- same "run manually" pattern as scripts/ai_benchmark.py. Install its own dependency
first, in whatever environment you run it from:

    pip install -r scripts/postgres_migration.requirements.txt

Usage:
    export DATABASE_URL=postgresql://user:pass@host:5432/dbname
    python3 scripts/migrate_stats_to_postgres.py                  # backfill from ./stats.json
    python3 scripts/migrate_stats_to_postgres.py --stats-file /path/to/stats.json
    python3 scripts/migrate_stats_to_postgres.py --dry-run        # real DB round-trip, then ROLLBACK
    python3 scripts/migrate_stats_to_postgres.py --only referrals # backfill one domain only

Applies db/migrations/0001_phase1_schema.sql itself (idempotent CREATE TABLE IF NOT EXISTS) before
backfilling, so a fresh empty database needs no separate manual step.
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timezone

import psycopg2
import psycopg2.extras

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
SCHEMA_PATH = os.path.join(REPO_ROOT, "db", "migrations", "0001_phase1_schema.sql")

DOMAINS = ("users", "subscriptions", "payments", "manual_grants", "referrals", "ai_usage_daily")


def _ts(value) -> datetime | None:
    """unix-timestamp (float/int) -> aware datetime, None/0/falsy -> None."""
    if not value:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc)


def load_stats(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def apply_schema(conn) -> None:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        sql = f.read()
    with conn.cursor() as cur:
        cur.execute(sql)


def _collect_all_referenced_uids(stats: dict) -> set[int]:
    """Каждая другая Phase-1-таблица имеет FK NOT NULL на users(user_id) -- если где-то в JSON
    есть uid, который почему-то не попал в total_users/user_names/user_username (например,
    админ вручную выдал подписку человеку, который ни разу не жал /start), backfill той таблицы
    упадёт на FK violation. Собираем uid'ы из ВСЕХ доменов заранее, чтобы users содержал каждого
    возможного заказчика FK, даже если про него больше ничего не известно (username/full_name
    останутся NULL)."""
    uids: set[int] = set(int(u) for u in stats.get("total_users", []))
    uids |= {int(u) for u in stats.get("user_names", {})}
    uids |= {int(u) for u in stats.get("user_username", {})}
    uids |= {int(u) for u in stats.get("subscriptions", {})}
    uids |= {int(u) for u in stats.get("manual_access_granted", [])}
    uids |= {int(u) for u in stats.get("manual_anatomy_demo_granted", [])}
    uids |= {int(u) for u in stats.get("temporary_access", {})}
    uids |= {int(u) for u in stats.get("histology_temp_access", {})}
    uids |= {int(u) for u in stats.get("referral_warnings", {})}
    uids |= {int(u) for u in stats.get("ai_usage", {})}
    for referrer_str, referred_list in stats.get("referrals", {}).items():
        uids.add(int(referrer_str))
        uids |= {int(r) for r in referred_list}
    for entry in stats.get("processed_payment_charge_ids", {}).values():
        if entry.get("user_id") is not None:
            uids.add(int(entry["user_id"]))
    return uids


def migrate_users(conn, stats: dict) -> int:
    user_names = stats.get("user_names", {})
    user_username = stats.get("user_username", {})
    usernames_reverse = stats.get("usernames", {})  # {username: uid} -- authoritative current mapping

    uids = _collect_all_referenced_uids(stats)
    rows = []
    for uid in sorted(uids):
        uid_str = str(uid)
        username = user_username.get(uid_str)
        # stats["user_username"] (forward, {uid: username}) can go stale if a Telegram username
        # changes hands: user A drops @foo, user B later takes it -- stats["usernames"] (reverse,
        # {username: uid}) gets overwritten to B, but A's forward entry may still say "foo" until
        # A is next seen. Trust the reverse index as the tiebreaker: only keep a forward username
        # if the reverse index still agrees it belongs to this uid, otherwise drop it to NULL
        # rather than risk a spurious UNIQUE(username) collision or crediting A's row with B's name.
        if username is not None and usernames_reverse.get(username) != uid:
            username = None
        rows.append((uid, username, user_names.get(uid_str)))

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO users (user_id, username, full_name) VALUES %s
               ON CONFLICT (user_id) DO UPDATE
               SET username = EXCLUDED.username, full_name = EXCLUDED.full_name""",
            rows,
        )
    return len(rows)


def migrate_subscriptions(conn, stats: dict) -> int:
    """В JSON только ПОСЛЕДНЯЯ подписка на юзера -- переносим как ОДНУ строку (первая запись в
    новой append-only истории), source_legacy_key = 'legacy_subscription_{user_id}'. Живые
    покупки уже в Postgres добавляют новые строки с source_legacy_key = NULL -- см.
    db/migrations/0001_phase1_schema.sql за тем, почему ON CONFLICT именно на этой колонке,
    а не на (user_id, purchased_at) (была реальная дыра при повторном прогоне)."""
    subs = stats.get("subscriptions", {})
    rows = []
    for uid_str, sub in subs.items():
        ai_monthly = sub.get("ai_used_monthly") or {}
        rows.append((
            int(uid_str),
            sub["tier"],
            sub.get("restricted_subject"),
            _ts(sub.get("expires")),
            bool(sub.get("histology_access", False)),
            _ts(sub.get("histology_until")),
            bool(sub.get("anatomy", False)),
            bool(sub.get("biology_download", False)),
            bool(sub.get("cheat_sheets", False)),
            sub.get("subscription_version", 1),
            _ts(sub.get("purchased_at")) or datetime.now(timezone.utc),
            sub.get("method", "rubles_manual"),
            sub.get("price", 0),
            sub.get("ai_used_period", 0),
            ai_monthly.get("month"),
            ai_monthly.get("count", 0),
            f"legacy_subscription_{uid_str}",
        ))
    if not rows:
        return 0
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO subscriptions
               (user_id, tier, restricted_subject, expires, histology_access, histology_until,
                anatomy, biology_download, cheat_sheets, subscription_version, purchased_at,
                method, price, ai_used_period, ai_used_monthly_month, ai_used_monthly_count,
                source_legacy_key)
               VALUES %s
               ON CONFLICT (source_legacy_key) DO NOTHING""",
            rows,
        )
    return len(rows)


def migrate_payments(conn, stats: dict) -> int:
    """Только Stars-платежи -- рубли сегодня не проходят через successful_payment вообще (см.
    design doc §4), исторических событий для них в stats.json просто нет; текущее состояние
    рублёвой подписки уже переносится через migrate_subscriptions()."""
    charges = stats.get("processed_payment_charge_ids", {})
    rows = []
    for charge_id, entry in charges.items():
        payload = entry.get("payload") or ""
        if payload.startswith("sub_stars_"):
            kind = "sub_stars"
            parts = payload.split("_")
            tier = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        else:
            kind = "donation_stars"
            tier = None
        rows.append((
            charge_id,
            int(entry["user_id"]),
            kind,
            entry.get("stars", 0),
            tier,
            payload,
            _ts(entry.get("at")) or datetime.now(timezone.utc),
        ))
    if not rows:
        return 0
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO payments (charge_id, user_id, kind, amount, tier, payload, created_at)
               VALUES %s
               ON CONFLICT (charge_id) DO NOTHING""",
            rows,
        )
    return len(rows)


def migrate_manual_grants(conn, stats: dict) -> int:
    rows = []
    for uid in stats.get("manual_access_granted", []):
        rows.append((int(uid), "full_access", None))
    for uid in stats.get("manual_anatomy_demo_granted", []):
        rows.append((int(uid), "anatomy_demo", None))
    for uid_str, expiry in stats.get("temporary_access", {}).items():
        rows.append((int(uid_str), "temp_access", _ts(expiry)))
    for uid_str, expiry in stats.get("histology_temp_access", {}).items():
        rows.append((int(uid_str), "histology_temp", _ts(expiry)))
    if not rows:
        return 0
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO manual_grants (user_id, grant_type, expires_at) VALUES %s
               ON CONFLICT (user_id, grant_type) DO UPDATE SET expires_at = EXCLUDED.expires_at""",
            rows,
        )
    return len(rows)


def migrate_referrals(conn, stats: dict) -> int:
    """stats["referrals"][referrer] -- плоский список referred_id, БЕЗ таймстампов на каждый
    отдельный реферал. Backfilled-строки получают created_at = NULL ("дата неизвестна") --
    round 1 этого скрипта пыталось угадать, какие рефералы "относятся к текущему месяцу" по
    хвосту списка + stats["referral_monthly"], но это лишний и хрупкий шаг: правильное решение —
    перенести stats["referral_monthly"][referrer] = {month, count} КАК ЕСТЬ, одним снимком, в
    отдельную referral_monthly_legacy_credit, и оставить формулу месячного счёта переходной (см.
    design doc §2 и комментарий над этой таблицей в db/migrations/0001_phase1_schema.sql):

        legacy_credit.count (если legacy_credit.month = текущий МСК-месяц, иначе 0)
        + COUNT(*) FROM referrals WHERE referrer_id = ? AND created_at >= <начало текущего месяца>

    NULL created_at в это сравнение никогда не попадает -- исторические рефералы не задваивают и
    не обнуляют ничей месячный счёт при cutover, а после смены календарного месяца снимок сам
    перестаёт что-либо давать (без отдельной миграции/крона)."""
    referrals = stats.get("referrals", {})
    referral_monthly = stats.get("referral_monthly", {})

    rows = []
    for referrer_str, referred_list in referrals.items():
        referrer_id = int(referrer_str)
        for referred_id in referred_list:
            rows.append((int(referred_id), referrer_id, None))
    if rows:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO referrals (referred_id, referrer_id, created_at) VALUES %s
                   ON CONFLICT (referred_id) DO NOTHING""",
                rows,
            )

    legacy_credit_rows = []
    for uid_str, entry in referral_monthly.items():
        month = entry.get("month")
        if not month:
            continue
        legacy_credit_rows.append((int(uid_str), month, entry.get("count", 0)))
    if legacy_credit_rows:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO referral_monthly_legacy_credit (user_id, month, count) VALUES %s
                   ON CONFLICT (user_id) DO UPDATE
                   SET month = EXCLUDED.month, count = EXCLUDED.count""",
                legacy_credit_rows,
            )

    warning_rows = []
    for uid_str, entry in stats.get("referral_warnings", {}).items():
        warning_rows.append((int(uid_str), entry.get("count", 0), _ts(entry.get("last_warn_at"))))
    if warning_rows:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO referral_warnings (user_id, count, last_warn_at) VALUES %s
                   ON CONFLICT (user_id) DO UPDATE
                   SET count = EXCLUDED.count, last_warn_at = EXCLUDED.last_warn_at""",
                warning_rows,
            )
    return len(rows)


def migrate_ai_usage_daily(conn, stats: dict) -> int:
    rows = []
    for uid_str, entry in stats.get("ai_usage", {}).items():
        day_str = entry.get("date")
        if not day_str:
            continue
        rows.append((int(uid_str), date.fromisoformat(day_str), entry.get("count", 0)))
    if not rows:
        return 0
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO ai_usage_daily (user_id, day, count) VALUES %s
               ON CONFLICT (user_id, day) DO UPDATE SET count = EXCLUDED.count""",
            rows,
        )
    return len(rows)


MIGRATORS = {
    "users": migrate_users,
    "subscriptions": migrate_subscriptions,
    "payments": migrate_payments,
    "manual_grants": migrate_manual_grants,
    "referrals": migrate_referrals,
    "ai_usage_daily": migrate_ai_usage_daily,
}
# users должен идти первым (все остальные таблицы FK на него); внутри остального порядок
# произволен -- независимые друг от друга таблицы.
ORDER = ["users", "subscriptions", "payments", "manual_grants", "referrals", "ai_usage_daily"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stats-file", default="stats.json", help="путь к stats.json (по умолчанию ./stats.json)")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"),
                         help="строка подключения Postgres (по умолчанию из $DATABASE_URL)")
    parser.add_argument("--only", choices=ORDER,
                         help="перенести только один домен (для отладки) — все, кроме users, "
                              "имеют FK NOT NULL на users(user_id), так что --only <домен> "
                              "падает с ForeignKeyViolation, если users ещё не забэкфиллен "
                              "полным прогоном без --only")
    parser.add_argument("--dry-run", action="store_true",
                         help="выполнить всё внутри транзакции и откатить в конце — реальные "
                              "constraint-проверки БД срабатывают, но ничего не сохраняется")
    args = parser.parse_args()

    if not args.database_url:
        print("ошибка: не задан --database-url и не задан $DATABASE_URL", file=sys.stderr)
        return 1
    if not os.path.exists(args.stats_file):
        print(f"ошибка: файл не найден: {args.stats_file}", file=sys.stderr)
        return 1

    stats = load_stats(args.stats_file)
    domains = [args.only] if args.only else ORDER

    conn = psycopg2.connect(args.database_url)
    try:
        apply_schema(conn)
        counts = {}
        for domain in domains:
            counts[domain] = MIGRATORS[domain](conn, stats)
        if args.dry_run:
            conn.rollback()
            print("-- DRY RUN: транзакция откачена, в БД ничего не сохранено --")
        else:
            conn.commit()
        for domain in domains:
            print(f"{domain}: {counts[domain]} строк")
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
