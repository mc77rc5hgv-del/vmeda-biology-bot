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
    assert {"biochemistry", "pharmacology", "latin", "law", "physiology"} <= ids


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
