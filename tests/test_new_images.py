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

def check_media_group(errors, label, media_list):
    for m in media_list:
        photo = m.media
        if isinstance(photo, tb.FSInputFile):
            if not os.path.exists(photo.path):
                errors.append(f"{label}: file missing: {photo.path}")
        elif not (isinstance(photo, str) and photo.startswith("http")):
            errors.append(f"{label}: unexpected photo type: {type(photo)} {photo!r}")
        if m.caption and len(m.caption) > 1024:
            errors.append(f"{label}: caption too long: {len(m.caption)}")

def check_single_photo(errors, label, photo, caption):
    if isinstance(photo, tb.FSInputFile):
        if not os.path.exists(photo.path):
            errors.append(f"{label}: file missing: {photo.path}")
    elif not (isinstance(photo, str) and photo.startswith("http")):
        errors.append(f"{label}: unexpected photo type: {type(photo)} {photo!r}")
    if caption and len(caption) > 1024:
        errors.append(f"{label}: caption too long: {len(caption)}")

async def main():
    errors = []
    total_images_tested = 0

    for topic_key in ("trunk_bones", "upper_limb_bones", "skull"):
        topic = tb.get_anatomy_topic_data(topic_key)
        for bone in topic["bones_list"]:
            bid = bone["id"]
            for kind, cb_fn, prefix in (
                ("slides", tb.cb_anatomy_bone_slides, "anatomy_bone_slides"),
                ("atlas", tb.cb_anatomy_bone_atlas, "anatomy_bone_atlas"),
            ):
                images = tb.get_bone_images(topic_key, bid, kind=kind)
                n_pages = max(1, (len(images) + tb.ANATOMY_ALBUM_PAGE_SIZE - 1) // tb.ANATOMY_ALBUM_PAGE_SIZE) if images else 0
                for page in range(n_pages):
                    cb = FakeCB(f"{prefix}:{topic_key}:{bid}:{page}")
                    await cb_fn(cb)
                    expected = min(tb.ANATOMY_ALBUM_PAGE_SIZE, len(images) - page * tb.ANATOMY_ALBUM_PAGE_SIZE)
                    label = f"{topic_key}/{bid}/{kind} page={page}"
                    if not cb.message.deleted or not (cb.message.media_groups or cb.message.photos):
                        errors.append(f"{label}: no photo(s) sent")
                        continue
                    if expected == 1:
                        # Telegram's sendMediaGroup needs >=2 items — a lone photo on a page
                        # goes through answer_photo instead.
                        if not cb.message.photos:
                            errors.append(f"{label}: single-image page must use answer_photo")
                            continue
                        photo, caption = cb.message.photos[0]
                        check_single_photo(errors, label, photo, caption)
                        total_images_tested += 1
                    else:
                        if not cb.message.media_groups:
                            errors.append(f"{label}: no album sent")
                            continue
                        media = cb.message.media_groups[0]
                        if len(media) != expected:
                            errors.append(f"{label}: expected {expected} photos, got {len(media)}")
                        check_media_group(errors, label, media)
                        total_images_tested += len(media)
                    # a follow-up text message with nav/back buttons must always be sent
                    if not cb.message.edits:
                        errors.append(f"{label}: no nav message sent")
        print(f"{topic_key}: {len(topic['bones_list'])} bones OK")

    # section navigation: trunk_bones and upper_limb_bones must appear under osteology menu
    cb = FakeCB("anatomy_section:osteology")
    await tb.cb_anatomy_section(cb)
    assert cb.message.edits

    # bone hub text should reflect slides/atlas counts correctly, split by source
    hub_text = tb.get_anatomy_bone_hub_text("trunk_bones", "columna_vertebralis")
    assert "Атлас (Неттер/Гайворонский): 1" in hub_text, hub_text

    hub_text2 = tb.get_anatomy_bone_hub_text("skull", "whole_skull")
    assert "Слайдов презентации:" in hub_text2 and "Атлас (Неттер/Гайворонский):" in hub_text2, hub_text2

    print(f"\nTotal images functionally tested: {total_images_tested}")
    if errors:
        print("ERRORS:")
        for e in errors[:30]:
            print(" -", e)
        sys.exit(1)
    print("ALL NEW IMAGE TESTS PASSED")

asyncio.run(main())
