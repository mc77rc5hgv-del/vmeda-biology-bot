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
    assert tb.BOT_USERNAME in caption
    assert os.path.exists(tb.STATS_FILE)
    assert tb.stats["referral_warnings"] == referral_warnings_before, "export must not mutate stats"
    print("admin export sends current stats.json, stats untouched: OK")

    cb_export2 = FakeCB("admin_export_stats", uid=123456789)
    await tb.cb_admin_export_stats(cb_export2)
    assert not cb_export2.message.documents
    print("export non-admin blocked: OK")

    print("ALL ADMIN STATS TESTS PASSED")

asyncio.run(main())
