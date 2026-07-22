# -*- coding: utf-8 -*-
"""Generic coverage test for the per-bone Latin terminology trainer — walks every
bone-hub topic (skull, trunk_bones, upper_limb_bones, lower_limb_bones) and every
bone in its bones_list, not a hand-picked list, so newly added terms are automatically
exercised here."""
import asyncio
from _bootstrap import tb

ADMIN_ID = next(iter(tb.ADMIN_IDS))

BONE_HUB_TOPICS = ("skull", "trunk_bones", "upper_limb_bones", "lower_limb_bones")

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
    total_terms_tested = 0
    bones_with_terms = 0
    bones_without_terms = 0

    for topic_key in BONE_HUB_TOPICS:
        topic = tb.get_anatomy_topic_data(topic_key)
        pooled_terms = tb.get_topic_latin_terms(topic_key)
        assert pooled_terms, f"{topic_key}: expected a non-empty pooled latin_terms list"

        for term in pooled_terms:
            if not term.get("la", "").strip() or not term.get("ru", "").strip():
                errors.append(f"{topic_key}: latin term with empty la/ru: {term}")
            if not term.get("bone"):
                errors.append(f"{topic_key}: latin term missing bone tag: {term}")
            elif term["bone"] not in {b["id"] for b in topic["bones_list"]}:
                errors.append(f"{topic_key}: latin term tagged to unknown bone {term['bone']!r}")

        for bone in topic["bones_list"]:
            bone_id = bone["id"]
            bone_terms = tb.get_bone_latin_terms(topic_key, bone_id)

            cb = FakeCB(f"anatomy_bone_latin_start:{topic_key}:{bone_id}")
            await tb.cb_anatomy_bone_latin_start(cb)

            if not bone_terms:
                bones_without_terms += 1
                if not (cb._answers and cb._answers[0][1] is True):
                    errors.append(f"{topic_key}/{bone_id}: expected graceful alert for empty term list")
                continue

            bones_with_terms += 1
            if not cb.message.edits:
                errors.append(f"{topic_key}/{bone_id}: latin session failed to start")
                continue
            uid = cb.from_user.id
            sess = tb.ANATOMY_LATIN_SESSIONS.get(uid)
            if sess is None:
                errors.append(f"{topic_key}/{bone_id}: no session created")
                continue
            if sess["bone_id"] != bone_id:
                errors.append(f"{topic_key}/{bone_id}: session bone_id mismatch")
            if not all(t["bone"] == bone_id for t in sess["queue"]):
                errors.append(f"{topic_key}/{bone_id}: session queue leaked terms from other bones")

            # answer the current question correctly, then stop
            correct_idx = sess["current_correct_idx"]
            cb2 = FakeCB(f"anatomy_latin_answer:{correct_idx}", uid)
            await tb.cb_anatomy_latin_answer(cb2)
            if uid in tb.ANATOMY_LATIN_SESSIONS:
                cb3 = FakeCB("anatomy_latin_stop", uid)
                await tb.cb_anatomy_latin_stop(cb3)
            if uid in tb.ANATOMY_LATIN_SESSIONS:
                errors.append(f"{topic_key}/{bone_id}: session not cleaned up")

            # bone hub keyboard should show the latin trainer button
            kb = tb.get_anatomy_bone_hub_keyboard(topic_key, bone_id)
            data = [b.callback_data for row in kb.inline_keyboard for b in row]
            if f"anatomy_bone_latin_start:{topic_key}:{bone_id}" not in data:
                errors.append(f"{topic_key}/{bone_id}: hub keyboard missing latin trainer button")

            total_terms_tested += len(bone_terms)

        print(f"{topic_key}: {len(pooled_terms)} pooled terms across {len(topic['bones_list'])} bones OK")

    print(f"\nBones with latin terms: {bones_with_terms}, without: {bones_without_terms}")
    print(f"Total per-bone terms tested: {total_terms_tested}")

    if errors:
        print("ERRORS:")
        for e in errors[:40]:
            print(" -", e)
        raise SystemExit(1)
    print("ALL BONE LATIN TERM TESTS PASSED")

asyncio.run(main())
