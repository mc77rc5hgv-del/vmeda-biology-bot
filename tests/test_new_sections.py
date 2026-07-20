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

    # 1. anatomy_menu should list all 3 sections
    cb = FakeCB("anatomy_menu")
    await tb.cb_anatomy_menu(cb)
    assert cb.message.edits, "anatomy_menu did not render"
    print("anatomy_menu OK")

    # 2. walk every section -> topic -> every material page
    for section_key, section in tb.ANATOMY.items():
        cb = FakeCB(f"anatomy_section:{section_key}")
        await tb.cb_anatomy_section(cb)
        if not cb.message.edits:
            errors.append(f"section {section_key} failed to render")
            continue
        print(f"section {section_key} OK ({len(section['topics'])} topics)")

        for topic_key, topic in section["topics"].items():
            cb = FakeCB(f"anatomy_topic:{topic_key}")
            await tb.cb_anatomy_topic(cb)
            if not cb.message.edits:
                errors.append(f"topic {topic_key} hub failed")
                continue

            n_pages = len(topic["material"])
            for idx in range(n_pages):
                cb = FakeCB(f"anatomy_material:{topic_key}:{idx}")
                await tb.cb_anatomy_material(cb)
                if not cb.message.edits:
                    errors.append(f"{topic_key} material idx={idx} failed to render")
                    continue
                text = cb.message.edits[0]
                if len(text) > 4096:
                    errors.append(f"{topic_key} material idx={idx} rendered text too long: {len(text)}")

            # material list keyboard
            cb = FakeCB(f"anatomy_material_list:{topic_key}")
            await tb.cb_anatomy_material_list(cb)
            if not cb.message.edits:
                errors.append(f"{topic_key} material_list failed")

            print(f"  topic {topic_key}: {n_pages} pages OK")

    # 3. skull's per-bone subdivisions should still work (regression check)
    cb = FakeCB("anatomy_bones:skull")
    await tb.cb_anatomy_bones(cb)
    assert cb.message.edits, "skull bones list broken"
    print("skull bones list still OK (regression check)")

    # 4. non-admin should be blocked everywhere (ANATOMY_PUBLIC=False)
    cb = FakeCB("anatomy_section:myology", uid=123456789)
    await tb.cb_anatomy_section(cb)
    assert not cb.message.edits and cb._answers[0][1] is True
    print("access-control OK")

    if errors:
        print("ERRORS FOUND:")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    print("ALL NEW-SECTION TESTS PASSED")

asyncio.run(main())
