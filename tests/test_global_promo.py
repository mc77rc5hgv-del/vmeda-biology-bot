# -*- coding: utf-8 -*-
import asyncio, random
from _bootstrap import tb
from html.parser import HTMLParser

ADMIN_ID = next(iter(tb.ADMIN_IDS))

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

class FakeUser:
    def __init__(self, uid):
        self.id = uid
        self.is_bot = False
        self.full_name = "Test User"
        self.username = None

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
    def __init__(self, data, uid=ADMIN_ID):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
        self._answers = []
    async def answer(self, text=None, show_alert=False):
        self._answers.append((text, show_alert))

def kb_texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row]

def fresh_uid():
    return random.randint(10_000_000, 99_999_999)

async def main():
    tb.stats["section_promos"].pop("global", None)

    # 1. no promo -> ordinary user has no access to any gated subject
    uid = fresh_uid()
    tb.stats["referrals"][str(uid)] = []
    assert not tb.has_free_access(uid)
    assert not tb.has_subject_access(uid, "biology")
    assert not tb.has_subject_access(uid, "physics")
    assert not tb.has_subject_access(uid, "chemistry")
    assert not tb.anatomy_access_ok(uid)
    assert not tb.histology_access_ok(uid)
    print("baseline: no access without promo OK")

    # 2. admin menu shows the button
    menu = tb.get_admin_menu()
    assert any("Снять все ограничения" in t for t in kb_texts(menu))
    print("admin menu button present OK")

    # 3. non-admin cannot trigger the confirm screen
    non_admin = fresh_uid()
    cb_nb = FakeCB("admin_global_promo_confirm", uid=non_admin)
    await tb.cb_admin_global_promo_confirm(cb_nb)
    assert not cb_nb.message.edits
    print("non-admin blocked from confirm OK")

    # 4. admin confirm screen renders
    cb_confirm = FakeCB("admin_global_promo_confirm")
    await tb.cb_admin_global_promo_confirm(cb_confirm)
    assert cb_confirm.message.edits
    confirm_text, confirm_kb = cb_confirm.message.edits[0]
    check_html(confirm_text)
    assert "24 часа" in confirm_text
    assert any("Да, открыть всё на 24ч" in t for t in kb_texts(confirm_kb))
    print("confirm screen renders OK")

    # 5. non-admin cannot trigger go
    cb_go_nb = FakeCB("admin_global_promo_go", uid=non_admin)
    await tb.cb_admin_global_promo_go(cb_go_nb)
    assert not cb_go_nb.message.edits
    assert not tb.is_section_promo_active("global")
    print("non-admin blocked from go OK")

    # 6. go activates the promo and broadcasts to everyone
    orig_broadcast = tb._broadcast
    broadcast_calls = []
    async def fake_broadcast(text, keyboard=None):
        broadcast_calls.append((text, keyboard))
    tb._broadcast = fake_broadcast

    cb_go = FakeCB("admin_global_promo_go")
    await tb.cb_admin_global_promo_go(cb_go)
    await asyncio.sleep(0)  # let asyncio.create_task(announce_global_promo_start()) run
    assert tb.is_section_promo_active("global")
    assert broadcast_calls, "expected a broadcast announcing the promo"
    check_html(broadcast_calls[0][0])
    assert "24" in broadcast_calls[0][0]
    print("promo go activates promo + broadcasts OK")

    # 7. double-start does not re-broadcast
    cb_go_twice = FakeCB("admin_global_promo_go")
    await tb.cb_admin_global_promo_go(cb_go_twice)
    assert cb_go_twice._answers and cb_go_twice._answers[0][1] is True
    assert len(broadcast_calls) == 1, "second start attempt must not broadcast again"
    print("double-start blocked OK")

    # 8. while active, an ordinary (no-referral, no-subscription) user has access everywhere
    assert tb.has_free_access(uid)
    assert tb.has_subject_access(uid, "biology")
    assert tb.has_subject_access(uid, "physics")
    assert tb.has_subject_access(uid, "chemistry")
    assert tb.anatomy_access_ok(uid)
    assert tb.histology_access_ok(uid)
    print("promo active: full access to all 5 subjects OK")

    # 9. the referral gate middleware itself lets a gated callback through during the promo
    class FakeUpdate:
        def __init__(self, callback_query):
            self.callback_query = callback_query
            self.message = None
    called = []
    async def next_handler(event, data):
        called.append(1)
        return "ok"
    cb_mw = FakeCB("menu_biology", uid=uid)
    await tb.referral_gate_middleware(next_handler, FakeUpdate(cb_mw), {})
    assert called == [1], "gated callback must pass through the middleware during a global promo"
    print("middleware passes gated callback during promo OK")

    tb.stats["section_promos"].pop("global", None)
    tb._broadcast = orig_broadcast

    # 10. after the promo is cleared, access reverts to normal
    assert not tb.has_free_access(uid)
    assert not tb.anatomy_access_ok(uid)
    assert not tb.histology_access_ok(uid)
    print("after promo clears: access reverts to normal OK")

    print("ALL GLOBAL PROMO TESTS PASSED")

asyncio.run(main())
