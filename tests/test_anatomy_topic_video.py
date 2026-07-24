# -*- coding: utf-8 -*-
"""Anatomy topic overview screen: optional per-topic YouTube video link, shown as plain
(unwrapped) URL text with link previews left enabled, so Telegram renders its own inline
YouTube preview player in the chat -- no download, no navigating away via a button."""
import asyncio
from _bootstrap import tb

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

    print("ALL ANATOMY TOPIC VIDEO TESTS PASSED")

asyncio.run(main())
