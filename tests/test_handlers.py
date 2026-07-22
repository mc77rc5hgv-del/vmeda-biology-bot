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
        self.message_id = 1
        self.chat = type("C", (), {"id": 1})()
    async def edit_text(self, text, **kwargs):
        self.edits.append(text)
        return self
    async def delete(self):
        pass
    async def answer_media_group(self, media, **kwargs):
        self.media_groups.append(media)
        return [self] * len(media)
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
    topic_key = "skull"
    topic = tb.get_anatomy_topic_data(topic_key)
    bones = topic["bones_list"]

    # anatomy_bones:
    cb = FakeCB(f"anatomy_bones:{topic_key}")
    await tb.cb_anatomy_bones(cb)
    assert cb.message.edits, "no edit for anatomy_bones"

    for bone in bones:
        bid = bone["id"]
        cb = FakeCB(f"anatomy_bone_hub:{topic_key}:{bid}")
        await tb.cb_anatomy_bone_hub(cb)
        assert cb.message.edits

        # material page 0 (some pseudo-bones like "general"/"whole_skull" are photo-only, no material)
        has_material = bool(tb.get_bone_material_list(topic_key, bid))
        cb = FakeCB(f"anatomy_bone_material:{topic_key}:{bid}:0")
        await tb.cb_anatomy_bone_material(cb)
        if has_material:
            assert cb.message.edits
        else:
            assert cb._answers and cb._answers[0][1] is True

        # images (real photos now, sent as a native Telegram album)
        cb = FakeCB(f"anatomy_bone_slides:{topic_key}:{bid}:0")
        await tb.cb_anatomy_bone_slides(cb)
        assert cb.message.media_groups, f"{bid} should have at least one slide"

        # flashcards
        fcards = tb.get_bone_flashcards(topic_key, bid)
        cb = FakeCB(f"anatomy_bone_flash_start:{topic_key}:{bid}")
        await tb.cb_anatomy_bone_flash_start(cb)
        if fcards:
            assert cb.message.edits, f"{bid} flash start should render"
            uid = cb.from_user.id
            # simulate showing answer + know
            cb2 = FakeCB("anatomy_flash_show_answer", uid)
            await tb.cb_anatomy_flash_show_answer(cb2)
            cb3 = FakeCB("anatomy_flash_know", uid)
            await tb.cb_anatomy_flash_answer(cb3)
            # stop it to clean session
            cb4 = FakeCB("anatomy_flash_stop", uid)
            await tb.cb_anatomy_flash_stop(cb4)
        else:
            assert cb._answers and cb._answers[0][1] is True, f"{bid} should alert no cards"

        # matching
        pairs = tb.get_bone_pairs(topic_key, bid)
        cb = FakeCB(f"anatomy_bone_match_start:{topic_key}:{bid}")
        await tb.cb_anatomy_bone_match_start(cb)
        if pairs:
            assert cb.message.edits, f"{bid} match start should render"
            uid = cb.from_user.id
            sess = tb.ANATOMY_MATCH_SESSIONS.get(uid)
            assert sess is not None
            correct_idx = sess["current_correct_idx"]
            cb2 = FakeCB(f"anatomy_match_answer:{correct_idx}", uid)
            await tb.cb_anatomy_match_answer(cb2)
            cb3 = FakeCB("anatomy_match_stop", uid)
            await tb.cb_anatomy_match_stop(cb3)
        else:
            assert cb._answers and cb._answers[0][1] is True, f"{bid} should alert no pairs"

        # mnemonics
        mnemos = tb.get_bone_mnemonics(topic_key, bid)
        cb = FakeCB(f"anatomy_bone_mnemonics:{topic_key}:{bid}:0")
        await tb.cb_anatomy_bone_mnemonics(cb)
        if mnemos:
            assert cb.message.edits, f"{bid} mnemonics should render"
        else:
            assert cb._answers and cb._answers[0][1] is True, f"{bid} should alert no mnemonics"

        print(f"handler-OK {bid}")

    # non-admin access should be blocked (ANATOMY_PUBLIC=False)
    cb = FakeCB(f"anatomy_bone_hub:{topic_key}:frontal", uid=123456789)
    await tb.cb_anatomy_bone_hub(cb)
    assert not cb.message.edits and cb._answers[0][1] is True
    print("access-control OK")

    # pooled (non-bone) match/flash still work end to end through real handlers
    cb = FakeCB(f"anatomy_flash_start:{topic_key}")
    await tb.cb_anatomy_flash_start(cb)
    assert cb.message.edits
    uid = cb.from_user.id
    cb2 = FakeCB("anatomy_flash_stop", uid)
    await tb.cb_anatomy_flash_stop(cb2)

    cb = FakeCB(f"anatomy_match_start:{topic_key}")
    await tb.cb_anatomy_match_start(cb)
    assert cb.message.edits
    uid = cb.from_user.id
    sess = tb.ANATOMY_MATCH_SESSIONS.get(uid)
    correct_idx = sess["current_correct_idx"]
    cb2 = FakeCB(f"anatomy_match_answer:{correct_idx}", uid)
    await tb.cb_anatomy_match_answer(cb2)
    cb3 = FakeCB("anatomy_match_stop", uid)
    await tb.cb_anatomy_match_stop(cb3)
    print("pooled-mode-handlers OK")

    # latin terms trainer (skull only, for now)
    latin_terms = tb.get_topic_latin_terms(topic_key)
    assert len(latin_terms) >= 30, "skull should have a sizable latin term bank"
    cb = FakeCB(f"anatomy_latin_start:{topic_key}")
    await tb.cb_anatomy_latin_start(cb)
    assert cb.message.edits
    uid = cb.from_user.id
    sess = tb.ANATOMY_LATIN_SESSIONS.get(uid)
    assert sess is not None
    correct_idx = sess["current_correct_idx"]
    correct_term = sess["queue"][sess["index"]]
    assert sess["current_options"][correct_idx] == correct_term["ru"]

    # wrong answer -> alert with correct translation, session continues
    wrong_idx = (correct_idx + 1) % len(sess["current_options"])
    cb2 = FakeCB(f"anatomy_latin_answer:{wrong_idx}", uid)
    await tb.cb_anatomy_latin_answer(cb2)
    assert cb2._answers and cb2._answers[0][1] is True and "Неверно" in cb2._answers[0][0]
    assert sess["wrong"] == 1

    cb3 = FakeCB("anatomy_latin_stop", uid)
    await tb.cb_anatomy_latin_stop(cb3)
    assert uid not in tb.ANATOMY_LATIN_SESSIONS

    # topic with no latin_terms -> graceful alert, not a crash
    cb4 = FakeCB("anatomy_latin_start:trunk_bones")
    await tb.cb_anatomy_latin_start(cb4)
    assert cb4._answers and cb4._answers[0][1] is True
    print("latin terms trainer OK")

    print("ALL HANDLER TESTS PASSED")

asyncio.run(main())
