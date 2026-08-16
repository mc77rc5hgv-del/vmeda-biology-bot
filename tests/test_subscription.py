# -*- coding: utf-8 -*-
import asyncio, random, time
from _bootstrap import tb
from html.parser import HTMLParser

ADMIN_ID = next(iter(tb.ADMIN_IDS))

class C(HTMLParser):
    def __init__(self):
        super().__init__(); self.stack=[]; self.problems=[]
    def handle_starttag(self, tag, attrs): self.stack.append(tag)
    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag: self.problems.append(tag)
        else: self.stack.pop()

def check_html(text):
    c = C(); c.feed(text)
    assert not c.stack and not c.problems, (text[:300], c.stack, c.problems)
    assert len(text) <= 4096, len(text)

class FakeUser:
    def __init__(self, uid, full_name="Тест Юзер", username=None):
        self.id = uid
        self.full_name = full_name
        self.username = username

class FakeMsg:
    def __init__(self, from_user=None):
        self.edits = []
        self.answers = []
        self.from_user = from_user
        self.successful_payment = None
        self.text = None
        self.html_text = None
    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self
    async def delete(self):
        pass
    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs.get("reply_markup")))
        return self

class FakeCB:
    def __init__(self, data, uid=ADMIN_ID):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
        self._answers = []
    async def answer(self, text=None, show_alert=False):
        self._answers.append((text, show_alert))

def kb_texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row]

def kb_data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]

class FakeSuccessfulPayment:
    def __init__(self, total_amount, invoice_payload):
        self.total_amount = total_amount
        self.invoice_payload = invoice_payload

# Тарифы 1-11 (старая линейка) — ВСЕ сняты с продажи после введения новой линейки 20-28, но их
# условия (цена/срок/права) не меняются задним числом, и записи, уже выданные по ним, продолжают
# резолвиться ровно как раньше. Тарифы 20-28 — новая линейка (см. services/access.py).
RETIRED_TIERS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11}
ACTIVE_TIERS = {20, 21, 22, 23, 24, 25, 26, 27, 28}

