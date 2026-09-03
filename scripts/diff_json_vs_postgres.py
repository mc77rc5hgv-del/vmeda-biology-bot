#!/usr/bin/env python3
"""Read-only sanity check: does Postgres agree with stats.json for the 6 Phase-1 domains?

See docs/postgres_migration_design.md §5. Run manually/on a cron during the whole dual-write
period (see CLAUDE.md-to-be once dual-write ships) — this script NEVER writes to stats.json or to
Postgres, it only SELECTs from both and reports where they disagree. The design doc's own
cutover criterion is "0 diffs on this report for N days running under real load" (N=3 for
payments/subscriptions, N=7 for referrals/ai_usage) — this script is what produces that number.

DELIBERATELY NOT part of the bot or its requirements.txt, same "run manually" pattern as
scripts/migrate_stats_to_postgres.py. Same dependency:

    pip install -r scripts/postgres_migration.requirements.txt

Usage:
    export DATABASE_URL=postgresql://user:pass@host:5432/dbname
    python3 scripts/diff_json_vs_postgres.py                     # diff against ./stats.json
    python3 scripts/diff_json_vs_postgres.py --stats-file /path/to/stats.json
    python3 scripts/diff_json_vs_postgres.py --only referrals    # one domain only
    python3 scripts/diff_json_vs_postgres.py --exit-nonzero-on-diff   # for cron/CI: exit 1 if any diff found
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

import psycopg2
import psycopg2.extras

MSK = timezone(timedelta(hours=3))  # см. telegram_bot.APP_TIMEZONE -- тот же захардкоженный
                                     # фиксированный офсет, тот же резон (Россия без DST с 2014).


def local_today_msk() -> date:
    return datetime.now(MSK).date()


def current_month_key_msk() -> str:
    return datetime.now(MSK).strftime("%Y-%m")


def load_stats(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class Diff:
    __slots__ = ("domain", "user_id", "field", "json_value", "db_value")

    def __init__(self, domain, user_id, field, json_value, db_value):
        self.domain = domain
        self.user_id = user_id
        self.field = field
        self.json_value = json_value
        self.db_value = db_value

    def __str__(self) -> str:
        return (
            f"[{self.domain}] user_id={self.user_id} field={self.field}: "
            f"json={self.json_value!r} db={self.db_value!r}"
        )


def diff_users(cur, stats: dict) -> list[Diff]:
    diffs = []
    user_names = stats.get("user_names", {})
    user_username = stats.get("user_username", {})
    usernames_reverse = stats.get("usernames", {})
    json_uids = {int(u) for u in stats.get("total_users", [])}

    cur.execute("SELECT user_id, username, full_name FROM users")
    db_rows = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
    db_uids = set(db_rows)

    for uid in sorted(json_uids - db_uids):
        diffs.append(Diff("users", uid, "presence", "in JSON", "MISSING in DB"))
    for uid in sorted(db_uids - json_uids):
        diffs.append(Diff("users", uid, "presence", "not in total_users", "present in DB"))

    for uid in sorted(json_uids & db_uids):
        uid_str = str(uid)
        expected_username = user_username.get(uid_str)
        if expected_username is not None and usernames_reverse.get(expected_username) != uid:
            expected_username = None  # тот же tiebreaker, что migrate_users() -- см. миграцию
        db_username, db_full_name = db_rows[uid]
        if expected_username != db_username:
            diffs.append(Diff("users", uid, "username", expected_username, db_username))
        expected_name = user_names.get(uid_str)
        if expected_name != db_full_name:
            diffs.append(Diff("users", uid, "full_name", expected_name, db_full_name))
    return diffs


def diff_subscriptions(cur, stats: dict) -> list[Diff]:
    """Сравнивает ТЕКУЩУЮ (последнюю по purchased_at) подписку в Postgres с тем, что лежит в
    stats["subscriptions"][uid] -- см. design doc §2: "действующая подписка" в append-only модели
    это SELECT ... ORDER BY purchased_at DESC LIMIT 1, что должно вести себя идентично сегодняшнему
    stats["subscriptions"][uid] сразу после backfill'а (до первой новой покупки в Postgres)."""
    diffs = []
    subs = stats.get("subscriptions", {})
    json_uids = {int(u) for u in subs}

    cur.execute("""
        SELECT DISTINCT ON (user_id) user_id, tier, restricted_subject, expires, histology_access,
               histology_until, anatomy, biology_download, cheat_sheets, subscription_version,
               method, price
        FROM subscriptions
        ORDER BY user_id, purchased_at DESC
    """)
    db_rows = {row[0]: row[1:] for row in cur.fetchall()}
    db_uids = set(db_rows)

    for uid in sorted(json_uids - db_uids):
        diffs.append(Diff("subscriptions", uid, "presence", "in JSON", "MISSING in DB"))
    for uid in sorted(db_uids - json_uids):
        diffs.append(Diff("subscriptions", uid, "presence", "no current sub in JSON", "present in DB"))

    for uid in sorted(json_uids & db_uids):
        sub = subs[str(uid)]
        (tier, restricted_subject, expires, histology_access, histology_until, anatomy,
         biology_download, cheat_sheets, subscription_version, method, price) = db_rows[uid]
        checks = [
            ("tier", sub.get("tier"), tier),
            ("restricted_subject", sub.get("restricted_subject"), restricted_subject),
            ("histology_access", bool(sub.get("histology_access", False)), histology_access),
            ("anatomy", bool(sub.get("anatomy", False)), anatomy),
            ("biology_download", bool(sub.get("biology_download", False)), biology_download),
            ("cheat_sheets", bool(sub.get("cheat_sheets", False)), cheat_sheets),
            ("subscription_version", sub.get("subscription_version", 1), subscription_version),
            ("method", sub.get("method", "rubles_manual"), method),
            ("price", sub.get("price", 0), price),
        ]
        for field, json_value, db_value in checks:
            if json_value != db_value:
                diffs.append(Diff("subscriptions", uid, field, json_value, db_value))
    return diffs


