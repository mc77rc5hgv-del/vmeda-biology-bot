# -*- coding: utf-8 -*-
"""Anatomy section/topic video links: an optional entry["video"] field (string or list of
strings) surfaces as a "🎥 Видео" button on the section/topic screen; tapping it opens a
dedicated sub-screen showing the URL(s) as plain (unwrapped) text with link previews left
enabled, so Telegram renders its own inline YouTube preview player in the chat -- no download,
no forced navigation away via a button pointing off-Telegram."""
import asyncio
from html.parser import HTMLParser
from _bootstrap import tb

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
    assert len(text) <= 4096, f"too long: {len(text)} chars"

ADMIN_ID = next(iter(tb.ADMIN_IDS))

class FakeUser:
    def __init__(self, uid):
        self.id = uid

class FakeMsg:
    def __init__(self):
        self.edits = []
    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs))
        return self
    async def delete(self):
        pass
    async def answer(self, text, **kwargs):
        self.edits.append((text, kwargs))
        return self

class FakeCB:
    def __init__(self, data, uid=ADMIN_ID):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
        self._answers = []
    async def answer(self, text=None, show_alert=False):
        self._answers.append((text, show_alert))

def kb_data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]

def kb_texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row]

async def main():
    # topic with no "video" field: cranium_intro carries no video since it holds the
    # general/overview skull material split off from the old skull topic's single video.
    topic_key, topic = "cranium_intro", tb.ANATOMY["module1_osteology"]["topics"]["cranium_intro"]

    # 1. topic with no "video" field: no button on the topic screen, direct access alerts.
    assert "video" not in topic
    kb = tb.get_anatomy_topic_keyboard(topic_key)
    assert "🎥 Видео" not in kb_texts(kb)
    cb_direct = FakeCB(f"anatomy_topic_video:{topic_key}")
    await tb.cb_anatomy_topic_video(cb_direct)
    assert not cb_direct.message.edits
    assert cb_direct._answers and cb_direct._answers[-1][1] is True
    print("topic without a video field: no button, direct access alerts: OK")

    # 2. topic with a "video" field: button appears, and its screen shows the URL as plain
    # text (not wrapped in <a href>), with disable_web_page_preview not set to True so the
    # native inline preview/player still renders.
    fake_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    topic["video"] = fake_url
    try:
        kb2 = tb.get_anatomy_topic_keyboard(topic_key)
        assert "🎥 Видео" in kb_texts(kb2)
        video_cb_data = kb_data(kb2)[kb_texts(kb2).index("🎥 Видео")]
        assert video_cb_data == f"anatomy_topic_video:{topic_key}"

        cb2 = FakeCB(video_cb_data)
        await tb.cb_anatomy_topic_video(cb2)
        text2, kwargs2 = cb2.message.edits[-1]
        assert fake_url in text2
        assert f'href="{fake_url}"' not in text2, "video URL must be plain text, not an <a> link, for the preview to trigger"
        assert kwargs2.get("disable_web_page_preview") is not True, \
            "must not suppress the link preview, or the inline YouTube player won't render"
        back_kb = cb2.message.edits[-1][1]["reply_markup"]
        assert kb_data(back_kb) == [f"anatomy_topic:{topic_key}"]
        print("topic with a video field: button leads to a plain-URL screen, preview not disabled: OK")
    finally:
        del topic["video"]

    # 3. list-valued "video" renders every URL on its own line (used e.g. by general_joints)
    fake_urls = [
        "https://www.youtube.com/watch?v=aaaaaaaaaaa",
        "https://www.youtube.com/watch?v=bbbbbbbbbbb",
    ]
    topic["video"] = fake_urls
    try:
        cb3 = FakeCB(f"anatomy_topic_video:{topic_key}")
        await tb.cb_anatomy_topic_video(cb3)
        text3, kwargs3 = cb3.message.edits[-1]
        for url in fake_urls:
            assert url in text3
        assert kwargs3.get("disable_web_page_preview") is not True
        print("topic with a list-valued video field: every URL shown: OK")
    finally:
        del topic["video"]

    # 4. section-level video button (anatomy_section_video:) works the same way -- no
    # section in the current (Kafarov-module) structure carries a video field, since
    # the old per-section videos didn't map cleanly onto the new module boundaries.
    section_key, section = "module1_osteology", tb.ANATOMY["module1_osteology"]
    assert "video" not in section
    kb4 = tb.get_anatomy_section_keyboard(section_key)
    assert "🎥 Видео" not in kb_texts(kb4)
    cb_direct2 = FakeCB(f"anatomy_section_video:{section_key}")
    await tb.cb_anatomy_section_video(cb_direct2)
    assert not cb_direct2.message.edits
    assert cb_direct2._answers and cb_direct2._answers[-1][1] is True
    print("section without a video field: no button, direct access alerts: OK")

    section["video"] = fake_url
    try:
        kb5 = tb.get_anatomy_section_keyboard(section_key)
        assert "🎥 Видео" in kb_texts(kb5)
        cb5 = FakeCB(f"anatomy_section_video:{section_key}")
        await tb.cb_anatomy_section_video(cb5)
        text5, kwargs5 = cb5.message.edits[-1]
        assert fake_url in text5 and f'href="{fake_url}"' not in text5
        assert kwargs5.get("disable_web_page_preview") is not True
        back_kb5 = cb5.message.edits[-1][1]["reply_markup"]
        assert kb_data(back_kb5) == [f"anatomy_section:{section_key}"]
        print("section with a video field: button leads to a plain-URL screen, preview not disabled: OK")
    finally:
        del section["video"]

    # 5. real content: every section/topic video URL currently in anatomy.json is a real
    # youtube.com link, the "🎥 Видео" button is present, and its screen renders valid,
    # in-budget HTML for every populated entry. Since the Kafarov-module restructuring,
    # not every topic carries a video (many new fine-grained subtopics are still empty
    # skeletons), so this walks only the topics that do, rather than asserting on all.
    checked = 0
    for skey, sect in tb.ANATOMY.items():
        assert not sect.get("video"), f"{skey}: unexpected section-level video in new structure"
        for tkey, top in sect.get("topics", {}).items():
            if not top.get("video"):
                continue
            urls = top["video"] if isinstance(top["video"], list) else [top["video"]]
            for u in urls:
                assert u.startswith("https://www.youtube.com/"), f"{tkey}: bad video url {u}"
            assert "🎥 Видео" in kb_texts(tb.get_anatomy_topic_keyboard(tkey))
            cb = FakeCB(f"anatomy_topic_video:{tkey}")
            await tb.cb_anatomy_topic_video(cb)
            text, _ = cb.message.edits[-1]
            check_html(text)
            checked += 1
    assert checked == 44, f"expected 44 topics with a migrated video field, got {checked}"
    print(f"all {checked} real video-bearing topic screens render OK (HTML-balanced, under 4096 chars): OK")

    # 6. access control: non-admin without anatomy access is blocked on both new callbacks
    non_admin = 123456789
    cb_na1 = FakeCB(f"anatomy_topic_video:{topic_key}", uid=non_admin)
    await tb.cb_anatomy_topic_video(cb_na1)
    assert not cb_na1.message.edits
    cb_na2 = FakeCB("anatomy_section_video:module1_osteology", uid=non_admin)
    await tb.cb_anatomy_section_video(cb_na2)
    assert not cb_na2.message.edits
    print("non-admin without anatomy access blocked on both video callbacks: OK")

    print("ALL ANATOMY VIDEO TESTS PASSED")

asyncio.run(main())
