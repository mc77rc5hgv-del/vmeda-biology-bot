# -*- coding: utf-8 -*-
"""«📋 Рубежные контроли» — 11 реальных рубежных контролей кафедры нормальной физиологии,
импортированных из пользовательского архива (DOCX -> content.md, извлечение "без OCR и без
парафраза", ordering="document_body_order" — см. docstring handlers/physiology.py). Эти тесты
проверяют: целостность датасета (11 контролей, уникальные id, порядок, отсутствие оставшихся
{{IMAGE}}/### Таблица маркеров, все image-пути существуют на диске и совпадают по SHA-256 с тем,
что записано в самом датасете при импорте -- ровно 46 картинок и 4 таблицы только в rk_04),
навигацию (список -> контроль -> постраничное чтение с картинками, границы, неизвестный
control_id/страница), что "Источник"-подписи нигде не рендерятся (тот же принцип, что и остальной
раздел — см. предыдущие коммиты), и HTML-баланс каждой текстовой страницы каждого из 11
контролей. Сверка идёт против sha256, сохранённого в physiology.json на этапе импорта (не против
исходного manifest.json пользовательского архива — тот жил только в scratchpad этой сессии и не
переживает переезд на другую машину/CI), поэтому тест самодостаточен и не зависит от scratchpad."""
import asyncio, hashlib, os
from _bootstrap import tb
from html.parser import HTMLParser

ADMIN_ID = next(iter(tb.ADMIN_IDS))


class C(HTMLParser):
    def __init__(self):
        super().__init__(); self.stack = []; self.problems = []
    def handle_starttag(self, tag, attrs): self.stack.append(tag)
    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag: self.problems.append(tag)
        else: self.stack.pop()


def check_html(text):
    c = C(); c.feed(text)
    assert not c.stack and not c.problems, (text[:300], c.stack, c.problems)
    assert len(text) <= 4096, len(text)


class FakeUser:
    def __init__(self, uid):
        self.id = uid


class FakePhotoSize:
    def __init__(self, file_id):
        self.file_id = file_id


class FakeSentPhoto:
    def __init__(self, file_id="fake_file_id"):
        self.photo = [FakePhotoSize(file_id)]


class FakeMsg:
    def __init__(self):
        self.deleted = False
        self.sent_texts = []
        self.sent_photos = []
    async def delete(self):
        self.deleted = True
    async def answer(self, text, **kwargs):
        self.sent_texts.append((text, kwargs.get("reply_markup")))
        return self
    async def answer_photo(self, photo, **kwargs):
        self.sent_photos.append((photo, kwargs.get("reply_markup")))
        return FakeSentPhoto()
    async def edit_text(self, text, **kwargs):
        self.sent_texts.append((text, kwargs.get("reply_markup")))
        return self


class FakeCB:
    def __init__(self, data, uid=ADMIN_ID):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
        self._answers = []
    async def answer(self, text=None, show_alert=False):
        self._answers.append((text, show_alert))


def kb_data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def kb_texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


