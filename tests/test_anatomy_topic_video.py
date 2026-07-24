# -*- coding: utf-8 -*-
"""Anatomy section/topic overview screens: optional YouTube video link(s) (get_video_block,
entry["video"] as a string or list of strings), shown as plain (unwrapped) URL text with link
previews left enabled, so Telegram renders its own inline YouTube preview player in the chat --
no download, no navigating away via a button."""
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
    async def answer(self, text=None, show_alert=False):
        pass

async def main():
    topic_key, topic = next(iter(next(iter(tb.ANATOMY.values()))["topics"].items()))

    # 1. topic with no "video" field: no video block, nothing weird added
    assert "video" not in topic
    cb = FakeCB(f"anatomy_topic:{topic_key}")
    await tb.cb_anatomy_topic(cb)
    text, kwargs = cb.message.edits[-1]
    assert "🎥 Видео по теме" not in text
    print("topic without a video field: no video block rendered: OK")

    # 2. topic with a "video" field: URL shown as plain text (not wrapped in <a href>), and
    # disable_web_page_preview is not set to True, so Telegram will still auto-generate its
    # native inline preview/player for the link.
    fake_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    topic["video"] = fake_url
    try:
        cb2 = FakeCB(f"anatomy_topic:{topic_key}")
        await tb.cb_anatomy_topic(cb2)
        text2, kwargs2 = cb2.message.edits[-1]
        assert "🎥 Видео по теме" in text2
        assert fake_url in text2
        assert f'href="{fake_url}"' not in text2, "video URL must be plain text, not an <a> link, for the preview to trigger"
        assert kwargs2.get("disable_web_page_preview") is not True, \
            "must not suppress the link preview, or the inline YouTube player won't render"
        print("topic with a video field: plain URL shown, preview not disabled: OK")
    finally:
        del topic["video"]

    # 3. list-valued "video" renders every URL on its own line (used e.g. by general_joints /
    # heart, which each have two relevant Кафаров videos)
    fake_urls = [
        "https://www.youtube.com/watch?v=aaaaaaaaaaa",
        "https://www.youtube.com/watch?v=bbbbbbbbbbb",
    ]
    topic["video"] = fake_urls
    try:
        cb3 = FakeCB(f"anatomy_topic:{topic_key}")
        await tb.cb_anatomy_topic(cb3)
        text3, kwargs3 = cb3.message.edits[-1]
        for url in fake_urls:
            assert url in text3
        assert kwargs3.get("disable_web_page_preview") is not True
        print("topic with a list-valued video field: every URL shown: OK")
    finally:
        del topic["video"]

    # 4. section-level video block (anatomy_section:) works the same way
    section_key, section = "sense_organs", tb.ANATOMY["sense_organs"]
    assert "video" not in section
    cb4 = FakeCB(f"anatomy_section:{section_key}")
    await tb.cb_anatomy_section(cb4)
    text4, _ = cb4.message.edits[-1]
    assert "🎥 Видео по теме" not in text4
    print("section without a video field: no video block rendered: OK")

    section["video"] = fake_url
    try:
        cb5 = FakeCB(f"anatomy_section:{section_key}")
        await tb.cb_anatomy_section(cb5)
        text5, kwargs5 = cb5.message.edits[-1]
        assert fake_url in text5 and f'href="{fake_url}"' not in text5
        assert kwargs5.get("disable_web_page_preview") is not True
        print("section with a video field: plain URL shown, preview not disabled: OK")
    finally:
        del section["video"]

    # 5. real content: every section/topic video URL currently in anatomy.json is a real
    # youtube.com link, and every screen that shows one still renders valid, in-budget HTML
    checked = 0
    for skey, sect in tb.ANATOMY.items():
        if sect.get("video"):
            urls = sect["video"] if isinstance(sect["video"], list) else [sect["video"]]
            for u in urls:
                assert u.startswith("https://www.youtube.com/"), f"{skey}: bad video url {u}"
            checked += 1
        for tkey, top in sect.get("topics", {}).items():
            if top.get("video"):
                urls = top["video"] if isinstance(top["video"], list) else [top["video"]]
                for u in urls:
                    assert u.startswith("https://www.youtube.com/"), f"{tkey}: bad video url {u}"
                checked += 1
    assert checked > 0, "expected at least one real video field populated in anatomy.json"
    print(f"real anatomy.json video fields present and well-formed ({checked} entries): OK")

    async def _walk_real():
        rendered = 0
        for skey, sect in tb.ANATOMY.items():
            if sect.get("video"):
                cb = FakeCB(f"anatomy_section:{skey}")
                await tb.cb_anatomy_section(cb)
                text, _ = cb.message.edits[-1]
                check_html(text)
                rendered += 1
            for tkey, top in sect.get("topics", {}).items():
                if top.get("video"):
                    cb = FakeCB(f"anatomy_topic:{tkey}")
                    await tb.cb_anatomy_topic(cb)
                    text, _ = cb.message.edits[-1]
                    check_html(text)
                    rendered += 1
        return rendered
    rendered = await _walk_real()
    assert rendered == checked
    print(f"all {rendered} real video-bearing screens render OK (HTML-balanced, under 4096 chars): OK")

    print("ALL ANATOMY TOPIC VIDEO TESTS PASSED")

asyncio.run(main())
