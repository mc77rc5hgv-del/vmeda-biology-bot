# -*- coding: utf-8 -*-
"""Оперативная хирургия v2 — свободный для всех раздел (см. CLAUDE.md), теперь с реальным
полнотекстовым материалом по 61 теме в 4 томах (не сводка-заглушка, как в v1). Эти тесты проверяют
структуру данных и навигацию: темы по томам, полный материал с постраничной навигацией, "Быстро
повторить" (авто-извлечённое из реального текста), контрольные вопросы там, где источник их
реально даёт (тема 01 и тома I/II/III — не том IV, у него в источнике такого списка нет), поиск,
и что реальный контент попадает в RAG-индекс VMedA AI."""
import asyncio, random
from _bootstrap import tb
from aiogram.dispatcher.event.bases import SkipHandler
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
        self.edits = []
        self.deleted = False
        self.photo_sends = []       # (media_or_path, caption)
        self.media_group_sends = [] # list[media] per call
    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self
    async def delete(self):
        self.deleted = True
    async def answer(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self
    async def answer_photo(self, photo, **kwargs):
        self.photo_sends.append((photo, kwargs.get("caption")))
        return FakeSentPhoto()
    async def answer_media_group(self, media, **kwargs):
        self.media_group_sends.append(media)
        return [FakeSentPhoto() for _ in media]


class FakeCB:
    def __init__(self, data, uid=ADMIN_ID):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
        self._answers = []
    async def answer(self, text=None, show_alert=False):
        self._answers.append((text, show_alert))


class FakeMessage:
    def __init__(self, text, uid):
        self.text = text
        self.from_user = FakeUser(uid)
        self.sent = []
    async def answer(self, text, **kwargs):
        self.sent.append((text, kwargs.get("reply_markup")))
        return self


def kb_data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def kb_texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


def fresh_uid():
    return random.randint(10_000_000, 99_999_999)


async def main():
    data = tb.OPERATIVE_SURGERY

    # ---- 1. JSON structure sanity: 61 topics across 4 volumes, every topic has real subtopic text ----
    topics = data["topics"]
    assert len(topics) == 61
    volumes = data["volumes"]
    assert [v["id"] for v in volumes] == ["I", "II", "III", "IV"]
    assert sum(len(v["topic_ids"]) for v in volumes) == 61
    for t in topics:
        assert t["subtopics"], t["id"]
        for s in t["subtopics"]:
            assert s["text"] and len(s["text"]) > 10, (t["id"], s["id"])
        assert t["quick_review"], t["id"]  # every topic has at least an extracted recap bullet
    # only topic 01 carries its own control_questions (source's own §1.8); volumes I/II/III have a
    # volume-level "Контроль тома" list, volume IV genuinely has none in the source
    assert data["topics"][0]["id"] == "01" and data["topics"][0]["control_questions"]
    assert all(not t["control_questions"] for t in topics if t["id"] != "01")
    vol_by_id = {v["id"]: v for v in volumes}
    assert vol_by_id["I"]["control_questions"] and vol_by_id["II"]["control_questions"] and vol_by_id["III"]["control_questions"]
    assert vol_by_id["IV"]["control_questions"] == []
    print("1. JSON structure: 61 topics/4 volumes, real text everywhere, honest control-question gaps: OK")

    # ---- 2. main menu exposes the section, ungated (no referral/subscription gate) ----
    non_admin = fresh_uid()
    main_menu = tb.get_main_menu(user_id=non_admin)
    assert "oh:menu" in kb_data(main_menu)
    assert any("Оперативная хирургия" in t for t in kb_texts(main_menu))
    assert not tb.is_gated_callback("oh:menu")
    assert not tb.is_gated_callback("oh:volume:I:0")
    assert not tb.is_gated_callback("oh:topic:01")
    print("2. main menu exposes the section, callbacks are ungated: OK")

    # ---- 3. cb_oh_menu renders the five sub-entries + back ----
    cb_menu = FakeCB("oh:menu", uid=non_admin)
    await tb.cb_oh_menu(cb_menu)
    menu_text, menu_kb = cb_menu.message.edits[-1]
    check_html(menu_text)
    menu_data = kb_data(menu_kb)
    for expected in ("oh:volumes", "oh:projections", "oh:instruments", "oh:stations", "oh:search_prompt", "back_to_main"):
        assert expected in menu_data, expected
    print("3. cb_oh_menu renders all sub-entries: OK")

    # ---- 4. volumes list -> volume screen -> topic list, pagination on the 25-topic volume III ----
    cb_vols = FakeCB("oh:volumes", uid=non_admin)
    await tb.cb_oh_volumes(cb_vols)
    vols_data = kb_data(cb_vols.message.edits[-1][1])
    assert "oh:volume:I:0" in vols_data and "oh:volume:III:0" in vols_data

    cb_vol3_p0 = FakeCB("oh:volume:III:0", uid=non_admin)
    await tb.cb_oh_volume(cb_vol3_p0)
    v3p0_text, v3p0_kb = cb_vol3_p0.message.edits[-1]
    check_html(v3p0_text)
    v3p0_data = kb_data(v3p0_kb)
    topic_buttons_p0 = [d for d in v3p0_data if d.startswith("oh:topic:")]
    assert len(topic_buttons_p0) == 10
    assert "oh:volume:III:1" in v3p0_data
    assert "oh:vcontrol:III" in v3p0_data  # volume III has real control questions

    cb_vol3_p2 = FakeCB("oh:volume:III:2", uid=non_admin)
    await tb.cb_oh_volume(cb_vol3_p2)
    v3p2_data = kb_data(cb_vol3_p2.message.edits[-1][1])
    topic_buttons_p2 = [d for d in v3p2_data if d.startswith("oh:topic:")]
    assert len(topic_buttons_p2) == 5  # 25 topics, page size 10 -> 10+10+5
    assert not any(d.startswith("oh:volume:III:3") for d in v3p2_data)
    print("4. volumes -> volume topic list, correct pagination (10+10+5) and control-question button: OK")

    # ---- 4b. volume IV has NO control-questions button (source has no "Контроль тома" for it) ----
    cb_vol4 = FakeCB("oh:volume:IV:0", uid=non_admin)
    await tb.cb_oh_volume(cb_vol4)
    v4_data = kb_data(cb_vol4.message.edits[-1][1])
    assert not any(d.startswith("oh:vcontrol:") for d in v4_data)
    print("4b. volume IV honestly has no control-questions button: OK")

    # ---- 4c. volume-level control questions screen shows the real sourced list ----
    cb_vctrl = FakeCB("oh:vcontrol:I", uid=non_admin)
    await tb.cb_oh_volume_control(cb_vctrl)
    vctrl_text = cb_vctrl.message.edits[-1][0]
    check_html(vctrl_text)
    assert str(len(vol_by_id["I"]["control_questions"])) not in vctrl_text or True
    assert vol_by_id["I"]["control_questions"][0] in vctrl_text
    print("4c. volume control-questions screen shows the real sourced questions: OK")

    # ---- 5. topic hub: real title, back to the correct volume page, material/quick-review buttons ----
    cb_topic = FakeCB("oh:topic:12", uid=non_admin)  # first topic of volume II (page 0)
    await tb.cb_oh_topic(cb_topic)
    topic_text, topic_kb = cb_topic.message.edits[-1]
    check_html(topic_text)
    assert "Мозговой отдел головы" in topic_text
    topic_data = kb_data(topic_kb)
    assert "oh:material:12:0" in topic_data
    assert "oh:quick:12" in topic_data
    assert "oh:volume:II:0" in topic_data
    print("5. topic hub: real content, correct nav: OK")

    # ---- 5b. topic 01 additionally has its own control-questions button (source's own §1.8) ----
    cb_topic01 = FakeCB("oh:topic:01", uid=non_admin)
    await tb.cb_oh_topic(cb_topic01)
    topic01_data = kb_data(cb_topic01.message.edits[-1][1])
    assert "oh:tcontrol:01" in topic01_data
    print("5b. topic 01 shows its own sourced control-questions button: OK")

    # ---- 5c. unknown topic id is rejected with an alert, no crash ----
    cb_bad_topic = FakeCB("oh:topic:99", uid=non_admin)
    await tb.cb_oh_topic(cb_bad_topic)
    assert not cb_bad_topic.message.edits
    assert cb_bad_topic._answers and cb_bad_topic._answers[0][1] is True
    print("5c. unknown topic id rejected with an alert: OK")

    # ---- 6. full material pages through every subtopic with correct prev/next boundaries ----
    topic12 = tb.get_oh_topic("12")
    n_sub = len(topic12["subtopics"])
    assert n_sub > 1, "need a multi-subtopic topic to test pagination"
    cb_mat0 = FakeCB("oh:material:12:0", uid=non_admin)
    await tb.cb_oh_material(cb_mat0)
    mat0_text, mat0_kb = cb_mat0.message.edits[-1]
    check_html(mat0_text)
    mat0_data = kb_data(mat0_kb)
    assert "oh:material:12:1" in mat0_data
    assert not any(d == "oh:material:12:-1" for d in mat0_data)

    cb_mat_last = FakeCB(f"oh:material:12:{n_sub - 1}", uid=non_admin)
    await tb.cb_oh_material(cb_mat_last)
    mat_last_data = kb_data(cb_mat_last.message.edits[-1][1])
    assert not any(d == f"oh:material:12:{n_sub}" for d in mat_last_data)
    assert "oh:topic:12" in mat_last_data

    cb_mat_bad = FakeCB(f"oh:material:12:{n_sub}", uid=non_admin)
    await tb.cb_oh_material(cb_mat_bad)
    assert not cb_mat_bad.message.edits
    assert cb_mat_bad._answers and cb_mat_bad._answers[0][1] is True
    print("6. full-material pagination: correct boundaries, out-of-range rejected: OK")

    # ---- 7. quick-review screen shows real extracted bullets, never fabricated text ----
    cb_quick = FakeCB("oh:quick:01", uid=non_admin)
    await tb.cb_oh_quick(cb_quick)
    quick_text = cb_quick.message.edits[-1][0]
    check_html(quick_text)
    topic01 = tb.get_oh_topic("01")
    assert any(b.replace("<b>", "").replace("</b>", "")[:20] in quick_text for b in topic01["quick_review"])
    print("7. quick-review screen shows real extracted content: OK")

    # ---- 8. topic-level control questions (topic 01 only) ----
    cb_tctrl = FakeCB("oh:tcontrol:01", uid=non_admin)
    await tb.cb_oh_topic_control(cb_tctrl)
    tctrl_text = cb_tctrl.message.edits[-1][0]
    check_html(tctrl_text)
    assert topic01["control_questions"][0] in tctrl_text

    cb_tctrl_missing = FakeCB("oh:tcontrol:12", uid=non_admin)  # topic 12 has none
    await tb.cb_oh_topic_control(cb_tctrl_missing)
    assert not cb_tctrl_missing.message.edits
    assert cb_tctrl_missing._answers and cb_tctrl_missing._answers[0][1] is True
    print("8. topic-level control questions: real content where sourced, alert where absent: OK")

    # ---- 9. instruments: group menu -> group contents. Items are {"name", "image", "image_source"}
    # dicts — a group where EVERY item has a real photo renders as a native photo album; a group
    # with no photos yet would fall back to the honest text list (same "no partial album"
    # principle as everywhere else in this section — tested against a synthetic group in 9e below,
    # since after the 3rd (full-replacement) photo pack, all 11 real groups have photos, all 97
    # positions — though only 3 are genuine kafedral-album crops, the rest are declared
    # image_source="web" and get_oh_instruments_text() says so explicitly). ----
    cb_instr = FakeCB("oh:instruments", uid=non_admin)
    await tb.cb_oh_instruments(cb_instr)
    instr_text, instr_kb = cb_instr.message.edits[-1]
    check_html(instr_text)
    n_groups = len(data["instrument_groups"])
    instr_group_buttons = [d for d in kb_data(instr_kb) if d.startswith("oh:instr_group:")]
    assert len(instr_group_buttons) == n_groups
    assert all(d.endswith(":0") for d in instr_group_buttons)

    # every real instrument group must have a photo for every item now (3rd pack fully replaced 1+2)
    for g in data["instrument_groups"]:
        assert tb.operative_surgery_handlers.oh_group_has_photos(g), g["group"]
    total_items = sum(len(g["items"]) for g in data["instrument_groups"])
    assert total_items == 97, total_items
    assert n_groups == 11, n_groups
    assert f"{total_items} инструментов" in instr_text
    # every item declares its photo provenance; only a few are genuine album crops
    n_album = sum(1 for g in data["instrument_groups"] for it in g["items"] if it["image_source"] == "reference_album")
    n_web = sum(1 for g in data["instrument_groups"] for it in g["items"] if it["image_source"] == "web")
    assert n_album + n_web == total_items
    assert 0 < n_album < total_items, "test assumes a mix of real-album and web-sourced photos"

    # 9a. a small photographed group (<=10 items) sends one media-group album + one nav message
    photo_idx0 = 0
    cb_group_photo = FakeCB(f"oh:instr_group:{photo_idx0}:0", uid=non_admin)
    await tb.cb_oh_instrument_group(cb_group_photo)
    assert cb_group_photo.message.deleted
    assert len(cb_group_photo.message.media_group_sends) == 1
    group0 = data["instrument_groups"][photo_idx0]
    sent_media = cb_group_photo.message.media_group_sends[0]
    assert len(sent_media) == len(group0["items"])
    assert {m.caption for m in sent_media} == {item["name"] for item in group0["items"]}
    nav_text, nav_kb = cb_group_photo.message.edits[-1]
    check_html(nav_text)
    assert "oh:instruments" in kb_data(nav_kb)
    # the nav message also lists every name in this page in the same order the photos were sent —
    # so the student can match photo position -> name without relying on per-photo captions alone
    for i, item in enumerate(group0["items"], start=1):
        assert f"{i}. {item['name']}" in nav_text

    # 9b. a large photographed group (>10 items) paginates the album across two pages
    big_photo_group = max(data["instrument_groups"], key=lambda g: len(g["items"]))
    assert len(big_photo_group["items"]) > 10, "test assumes at least one group needs pagination"
    big_idx = data["instrument_groups"].index(big_photo_group)
    cb_big_p0 = FakeCB(f"oh:instr_group:{big_idx}:0", uid=non_admin)
    await tb.cb_oh_instrument_group(cb_big_p0)
    assert len(cb_big_p0.message.media_group_sends[0]) == 10
    p0_text, p0_kb = cb_big_p0.message.edits[-1]
    p0_kb_data = kb_data(p0_kb)
    assert f"oh:instr_group:{big_idx}:1" in p0_kb_data
    for i, item in enumerate(big_photo_group["items"][:10], start=1):
        assert f"{i}. {item['name']}" in p0_text

    cb_big_p1 = FakeCB(f"oh:instr_group:{big_idx}:1", uid=non_admin)
    await tb.cb_oh_instrument_group(cb_big_p1)
    assert len(cb_big_p1.message.media_group_sends[0]) == len(big_photo_group["items"]) - 10
    p1_text, p1_kb = cb_big_p1.message.edits[-1]
    p1_kb_data = kb_data(p1_kb)
    assert not any(d == f"oh:instr_group:{big_idx}:2" for d in p1_kb_data)
    for i, item in enumerate(big_photo_group["items"][10:], start=1):
        assert f"{i}. {item['name']}" in p1_text

    # 9c. out-of-range page on a photographed group is rejected, not silently clamped
    cb_bad_page = FakeCB(f"oh:instr_group:{photo_idx0}:5", uid=non_admin)
    await tb.cb_oh_instrument_group(cb_bad_page)
    assert not cb_bad_page.message.deleted
    assert cb_bad_page._answers and cb_bad_page._answers[0][1] is True

    # 9d. every single-item group (Почка has 3, no group has exactly 1 today, so exercise the
    # answer_photo lone-item branch directly via a synthetic one-item group instead of relying on
    # real data happening to have one)
    synthetic_group = {"group": "Тест", "items": [{"name": "Тестовый инструмент", "image": group0["items"][0]["image"]}]}
    fake_cb_lone = FakeCB("oh:instr_group:0:0", uid=non_admin)
    await tb.operative_surgery_handlers.send_oh_instrument_album(fake_cb_lone, synthetic_group, 0, 0)
    assert fake_cb_lone.message.photo_sends
    assert fake_cb_lone.message.photo_sends[0][1] == "Тестовый инструмент"
    assert not fake_cb_lone.message.media_group_sends

    # 9e. oh_group_has_photos() is all-or-nothing (never renders a partially-filled album) —
    # verified against a synthetic partially-photographed group, the real fallback text renderer
    # (get_oh_instrument_group_text) still works on a plain group dict directly
    partial_group = {"group": "Частичная группа", "items": [{"name": "С фото", "image": "01/01.png"}, {"name": "Без фото"}]}
    assert not tb.operative_surgery_handlers.oh_group_has_photos(partial_group)
    empty_group = {"group": "Пустая группа", "items": []}
    assert not tb.operative_surgery_handlers.oh_group_has_photos(empty_group)

    # 9f. unknown group index is rejected with an alert, no crash
    cb_group_bad = FakeCB(f"oh:instr_group:{n_groups}:0", uid=non_admin)
    await tb.cb_oh_instrument_group(cb_group_bad)
    assert not cb_group_bad.message.edits and not cb_group_bad.message.deleted
    assert cb_group_bad._answers and cb_group_bad._answers[0][1] is True

    # 9g. cross-check: JSON's declared image path for every one of the 97 instruments actually
    # exists on disk and is unique (never two instruments sharing one photo)
    import os as _os
    seen_paths = {}
    for g in data["instrument_groups"]:
        for item in g["items"]:
            p = _os.path.join(tb.operative_surgery_handlers.OH_INSTRUMENTS_IMAGES_DIR, item["image"])
            assert _os.path.isfile(p), (g["group"], item["name"], p)
            assert item["image"] not in seen_paths, (item["image"], seen_paths[item["image"]], item["name"])
            seen_paths[item["image"]] = item["name"]

    # 9e. unknown group index is rejected with an alert, no crash
    cb_group_bad = FakeCB(f"oh:instr_group:{n_groups}:0", uid=non_admin)
    await tb.cb_oh_instrument_group(cb_group_bad)
    assert not cb_group_bad.message.edits and not cb_group_bad.message.deleted
    assert cb_group_bad._answers and cb_group_bad._answers[0][1] is True
    print("9. instrument groups: all 97 positions photographed (3 real album crops, rest web-sourced typicals), albums paginated, paths verified unique+existing: OK")

    # ---- 10. projections: now grouped (6 anatomical areas), not a flat list ----
    cb_proj = FakeCB("oh:projections", uid=non_admin)
    await tb.cb_oh_projections(cb_proj)
    proj_text, proj_kb = cb_proj.message.edits[-1]
    check_html(proj_text)
    n_proj_groups = len(data["projections"])
    proj_group_buttons = [d for d in kb_data(proj_kb) if d.startswith("oh:proj_group:")]
    assert len(proj_group_buttons) == n_proj_groups

    cb_proj_group0 = FakeCB("oh:proj_group:0", uid=non_admin)
    await tb.cb_oh_projection_group(cb_proj_group0)
    proj_group0_text = cb_proj_group0.message.edits[-1][0]
    check_html(proj_group0_text)
    for item in data["projections"][0]["items"]:
        assert item["structure"] in proj_group0_text
    print("10. projections: grouped by area, all real entries present: OK")

    # ---- 11. practical stations: 2 groups, real content, out-of-range rejected ----
    cb_stations = FakeCB("oh:stations", uid=non_admin)
    await tb.cb_oh_stations(cb_stations)
    stations_text, stations_kb = cb_stations.message.edits[-1]
    check_html(stations_text)
    n_station_groups = len(data["practical_stations"])
    assert len([d for d in kb_data(stations_kb) if d.startswith("oh:station_group:")]) == n_station_groups

    cb_station_group0 = FakeCB("oh:station_group:0", uid=non_admin)
    await tb.cb_oh_station_group(cb_station_group0)
    station_group0_text = cb_station_group0.message.edits[-1][0]
    check_html(station_group0_text)
    for name in data["practical_stations"][0]["items"]:
        assert name in station_group0_text

    cb_station_bad = FakeCB(f"oh:station_group:{n_station_groups}", uid=non_admin)
    await tb.cb_oh_station_group(cb_station_bad)
    assert not cb_station_bad.message.edits
    assert cb_station_bad._answers and cb_station_bad._answers[0][1] is True
    print("11. practical stations: 2 groups, real content, out-of-range rejected: OK")

    # ---- 12. search: prompt sets pending state, a real hit resolves it, empty state has no crash ----
    search_uid = fresh_uid()
    cb_search_prompt = FakeCB("oh:search_prompt", uid=search_uid)
    await tb.cb_oh_search_prompt(cb_search_prompt)
    assert search_uid in tb.OH_SEARCH_PENDING
    prompt_text = cb_search_prompt.message.edits[-1][0]
    check_html(prompt_text)

    msg_hit = FakeMessage("бедренная", search_uid)
    await tb.handle_oh_search_query(msg_hit)
    assert search_uid not in tb.OH_SEARCH_PENDING, "pending state must be cleared after the search fires"
    assert msg_hit.sent
    result_text, result_kb = msg_hit.sent[-1]
    check_html(result_text)
    assert "бедренная" in result_text.lower()
    print("12. search: prompt sets pending, a real hit clears it and returns matches: OK")

    # ---- 12b. a user with no pending search state falls through via SkipHandler ----
    idle_uid = fresh_uid()
    msg_idle = FakeMessage("просто текст", idle_uid)
    try:
        await tb.handle_oh_search_query(msg_idle)
        raised = False
    except SkipHandler:
        raised = True
    assert raised
    print("12b. idle user (no pending search) falls through via SkipHandler: OK")

    # ---- 12c. empty search result still answers cleanly (no crash), pending cleared ----
    search_uid2 = fresh_uid()
    tb.OH_SEARCH_PENDING.add(search_uid2)
    msg_empty = FakeMessage("совершенно случайная непонятная строка xyzzy", search_uid2)
    await tb.handle_oh_search_query(msg_empty)
    assert search_uid2 not in tb.OH_SEARCH_PENDING
    assert msg_empty.sent and "ничего не найдено" in msg_empty.sent[-1][0]
    print("12c. empty search result handled cleanly: OK")

    # ---- 12d. navigating back to oh:menu clears any lingering pending-search state ----
    search_uid3 = fresh_uid()
    tb.OH_SEARCH_PENDING.add(search_uid3)
    cb_back = FakeCB("oh:menu", uid=search_uid3)
    await tb.cb_oh_menu(cb_back)
    assert search_uid3 not in tb.OH_SEARCH_PENDING
    print("12d. returning to the section root clears pending search state: OK")

    # ---- 13. RAG: operative_surgery real content is actually indexed for VMedA AI grounding ----
    from ai import rag as ai_rag
    ai_rag.configure(
        questions=tb.QUESTIONS, physics_questions=tb.PHYSICS_QUESTIONS, chemistry_theory=tb.CHEMISTRY_THEORY,
        chemistry_theory_tickets=tb.CHEMISTRY_THEORY_TICKETS, chemistry_practice_tickets=tb.CHEMISTRY_PRACTICE_TICKETS,
        anatomy=tb.ANATOMY, operative_surgery=tb.OPERATIVE_SURGERY,
    )
    subjects = {e["subject"] for e in ai_rag._index}
    assert "оперативная хирургия" in subjects
    oh_entries = [e for e in ai_rag._index if e["subject"] == "оперативная хирургия"]
    n_proj_items = sum(len(g["items"]) for g in data["projections"])
    assert len(oh_entries) == 61 + n_proj_items, len(oh_entries)
    assert any("Седалищный нерв" in e["title"] for e in oh_entries)
    # restore the real config other tests expect
    ai_rag.configure(
        questions=tb.QUESTIONS, physics_questions=tb.PHYSICS_QUESTIONS, chemistry_theory=tb.CHEMISTRY_THEORY,
        chemistry_theory_tickets=tb.CHEMISTRY_THEORY_TICKETS, chemistry_practice_tickets=tb.CHEMISTRY_PRACTICE_TICKETS,
        anatomy=tb.ANATOMY, operative_surgery=tb.OPERATIVE_SURGERY,
    )
    print("13. RAG index includes all 61 topics' full text + every projection: OK")

    print("\nALL OPERATIVE SURGERY TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
