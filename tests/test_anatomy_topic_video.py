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
    topic_key, topic = next(iter(next(iter(tb.ANATOMY.values()))["topics"].items()))

    # 1. topic with no "video" field: no button on the topic screen, direct access alerts.
    # Every topic in anatomy.json is now populated with a video, so simulate absence by
    # popping it temporarily rather than relying on finding a naturally video-less topic.
    assert "video" in topic, "every real topic is expected to have a video field by now"
    saved_video = topic.pop("video")
    try:
        kb = tb.get_anatomy_topic_keyboard(topic_key)
        assert "🎥 Видео" not in kb_texts(kb)
        cb_direct = FakeCB(f"anatomy_topic_video:{topic_key}")
        await tb.cb_anatomy_topic_video(cb_direct)
        assert not cb_direct.message.edits
        assert cb_direct._answers and cb_direct._answers[-1][1] is True
        print("topic without a video field: no button, direct access alerts: OK")
    finally:
        topic["video"] = saved_video

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
        topic["video"] = saved_video

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
        topic["video"] = saved_video

    # 4. section-level video button (anatomy_section_video:) works the same way
    section_key, section = "sense_organs", tb.ANATOMY["sense_organs"]
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
    # in-budget HTML for every populated entry.
    checked = 0
    for skey, sect in tb.ANATOMY.items():
        if sect.get("video"):
            urls = sect["video"] if isinstance(sect["video"], list) else [sect["video"]]
            for u in urls:
                assert u.startswith("https://www.youtube.com/"), f"{skey}: bad video url {u}"
            assert "🎥 Видео" in kb_texts(tb.get_anatomy_section_keyboard(skey))
            cb = FakeCB(f"anatomy_section_video:{skey}")
            await tb.cb_anatomy_section_video(cb)
            text, _ = cb.message.edits[-1]
            check_html(text)
            checked += 1
        for tkey, top in sect.get("topics", {}).items():
            assert top.get("video"), f"{skey}/{tkey}: expected every topic to have a video field"
            urls = top["video"] if isinstance(top["video"], list) else [top["video"]]
            for u in urls:
                assert u.startswith("https://www.youtube.com/"), f"{tkey}: bad video url {u}"
            assert "🎥 Видео" in kb_texts(tb.get_anatomy_topic_keyboard(tkey))
            cb = FakeCB(f"anatomy_topic_video:{tkey}")
            await tb.cb_anatomy_topic_video(cb)
            text, _ = cb.message.edits[-1]
            check_html(text)
            checked += 1
    assert checked == 47 + 7, f"expected 47 topics + 7 sections with video, got {checked}"
    print(f"all {checked} real video-bearing screens render OK (HTML-balanced, under 4096 chars): OK")

    # 6. access control: non-admin without anatomy access is blocked on both new callbacks
    non_admin = 123456789
    cb_na1 = FakeCB(f"anatomy_topic_video:{topic_key}", uid=non_admin)
    await tb.cb_anatomy_topic_video(cb_na1)
    assert not cb_na1.message.edits
    cb_na2 = FakeCB("anatomy_section_video:osteology", uid=non_admin)
    await tb.cb_anatomy_section_video(cb_na2)
    assert not cb_na2.message.edits
    print("non-admin without anatomy access blocked on both video callbacks: OK")

    print("ALL ANATOMY VIDEO TESTS PASSED")

asyncio.run(main())
