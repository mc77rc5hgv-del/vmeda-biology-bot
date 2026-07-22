# -*- coding: utf-8 -*-
"""Generic coverage test for pooled (non-bone) flashcards/matching_sets/mnemonics —
walks every topic in ANATOMY, not a hand-picked list, so content added to any new
section (arthrology, myology, splanchnology, ...) is automatically exercised here."""
import asyncio
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
    topics_with_flashcards = 0
    topics_with_matching = 0
    topics_with_mnemonics = 0

    for section_key, section in tb.ANATOMY.items():
        for topic_key, topic in section.get("topics", {}).items():
            flashcards = topic.get("flashcards") or []
            matching_pairs = tb.get_anatomy_all_pairs(topic_key)
            mnemonics = topic.get("mnemonics") or []

            # ---- flashcards: content quality + end-to-end session ----
            if flashcards:
                topics_with_flashcards += 1
                fronts = [fc["front"] for fc in flashcards]
                if len(fronts) != len(set(fronts)):
                    errors.append(f"{topic_key}: duplicate flashcard fronts")
                for fc in flashcards:
                    if not fc.get("front", "").strip() or not fc.get("back", "").strip():
                        errors.append(f"{topic_key}: flashcard with empty front/back")

                cb = FakeCB(f"anatomy_flash_start:{topic_key}")
                await tb.cb_anatomy_flash_start(cb)
                if not cb.message.edits:
                    errors.append(f"{topic_key}: flash session failed to start")
                else:
                    uid = cb.from_user.id
                    cb2 = FakeCB("anatomy_flash_show_answer", uid)
                    await tb.cb_anatomy_flash_show_answer(cb2)
                    cb3 = FakeCB("anatomy_flash_know", uid)
                    await tb.cb_anatomy_flash_answer(cb3)
                    cb4 = FakeCB("anatomy_flash_stop", uid)
                    await tb.cb_anatomy_flash_stop(cb4)
                    if uid in tb.ANATOMY_FLASH_SESSIONS:
                        errors.append(f"{topic_key}: flash session not cleaned up after stop")

            # ---- matching sets: content quality + end-to-end session ----
            if matching_pairs:
                topics_with_matching += 1
                for p in matching_pairs:
                    if not p.get("term", "").strip() or not p.get("definition", "").strip():
                        errors.append(f"{topic_key}: matching pair with empty term/definition")
                    if p["term"].strip() == p["definition"].strip():
                        errors.append(f"{topic_key}: matching pair term == definition")

                cb = FakeCB(f"anatomy_match_start:{topic_key}")
                await tb.cb_anatomy_match_start(cb)
                if not cb.message.edits:
                    errors.append(f"{topic_key}: match session failed to start")
                else:
                    uid = cb.from_user.id
                    sess = tb.ANATOMY_MATCH_SESSIONS.get(uid)
                    if sess is None:
                        errors.append(f"{topic_key}: no match session created")
                    else:
                        correct_idx = sess["current_correct_idx"]
                        cb2 = FakeCB(f"anatomy_match_answer:{correct_idx}", uid)
                        await tb.cb_anatomy_match_answer(cb2)
                        cb3 = FakeCB("anatomy_match_stop", uid)
                        await tb.cb_anatomy_match_stop(cb3)
                        if uid in tb.ANATOMY_MATCH_SESSIONS:
                            errors.append(f"{topic_key}: match session not cleaned up after stop")

            # ---- mnemonics: content quality + paging ----
            if mnemonics:
                topics_with_mnemonics += 1
                for mn in mnemonics:
                    if not mn.get("title", "").strip() or not mn.get("text", "").strip():
                        errors.append(f"{topic_key}: mnemonic with empty title/text")

                for idx in range(len(mnemonics)):
                    cb = FakeCB(f"anatomy_mnemonics:{topic_key}:{idx}")
                    await tb.cb_anatomy_mnemonics(cb)
                    if not cb.message.edits:
                        errors.append(f"{topic_key}: mnemonic page {idx} failed to render")

    print(f"topics with flashcards: {topics_with_flashcards}")
    print(f"topics with matching pairs: {topics_with_matching}")
    print(f"topics with mnemonics: {topics_with_mnemonics}")

    if errors:
        print("ERRORS:")
        for e in errors[:40]:
            print(" -", e)
        raise SystemExit(1)
    print("ALL TOPIC STUDY-AID TESTS PASSED")

asyncio.run(main())
