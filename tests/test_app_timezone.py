# -*- coding: utf-8 -*-
"""APP_TIMEZONE (Europe/Moscow, fixed UTC+3 — Russia has had no DST since 2014) is the single
source of truth for every recurring daily/monthly period boundary and for the subscription
cutoff deadlines in services/access.py. Before this, those all used date.today()/datetime.now(),
i.e. the CONTAINER's local time (UTC on Railway) — meaning "a new day"/"a new month" flipped up
to 3 hours later than it actually did in Moscow, and format_subscription_expiry() could even show
the wrong calendar DAY for an expiry timestamp computed near a day boundary."""
from datetime import datetime, timedelta
from _bootstrap import tb
from services import access

# ---- 1. APP_TIMEZONE is a fixed UTC+3 offset, not a system/zoneinfo-dependent timezone ----
assert tb.APP_TIMEZONE.utcoffset(None) == timedelta(hours=3)
print("1. APP_TIMEZONE is a fixed UTC+3 offset: OK")

# ---- 2. local_now()/local_today() are anchored to that offset, independent of system tz ----
now_msk = tb.local_now()
assert now_msk.utcoffset() == timedelta(hours=3)
assert tb.local_today() == now_msk.date()
print("2. local_now()/local_today() are MSK-anchored: OK")

# ---- 3. every period-key helper derives from the same local_today()/local_now(), so they can
# never disagree with each other about what day/month/hour it currently is ----
assert access._current_referral_month_key() == tb.local_today().strftime("%Y-%m")
assert tb._current_ai_month_key() == tb.local_today().strftime("%Y-%m")
assert tb._current_day_key() == tb.local_today().isoformat()
assert tb._current_hour_key() == tb.local_now().strftime("%Y-%m-%d-%H")
print("3. referral/AI-monthly/cost-breaker period keys all agree with local_today()/local_now(): OK")

# ---- 4. subscription cutoff constants are MSK midnight of their calendar date, not container-
# local midnight — verified against the same _msk_deadline() helper they're built from ----
assert access.OCT_2026_CUTOFF == access._msk_deadline(2026, 10, 1)
assert access.OCT_2026_CUTOFF == datetime(2026, 10, 1, tzinfo=tb.APP_TIMEZONE).timestamp()
print("4. subscription cutoff constants are anchored to MSK midnight: OK")

# ---- 5. format_subscription_expiry() must show the MSK calendar day, not the UTC one — pick a
# timestamp that is 23:30 UTC on day N (= 02:30 MSK on day N+1, the exact boundary case that
# used to render one day early under container-local UTC formatting) ----
ts_2330_utc_aug_10 = datetime(2026, 8, 10, 23, 30, tzinfo=tb.timezone.utc).timestamp()
text = tb.format_subscription_expiry(ts_2330_utc_aug_10)
assert "11.08.2026" in text, f"expected the MSK day (11.08.2026), got: {text}"
assert "10.08.2026" not in text
print("5. format_subscription_expiry() renders the MSK calendar day at a UTC day boundary: OK")

# ---- 6. format_subscription_expiry(None) is untouched by any of this ----
assert tb.format_subscription_expiry(None) == "навсегда"
print("6. format_subscription_expiry(None) still means forever: OK")

print("ALL APP_TIMEZONE TESTS PASSED")
