# -*- coding: utf-8 -*-
import os, sys, asyncio, random
from _bootstrap import tb
from html.parser import HTMLParser
from aiogram.types import FSInputFile

ADMIN_ID = next(iter(tb.ADMIN_IDS))

class C(HTMLParser):
    def __init__(self):
        super().__init__(); self.stack=[]; self.problems=[]
    def handle_starttag(self, tag, attrs): self.stack.append(tag)
    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag: self.problems.append(tag)
        else: self.stack.pop()

class FakeUser:
    def __init__(self, uid):
        self.id = uid

class FakeMsg:
    def __init__(self):
        self.edits = []
        self.photos = []
        self.deleted = False
        self.caption_edits = []
    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self
    async def edit_caption(self, **kwargs):
        self.caption_edits.append((kwargs.get("caption"), kwargs.get("reply_markup")))
        return self
    async def delete(self):
        self.deleted = True
    async def answer(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self
    async def answer_photo(self, photo, **kwargs):
        self.photos.append((photo, kwargs.get("caption"), kwargs.get("reply_markup")))
        # Mirrors real aiogram: answer_photo returns a NEW Message object distinct
        # from the message it was called on (the original gets .delete()d elsewhere).
        new_msg = FakeMsg()
        new_msg.photos.append((photo, kwargs.get("caption"), kwargs.get("reply_markup")))
        return new_msg

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

def check_html(text):
    c = C(); c.feed(text)
    assert not c.stack and not c.problems, (text[:200], c.stack, c.problems)
    assert len(text) <= 4096, len(text)

async def main():
    # 1. Data integrity: every image path exists on disk, every specimen has protocol+images
    total_specimens = 0
    total_images = 0
    for diag_key, diag in tb.HISTOLOGY.items():
        assert diag["specimens"], f"{diag_key} has no specimens"
        for spec in diag["specimens"]:
            total_specimens += 1
            assert spec["protocol"], f"{diag_key}/{spec['id']} missing protocol"
            assert spec["images"], f"{diag_key}/{spec['id']} missing images"
            for img in spec["images"]:
                full = os.path.join(tb.HISTOLOGY_IMAGES_DIR, img)
                assert os.path.isfile(full), full
                total_images += 1
            # title/number sanity
            assert spec["title"], spec
            assert spec["number"], spec
    print(f"data integrity OK: {total_specimens} specimens, {total_images} images")

    # 1b. guess_image integrity: every set path exists on disk and is distinct from
    # a "known-bad" set of specimens verified by hand to still contain readable
    # labels/legend text in every available source photo.
    KNOWN_UNRELIABLE = {
        "d3_12", "d3_13", "d3_14", "d3_15", "d3_16", "d3_17", "d3_18", "d3_19",
        "d3_20", "d3_21", "d3_22", "d3_23", "d3_24", "d3_25", "d3_26", "d3_28",
        "d3_29", "d3_30", "d3_31", "d3_32", "d3_33", "d4_46", "d4_53",
    }
    n_guess = 0
    for diag_key, diag in tb.HISTOLOGY.items():
        for spec in diag["specimens"]:
            gi = spec.get("guess_image")
            if gi:
                n_guess += 1
                full = os.path.join(tb.HISTOLOGY_IMAGES_DIR, gi)
                assert os.path.isfile(full), full
                assert spec["id"] not in KNOWN_UNRELIABLE, f"{spec['id']} should not have a guess_image"
            else:
                assert spec["id"] in KNOWN_UNRELIABLE, f"{spec['id']} unexpectedly has no guess_image"
    assert n_guess == 48, n_guess
    print(f"guess_image integrity OK: {n_guess} specimens eligible for guess mode")

    # 2. Text rendering HTML-balance + length for every specimen
    for diag_key, diag in tb.HISTOLOGY.items():
        check_html(tb.get_histology_topic_text(diag_key))
        for spec in diag["specimens"]:
            check_html(tb.get_histology_specimen_text(diag_key, spec["id"]))
    print("all specimen/topic texts HTML-balanced and within length limit: OK")

    # 3. Menu keyboard has all 3 diagnostika
    kb = tb.get_histology_menu_keyboard()
    texts = kb_texts(kb)
    assert any("Цитология" in t for t in texts)
    assert len(tb.HISTOLOGY) == 5
    for n in range(2, 6):
        assert any(f"№{n}" in t for t in texts), (n, texts)
    print("menu keyboard OK:", texts)

    # 4. Access control: non-admin sees locked screen (not raw content) while HISTOLOGY_PUBLIC=False
    assert tb.HISTOLOGY_PUBLIC is False
    non_admin = random.randint(10_000_000, 99_999_999)
    cb = FakeCB("histology_menu", uid=non_admin)
    await tb.cb_histology_menu(cb)
    assert cb.message.edits, "locked screen should render"
    locked_text, locked_kb = cb.message.edits[0]
    check_html(locked_text)
    assert "по подписке" in locked_text and "239" in locked_text
    assert any("Оформить подписку" in t for t in kb_texts(locked_kb))
    print("non-admin sees histology locked screen with subscription info: OK")

    # 5. Admin flow: menu -> topic -> specimen -> image carousel (diagnostika_1, spec d1_01)
    cb1 = FakeCB("histology_menu")
    await tb.cb_histology_menu(cb1)
    assert cb1.message.edits, "expected menu render"
    print("admin sees histology menu: OK")

    cb2 = FakeCB("histology_topic:diagnostika_1")
    await tb.cb_histology_topic(cb2)
    assert cb2.message.edits
    topic_text, topic_kb = cb2.message.edits[0]
    assert "Диагностика №1" in topic_text
    assert any("№1." in t for t in kb_texts(topic_kb))
    print("topic view diagnostika_1: OK")

    cb3 = FakeCB("histology_specimen:diagnostika_1:d1_01")
    await tb.cb_histology_specimen(cb3)
    assert cb3.message.edits
    spec_text, spec_kb = cb3.message.edits[0]
    assert "Жировые включения" in spec_text
    assert "Осмиевая" in spec_text
    assert any("Микрофото" in t for t in kb_texts(spec_kb))
    print("specimen view d1_01: OK")

    cb4 = FakeCB("histology_img:diagnostika_1:d1_01:0")
    await tb.cb_histology_img(cb4)
    assert cb4.message.deleted
    assert cb4.message.photos, "expected a photo to be sent"
    photo, caption, img_kb = cb4.message.photos[0]
    assert isinstance(photo, FSInputFile)
    assert "1/1" in caption
    print("image carousel single-photo d1_01: OK")

    # 6. Multi-photo carousel navigation (diagnostika_2, d2_02 has 9 images)
    spec = tb.get_histology_specimen("diagnostika_2", "d2_02")
    assert len(spec["images"]) == 9
    cb5 = FakeCB("histology_img:diagnostika_2:d2_02:0")
    await tb.cb_histology_img(cb5)
    _, cap5, kb5 = cb5.message.photos[0]
    assert "1/9" in cap5
    assert not any(b.text == "⬅️" for row in kb5.inline_keyboard for b in row)
    assert any(b.text == "➡️" for row in kb5.inline_keyboard for b in row)

    cb6 = FakeCB("histology_img:diagnostika_2:d2_02:8")
    await tb.cb_histology_img(cb6)
    _, cap6, kb6 = cb6.message.photos[0]
    assert "9/9" in cap6
    assert any(b.text == "⬅️" for row in kb6.inline_keyboard for b in row)
    assert not any(b.text == "➡️" for row in kb6.inline_keyboard for b in row)
    print("multi-photo carousel nav d2_02: OK")

    # 7. Out-of-range image index rejected
    cb7 = FakeCB("histology_img:diagnostika_1:d1_01:5")
    await tb.cb_histology_img(cb7)
    assert cb7._answers and cb7._answers[0][1] is True and not cb7.message.photos
    print("out-of-range image index blocked: OK")

    # 8. Unknown topic/specimen rejected gracefully
    cb8 = FakeCB("histology_topic:diagnostika_99")
    await tb.cb_histology_topic(cb8)
    assert cb8._answers and cb8._answers[0][1] is True and not cb8.message.edits
    cb9 = FakeCB("histology_specimen:diagnostika_1:nope")
    await tb.cb_histology_specimen(cb9)
    assert cb9._answers and cb9._answers[0][1] is True and not cb9.message.edits
    print("unknown topic/specimen handled: OK")

    # 9. Diagnostika_3 complete (23/23) — no partial-progress note
    d3_text = tb.get_histology_topic_text("diagnostika_3")
    assert "<b>23</b>" in d3_text
    assert "добавим по мере поступления" not in d3_text
    print("diagnostika_3 complete, no partial-progress note: OK")

    # 9b. Diagnostika_4 complete at its achievable max (20/20, items 36/38 permanently
    # have no slide in the source presentation, so they're excluded from total_official)
    d4_text = tb.get_histology_topic_text("diagnostika_4")
    assert "<b>20</b>" in d4_text
    assert "добавим по мере поступления" not in d4_text
    specs4 = {s["number"] for s in tb.HISTOLOGY["diagnostika_4"]["specimens"]}
    assert 36 not in specs4 and 38 not in specs4
    assert specs4 == set(range(34, 56)) - {36, 38}
    print("diagnostika_4 complete (20 specimens, 36/38 permanently skipped): OK")

    # 9c. Diagnostika_5 complete (8/8), new topic
    d5_text = tb.get_histology_topic_text("diagnostika_5")
    assert "<b>8</b>" in d5_text
    assert "добавим по мере поступления" not in d5_text
    specs5 = {s["number"] for s in tb.HISTOLOGY["diagnostika_5"]["specimens"]}
    assert specs5 == set(range(56, 64))
    print("diagnostika_5 complete (8 specimens): OK")

    # 9d. Full perechen coverage: 61 of 63 official items achievable, all present
    all_numbers = set()
    for diag_key in ["diagnostika_2", "diagnostika_3", "diagnostika_4", "diagnostika_5"]:
        all_numbers |= {s["number"] for s in tb.HISTOLOGY[diag_key]["specimens"]}
    assert all_numbers == set(range(1, 64)) - {36, 38}
    print("full official perechen (items 1-63, minus no-slide 36/38) fully covered: OK")

    # 10. Main menu button: always visible, labeled per access level while HISTOLOGY_PUBLIC=False
    admin_menu = tb.get_main_menu(user_id=ADMIN_ID)
    assert "🔬 Гистология (админ)" in kb_texts(admin_menu)
    non_admin_menu = tb.get_main_menu(user_id=non_admin)
    assert "🔬 Гистология (по подписке)" in kb_texts(non_admin_menu)
    print("main menu gating: OK")

    # 11. is_gated_callback exempts histology (should behave like anatomy: never gated)
    assert not tb.is_gated_callback("histology_menu")
    assert not tb.is_gated_callback("histology_topic:diagnostika_1")
    assert not tb.is_gated_callback("histology_img:diagnostika_1:d1_01:0")
    assert not tb.is_gated_callback("histology_guess_start:all")
    print("histology callbacks exempt from referral gate: OK")

    # 12. Guess-the-specimen mode: non-admin blocked
    cb_g0 = FakeCB("histology_guess_start:all", uid=non_admin)
    await tb.cb_histology_guess_start(cb_g0)
    assert cb_g0._answers and cb_g0._answers[0][1] is True
    assert not cb_g0.message.deleted and not cb_g0.message.photos
    print("guess mode non-admin blocked: OK")

    # 13. Guess mode: scoped to a single diagnostika (diagnostika_1, 10 specimens -> full session size 10)
    assert ADMIN_ID not in tb.HISTOLOGY_GUESS_SESSIONS
    cb_g1 = FakeCB("histology_guess_start:diagnostika_1")
    await tb.cb_histology_guess_start(cb_g1)
    assert cb_g1.message.deleted
    assert cb_g1.message.photos, "expected a question photo to be sent"
    session = tb.HISTOLOGY_GUESS_SESSIONS[ADMIN_ID]
    assert session["scope"] == "diagnostika_1"
    assert len(session["items"]) == 10
    assert all(diag_key == "diagnostika_1" for diag_key, _ in session["items"])
    q_photo, q_caption, q_kb = cb_g1.message.photos[0]
    assert isinstance(q_photo, FSInputFile)
    assert "1/10" in q_caption
    assert "Угадай препарат" in q_caption
    # question caption must not leak the answer (title)
    diag_key0, spec_id0 = session["items"][0]
    spec0 = tb.get_histology_specimen(diag_key0, spec_id0)
    assert spec0["title"] not in q_caption
    assert any("Показать ответ" in t for t in kb_texts(q_kb))
    print("guess mode session start (scoped): OK")

    # 14. Show answer edits the CAPTION of the sent photo message (not the deleted original)
    photo_msg = session["msg"]
    cb_g2 = FakeCB("histology_guess_show_answer")
    await tb.cb_histology_guess_show_answer(cb_g2)
    assert photo_msg.caption_edits, "expected caption edit on the photo message"
    ans_caption, ans_kb = photo_msg.caption_edits[0]
    assert spec0["title"] in ans_caption
    assert any("Угадал" in t for t in kb_texts(ans_kb))
    assert any("Не угадал" in t for t in kb_texts(ans_kb))
    print("guess mode show answer edits correct message: OK")

    # 15. Answering advances to next question (new photo message, index 2/10)
    cb_g3 = FakeCB("histology_guess_know")
    await tb.cb_histology_guess_answer(cb_g3)
    assert tb.HISTOLOGY_GUESS_SESSIONS[ADMIN_ID]["know"] == 1
    assert tb.HISTOLOGY_GUESS_SESSIONS[ADMIN_ID]["index"] == 1
    _, cap2, _ = cb_g3.message.photos[0]
    assert "2/10" in cap2
    print("guess mode advances after answering: OK")

    # 16. Stop mid-session records summary and clears session
    cb_g4 = FakeCB("histology_guess_stop")
    await tb.cb_histology_guess_stop(cb_g4)
    assert ADMIN_ID not in tb.HISTOLOGY_GUESS_SESSIONS
    print("guess mode stop clears session: OK")

    # 17. Empty pool (unknown scope) handled gracefully
    cb_g5 = FakeCB("histology_guess_start:nope")
    await tb.cb_histology_guess_start(cb_g5)
    assert cb_g5._answers and cb_g5._answers[0][1] is True
    assert ADMIN_ID not in tb.HISTOLOGY_GUESS_SESSIONS
    print("guess mode unknown scope handled: OK")

    # 17b. Pool excludes specimens without guess_image (diagnostika_3: only 2 of 23
    # eligible -- most of that deck's photos still show labels in every available
    # source image, so the honest choice was to leave them out of guess mode)
    pool3 = tb.get_histology_guess_pool("diagnostika_3")
    assert {sid for _, sid in pool3} == {"d3_11", "d3_27"}, pool3
    cb_g3s = FakeCB("histology_guess_start:diagnostika_3")
    await tb.cb_histology_guess_start(cb_g3s)
    assert len(tb.HISTOLOGY_GUESS_SESSIONS[ADMIN_ID]["items"]) == 2
    await tb.cb_histology_guess_stop(FakeCB("histology_guess_stop"))
    print("guess mode pool excludes unreliable-deck specimens: OK")

    # 18. Full run-through to completion (scope=all) tallies know/dont_know and ends with summary
    cb_start = FakeCB("histology_guess_start:all")
    await tb.cb_histology_guess_start(cb_start)
    total = len(tb.HISTOLOGY_GUESS_SESSIONS[ADMIN_ID]["items"])
    assert total == tb.HISTOLOGY_GUESS_SESSION_SIZE
    last_msg = None
    for i in range(total):
        last_msg = tb.HISTOLOGY_GUESS_SESSIONS[ADMIN_ID]["msg"]
        cb_show = FakeCB("histology_guess_show_answer")
        await tb.cb_histology_guess_show_answer(cb_show)
        data = "histology_guess_know" if i % 2 == 0 else "histology_guess_dont_know"
        cb_ans = FakeCB(data)
        await tb.cb_histology_guess_answer(cb_ans)
    assert ADMIN_ID not in tb.HISTOLOGY_GUESS_SESSIONS, "session should be cleared after last question"
    assert last_msg.caption_edits, "expected summary written via caption edit"
    summary_caption, summary_kb = last_msg.caption_edits[-1]
    assert "Препараты закончились" in summary_caption
    assert "Отвечено: 10" in summary_caption
    assert any("Пройти ещё раз" in t for t in kb_texts(summary_kb))
    print("guess mode full run-through -> summary: OK")

    print("ALL HISTOLOGY TESTS PASSED")

asyncio.run(main())
