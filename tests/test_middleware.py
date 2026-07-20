# -*- coding: utf-8 -*-
import asyncio, random
from _bootstrap import tb

class FakeUser:
    def __init__(self, uid):
        self.id = uid
        self.is_bot = False
        self.full_name = "Test User"
        self.username = None

class FakeMsg:
    def __init__(self):
        self.sent = []
    async def answer(self, text, **kwargs):
        self.sent.append(text)
        return self

class FakeCallback:
    def __init__(self, data, uid):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
        self.answers = []
    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

class FakeMessage:
    def __init__(self, text, uid):
        self.text = text
        self.from_user = FakeUser(uid)
        self.successful_payment = None
        self.sent = []
    async def answer(self, text, **kwargs):
        self.sent.append(text)
        return self

class FakeUpdate:
    def __init__(self, message=None, callback_query=None):
        self.message = message
        self.callback_query = callback_query

def fresh_uid():
    return random.randint(10_000_000, 99_999_999)

async def hard_block(uid, data_or_msg, is_message=False):
    """Force the hard-block path: pre-set warning count to threshold."""
    uid_str = str(uid)
    tb.stats["referral_warnings"][uid_str] = {"count": tb.REFERRAL_WARNING_THRESHOLD, "last_warn_at": 0}
    called = []
    async def next_handler(event, data):
        called.append(1)
        return "ok"
    if is_message:
        msg = FakeMessage(data_or_msg, uid)
        update = FakeUpdate(message=msg)
        await tb.referral_gate_middleware(next_handler, update, {})
        return called, msg.sent
    else:
        cb = FakeCallback(data_or_msg, uid)
        update = FakeUpdate(callback_query=cb)
        await tb.referral_gate_middleware(next_handler, update, {})
        return called, cb.message.sent

async def main():
    # 1. Gated callback (menu_biology), hard-blocked user -> handler NOT called
    uid = fresh_uid()
    tb.stats["referrals"][str(uid)] = []
    called, sent = await hard_block(uid, "menu_biology")
    assert called == [], f"biology should be hard-blocked: {called}"
    assert sent, "expected a block message"
    assert "ДОСТУП ЗАКРЫТ" in sent[0]
    print("gated hard-block: menu_biology -> blocked OK")

    # 2. Exempt callback (referral_battle), same hard-blocked user -> handler IS called
    called, sent = await hard_block(uid, "referral_battle")
    assert called == [1], "referral_battle must always be allowed, even hard-blocked"
    assert not sent
    print("exempt hard-block: referral_battle -> passed OK")

    # 3. admin_panel always passes
    called, sent = await hard_block(uid, "admin_panel")
    assert called == [1]
    print("exempt hard-block: admin_panel -> passed OK")

    # 4. Chemistry callback -> blocked
    called, sent = await hard_block(uid, "menu_chemistry")
    assert called == []
    print("gated hard-block: menu_chemistry -> blocked OK")

    # 5. Physics prefix callback -> blocked
    called, sent = await hard_block(uid, "physics_q:10")
    assert called == []
    print("gated hard-block: physics_q:10 -> blocked OK")

    # 6. Anatomy callback (admin-only feature, but gate-wise must be exempt) -> passes gate
    #    (actual admin-only enforcement happens inside the handler itself, separately)
    called, sent = await hard_block(uid, "anatomy_menu")
    assert called == [1]
    print("exempt hard-block: anatomy_menu -> passed gate OK")

    # 7. Support/donation callbacks -> pass
    for cb_data in ["support_menu", "donate_stars_menu", "donate_stars_amount:100", "donors_leaderboard"]:
        called, sent = await hard_block(uid, cb_data)
        assert called == [1], cb_data
    print("exempt hard-block: support/donate callbacks -> passed OK")

    # 8. Plain text message (biology keyword search), hard-blocked -> blocked
    called, sent = await hard_block(uid, "митохондрия", is_message=True)
    assert called == [], "free-text search is biology content, must be gated"
    assert sent and "ДОСТУП ЗАКРЫТ" in sent[0]
    print("gated hard-block: free-text search -> blocked OK")

    # 9. Command messages always pass regardless of block state
    uid2 = fresh_uid()
    tb.stats["referral_warnings"][str(uid2)] = {"count": tb.REFERRAL_WARNING_THRESHOLD, "last_warn_at": 0}
    called_cmd = []
    async def next_handler2(event, data):
        called_cmd.append(1)
        return "ok"
    msg = FakeMessage("/start", uid2)
    update = FakeUpdate(message=msg)
    await tb.referral_gate_middleware(next_handler2, update, {})
    assert called_cmd == [1]
    print("command message always passes OK")

    # 10. Full access (2 referrals) -> biology passes too
    uid3 = fresh_uid()
    tb.stats["referrals"][str(uid3)] = ["a", "b"]
    called, sent = await hard_block(uid3, "menu_biology")
    assert called == [1], "2-referral user must have full access even to gated sections"
    print("full-access user: menu_biology -> passed OK")

    print("ALL MIDDLEWARE TESTS PASSED")

asyncio.run(main())
