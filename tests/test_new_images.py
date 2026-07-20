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
    errors = []
    total_images_tested = 0

    for topic_key in ("trunk_bones", "upper_limb_bones", "skull"):
        topic = tb.get_anatomy_topic_data(topic_key)
        for bone in topic["bones_list"]:
            bid = bone["id"]
            images = tb.get_bone_images(topic_key, bid)
            for idx in range(len(images)):
                cb = FakeCB(f"anatomy_bone_img:{topic_key}:{bid}:{idx}")
                await tb.cb_anatomy_bone_img(cb)
                if not cb.message.deleted or not cb.message.photos:
                    errors.append(f"{topic_key}/{bid} idx={idx}: no photo sent")
                    continue
                photo, caption = cb.message.photos[0]
                if isinstance(photo, tb.FSInputFile):
                    if not os.path.exists(photo.path):
                        errors.append(f"{topic_key}/{bid} idx={idx}: file missing: {photo.path}")
                elif not (isinstance(photo, str) and photo.startswith("http")):
                    errors.append(f"{topic_key}/{bid} idx={idx}: unexpected photo type: {type(photo)} {photo!r}")
                if len(caption) > 1024:
                    errors.append(f"{topic_key}/{bid} idx={idx}: caption too long: {len(caption)}")
                total_images_tested += 1
        print(f"{topic_key}: {len(topic['bones_list'])} bones OK")

    # section navigation: trunk_bones and upper_limb_bones must appear under osteology menu
    cb = FakeCB("anatomy_section:osteology")
    await tb.cb_anatomy_section(cb)
    assert cb.message.edits

    # bone hub text should reflect image counts correctly
    hub_text = tb.get_anatomy_bone_hub_text("trunk_bones", "columna_vertebralis")
    assert "Фото и схем: 2" in hub_text, hub_text

    hub_text2 = tb.get_anatomy_bone_hub_text("skull", "whole_skull")
    assert "Фото и схем: 20" in hub_text2, hub_text2

    print(f"\nTotal images functionally tested: {total_images_tested}")
    if errors:
        print("ERRORS:")
        for e in errors[:30]:
            print(" -", e)
        sys.exit(1)
    print("ALL NEW IMAGE TESTS PASSED")

asyncio.run(main())
