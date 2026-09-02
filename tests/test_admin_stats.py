# -*- coding: utf-8 -*-
import asyncio, random, copy, os
from _bootstrap import tb

ADMIN_ID = next(iter(tb.ADMIN_IDS))

class FakeUser:
    def __init__(self, uid):
        self.id = uid

class FakeMsg:
    def __init__(self):
        self.edits = []
        self.documents = []
    async def edit_text(self, text, **kwargs):
        self.edits.append(text)
        return self
    async def delete(self):
        pass
    async def answer(self, text, **kwargs):
        self.edits.append(text)
        return self
    async def answer_document(self, document, **kwargs):
        self.documents.append((document, kwargs.get("caption")))
        return self

class FakeCB:
    def __init__(self, data, uid=ADMIN_ID):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
    async def answer(self, text=None, show_alert=False):
        pass

def fresh_uid():
    return str(random.randint(10_000_000, 99_999_999))

async def main():
    # user A: blocked (count >= threshold, no free access) -> should count
    uid_a = fresh_uid()
    tb.stats["referral_warnings"][uid_a] = {"count": tb.REFERRAL_WARNING_THRESHOLD, "last_warn_at": 0}
    tb.stats["referrals"].pop(uid_a, None)

    # user B: blocked count reached, but later got 2 referrals -> should NOT count (has free access now)
    uid_b = fresh_uid()
    tb.stats["referral_warnings"][uid_b] = {"count": tb.REFERRAL_WARNING_THRESHOLD, "last_warn_at": 0}
    tb.stats["referrals"][uid_b] = ["x", "y"]

    # user C: only 1 warning so far, not blocked -> should NOT count
    uid_c = fresh_uid()
    tb.stats["referral_warnings"][uid_c] = {"count": 1, "last_warn_at": 0}
    tb.stats["referrals"].pop(uid_c, None)

    cb = FakeCB("admin_stats")
    await tb.cb_admin_stats(cb)
    text = cb.message.edits[0]
    print(text)

    # exact count check: recompute independently
    expected = sum(
        1 for u, e in tb.stats["referral_warnings"].items()
        if e.get("count", 0) >= tb.REFERRAL_WARNING_THRESHOLD and not tb.has_free_access(int(u))
    )
    import re
    m = re.search(r"Исчерпали бесплатные заходы без рефералов: <b>(\d+)</b>", text)
    assert m, "stat line not found"
    shown = int(m.group(1))
    assert shown == expected, f"shown={shown} expected={expected}"
    assert uid_a in tb.stats["referral_warnings"], "stats must not be reset"
    assert tb.stats["referral_warnings"][uid_a]["count"] == tb.REFERRAL_WARNING_THRESHOLD, "count must not be reset"
    print(f"metric correct ({shown}), stats untouched: OK")

    # non-admin blocked
    cb2 = FakeCB("admin_stats", uid=123456789)
    await tb.cb_admin_stats(cb2)
    assert not cb2.message.edits
    print("non-admin blocked: OK")

    # "below threshold" metric: counts total_users with < REFERRAL_FULL_ACCESS_THRESHOLD referrals
    uid_0ref = int(fresh_uid())
    uid_1ref = int(fresh_uid())
    uid_2ref = int(fresh_uid())
    uid_5ref = int(fresh_uid())
    tb.stats["total_users"].update([uid_0ref, uid_1ref, uid_2ref, uid_5ref])
    tb.stats["referrals"].pop(str(uid_0ref), None)
    tb.stats["referrals"][str(uid_1ref)] = ["x"]
    tb.stats["referrals"][str(uid_2ref)] = ["x", "y"]
    tb.stats["referrals"][str(uid_5ref)] = ["a", "b", "c", "d", "e"]

    cb3 = FakeCB("admin_stats")
    await tb.cb_admin_stats(cb3)
    text3 = cb3.message.edits[0]
    expected_below = sum(
        1 for uid in tb.stats["total_users"] if tb.get_referral_count(uid) < tb.REFERRAL_FULL_ACCESS_THRESHOLD
    )
    m2 = re.search(rf"Меньше {tb.REFERRAL_FULL_ACCESS_THRESHOLD} рефералов: <b>(\d+)</b>", text3)
    assert m2, "below-threshold stat line not found"
    assert int(m2.group(1)) == expected_below
    assert expected_below >= 2, "sanity: our two synthetic 0/1-referral users must be counted"
    print(f"below-threshold metric correct ({expected_below}): OK")

    # "referral free access this month" counter: distinct from the lifetime below-threshold metric —
    # only counts users who hit the monthly threshold IN THE CURRENT MONTH (stats["referral_monthly"]).
    current_month = tb.local_today().strftime("%Y-%m")
    uid_unlocked_now = fresh_uid()
    uid_unlocked_last_month = fresh_uid()
    uid_not_enough_this_month = fresh_uid()
    tb.stats["referral_monthly"][uid_unlocked_now] = {
        "month": current_month, "count": tb.REFERRAL_FULL_ACCESS_THRESHOLD,
    }
    tb.stats["referral_monthly"][uid_unlocked_last_month] = {
        "month": "2000-01", "count": tb.REFERRAL_FULL_ACCESS_THRESHOLD + 5,
    }
    tb.stats["referral_monthly"][uid_not_enough_this_month] = {
        "month": current_month, "count": tb.REFERRAL_FULL_ACCESS_THRESHOLD - 1,
    }

    cb3b = FakeCB("admin_stats")
    await tb.cb_admin_stats(cb3b)
    text3b = cb3b.message.edits[0]
    expected_unlocked = sum(
        1 for e in tb.stats["referral_monthly"].values()
        if e.get("month") == current_month and e.get("count", 0) >= tb.REFERRAL_FULL_ACCESS_THRESHOLD
    )
    m2b = re.search(
        rf"Доступ по {tb.REFERRAL_FULL_ACCESS_THRESHOLD} рефералам в этом месяце: <b>(\d+)</b>", text3b
    )
    assert m2b, "referral-free-access-this-month stat line not found"
    assert int(m2b.group(1)) == expected_unlocked == tb.get_referral_free_access_user_count()
    assert uid_unlocked_now in tb.stats["referral_monthly"], "sanity: our synthetic user must still be counted"
    print(f"referral-free-access-this-month metric correct ({expected_unlocked}), excludes stale months: OK")

    for uid in (uid_unlocked_now, uid_unlocked_last_month, uid_not_enough_this_month):
        tb.stats["referral_monthly"].pop(uid, None)

    # subscriptions + payments block: grant a stars tier-2 and a rubles tier-3, check totals reflected
    uid_sub_stars = fresh_uid()
    uid_sub_rubles = fresh_uid()
    tb.stats["subscriptions"].pop(uid_sub_stars, None)
    tb.stats["subscriptions"].pop(uid_sub_rubles, None)
    tb.grant_subscription(int(uid_sub_stars), 2, "stars", 239)
    tb.grant_subscription(int(uid_sub_rubles), 3, "rubles", 899)

    donations_stars_before = tb.stats.get("donations_stars_total", 0)
    donations_stars_count_before = tb.stats.get("donations_stars_count", 0)
    tb.stats["donations_stars_total"] = donations_stars_before + 50
    tb.stats["donations_stars_count"] = donations_stars_count_before + 1
    uid_donor_rubles = fresh_uid()
    tb.stats["donor_rubles"][uid_donor_rubles] = tb.stats["donor_rubles"].get(uid_donor_rubles, 0) + 300

    cb3 = FakeCB("admin_stats")
    await tb.cb_admin_stats(cb3)
    text3 = cb3.message.edits[0]
    assert "💎 <b>Подписки</b>" in text3
    assert "💰 <b>Платежи</b>" in text3
    for cfg in tb.SUBSCRIPTION_TIERS.values():
        assert cfg["short"] in text3
    import re as _re
    m_total = _re.search(r"Всего куплено: <b>(\d+)</b>, активных сейчас: <b>(\d+)</b>", text3)
    assert m_total, "subscriptions summary line not found"
    assert int(m_total.group(1)) == len(tb.stats["subscriptions"])
    m_stars_rev = _re.search(r"⭐ Подписки звёздами: <b>(\d+)</b>", text3)
    m_rubles_rev = _re.search(r"💵 Подписки рублями: <b>(\d+)</b>₽", text3)
    assert m_stars_rev and int(m_stars_rev.group(1)) >= 239
    assert m_rubles_rev and int(m_rubles_rev.group(1)) >= 899
    m_don_stars = _re.search(r"⭐ Донаты звёздами: <b>(\d+)</b> \((\d+) платежей\)", text3)
    assert m_don_stars and int(m_don_stars.group(1)) == tb.stats["donations_stars_total"]
    m_don_rub = _re.search(r"💵 Донаты рублями: <b>(\d+)</b>₽ \((\d+) чел\.\)", text3)
    assert m_don_rub and int(m_don_rub.group(1)) == sum(tb.stats["donor_rubles"].values())

    tb.stats["subscriptions"].pop(uid_sub_stars, None)
    tb.stats["subscriptions"].pop(uid_sub_rubles, None)
    tb.stats["donor_rubles"].pop(uid_donor_rubles, None)
    print("subscriptions + payments stats block present and correct: OK")

    # rubles_manual (admin-granted-for-free) subscriptions must NOT count toward payment revenue,
    # even though they still count toward "Всего куплено" / active-by-tier totals
    uid_sub_manual = fresh_uid()
    tb.stats["subscriptions"].pop(uid_sub_manual, None)
    tb.grant_subscription(int(uid_sub_manual), 6, "rubles_manual", 239)
    cb4 = FakeCB("admin_stats")
    await tb.cb_admin_stats(cb4)
    text4 = cb4.message.edits[0]
    m_total2 = _re.search(r"Всего куплено: <b>(\d+)</b>", text4)
    assert m_total2 and int(m_total2.group(1)) == len(tb.stats["subscriptions"]), \
        "manually-granted subscriptions still count toward the total"
    m_rubles_rev2 = _re.search(r"💵 Подписки рублями: <b>(\d+)</b>₽", text4)
    assert m_rubles_rev2 and int(m_rubles_rev2.group(1)) == 0, \
        "rubles_manual grants (free comps) must not be counted as payment revenue"
    tb.stats["subscriptions"].pop(uid_sub_manual, None)
    print("manually-granted (free) subscriptions excluded from payment revenue: OK")

    # stats.json export: admin gets the current file as a document, nothing is modified/reset
    tb.save_stats()
    tb._stats_executor.submit(lambda: None).result()  # barrier: wait for the queued write (single worker, FIFO) to land
    referral_warnings_before = copy.deepcopy(tb.stats["referral_warnings"])

    cb_export = FakeCB("admin_export_stats")
    await tb.cb_admin_export_stats(cb_export)
    assert cb_export.message.documents, "expected a document to be sent"
    doc, caption = cb_export.message.documents[0]
    assert doc.path == tb.STATS_FILE
    assert caption and "stats.json" in caption
    assert f"@{tb.BOT_USERNAME}" in caption
    assert os.path.exists(tb.STATS_FILE)
    assert tb.stats["referral_warnings"] == referral_warnings_before, "export must not mutate stats"
    print("admin export sends current stats.json, stats untouched: OK")

    cb_export2 = FakeCB("admin_export_stats", uid=123456789)
    await tb.cb_admin_export_stats(cb_export2)
    assert not cb_export2.message.documents
    print("export non-admin blocked: OK")

    # /stats command: admin-only (info-disclosure guard)
    class FakeStatsMsg:
        def __init__(self, uid):
            self.from_user = FakeUser(uid)
            self.sent = []
        async def answer(self, text, **kwargs):
            self.sent.append(text)
            return self

    msg_admin = FakeStatsMsg(ADMIN_ID)
    await tb.cmd_stats(msg_admin)
    assert msg_admin.sent, "admin should get a /stats reply"
    assert "Статистика бота" in msg_admin.sent[0]
    print("/stats admin gets stats: OK")

    msg_non_admin = FakeStatsMsg(123456789)
    await tb.cmd_stats(msg_non_admin)
    assert not msg_non_admin.sent, "/stats must not leak metrics to non-admins"
    print("/stats non-admin blocked: OK")

    # AI cost circuit breaker: the stats screen shows the tripped block + reset button only while
    # tripped, and admin_ai_breaker_reset actually clears it (see CLAUDE.md/AI cost-safety section)
    orig_windows = copy.deepcopy(tb.stats["ai_cost_windows"])
    tb.stats["ai_cost_windows"] = {
        "hour_key": "x", "hour_cost_usd": 7.5, "day_key": "y", "day_cost_usd": 40.0,
        "breaker_tripped": True, "breaker_alerted": True,
    }
    cb_tripped = FakeCB("admin_stats")
    await tb.cb_admin_stats(cb_tripped)
    tripped_text = cb_tripped.message.edits[-1]
    assert "AI-автовыключатель сработал" in tripped_text
    tripped_kb = tb.get_admin_stats_keyboard(True)
    tripped_kb_data = [b.callback_data for row in tripped_kb.inline_keyboard for b in row]
    assert "admin_ai_breaker_reset" in tripped_kb_data
    print("admin stats screen shows the tripped AI circuit breaker + reset button: OK")

    cb_reset = FakeCB("admin_ai_breaker_reset")
    await tb.cb_admin_ai_breaker_reset(cb_reset)
    assert not tb.ai_circuit_breaker_tripped(), "cb_admin_ai_breaker_reset must clear the breaker"
    reset_text = cb_reset.message.edits[-1]
    assert "AI-автовыключатель сработал" not in reset_text, "the screen must re-render without the tripped block"
    print("cb_admin_ai_breaker_reset clears the breaker and re-renders the stats screen: OK")

    cb_reset_non_admin = FakeCB("admin_ai_breaker_reset", uid=123456789)
    tb.stats["ai_cost_windows"]["breaker_tripped"] = True
    await tb.cb_admin_ai_breaker_reset(cb_reset_non_admin)
    assert tb.ai_circuit_breaker_tripped(), "a non-admin must not be able to reset the breaker"
    print("cb_admin_ai_breaker_reset non-admin blocked: OK")

    normal_kb = tb.get_admin_stats_keyboard(False)
    normal_kb_data = [b.callback_data for row in normal_kb.inline_keyboard for b in row]
    assert "admin_ai_breaker_reset" not in normal_kb_data, "the reset button must not appear when not tripped"
    tb.stats["ai_cost_windows"] = orig_windows
    print("get_admin_stats_keyboard omits the reset button when the breaker isn't tripped: OK")

    print("ALL ADMIN STATS TESTS PASSED")

asyncio.run(main())
