from fastapi.testclient import TestClient

from web_api.deps import get_current_user_id, get_fresh_bot_module
from web_api.main import app


class FakeBot:
    SUBSCRIPTION_TIERS = {7: {"title": "Учебный тариф"}}

    def __init__(self, *, open_subjects=(), unlimited_ai=False, provider=True):
        self.open_subjects = set(open_subjects)
        self.unlimited_ai = unlimited_ai
        self.provider = provider

    def get_subscription(self, _user_id):
        return {"tier": 7, "expires": 1_800_000_000}

    def has_active_subscription(self, _user_id):
        return True

    def has_free_access(self, _user_id):
        return False

    def biology_tickets_download_ok(self, _user_id):
        return "biology" in self.open_subjects

    def has_subject_access(self, _user_id, subject_id):
        return subject_id in self.open_subjects

    def histology_access_ok(self, _user_id):
        return "histology" in self.open_subjects

    def has_unlimited_ai(self, _user_id):
        return self.unlimited_ai

    def ai_requests_left(self, _user_id):
        return 4

    def ai_provider_available(self):
        return self.provider


def _client(fake_bot: FakeBot) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: 123
    app.dependency_overrides[get_fresh_bot_module] = lambda: fake_bot
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def test_subject_access_is_server_calculated_and_restricted():
    client = _client(FakeBot(open_subjects={"biology"}))

    biology = client.get("/api/v1/access/biology")
    chemistry = client.get("/api/v1/access/chemistry")

    assert biology.status_code == 200
    assert biology.json()["can_open_subject"] is True
    assert biology.json()["can_download"] is True
    assert chemistry.json()["can_open_subject"] is False
    assert chemistry.json()["locked_reason"]


def test_open_course_remains_open_but_ai_reflects_provider_state():
    client = _client(FakeBot(provider=False))
    response = client.get("/api/v1/access/pharmacology")

    assert response.status_code == 200
    assert response.json()["can_open_subject"] is True
    assert response.json()["can_use_ai"] is False
    assert response.json()["ai_requests_left"] == 4


def test_subscription_summary_contains_real_tier_and_utc_expiry():
    client = _client(FakeBot(unlimited_ai=True))
    body = client.get("/api/v1/subscription").json()

    assert body["subscription_title"] == "Учебный тариф"
    assert body["subscription_expires_at"].endswith("+00:00")
    assert body["ai_requests_left"] is None
    assert body["can_use_ai"] is True


def test_unknown_subject_is_404():
    response = _client(FakeBot()).get("/api/v1/access/not-a-subject")
    assert response.status_code == 404
