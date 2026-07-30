# -*- coding: utf-8 -*-
"""Anatomy -> «Экзамен» -> «Вопросы практики»: official practical exam question bank
(«покажите и назовите...», Гайворонский, ВМедА), browsable by section -> question list ->
question detail. Every answer ships with an image (Netter/Гайворонский atlas or an
open-source captioned fallback), sent as a Telegram photo with the answer as caption
(or, if the answer overflows Telegram's 1024-char caption limit, as a short photo caption
followed by the full answer as a separate text message)."""
import asyncio
import os
from _bootstrap import tb
from html.parser import HTMLParser

NON_ADMIN = 918273645

class C(HTMLParser):
    def __init__(self):
        super().__init__(); self.stack = []; self.problems = []
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
        self.photos = []
        self.media_groups = []
        self.deleted = False
    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self
    async def delete(self):
        self.deleted = True
    async def answer(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self
    async def answer_photo(self, photo, **kwargs):
        self.photos.append((photo, kwargs.get("caption"), kwargs.get("reply_markup")))
        new_msg = FakeMsg()
        new_msg.photos.append((photo, kwargs.get("caption"), kwargs.get("reply_markup")))
        return new_msg
    async def answer_media_group(self, media, **kwargs):
        self.media_groups.append(media)
        return [FakeMsg() for _ in media]

class FakeCB:
    def __init__(self, data, uid=NON_ADMIN):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
        self._answers = []
    async def answer(self, text=None, show_alert=False):
        self._answers.append((text, show_alert))

def kb_texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row]

def kb_data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]

