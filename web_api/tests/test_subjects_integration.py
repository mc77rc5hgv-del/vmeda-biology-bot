"""Полный путь через API на РЕАЛЬНЫХ данных (generated_courses/biochemistry.json,
generated_courses/pharmacology.json) -- не на фикстуре, как web_api/tests/test_content.py,
и не на моках, как miniapp/src/lib/mockData.ts. Если эти данные когда-нибудь поменяют форму,
тест должен упасть -- он и есть проверка того, что "контент-адаптер для 2-3 предметов" (Этап 3)
реально доводит один предмет от JSON до HTTP-ответа."""
import json
import os
import tempfile

os.environ.setdefault("BOT_TOKEN", "123456789:AASubjectsIntegrationTestToken0000000")
os.environ.setdefault("SESSION_SECRET", "subjects-integration-test-secret")
_TEST_STATS_DIR = tempfile.mkdtemp(prefix="web_api_subjects_test_stats_")
os.environ.setdefault("STATS_DIR", _TEST_STATS_DIR)
with open(os.path.join(os.environ["STATS_DIR"], "stats.json"), "w", encoding="utf-8") as _stats_stream:
    json.dump({}, _stats_stream)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(_REPO_ROOT)

import hashlib  # noqa: E402
import hmac  # noqa: E402
import time  # noqa: E402
from urllib.parse import urlencode  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from web_api.main import app  # noqa: E402

client = TestClient(app)


