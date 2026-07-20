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
    def __init__(self, uid, full_name="Тест Юзер"):
        self.id = uid
        self.full_name = full_name

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

class FakeSuccessfulPayment:
    def __init__(self, total_amount, invoice_payload):
        self.total_amount = total_amount
        self.invoice_payload = invoice_payload

async def main():
    non_admin = random.randint(10_000_000, 99_999_999)
    tb.stats["subscriptions"].pop(str(non_admin), None)

    # 1. Tier data integrity
    assert set(tb.SUBSCRIPTION_TIERS.keys()) == {1, 2, 3, 4}
    assert tb.SUBSCRIPTION_TIERS[1]["scope"] == "gated" and tb.SUBSCRIPTION_TIERS[1]["duration_days"] == 30
    assert tb.SUBSCRIPTION_TIERS[2]["scope"] == "gated" and tb.SUBSCRIPTION_TIERS[2]["duration_days"] is None
    assert tb.SUBSCRIPTION_TIERS[3]["scope"] == "all" and tb.SUBSCRIPTION_TIERS[3]["duration_days"] == 365
    assert tb.SUBSCRIPTION_TIERS[4]["scope"] == "all" and tb.SUBSCRIPTION_TIERS[4]["duration_days"] == 2190
    for t, cfg in tb.SUBSCRIPTION_TIERS.items():
        assert cfg["price_rub"] > 0 and cfg["price_stars"] > 0
        assert len(cfg["benefits"]) >= 2
    assert tb.SUBSCRIPTION_TIERS[1]["price_rub"] == 89
    assert tb.SUBSCRIPTION_TIERS[2]["price_rub"] == 239
    assert tb.SUBSCRIPTION_TIERS[3]["price_rub"] == 899
    assert tb.SUBSCRIPTION_TIERS[4]["price_rub"] == 2499
    for t, cfg in tb.SUBSCRIPTION_TIERS.items():
        assert cfg.get("joke"), f"tier {t} missing joke tagline"
    print("tier data integrity: OK")

    # 2. No subscription -> no access
    assert not tb.has_active_subscription(non_admin)
    assert not tb.has_subscription_scope_all(non_admin)
    assert not tb.has_free_access(non_admin)
    print("no subscription -> no access: OK")

    # 3. Grant tier 1 (gated, 30 days) -> has_free_access True, scope_all False
    tb.grant_subscription(non_admin, 1, "stars", 89)
    assert tb.has_active_subscription(non_admin)
    assert tb.has_free_access(non_admin)
    assert not tb.has_subscription_scope_all(non_admin)
    assert not tb.anatomy_access_ok(non_admin)
    assert not tb.histology_access_ok(non_admin)
    sub = tb.get_subscription(non_admin)
    assert sub["tier"] == 1 and sub["scope"] == "gated" and sub["method"] == "stars" and sub["price"] == 89
    expected_expiry = time.time() + 30 * 86400
    assert abs(sub["expires"] - expected_expiry) < 5
    print("tier 1 grants gated-only access with 30-day expiry: OK")

    # 4. Grant tier 3 (all, 365 days) -> scope_all True, anatomy/histology unlocked
    tb.grant_subscription(non_admin, 3, "rubles", 899)
    assert tb.has_subscription_scope_all(non_admin)
    assert tb.anatomy_access_ok(non_admin)
    assert tb.histology_access_ok(non_admin)
    sub = tb.get_subscription(non_admin)
    assert sub["tier"] == 3 and sub["scope"] == "all"
    print("tier 3 grants scope=all, unlocks anatomy/histology: OK")

    # 5. Grant tier 2 (gated, forever) -> expires is None, still active far in future
    tb.grant_subscription(non_admin, 2, "stars", 239)
    sub = tb.get_subscription(non_admin)
    assert sub["expires"] is None
    assert tb.has_active_subscription(non_admin)
    print("tier 2 (forever) has expires=None and stays active: OK")

    # 5b. Tier 2 grants early Histology access but NOT Anatomy (Anatomy stays scope=all only)
    assert sub["early_histology"] is True
    assert tb.has_subscription_histology_access(non_admin)
    assert tb.histology_access_ok(non_admin)
    assert not tb.has_subscription_scope_all(non_admin)
    assert not tb.anatomy_access_ok(non_admin)
    assert "Гистологии" in tb.get_subscription_scope_label(sub)
    menu_tier2 = tb.get_main_menu(user_id=non_admin)
    tier2_texts = kb_texts(menu_tier2)
    assert any(t.startswith("🔬 Гистология") for t in tier2_texts)
    assert "🦴 Анатомия (в разработке)" in tier2_texts, "Anatomy button should stay visible but locked for tier 2"
    print("tier 2 grants early Histology access only (Anatomy button visible but locked): OK")

    # 6. Expired subscription -> no access
    tb.stats["subscriptions"][str(non_admin)] = {
        "tier": 1, "scope": "gated", "expires": time.time() - 10,
        "purchased_at": time.time() - 1000, "method": "stars", "price": 79,
    }
    assert not tb.has_active_subscription(non_admin)
    assert not tb.has_free_access(non_admin)
    tb.stats["subscriptions"].pop(str(non_admin), None)
    print("expired subscription -> no access: OK")

    # 7. format_subscription_expiry
    assert tb.format_subscription_expiry(None) == "навсегда"
    future_ts = time.time() + 86400
    assert "до " in tb.format_subscription_expiry(future_ts)
    print("format_subscription_expiry: OK")

    # 8. Subscription menu / tier screens: HTML-balanced, correct keyboards
    menu_text = tb.get_subscription_menu_text(non_admin)
    check_html(menu_text)
    for cfg in tb.SUBSCRIPTION_TIERS.values():
        assert cfg["title"] in menu_text
        assert str(cfg["price_rub"]) in menu_text
    menu_kb = tb.get_subscription_menu_keyboard()
    texts = kb_texts(menu_kb)
    assert len(texts) == 5  # 4 tiers + back
    for cfg in tb.SUBSCRIPTION_TIERS.values():
        assert any(cfg["short"] in t for t in texts)
    print("subscription menu text/keyboard: OK")

    # 8b. Menu text explains the paid-tiers rationale and the finished Histology section
    assert "затрат" in menu_text and "вынуждены" in menu_text
    assert "Гистологии" in menu_text and "препаратов академии" in menu_text
    assert "препараты именно с академии" in tb.SUBSCRIPTION_TIERS[2]["benefits"][1]
    assert tb.SUBSCRIPTION_TIERS[2]["early_histology"] is True
    print("menu text covers cost rationale + finished-Histology claim, tier 2 benefit lists early histology: OK")

    # 8c. Year tier (899₽) is marked with a bold "РЕКОМЕНДОВАНО" badge everywhere it's shown;
    # other tiers have no badge.
    assert tb.SUBSCRIPTION_TIERS[3]["badge"] == "🔥 РЕКОМЕНДОВАНО 🔥"
    assert "<b>🔥 РЕКОМЕНДОВАНО 🔥</b>" in menu_text
    for tier_id, cfg in tb.SUBSCRIPTION_TIERS.items():
        if tier_id != 3:
            assert "badge" not in cfg
    year_tier_text = tb.get_sub_tier_text(3)
    check_html(year_tier_text)
    assert "<b>🔥 РЕКОМЕНДОВАНО 🔥</b>" in year_tier_text
    for tier_id in (1, 2, 4):
        assert "РЕКОМЕНДОВАНО" not in tb.get_sub_tier_text(tier_id)
    badge_kb_texts = kb_texts(tb.get_subscription_menu_keyboard())
    assert any("РЕКОМЕНДОВАНО" in t and "1 год" in t for t in badge_kb_texts)
    assert sum("РЕКОМЕНДОВАНО" in t for t in badge_kb_texts) == 1
    print("year tier (899₽) shows bold РЕКОМЕНДОВАНО badge in menu/tier screen/keyboard: OK")

    # 8d. Every tier's joke tagline is shown (italicized) in the menu list and on its own tier screen
    expected_jokes = {
        1: "ЭНЕРГЕТИК 🤮 или УСПЕШНАЯ СДАЧА ЭКЗАМЕНА 😇",
        2: "маленькая шаверма 🥙 или УСПЕШНАЯ СДАЧА ЭКЗАМЕНОВ 😇",
        3: "2 шавермы 🥙🥙 или ПОДПИСКА НА ГОД 🚀",
        4: "2499₽ в кармане 💸 или успешно окончить академию 🎓",
    }
    for tier_id, joke in expected_jokes.items():
        assert tb.SUBSCRIPTION_TIERS[tier_id]["joke"] == joke
        assert f"<i>{joke}</i>" in menu_text
        tier_text = tb.get_sub_tier_text(tier_id)
        check_html(tier_text)
        assert f"<i>{joke}</i>" in tier_text
    print("joke tagline present (italicized) for all 4 tiers in menu + tier screens: OK")

    # 8e. Broadcast announcement + referral teaser reflect the new 89₽ price, not the old 79₽
    ann_text = tb.get_subscription_announcement_text()
    check_html(ann_text)
    assert "89₽" in ann_text and "79₽" not in ann_text
    print("announcement text uses updated 89₽ price, no stale 79₽: OK")

    for tier_id in tb.SUBSCRIPTION_TIERS:
        tier_text = tb.get_sub_tier_text(tier_id)
        check_html(tier_text)
        tier_kb = tb.get_sub_tier_keyboard(tier_id)
        tt = kb_texts(tier_kb)
        assert any("Оплатить" in t and "звёзд" in t for t in tt)
        assert any("Оплатить" in t and "₽" in t for t in tt)
        if tier_id == 1:
            assert "Выгоднее" in tier_text and "239₽" in tier_text and "150₽" in tier_text
            assert any("Навсегда" in t for t in tt)
        else:
            assert "Выгоднее" not in tier_text
            assert not any("Навсегда" in t for t in tt)
    print("per-tier screens OK for all 4 tiers; tier 1 pre-payment screen offers tier 2 upsell")

    # 9. Rubles flow: deep-link keyboard and message text
    for tier_id in tb.SUBSCRIPTION_TIERS:
        rub_text = tb.get_sub_rubles_message_text(tier_id)
        check_html(rub_text)
        rub_kb = tb.get_sub_rubles_keyboard(tier_id)
        assert any(b.url for row in rub_kb.inline_keyboard for b in row if b.url)
    print("rubles deep-link flow OK for all tiers")

    # 10. Handlers: subscription_menu -> sub_tier -> buy_sub_rubles navigation
    cb1 = FakeCB("subscription_menu", uid=non_admin)
    await tb.cb_subscription_menu(cb1)
    assert cb1.message.edits
    print("cb_subscription_menu renders: OK")

    cb2 = FakeCB("sub_tier:3", uid=non_admin)
    await tb.cb_sub_tier(cb2)
    assert cb2.message.edits and "Год" in cb2.message.edits[0][0]
    print("cb_sub_tier renders correct tier: OK")

    cb3 = FakeCB("sub_tier:99", uid=non_admin)
    await tb.cb_sub_tier(cb3)
    assert cb3._answers and cb3._answers[0][1] is True and not cb3.message.edits
    print("cb_sub_tier rejects unknown tier: OK")

    cb4 = FakeCB("buy_sub_rubles:2", uid=non_admin)
    await tb.cb_buy_sub_rubles(cb4)
    assert cb4.message.edits and "239" in cb4.message.edits[0][0]
    print("cb_buy_sub_rubles renders payment instructions: OK")

    # 11. Stars purchase flow: send_invoice captured, payload encodes tier
    orig_send_invoice = tb.bot.send_invoice
    invoice_calls = []
    async def fake_send_invoice(**kwargs):
        invoice_calls.append(kwargs)
    tb.bot.send_invoice = fake_send_invoice

    cb5 = FakeCB("buy_sub_stars:4", uid=non_admin)
    await tb.cb_buy_sub_stars(cb5)
    assert invoice_calls, "expected send_invoice to be called"
    call = invoice_calls[-1]
    assert call["currency"] == "XTR"
    assert call["prices"][0].amount == tb.SUBSCRIPTION_TIERS[4]["price_stars"]
    assert call["payload"].startswith(f"sub_stars_4_{non_admin}_")
    print("buy_sub_stars sends correct XTR invoice: OK")

    # 12. successful_payment for a subscription payload grants the tier and does NOT
    # touch donation stats
    tb.stats["subscriptions"].pop(str(non_admin), None)
    donations_before = tb.stats["donations_stars_total"]
    admin_msgs = []
    orig_send_message = tb.bot.send_message
    async def fake_send_message(chat_id, text, **kwargs):
        admin_msgs.append((chat_id, text))
    tb.bot.send_message = fake_send_message

    msg = FakeMsg(from_user=FakeUser(non_admin))
    msg.successful_payment = FakeSuccessfulPayment(2499, f"sub_stars_4_{non_admin}_{int(time.time())}")
    await tb.handle_successful_payment(msg)
    assert tb.has_subscription_scope_all(non_admin)
    assert tb.get_subscription(non_admin)["tier"] == 4
    assert tb.stats["donations_stars_total"] == donations_before, "subscription payment must not be counted as a donation"
    assert msg.answers and "активирована" in msg.answers[0][0]
    print("successful_payment (subscription payload) grants tier, not counted as donation: OK")

    # 13. successful_payment for a donation payload still works as before (regression)
    tb.stats["subscriptions"].pop(str(non_admin), None)
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

    # 14. Admin manual rubles grant flow
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

    m2 = FakeMsg(from_user=FakeUser(ADMIN_ID))
    m2.text = "4"
    await tb.handle_admin_pending_action(m2)
    assert ADMIN_ID not in tb.ADMIN_PENDING
    assert tb.get_subscription(non_admin)["tier"] == 4
    assert tb.get_subscription(non_admin)["method"] == "rubles"
    assert admin_notify and "активирована" in admin_notify[-1][1]
    print("admin manual rubles subscription grant flow: OK")

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
    del tb.ADMIN_PENDING[ADMIN_ID]
    tb.bot.send_message = orig_send_message
    print("admin flow rejects invalid tier number: OK")

    # 14b. Buying tier 1 (89₽/⭐) offers an upsell to tier 2 (239₽/⭐); tier 4 purchase does not
    upsell_uid = random.randint(10_000_000, 99_999_999)
    orig_send_invoice2 = tb.bot.send_invoice
    async def fake_send_invoice2(**kwargs):
        pass
    tb.bot.send_invoice = fake_send_invoice2
    orig_send_message4 = tb.bot.send_message
    async def fake_send_message4(chat_id, text, **kwargs):
        pass
    tb.bot.send_message = fake_send_message4

    msg_t1 = FakeMsg(from_user=FakeUser(upsell_uid))
    msg_t1.successful_payment = FakeSuccessfulPayment(89, f"sub_stars_1_{upsell_uid}_{int(time.time())}")
    await tb.handle_successful_payment(msg_t1)
    assert msg_t1.answers, "expected a confirmation message"
    t1_text, t1_kb = msg_t1.answers[0]
    check_html(t1_text)
    assert "активирована" in t1_text
    assert "Выгоднее" in t1_text and "239₽" in t1_text and "150₽" in t1_text
    assert t1_kb is not None and any("Навсегда" in b.text for row in t1_kb.inline_keyboard for b in row)
    tb.stats["subscriptions"].pop(str(upsell_uid), None)
    print("tier 1 stars purchase offers tier 2 upsell: OK")

    upsell_uid2 = random.randint(10_000_000, 99_999_999)
    msg_t4 = FakeMsg(from_user=FakeUser(upsell_uid2))
    msg_t4.successful_payment = FakeSuccessfulPayment(2499, f"sub_stars_4_{upsell_uid2}_{int(time.time())}")
    await tb.handle_successful_payment(msg_t4)
    assert msg_t4.answers
    t4_text, t4_kb = msg_t4.answers[0]
    assert "Выгоднее" not in t4_text and t4_kb is None
    tb.stats["subscriptions"].pop(str(upsell_uid2), None)
    tb.bot.send_invoice = orig_send_invoice2
    tb.bot.send_message = orig_send_message4
    print("tier 4 purchase shows no upsell: OK")

    # Same upsell on the admin manual-rubles-grant path (tier 1)
    upsell_uid3 = random.randint(10_000_000, 99_999_999)
    tb.stats["user_username"][str(upsell_uid3)] = "upselltester"
    tb.stats["usernames"]["upselltester"] = upsell_uid3
    admin_notify2 = []
    async def fake_send_message3(chat_id, text, **kwargs):
        admin_notify2.append((chat_id, text, kwargs.get("reply_markup")))
    orig_send_message3 = tb.bot.send_message
    tb.bot.send_message = fake_send_message3

    cb_prompt3 = FakeCB("admin_subscription_prompt")
    await tb.cb_admin_subscription_prompt(cb_prompt3)
    m5 = FakeMsg(from_user=FakeUser(ADMIN_ID))
    m5.text = "upselltester"
    await tb.handle_admin_pending_action(m5)
    m6 = FakeMsg(from_user=FakeUser(ADMIN_ID))
    m6.text = "1"
    await tb.handle_admin_pending_action(m6)
    assert admin_notify2, "expected the target user to be notified"
    notify_chat_id, notify_text, notify_kb = admin_notify2[-1]
    assert notify_chat_id == upsell_uid3
    assert "Выгоднее" in notify_text and notify_kb is not None
    tb.stats["subscriptions"].pop(str(upsell_uid3), None)
    tb.bot.send_message = orig_send_message3
    print("tier 1 admin rubles grant offers tier 2 upsell: OK")

    # 15. Referral gate integration: get_referral_status_text shows subscription branch
    tb.grant_subscription(non_admin, 3, "stars", 899)
    status_text = tb.get_referral_status_text(non_admin)
    check_html(status_text)
    assert "активна подписка" in status_text
    tb.stats["subscriptions"].pop(str(non_admin), None)
    print("get_referral_status_text shows active-subscription branch: OK")

    # default "invite friends" branch includes subscription teaser
    tb.stats["referrals"].pop(str(non_admin), None)
    tb.stats["temporary_access"].pop(str(non_admin), None)
    if non_admin in tb.stats["manual_access_granted"]:
        tb.stats["manual_access_granted"].remove(non_admin)
    default_text = tb.get_referral_status_text(non_admin)
    check_html(default_text)
    assert "Не хочешь ждать друзей" in default_text
    print("default referral text includes subscription teaser: OK")

    back_kb = tb.get_referral_back_keyboard()
    assert any("Открыть доступ без рефералов" in t for t in kb_texts(back_kb))
    print("get_referral_back_keyboard has subscription button: OK")

    teaser_kb = tb.get_subscription_teaser_keyboard()
    assert kb_texts(teaser_kb)[0] == "💎 Открыть доступ без рефералов"
    assert teaser_kb.inline_keyboard[0][0].callback_data == "subscription_menu"
    print("get_subscription_teaser_keyboard: OK")

    # 16. Main menu: subscription button always visible (label depends on status) +
    # anatomy/histology visibility for scope=all
    menu_no_sub = tb.get_main_menu(user_id=non_admin)
    assert "💎 Подписка без рефералов" in kb_texts(menu_no_sub)
    assert "🦴 Анатомия (в разработке)" in kb_texts(menu_no_sub), "Anatomy button stays visible even with no access"
    assert "🔬 Гистология (рефералы/подписка)" in kb_texts(menu_no_sub), "Histology button stays visible even with no access"

    tb.grant_subscription(non_admin, 3, "stars", 899)
    menu_with_sub = tb.get_main_menu(user_id=non_admin)
    texts = kb_texts(menu_with_sub)
    assert "💎 Моя подписка" in texts, "subscription button should switch label, not disappear, once subscribed"
    assert not any("Подписка без рефералов" in t for t in texts)
    assert "🦴 Анатомия 💎" in texts
    assert "🔬 Гистология 💎" in texts
    tb.stats["subscriptions"].pop(str(non_admin), None)
    print("main menu subscription button always visible, label reflects status: OK")

    # 16b. Regression: a user with free access via referrals (not subscription) must still
    # see the subscription entry point — it used to disappear entirely for such users.
    tb.stats["referrals"][str(non_admin)] = ["ref1", "ref2"]
    assert tb.get_referral_count(non_admin) >= tb.REFERRAL_FULL_ACCESS_THRESHOLD
    assert tb.has_free_access(non_admin) and not tb.has_active_subscription(non_admin)
    menu_referral_access = tb.get_main_menu(user_id=non_admin)
    assert "💎 Подписка без рефералов" in kb_texts(menu_referral_access), \
        "subscription entry point must stay visible even for users with free referral access"
    tb.stats["referrals"].pop(str(non_admin), None)
    print("subscription button stays visible for users with free referral access (not subscribed): OK")

    # 16c. Locked Histology screen: trial exhausted, no referrals/subscription -> subscription CTA
    tb.stats["histology_temp_access"][str(non_admin)] = tb.time.time() - 1
    tb.stats["histology_warnings"][str(non_admin)] = {"count": tb.HISTOLOGY_WARNING_THRESHOLD, "last_warn_at": 0}
    cb_hist_locked = FakeCB("histology_menu", uid=non_admin)
    await tb.cb_histology_menu(cb_hist_locked)
    assert cb_hist_locked.message.edits, "locked histology screen should render"
    hist_locked_text, hist_locked_kb = cb_hist_locked.message.edits[0]
    check_html(hist_locked_text)
    assert "полностью готов" in hist_locked_text and "239" in hist_locked_text
    assert any("Оформить подписку" in t for t in kb_texts(hist_locked_kb))
    tb.stats["histology_temp_access"].pop(str(non_admin), None)
    tb.stats["histology_warnings"].pop(str(non_admin), None)

    tb.grant_subscription(non_admin, 2, "stars", 239)
    cb_hist_unlocked = FakeCB("histology_menu", uid=non_admin)
    await tb.cb_histology_menu(cb_hist_unlocked)
    assert cb_hist_unlocked.message.edits
    assert "Выбери диагностику" in cb_hist_unlocked.message.edits[0][0]
    tb.stats["subscriptions"].pop(str(non_admin), None)
    print("histology_menu shows locked screen with subscription CTA when access is missing: OK")

    # 16b. Locked Anatomy screen: no access -> rendered message (not a bare alert) with subscription CTA
    cb_anat_locked = FakeCB("anatomy_menu", uid=non_admin)
    await tb.cb_anatomy_menu(cb_anat_locked)
    assert cb_anat_locked.message.edits, "locked anatomy screen should render a message"
    locked_text, locked_kb = cb_anat_locked.message.edits[0]
    check_html(locked_text)
    assert "в разработке" in locked_text and "Год" in locked_text and "6 лет" in locked_text
    assert any("Оформить подписку" in t for t in kb_texts(locked_kb))

    tb.grant_subscription(non_admin, 3, "stars", 899)
    cb_anat_unlocked = FakeCB("anatomy_menu", uid=non_admin)
    await tb.cb_anatomy_menu(cb_anat_unlocked)
    assert cb_anat_unlocked.message.edits
    assert "Выбери подраздел" in cb_anat_unlocked.message.edits[0][0]
    tb.stats["subscriptions"].pop(str(non_admin), None)
    print("anatomy_menu shows locked screen with subscription CTA when access is missing: OK")

    # 17. is_gated_callback exempts all subscription callbacks (must always be reachable)
    assert not tb.is_gated_callback("subscription_menu")
    assert not tb.is_gated_callback("sub_tier:1")
    assert not tb.is_gated_callback("buy_sub_stars:1")
    assert not tb.is_gated_callback("buy_sub_rubles:1")
    print("subscription callbacks exempt from referral gate: OK")

    # 18. Admin subscription-announcement broadcast: preview -> confirm -> broadcast
    orig_broadcast = tb._broadcast
    broadcast_calls = []
    async def fake_broadcast(text, keyboard=None):
        broadcast_calls.append((text, keyboard))
    tb._broadcast = fake_broadcast

    ann_text = tb.get_subscription_announcement_text()
    check_html(ann_text)
    assert "239" in ann_text and "Гистологии" in ann_text and "затрат" in ann_text
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
    print("admin subscription-announcement broadcast (preview/confirm/go, non-admin blocked): OK")

    print("ALL SUBSCRIPTION TESTS PASSED")

asyncio.run(main())