def diff_payments(cur, stats: dict) -> list[Diff]:
    """Только Stars -- у RUB нет исторического журнала в JSON (см. design doc §4), сравнивать не
    с чем. Проверяет ровно то же множество ключей, что migrate_payments() переносит."""
    diffs = []
    charges = stats.get("processed_payment_charge_ids", {})
    json_charge_ids = set(charges)

    cur.execute("SELECT charge_id FROM payments WHERE kind IN ('sub_stars', 'donation_stars')")
    db_charge_ids = {row[0] for row in cur.fetchall()}

    for charge_id in sorted(json_charge_ids - db_charge_ids):
        diffs.append(Diff("payments", charges[charge_id].get("user_id"), "presence", charge_id, "MISSING in DB"))
    for charge_id in sorted(db_charge_ids - json_charge_ids):
        diffs.append(Diff("payments", None, "presence", "not in processed_payment_charge_ids", charge_id))
    return diffs


def diff_manual_grants(cur, stats: dict) -> list[Diff]:
    diffs = []
    expected: dict[tuple[int, str], float | None] = {}
    for uid in stats.get("manual_access_granted", []):
        expected[(int(uid), "full_access")] = None
    for uid in stats.get("manual_anatomy_demo_granted", []):
        expected[(int(uid), "anatomy_demo")] = None
    for uid_str, expiry in stats.get("temporary_access", {}).items():
        expected[(int(uid_str), "temp_access")] = expiry
    for uid_str, expiry in stats.get("histology_temp_access", {}).items():
        expected[(int(uid_str), "histology_temp")] = expiry

    cur.execute("SELECT user_id, grant_type, expires_at FROM manual_grants")
    actual = {(row[0], row[1]): row[2] for row in cur.fetchall()}

    for key in sorted(set(expected) - set(actual)):
        diffs.append(Diff("manual_grants", key[0], key[1], "in JSON", "MISSING in DB"))
    for key in sorted(set(actual) - set(expected)):
        diffs.append(Diff("manual_grants", key[0], key[1], "not in JSON", "present in DB"))
    return diffs


