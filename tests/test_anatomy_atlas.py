# -*- coding: utf-8 -*-
import os, sys, asyncio
from _bootstrap import tb

ADMIN_ID = next(iter(tb.ADMIN_IDS))

class FakeUser:
    def __init__(self, uid):
        self.id = uid

class FakeMsg:
    def __init__(self):
        self.edits = []
        self.media_groups = []
        self.photos = []
        self.deleted = False
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
        return [self] * len(media)
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

def kb_data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]

def n_pages(n_images):
    return max(1, (n_images + tb.ANATOMY_ALBUM_PAGE_SIZE - 1) // tb.ANATOMY_ALBUM_PAGE_SIZE)

async def main():
    errors = []
    total_images_tested = 0

    # Derived generically (not hand-listed) so every section that adds atlas_images —
    # present and future — is automatically exercised here.
    topics_with_atlas = [
        (section_key, topic_key)
        for section_key, section in tb.ANATOMY.items()
        for topic_key, topic in section.get("topics", {}).items()
        if topic.get("atlas_images")
    ]
    assert len(topics_with_atlas) >= 29, f"expected atlas_images on ~29+ topics, got {len(topics_with_atlas)}"

    # 1. every topic with atlas_images shows the button on its topic screen
    for section_key, topic_key in topics_with_atlas:
        images = tb.get_topic_atlas_images(topic_key)
        assert images, f"{topic_key} expected to have atlas_images"
        kb = tb.get_anatomy_topic_keyboard(topic_key)
        assert f"anatomy_atlas:{topic_key}:0" in kb_data(kb), f"{topic_key}: missing atlas button"

    # topics without atlas_images (still to be built) must NOT show the button
    for topic_key in ("general_joints",):
        kb = tb.get_anatomy_topic_keyboard(topic_key)
        assert not any(d and d.startswith(f"anatomy_atlas:{topic_key}:") for d in kb_data(kb)), topic_key
    print("atlas button presence matches atlas_images content: OK")

    # 2. every atlas page renders as a native album: real files, captions with credit, correct nav
    for section_key, topic_key in topics_with_atlas:
        images = tb.get_topic_atlas_images(topic_key)
        pages = n_pages(len(images))
        for page in range(pages):
            cb = FakeCB(f"anatomy_atlas:{topic_key}:{page}")
            await tb.cb_anatomy_atlas(cb)
            expected = min(tb.ANATOMY_ALBUM_PAGE_SIZE, len(images) - page * tb.ANATOMY_ALBUM_PAGE_SIZE)
            if not cb.message.deleted or not (cb.message.media_groups or cb.message.photos):
                errors.append(f"{topic_key} page={page}: no photo(s) sent")
                continue
            if expected == 1:
                # Telegram's sendMediaGroup needs >=2 items — a lone photo on a page
                # goes through answer_photo instead.
                if not cb.message.photos:
                    errors.append(f"{topic_key} page={page}: single-image page must use answer_photo")
                    continue
                photo, caption = cb.message.photos[0]
                if isinstance(photo, tb.FSInputFile):
                    if not os.path.exists(photo.path):
                        errors.append(f"{topic_key} page={page}: file missing: {photo.path}")
                elif not (isinstance(photo, str) and photo.startswith("http")):
                    errors.append(f"{topic_key} page={page}: unexpected photo type: {type(photo)}")
                if not caption or "Источник:" not in caption:
                    errors.append(f"{topic_key} page={page}: caption missing credit line")
            else:
                if not cb.message.media_groups:
                    errors.append(f"{topic_key} page={page}: no album sent")
                    continue
                media = cb.message.media_groups[0]
                if len(media) != expected:
                    errors.append(f"{topic_key} page={page}: expected {expected} photos, got {len(media)}")
                for m in media:
                    photo = m.media
                    if isinstance(photo, tb.FSInputFile):
                        if not os.path.exists(photo.path):
                            errors.append(f"{topic_key} page={page}: file missing: {photo.path}")
                    elif not (isinstance(photo, str) and photo.startswith("http")):
                        errors.append(f"{topic_key} page={page}: unexpected photo type: {type(photo)}")
                    if not m.caption or "Источник:" not in m.caption:
                        errors.append(f"{topic_key} page={page}: caption missing credit line")
            assert cb.message.edits, f"{topic_key} page={page}: missing nav message"
            nav_text, kb = cb.message.edits[-1]
            data = kb_data(kb)
            if page > 0:
                assert f"anatomy_atlas:{topic_key}:{page-1}" in data, f"{topic_key} page={page}: missing prev button"
            if page < pages - 1:
                assert f"anatomy_atlas:{topic_key}:{page+1}" in data, f"{topic_key} page={page}: missing next button"
            assert f"anatomy_topic:{topic_key}" in data
            total_images_tested += len(media)
        print(f"{topic_key}: {len(images)} atlas images across {pages} page(s) OK")

    # 3. out-of-range page -> alert, no crash
    cb = FakeCB("anatomy_atlas:trunk_joints:999")
    await tb.cb_anatomy_atlas(cb)
    assert not cb.message.media_groups
    assert cb._answers and cb._answers[-1][1] is True
    print("out-of-range page -> alert OK")

    # 4. topic without atlas_images -> alert, no crash
    cb = FakeCB("anatomy_atlas:general_joints:0")
    await tb.cb_anatomy_atlas(cb)
    assert not cb.message.media_groups
    assert cb._answers and cb._answers[-1][1] is True
    print("topic without atlas_images -> alert OK")

    print(f"\nTotal atlas images functionally tested: {total_images_tested}")
    if errors:
        print("ERRORS:")
        for e in errors[:30]:
            print(" -", e)
        sys.exit(1)
    print("ALL ANATOMY ATLAS TESTS PASSED")

asyncio.run(main())
