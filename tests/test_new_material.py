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
    async def edit_text(self, text, **kwargs):
        self.edits.append(text)
        return self
    async def delete(self):
        pass
    async def answer(self, text, **kwargs):
        self.edits.append(text)
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
    for topic_key in ("trunk_bones", "upper_limb_bones", "skull"):
        topic = tb.get_anatomy_topic_data(topic_key)
        for bone in topic["bones_list"]:
            bid = bone["id"]
            pages = tb.get_bone_material_list(topic_key, bid)
            if not pages:
                errors.append(f"{topic_key}/{bid}: NO material pages")
                continue
            for idx in range(len(pages)):
                cb = FakeCB(f"anatomy_bone_material:{topic_key}:{bid}:{idx}")
                await tb.cb_anatomy_bone_material(cb)
                if not cb.message.edits:
                    errors.append(f"{topic_key}/{bid} material idx={idx}: no render")
                    continue
                text = cb.message.edits[0]
                if len(text) > 4096:
                    errors.append(f"{topic_key}/{bid} material idx={idx}: too long {len(text)}")
        print(f"{topic_key}: {len(topic['bones_list'])} bones, material OK")

    if errors:
        print("ERRORS:")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    print("ALL MATERIAL TESTS PASSED")

asyncio.run(main())