async def main():
    non_admin = random.randint(10_000_000, 99_999_999)
    tb.stats["subscriptions"].pop(str(non_admin), None)

    # Network-safety net: cb_buy_sub_rubles(_subj) now also pings admins via bot.send_message —
    # install a no-op everywhere by default so any call site we don't explicitly mock for
    # inspection never hits the real network; sections that need to inspect messages swap in
    # a recording mock and restore this same no-op afterwards (never the real bot method).
    async def _noop_send_message(chat_id, text, **kwargs):
        pass
    tb.bot.send_message = _noop_send_message

    # 1. Tier data integrity: 11 legacy tiers (all retired), 9 new tiers (all active/on sale)
    assert set(tb.SUBSCRIPTION_TIERS.keys()) == RETIRED_TIERS | ACTIVE_TIERS
    assert set(tb.ACTIVE_SUBSCRIPTION_TIERS.keys()) == ACTIVE_TIERS
    for t in RETIRED_TIERS:
        assert tb.SUBSCRIPTION_TIERS[t].get("retired") is True
    for t in ACTIVE_TIERS:
        assert not tb.SUBSCRIPTION_TIERS[t].get("retired")
    for cfg in tb.SUBSCRIPTION_TIERS.values():
        assert cfg["price_rub"] > 0 and cfg["price_stars"] > 0
        assert len(cfg["benefits"]) >= 2
    print("tier data integrity (retired/active split): OK")

    # 1b. Legacy tier configs (1-11) are byte-for-byte unchanged from before the new lineup —
    # this is the single most important regression guard in this file: nothing here may drift.
    legacy_expected_prices = {1: 89, 6: 239, 7: 389, 8: 749, 9: 1119, 10: 3899, 11: 1999}
    for t, price in legacy_expected_prices.items():
        assert tb.SUBSCRIPTION_TIERS[t]["price_rub"] == price, t
    assert tb.SUBSCRIPTION_TIERS[5]["subject_choice_required"] is True
    for t in (1, 6, 7, 8, 9, 10, 11):
        assert not tb.SUBSCRIPTION_TIERS[t].get("subject_choice_required")
    for t in (7, 8, 9, 10, 11):
        assert tb.SUBSCRIPTION_TIERS[t]["anatomy"] is True
    for t in (1, 6):
        assert not tb.SUBSCRIPTION_TIERS[t]["anatomy"]
    for t in (9, 10, 11):
        assert tb.SUBSCRIPTION_TIERS[t]["biology_download"] is True
        assert tb.SUBSCRIPTION_TIERS[t]["cheat_sheets"] is True
    for t in (1, 6, 7, 8):
        assert not tb.SUBSCRIPTION_TIERS[t]["biology_download"]
    assert tb.SUBSCRIPTION_TIERS[1]["histology_until_rule"] == tb.JULY_END_2026
    assert tb.SUBSCRIPTION_TIERS[6]["expires_at"] == tb.OCT_2026_CUTOFF
    assert tb.SUBSCRIPTION_TIERS[7]["expires_at"] == tb.NOV_END_2026_CUTOFF
    assert tb.SUBSCRIPTION_TIERS[8]["expires_at"] == tb.FEB_2027_CUTOFF
    assert tb.SUBSCRIPTION_TIERS[9]["expires_at"] == tb.SECOND_YEAR_END_2027
    assert tb.SUBSCRIPTION_TIERS[10]["duration_days"] == 6 * 365
    assert tb.SUBSCRIPTION_TIERS[11]["duration_days"] == 2 * 365
    # legacy tiers carry no subscription_version / ai_limit_type fields at all — new-lineup-only concepts
    for t in RETIRED_TIERS:
        assert "subscription_version" not in tb.SUBSCRIPTION_TIERS[t]
        assert "ai_limit_type" not in tb.SUBSCRIPTION_TIERS[t]
    print("legacy tier (1-11) configs are byte-for-byte unchanged: OK")

    # 1c. New tier (20-28) configs match the agreed price list exactly
    expected_new = {
        20: {"price_rub": 99, "price_stars": 99, "duration_days": 7, "expires_at": None,
             "subject_choice_required": True, "anatomy": False, "biology_download": False,
             "cheat_sheets": False, "ai_limit_type": "period", "ai_limit": 30},
        21: {"price_rub": 129, "price_stars": 129, "duration_days": 30, "expires_at": None,
             "subject_choice_required": False, "anatomy": False, "biology_download": False,
             "cheat_sheets": False, "ai_limit_type": "period", "ai_limit": 110},
        22: {"price_rub": 249, "price_stars": 249, "duration_days": None, "expires_at": tb.NOV_1_2026_CUTOFF,
             "subject_choice_required": False, "anatomy": False, "biology_download": False,
             "cheat_sheets": False, "ai_limit_type": "period", "ai_limit": 225},
        23: {"price_rub": 299, "price_stars": 299, "duration_days": None, "expires_at": tb.JAN_1_2027_CUTOFF,
             "subject_choice_required": False, "anatomy": False, "biology_download": False,
             "cheat_sheets": False, "ai_limit_type": "period", "ai_limit": 225},
        24: {"price_rub": 599, "price_stars": 599, "duration_days": None, "expires_at": tb.MAR_1_2027_CUTOFF,
             "subject_choice_required": False, "anatomy": True, "biology_download": False,
             "cheat_sheets": False, "ai_limit_type": "period", "ai_limit": 450},
        25: {"price_rub": 849, "price_stars": 849, "duration_days": None, "expires_at": tb.FIRST_YEAR_END_2027,
             "subject_choice_required": False, "anatomy": False, "biology_download": False,
             "cheat_sheets": False, "ai_limit_type": "monthly", "ai_limit": 150},
        26: {"price_rub": 1290, "price_stars": 1290, "duration_days": None, "expires_at": tb.SECOND_YEAR_END_2027,
             "subject_choice_required": False, "anatomy": True, "biology_download": True,
             "cheat_sheets": True, "ai_limit_type": "monthly", "ai_limit": 225},
        27: {"price_rub": 1690, "price_stars": 1690, "duration_days": 2 * 365, "expires_at": None,
             "subject_choice_required": False, "anatomy": True, "biology_download": True,
             "cheat_sheets": True, "ai_limit_type": "monthly", "ai_limit": 375},
        28: {"price_rub": 2990, "price_stars": 2990, "duration_days": 6 * 365, "expires_at": None,
             "subject_choice_required": False, "anatomy": True, "biology_download": True,
             "cheat_sheets": True, "ai_limit_type": "monthly", "ai_limit": 375},
    }
    for t, expected in expected_new.items():
        cfg = tb.SUBSCRIPTION_TIERS[t]
        for k, v in expected.items():
            assert cfg[k] == v, (t, k, cfg.get(k), v)
        assert cfg["subscription_version"] == 2, t
    # id 20 is the only new tier requiring a subject choice
    for t in ACTIVE_TIERS - {20}:
        assert not tb.SUBSCRIPTION_TIERS[t].get("subject_choice_required"), t
    # 26/27/28 never used a HOT badge (per spec, tier 28 must not be marked HOT)
    assert "HOT" not in (tb.SUBSCRIPTION_TIERS[28].get("badge") or "")
    print("new tier (20-28) configs match the agreed price list exactly: OK")

    # 2. No subscription -> no access to any subject, no anatomy/histology
    assert not tb.has_active_subscription(non_admin)
    assert not tb.has_free_access(non_admin)
    for subject in ("biology", "physics", "chemistry"):
        assert not tb.has_subject_access(non_admin, subject)
    assert not tb.anatomy_access_ok(non_admin)
    assert not tb.histology_access_ok(non_admin)
    print("no subscription -> no access: OK")

    # 3. Tier 5 (legacy, 3 days, one subject) restricts access to exactly the chosen subject —
    # grant_subscription() itself doesn't care whether a tier is retired, only the shop UI does,
    # so this legacy behavior must keep working exactly as it did before it was retired.
    tb.grant_subscription(non_admin, 5, "stars", 49, "physics")
    assert tb.has_active_subscription(non_admin)
    assert tb.has_free_access(non_admin), "has_free_access is a blanket check, used for non-subject contexts"
    assert tb.has_subject_access(non_admin, "physics")
    assert not tb.has_subject_access(non_admin, "biology")
    assert not tb.has_subject_access(non_admin, "chemistry")
    assert not tb.anatomy_access_ok(non_admin) and not tb.histology_access_ok(non_admin)
    sub = tb.get_subscription(non_admin)
    assert sub["tier"] == 5 and sub["restricted_subject"] == "physics"
    assert "только к Физике" in tb.get_subscription_scope_label(sub)
    expected_expiry = time.time() + 3 * 86400
    assert abs(sub["expires"] - expected_expiry) < 5
    print("legacy tier 5 (3 days, 1 subject) restricts access to the chosen subject only: OK")

    # 3b. The referral-gate middleware's subject classifier agrees with this restriction
    assert tb.get_gated_subject("menu_physics") == "physics"
    assert tb.get_gated_subject("menu_biology") == "biology"
    assert tb.get_gated_subject("chemistry_labs") == "chemistry"
    assert tb.get_gated_subject("anatomy_menu") is None
    print("get_gated_subject classifies gated callbacks by subject: OK")

    # 4. Legacy tier 1 (89₽, month) -> all 3 subjects, time-boxed Histology preview, no Anatomy.
    # JULY_END_2026 (1 Aug 2026) is a frozen historical cutoff for a tier no longer sold — it must
    # NEVER be advanced just because real calendar time has passed it (that would retroactively
    # reshape what tier-1 buyers were actually promised, see CLAUDE.md). So rather than asserting
    # histology_access_ok(non_admin) directly (true only while the real clock is before that date,
    # which stops holding after 1 Aug 2026), test the on/off mechanism itself with explicit
    # before/after timestamps, and separately assert whichever branch actually holds right now —
    # this stays correct and passing on both sides of the cutoff, indefinitely.
    tb.grant_subscription(non_admin, 1, "stars", 89)
    for subject in ("biology", "physics", "chemistry"):
        assert tb.has_subject_access(non_admin, subject)
    assert not tb.anatomy_access_ok(non_admin)
    sub = tb.get_subscription(non_admin)
    assert sub["restricted_subject"] is None
    assert sub["histology_until"] == tb.JULY_END_2026
    assert "Анатомии" not in tb.get_subscription_scope_label(sub)
    assert tb._sub_has_histology({"histology_access": True, "histology_until": time.time() + 86400}), \
        "still within the preview window -> Histology must be granted"
    assert not tb._sub_has_histology({"histology_access": True, "histology_until": time.time() - 86400}), \
        "past the preview window -> Histology must be denied"
    if time.time() < tb.JULY_END_2026:
        assert tb.histology_access_ok(non_admin), "preview window still open as of the real clock"
        assert "Гистологии" in tb.get_subscription_scope_label(sub)
    else:
        assert not tb.histology_access_ok(non_admin), "preview window (1 Aug 2026) has closed"
        assert "Гистологии" not in tb.get_subscription_scope_label(sub)
    print("legacy tier 1 grants all 3 gated subjects + time-boxed Histology preview mechanism verified: OK")

    # 5. Legacy tier 6 (239₽, until Oct 2026) -> fixed calendar expiry, not a relative duration
    tb.grant_subscription(non_admin, 6, "rubles", 239)
    sub = tb.get_subscription(non_admin)
    assert sub["expires"] == tb.OCT_2026_CUTOFF
    assert tb.histology_access_ok(non_admin)
    assert not tb.anatomy_access_ok(non_admin)
    assert not tb.biology_tickets_download_ok(non_admin)
    print("legacy tier 6 grants Histology on a fixed October 2026 cutoff, no Anatomy/biology-download: OK")

    # 6. Legacy tier 7 (389₽) adds early Anatomy access on top of the 5-subject bundle
    tb.grant_subscription(non_admin, 7, "rubles", 389)
    assert tb.anatomy_access_ok(non_admin)
    assert tb.histology_access_ok(non_admin)
    assert not tb.biology_tickets_download_ok(non_admin)
    print("legacy tier 7 adds Anatomy access: OK")

    # 7. Legacy tier 9 (1119₽) additionally unlocks biology-ticket downloads + cheat sheets flag
    tb.grant_subscription(non_admin, 9, "rubles", 1119)
    assert tb.anatomy_access_ok(non_admin) and tb.histology_access_ok(non_admin)
    assert tb.biology_tickets_download_ok(non_admin)
    assert tb.get_subscription(non_admin)["cheat_sheets"] is True
    assert tb.get_subscription(non_admin)["expires"] == tb.SECOND_YEAR_END_2027
    print("legacy tier 9 unlocks biology downloads + cheat_sheets, expires at end of 2nd course: OK")

    # 8. Legacy tier 10 (3899₽, 6 years) -> relative duration (not a fixed calendar cutoff), everything on
    tb.grant_subscription(non_admin, 10, "stars", 3899)
    sub = tb.get_subscription(non_admin)
    expected_expiry = time.time() + 6 * 365 * 86400
    assert abs(sub["expires"] - expected_expiry) < 5
    assert tb.anatomy_access_ok(non_admin) and tb.biology_tickets_download_ok(non_admin)
    assert "ко всем разделам бота" in tb.get_subscription_scope_label(sub)
    tb.stats["subscriptions"].pop(str(non_admin), None)
    print("legacy tier 10 (6 years, everything) grants full scope with a relative 6-year expiry: OK")

    # 8b. Regression: a hand-written "gift" legacy tier 10 record (the shape a manually-granted/
    # comped subscription actually has in stats["subscriptions"] — not produced via
    # grant_subscription(), unlike section 8 above) keeps working exactly as promised after the
    # new 20-28 lineup was introduced, and the new tier 28 ("Вся академия", the closest modern
    # equivalent) has zero effect on it whatsoever.
    gift_uid = random.randint(10_000_000, 99_999_999)
    tb.stats["subscriptions"][str(gift_uid)] = {
        "tier": 10,
        "expires": time.time() + 6 * 365 * 86400,
        "anatomy": True,
        "histology_access": True,
        "histology_until": None,
        "biology_download": True,
        "cheat_sheets": True,
        "purchased_at": time.time(),
        "method": "rubles_manual",
        "price": 0,
    }
    assert tb.has_active_subscription(gift_uid)
    assert tb.anatomy_access_ok(gift_uid)
    assert tb.histology_access_ok(gift_uid)
    assert tb.biology_tickets_download_ok(gift_uid)
    gift_sub_before = dict(tb.get_subscription(gift_uid))
    # tier 28 existing at all (config lookups, ACTIVE_SUBSCRIPTION_TIERS membership, etc.) must not
    # retroactively touch this gift record in any way
    assert 28 in tb.SUBSCRIPTION_TIERS and 28 in tb.ACTIVE_SUBSCRIPTION_TIERS
    assert tb.get_subscription(gift_uid) == gift_sub_before, "tier 28's existence must not alter the gift record"
    assert tb.get_subscription(gift_uid)["tier"] == 10, "still resolves against the frozen legacy tier 10 entry"
    tb.stats["subscriptions"].pop(str(gift_uid), None)
    print("hand-written gift legacy tier 10 subscription keeps working, unaffected by new tier 28: OK")

    # 9. Expired subscription -> no access
    tb.stats["subscriptions"][str(non_admin)] = {
        "tier": 1, "restricted_subject": None, "expires": time.time() - 10,
        "histology_access": True, "histology_until": None, "anatomy": False,
        "biology_download": False, "cheat_sheets": False,
        "purchased_at": time.time() - 1000, "method": "stars", "price": 89,
    }
    assert not tb.has_active_subscription(non_admin)
    assert not tb.has_free_access(non_admin)
    tb.stats["subscriptions"].pop(str(non_admin), None)
    print("expired subscription -> no access: OK")

    # 10. Legacy subscriptions (old scope/early_histology fields, no new fields at all — not even
    # subscription_version) still resolve correctly through the pure-fallback path
    tb.stats["subscriptions"][str(non_admin)] = {
        "tier": 3, "scope": "all", "expires": time.time() + 86400,
        "purchased_at": time.time(), "method": "rubles", "price": 899,
    }
    assert tb.anatomy_access_ok(non_admin)
    assert tb.histology_access_ok(non_admin)
    assert tb.biology_tickets_download_ok(non_admin)
    assert "ко всем разделам бота" in tb.get_subscription_scope_label(tb.get_subscription(non_admin))
    assert tb.get_subscription(non_admin).get("subscription_version", 1) == 1, "absent field reads as version 1"
    tb.stats["subscriptions"].pop(str(non_admin), None)
    print("legacy (pre-migration) subscriptions still resolve via fallback fields: OK")

    # 11. format_subscription_expiry unchanged
    assert tb.format_subscription_expiry(None) == "навсегда"
    future_ts = time.time() + 86400
    assert "до " in tb.format_subscription_expiry(future_ts)
    print("format_subscription_expiry: OK")

    # ==================== NEW-LINEUP AI QUOTAS (subscription_version 2 + legacy bonus) ====================
    # 11b. New tier with a "period" AI plan (total pool for the whole subscription lifetime)
    ai_uid = random.randint(10_000_000, 99_999_999)
    tb.stats["subscriptions"].pop(str(ai_uid), None)
    tb.grant_subscription(ai_uid, 21, "stars", 129)  # 110 AI requests, period
    assert tb.get_subscription(ai_uid)["subscription_version"] == 2
    assert tb.sub_ai_requests_left(ai_uid) == 110
    assert tb.ai_requests_left(ai_uid) == 110
    assert tb.ai_quota_ok(ai_uid)
    tb.increment_ai_usage(ai_uid)
    tb.increment_ai_usage(ai_uid)
    assert tb.sub_ai_requests_left(ai_uid) == 108
    assert tb.get_subscription(ai_uid)["ai_used_period"] == 2
    assert str(ai_uid) not in tb.stats["ai_usage"], "period AI usage must not touch the free daily counter"
    label = tb.get_ai_quota_label(ai_uid)
    assert "108/110" in label and "срок подписки" in label
    tb.stats["subscriptions"].pop(str(ai_uid), None)
    print("new tier 'period' AI plan: independent pool, decrements correctly: OK")

    # 11c. New tier with a "monthly" AI plan resets on a new calendar month
    ai_uid2 = random.randint(10_000_000, 99_999_999)
    tb.stats["subscriptions"].pop(str(ai_uid2), None)
    tb.grant_subscription(ai_uid2, 26, "stars", 1290)  # 225 AI requests, monthly
    assert tb.sub_ai_requests_left(ai_uid2) == 225
    tb.increment_ai_usage(ai_uid2)
    assert tb.sub_ai_requests_left(ai_uid2) == 224
    sub2 = tb.get_subscription(ai_uid2)
    assert sub2["ai_used_monthly"]["month"] == tb._current_ai_month_key()
    # simulate a stale month key (e.g. left over from a previous month) -> usage resets to 0
    sub2["ai_used_monthly"] = {"month": "2001-01", "count": 999}
    assert tb.sub_ai_requests_left(ai_uid2) == 225, "usage from a different month must not carry over"
    label2 = tb.get_ai_quota_label(ai_uid2)
    assert "225/225" in label2 and "в месяц" in label2
    tb.stats["subscriptions"].pop(str(ai_uid2), None)
    print("new tier 'monthly' AI plan resets across calendar months: OK")

    # 11d. Legacy paid subscription (subscription_version absent) gets a flat monthly AI bonus —
    # entirely independent of, and without touching, its stored content-access fields
    ai_uid3 = random.randint(10_000_000, 99_999_999)
    tb.stats["subscriptions"][str(ai_uid3)] = {
        "tier": 9, "restricted_subject": None, "expires": time.time() + 86400,
        "histology_access": True, "histology_until": None, "anatomy": True,
        "biology_download": True, "cheat_sheets": True,
        "purchased_at": time.time(), "method": "rubles", "price": 1119,
    }
    assert tb.sub_ai_requests_left(ai_uid3) == tb.LEGACY_PAID_AI_MONTHLY_BONUS
    before_sub = dict(tb.get_subscription(ai_uid3))
    tb.increment_ai_usage(ai_uid3)
    after_sub = tb.get_subscription(ai_uid3)
    assert after_sub["anatomy"] is True and after_sub["histology_access"] is True
    assert after_sub["biology_download"] is True and after_sub["cheat_sheets"] is True
    assert after_sub["tier"] == 9 and after_sub["expires"] == before_sub["expires"], "content/expiry fields untouched"
    assert tb.sub_ai_requests_left(ai_uid3) == tb.LEGACY_PAID_AI_MONTHLY_BONUS - 1
    tb.stats["subscriptions"].pop(str(ai_uid3), None)
    print("legacy paid subscription gets a flat AI bonus without altering its stored content rights: OK")

    # 11e. No subscription / expired subscription -> falls back to the ordinary free daily limit,
    # completely unaffected by the new subscription AI-plan layer (regression, matches test_ai_mvp.py)
    assert tb.sub_ai_requests_left(non_admin) is None
    assert tb.ai_requests_left(non_admin) == tb.AI_FREE_DAILY_LIMIT
    print("no active subscription -> ordinary free daily AI limit applies, unaffected: OK")

    # 12. Subscription menu ("📦 Все тарифы") only lists the 9 active tiers, never the 11 retired ones
    menu_text = tb.get_subscription_menu_text(non_admin)
    check_html(menu_text)
    for cfg in tb.ACTIVE_SUBSCRIPTION_TIERS.values():
        assert cfg["title"] in menu_text
        assert str(cfg["price_rub"]) in menu_text
    menu_kb = tb.get_subscription_menu_keyboard()
    texts = kb_texts(menu_kb)
    assert len(texts) == len(ACTIVE_TIERS) + 1  # + back button
    for cfg in tb.ACTIVE_SUBSCRIPTION_TIERS.values():
        assert any(cfg["short"] in t for t in texts)
    # retired tiers must not leak into the "all tiers" screen at all
    for t in RETIRED_TIERS:
        cfg = tb.SUBSCRIPTION_TIERS[t]
        assert cfg["title"] not in menu_text
        assert not any(f"sub_tier:{t}" == d for d in kb_data(menu_kb))
    print("'all tiers' screen lists only the 9 new active tiers, retired tiers excluded: OK")

    # 12b. Every active tier's detail screen renders valid HTML
    for tier_id in ACTIVE_TIERS:
        tier_text = tb.get_sub_tier_text(tier_id)
        check_html(tier_text)
    print("every active tier's detail screen renders: OK")

    # 13. Per-tier screens: subject-choice tier (new tier 20) shows subject buttons, not payment buttons directly
    tier20_text = tb.get_sub_tier_text(20)
    check_html(tier20_text)
    assert "выбери предмет" in tier20_text
    tier20_kb = tb.get_sub_tier_keyboard(20)
    tier20_data = kb_data(tier20_kb)
    assert "sub_subject:20:biology" in tier20_data
    assert "sub_subject:20:physics" in tier20_data
    assert "sub_subject:20:chemistry" in tier20_data
    assert not any(d.startswith("buy_sub_stars:") for d in tier20_data)
    print("new tier 20 pre-payment screen offers subject choice, not direct payment: OK")

    for tier_id in ACTIVE_TIERS - {20}:
        tier_kb = tb.get_sub_tier_keyboard(tier_id)
        tt = kb_texts(tier_kb)
        assert any("Оплатить" in t and "звёзд" in t for t in tt)
        assert any("Оплатить" in t and "₽" in t for t in tt)
    print("non-subject-choice active tiers offer direct payment buttons: OK")

    # 13b. Upsell: every active tier except the most expensive one offers the next tier up
    price_sorted = sorted(ACTIVE_TIERS, key=lambda t: tb.SUBSCRIPTION_TIERS[t]["price_rub"])
    top_tier = price_sorted[-1]
    assert top_tier == 28
    for i, tier_id in enumerate(price_sorted[:-1]):
        nxt_id = price_sorted[i + 1]
        upsell_text = tb.get_tier_upsell_text(tier_id)
        assert "Выгоднее" in upsell_text
        assert str(tb.SUBSCRIPTION_TIERS[nxt_id]["price_rub"]) in upsell_text
        upsell_kb = tb.get_tier_upsell_keyboard(tier_id)
        assert upsell_kb is not None
    assert tb.get_tier_upsell_text(top_tier) == ""
    assert tb.get_tier_upsell_keyboard(top_tier) is None
    print("tier upsell dynamically points at the next-more-expensive active tier: OK")

    # 14. Rubles flow: deep-link keyboard and message text for all active tiers
    for tier_id in ACTIVE_TIERS:
        rub_text = tb.get_sub_rubles_message_text(tier_id)
        check_html(rub_text)
        rub_kb = tb.get_sub_rubles_keyboard(tier_id)
        assert any(b.url for row in rub_kb.inline_keyboard for b in row if b.url)
    print("rubles deep-link flow OK for all active tiers")

    # 15. Handlers: subscription_menu now opens the course picker (not a flat tier list directly)
    cb1 = FakeCB("subscription_menu", uid=non_admin)
    await tb.cb_subscription_menu(cb1)
    assert cb1.message.edits
    picker_text, picker_kb = cb1.message.edits[0]
    check_html(picker_text)
    assert "Выбери свой курс" in picker_text
    picker_data = kb_data(picker_kb)
    assert picker_data[:3] == ["subscription_course:year1", "subscription_course:year2", "subscription_all_tiers"]
    print("cb_subscription_menu renders the course picker: OK")

    cb2 = FakeCB("sub_tier:26", uid=non_admin)
    await tb.cb_sub_tier(cb2)
    assert cb2.message.edits and "2 курса" in cb2.message.edits[0][0]
    print("cb_sub_tier renders correct tier: OK")

    cb3 = FakeCB("sub_tier:99", uid=non_admin)
    await tb.cb_sub_tier(cb3)
    assert cb3._answers and cb3._answers[0][1] is True and not cb3.message.edits
    print("cb_sub_tier rejects unknown tier: OK")

    cb3b = FakeCB("sub_tier:9", uid=non_admin)  # retired tier — still reachable (historical deep link), but not sold
    await tb.cb_sub_tier(cb3b)
    assert cb3b.message.edits, "retired tier screens still render if reached directly (no crash)"
    retired_text, retired_kb = cb3b.message.edits[0]
    check_html(retired_text)
    assert "больше не продаётся" in retired_text
    assert tb.SUBSCRIPTION_TIERS[9]["title"] in retired_text
    assert not any(d.startswith("buy_sub_") for d in kb_data(retired_kb)), "no live payment buttons on a retired tier screen"
    assert kb_data(retired_kb) == ["subscription_menu"]
    print("cb_sub_tier shows a 'no longer sold' screen (no payment buttons) for a retired tier id: OK")

    # 15c. Regression: none of the purchase-creating handlers may act on a retired tier — this is
    # the exact gap a production smoke-check caught (buy_sub_stars:9 was creating a real XTR
    # invoice for a tier that's supposed to be unsellable) before this guard existed.
    orig_send_invoice_retired = tb.bot.send_invoice
    retired_invoice_calls = []
    async def fake_send_invoice_retired(**kwargs):
        retired_invoice_calls.append(kwargs)
    tb.bot.send_invoice = fake_send_invoice_retired
    retired_admin_sent = []
    async def fake_send_message_retired(chat_id, text, **kwargs):
        retired_admin_sent.append((chat_id, text))
    orig_send_message_retired = tb.bot.send_message
    tb.bot.send_message = fake_send_message_retired

    retired_uid = random.randint(10_000_000, 99_999_999)
    tb.stats["subscriptions"].pop(str(retired_uid), None)

    cb_retired_stars = FakeCB("buy_sub_stars:9", uid=retired_uid)
    await tb.cb_buy_sub_stars(cb_retired_stars)
    assert not retired_invoice_calls, "must not create an invoice for a retired tier"
    assert cb_retired_stars._answers and cb_retired_stars._answers[0][1] is True
    assert cb_retired_stars._answers[0][0] == "Этот тариф больше не продаётся"

    cb_retired_rub = FakeCB("buy_sub_rubles:9", uid=retired_uid)
    await tb.cb_buy_sub_rubles(cb_retired_rub)
    assert not retired_admin_sent, "must not notify admins of a payment request for a retired tier"
    assert not cb_retired_rub.message.edits, "must not show payment instructions for a retired tier"
    assert cb_retired_rub._answers and cb_retired_rub._answers[0][1] is True

    cb_retired_stars_disc = FakeCB("buy_sub_stars_discount:9", uid=retired_uid)
    await tb.cb_buy_sub_stars_discount(cb_retired_stars_disc)
    assert not retired_invoice_calls, "discount path must not create an invoice for a retired tier either"

    cb_retired_rub_disc = FakeCB("buy_sub_rubles_discount:9", uid=retired_uid)
    await tb.cb_buy_sub_rubles_discount(cb_retired_rub_disc)
    assert not retired_admin_sent

    cb_retired_disc_screen = FakeCB("sub_discount:9", uid=retired_uid)
    await tb.cb_sub_discount(cb_retired_disc_screen)
    assert not cb_retired_disc_screen.message.edits, "discount offer screen must reject a retired tier too"

    assert not tb.has_active_subscription(retired_uid), "no path above may have granted anything"
    tb.bot.send_invoice = orig_send_invoice_retired
    tb.bot.send_message = orig_send_message_retired
    print("every purchase-creating handler (stars/rubles, incl. discount) rejects a retired tier id: OK")

    cb4 = FakeCB("buy_sub_rubles:22", uid=non_admin)
    await tb.cb_buy_sub_rubles(cb4)
    assert cb4.message.edits and "249" in cb4.message.edits[0][0]
    print("cb_buy_sub_rubles renders payment instructions: OK")

    # 15b. Subject-choice purchase flow end-to-end (rubles), now on new tier 20
    cb_subj = FakeCB("sub_subject:20:biology", uid=non_admin)
    await tb.cb_sub_subject(cb_subj)
    assert cb_subj.message.edits and "Биологии" in cb_subj.message.edits[0][0]
    subj_kb_data = kb_data(cb_subj.message.edits[0][1])
    assert "buy_sub_stars_subj:20:biology" in subj_kb_data
    assert "buy_sub_rubles_subj:20:biology" in subj_kb_data

    cb_subj_bad = FakeCB("sub_subject:20:latin", uid=non_admin)
    await tb.cb_sub_subject(cb_subj_bad)
    assert not cb_subj_bad.message.edits, "unknown subject must be rejected"

    cb_rub_subj = FakeCB("buy_sub_rubles_subj:20:biology", uid=non_admin)
    await tb.cb_buy_sub_rubles_subj(cb_rub_subj)
    assert cb_rub_subj.message.edits
    rub_subj_text = cb_rub_subj.message.edits[0][0]
    assert "Биологии" in rub_subj_text
    print("subject-choice purchase flow (rubles) renders subject-specific screens: OK")

    # 16. Stars purchase flow: send_invoice captured, payload encodes tier (and subject, if any)
    orig_send_invoice = tb.bot.send_invoice
    invoice_calls = []
    async def fake_send_invoice(**kwargs):
        invoice_calls.append(kwargs)
    tb.bot.send_invoice = fake_send_invoice

    cb5 = FakeCB("buy_sub_stars:28", uid=non_admin)
    await tb.cb_buy_sub_stars(cb5)
    assert invoice_calls, "expected send_invoice to be called"
    call = invoice_calls[-1]
    assert call["currency"] == "XTR"
    assert call["prices"][0].amount == tb.SUBSCRIPTION_TIERS[28]["price_stars"]
    assert call["payload"].startswith(f"sub_stars_28_-_{non_admin}_")
    print("buy_sub_stars sends correct XTR invoice: OK")

    cb5b = FakeCB("buy_sub_stars_subj:20:chemistry", uid=non_admin)
    await tb.cb_buy_sub_stars_subj(cb5b)
    call = invoice_calls[-1]
    assert call["payload"].startswith(f"sub_stars_20_chemistry_{non_admin}_")
    assert "Химии" in call["title"]
    print("buy_sub_stars_subj encodes the chosen subject into the invoice payload: OK")

    # 17. successful_payment for a subscription payload grants the tier and does NOT touch donations
    tb.stats["subscriptions"].pop(str(non_admin), None)
    donations_before = tb.stats["donations_stars_total"]
    admin_msgs = []
    orig_send_message = tb.bot.send_message
    async def fake_send_message(chat_id, text, **kwargs):
        admin_msgs.append((chat_id, text))
    tb.bot.send_message = fake_send_message

    msg = FakeMsg(from_user=FakeUser(non_admin))
    msg.successful_payment = FakeSuccessfulPayment(28, f"sub_stars_27_-_{non_admin}_{int(time.time())}")
    await tb.handle_successful_payment(msg)
    assert tb.anatomy_access_ok(non_admin)
    assert tb.get_subscription(non_admin)["tier"] == 27
    assert tb.get_subscription(non_admin)["subscription_version"] == 2
    assert tb.stats["donations_stars_total"] == donations_before, "subscription payment must not be counted as a donation"
    buyer_msgs = [t for cid, t in admin_msgs if cid == non_admin]
    assert buyer_msgs and "активирована" in buyer_msgs[0]
    print("successful_payment (subscription payload) grants tier, not counted as donation: OK")

    # 17b. successful_payment with an encoded subject grants a subject-restricted subscription
    tb.stats["subscriptions"].pop(str(non_admin), None)
    msg_subj = FakeMsg(from_user=FakeUser(non_admin))
    msg_subj.successful_payment = FakeSuccessfulPayment(99, f"sub_stars_20_chemistry_{non_admin}_{int(time.time())}")
    await tb.handle_successful_payment(msg_subj)
    assert tb.get_subscription(non_admin)["restricted_subject"] == "chemistry"
    assert tb.has_subject_access(non_admin, "chemistry") and not tb.has_subject_access(non_admin, "biology")
    tb.stats["subscriptions"].pop(str(non_admin), None)
    print("successful_payment with an encoded subject grants subject-restricted access: OK")

    # 18. successful_payment for a donation payload still works as before (regression)
    donations_before = tb.stats["donations_stars_total"]
    msg2 = FakeMsg(from_user=FakeUser(non_admin))
    msg2.successful_payment = FakeSuccessfulPayment(50, f"donate_stars_50_{non_admin}_{int(time.time())}")
    await tb.handle_successful_payment(msg2)
    assert tb.stats["donations_stars_total"] == donations_before + 50
    assert not tb.has_active_subscription(non_admin), "donation must not grant a subscription"
    assert msg2.answers and "Спасибо" in msg2.answers[0][0]
    print("successful_payment (donation payload) still works, grants no subscription: OK")

    tb.bot.send_invoice = orig_send_invoice
    tb.bot.send_message = orig_send_message

    # 19. Admin manual rubles grant flow — reply-keyboard tier picker, non-subject new tier
    tb.stats["subscriptions"].pop(str(non_admin), None)
    tb.stats["user_username"][str(non_admin)] = "testbuyer"
    tb.stats["usernames"]["testbuyer"] = non_admin
    admin_notify = []
    async def fake_send_message2(chat_id, text, **kwargs):
        admin_notify.append((chat_id, text))
    tb.bot.send_message = fake_send_message2

    cb_prompt = FakeCB("admin_subscription_prompt")
    await tb.cb_admin_subscription_prompt(cb_prompt)
    assert tb.ADMIN_PENDING[ADMIN_ID]["action"] == "record_subscription_username"

    m1 = FakeMsg(from_user=FakeUser(ADMIN_ID))
    m1.text = "testbuyer"
    await tb.handle_admin_pending_action(m1)
    assert tb.ADMIN_PENDING[ADMIN_ID]["action"] == "record_subscription_tier"
    assert tb.ADMIN_PENDING[ADMIN_ID]["target_id"] == non_admin
    assert m1.answers and isinstance(m1.answers[-1][1], tb.ReplyKeyboardMarkup), "tier prompt should carry a reply-keyboard"
    tier_kb_texts = [b.text for row in m1.answers[-1][1].keyboard for b in row]
    assert any(t.startswith("26 —") for t in tier_kb_texts), "reply-keyboard should list active tiers by id"
    assert not any(t.startswith("9 —") for t in tier_kb_texts), "retired tiers must not appear on the quick-picker"

    m2 = FakeMsg(from_user=FakeUser(ADMIN_ID))
    m2.text = "26 — всё, до конца 2 курса — 1290₽"  # simulates tapping the reply-keyboard button
    await tb.handle_admin_pending_action(m2)
    assert ADMIN_ID not in tb.ADMIN_PENDING
    assert tb.get_subscription(non_admin)["tier"] == 26
    assert tb.get_subscription(non_admin)["method"] == "rubles_manual"
    assert admin_notify and "активирована" in admin_notify[-1][1]
    print("admin manual rubles subscription grant flow via reply-keyboard: OK")

    # 19b. retired tier number is rejected even though it still exists in SUBSCRIPTION_TIERS
    tb.stats["subscriptions"].pop(str(non_admin), None)
    cb_prompt_r = FakeCB("admin_subscription_prompt")
    await tb.cb_admin_subscription_prompt(cb_prompt_r)
    mr1 = FakeMsg(from_user=FakeUser(ADMIN_ID))
    mr1.text = "testbuyer"
    await tb.handle_admin_pending_action(mr1)
    mr2 = FakeMsg(from_user=FakeUser(ADMIN_ID))
    mr2.text = "9"  # retired tier
    await tb.handle_admin_pending_action(mr2)
    assert ADMIN_ID in tb.ADMIN_PENDING, "retired tier must not clear pending state"
    assert not tb.has_active_subscription(non_admin)
    del tb.ADMIN_PENDING[ADMIN_ID]
    print("admin flow rejects retired tier numbers: OK")

    # invalid tier number rejected
    tb.stats["subscriptions"].pop(str(non_admin), None)
    cb_prompt2 = FakeCB("admin_subscription_prompt")
    await tb.cb_admin_subscription_prompt(cb_prompt2)
    m3 = FakeMsg(from_user=FakeUser(ADMIN_ID))
    m3.text = "testbuyer"
    await tb.handle_admin_pending_action(m3)
    m4 = FakeMsg(from_user=FakeUser(ADMIN_ID))
    m4.text = "999"
    await tb.handle_admin_pending_action(m4)
    assert ADMIN_ID in tb.ADMIN_PENDING, "invalid tier should not clear pending state"
    assert not tb.has_active_subscription(non_admin)

    # cancel via the reply-keyboard's "Отмена" button
    m4b = FakeMsg(from_user=FakeUser(ADMIN_ID))
    m4b.text = "❌ Отмена"
    await tb.handle_admin_pending_action(m4b)
    assert ADMIN_ID not in tb.ADMIN_PENDING
    print("admin flow rejects invalid tier number, supports cancel: OK")

    # 19c. Admin grant flow for a subject-choice tier — new tier 20 is active, so (unlike before,
    # when the only subject-choice tier was retired) this path is now exercised with real data.
    tb.stats["subscriptions"].pop(str(non_admin), None)
    cb_prompt3 = FakeCB("admin_subscription_prompt")
    await tb.cb_admin_subscription_prompt(cb_prompt3)
    m5 = FakeMsg(from_user=FakeUser(ADMIN_ID))
    m5.text = "testbuyer"
    await tb.handle_admin_pending_action(m5)
    m6 = FakeMsg(from_user=FakeUser(ADMIN_ID))
    m6.text = "20"
    await tb.handle_admin_pending_action(m6)
    assert tb.ADMIN_PENDING[ADMIN_ID]["action"] == "record_subscription_subject"
    assert m6.answers and isinstance(m6.answers[-1][1], tb.ReplyKeyboardMarkup)
    m7 = FakeMsg(from_user=FakeUser(ADMIN_ID))
    m7.text = "Химия"
    await tb.handle_admin_pending_action(m7)
    assert ADMIN_ID not in tb.ADMIN_PENDING
    granted20 = tb.get_subscription(non_admin)
    assert granted20["tier"] == 20 and granted20["restricted_subject"] == "chemistry"
    tb.stats["subscriptions"].pop(str(non_admin), None)
    print("admin grant flow for a subject-choice new tier (20) end-to-end: OK")

    tb.bot.send_message = orig_send_message

    # 20. Upsell shown after purchase (stars + admin rubles paths) for a non-top-tier purchase
    upsell_uid = random.randint(10_000_000, 99_999_999)
    async def fake_send_invoice2(**kwargs):
        pass
    tb.bot.send_invoice = fake_send_invoice2
    sent4 = []
    async def fake_send_message4(chat_id, text, **kwargs):
        sent4.append((chat_id, text, kwargs.get("reply_markup")))
    tb.bot.send_message = fake_send_message4

    msg_t1 = FakeMsg(from_user=FakeUser(upsell_uid))
    msg_t1.successful_payment = FakeSuccessfulPayment(99, f"sub_stars_20_-_{upsell_uid}_{int(time.time())}")
    await tb.handle_successful_payment(msg_t1)
    buyer_sent = [(c, t, k) for c, t, k in sent4 if c == upsell_uid]
    assert buyer_sent, "expected a confirmation message"
    _, t1_text, t1_kb = buyer_sent[0]
    check_html(t1_text)
    assert "активирована" in t1_text and "Выгоднее" in t1_text
    assert t1_kb is not None
    tb.stats["subscriptions"].pop(str(upsell_uid), None)
    print("tier 20 stars purchase offers an upsell to the next tier: OK")

    sent4.clear()
    upsell_uid2 = random.randint(10_000_000, 99_999_999)
    msg_t28 = FakeMsg(from_user=FakeUser(upsell_uid2))
    msg_t28.successful_payment = FakeSuccessfulPayment(2990, f"sub_stars_28_-_{upsell_uid2}_{int(time.time())}")
    await tb.handle_successful_payment(msg_t28)
    buyer_sent2 = [(c, t, k) for c, t, k in sent4 if c == upsell_uid2]
    assert buyer_sent2
    _, t28_text, t28_kb = buyer_sent2[0]
    assert "Выгоднее" not in t28_text and t28_kb is None
    tb.stats["subscriptions"].pop(str(upsell_uid2), None)
    tb.bot.send_invoice = orig_send_invoice
    tb.bot.send_message = orig_send_message
    print("top-tier (28) purchase shows no upsell: OK")

    # 20b. Buying with rubles pings admins with a one-tap payment-confirm request, and tapping it
    # grants the subscription immediately (old manual admin flow still works too)
    confirm_uid = random.randint(10_000_000, 99_999_999)
    tb.stats["subscriptions"].pop(str(confirm_uid), None)
    admin_sent = []
    async def fake_send_message5(chat_id, text, **kwargs):
        admin_sent.append((chat_id, text, kwargs.get("reply_markup")))
    tb.bot.send_message = fake_send_message5

    cb_rub = FakeCB("buy_sub_rubles:22", uid=confirm_uid)
    await tb.cb_buy_sub_rubles(cb_rub)
    assert cb_rub.message.edits, "buyer still sees the @vmeda_helper deep-link screen"
    admin_requests = [(c, t, k) for c, t, k in admin_sent if c in tb.ADMIN_IDS]
    assert len(admin_requests) == len(tb.ADMIN_IDS), "every admin should get a confirm request"
    req_chat, req_text, req_kb = admin_requests[0]
    check_html(req_text)
    assert "249" in req_text and "подтверждение оплаты" in req_text
    assert req_kb is not None
    confirm_cb_data = req_kb.inline_keyboard[0][0].callback_data
    assert confirm_cb_data == f"admin_confirm_sub:22:{confirm_uid}:-:249"
    print("buy_sub_rubles pings every admin with a one-tap confirm request: OK")

    admin_sent.clear()
    cb_confirm = FakeCB(confirm_cb_data, uid=ADMIN_ID)
    await tb.cb_admin_confirm_sub(cb_confirm)
    assert tb.get_subscription(confirm_uid)["tier"] == 22
    assert tb.get_subscription(confirm_uid)["method"] == "rubles"
    assert cb_confirm.message.edits and "Подтверждено" in cb_confirm.message.edits[0][0]
    buyer_notified = [(c, t) for c, t, _ in admin_sent if c == confirm_uid]
    assert buyer_notified and "активирована" in buyer_notified[0][1]
    print("tapping the admin confirm button grants the subscription and notifies the buyer: OK")

    # tapping confirm again (e.g. the other admin) is a harmless no-op, not a duplicate grant/notify
    admin_sent.clear()
    cb_confirm2 = FakeCB(confirm_cb_data, uid=ADMIN_ID)
    await tb.cb_admin_confirm_sub(cb_confirm2)
    assert cb_confirm2.message.edits and "Уже подтверждено" in cb_confirm2.message.edits[0][0]
    assert not [c for c, t, _ in admin_sent if c == confirm_uid], "must not re-notify the buyer"
    print("double-confirm (race between two admins) does not re-grant or re-notify: OK")

    # non-admin cannot tap the confirm button
    tb.stats["subscriptions"].pop(str(confirm_uid), None)
    cb_confirm_bad = FakeCB(confirm_cb_data, uid=non_admin)
    await tb.cb_admin_confirm_sub(cb_confirm_bad)
    assert not tb.has_active_subscription(confirm_uid), "non-admin must not be able to confirm payments"
    tb.stats["subscriptions"].pop(str(confirm_uid), None)
    print("non-admin cannot confirm a payment: OK")

    # reject button: closes the request without granting anything (buyer ignored/never paid)
    reject_uid = random.randint(10_000_000, 99_999_999)
    tb.stats["subscriptions"].pop(str(reject_uid), None)
    tb.stats["user_username"][str(reject_uid)] = "ignoredbuyer"
    admin_sent.clear()
    cb_rub2 = FakeCB("buy_sub_rubles:22", uid=reject_uid)
    await tb.cb_buy_sub_rubles(cb_rub2)
    admin_requests2 = [(c, t, k) for c, t, k in admin_sent if c in tb.ADMIN_IDS]
    req_kb2 = admin_requests2[0][2]
    assert len(req_kb2.inline_keyboard) == 2, "confirm and reject should each be on their own row"
    confirm_data2 = req_kb2.inline_keyboard[0][0].callback_data
    reject_data2 = req_kb2.inline_keyboard[1][0].callback_data
    assert reject_data2 == f"admin_reject_sub:22:{reject_uid}:-"

    cb_reject = FakeCB(reject_data2, uid=ADMIN_ID)
    await tb.cb_admin_reject_sub(cb_reject)
    assert cb_reject.message.edits and "Отклонено" in cb_reject.message.edits[0][0]
    assert not tb.has_active_subscription(reject_uid), "reject must not grant a subscription"
    assert str(reject_uid) not in tb.stats["subscriptions"]

    # confirm still works afterwards (declining doesn't block a later real confirmation)
    cb_confirm3 = FakeCB(confirm_data2, uid=ADMIN_ID)
    await tb.cb_admin_confirm_sub(cb_confirm3)
    assert tb.get_subscription(reject_uid)["tier"] == 22
    tb.stats["subscriptions"].pop(str(reject_uid), None)

    # non-admin cannot tap the reject button either
    cb_reject_bad = FakeCB(reject_data2, uid=non_admin)
    await tb.cb_admin_reject_sub(cb_reject_bad)
    assert not cb_reject_bad.message.edits, "non-admin must not be able to reject a payment request"
    tb.bot.send_message = orig_send_message
    print("reject button closes an unpaid request without granting, and doesn't block a later confirm: OK")

    # 21. Referral gate integration: get_referral_status_text shows subscription branch
    tb.grant_subscription(non_admin, 26, "stars", 1290)
    status_text = tb.get_referral_status_text(non_admin)
    check_html(status_text)
    assert "активна подписка" in status_text
    tb.stats["subscriptions"].pop(str(non_admin), None)
    print("get_referral_status_text shows active-subscription branch: OK")

    tb.stats["referrals"].pop(str(non_admin), None)
    tb.stats["temporary_access"].pop(str(non_admin), None)
    if non_admin in tb.stats["manual_access_granted"]:
        tb.stats["manual_access_granted"].remove(non_admin)
    default_text = tb.get_referral_status_text(non_admin)
    check_html(default_text)
    assert "Не хочешь ждать друзей" in default_text
    assert str(tb.cheapest_gated3_tier()["price_rub"]) in default_text
    assert "Medical_vpn_bot" in default_text
    # the "самые выгодные варианты" callout now points at active tiers 21/26, never a retired one
    assert tb.SUBSCRIPTION_TIERS[21]["short"] in default_text
    assert tb.SUBSCRIPTION_TIERS[26]["short"] in default_text
    print("default referral text includes subscription teaser pointing at active tiers 21/26: OK")

    back_kb = tb.get_referral_back_keyboard()
    assert any("Открыть доступ без рефералов" in t for t in kb_texts(back_kb))
    assert any(t == "🚀 Запустить Medical_vpn_bot" for t in kb_texts(back_kb))
    vpn_btn = next(b for row in back_kb.inline_keyboard for b in row if b.text == "🚀 Запустить Medical_vpn_bot")
    assert vpn_btn.url == tb.MEDICAL_VPN_URL
    print("get_referral_back_keyboard has subscription button: OK")

    teaser_kb = tb.get_subscription_teaser_keyboard()
    assert kb_texts(teaser_kb)[0] == "💎 Открыть доступ без рефералов"
    assert teaser_kb.inline_keyboard[0][0].callback_data == "subscription_menu"
    assert any(t == "🚀 Запустить Medical_vpn_bot" for t in kb_texts(teaser_kb))
    print("get_subscription_teaser_keyboard: OK")

    # 22. Main menu: subscription button always visible; anatomy/histology labels reflect
    # has_subscription_anatomy_access/has_subscription_histology_access, not scope=="all".
    # Anatomy's label has a third state (ANATOMY_MAINTENANCE_MODE, unrelated to subscriptions —
    # see test_anatomy_maintenance.py) that would otherwise shadow the 💎/plain distinction this
    # section actually tests; pin it to False for this section only, same save/restore pattern
    # test_anatomy_maintenance.py itself uses, so this test's outcome doesn't depend on whatever
    # unrelated state that flag happens to be in.
    orig_maintenance_mode = tb.anatomy_handlers.ANATOMY_MAINTENANCE_MODE
    tb.anatomy_handlers.ANATOMY_MAINTENANCE_MODE = False
    try:
        menu_no_sub = tb.get_main_menu(user_id=non_admin)
        assert "💎 Подписка без рефералов" in kb_texts(menu_no_sub)
        assert "🔥🦴 Анатомия" in kb_texts(menu_no_sub)
        assert "🔬 Гистология (рефералы/подписка)" in kb_texts(menu_no_sub)

        tb.grant_subscription(non_admin, 21, "stars", 129)  # no histology, no anatomy
        menu_tier21 = tb.get_main_menu(user_id=non_admin)
        tier21_texts = kb_texts(menu_tier21)
        assert "💎 Моя подписка" in tier21_texts
        assert "🔬 Гистология (рефералы/подписка)" in tier21_texts, "tier 21 has no histology"
        assert "🔥🦴 Анатомия" in tier21_texts, "tier 21 has no anatomy — button stays plain (not the 💎 variant)"
        tb.stats["subscriptions"].pop(str(non_admin), None)

        tb.grant_subscription(non_admin, 24, "stars", 599)  # anatomy + histology yes (Зимняя сессия)
        menu_tier24 = tb.get_main_menu(user_id=non_admin)
        tier24_texts = kb_texts(menu_tier24)
        assert "🔥🦴 Анатомия 💎" in tier24_texts
        assert "🔬 Гистология 💎" in tier24_texts
        tb.stats["subscriptions"].pop(str(non_admin), None)
    finally:
        tb.anatomy_handlers.ANATOMY_MAINTENANCE_MODE = orig_maintenance_mode
    print("main menu subscription button always visible, anatomy/histology labels match per-tier flags: OK")

    # 22b. Regression: free referral access (no subscription) must still show the subscription entry
    tb.stats["referrals"][str(non_admin)] = [f"ref{i}" for i in range(tb.REFERRAL_FULL_ACCESS_THRESHOLD)]
    assert tb.get_referral_count(non_admin) >= tb.REFERRAL_FULL_ACCESS_THRESHOLD
    assert tb.has_free_access(non_admin) and not tb.has_active_subscription(non_admin)
    menu_referral_access = tb.get_main_menu(user_id=non_admin)
    assert "💎 Подписка без рефералов" in kb_texts(menu_referral_access)
    tb.stats["referrals"].pop(str(non_admin), None)
    print("subscription button stays visible for users with free referral access (not subscribed): OK")

    # 23. Locked Histology screen: dynamic cheapest-histology-tier price, not a stale literal
    tb.stats["histology_temp_access"][str(non_admin)] = tb.time.time() - 1
    tb.stats["histology_warnings"][str(non_admin)] = {"count": tb.HISTOLOGY_WARNING_THRESHOLD, "last_warn_at": 0}
    cb_hist_locked = FakeCB("histology_menu", uid=non_admin)
    await tb.cb_histology_menu(cb_hist_locked)
    assert cb_hist_locked.message.edits
    hist_locked_text, hist_locked_kb = cb_hist_locked.message.edits[0]
    check_html(hist_locked_text)
    assert "полностью готов" in hist_locked_text
    assert str(tb.cheapest_histology_tier()["price_rub"]) in hist_locked_text
    assert any("Оформить подписку" in t for t in kb_texts(hist_locked_kb))
    tb.stats["histology_temp_access"].pop(str(non_admin), None)
    tb.stats["histology_warnings"].pop(str(non_admin), None)

    tb.grant_subscription(non_admin, 24, "stars", 599)
    cb_hist_unlocked = FakeCB("histology_menu", uid=non_admin)
    await tb.cb_histology_menu(cb_hist_unlocked)
    assert cb_hist_unlocked.message.edits
    assert "Выбери диагностику" in cb_hist_unlocked.message.edits[0][0]
    tb.stats["subscriptions"].pop(str(non_admin), None)
    print("histology_menu shows locked screen with dynamic subscription CTA when access is missing: OK")

    # 24. anatomy_menu always renders the full section list (never a blanket lock screen) —
    # paid-tier sections show a 🔒 prefix until the user has a qualifying subscription
    cb_anat_locked = FakeCB("anatomy_menu", uid=non_admin)
    await tb.cb_anatomy_menu(cb_anat_locked)
    assert cb_anat_locked.message.edits
    locked_text, locked_kb = cb_anat_locked.message.edits[0]
    check_html(locked_text)
    assert "Выбери подраздел" in locked_text
    locked_labels = kb_texts(locked_kb)
    for section_key, section in tb.ANATOMY.items():
        label = section.get("menu_title", section["title"])
        if section_key in tb.ANATOMY_FREE_SECTIONS:
            assert label in locked_labels, f"{section_key} should be unlocked"
        else:
            assert f"🔒 {label}" in locked_labels, f"{section_key} should show a lock icon"

    tb.grant_subscription(non_admin, 24, "stars", 599)
    cb_anat_unlocked = FakeCB("anatomy_menu", uid=non_admin)
    await tb.cb_anatomy_menu(cb_anat_unlocked)
    assert cb_anat_unlocked.message.edits
    unlocked_text, unlocked_kb = cb_anat_unlocked.message.edits[0]
    assert "Выбери подраздел" in unlocked_text
    assert not any(t.startswith("🔒") for t in kb_texts(unlocked_kb)), "subscribed user should see no locks"
    tb.stats["subscriptions"].pop(str(non_admin), None)
    print("anatomy_menu always renders; paid sections show 🔒 until a qualifying subscription: OK")

    # 24b. Tapping a locked section shows a section-specific locked screen with a dynamic tier list
    paid_section_key = next(k for k in tb.ANATOMY if k not in tb.ANATOMY_FREE_SECTIONS)
    cb_section_locked = FakeCB(f"anatomy_section:{paid_section_key}", uid=non_admin)
    await tb.cb_anatomy_section(cb_section_locked)
    assert cb_section_locked.message.edits
    section_locked_text, section_locked_kb = cb_section_locked.message.edits[0]
    check_html(section_locked_text)
    for cfg in tb.ACTIVE_SUBSCRIPTION_TIERS.values():
        if cfg.get("anatomy"):
            assert cfg["title"] in section_locked_text
    assert any("Оформить подписку" in t for t in kb_texts(section_locked_kb))
    print("locked section screen lists all anatomy-granting tiers dynamically: OK")

    # 24c. The short callback-answer alert for in-handler anatomy locks stays under Telegram's ~200-char cap
    alert_text = tb.get_anatomy_dev_alert_text()
    assert len(alert_text) <= 200
    assert str(tb.cheapest_anatomy_tier()["price_rub"]) in alert_text
    print("anatomy dev-alert text is short and dynamically priced: OK")

    # 25. is_gated_callback exempts all subscription callbacks (must always be reachable) —
    # including the new course-picker/all-tiers screens
    assert not tb.is_gated_callback("subscription_menu")
    assert not tb.is_gated_callback("subscription_all_tiers")
    assert not tb.is_gated_callback("subscription_course:year1")
    assert not tb.is_gated_callback("sub_tier:21")
    assert not tb.is_gated_callback("buy_sub_stars:21")
    assert not tb.is_gated_callback("buy_sub_rubles:21")
    assert not tb.is_gated_callback("sub_subject:20:biology")
    print("subscription callbacks (incl. the new course screens) exempt from referral gate: OK")

    # 26. Admin subscription-announcement broadcast: preview -> confirm -> broadcast
    orig_broadcast = tb._broadcast
    broadcast_calls = []
    async def fake_broadcast(text, keyboard=None):
        broadcast_calls.append((text, keyboard))
    tb._broadcast = fake_broadcast

    ann_text = tb.get_subscription_announcement_text()
    check_html(ann_text)
    for cfg in tb.ACTIVE_SUBSCRIPTION_TIERS.values():
        assert str(cfg["price_rub"]) in ann_text
    for t in RETIRED_TIERS:
        assert tb.SUBSCRIPTION_TIERS[t]["title"] not in ann_text
    ann_kb = tb.get_subscription_announcement_keyboard()
    assert kb_texts(ann_kb)[0] == "💎 Подписка без рефералов"
    assert ann_kb.inline_keyboard[0][0].callback_data == "subscription_menu"

    cb_ann1 = FakeCB("admin_announce_subscription_confirm")
    await tb.cb_admin_announce_subscription_confirm(cb_ann1)
    assert cb_ann1.message.edits and "Отправить" in cb_ann1.message.edits[0][0]
    assert not broadcast_calls, "must not broadcast before confirmation"

    broadcasts_before = tb.stats.get("broadcast_count", 0)
    cb_ann2 = FakeCB("admin_announce_subscription_go")
    await tb.cb_admin_announce_subscription_go(cb_ann2)
    assert broadcast_calls, "expected broadcast to be sent"
    assert broadcast_calls[0][0] == ann_text
    assert tb.stats["broadcast_count"] == broadcasts_before + 1
    assert cb_ann2.message.edits and "отправлено" in cb_ann2.message.edits[0][0]

    cb_ann3 = FakeCB("admin_announce_subscription_confirm", uid=non_admin)
    await tb.cb_admin_announce_subscription_confirm(cb_ann3)
    assert not cb_ann3.message.edits, "non-admin must be blocked"

    tb._broadcast = orig_broadcast
    print("admin subscription-announcement broadcast lists only active tiers, excludes retired ones: OK")

    # 26b. Admin Anatomy-section announcement broadcast: preview -> confirm -> broadcast
    orig_broadcast2 = tb._broadcast
    anatomy_broadcast_calls = []
    async def fake_broadcast2(text, keyboard=None):
        anatomy_broadcast_calls.append((text, keyboard))
    tb._broadcast = fake_broadcast2

    anat_ann_text = tb.get_anatomy_announcement_text()
    check_html(anat_ann_text)
    for cfg in tb.ACTIVE_SUBSCRIPTION_TIERS.values():
        if cfg.get("anatomy"):
            assert str(cfg["price_rub"]) in anat_ann_text
            assert cfg["title"] in anat_ann_text
    for t in RETIRED_TIERS:
        assert tb.SUBSCRIPTION_TIERS[t]["title"] not in anat_ann_text
    # tier 21 (no anatomy) must not be advertised as an anatomy-granting tier here
    assert tb.SUBSCRIPTION_TIERS[21]["title"] not in anat_ann_text
    anat_ann_kb = tb.get_anatomy_announcement_keyboard()
    anat_ann_data = kb_data(anat_ann_kb)
    assert "subscription_menu" in anat_ann_data
    assert "anatomy_root" in anat_ann_data

    cb_anat1 = FakeCB("admin_announce_anatomy_confirm")
    await tb.cb_admin_announce_anatomy_confirm(cb_anat1)
    assert cb_anat1.message.edits and "Отправить" in cb_anat1.message.edits[0][0]
    assert not anatomy_broadcast_calls, "must not broadcast before confirmation"

    broadcasts_before2 = tb.stats.get("broadcast_count", 0)
    cb_anat2 = FakeCB("admin_announce_anatomy_go")
    await tb.cb_admin_announce_anatomy_go(cb_anat2)
    assert anatomy_broadcast_calls, "expected broadcast to be sent"
    assert anatomy_broadcast_calls[0][0] == anat_ann_text
    assert tb.stats["broadcast_count"] == broadcasts_before2 + 1
    assert cb_anat2.message.edits and "отправлен" in cb_anat2.message.edits[0][0]

    cb_anat3 = FakeCB("admin_announce_anatomy_confirm", uid=non_admin)
    await tb.cb_admin_announce_anatomy_confirm(cb_anat3)
    assert not cb_anat3.message.edits, "non-admin must be blocked"

    tb._broadcast = orig_broadcast2
    print("admin Anatomy-announcement broadcast lists only anatomy-granting active tiers: OK")

    # 26c. Admin panel exposes the new Anatomy-announcement button
    admin_menu_texts = kb_texts(tb.get_admin_menu())
    assert "📣 Анонс раздела Анатомия" in admin_menu_texts
    print("admin panel exposes Anatomy-announcement button: OK")

    # 26c2. Admin Anatomy-exam announcement broadcast (ТЕСТ/теория/практика): preview -> confirm -> broadcast
    orig_broadcast_exam = tb._broadcast
    exam_broadcast_calls = []
    async def fake_broadcast_exam(text, keyboard=None):
        exam_broadcast_calls.append((text, keyboard))
    tb._broadcast = fake_broadcast_exam

    exam_ann_text = tb.get_anatomy_exam_announcement_text()
    check_html(exam_ann_text)
    exam_ann_kb = tb.get_anatomy_exam_announcement_keyboard()
    exam_ann_data = kb_data(exam_ann_kb)
    assert "anatomy_exam_test_menu" in exam_ann_data
    assert "anatomy_exam_theory" in exam_ann_data
    assert "anatomy_exam_practice" in exam_ann_data
    assert "anatomy_exam_test_leaderboard" in exam_ann_data

    cb_exam1 = FakeCB("admin_announce_anatomy_exam_confirm")
    await tb.cb_admin_announce_anatomy_exam_confirm(cb_exam1)
    assert cb_exam1.message.edits and "Отправить" in cb_exam1.message.edits[0][0]
    assert not exam_broadcast_calls, "must not broadcast before confirmation"

    broadcasts_before_exam = tb.stats.get("broadcast_count", 0)
    cb_exam2 = FakeCB("admin_announce_anatomy_exam_go")
    await tb.cb_admin_announce_anatomy_exam_go(cb_exam2)
    assert exam_broadcast_calls, "expected broadcast to be sent"
    assert exam_broadcast_calls[0][0] == exam_ann_text
    assert tb.stats["broadcast_count"] == broadcasts_before_exam + 1
    assert cb_exam2.message.edits and "отправлен" in cb_exam2.message.edits[0][0]

    cb_exam3 = FakeCB("admin_announce_anatomy_exam_confirm", uid=non_admin)
    await tb.cb_admin_announce_anatomy_exam_confirm(cb_exam3)
    assert not cb_exam3.message.edits, "non-admin must be blocked"

    tb._broadcast = orig_broadcast_exam
    assert "📣 Анонс Экзамена (ТЕСТ/теория/практика)" in admin_menu_texts
    print("admin Anatomy-exam-announcement broadcast + admin panel button: OK")

    # 26d. Admin announcement for the global Latin-terminology quiz: preview -> confirm -> broadcast
    orig_broadcast3 = tb._broadcast
    latin_broadcast_calls = []
    async def fake_broadcast3(text, keyboard=None):
        latin_broadcast_calls.append((text, keyboard))
    tb._broadcast = fake_broadcast3

    latin_ann_text = tb.get_anatomy_latin_announcement_text()
    check_html(latin_ann_text)
    latin_ann_kb = tb.get_anatomy_latin_announcement_keyboard()
    latin_ann_data = kb_data(latin_ann_kb)
    assert "anatomy_latin_all_start" in latin_ann_data
    assert "anatomy_latin_leaderboard" in latin_ann_data

    cb_latin1 = FakeCB("admin_announce_anatomy_latin_confirm")
    await tb.cb_admin_announce_anatomy_latin_confirm(cb_latin1)
    assert cb_latin1.message.edits and "Отправить" in cb_latin1.message.edits[0][0]
    assert not latin_broadcast_calls, "must not broadcast before confirmation"

    broadcasts_before3 = tb.stats.get("broadcast_count", 0)
    cb_latin2 = FakeCB("admin_announce_anatomy_latin_go")
    await tb.cb_admin_announce_anatomy_latin_go(cb_latin2)
    assert latin_broadcast_calls, "expected broadcast to be sent"
    assert latin_broadcast_calls[0][0] == latin_ann_text
    assert tb.stats["broadcast_count"] == broadcasts_before3 + 1
    assert cb_latin2.message.edits and "отправлен" in cb_latin2.message.edits[0][0]

    cb_latin3 = FakeCB("admin_announce_anatomy_latin_confirm", uid=non_admin)
    await tb.cb_admin_announce_anatomy_latin_confirm(cb_latin3)
    assert not cb_latin3.message.edits, "non-admin must be blocked"

    tb._broadcast = orig_broadcast3
    assert "📣 Анонс теста по латыни" in kb_texts(tb.get_admin_menu())
    print("admin Latin-quiz announcement broadcast + admin panel button: OK")

    # 27. Menu order: active tiers appear in ascending price order (menu_number), 20 first, 28 last.
    # (Checked via the keyboard's button order, not text position — the teaser paragraph at the
    # top of the message deliberately name-drops tiers 21/26 early as "top offers", so searching
    # for a tier's title anywhere in the free text isn't a reliable position check.)
    menu_text2 = tb.get_subscription_menu_text(non_admin)
    check_html(menu_text2)
    menu_kb2 = tb.get_subscription_menu_keyboard()
    order = [d for d in kb_data(menu_kb2) if d.startswith("sub_tier:")]
    assert order == [f"sub_tier:{t}" for t in range(20, 29)]
    print("'all tiers' screen lists tiers 20..28 in ascending price order: OK")

    # 28. Discount purchase flow (10% off), reachable via sub_discount:{tier} — now tiers 21/26
    for t in (21, 26):
        cfg_t = tb.SUBSCRIPTION_TIERS[t]
        expected_rub = round(cfg_t["price_rub"] * 0.9)
        assert tb.discount_price(cfg_t["price_rub"]) == expected_rub
        cb_disc = FakeCB(f"sub_discount:{t}", uid=non_admin)
        await tb.cb_sub_discount(cb_disc)
        disc_text, disc_kb = cb_disc.message.edits[-1]
        check_html(disc_text)
        assert str(expected_rub) in disc_text and str(cfg_t["price_rub"]) in disc_text
        disc_data = kb_data(disc_kb)
        assert f"buy_sub_stars_discount:{t}" in disc_data
        assert f"buy_sub_rubles_discount:{t}" in disc_data
    print("sub_discount screen shows correct 10%-off price for tiers 21 and 26: OK")

    # subject-choice tiers aren't supported by the discount flow (guarded, not silently wrong)
    cb_disc_bad = FakeCB("sub_discount:20", uid=non_admin)
    await tb.cb_sub_discount(cb_disc_bad)
    assert not cb_disc_bad.message.edits and cb_disc_bad._answers and cb_disc_bad._answers[0][1] is True
    print("sub_discount rejects subject-choice tiers: OK")

    # Stars: invoice is sent at the discounted amount
    disc_stars_uid = random.randint(10_000_000, 99_999_999)
    invoice_calls = []
    async def fake_send_invoice_disc(**kwargs):
        invoice_calls.append(kwargs)
    orig_send_invoice2 = tb.bot.send_invoice
    tb.bot.send_invoice = fake_send_invoice_disc
    cb_disc_stars = FakeCB("buy_sub_stars_discount:26", uid=disc_stars_uid)
    await tb.cb_buy_sub_stars_discount(cb_disc_stars)
    assert invoice_calls[-1]["prices"][0].amount == tb.discount_price(tb.SUBSCRIPTION_TIERS[26]["price_stars"])
    tb.bot.send_invoice = orig_send_invoice2
    print("buy_sub_stars_discount sends the invoice at 10% off: OK")

    # Rubles: admin sees the discounted price, and confirming grants at that discounted price
    disc_rub_uid = random.randint(10_000_000, 99_999_999)
    tb.stats["subscriptions"].pop(str(disc_rub_uid), None)
    disc_admin_sent = []
    async def fake_send_message_disc(chat_id, text, **kwargs):
        disc_admin_sent.append((chat_id, text, kwargs.get("reply_markup")))
    orig_send_message2 = tb.bot.send_message
    tb.bot.send_message = fake_send_message_disc
    cb_disc_rub = FakeCB("buy_sub_rubles_discount:21", uid=disc_rub_uid)
    await tb.cb_buy_sub_rubles_discount(cb_disc_rub)
    disc_rub_text, _ = cb_disc_rub.message.edits[-1]
    check_html(disc_rub_text)
    expected_disc21 = tb.discount_price(tb.SUBSCRIPTION_TIERS[21]["price_rub"])
    assert str(expected_disc21) in disc_rub_text
    admin_disc_reqs = [(c, t, k) for c, t, k in disc_admin_sent if c in tb.ADMIN_IDS]
    assert admin_disc_reqs, "admin should be notified of the discounted rubles request"
    disc_req_text = admin_disc_reqs[0][1]
    assert str(expected_disc21) in disc_req_text and "скидк" in disc_req_text.lower()
    disc_confirm_data = admin_disc_reqs[0][2].inline_keyboard[0][0].callback_data
    assert disc_confirm_data == f"admin_confirm_sub:21:{disc_rub_uid}:-:{expected_disc21}"
    disc_admin_sent.clear()
    cb_disc_confirm = FakeCB(disc_confirm_data, uid=ADMIN_ID)
    await tb.cb_admin_confirm_sub(cb_disc_confirm)
    granted = tb.get_subscription(disc_rub_uid)
    assert granted["tier"] == 21 and granted["price"] == expected_disc21
    tb.stats["subscriptions"].pop(str(disc_rub_uid), None)
    tb.bot.send_message = orig_send_message2
    print("buy_sub_rubles_discount grants the subscription at the discounted price: OK")

    # 29. Admin broadcast: 10%-off promo to users below the referral threshold (no subscription)
    promo_uid = random.randint(10_000_000, 99_999_999)
    tb.stats["total_users"].add(promo_uid)
    tb.stats["referrals"].pop(str(promo_uid), None)
    tb.stats["subscriptions"].pop(str(promo_uid), None)
    tb.stats["manual_access_granted"] = [u for u in tb.stats["manual_access_granted"] if u != promo_uid]
    tb.stats["temporary_access"].pop(str(promo_uid), None)

    cb_promo_confirm = FakeCB("admin_discount_promo_confirm", uid=ADMIN_ID)
    await tb.cb_admin_discount_promo_confirm(cb_promo_confirm)
    promo_preview, promo_preview_kb = cb_promo_confirm.message.edits[-1]
    check_html(promo_preview)
    assert "10%" in promo_preview
    assert kb_data(promo_preview_kb)[0] == "admin_discount_promo_go"

    promo_sent = []
    async def fake_send_message_promo(chat_id, text, **kwargs):
        promo_sent.append((chat_id, text, kwargs.get("reply_markup")))
    orig_send_message3 = tb.bot.send_message
    tb.bot.send_message = fake_send_message_promo
    cb_promo_go = FakeCB("admin_discount_promo_go", uid=ADMIN_ID)
    await tb.cb_admin_discount_promo_go(cb_promo_go)
    tb.bot.send_message = orig_send_message3
    promo_delivered = [(c, t, k) for c, t, k in promo_sent if c == promo_uid]
    assert promo_delivered, "user below the referral threshold should receive the discount broadcast"
    promo_text, promo_kb = promo_delivered[0][1], promo_delivered[0][2]
    check_html(promo_text)
    assert kb_data(promo_kb) == ["sub_discount:21", "sub_discount:26"]

    cb_promo_confirm_bad = FakeCB("admin_discount_promo_confirm", uid=non_admin)
    await tb.cb_admin_discount_promo_confirm(cb_promo_confirm_bad)
    assert not cb_promo_confirm_bad.message.edits, "non-admin must be blocked"
    print("admin discount-promo broadcast reaches users below the referral threshold: OK")

    # ==================== NEW SHOP: COURSE PICKER ====================
    # 30. Course picker screen: two courses + "all tiers", back to main menu
    cb_picker = FakeCB("subscription_menu", uid=non_admin)
    await tb.cb_subscription_menu(cb_picker)
    picker_text2, picker_kb2 = cb_picker.message.edits[0]
    check_html(picker_text2)
    picker_data2 = kb_data(picker_kb2)
    assert "subscription_course:year1" in picker_data2
    assert "subscription_course:year2" in picker_data2
    assert "subscription_all_tiers" in picker_data2
    assert "back_to_main" in picker_data2
    print("course picker screen renders both courses + all-tiers + back: OK")

    # 30b. First-year screen: max 4 tiers, all from FIRST_YEAR_TIER_IDS, no crash, valid HTML
    assert len(tb.FIRST_YEAR_TIER_IDS) <= 4
    cb_y1 = FakeCB("subscription_course:year1", uid=non_admin)
    await tb.cb_subscription_course(cb_y1)
    y1_text, y1_kb = cb_y1.message.edits[0]
    check_html(y1_text)
    y1_tier_ids = [d.split(":")[1] for d in kb_data(y1_kb) if d.startswith("sub_tier:")]
    assert y1_tier_ids == [str(t) for t in tb.FIRST_YEAR_TIER_IDS]
    assert "subscription_all_tiers" in kb_data(y1_kb)
    print("first-year course screen lists <=4 curated tiers: OK")

    # 30c. Second-year screen: switches from the autumn (resit) lineup to the winter lineup at
    # the NOV_1_2026_CUTOFF boundary — same cutoff tier 22 itself expires on.
    assert len(tb.SECOND_YEAR_AUTUMN_TIER_IDS) <= 4
    assert len(tb.SECOND_YEAR_WINTER_TIER_IDS) <= 4
    cb_y2 = FakeCB("subscription_course:year2", uid=non_admin)
    await tb.cb_subscription_course(cb_y2)
    y2_text, y2_kb = cb_y2.message.edits[0]
    check_html(y2_text)
    y2_tier_ids = [d.split(":")[1] for d in kb_data(y2_kb) if d.startswith("sub_tier:")]
    is_autumn = time.time() < tb.NOV_1_2026_CUTOFF
    expected_ids = tb.SECOND_YEAR_AUTUMN_TIER_IDS if is_autumn else tb.SECOND_YEAR_WINTER_TIER_IDS
    assert y2_tier_ids == [str(t) for t in expected_ids]
    print(f"second-year course screen lists the {'autumn/resit' if is_autumn else 'winter'} lineup: OK")

    orig_time_fn = tb.time.time
    tb.time.time = lambda: tb.NOV_1_2026_CUTOFF + 1
    try:
        assert tb._course_tier_ids("year2") == tb.SECOND_YEAR_WINTER_TIER_IDS
    finally:
        tb.time.time = orig_time_fn
    print("second-year lineup switches to the winter set past the October cutoff: OK")

    # 30d. Unknown course is rejected without crashing
    cb_bad_course = FakeCB("subscription_course:bogus", uid=non_admin)
    await tb.cb_subscription_course(cb_bad_course)
    assert not cb_bad_course.message.edits
    print("unknown course rejected without crashing: OK")

    # 30e. "All tiers" reachable from a course screen, still the unfiltered flat list
    cb_all = FakeCB("subscription_all_tiers", uid=non_admin)
    await tb.cb_subscription_all_tiers(cb_all)
    all_text, all_kb = cb_all.message.edits[0]
    check_html(all_text)
    all_ids = {d.split(":")[1] for d in kb_data(all_kb) if d.startswith("sub_tier:")}
    assert all_ids == {str(t) for t in ACTIVE_TIERS}
    print("'all tiers' screen (reached from course flow) still lists every active tier: OK")

    print("ALL SUBSCRIPTION TESTS PASSED")

asyncio.run(main())
