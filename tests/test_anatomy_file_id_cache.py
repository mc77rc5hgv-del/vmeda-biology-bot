# -*- coding: utf-8 -*-
import asyncio, os
from _bootstrap import tb

ADMIN_ID = next(iter(tb.ADMIN_IDS))

class FakeUser:
    def __init__(self, uid):
        self.id = uid

class FakePhotoSize:
    def __init__(self, file_id):
        self.file_id = file_id

class FakeSentMessage:
    """Stands in for a real Telegram Message returned by answer_photo/answer_media_group —
    unlike the plain FakeMsg used elsewhere, this one carries a .photo list so the caching
    code under test has something to read a file_id from."""
    def __init__(self, file_id):
        self.photo = [FakePhotoSize(file_id)]

class FakeMsg:
    def __init__(self):
        self.edits = []
        self.media_groups = []
        self.photos = []
        self.deleted = False
        self._next_file_id = 0
    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self
    async def delete(self):
        self.deleted = True
    async def answer(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self
    async def answer_media_group(self, media, **kwargs):
        self.media_groups.append(media)
        sent = []
        for _ in media:
            self._next_file_id += 1
            sent.append(FakeSentMessage(f"FAKE_FILE_ID_{self._next_file_id}"))
        return sent
    async def answer_photo(self, photo, **kwargs):
        self.photos.append((photo, kwargs.get("caption")))
        self._next_file_id += 1
        return FakeSentMessage(f"FAKE_FILE_ID_{self._next_file_id}")

class FakeCB:
    def __init__(self, data, uid=ADMIN_ID):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
        self._answers = []
    async def answer(self, text=None, show_alert=False):
        self._answers.append((text, show_alert))

async def main():
    tb.ANATOMY_FILE_ID_CACHE.clear()

    # ---- multi-photo album page: every image's file_id gets cached after first send ----
    topic_key, bone_id = "skull", "temporal"
    images = tb.get_bone_images(topic_key, bone_id, kind="slides")
    assert len(images) >= 2, "need a multi-image page to exercise the media-group branch"
    keys = [tb._anatomy_image_key(img) for img in images[:tb.ANATOMY_ALBUM_PAGE_SIZE]]
    for k in keys:
        assert k not in tb.ANATOMY_FILE_ID_CACHE

    cb = FakeCB(f"anatomy_bone_slides:{topic_key}:{bone_id}:0")
    await tb.cb_anatomy_bone_slides(cb)
    for k in keys:
        assert k in tb.ANATOMY_FILE_ID_CACHE, f"{k} should be cached after first send"
    print("album page: file_id cached for every image after first send: OK")

    # ---- second view of the same page reuses the cached file_id, not FSInputFile/url ----
    cb2 = FakeCB(f"anatomy_bone_slides:{topic_key}:{bone_id}:0")
    await tb.cb_anatomy_bone_slides(cb2)
    media = cb2.message.media_groups[0]
    for m, img in zip(media, images[:tb.ANATOMY_ALBUM_PAGE_SIZE]):
        expected_file_id = tb.ANATOMY_FILE_ID_CACHE[tb._anatomy_image_key(img)]
        assert m.media == expected_file_id, "second view must reuse the cached file_id string"
        assert not isinstance(m.media, tb.FSInputFile), "must not re-read from disk once cached"
    print("album page: second view reuses cached file_id instead of re-reading disk: OK")

    # ---- single-photo page (answer_photo branch) also gets cached and reused ----
    tb.ANATOMY_FILE_ID_CACHE.clear()
    single_topic, single_bone = "skull", "mandible"
    single_images = tb.get_bone_images(single_topic, single_bone, kind="atlas")
    assert len(single_images) == 1, "mandible should have exactly one atlas image (single-photo branch)"
    key = tb._anatomy_image_key(single_images[0])

    cb3 = FakeCB(f"anatomy_bone_atlas:{single_topic}:{single_bone}:0")
    await tb.cb_anatomy_bone_atlas(cb3)
    assert key in tb.ANATOMY_FILE_ID_CACHE
    cached_file_id = tb.ANATOMY_FILE_ID_CACHE[key]

    cb4 = FakeCB(f"anatomy_bone_atlas:{single_topic}:{single_bone}:0")
    await tb.cb_anatomy_bone_atlas(cb4)
    photo, _caption = cb4.message.photos[0]
    assert photo == cached_file_id, "second view of a single-photo page must reuse the cached file_id"
    print("single-photo page: file_id cached and reused on second view: OK")

    # ---- cache persists to disk and reloads correctly (write happens on a background thread) ----
    import json, time
    on_disk = {}
    for _ in range(40):
        if os.path.exists(tb.ANATOMY_FILE_ID_CACHE_PATH):
            with open(tb.ANATOMY_FILE_ID_CACHE_PATH, "r", encoding="utf-8") as f:
                on_disk = json.load(f)
            if key in on_disk:
                break
        time.sleep(0.05)
    assert key in on_disk and on_disk[key] == cached_file_id, "cache must be persisted to disk (async write)"
    print("cache persisted to disk: OK")

    print("ALL ANATOMY FILE_ID CACHE TESTS PASSED")

asyncio.run(main())
