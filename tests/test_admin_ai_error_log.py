# -*- coding: utf-8 -*-
"""Admin AI error log ("🩺 Ошибки AI-провайдеров"): before this, a "failed"/"refused" provider
attempt (see ai.router.try_providers) only ever reached server logs (logger.exception), invisible
to an admin without hosting access. record_ai_attempts_cost now also appends those attempts to
stats["ai_error_log"] (a bounded ring buffer), and the admin panel renders it."""
import asyncio
from _bootstrap import tb
from html.parser import HTMLParser

ADMIN_ID = next(iter(tb.ADMIN_IDS))
NON_ADMIN = 663322110

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
    def __init__(self, data, uid):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
        self._answers = []
    async def answer(self, text=None, show_alert=False):
        self._answers.append((text, show_alert))

def kb_data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]

async def main():
    tb.stats["ai_error_log"] = []
    orig_totals = tb.stats["ai_cost_totals"]
    tb.stats["ai_cost_totals"] = {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

    # ==================== empty log renders a clear message ====================
    empty_text = tb.get_ai_error_log_text()
    check_html(empty_text)
    assert "Пока ни одного сбоя" in empty_text
    print("empty error log renders a clear message: OK")

    # ==================== record_ai_attempts_cost logs failed/refused, skips success ====================
    attempts = [
        {"provider": "grok", "status": "failed", "usage": {"input_tokens": 0, "output_tokens": 0},
         "error": "TimeoutError: timed out after 30s"},
        {"provider": "openai", "status": "refused", "usage": {"input_tokens": 80, "output_tokens": 5},
         "error": "похоже на срабатывание контент-фильтра"},
        {"provider": "gemini", "status": "success", "usage": {"input_tokens": 100, "output_tokens": 20},
         "error": None},
    ]
    tb.record_ai_attempts_cost(attempts)
    assert len(tb.stats["ai_error_log"]) == 2, "only failed/refused attempts are logged, not success"
    assert {e["provider"] for e in tb.stats["ai_error_log"]} == {"grok", "openai"}
    print("record_ai_attempts_cost logs failed/refused attempts, skips success: OK")

    text = tb.get_ai_error_log_text()
    check_html(text)
    assert "grok" in text and "openai" in text
    assert "TimeoutError" in text
    assert "контент-фильтра" in text
    assert "gemini" not in text.split("хранится до")[1]  # the success attempt never shows in the list body
    print("get_ai_error_log_text renders provider/status/error for logged entries: OK")

    # ==================== newest entries shown first ====================
    tb.stats["ai_error_log"] = []
    tb.record_ai_attempts_cost([
        {"provider": "first", "status": "failed", "usage": {"input_tokens": 0, "output_tokens": 0}, "error": "err1"},
    ])
    tb.record_ai_attempts_cost([
        {"provider": "second", "status": "failed", "usage": {"input_tokens": 0, "output_tokens": 0}, "error": "err2"},
    ])
    text_order = tb.get_ai_error_log_text()
    assert text_order.index("second") < text_order.index("first"), "most recent entry must render first"
    print("newest error entries render first: OK")

    # ==================== ring buffer caps at AI_ERROR_LOG_MAX ====================
    tb.stats["ai_error_log"] = []
    for i in range(tb.AI_ERROR_LOG_MAX + 10):
        tb.record_ai_attempts_cost([
            {"provider": f"p{i}", "status": "failed", "usage": {"input_tokens": 0, "output_tokens": 0}, "error": f"e{i}"},
        ])
    assert len(tb.stats["ai_error_log"]) == tb.AI_ERROR_LOG_MAX
    assert tb.stats["ai_error_log"][-1]["provider"] == f"p{tb.AI_ERROR_LOG_MAX + 9}", "must keep the newest entries"
    print(f"ring buffer caps at AI_ERROR_LOG_MAX ({tb.AI_ERROR_LOG_MAX}), drops oldest: OK")

    # ==================== missing/None error field degrades cleanly (no crash) ====================
    tb.stats["ai_error_log"] = []
    tb.record_ai_attempts_cost([
        {"provider": "noerror", "status": "failed", "usage": {"input_tokens": 0, "output_tokens": 0}},
    ])
    text_no_err = tb.get_ai_error_log_text()
    check_html(text_no_err)
    assert "noerror" in text_no_err
    print("missing 'error' field on an attempt degrades cleanly instead of crashing: OK")

    # ==================== HTML-injection-safe: provider/error text is escaped ====================
    tb.stats["ai_error_log"] = []
    tb.record_ai_attempts_cost([
        {"provider": "openai", "status": "failed", "usage": {"input_tokens": 0, "output_tokens": 0},
         "error": "<script>bad</script> & stuff"},
    ])
    injected_text = tb.get_ai_error_log_text()
    check_html(injected_text)
    assert "&lt;script&gt;" in injected_text
    print("error text is HTML-escaped before being embedded in the reply: OK")

    # ==================== admin panel button + screen ====================
    tb.stats["ai_error_log"] = []
    tb.record_ai_attempts_cost([
        {"provider": "openai", "status": "failed", "usage": {"input_tokens": 0, "output_tokens": 0}, "error": "boom"},
    ])
    menu_kb = tb.get_admin_menu()
    assert "admin_ai_error_log" in kb_data(menu_kb)
    label = next(
        b.text for row in menu_kb.inline_keyboard for b in row if b.callback_data == "admin_ai_error_log"
    )
    assert "(1)" in label, "menu label must show the current error count"
    print("admin menu exposes the error-log button with a live count: OK")

    cb = FakeCB("admin_ai_error_log", ADMIN_ID)
    await tb.cb_admin_ai_error_log(cb)
    assert cb.message.edits
    screen_text, screen_kb = cb.message.edits[-1]
    check_html(screen_text)
    assert "boom" in screen_text
    assert "admin_ai_error_log" in kb_data(screen_kb)  # refresh button
    assert "admin_panel" in kb_data(screen_kb)

    cb_denied = FakeCB("admin_ai_error_log", NON_ADMIN)
    await tb.cb_admin_ai_error_log(cb_denied)
    assert not cb_denied.message.edits, "non-admin must be denied"
    print("cb_admin_ai_error_log renders the screen for admin, denies non-admin: OK")

    tb.stats["ai_error_log"] = []
    tb.stats["ai_cost_totals"] = orig_totals
    print("ALL ADMIN AI ERROR LOG TESTS PASSED")

asyncio.run(main())