def _auth_headers() -> dict:
    bot_token = os.environ["BOT_TOKEN"]
    fields = {
        "user": json.dumps({"id": 900_777_888_999, "first_name": "Тест Контента"}),
        "auth_date": str(int(time.time())),
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    init_data = urlencode(fields)
    token = client.post("/api/v1/auth/telegram", json={"init_data": init_data}).json()["session_token"]
    return {"Authorization": f"Bearer {token}"}


def test_list_subjects_includes_real_dynamic_courses():
    resp = client.get("/api/v1/subjects", headers=_auth_headers())
    assert resp.status_code == 200
    ids = {s["id"] for s in resp.json()}
    assert {
        "biochemistry", "pharmacology", "latin", "law", "physiology", "operative_surgery", "anatomy",
    } <= ids


def test_list_subjects_requires_auth():
    resp = client.get("/api/v1/subjects")
    assert resp.status_code == 401


def test_biochemistry_subject_detail_has_real_sections():
    resp = client.get("/api/v1/subjects/biochemistry", headers=_auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Биохимия"
    section_ids = {s["id"] for s in body["sections"]}
    assert {"core_course", "credit", "exam_tickets"} <= section_ids
    core = next(s for s in body["sections"] if s["id"] == "core_course")
    assert core["kind"] == "flat"
    assert core["item_count"] == 47  # см. отчёт аудита


def test_biochemistry_flat_section_and_material_round_trip():
    headers = _auth_headers()
    section = client.get("/api/v1/subjects/biochemistry/sections/core_course", headers=headers).json()
    assert section["kind"] == "flat"
    first_item = section["items"][0]
    assert first_item["id"] == "core_p1_1"
    assert first_item["order"] == 1

    material = client.get(
        f"/api/v1/materials/biochemistry/core_course/{first_item['id']}", headers=headers
    ).json()
    assert material["title"] == first_item["title"]
    assert "Военно-медицинская акаде" in material["content_html"]  # реальный текст источника
    assert material["sources"] == ["учебное пособие.pdf, стр. 1"]
    assert material["group_id"] is None
    assert material["prev_id"] is None  # первый урок раздела
    assert material["next_id"] == section["items"][1]["id"]


def test_pharmacology_grouped_section_and_material_round_trip():
    headers = _auth_headers()
    section = client.get("/api/v1/subjects/pharmacology/sections/course", headers=headers).json()
    assert section["kind"] == "grouped"
    group_ids = {g["id"] for g in section["groups"]}
    assert "foundations" in group_ids

    group = client.get(
        "/api/v1/subjects/pharmacology/sections/course/groups/foundations", headers=headers
    ).json()
    assert group["items"], "foundations group must have at least one lesson"
    first_item = group["items"][0]

    material = client.get(
        f"/api/v1/materials/pharmacology/course/{first_item['id']}", headers=headers
    ).json()
    assert material["title"] == first_item["title"]
    assert material["group_id"] == "foundations"
    # show_sources=False у Фармакологии -- источники не должны утечь в ответ API, даже если они
    # есть в исходном JSON (см. content.py::_lesson_to_material и handlers/dynamic_courses.py).
    assert material["sources"] == []


def test_unknown_subject_returns_404():
    resp = client.get("/api/v1/subjects/does-not-exist", headers=_auth_headers())
    assert resp.status_code == 404


def test_unknown_section_returns_404():
    resp = client.get("/api/v1/subjects/biochemistry/sections/does-not-exist", headers=_auth_headers())
    assert resp.status_code == 404


def test_unknown_material_returns_404():
    resp = client.get(
        "/api/v1/materials/biochemistry/core_course/does-not-exist", headers=_auth_headers()
    )
    assert resp.status_code == 404


def test_physiology_course_and_boundary_control_round_trip():
    headers = _auth_headers()
    detail = client.get("/api/v1/subjects/physiology", headers=headers)
    assert detail.status_code == 200, detail.text
    sections = {section["id"]: section for section in detail.json()["sections"]}
    assert sections["course"]["item_count"] == 23
    assert sections["boundary-controls"]["kind"] == "grouped"

    course = client.get("/api/v1/subjects/physiology/sections/course", headers=headers).json()
    first_topic = course["items"][0]
    material = client.get(
        f"/api/v1/materials/physiology/course/{first_topic['id']}", headers=headers
    )
    assert material.status_code == 200, material.text
    assert material.json()["title"] == first_topic["title"]
    assert material.json()["content_html"]
    assert material.json()["sources"] == []

    controls = client.get(
        "/api/v1/subjects/physiology/sections/boundary-controls", headers=headers
    ).json()
    assert len(controls["groups"]) == 11
    first_control_id = controls["groups"][0]["id"]
    group = client.get(
        f"/api/v1/subjects/physiology/sections/boundary-controls/groups/{first_control_id}",
        headers=headers,
    ).json()
    assert group["items"]

    media_material = None
    for item in group["items"]:
        candidate = client.get(
            f"/api/v1/materials/physiology/boundary-controls/{item['id']}", headers=headers
        ).json()
        if candidate["media"]:
            media_material = candidate
            break
    assert media_material is not None
    media = client.get(
        f"/api/v1/materials/physiology/boundary-controls/{media_material['id']}/media/0",
        headers=headers,
    )
    assert media.status_code == 200
    assert media.content


def test_operative_surgery_volumes_and_material_round_trip():
    """Реальные operative_surgery.json: 4 тома, 61 тема — проверяем, что раздел "Тома"
    (сгруппированный, как у Фармакологии) действительно доводит студента до текста конкретной
    темы, с правильным prev/next внутри тома (см. web_api/static_content.py)."""
    headers = _auth_headers()
    detail = client.get("/api/v1/subjects/operative_surgery", headers=headers)
    assert detail.status_code == 200, detail.text
    sections = {section["id"]: section for section in detail.json()["sections"]}
    assert sections["volumes"]["kind"] == "grouped"
    assert sections["volumes"]["item_count"] == 61  # см. отчёт аудита: 61 тема в 4 томах

    volumes = client.get("/api/v1/subjects/operative_surgery/sections/volumes", headers=headers).json()
    assert [g["id"] for g in volumes["groups"]] == ["I", "II", "III", "IV"]
    volume_i = next(g for g in volumes["groups"] if g["id"] == "I")
    assert volume_i["item_count"] == 10  # см. отчёт аудита: том I — 10 тем

    group = client.get(
        "/api/v1/subjects/operative_surgery/sections/volumes/groups/I", headers=headers
    ).json()
    assert len(group["items"]) == 10
    first_topic = group["items"][0]
    assert first_topic["id"] == "01"

    material = client.get(
        f"/api/v1/materials/operative_surgery/volumes/{first_topic['id']}", headers=headers
    )
    assert material.status_code == 200, material.text
    body = material.json()
    assert body["title"] == first_topic["title"]
    assert body["content_html"]  # реальный текст подтем, не заглушка
    assert body["group_id"] == "I"
    assert body["prev_id"] is None  # первая тема тома
    assert body["next_id"] == group["items"][1]["id"]


def _set_anatomy_maintenance_override(value) -> None:
    """anatomy_maintenance_mode_enabled() reads stats["anatomy_maintenance_override"] from disk on
    EVERY request (web_api/deps.py::get_fresh_bot_module calls bot_state.refresh_stats(), which
    replaces tb.stats with a fresh tb.load_stats() read of STATS_FILE) -- an in-memory-only mutation
    of tb.stats would just get overwritten by the very next request, so this writes straight to the
    test's own isolated stats.json on disk, the same file the test bootstrap at the top of this
    module initialized to {}."""
    stats_path = os.path.join(os.environ["STATS_DIR"], "stats.json")
    with open(stats_path, "r", encoding="utf-8") as stream:
        data = json.load(stream)
    data["anatomy_maintenance_override"] = value
    with open(stats_path, "w", encoding="utf-8") as stream:
        json.dump(data, stream)


def _first_anatomy_topic_id(module_key: str) -> str:
    """Реальный id темы читается напрямую из anatomy.json, а не через /sections/course/groups/{id}
    -- у платного модуля этот эндпоинт сам гейтится (403), так что через API список тем платного
    модуля недоступен ДО того, как есть подписка, ровно как и в самом боте (см. cb_anatomy_section)."""
    with open("anatomy.json", encoding="utf-8") as stream:
        anatomy = json.load(stream)
    return next(iter(anatomy[module_key]["topics"]))


def test_anatomy_default_maintenance_mode_locks_every_module_for_non_admin():
    """Свежая база (админ ни разу не трогал тумблер техрежима -- см. CLAUDE.md "Anatomy maintenance
    mode") -- ANATOMY_MAINTENANCE_MODE=True по умолчанию закрывает ВЕСЬ раздел, включая бесплатные
    модули, для всех, кроме админа/помощника. Список модулей при этом всё равно виден (см.
    "hide vs relabel" в CLAUDE.md) -- только помечен locked, а не скрыт."""
    _set_anatomy_maintenance_override(None)
    headers = _auth_headers()
    section = client.get("/api/v1/subjects/anatomy/sections/course", headers=headers).json()
    assert len(section["groups"]) == 10  # см. отчёт по данным: 10 модулей Кафарова
    assert all(g["locked"] for g in section["groups"])
    assert all("технич" in g["locked_reason"].lower() for g in section["groups"])

    free_group_id = section["groups"][0]["id"]
    resp = client.get(
        f"/api/v1/subjects/anatomy/sections/course/groups/{free_group_id}", headers=headers
    )
    assert resp.status_code == 403


def test_anatomy_free_module_open_and_paid_module_locked_once_maintenance_is_off():
    """С выключенным техрежимом (админ явно открыл раздел) вступает в силу обычный
    ANATOMY_FREE_SECTIONS-гейт по модулям -- module1_osteology бесплатен всем,
    module7_nervous нет (см. handlers/anatomy.py::ANATOMY_FREE_SECTIONS)."""
    _set_anatomy_maintenance_override(False)
    headers = _auth_headers()

    section = client.get("/api/v1/subjects/anatomy/sections/course", headers=headers).json()
    groups_by_id = {g["id"]: g for g in section["groups"]}
    assert groups_by_id["module1_osteology"]["locked"] is False
    assert groups_by_id["module1_osteology"]["locked_reason"] is None
    assert groups_by_id["module7_nervous"]["locked"] is True
    assert "подписк" in groups_by_id["module7_nervous"]["locked_reason"].lower()

    group = client.get(
        "/api/v1/subjects/anatomy/sections/course/groups/module1_osteology", headers=headers
    ).json()
    assert group["items"], "module1_osteology must have real topics"
    first_topic = group["items"][0]

    material = client.get(
        f"/api/v1/materials/anatomy/course/{first_topic['id']}", headers=headers
    )
    assert material.status_code == 200, material.text
    body = material.json()
    assert body["title"] == first_topic["title"]
    assert body["content_html"]  # реальный текст, не заглушка -- модуль бесплатный
    assert body["group_id"] == "module1_osteology"
    assert body["sources"] == []

    locked_group_resp = client.get(
        "/api/v1/subjects/anatomy/sections/course/groups/module7_nervous", headers=headers
    )
    assert locked_group_resp.status_code == 403

    nervous_topic_id = _first_anatomy_topic_id("module7_nervous")
    locked_material_resp = client.get(
        f"/api/v1/materials/anatomy/course/{nervous_topic_id}", headers=headers
    )
    assert locked_material_resp.status_code == 403


def test_anatomy_unknown_module_is_not_found_not_locked():
    _set_anatomy_maintenance_override(False)
    headers = _auth_headers()
    resp = client.get(
        "/api/v1/subjects/anatomy/sections/course/groups/module99_missing", headers=headers
    )
    assert resp.status_code == 404


def test_media_endpoint_serves_real_file_when_present():
    """Биохимия: реальный урок с media (см. отчёт по данным -- 5 таких уроков в предмете).
    Находим первый попавшийся динамически, а не хардкодим id -- список media может измениться
    при перегенерации контента, а сам факт "если media есть, эндпоинт должен её отдать" -- нет."""
    headers = _auth_headers()
    subject = client.get("/api/v1/subjects/biochemistry", headers=headers).json()
    for section_summary in subject["sections"]:
        section = client.get(
            f"/api/v1/subjects/biochemistry/sections/{section_summary['id']}", headers=headers
        ).json()
        if section["kind"] != "flat":
            continue
        for item in section["items"]:
            material = client.get(
                f"/api/v1/materials/biochemistry/{section['id']}/{item['id']}", headers=headers
            ).json()
            if material["media"]:
                media_resp = client.get(
                    f"/api/v1/materials/biochemistry/{section['id']}/{item['id']}/media/0",
                    headers=headers,
                )
                assert media_resp.status_code == 200
                assert len(media_resp.content) > 0
                return
    pytest.fail("expected at least one biochemistry lesson with media, found none")