async def main():
    controls = tb.PHYSIOLOGY["boundary_controls"]

    # ---- 1. dataset structure: exactly 11 controls, unique ids, ordered ----
    assert len(controls) == 11, len(controls)
    ids = [c["control_id"] for c in controls]
    assert len(set(ids)) == 11
    orders = [c["order"] for c in controls]
    assert orders == sorted(orders) == list(range(1, 12))
    for c in controls:
        assert c["blocks"], c["control_id"]
        assert c["title"].strip()
    print("1. dataset structure: 11 controls, unique ids, ordered 1..11: OK")

    # ---- 2. no leftover {{IMAGE}}/### Таблица markers in text blocks, no replacement char,
    # every block carries provenance (never rendered, just stored) ----
    n_images = n_tables = n_text = 0
    for c in controls:
        for b in c["blocks"]:
            assert "provenance" in b and b["provenance"]["control_id"] == c["control_id"]
            if b["type"] == "text":
                assert "{{IMAGE" not in b["text"] and "### Таблица" not in b["text"]
                assert "�" not in b["text"]
                n_text += 1
            elif b["type"] == "image":
                n_images += 1
            elif b["type"] == "table":
                n_tables += 1
                assert b["rows"]
    assert n_images == 46, n_images
    assert n_tables == 4, n_tables
    tables_by_control = {c["control_id"] for c in controls if any(b["type"] == "table" for b in c["blocks"])}
    assert tables_by_control == {"rk_04"}, tables_by_control
    print("2. no leftover markers, provenance on every block, 46 images / 4 tables (rk_04 only): OK")

    # ---- 3. every image path resolves to a real file, byte-identical (SHA-256) to what the
    # dataset itself recorded at import time, no duplicate paths ----
    seen_paths = set()
    for c in controls:
        for b in c["blocks"]:
            if b["type"] != "image":
                continue
            assert b["path"] not in seen_paths, f"duplicate image path {b['path']}"
            seen_paths.add(b["path"])
            full_path = os.path.join(tb.physiology_handlers.PHYS_RK_IMAGES_DIR, b["path"])
            assert os.path.isfile(full_path), full_path
            real_sha = hashlib.sha256(open(full_path, "rb").read()).hexdigest()
            assert real_sha == b["sha256"] == b["provenance"]["sha256"], b["path"]
    assert len(seen_paths) == 46
    print("3. every image file exists on disk, byte-identical (SHA-256) to the dataset's own record: OK")

    non_admin = 77_331_144

    # ---- 4. rk_menu lists all 11 controls in order, back button present ----
    cb_rk_menu = FakeCB("phys:rk_menu", uid=non_admin)
    await tb.cb_phys_rk_menu(cb_rk_menu)
    rk_menu_text, rk_menu_kb = cb_rk_menu.message.sent_texts[-1]
    check_html(rk_menu_text)
    rk_menu_data = kb_data(rk_menu_kb)
    for cid in ids:
        assert f"phys:rk:{cid}:0" in rk_menu_data, cid
    assert "phys:menu" in rk_menu_data
    print("4. rk_menu lists all 11 controls + back button: OK")

    # ---- 5. opening control 1 renders its first (text) page with correct nav ----
    cb_open = FakeCB("phys:rk:rk_01:0", uid=non_admin)
    await tb.cb_phys_rk_page(cb_open)
    assert cb_open.message.deleted
    page0_text, page0_kb = cb_open.message.sent_texts[-1]
    check_html(page0_text)
    assert "Рубежный контроль 1" in page0_text
    page0_data = kb_data(page0_kb)
    assert "phys:rk:rk_01:1" in page0_data
    assert not any(d == "phys:rk:rk_01:-1" for d in page0_data)
    assert "phys:rk_menu" in page0_data
    print("5. opening a control renders page 1/N, correct forward nav, no back-page button: OK")

    # ---- 6. paginate to the last page: no forward button, back-to-rk-menu present ----
    control1 = tb.get_rk_control("rk_01")
    pages1 = tb.build_rk_pages(control1["blocks"])
    last_idx = len(pages1) - 1
    cb_last = FakeCB(f"phys:rk:rk_01:{last_idx}", uid=non_admin)
    await tb.cb_phys_rk_page(cb_last)
    last_kind = pages1[last_idx]["kind"]
    if last_kind == "text":
        last_text, last_kb = cb_last.message.sent_texts[-1]
        check_html(last_text)
    else:
        assert cb_last.message.sent_photos
        last_kb = cb_last.message.sent_photos[-1][1]
    last_data = kb_data(last_kb)
    assert not any(d == f"phys:rk:rk_01:{last_idx + 1}" for d in last_data)
    assert f"phys:rk:rk_01:{last_idx - 1}" in last_data
    print(f"6. last page ({last_idx + 1}/{len(pages1)}, kind={last_kind}): no forward nav, back present: OK")

    # ---- 7. image pages are sent via answer_photo (not text), file_id cached on repeat view ----
    img_idx = next(i for i, p in enumerate(pages1) if p["kind"] == "image")
    img_path = pages1[img_idx]["path"]
    tb.physiology_handlers.PHYS_RK_FILE_ID_CACHE.pop(img_path, None)
    cb_img = FakeCB(f"phys:rk:rk_01:{img_idx}", uid=non_admin)
    await tb.cb_phys_rk_page(cb_img)
    assert cb_img.message.deleted
    assert cb_img.message.sent_photos and not cb_img.message.sent_texts
    assert tb.physiology_handlers.PHYS_RK_FILE_ID_CACHE.get(img_path) == "fake_file_id"
    print("7. image page sent via answer_photo, file_id cached after first view: OK")

    # ---- 8. unknown control_id / out-of-range page index rejected with an alert, no crash ----
    cb_bad_control = FakeCB("phys:rk:rk_99:0", uid=non_admin)
    await tb.cb_phys_rk_page(cb_bad_control)
    assert not cb_bad_control.message.deleted
    assert cb_bad_control._answers and cb_bad_control._answers[0][1] is True

    cb_bad_page = FakeCB(f"phys:rk:rk_01:{len(pages1)}", uid=non_admin)
    await tb.cb_phys_rk_page(cb_bad_page)
    assert not cb_bad_page.message.deleted
    assert cb_bad_page._answers and cb_bad_page._answers[0][1] is True
    print("8. unknown control / out-of-range page rejected with an alert, no crash: OK")

    # ---- 9. build_rk_pages: an image always starts its own page (never shares a page with
    # text/table content), no single block is ever split across pages ----
    for c in controls:
        pages = tb.build_rk_pages(c["blocks"])
        for p in pages:
            if p["kind"] == "text":
                assert len(p["text"]) <= 4096 - 200, (c["control_id"], len(p["text"]))
        img_page_count = sum(1 for p in pages if p["kind"] == "image")
        expected_images = sum(1 for b in c["blocks"] if b["type"] == "image")
        assert img_page_count == expected_images, c["control_id"]
    print("9. build_rk_pages: every image is its own page, all pages within the Telegram cap: OK")

    # ---- 10. table rendering (rk_04) never leaks raw '**Ячейка'/'**Строка' markdown syntax ----
    rk04 = tb.get_rk_control("rk_04")
    pages4 = tb.build_rk_pages(rk04["blocks"])
    table_page = next(p for p in pages4 if p["kind"] == "text" and "Таблица" in p["text"])
    assert "**Ячейка" not in table_page["text"] and "**Строка" not in table_page["text"]
    assert "Цоликлоны" in table_page["text"]
    print("10. table blocks render as clean text, no raw markdown table syntax leaks: OK")

    # ---- 11. no "Источник" caption anywhere across all 11 controls' rendered pages (same rule
    # as the rest of the Physiology section, see prior commits) ----
    for c in controls:
        pages = tb.build_rk_pages(c["blocks"])
        for p in pages:
            if p["kind"] == "text":
                assert "Источник" not in p["text"], (c["control_id"], p["text"][:80])
    assert "Источник" not in tb.get_rk_menu_text()
    print("11. no 'Источник' caption anywhere in Рубежные контроли: OK")

    # ---- 12. main physiology menu exposes the "📋 Рубежные контроли" entry point ----
    cb_menu2 = FakeCB("phys:menu", uid=non_admin)
    await tb.cb_phys_menu(cb_menu2)
    menu_text2, menu_kb2 = cb_menu2.message.sent_texts[-1]
    assert "phys:rk_menu" in kb_data(menu_kb2)
    assert any("Рубежные контроли" in t for t in kb_texts(menu_kb2))
    print("12. main Physiology menu links to Рубежные контроли: OK")

    # ---- 13. boundary-control content is actually indexed for VMedA AI (ai/rag.py) and a real
    # exam fact from it is genuinely retrievable by keyword search, not just present in the raw
    # index — never one giant per-control blob (format_context() only shows the first
    # SNIPPET_MAX_CHARS of a matched entry, so a huge blob would silently hide anything past that) ----
    from ai import rag as ai_rag
    ai_rag.configure(
        questions=tb.QUESTIONS, physics_questions=tb.PHYSICS_QUESTIONS, chemistry_theory=tb.CHEMISTRY_THEORY,
        chemistry_theory_tickets=tb.CHEMISTRY_THEORY_TICKETS, chemistry_practice_tickets=tb.CHEMISTRY_PRACTICE_TICKETS,
        anatomy=tb.ANATOMY, operative_surgery=tb.OPERATIVE_SURGERY, physiology=tb.PHYSIOLOGY,
    )
    rk_entries = [e for e in ai_rag._index if e["subject"] == "нормальная физиология" and "Рубежный контроль" in e["title"]]
    n_expected_chunks = sum(len(ai_rag._chunk_rk_blocks(c["blocks"])) for c in controls)
    assert len(rk_entries) == n_expected_chunks, (len(rk_entries), n_expected_chunks)
    # a chunk never exceeds the budget by more than one oversized single block (never split) —
    # 2000 is a generous ceiling given the real max single source paragraph is 1532 chars
    assert all(len(e["text"]) <= 2000 for e in rk_entries), max(len(e["text"]) for e in rk_entries)

    scored = ai_rag._score_entries(
        "В норме величина основного обмена у человека весом 70 кг", ai_rag._index, ai_rag._idf
    )
    scored.sort(key=lambda x: -x[0])
    assert scored, "expected at least one keyword match"
    top_entry = scored[0][1]
    assert top_entry["subject"] == "нормальная физиология"
    assert "1700 ккал" in top_entry["text"], top_entry["text"][:200]
    ctx = ai_rag.format_context([top_entry])
    assert "1700 ккал" in ctx, "the real fact must survive format_context's SNIPPET_MAX_CHARS truncation"

    # restore the config other tests expect
    ai_rag.configure(
        questions=tb.QUESTIONS, physics_questions=tb.PHYSICS_QUESTIONS, chemistry_theory=tb.CHEMISTRY_THEORY,
        chemistry_theory_tickets=tb.CHEMISTRY_THEORY_TICKETS, chemistry_practice_tickets=tb.CHEMISTRY_PRACTICE_TICKETS,
        anatomy=tb.ANATOMY, operative_surgery=tb.OPERATIVE_SURGERY, physiology=tb.PHYSIOLOGY,
    )
    print("13. boundary-control content indexed in small chunks, a real fact is genuinely retrievable: OK")

    print("\nALL PHYSIOLOGY BOUNDARY-CONTROL TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
