# -*- coding: utf-8 -*-
import os, sys, json
from _bootstrap import tb

topic_key = "skull"
topic = tb.get_anatomy_topic_data(topic_key)
bones = topic["bones_list"]
print("bones:", len(bones))

errors = []

for bone in bones:
    bid = bone["id"]
    try:
        hub_text = tb.get_anatomy_bone_hub_text(topic_key, bid)
        hub_kb = tb.get_anatomy_bone_hub_keyboard(topic_key, bid)
        pages = tb.get_bone_material_list(topic_key, bid)
        assert len(pages) >= 1, f"{bid}: no material pages"
        for i in range(len(pages)):
            txt = tb.get_bone_material_text(topic_key, bid, i)
            kb = tb.get_bone_material_keyboard(topic_key, bid, i)
            assert len(txt) <= 4096, f"{bid} material {i} too long: {len(txt)}"

        # flashcards
        fcards = tb.get_bone_flashcards(topic_key, bid)
        uid = 999000 + hash(bid) % 1000
        tb.start_anatomy_flash_session(uid, topic_key, bone_id=bid)
        sess = tb.ANATOMY_FLASH_SESSIONS.get(uid)
        if fcards:
            assert sess is not None and len(sess["cards"]) == min(tb.ANATOMY_FLASH_SESSION_SIZE, len(fcards))
            assert sess["bone_id"] == bid
            kb = tb.get_anatomy_flash_summary_keyboard(topic_key, bid)
        else:
            assert sess is not None and len(sess["cards"]) == 0
        tb.ANATOMY_FLASH_SESSIONS.pop(uid, None)

        # matching
        pairs = tb.get_bone_pairs(topic_key, bid)
        tb.start_anatomy_match_session(uid, topic_key, bone_id=bid)
        msess = tb.ANATOMY_MATCH_SESSIONS.get(uid)
        assert msess["bone_id"] == bid
        assert len(msess["queue"]) == min(tb.ANATOMY_MATCH_SESSION_SIZE, len(pairs))
        if pairs:
            # simulate rendering question (sync logic without safe_edit_text network call)
            pair = msess["queue"][0]
            term, correct_def = pair["term"], pair["definition"]
            distractor_pool = [p["definition"] for p in msess["all_pairs"] if p["definition"] != correct_def]
            assert isinstance(term, str) and isinstance(correct_def, str)
        tb.ANATOMY_MATCH_SESSIONS.pop(uid, None)

        # mnemonics
        mnemos = tb.get_bone_mnemonics(topic_key, bid)
        if mnemos:
            for i in range(len(mnemos)):
                txt = tb.get_bone_mnemonic_text(topic_key, bid, i)
                kb = tb.get_bone_mnemonics_keyboard(topic_key, bid, i)

        print(f"OK {bid:20s} material={len(pages)} flash={len(fcards)} pairs={len(pairs)} mnemo={len(mnemos)}")
    except Exception as e:
        errors.append((bid, str(e)))
        print(f"FAIL {bid}: {e}")

print()
if errors:
    print("ERRORS:", errors)
else:
    print("ALL BONES OK")

# also test whole-topic (unfiltered) pooled mode still works after dict conversion
tb.start_anatomy_match_session(555111, topic_key)
msess = tb.ANATOMY_MATCH_SESSIONS[555111]
assert msess["bone_id"] is None
pair = msess["queue"][0]
term, correct_def = pair["term"], pair["definition"]
distractor_pool = [p["definition"] for p in msess["all_pairs"] if p["definition"] != correct_def]
distractors = tb.random.sample(distractor_pool, min(3, len(distractor_pool)))
print("pooled match OK, term:", term[:40])
tb.ANATOMY_MATCH_SESSIONS.pop(555111, None)

tb.start_anatomy_flash_session(555111, topic_key)
fsess = tb.ANATOMY_FLASH_SESSIONS[555111]
assert fsess["bone_id"] is None
assert len(fsess["cards"]) == min(tb.ANATOMY_FLASH_SESSION_SIZE, len(topic["flashcards"]))
print("pooled flash OK")
tb.ANATOMY_FLASH_SESSIONS.pop(555111, None)

print("DONE")
