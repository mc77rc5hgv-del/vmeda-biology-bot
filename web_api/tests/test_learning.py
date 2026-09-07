from web_api import learning
from fastapi.testclient import TestClient
from web_api.deps import get_current_user_id
from web_api.main import app


def test_learning_state_persists_progress_favorites_and_quiz(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIAPP_LEARNING_DB", str(tmp_path / "learning.sqlite3"))
    material = {
        "subject_id": "biochemistry",
        "section_id": "course",
        "material_id": "lesson-1",
        "subject_title": "Биохимия",
        "section_title": "Курс",
        "material_title": "Гликолиз",
        "material_order": 1,
        "total_in_section": 10,
    }

    learning.touch_material(42, material)
    learning.set_material_flag(42, "biochemistry", "course", "lesson-1", "completed", True)
    learning.set_material_flag(42, "biochemistry", "course", "lesson-1", "favorite", True)
    learning.record_quiz_attempt(42, "biochemistry", "course", "lesson-1", True)

    state = learning.get_state(42)
    assert state["completed_keys"] == ["biochemistry/course/lesson-1"]
    assert state["completed_by_subject"] == {"biochemistry": 1}
    assert state["favorites"][0]["material_title"] == "Гликолиз"
    assert state["last_material"]["material_id"] == "lesson-1"
    assert state["quiz_attempts"] == 1
    assert state["quiz_correct"] == 1


def test_learning_state_is_isolated_per_user(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIAPP_LEARNING_DB", str(tmp_path / "learning.sqlite3"))
    learning.touch_material(1, {"subject_id": "latin", "section_id": "credit", "material_id": "1"})
    assert learning.get_state(1)["last_material"] is not None
    assert learning.get_state(2)["last_material"] is None


def test_learning_http_flow(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIAPP_LEARNING_DB", str(tmp_path / "learning.sqlite3"))
    app.dependency_overrides[get_current_user_id] = lambda: 77
    client = TestClient(app)
    try:
        response = client.post("/api/v1/learning/materials/touch", json={
            "subject_id": "biochemistry", "section_id": "credit", "material_id": "ticket-1",
            "subject_title": "Биохимия", "section_title": "Зачёт",
            "material_title": "Билет 1", "material_order": 1, "total_in_section": 109,
        })
        assert response.status_code == 200
        completed = client.post(
            "/api/v1/learning/materials/biochemistry/credit/ticket-1/completed",
            json={"value": True},
        )
        assert completed.status_code == 200
        assert completed.json()["completed_total"] == 1
        assert client.get("/api/v1/learning/state").json()["last_material"]["material_title"] == "Билет 1"
    finally:
        app.dependency_overrides.clear()


def test_learning_requires_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIAPP_LEARNING_DB", str(tmp_path / "learning.sqlite3"))
    assert TestClient(app).get("/api/v1/learning/state").status_code == 401
