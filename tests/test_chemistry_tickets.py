# -*- coding: utf-8 -*-
import asyncio
from _bootstrap import tb
from html.parser import HTMLParser

class C(HTMLParser):
    def __init__(self):
        super().__init__(); self.stack = []; self.problems = []
    def handle_starttag(self, tag, attrs): self.stack.append(tag)
    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag: self.problems.append(tag)
        else: self.stack.pop()

def check_html(text):
    c = C(); c.feed(text)
    assert not c.stack and not c.problems, (text[:200], c.stack, c.problems)
    assert len(text) <= 4096, len(text)

class FakeUser:
    def __init__(self, uid):
        self.id = uid

class FakeMsg:
    def __init__(self):
        self.edits = []
    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self
    async def delete(self):
        pass
    async def answer(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self

class FakeCB:
    def __init__(self, data, uid=111222333):
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

TEST_UID = 111222333

async def main():
    uid_str = str(TEST_UID)
    tb.stats["referrals"][uid_str] = []
    tb.stats["referral_monthly"].pop(uid_str, None)
    tb.stats["subscriptions"].pop(uid_str, None)
    tb.stats["manual_access_granted"] = [x for x in tb.stats["manual_access_granted"] if x != TEST_UID]
    tb.stats["temporary_access"].pop(uid_str, None)

    # 0. extra restriction: no referrals + no subscription -> every ticket entry point locked,
    #    even though the general chemistry gate itself would already let this callback through
    assert not tb.chemistry_tickets_access_ok(TEST_UID)
    locked_points = [
        "chemistry_tickets", "chem_theory_tickets", "chem_practice_tickets",
        "chem_theory_ticket:1", "chem_theory_q:1:0", "chem_practice_ticket:1",
    ]
    handlers = {
        "chemistry_tickets": tb.cb_chemistry_tickets,
        "chem_theory_tickets": tb.cb_chem_theory_tickets,
        "chem_practice_tickets": tb.cb_chem_practice_tickets,
        "chem_theory_ticket:1": tb.cb_chem_theory_ticket,
        "chem_theory_q:1:0": tb.cb_chem_theory_question,
        "chem_practice_ticket:1": tb.cb_chem_practice_ticket,
    }
    for data in locked_points:
        cb = FakeCB(data)
        await handlers[data](cb)
        assert cb.message.edits, f"{data} did not render a locked screen"
        text, kb = cb.message.edits[-1]
        check_html(text)
        assert f"{tb.REFERRAL_FULL_ACCESS_THRESHOLD} реферала" in text or "реферала или подписка" in text
        assert "89" in text
        assert "subscription_menu" in kb_data(kb)
        assert "referral_info" in kb_data(kb)
    print("extra restriction locks all 6 ticket entry points without referrals/subscription: OK")

    # 0b. a legacy chemistry-granting subscription priced below 89₽ (retired tier 5, still
    # grantable programmatically for historical accounts) does NOT satisfy the extra restriction,
    # even though it does satisfy the ordinary chemistry gate (has_subject_access)
    tb.grant_subscription(TEST_UID, 5, "rubles", 49, "chemistry")
    assert tb.has_subject_access(TEST_UID, "chemistry")
    assert not tb.chemistry_tickets_access_ok(TEST_UID), "a sub priced below 89₽ must not unlock tickets"
    cb = FakeCB("chemistry_tickets")
    await tb.cb_chemistry_tickets(cb)
    text, _ = cb.message.edits[-1]
    assert "89" in text
    tb.stats["subscriptions"].pop(uid_str, None)
    print("sub priced below 89₽ satisfies the general gate but not the ticket restriction: OK")

    # 0c. an active subscription priced >= 89₽ satisfies the extra restriction
    tb.grant_subscription(TEST_UID, 1, "stars", 89)
    assert tb.chemistry_tickets_access_ok(TEST_UID)
    tb.stats["subscriptions"].pop(uid_str, None)
    print("sub priced >= 89₽ satisfies the ticket restriction: OK")

    # From here on, grant the test user full referral access so the rest of this file exercises
    # ticket content/navigation exactly as before the extra restriction was added.
    tb.stats["referrals"][uid_str] = [f"ref{i}" for i in range(tb.REFERRAL_FULL_ACCESS_THRESHOLD)]
    tb.stats["referral_monthly"][uid_str] = {
        "month": tb._current_referral_month_key(), "count": tb.REFERRAL_FULL_ACCESS_THRESHOLD,
    }
    assert tb.chemistry_tickets_access_ok(TEST_UID)

    # 1. chemistry menu exposes the new "Билеты" entry point
    menu_kb = tb.get_chemistry_menu()
    assert "chemistry_tickets" in kb_data(menu_kb)
    print("chemistry menu exposes tickets button: OK")

    # 2. chemistry_tickets renders the two-way split menu
    cb = FakeCB("chemistry_tickets")
    await tb.cb_chemistry_tickets(cb)
    assert cb.message.edits
    text, kb = cb.message.edits[-1]
    check_html(text)
    data = kb_data(kb)
    assert "chem_theory_tickets" in data and "chem_practice_tickets" in data
    print("chemistry_tickets menu OK")

    # 3. theory tickets: list screen
    cb = FakeCB("chem_theory_tickets")
    await tb.cb_chem_theory_tickets(cb)
    text, kb = cb.message.edits[-1]
    check_html(text)
    data = kb_data(kb)
    for num in tb.CHEMISTRY_THEORY_TICKETS:
        assert f"chem_theory_ticket:{num}" in data
    print("chem_theory_tickets list screen OK")

    # 4. theory ticket detail lists a button per question (2 each: theory Q + lab)
    for num, ticket in tb.CHEMISTRY_THEORY_TICKETS.items():
        assert len(ticket["questions"]) == 2, num
        cb = FakeCB(f"chem_theory_ticket:{num}")
        await tb.cb_chem_theory_ticket(cb)
        assert cb.message.edits, f"ticket {num} detail did not render"
        text, kb = cb.message.edits[-1]
        check_html(text)
        data = kb_data(kb)
        assert f"chem_theory_q:{num}:0" in data
        assert f"chem_theory_q:{num}:1" in data
    print(f"all {len(tb.CHEMISTRY_THEORY_TICKETS)} theory tickets render detail screens OK")

    # 5. unknown theory ticket -> alert, no crash
    cb = FakeCB("chem_theory_ticket:999")
    await tb.cb_chem_theory_ticket(cb)
    assert not cb.message.edits
    assert cb._answers and cb._answers[-1][1] is True
    print("unknown theory ticket -> alert OK")

    # 6. every theory question renders non-empty title+answer, valid HTML, under Telegram's limit
    for num, ticket in tb.CHEMISTRY_THEORY_TICKETS.items():
        for idx, q in enumerate(ticket["questions"]):
            cb = FakeCB(f"chem_theory_q:{num}:{idx}")
            await tb.cb_chem_theory_question(cb)
            assert cb.message.edits, f"ticket {num} question {idx} did not render"
            text, kb = cb.message.edits[-1]
            check_html(text)
            assert q["title"] in text and q["answer"] in text
    print("all theory ticket questions render OK (HTML-balanced, under 4096 chars)")

    # 7. prev/next navigation at the boundaries for a known 2-question ticket
    cb = FakeCB("chem_theory_q:1:0")
    await tb.cb_chem_theory_question(cb)
    _, kb = cb.message.edits[-1]
    texts = kb_texts(kb)
    data = kb_data(kb)
    assert not any("Предыдущий" in t for t in texts)
    assert "chem_theory_q:1:1" in data
    print("first question has no 'previous' button OK")

    cb = FakeCB("chem_theory_q:1:1")
    await tb.cb_chem_theory_question(cb)
    _, kb = cb.message.edits[-1]
    texts = kb_texts(kb)
    data = kb_data(kb)
    assert not any("Следующий" in t for t in texts)
    assert "chem_theory_q:1:0" in data
    print("last question has no 'next' button OK")

    # 8. unknown question index -> alert, no crash
    cb = FakeCB("chem_theory_q:1:99")
    await tb.cb_chem_theory_question(cb)
    assert not cb.message.edits
    assert cb._answers and cb._answers[-1][1] is True
    print("unknown question index -> alert OK")

    # 9. practice tickets: list screen
    cb = FakeCB("chem_practice_tickets")
    await tb.cb_chem_practice_tickets(cb)
    text, kb = cb.message.edits[-1]
    check_html(text)
    data = kb_data(kb)
    for num in tb.CHEMISTRY_PRACTICE_TICKETS:
        assert f"chem_practice_ticket:{num}" in data
    print("chem_practice_tickets list screen OK")

    # 10. the new ticket 11 (Ag3PO4) is present and renders correctly
    assert "11" in tb.CHEMISTRY_PRACTICE_TICKETS
    cb = FakeCB("chem_practice_ticket:11")
    await tb.cb_chem_practice_ticket(cb)
    assert cb.message.edits
    text, kb = cb.message.edits[-1]
    check_html(text)
    assert "Ag" in text and "PO" in text
    print("practice ticket 11 (Ag3PO4) renders OK")

    # 11. every practice ticket renders, valid HTML, under Telegram's limit
    for num, ticket in tb.CHEMISTRY_PRACTICE_TICKETS.items():
        cb = FakeCB(f"chem_practice_ticket:{num}")
        await tb.cb_chem_practice_ticket(cb)
        assert cb.message.edits, f"practice ticket {num} did not render"
        text, kb = cb.message.edits[-1]
        check_html(text)
        assert ticket["title"] in text and ticket["content"] in text
    print(f"all {len(tb.CHEMISTRY_PRACTICE_TICKETS)} practice tickets render OK")

    # 12. unknown practice ticket -> alert, no crash
    cb = FakeCB("chem_practice_ticket:999")
    await tb.cb_chem_practice_ticket(cb)
    assert not cb.message.edits
    assert cb._answers and cb._answers[-1][1] is True
    print("unknown practice ticket -> alert OK")

    # 13. gate: all new callbacks must be classified as chemistry-gated
    assert tb.get_gated_subject("chemistry_tickets") == "chemistry"
    assert tb.get_gated_subject("chem_theory_tickets") == "chemistry"
    assert tb.get_gated_subject("chem_practice_tickets") == "chemistry"
    assert tb.get_gated_subject("chem_theory_ticket:1") == "chemistry"
    assert tb.get_gated_subject("chem_theory_q:1:0") == "chemistry"
    assert tb.get_gated_subject("chem_practice_ticket:1") == "chemistry"
    print("gating classification OK")

    print("ALL CHEMISTRY TICKETS TESTS PASSED")

asyncio.run(main())
