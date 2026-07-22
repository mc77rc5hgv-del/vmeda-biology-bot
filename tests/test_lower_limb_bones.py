# -*- coding: utf-8 -*-
import asyncio
from _bootstrap import tb
from html.parser import HTMLParser

ADMIN_ID = next(iter(tb.ADMIN_IDS))

class C(HTMLParser):
    def __init__(self):
        super().__init__(); self.stack=[]; self.problems=[]
    def handle_starttag(self, tag, attrs): self.stack.append(tag)
    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag: self.problems.append(tag)
        else: self.stack.pop()

def check_html(text):
    c = C(); c.feed(text)
    assert not c.stack and not c.problems, (text[:200], c.stack, c.problems)
    assert len(text) <= 4096, len(text)

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

def kb_texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row]

async def main():
    # 1. topic exists, right place in osteology ordering, right count
    osteology_topics = list(tb.ANATOMY["osteology"]["topics"].keys())
    assert osteology_topics == ["skull", "trunk_bones", "upper_limb_bones", "lower_limb_bones"]
    llb = tb.ANATOMY["osteology"]["topics"]["lower_limb_bones"]
    assert len(llb["material"]) == 7
    print("lower_limb_bones is registered in the right osteology order: OK")

    # 2. every material page: HTML-balanced, has Latin italics, reasonable length
    for p in llb["material"]:
        check_html(p["content"])
        assert "<i>" in p["content"], f"{p['id']} has no Latin terms"
        assert len(p["content"]) >= 300, f"{p['id']} too thin"
    print("all 7 pages HTML-balanced with Latin terms, not too thin: OK")

    # 3. section -> topic -> bones list navigation via real handlers
    cb = FakeCB("anatomy_section:osteology")
    await tb.cb_anatomy_section(cb)
    assert cb.message.edits
    print("anatomy_section:osteology renders: OK")

    cb2 = FakeCB("anatomy_topic:lower_limb_bones")
    await tb.cb_anatomy_topic(cb2)
    assert cb2.message.edits, "topic hub should render"
    print("anatomy_topic:lower_limb_bones renders: OK")

    cb3 = FakeCB("anatomy_bones:lower_limb_bones")
    await tb.cb_anatomy_bones(cb3)
    assert cb3.message.edits, "bones list should render"
    print("anatomy_bones:lower_limb_bones renders: OK")

    # 4. every bone hub + its material page render correctly
    for bone in llb["bones_list"]:
        bid = bone["id"]
        cb_hub = FakeCB(f"anatomy_bone_hub:lower_limb_bones:{bid}")
        await tb.cb_anatomy_bone_hub(cb_hub)
        assert cb_hub.message.edits, f"bone hub {bid} failed"
        check_html(cb_hub.message.edits[0])

        cb_mat = FakeCB(f"anatomy_bone_material:lower_limb_bones:{bid}:0")
        await tb.cb_anatomy_bone_material(cb_mat)
        assert cb_mat.message.edits, f"bone material {bid} failed"
        check_html(cb_mat.message.edits[0])
    print("every bone hub (7) + material page renders correctly: OK")

    # 5. no images/flashcards/mnemonics/pairs -> graceful alert, not a crash
    # (patella still has no photos yet, unlike femur/pelvis/hip_bone/foot_bones)
    cb_slides = FakeCB("anatomy_bone_slides:lower_limb_bones:patella:0")
    await tb.cb_anatomy_bone_slides(cb_slides)
    assert not cb_slides.message.edits
    assert cb_slides._answers and "нет" in (cb_slides._answers[0][0] or "")

    cb_atlas = FakeCB("anatomy_bone_atlas:lower_limb_bones:patella:0")
    await tb.cb_anatomy_bone_atlas(cb_atlas)
    assert not cb_atlas.message.edits
    assert cb_atlas._answers and "нет" in (cb_atlas._answers[0][0] or "")

    cb_flash = FakeCB("anatomy_bone_flash_start:lower_limb_bones:femur")
    await tb.cb_anatomy_bone_flash_start(cb_flash)
    assert not cb_flash.message.edits

    cb_match = FakeCB("anatomy_bone_match_start:lower_limb_bones:femur")
    await tb.cb_anatomy_bone_match_start(cb_match)
    assert not cb_match.message.edits

    cb_mnemo = FakeCB("anatomy_bone_mnemonics:lower_limb_bones:femur:0")
    await tb.cb_anatomy_bone_mnemonics(cb_mnemo)
    assert not cb_mnemo.message.edits
    print("empty images/flashcards/matching/mnemonics degrade gracefully (no crash): OK")

    # 6. non-admin blocked (ANATOMY_PUBLIC=False, no subscription)
    non_admin = 918273645
    cb_na = FakeCB("anatomy_topic:lower_limb_bones", uid=non_admin)
    await tb.cb_anatomy_topic(cb_na)
    assert not cb_na.message.edits
    print("non-admin blocked on lower_limb_bones: OK")

    # 7. the "Кости черепа" hardcoded label bug is fixed for non-skull topics
    kb_trunk = tb.get_anatomy_topic_keyboard("trunk_bones")
    kb_llb = tb.get_anatomy_topic_keyboard("lower_limb_bones")
    assert not any("Кости черепа" in t for t in kb_texts(kb_trunk))
    assert not any("Кости черепа" in t for t in kb_texts(kb_llb))
    assert any("Разбор по каждой кости" in t for t in kb_texts(kb_llb))
    print("bones-list button label no longer hardcoded to 'Кости черепа': OK")

    print("ALL LOWER-LIMB-BONES TESTS PASSED")

asyncio.run(main())
