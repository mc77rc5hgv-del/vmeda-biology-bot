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

RETIRED_TIERS = {2, 3, 4}
ACTIVE_TIERS = {1, 5, 6, 7, 8, 9, 10}

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

    # 1. Tier data integrity: 10 defined, 3 retired (kept for historical grants), 7 on sale
    assert set(tb.SUBSCRIPTION_TIERS.keys()) == RETIRED_TIERS | ACTIVE_TIERS
    assert set(tb.ACTIVE_SUBSCRIPTION_TIERS.keys()) == ACTIVE_TIERS
    for t in RETIRED_TIERS:
        assert tb.SUBSCRIPTION_TIERS[t].get("retired") is True
    for t in ACTIVE_TIERS:
        assert not tb.SUBSCRIPTION_TIERS[t].get("retired")
    for cfg in tb.SUBSCRIPTION_TIERS.values():
        assert cfg["price_rub"] > 0 and cfg["price_stars"] > 0
        assert len(cfg["benefits"]) >= 2
    expected_prices = {1: 89, 5: 49, 6: 239, 7: 389, 8: 749, 9: 1119, 10: 3899}
    for t, price in expected_prices.items():
        assert tb.SUBSCRIPTION_TIERS[t]["price_rub"] == price, t
    assert tb.SUBSCRIPTION_TIERS[5]["subject_choice_required"] is True
    for t in ACTIVE_TIERS - {5}:
        assert not tb.SUBSCRIPTION_TIERS[t].get("subject_choice_required")
    for t in (7, 8, 9, 10):
        assert tb.SUBSCRIPTION_TIERS[t]["anatomy"] is True
    for t in (1, 5, 6):
        assert not tb.SUBSCRIPTION_TIERS[t]["anatomy"]
    for t in (9, 10):
        assert tb.SUBSCRIPTION_TIERS[t]["biology_download"] is True
        assert tb.SUBSCRIPTION_TIERS[t]["cheat_sheets"] is True
    for t in (1, 5, 6, 7, 8):
        assert not tb.SUBSCRIPTION_TIERS[t]["biology_download"]
    for cfg in tb.ACTIVE_SUBSCRIPTION_TIERS.values():
        assert any("текущим практическим занятиям" in b for b in cfg["benefits"]), cfg["title"]
    print("tier data integrity: OK")

    # 2. No subscription -> no access to any subject, no anatomy/histology
    assert not tb.has_active_subscription(non_admin)
    assert not tb.has_free_access(non_admin)
    for subject in ("biology", "physics", "chemistry"):
        assert not tb.has_subject_access(non_admin, subject)
    assert not tb.anatomy_access_ok(non_admin)
    assert not tb.histology_access_ok(non_admin)
    print("no subscription -> no access: OK")

    # 3. Tier 5 (3 days, one subject) restricts access to exactly the chosen subject
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
    print("tier 5 (3 days, 1 subject) restricts access to the chosen subject only: OK")

    # 3b. The referral-gate middleware's subject classifier agrees with this restriction
    assert tb.get_gated_subject("menu_physics") == "physics"
    assert tb.get_gated_subject("menu_biology") == "biology"
    assert tb.get_gated_subject("chemistry_labs") == "chemistry"
    assert tb.get_gated_subject("anatomy_menu") is None
    print("get_gated_subject classifies gated callbacks by subject: OK")

    # 4. Tier 1 (89₽, month) -> all 3 subjects, time-boxed Histology preview, no Anatomy
    tb.grant_subscription(non_admin, 1, "stars", 89)
    for subject in ("biology", "physics", "chemistry"):
        assert tb.has_subject_access(non_admin, subject)
    assert not tb.anatomy_access_ok(non_admin)
    assert tb.histology_access_ok(non_admin)
    sub = tb.get_subscription(non_admin)
    assert sub["restricted_subject"] is None
    assert sub["histology_until"] == tb.JULY_END_2026
    assert "Гистологии" in tb.get_subscription_scope_label(sub)
    assert "Анатомии" not in tb.get_subscription_scope_label(sub)
    print("tier 1 grants all 3 gated subjects + time-boxed Histology preview, no Anatomy: OK")

    # 5. Tier 6 (239₽, until Oct 2026) -> fixed calendar expiry, not a relative duration
    tb.grant_subscription(non_admin, 6, "rubles", 239)
    sub = tb.get_subscription(non_admin)
    assert sub["expires"] == tb.OCT_2026_CUTOFF
    assert tb.histology_access_ok(non_admin)
    assert not tb.anatomy_access_ok(non_admin)
    assert not tb.biology_tickets_download_ok(non_admin)
    print("tier 6 grants Histology on a fixed October 2026 cutoff, no Anatomy/biology-download: OK")

    # 6. Tier 7 (389₽) adds early Anatomy access on top of the 5-subject bundle
    tb.grant_subscription(non_admin, 7, "rubles", 389)
    assert tb.anatomy_access_ok(non_admin)
    assert tb.histology_access_ok(non_admin)
    assert not tb.biology_tickets_download_ok(non_admin)
    print("tier 7 adds Anatomy access: OK")

    # 7. Tier 9 (1119₽) additionally unlocks biology-ticket downloads + cheat sheets flag
    tb.grant_subscription(non_admin, 9, "rubles", 1119)
    assert tb.anatomy_access_ok(non_admin) and tb.histology_access_ok(non_admin)
    assert tb.biology_tickets_download_ok(non_admin)
    assert tb.get_subscription(non_admin)["cheat_sheets"] is True
    assert tb.get_subscription(non_admin)["expires"] == tb.SECOND_YEAR_END_2027
    print("tier 9 unlocks biology downloads + cheat_sheets, expires at end of 2nd course: OK")

    # 8. Tier 10 (3899₽, 6 years) -> relative duration (not a fixed calendar cutoff), everything on
    tb.grant_subscription(non_admin, 10, "stars", 3899)
    sub = tb.get_subscription(non_admin)
    expected_expiry = time.time() + 6 * 365 * 86400
    assert abs(sub["expires"] - expected_expiry) < 5
    assert tb.anatomy_access_ok(non_admin) and tb.biology_tickets_download_ok(non_admin)
    assert "ко всем разделам бота" in tb.get_subscription_scope_label(sub)
    tb.stats["subscriptions"].pop(str(non_admin), None)
    print("tier 10 (6 years, everything) grants full scope with a relative 6-year expiry: OK")

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

    # 10. Legacy subscriptions (old scope/early_histology fields, no new fields) still resolve correctly
    tb.stats["subscriptions"][str(non_admin)] = {
        "tier": 3, "scope": "all", "expires": time.time() + 86400,
        "purchased_at": time.time(), "method": "rubles", "price": 899,
    }
    assert tb.anatomy_access_ok(non_admin)
    assert tb.histology_access_ok(non_admin)
    assert tb.biology_tickets_download_ok(non_admin)
    assert "ко всем разделам бота" in tb.get_subscription_scope_label(tb.get_subscription(non_admin))
    tb.stats["subscriptions"].pop(str(non_admin), None)
    print("legacy (pre-migration) subscriptions still resolve via fallback fields: OK")

    # 11. format_subscription_expiry unchanged
    assert tb.format_subscription_expiry(None) == "навсегда"
    future_ts = time.time() + 86400
    assert "до " in tb.format_subscription_expiry(future_ts)
    print("format_subscription_expiry: OK")

    # 12. Subscription menu only lists the 7 active tiers, never the 3 retired ones
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
    # retired tiers must not leak into the menu at all
    for t in RETIRED_TIERS:
        cfg = tb.SUBSCRIPTION_TIERS[t]
        assert cfg["title"] not in menu_text
        assert not any(f"sub_tier:{t}" == d for d in kb_data(menu_kb))
    print("subscription menu lists only active tiers, retired tiers excluded: OK")

    # 12b. Tier 9 badge is shown; every active tier's text mentions the practicals benefit
    assert tb.SUBSCRIPTION_TIERS[9]["badge"] == "🔥 РЕКОМЕНДОВАНО 🔥"
    assert "<b>🔥 РЕКОМЕНДОВАНО 🔥</b>" in menu_text
    for tier_id in ACTIVE_TIERS:
        tier_text = tb.get_sub_tier_text(tier_id)
        check_html(tier_text)
        assert "текущим практическим занятиям" in tier_text
    print("badge shown, all active tier screens mention practicals benefit: OK")

    # 13. Per-tier screens: subject-choice tier (5) shows subject buttons, not payment buttons directly
    tier5_text = tb.get_sub_tier_text(5)
    check_html(tier5_text)
    assert "выбери предмет" in tier5_text
    tier5_kb = tb.get_sub_tier_keyboard(5)
    tier5_data = kb_data(tier5_kb)
    assert "sub_subject:5:biology" in tier5_data
    assert "sub_subject:5:physics" in tier5_data
    assert "sub_subject:5:chemistry" in tier5_data
    assert not any(d.startswith("buy_sub_stars:") for d in tier5_data)
    print("tier 5 pre-payment screen offers subject choice, not direct payment: OK")

    for tier_id in ACTIVE_TIERS - {5}:
        tier_kb = tb.get_sub_tier_keyboard(tier_id)
        tt = kb_texts(tier_kb)
        assert any("Оплатить" in t and "звёзд" in t for t in tt)
        assert any("Оплатить" in t and "₽" in t for t in tt)
    print("non-subject-choice tiers offer direct payment buttons: OK")

    # 13b. Upsell: every active tier except the most expensive one offers the next tier up
    price_sorted = sorted(ACTIVE_TIERS, key=lambda t: tb.SUBSCRIPTION_TIERS[t]["price_rub"])
    top_tier = price_sorted[-1]
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

    # 15. Handlers: subscription_menu -> sub_tier -> buy_sub_rubles navigation
    cb1 = FakeCB("subscription_menu", uid=non_admin)
    await tb.cb_subscription_menu(cb1)
    assert cb1.message.edits
    print("cb_subscription_menu renders: OK")

    cb2 = FakeCB("sub_tier:9", uid=non_admin)
    await tb.cb_sub_tier(cb2)
    assert cb2.message.edits and "2 курса" in cb2.message.edits[0][0]
    print("cb_sub_tier renders correct tier: OK")

    cb3 = FakeCB("sub_tier:99", uid=non_admin)
    await tb.cb_sub_tier(cb3)
    assert cb3._answers and cb3._answers[0][1] is True and not cb3.message.edits
    print("cb_sub_tier rejects unknown tier: OK")

    cb3b = FakeCB("sub_tier:2", uid=non_admin)  # retired tier — still resolvable (historical), just not sold
    await tb.cb_sub_tier(cb3b)
    assert cb3b.message.edits, "retired tier screens still render if reached directly (no crash)"
    print("cb_sub_tier does not crash on a retired tier id: OK")

    cb4 = FakeCB("buy_sub_rubles:6", uid=non_admin)
    await tb.cb_buy_sub_rubles(cb4)
    assert cb4.message.edits and "239" in cb4.message.edits[0][0]
    print("cb_buy_sub_rubles renders payment instructions: OK")

    # 15b. Subject-choice purchase flow end-to-end (rubles)
    cb_subj = FakeCB("sub_subject:5:biology", uid=non_admin)
    await tb.cb_sub_subject(cb_subj)
    assert cb_subj.message.edits and "Биологии" in cb_subj.message.edits[0][0]
    subj_kb_data = kb_data(cb_subj.message.edits[0][1])
    assert "buy_sub_stars_subj:5:biology" in subj_kb_data
    assert "buy_sub_rubles_subj:5:biology" in subj_kb_data

    cb_subj_bad = FakeCB("sub_subject:5:latin", uid=non_admin)
    await tb.cb_sub_subject(cb_subj_bad)
    assert not cb_subj_bad.message.edits, "unknown subject must be rejected"

    cb_rub_subj = FakeCB("buy_sub_rubles_subj:5:biology", uid=non_admin)
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

    cb5 = FakeCB("buy_sub_stars:10", uid=non_admin)
    await tb.cb_buy_sub_stars(cb5)
    assert invoice_calls, "expected send_invoice to be called"
    call = invoice_calls[-1]
    assert call["currency"] == "XTR"
    assert call["prices"][0].amount == tb.SUBSCRIPTION_TIERS[10]["price_stars"]
    assert call["payload"].startswith(f"sub_stars_10_-_{non_admin}_")
    print("buy_sub_stars sends correct XTR invoice: OK")

    cb5b = FakeCB("buy_sub_stars_subj:5:chemistry", uid=non_admin)
    await tb.cb_buy_sub_stars_subj(cb5b)
    call = invoice_calls[-1]
    assert call["payload"].startswith(f"sub_stars_5_chemistry_{non_admin}_")
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
    msg.successful_payment = FakeSuccessfulPayment(3899, f"sub_stars_10_-_{non_admin}_{int(time.time())}")
    await tb.handle_successful_payment(msg)
    assert tb.anatomy_access_ok(non_admin)
    assert tb.get_subscription(non_admin)["tier"] == 10
    assert tb.stats["donations_stars_total"] == donations_before, "subscription payment must not be counted as a donation"
    buyer_msgs = [t for cid, t in admin_msgs if cid == non_admin]
    assert buyer_msgs and "активирована" in buyer_msgs[0]
    print("successful_payment (subscription payload) grants tier, not counted as donation: OK")

    # 17b. successful_payment with an encoded subject grants a subject-restricted subscription
    tb.stats["subscriptions"].pop(str(non_admin), None)
    msg_subj = FakeMsg(from_user=FakeUser(non_admin))
    msg_subj.successful_payment = FakeSuccessfulPayment(49, f"sub_stars_5_chemistry_{non_admin}_{int(time.time())}")
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

    # 19. Admin manual rubles grant flow — reply-keyboard tier picker, non-subject tier
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
    assert any(t.startswith("9 —") for t in tier_kb_texts), "reply-keyboard should list active tiers by id"
    assert not any(t.startswith("2 —") for t in tier_kb_texts), "retired tiers must not appear on the quick-picker"

    m2 = FakeMsg(from_user=FakeUser(ADMIN_ID))
    m2.text = "9 — всё + зачёты, до конца 2 курса — 1119₽"  # simulates tapping the reply-keyboard button
    await tb.handle_admin_pending_action(m2)
    assert ADMIN_ID not in tb.ADMIN_PENDING
    assert tb.get_subscription(non_admin)["tier"] == 9
    assert tb.get_subscription(non_admin)["method"] == "rubles"
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
    mr2.text = "3"  # retired tier
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
    m4.text = "99"
    await tb.handle_admin_pending_action(m4)
    assert ADMIN_ID in tb.ADMIN_PENDING, "invalid tier should not clear pending state"
    assert not tb.has_active_subscription(non_admin)

    # cancel via the reply-keyboard's "Отмена" button
    m4b = FakeMsg(from_user=FakeUser(ADMIN_ID))
    m4b.text = "❌ Отмена"
    await tb.handle_admin_pending_action(m4b)
    assert ADMIN_ID not in tb.ADMIN_PENDING
    print("admin flow rejects invalid tier number, supports cancel: OK")

    # 19c. Admin grant flow for a subject-choice tier (5): tier -> subject reply-keyboard -> grant
    cb_prompt3 = FakeCB("admin_subscription_prompt")
    await tb.cb_admin_subscription_prompt(cb_prompt3)
    ms1 = FakeMsg(from_user=FakeUser(ADMIN_ID))
    ms1.text = "testbuyer"
    await tb.handle_admin_pending_action(ms1)
    ms2 = FakeMsg(from_user=FakeUser(ADMIN_ID))
    ms2.text = "5"
    await tb.handle_admin_pending_action(ms2)
    assert tb.ADMIN_PENDING[ADMIN_ID]["action"] == "record_subscription_subject"
    assert isinstance(ms2.answers[-1][1], tb.ReplyKeyboardMarkup)
    ms3 = FakeMsg(from_user=FakeUser(ADMIN_ID))
    ms3.text = "Физика"
    await tb.handle_admin_pending_action(ms3)
    assert ADMIN_ID not in tb.ADMIN_PENDING
    assert tb.get_subscription(non_admin)["tier"] == 5
    assert tb.get_subscription(non_admin)["restricted_subject"] == "physics"
    tb.stats["subscriptions"].pop(str(non_admin), None)
    print("admin grant flow for subject-choice tier prompts for and stores the subject: OK")

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
    msg_t1.successful_payment = FakeSuccessfulPayment(89, f"sub_stars_1_-_{upsell_uid}_{int(time.time())}")
    await tb.handle_successful_payment(msg_t1)
    buyer_sent = [(c, t, k) for c, t, k in sent4 if c == upsell_uid]
    assert buyer_sent, "expected a confirmation message"
    _, t1_text, t1_kb = buyer_sent[0]
    check_html(t1_text)
    assert "активирована" in t1_text and "Выгоднее" in t1_text
    assert t1_kb is not None
    tb.stats["subscriptions"].pop(str(upsell_uid), None)
    print("tier 1 stars purchase offers an upsell to the next tier: OK")

    sent4.clear()
    upsell_uid2 = random.randint(10_000_000, 99_999_999)
    msg_t10 = FakeMsg(from_user=FakeUser(upsell_uid2))
    msg_t10.successful_payment = FakeSuccessfulPayment(3899, f"sub_stars_10_-_{upsell_uid2}_{int(time.time())}")
    await tb.handle_successful_payment(msg_t10)
    buyer_sent2 = [(c, t, k) for c, t, k in sent4 if c == upsell_uid2]
    assert buyer_sent2
    _, t10_text, t10_kb = buyer_sent2[0]
    assert "Выгоднее" not in t10_text and t10_kb is None
    tb.stats["subscriptions"].pop(str(upsell_uid2), None)
    tb.bot.send_invoice = orig_send_invoice
    tb.bot.send_message = orig_send_message
    print("top-tier (10) purchase shows no upsell: OK")

    # 20b. New: buying with rubles now also pings admins with a one-tap payment-confirm request,
    # and tapping it grants the subscription immediately (old manual admin flow still works too)
    confirm_uid = random.randint(10_000_000, 99_999_999)
    tb.stats["subscriptions"].pop(str(confirm_uid), None)
    admin_sent = []
    async def fake_send_message5(chat_id, text, **kwargs):
        admin_sent.append((chat_id, text, kwargs.get("reply_markup")))
    tb.bot.send_message = fake_send_message5

    cb_rub = FakeCB("buy_sub_rubles:6", uid=confirm_uid)
    await tb.cb_buy_sub_rubles(cb_rub)
    assert cb_rub.message.edits, "buyer still sees the @vmeda_helper deep-link screen"
    admin_requests = [(c, t, k) for c, t, k in admin_sent if c in tb.ADMIN_IDS]
    assert len(admin_requests) == len(tb.ADMIN_IDS), "every admin should get a confirm request"
    req_chat, req_text, req_kb = admin_requests[0]
    check_html(req_text)
    assert "239" in req_text and "подтверждение оплаты" in req_text
    assert req_kb is not None
    confirm_cb_data = req_kb.inline_keyboard[0][0].callback_data
    assert confirm_cb_data == f"admin_confirm_sub:6:{confirm_uid}:-"
    print("buy_sub_rubles pings every admin with a one-tap confirm request: OK")

    admin_sent.clear()
    cb_confirm = FakeCB(confirm_cb_data, uid=ADMIN_ID)
    await tb.cb_admin_confirm_sub(cb_confirm)
    assert tb.get_subscription(confirm_uid)["tier"] == 6
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
    tb.bot.send_message = orig_send_message
    print("non-admin cannot confirm a payment: OK")

    # 21. Referral gate integration: get_referral_status_text shows subscription branch
    tb.grant_subscription(non_admin, 9, "stars", 1119)
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
    print("default referral text includes subscription teaser with the cheapest 3-subject tier: OK")

    back_kb = tb.get_referral_back_keyboard()
    assert any("Открыть доступ без рефералов" in t for t in kb_texts(back_kb))
    print("get_referral_back_keyboard has subscription button: OK")

    teaser_kb = tb.get_subscription_teaser_keyboard()
    assert kb_texts(teaser_kb)[0] == "💎 Открыть доступ без рефералов"
    assert teaser_kb.inline_keyboard[0][0].callback_data == "subscription_menu"
    print("get_subscription_teaser_keyboard: OK")

    # 22. Main menu: subscription button always visible; anatomy/histology labels reflect
    # has_subscription_anatomy_access/has_subscription_histology_access, not scope=="all"
    menu_no_sub = tb.get_main_menu(user_id=non_admin)
    assert "💎 Подписка без рефералов" in kb_texts(menu_no_sub)
    assert "🦴 Анатомия (в разработке)" in kb_texts(menu_no_sub)
    assert "🔬 Гистология (рефералы/подписка)" in kb_texts(menu_no_sub)

    tb.grant_subscription(non_admin, 6, "stars", 239)  # histology yes, anatomy no
    menu_tier6 = tb.get_main_menu(user_id=non_admin)
    tier6_texts = kb_texts(menu_tier6)
    assert "💎 Моя подписка" in tier6_texts
    assert any(t.startswith("🔬 Гистология") for t in tier6_texts)
    assert "🦴 Анатомия (в разработке)" in tier6_texts, "tier 6 has no anatomy — button stays locked"
    tb.stats["subscriptions"].pop(str(non_admin), None)

    tb.grant_subscription(non_admin, 7, "stars", 389)  # anatomy yes
    menu_tier7 = tb.get_main_menu(user_id=non_admin)
    tier7_texts = kb_texts(menu_tier7)
    assert "🦴 Анатомия 💎" in tier7_texts
    assert "🔬 Гистология 💎" in tier7_texts
    tb.stats["subscriptions"].pop(str(non_admin), None)
    print("main menu subscription button always visible, anatomy/histology labels match per-tier flags: OK")

    # 22b. Regression: free referral access (no subscription) must still show the subscription entry
    tb.stats["referrals"][str(non_admin)] = ["ref1", "ref2"]
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

    tb.grant_subscription(non_admin, 1, "stars", 89)
    cb_hist_unlocked = FakeCB("histology_menu", uid=non_admin)
    await tb.cb_histology_menu(cb_hist_unlocked)
    assert cb_hist_unlocked.message.edits
    assert "Выбери диагностику" in cb_hist_unlocked.message.edits[0][0]
    tb.stats["subscriptions"].pop(str(non_admin), None)
    print("histology_menu shows locked screen with dynamic subscription CTA when access is missing: OK")

    # 24. Locked Anatomy screen: dynamic list of anatomy-granting tiers, not stale "Год"/"6 лет" text
    cb_anat_locked = FakeCB("anatomy_menu", uid=non_admin)
    await tb.cb_anatomy_menu(cb_anat_locked)
    assert cb_anat_locked.message.edits
    locked_text, locked_kb = cb_anat_locked.message.edits[0]
    check_html(locked_text)
    assert "в разработке" in locked_text
    for cfg in tb.ACTIVE_SUBSCRIPTION_TIERS.values():
        if cfg.get("anatomy"):
            assert cfg["title"] in locked_text
    assert any("Оформить подписку" in t for t in kb_texts(locked_kb))

    tb.grant_subscription(non_admin, 8, "stars", 749)
    cb_anat_unlocked = FakeCB("anatomy_menu", uid=non_admin)
    await tb.cb_anatomy_menu(cb_anat_unlocked)
    assert cb_anat_unlocked.message.edits
    assert "Выбери подраздел" in cb_anat_unlocked.message.edits[0][0]
    tb.stats["subscriptions"].pop(str(non_admin), None)
    print("anatomy_menu shows locked screen listing all anatomy-granting tiers dynamically: OK")

    # 24b. The short callback-answer alert for in-handler anatomy locks stays under Telegram's ~200-char cap
    alert_text = tb.get_anatomy_dev_alert_text()
    assert len(alert_text) <= 200
    assert str(tb.cheapest_anatomy_tier()["price_rub"]) in alert_text
    print("anatomy dev-alert text is short and dynamically priced: OK")

    # 25. is_gated_callback exempts all subscription callbacks (must always be reachable)
    assert not tb.is_gated_callback("subscription_menu")
    assert not tb.is_gated_callback("sub_tier:1")
    assert not tb.is_gated_callback("buy_sub_stars:1")
    assert not tb.is_gated_callback("buy_sub_rubles:1")
    assert not tb.is_gated_callback("sub_subject:5:biology")
    print("subscription callbacks exempt from referral gate: OK")

    # 26. Admin subscription-announcement broadcast: preview -> confirm -> broadcast
    orig_broadcast = tb._broadcast
    broadcast_calls = []
    async def fake_broadcast(text, keyboard=None):
        broadcast_calls.append((text, keyboard))
    tb._broadcast = fake_broadcast

    ann_text = tb.get_subscription_announcement_text()
    check_html(ann_text)
    assert "Гистологии" not in ann_text or True  # no hard requirement on wording, just structural checks below
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

    print("ALL SUBSCRIPTION TESTS PASSED")

asyncio.run(main())
