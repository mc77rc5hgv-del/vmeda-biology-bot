# -*- coding: utf-8 -*-
"""register_referral() and the monthly-recurring referral access requirement (see CLAUDE.md/
services/access.py: REFERRAL_FULL_ACCESS_THRESHOLD used to be a one-time-forever unlock, now it's
re-earned every calendar month via stats["referral_monthly"]). test_referral_gate.py covers the
gate predicates themselves (has_free_access/get_referral_status_text) by poking stats directly;
this file covers the actual PRODUCTION code path that populates those stats — register_referral()
— plus the month-rollover behavior end to end."""
import asyncio
from _bootstrap import tb

REFERRER = 444555666
REF_A = 700000001
REF_B = 700000002
REF_C = 700000003


async def main():
    referrer_str = str(REFERRER)
    for ref in (REF_A, REF_B, REF_C):
        tb.stats["referred_by"].pop(str(ref), None)
    tb.stats["referrals"].pop(referrer_str, None)
    tb.stats["referral_monthly"].pop(referrer_str, None)

    sent = []
    orig_send_message = tb.bot.send_message
    async def fake_send_message(chat_id, text, **kwargs):
        sent.append((chat_id, text))
    tb.bot.send_message = fake_send_message

    # ---- 1. a genuinely new referral increments BOTH the lifetime list and this month's counter ----
    await tb.register_referral(REFERRER, REF_A)
    assert tb.get_referral_count(REFERRER) == 1, "lifetime count must reflect the new referral"
    assert tb.get_referral_count_this_month(REFERRER) == 1, "this month's count must reflect it too"
    assert tb.stats["referral_monthly"][referrer_str]["month"] == tb._current_referral_month_key()
    assert sent, "referrer must get a notification"
    assert "В этом месяце" in sent[-1][1] and "1" in sent[-1][1]
    assert "Всего приглашено за всё время" in sent[-1][1]
    print("1. register_referral increments both the lifetime list and this month's counter: OK")

    # ---- 2. a second distinct referral this month brings the user to the threshold (2) -> the
    # notification says the monthly quota is now met ----
    await tb.register_referral(REFERRER, REF_B)
    assert tb.get_referral_count(REFERRER) == 2
    assert tb.get_referral_count_this_month(REFERRER) == 2
    assert tb.has_free_access(REFERRER), "reaching the threshold this month must grant free access"
    assert "норма выполнена" in sent[-1][1], "notification must say the monthly quota is now met"
    print("2. reaching REFERRAL_FULL_ACCESS_THRESHOLD this month grants free access: OK")

    # ---- 3. re-registering the SAME referred user again is a no-op for both counters (existing
    # anti-fraud dedup via stats["referred_by"], unaffected by the new monthly counter) ----
    before_lifetime = tb.get_referral_count(REFERRER)
    before_month = tb.get_referral_count_this_month(REFERRER)
    sent.clear()
    await tb.register_referral(REFERRER, REF_A)
    assert tb.get_referral_count(REFERRER) == before_lifetime, "re-registering the same referred user must not double-count lifetime"
    assert tb.get_referral_count_this_month(REFERRER) == before_month, "...or the monthly counter"
    assert not sent, "no duplicate notification for an already-registered referred user"
    print("3. re-registering the same referred user is a no-op for both counters: OK")

    # ---- 4. a referrer can't refer themselves ----
    sent.clear()
    await tb.register_referral(REFERRER, REFERRER)
    assert tb.get_referral_count(REFERRER) == before_lifetime
    assert not sent
    print("4. self-referral is rejected: OK")

    # ---- 5. MONTH ROLLOVER: referrals earned in a past month don't count toward the current
    # month's requirement, even though the lifetime list still has them — access must close again
    # until new referrals are brought in the new month ----
    tb.stats["referral_monthly"][referrer_str] = {"month": "2001-01", "count": 2}
    assert tb.get_referral_count(REFERRER) == 2, "lifetime count is unaffected by the month rollover"
    assert tb.get_referral_count_this_month(REFERRER) == 0, "a past month's count must not carry over"
    assert not tb.has_free_access(REFERRER), "access must close again once the month rolls over"
    print("5. a past month's referrals don't carry over — access closes until new ones arrive: OK")

    # ---- 6. bringing ONE new referral in the (now current) month starts a fresh counter at 1,
    # not accumulating on top of the stale past-month value ----
    sent.clear()
    await tb.register_referral(REFERRER, REF_C)
    assert tb.get_referral_count(REFERRER) == 3, "lifetime count keeps accumulating across months"
    assert tb.get_referral_count_this_month(REFERRER) == 1, "the new month's counter starts fresh, not 2+1"
    assert not tb.has_free_access(REFERRER), "one referral this month is still below the threshold of 2"
    print("6. a new month's counter starts fresh instead of accumulating on a stale value: OK")

    tb.bot.send_message = orig_send_message
    for ref in (REF_A, REF_B, REF_C):
        tb.stats["referred_by"].pop(str(ref), None)
    tb.stats["referrals"].pop(referrer_str, None)
    tb.stats["referral_monthly"].pop(referrer_str, None)

    print("ALL REFERRAL MONTHLY TESTS PASSED")


asyncio.run(main())
