# -*- coding: utf-8 -*-
"""Admin content search ("🔍 Поиск по контенту"): a read-only, cross-subject substring search
(Biology, Physics, Chemistry theory/practice tickets, Anatomy exam ТЕСТ bank, plus reused
search_physiology()/search_operative_surgery()) so an admin can locate the exact question behind
a user complaint without paging through a subject's normal browsing UI by hand."""
import asyncio
from _bootstrap import tb
from html.parser import HTMLParser

ADMIN_ID = next(iter(tb.ADMIN_IDS))
NON_ADMIN = 552211990

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
    def __init__(self, from_user=None):
        self.edits = []
        self.answers = []
        self.from_user = from_user
        self.text = None
    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self
    async def delete(self):
        pass
    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs.get("reply_markup")))
        return self

class FakeCB:
    def __init__(self, data, uid):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
        self._answers = []
    async def answer(self, text=None, show_alert=False):
        self._answers.append((text, show_alert))

async def main():
    # ==================== helper search functions find real content ====================
    bio_num = next(iter(tb.QUESTIONS))
    bio_word = [w for w in tb.QUESTIONS[bio_num]["title"].split() if len(w) >= 6][0]

    text = tb.get_admin_content_search_text(bio_word)
    check_html(text)
    assert f"№{bio_num}" in text
    assert "Биология" in text
    print("get_admin_content_search_text finds a real Biology question by a title word: OK")

    # ==================== empty query ====================
    empty_text = tb.get_admin_content_search_text("   ")
    assert "Пустой запрос" in empty_text
    print("empty query rejected with a clear message: OK")

    # ==================== no matches anywhere ====================
    no_match_text = tb.get_admin_content_search_text("zzzznonexistentqueryxyz123")
    check_html(no_match_text)
    assert "Ничего не найдено" in no_match_text
    print("no-match query renders a clear empty-result message: OK")

    # ==================== chemistry theory ticket question found ====================
    theory_num = next(iter(tb.CHEMISTRY_THEORY_TICKETS))
    theory_q = tb.CHEMISTRY_THEORY_TICKETS[theory_num]["questions"][0]
    theory_word = [w for w in theory_q["title"].split() if len(w) >= 6]
    if theory_word:
        theory_text = tb.get_admin_content_search_text(theory_word[0])
        check_html(theory_text)
        assert f"билет {theory_num}" in theory_text
        print("finds a Chemistry theory-ticket question: OK")

    # ==================== anatomy exam test bank found ====================
    part0 = tb.ANATOMY_EXAM_TEST_PARTS[0]
    q0 = part0["questions"][0]
    anatomy_word = [w for w in q0["question"].split() if len(w) >= 6]
    if anatomy_word:
        anatomy_text = tb.get_admin_content_search_text(anatomy_word[0])
        check_html(anatomy_text)
        assert f"№{q0['num']}" in anatomy_text
        print("finds an Anatomy ТЕСТ question: OK")

    # ==================== case-insensitive ====================
    text_lower = tb.get_admin_content_search_text(bio_word.lower())
    text_upper = tb.get_admin_content_search_text(bio_word.upper())
    assert (f"№{bio_num}" in text_lower) and (f"№{bio_num}" in text_upper)
    print("search is case-insensitive: OK")

    # ==================== query is HTML-escaped, content titles are not double-escaped ====================
    injected = tb.get_admin_content_search_text("<b>zzznope</b>")
    check_html(injected)
    assert "&lt;b&gt;" in injected
    print("query text is HTML-escaped before being embedded in the reply: OK")

    # ==================== prompt entry point ====================
    cb_prompt = FakeCB("admin_content_search_prompt", ADMIN_ID)
    await tb.cb_admin_content_search_prompt(cb_prompt)
    assert tb.ADMIN_PENDING[ADMIN_ID] == {"action": "content_search"}
    del tb.ADMIN_PENDING[ADMIN_ID]

    cb_prompt_denied = FakeCB("admin_content_search_prompt", NON_ADMIN)
    await tb.cb_admin_content_search_prompt(cb_prompt_denied)
    assert NON_ADMIN not in tb.ADMIN_PENDING, "non-admin must not be able to start a content search"
    print("admin_content_search_prompt: sets pending state, denies non-admin: OK")

    # ==================== end-to-end pending flow, and it stays pending for repeat queries ====================
    tb.ADMIN_PENDING[ADMIN_ID] = {"action": "content_search"}
    m1 = FakeMsg(from_user=FakeUser(ADMIN_ID))
    m1.text = bio_word
    await tb.handle_admin_pending_action(m1)
    assert m1.answers
    check_html(m1.answers[0][0])
    assert f"№{bio_num}" in m1.answers[0][0]
    assert tb.ADMIN_PENDING.get(ADMIN_ID) == {"action": "content_search"}, (
        "content_search must stay pending so the admin can search again without re-opening the menu"
    )

    m2 = FakeMsg(from_user=FakeUser(ADMIN_ID))
    m2.text = "zzzznonexistentqueryxyz123"
    await tb.handle_admin_pending_action(m2)
    assert m2.answers and "Ничего не найдено" in m2.answers[0][0]
    assert tb.ADMIN_PENDING.get(ADMIN_ID) == {"action": "content_search"}

    del tb.ADMIN_PENDING[ADMIN_ID]
    print("content_search pending flow answers each query and stays armed for the next one: OK")

    print("ALL ADMIN CONTENT SEARCH TESTS PASSED")

asyncio.run(main())
