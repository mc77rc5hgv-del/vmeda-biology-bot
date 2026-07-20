# -*- coding: utf-8 -*-
import os, sys, asyncio
from _bootstrap import tb

ADMIN_ID = next(iter(tb.ADMIN_IDS)) if tb.ADMIN_IDS else 1

class FakeUser:
    def __init__(self, uid):
        self.id = uid

class FakeMsg:
    def __init__(self):
        self.edits = []
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

        # hub text should mention image count
        hub_text = tb.get_anatomy_bone_hub_text(topic_key, bid)
        assert f"Фото и схем: {len(images)}" in hub_text, hub_text

        # walk every image via the real handler, following next-buttons
        for idx in range(len(images)):
            cb = FakeCB(f"anatomy_bone_img:{topic_key}:{bid}:{idx}")
            await tb.cb_anatomy_bone_img(cb)
            assert cb.message.deleted, f"{bid} idx {idx}: message not deleted"
            assert cb.message.photos, f"{bid} idx {idx}: no photo sent"
            photo_url, caption = cb.message.photos[0]
            if "url" in images[idx]:
                assert photo_url == images[idx]["url"]
            else:
                assert isinstance(photo_url, tb.FSInputFile)
            assert images[idx]["caption"] in caption
            assert images[idx]["credit"] in caption
            assert len(caption) <= 1024, f"{bid} idx {idx} caption too long: {len(caption)}"

        # out-of-range idx should alert, not crash
        cb = FakeCB(f"anatomy_bone_img:{topic_key}:{bid}:{len(images)}")
        await tb.cb_anatomy_bone_img(cb)
        assert cb._answers and cb._answers[0][1] is True

        print(f"images-OK {bid}: {len(images)} img")

    # access control still enforced
    cb = FakeCB(f"anatomy_bone_img:{topic_key}:frontal:0", uid=123456789)
    await tb.cb_anatomy_bone_img(cb)
    assert not cb.message.photos and cb._answers[0][1] is True
    print("access-control OK")

    print("ALL IMAGE TESTS PASSED")

asyncio.run(main())
