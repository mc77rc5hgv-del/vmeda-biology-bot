# -*- coding: utf-8 -*-
import asyncio
from _bootstrap import tb

ADMIN_ID = next(iter(tb.ADMIN_IDS)) if tb.ADMIN_IDS else 1

class FakeUser:
    def __init__(self, uid):
        self.id = uid

class FakeMsg:
    def __init__(self):
        self.edits = []
        self.media_groups = []
        self.photos = []
        self.deleted = False
        self.chat = type("C", (), {"id": 1})()
    async def edit_text(self, text, **kwargs):
        self.edits.append(text)
        return self
    async def delete(self):
        self.deleted = True
    async def answer(self, text, **kwargs):
        self.edits.append(text)
        return self
    async def answer_media_group(self, media, **kwargs):
        self.media_groups.append(media)
        return self
    async def answer_photo(self, photo, **kwargs):
        self.photos.append((photo, kwargs.get("caption")))
        return self

class FakeCB:
    def __init__(self, data, uid=ADMIN_ID):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
        self._answers = []
    async def answer(self, text=None, show_alert=False):
        self._answers.append((text, show_alert))

async def main():
    topic_key = "skull"
    topic = tb.get_anatomy_topic_data(topic_key)
    bones = topic["bones_list"]

    for bone in bones:
        bid = bone["id"]
        images = tb.get_bone_images(topic_key, bid)
        assert images, f"{bid} has no images!"
        slides = tb.get_bone_images(topic_key, bid, kind="slides")
        atlas = tb.get_bone_images(topic_key, bid, kind="atlas")
        assert len(slides) + len(atlas) == len(images), bid

        # hub text should mention both counts
        hub_text = tb.get_anatomy_bone_hub_text(topic_key, bid)
        assert f"Слайдов презентации: {len(slides)}" in hub_text, hub_text
        assert f"Атлас (Неттер/Гайворонский): {len(atlas)}" in hub_text, hub_text

        # walk every page of both albums via the real handlers, checking exact
        # caption/credit content against the source data
        for kind, kind_images, cb_fn, prefix in (
            ("slides", slides, tb.cb_anatomy_bone_slides, "anatomy_bone_slides"),
            ("atlas", atlas, tb.cb_anatomy_bone_atlas, "anatomy_bone_atlas"),
        ):
            n_pages = tb.anatomy_page_count(len(kind_images)) if kind_images else 0
            for page in range(n_pages):
                cb = FakeCB(f"{prefix}:{topic_key}:{bid}:{page}")
                await cb_fn(cb)
                assert cb.message.deleted, f"{bid}/{kind} page {page}: message not deleted"
                start = page * tb.ANATOMY_ALBUM_PAGE_SIZE
                expected_slice = kind_images[start:start + tb.ANATOMY_ALBUM_PAGE_SIZE]
                if len(expected_slice) == 1:
                    # Telegram's sendMediaGroup needs >=2 items — a lone photo on a page
                    # goes through answer_photo instead.
                    assert cb.message.photos, f"{bid}/{kind} page {page}: no single photo sent"
                    photo, caption = cb.message.photos[0]
                    img = expected_slice[0]
                    if "url" in img:
                        assert photo == img["url"]
                    else:
                        assert isinstance(photo, tb.FSInputFile)
                    assert img["caption"] in caption
                    assert img["credit"] in caption
                    assert len(caption) <= 1024, f"{bid}/{kind} page {page} caption too long: {len(caption)}"
                else:
                    assert cb.message.media_groups, f"{bid}/{kind} page {page}: no album sent"
                    media = cb.message.media_groups[0]
                    assert len(media) == len(expected_slice), f"{bid}/{kind} page {page}"
                    for m, img in zip(media, expected_slice):
                        if "url" in img:
                            assert m.media == img["url"]
                        else:
                            assert isinstance(m.media, tb.FSInputFile)
                        assert img["caption"] in m.caption
                        assert img["credit"] in m.caption
                        assert len(m.caption) <= 1024, f"{bid}/{kind} page {page} caption too long: {len(m.caption)}"

        print(f"images-OK {bid}: {len(slides)} slides, {len(atlas)} atlas")

    # out-of-range page should alert, not crash
    cb = FakeCB(f"anatomy_bone_slides:{topic_key}:frontal:999")
    await tb.cb_anatomy_bone_slides(cb)
    assert cb._answers and cb._answers[0][1] is True
    print("out-of-range page -> alert OK")

    # access control still enforced
    cb = FakeCB(f"anatomy_bone_slides:{topic_key}:frontal:0", uid=123456789)
    await tb.cb_anatomy_bone_slides(cb)
    assert not cb.message.media_groups and cb._answers[0][1] is True
    print("access-control OK")

    print("ALL IMAGE TESTS PASSED")

asyncio.run(main())
