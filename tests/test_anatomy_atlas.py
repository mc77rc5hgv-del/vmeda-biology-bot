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
    async def answer_photo(self, photo, **kwargs):
        self.photos.append((photo, kwargs.get("caption"), kwargs.get("reply_markup")))
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

    # 2. every atlas image renders: real file, caption, credit, correct nav
    for section_key, topic_key in topics_with_atlas:
        images = tb.get_topic_atlas_images(topic_key)
        for idx in range(len(images)):
            cb = FakeCB(f"anatomy_atlas:{topic_key}:{idx}")
            await tb.cb_anatomy_atlas(cb)
            if not cb.message.deleted or not cb.message.photos:
                errors.append(f"{topic_key} idx={idx}: no photo sent")
                continue
            photo, caption, kb = cb.message.photos[0]
            if isinstance(photo, tb.FSInputFile):
                if not os.path.exists(photo.path):
                    errors.append(f"{topic_key} idx={idx}: file missing: {photo.path}")
            else:
                errors.append(f"{topic_key} idx={idx}: unexpected photo type: {type(photo)}")
            if not caption or "Источник:" not in caption:
                errors.append(f"{topic_key} idx={idx}: caption missing credit line")
            data = kb_data(kb)
            if idx > 0:
                assert f"anatomy_atlas:{topic_key}:{idx-1}" in data, f"{topic_key} idx={idx}: missing prev button"
            else:
                assert not any(d and d.startswith(f"anatomy_atlas:{topic_key}:") and d.endswith(":-1") for d in data)
            if idx < len(images) - 1:
                assert f"anatomy_atlas:{topic_key}:{idx+1}" in data, f"{topic_key} idx={idx}: missing next button"
            assert f"anatomy_topic:{topic_key}" in data
            total_images_tested += 1
        print(f"{topic_key}: {len(images)} atlas images OK")

    # 3. out-of-range / missing index -> alert, no crash
    cb = FakeCB("anatomy_atlas:trunk_joints:999")
    await tb.cb_anatomy_atlas(cb)
    assert not cb.message.photos
    assert cb._answers and cb._answers[-1][1] is True
    print("out-of-range index -> alert OK")

    cb = FakeCB("anatomy_atlas:general_joints:0")
    await tb.cb_anatomy_atlas(cb)
    assert not cb.message.photos
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