async def main():
    sections = tb.ANATOMY_EXAM_PRACTICE_SECTIONS

    # 0. data integrity
    assert len(sections) == 4
    assert [s["id"] for s in sections] == [1, 2, 3, 4]
    titles = [s["title"] for s in sections]
    assert "СИСТЕМА ОРГАНОВ ОПОРЫ И ДВИЖЕНИЯ" in titles[0]
    assert "СПЛАНХНОЛОГИЯ" in titles[1]
    assert "СОСУДИСТАЯ СИСТЕМА" in titles[2]
    assert "НЕРВНАЯ СИСТЕМА" in titles[3]

    live_sections = [s for s in sections if s["questions"]]
    for s in live_sections:
        assert len(s["questions"]) == 42, s["id"]
        seen_nums = set()
        for q in s["questions"]:
            assert q["question"].strip()
            assert q["answer"].strip()
            assert q["num"] not in seen_nums
            seen_nums.add(q["num"])
            check_html(q["question"])
            check_html(q["answer"])
            images = q["images"]
            assert images, (s["id"], q["num"])
            for img in images:
                assert img.get("caption") and img.get("credit")
                assert ("path" in img) != ("url" in img), "image needs exactly one of path/url"
                if "path" in img:
                    full_path = os.path.join(tb.ANATOMY_IMAGES_DIR, img["path"])
                    assert os.path.exists(full_path), full_path
                else:
                    assert img["url"].startswith("https://"), img["url"]
            # combined question+answer as rendered on the detail screen must fit one message
            combined = tb.get_anatomy_exam_practice_question_text(s, q["num"])
            check_html(combined)
        assert seen_nums == set(range(1, 43)), s["id"]
    print(f"data integrity: 4 sections, {len(live_sections)} live with 42 well-formed questions+images each: OK")

    # 1. anatomy_exam_menu links to anatomy_exam_practice
    cb0 = FakeCB("anatomy_exam_menu")
    await tb.cb_anatomy_exam_menu(cb0)
    assert "anatomy_exam_practice" in kb_data(cb0.message.edits[-1][1])
    print("anatomy_exam_menu links to anatomy_exam_practice: OK")

    # 2. anatomy_exam_practice renders the section list, free for a non-admin user
    cb1 = FakeCB("anatomy_exam_practice", uid=NON_ADMIN)
    await tb.cb_anatomy_exam_practice(cb1)
    text1, kb1 = cb1.message.edits[-1]
    check_html(text1)
    data1 = kb_data(kb1)
    for s in sections:
        assert f"anatomy_exam_practice_section:{s['id']}" in data1
    assert "anatomy_exam_menu" in data1
    print("anatomy_exam_practice renders 4 sections: OK")

    # 3. unknown section id -> alert
    cb_bad_section = FakeCB("anatomy_exam_practice_section:999", uid=NON_ADMIN)
    await tb.cb_anatomy_exam_practice_section(cb_bad_section)
    assert not cb_bad_section.message.edits
    assert cb_bad_section._answers and cb_bad_section._answers[0][1] is True
    print("unknown section -> alert, no crash: OK")

    # 4. unknown question -> alert
    if live_sections:
        s1 = live_sections[0]
        cb_bad_q = FakeCB(f"anatomy_exam_practice_q:{s1['id']}:999", uid=NON_ADMIN)
        await tb.cb_anatomy_exam_practice_question(cb_bad_q)
        assert not cb_bad_q.message.photos
        assert cb_bad_q._answers and cb_bad_q._answers[0][1] is True
        print("unknown question -> alert, no crash: OK")

    # 5. for each live section: question list renders, first/middle/last question detail works
    for s in live_sections:
        section_id = s["id"]
        cb2 = FakeCB(f"anatomy_exam_practice_section:{section_id}", uid=NON_ADMIN)
        await tb.cb_anatomy_exam_practice_section(cb2)
        text2, kb2 = cb2.message.edits[-1]
        check_html(text2)
        data2 = kb_data(kb2)
        for q in s["questions"]:
            assert f"anatomy_exam_practice_q:{section_id}:{q['num']}" in data2
        assert "anatomy_exam_practice" in data2

        for num in (1, 21, 42):
            cb3 = FakeCB(f"anatomy_exam_practice_q:{section_id}:{num}", uid=NON_ADMIN)
            await tb.cb_anatomy_exam_practice_question(cb3)
            assert cb3.message.deleted
            q = next(qq for qq in s["questions"] if qq["num"] == num)
            if len(q["images"]) > 1:
                # album case: images have no caption/keyboard, text+nav follows separately
                assert cb3.message.media_groups, (section_id, num)
                assert len(cb3.message.media_groups[-1]) == len(q["images"])
                assert cb3.message.edits, (section_id, num)
                nav_text, nav_markup = cb3.message.edits[-1]
                assert q["question"] in nav_text and q["answer"] in nav_text
                check_html(nav_text)
                nav_data = kb_data(nav_markup)
            else:
                assert cb3.message.photos, (section_id, num)
                photo, caption, markup = cb3.message.photos[-1]
                if markup is not None:
                    # combined single-message case: keyboard is attached directly to the photo
                    nav_data = kb_data(markup)
                else:
                    # split case: keyboard is on the follow-up text message instead
                    assert cb3.message.edits, (section_id, num)
                    nav_text, nav_markup = cb3.message.edits[-1]
                    assert q["question"] in nav_text and q["answer"] in nav_text
                    check_html(nav_text)
                    nav_data = kb_data(nav_markup)
            if num > 1:
                assert f"anatomy_exam_practice_q:{section_id}:{num - 1}" in nav_data
            else:
                assert not any(d == f"anatomy_exam_practice_q:{section_id}:0" for d in nav_data)
            if num < 42:
                assert f"anatomy_exam_practice_q:{section_id}:{num + 1}" in nav_data
            else:
                assert not any(d == f"anatomy_exam_practice_q:{section_id}:43" for d in nav_data)
            assert f"anatomy_exam_practice_section:{section_id}" in nav_data
            assert "anatomy_exam_practice" in nav_data
        print(f"section {section_id} ({s['title']}): question list + detail navigation work: OK")

    print("ALL ANATOMY EXAM PRACTICE TESTS PASSED")

asyncio.run(main())