def diff_referrals(cur, stats: dict) -> list[Diff]:
    """Две проверки: (1) лифтайм-счётчик get_referral_count() = len(referrals[referrer]) должен
    совпасть с COUNT(*) в Postgres -- это НЕ зависит от того, известны ли даты; (2) переходная
    месячная формула (design doc §2) должна дать то же число, что сегодняшний
    get_referral_count_this_month() на чтении из JSON."""
    diffs = []
    referrals = stats.get("referrals", {})
    referral_monthly = stats.get("referral_monthly", {})
    current_month = current_month_key_msk()

    cur.execute("SELECT referrer_id, count(*) FROM referrals GROUP BY referrer_id")
    lifetime_counts_db = dict(cur.fetchall())

    all_referrers = {int(u) for u in referrals} | set(lifetime_counts_db)
    for referrer_id in sorted(all_referrers):
        json_count = len(referrals.get(str(referrer_id), []))
        db_count = lifetime_counts_db.get(referrer_id, 0)
        if json_count != db_count:
            diffs.append(Diff("referrals", referrer_id, "lifetime_count", json_count, db_count))

    cur.execute("SELECT user_id, month, count FROM referral_monthly_legacy_credit")
    legacy_credit = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
    cur.execute(
        "SELECT referrer_id, count(*) FROM referrals WHERE created_at >= %s GROUP BY referrer_id",
        (datetime.now(MSK).replace(day=1, hour=0, minute=0, second=0, microsecond=0),),
    )
    this_month_counts_db = dict(cur.fetchall())

    for referrer_id in sorted(all_referrers):
        entry = referral_monthly.get(str(referrer_id)) or {}
        json_month_count = entry.get("count", 0) if entry.get("month") == current_month else 0

        credit_month, credit_count = legacy_credit.get(referrer_id, (None, 0))
        db_month_count = (credit_count if credit_month == current_month else 0) + this_month_counts_db.get(referrer_id, 0)

        if json_month_count != db_month_count:
            diffs.append(Diff("referrals", referrer_id, "this_month_count", json_month_count, db_month_count))
    return diffs


def diff_ai_usage(cur, stats: dict) -> list[Diff]:
    diffs = []
    today = local_today_msk()
    ai_usage = stats.get("ai_usage", {})

    cur.execute("SELECT user_id, count FROM ai_usage_daily WHERE day = %s", (today,))
    db_today = dict(cur.fetchall())

    json_today = {}
    for uid_str, entry in ai_usage.items():
        if entry.get("date") == today.isoformat():
            json_today[int(uid_str)] = entry.get("count", 0)

    for uid in sorted(set(json_today) | set(db_today)):
        json_count = json_today.get(uid, 0)
        db_count = db_today.get(uid, 0)
        if json_count != db_count:
            diffs.append(Diff("ai_usage_daily", uid, "count_today", json_count, db_count))
    return diffs


DOMAIN_CHECKERS = {
    "users": diff_users,
    "subscriptions": diff_subscriptions,
    "payments": diff_payments,
    "manual_grants": diff_manual_grants,
    "referrals": diff_referrals,
    "ai_usage_daily": diff_ai_usage,
}
ORDER = ["users", "subscriptions", "payments", "manual_grants", "referrals", "ai_usage_daily"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stats-file", default="stats.json")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--only", choices=ORDER)
    parser.add_argument("--exit-nonzero-on-diff", action="store_true",
                         help="exit 1 if any diff was found (для крона/CI)")
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
    conn.set_session(readonly=True)  # эта команда никогда ничего не пишет -- на всякий случай явно на уровне драйвера
    total_diffs = 0
    try:
        with conn.cursor() as cur:
            for domain in domains:
                diffs = DOMAIN_CHECKERS[domain](cur, stats)
                if diffs:
                    print(f"=== {domain}: {len(diffs)} расхождений ===")
                    for d in diffs:
                        print(f"  {d}")
                else:
                    print(f"=== {domain}: 0 расхождений ===")
                total_diffs += len(diffs)
    finally:
        conn.close()

    print()
    if total_diffs == 0:
        print("ИТОГО: 0 расхождений по всем доменам.")
    else:
        print(f"ИТОГО: {total_diffs} расхождений — cutover (design doc §7) откладывается.")

    if args.exit_nonzero_on_diff and total_diffs > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
