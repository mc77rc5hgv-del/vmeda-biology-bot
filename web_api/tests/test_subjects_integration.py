"""Полный путь через API на РЕАЛЬНЫХ данных (generated_courses/biochemistry.json,
generated_courses/pharmacology.json) -- не на фикстуре, как web_api/tests/test_content.py,
и не на моках, как miniapp/src/lib/mockData.ts. Если эти данные когда-нибудь поменяют форму,
тест должен упасть -- он и есть проверка того, что "контент-адаптер для 2-3 предметов" (Этап 3)
реально доводит один предмет от JSON до HTTP-ответа."""
import os
import tempfile

os.environ.setdefault("BOT_TOKEN", "123456789:AASubjectsIntegrationTestToken0000000")
os.environ.setdefault("SESSION_SECRET", "subjects-integration-test-secret")
os.environ.setdefault("STATS_DIR", tempfile.mkdtemp(prefix="web_api_subjects_test_stats_"))

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(_REPO_ROOT)

import hashlib  # noqa: E402
import hmac  # noqa: E402
import json  # noqa: E402
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
    assert {"biochemistry", "pharmacology", "latin", "law"} <= ids


def test_list_subjects_requires_auth():
    resp = client.get("/api/v1/subjects")
    assert resp.status_code == 401


def test_biochemistry_subject_detail_has_real_sections():
    """The approved practicum is exposed as six grouped navigation blocks."""
    resp = client.get("/api/v1/subjects/biochemistry", headers=_auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Биохимия"
    section_ids = {s["id"] for s in body["sections"]}
    assert section_ids == {"guide", "foundations", "metabolism", "regulation", "clinical", "reference"}
    assert all(section["kind"] == "grouped" for section in body["sections"])
    assert sum(section["item_count"] for section in body["sections"]) >= 400


def test_biochemistry_guide_and_material_round_trip():
    headers = _auth_headers()
    section = client.get("/api/v1/subjects/biochemistry/sections/guide", headers=headers).json()
    assert section["kind"] == "grouped"
    assert {group["id"] for group in section["groups"]} == {"about", "contents"}
    group = client.get(
        "/api/v1/subjects/biochemistry/sections/guide/groups/about", headers=headers
    ).json()
    first_item = group["items"][0]
    assert first_item["id"] == "guide_about_p1"
    assert first_item["order"] == 1
    assert first_item["title"] == "О практикуме и как с ним работать"

    material = client.get(
        f"/api/v1/materials/biochemistry/guide/{first_item['id']}", headers=headers
    ).json()
    assert material["title"] == first_item["title"]
    assert "ВОЕННО-МЕДИЦИНСКАЯ АКАДЕМИЯ" in material["content_html"]
    assert "все 19 занятий" in material["content_html"]
    assert material["sources"] == []  # source locators are retained internally but hidden in student UI
    assert material["group_id"] == "about"
    assert material["prev_id"] is None and material["next_id"] is None


def test_biochemistry_practical_class_and_material_round_trip():
    headers = _auth_headers()
    section = client.get("/api/v1/subjects/biochemistry/sections/foundations", headers=headers).json()
    assert section["kind"] == "grouped"
    group_ids = {g["id"] for g in section["groups"]}
    assert group_ids == {f"class_{number}" for number in range(1, 7)}

    group = client.get(
        "/api/v1/subjects/biochemistry/sections/foundations/groups/class_1", headers=headers
    ).json()
    first_item = group["items"][0]
    assert first_item["id"] == "b1_u1_p1"
    assert first_item["title"] == "Занятие 1. Биохимия белков. Структура и функции белков"

    material = client.get(
        f"/api/v1/materials/biochemistry/foundations/{first_item['id']}", headers=headers
    ).json()
    assert material["title"] == first_item["title"]
    assert "Белки — высокомолекулярные" in material["content_html"]
    assert material["group_id"] == "class_1"
    assert material["next_id"] == group["items"][1]["id"]


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
        "/api/v1/materials/biochemistry/credit/does-not-exist", headers=_auth_headers()
    )
    assert resp.status_code == 404


def test_media_endpoint_serves_real_file_when_present():
    """Реальный урок с media -- Биохимия v2 (см. commit message) убрала свой единственный
    раздел с картинками ("Введение", вместе с остальным неструктурированным конспектом), так
    что теперь единственный предмет с media -- Фармакология, причём внутри ГРУППИРОВАННОГО
    раздела (course/drug_comparison, 455 уроков). Обход поэтому заходит и в groups, а не
    только в плоские секции, как раньше, когда единственный известный пример был плоским."""
    headers = _auth_headers()
    for subject_id in ("pharmacology", "biochemistry"):
        subject = client.get(f"/api/v1/subjects/{subject_id}", headers=headers).json()
        for section_summary in subject["sections"]:
            section = client.get(
                f"/api/v1/subjects/{subject_id}/sections/{section_summary['id']}", headers=headers
            ).json()
            if section["kind"] == "grouped":
                item_refs = []
                for group_summary in section["groups"]:
                    group = client.get(
                        f"/api/v1/subjects/{subject_id}/sections/{section['id']}/groups/{group_summary['id']}",
                        headers=headers,
                    ).json()
                    item_refs.extend(group["items"])
            else:
                item_refs = section["items"]
            for item in item_refs:
                material = client.get(
                    f"/api/v1/materials/{subject_id}/{section['id']}/{item['id']}", headers=headers
                ).json()
                if material["media"]:
                    media_resp = client.get(
                        f"/api/v1/materials/{subject_id}/{section['id']}/{item['id']}/media/0",
                        headers=headers,
                    )
                    assert media_resp.status_code == 200
                    assert len(media_resp.content) > 0
                    return
    pytest.fail("expected at least one lesson with media, found none")
