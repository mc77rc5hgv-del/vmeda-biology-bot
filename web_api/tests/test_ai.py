"""web_api/routers/ai.py -- тестируется ИЗОЛИРОВАННО от настоящего AI-пайплайна (ai/vision_parser.py,
ai/service.py и т.д. уже тщательно покрыты tests/test_ai_mvp.py на уровне самого бота) -- здесь
проверяется только логика самого роутера: порядок гвардов (автовыключатель/квота/лок/конкурентность),
маппинг исключений в HTTP-статусы, base64-декодирование фото, извлечение confidence_note и то, что
слот AI_CONCURRENCY_GATE всегда освобождается. Тот же FakeBot-паттерн, что и в test_access.py --
дешёвая заглушка с ровно нужными атрибутами вместо реального `import telegram_bot`."""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from web_api.deps import get_current_user_id, get_fresh_bot_module
from web_api.main import app


class FakeLock:
    def __init__(self, locked=False):
        self._locked = locked

    def locked(self):
        return self._locked

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class FakeConcurrencyGate:
    def __init__(self, allow=True):
        self.allow = allow
        self.acquired = 0
        self.released = 0

    def try_acquire(self):
        if not self.allow:
            return False
        self.acquired += 1
        return True

    def release(self):
        self.released += 1


class FakeVisionParser:
    def __init__(self, task=None, usage=None, raise_exc=None):
        self.task = task
        self.usage = usage or {}
        self.raise_exc = raise_exc
        self.calls = []

    async def parse_task(self, *, image_bytes=None, text=None):
        self.calls.append({"image_bytes": image_bytes, "text": text})
        if self.raise_exc:
            raise self.raise_exc
        return self.task, self.usage


class AIRefusalErrorFake(Exception):
    def __init__(self, ai_attempts_log=None):
        super().__init__("refused")
        self.ai_attempts_log = ai_attempts_log or []


class FakeBot:
    AIRefusalError = AIRefusalErrorFake

    def __init__(
        self, *,
        provider_available=True, breaker_tripped=False, quota_ok=True,
        lock_locked=False, gate_allow=True, precache=None,
        vision_parser=None, first_message_result=("ответ", "ответ"), first_message_raises=None,
        unlimited_ai=False, requests_left=2,
    ):
        self.provider_available = provider_available
        self.breaker_tripped = breaker_tripped
        self.quota_ok = quota_ok
        self._lock = FakeLock(locked=lock_locked)
        self.AI_CONCURRENCY_GATE = FakeConcurrencyGate(allow=gate_allow)
        self.precache = precache
        self.ai_vision_parser = vision_parser or FakeVisionParser()
        self.ai_service = SimpleNamespace(format_answer_html=lambda answer: f"<p>{answer}</p>")
        self.ai_router = SimpleNamespace(route_bucket=lambda task: "problem")
        self._first_message_result = first_message_result
        self._first_message_raises = first_message_raises
        self.unlimited_ai = unlimited_ai
        self._requests_left = requests_left
        self.AI_LOW_CONFIDENCE_NOTE = "\n\n⚠️ сверь этот ответ с курсом."
        self.cost_calls = []
        self.attempts_cost_calls = []
        self.raw_text_alias_calls = []
        self.first_message_calls = []

    def ai_provider_available(self):
        return self.provider_available

    def ai_circuit_breaker_tripped(self):
        return self.breaker_tripped

    def ai_quota_ok(self, _user_id):
        return self.quota_ok

    def _get_ai_user_lock(self, _user_id):
        return self._lock

    def get_raw_text_precache_answer(self, _text):
        return self.precache

    def record_ai_cost(self, usage):
        self.cost_calls.append(usage)

    def record_ai_attempts_cost(self, log):
        self.attempts_cost_calls.append(log)

    def record_raw_text_alias(self, text, task):
        self.raw_text_alias_calls.append((text, task))

    def resize_image_for_ai(self, raw_bytes):
        return raw_bytes

    def has_unlimited_ai(self, _user_id):
        return self.unlimited_ai

    def ai_requests_left(self, _user_id):
        return self._requests_left

    async def get_first_message_ai_answer(self, user_id, session, task):
        self.first_message_calls.append((user_id, task))
        if self._first_message_raises:
            raise self._first_message_raises
        display_answer, quick_answer = self._first_message_result
        session["quick_answer"] = quick_answer
        return display_answer, {"role": "user", "content": "..."}


def _client(fake_bot: FakeBot) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: 123
    app.dependency_overrides[get_fresh_bot_module] = lambda: fake_bot
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def test_invalid_mode_returns_400():
    client = _client(FakeBot())
    resp = client.post("/api/v1/ai/solve", json={"mode": "audio"})
    assert resp.status_code == 400


def test_text_mode_without_text_returns_400():
    client = _client(FakeBot())
    resp = client.post("/api/v1/ai/solve", json={"mode": "text", "text": "   "})
    assert resp.status_code == 400


def test_photo_mode_without_image_returns_400():
    client = _client(FakeBot())
    resp = client.post("/api/v1/ai/solve", json={"mode": "photo"})
    assert resp.status_code == 400


def test_photo_mode_with_invalid_base64_returns_400():
    client = _client(FakeBot())
    resp = client.post("/api/v1/ai/solve", json={"mode": "photo", "image_base64": "not-valid-base64!!!"})
    assert resp.status_code == 400


def test_provider_unavailable_returns_503():
    client = _client(FakeBot(provider_available=False))
    resp = client.post("/api/v1/ai/solve", json={"mode": "text", "text": "вопрос"})
    assert resp.status_code == 503


def test_circuit_breaker_tripped_returns_503():
    client = _client(FakeBot(breaker_tripped=True))
    resp = client.post("/api/v1/ai/solve", json={"mode": "text", "text": "вопрос"})
    assert resp.status_code == 503


def test_quota_exhausted_returns_429():
    client = _client(FakeBot(quota_ok=False))
    resp = client.post("/api/v1/ai/solve", json={"mode": "text", "text": "вопрос"})
    assert resp.status_code == 429


def test_lock_already_held_returns_429():
    client = _client(FakeBot(lock_locked=True))
    resp = client.post("/api/v1/ai/solve", json={"mode": "text", "text": "вопрос"})
    assert resp.status_code == 429


def test_concurrency_gate_full_returns_503():
    client = _client(FakeBot(gate_allow=False))
    resp = client.post("/api/v1/ai/solve", json={"mode": "text", "text": "вопрос"})
    assert resp.status_code == 503


def test_text_precache_hit_skips_pipeline_and_charges_nothing():
    vision_parser = FakeVisionParser()
    fake_bot = FakeBot(precache=("кэшированный ответ", "вопрос + суффикс"), vision_parser=vision_parser)
    client = _client(fake_bot)
    resp = client.post("/api/v1/ai/solve", json={"mode": "text", "text": "вопрос"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer_html"] == "<p>кэшированный ответ</p>"
    assert body["low_confidence"] is False
    assert body["confidence_note"] is None
    assert vision_parser.calls == []  # precache-хит не трогает парсер вообще
    assert fake_bot.first_message_calls == []
    assert fake_bot.cost_calls == []


def test_text_fresh_solve_calls_pipeline_and_records_alias():
    task = object()
    vision_parser = FakeVisionParser(task=task, usage={"input_tokens": 10, "output_tokens": 5})
    fake_bot = FakeBot(
        precache=None, vision_parser=vision_parser,
        first_message_result=("свежий ответ", "свежий ответ"),
    )
    client = _client(fake_bot)
    resp = client.post("/api/v1/ai/solve", json={"mode": "text", "text": "новый вопрос"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer_html"] == "<p>свежий ответ</p>"
    assert body["low_confidence"] is False
    assert vision_parser.calls == [{"image_bytes": None, "text": "новый вопрос"}]
    assert fake_bot.cost_calls == [{"input_tokens": 10, "output_tokens": 5}]
    assert fake_bot.raw_text_alias_calls == [("новый вопрос", task)]
    assert fake_bot.first_message_calls == [(123, task)]


def test_photo_mode_decodes_base64_and_calls_pipeline():
    import base64
    task = object()
    vision_parser = FakeVisionParser(task=task, usage={})
    fake_bot = FakeBot(vision_parser=vision_parser, first_message_result=("фото-ответ", "фото-ответ"))
    client = _client(fake_bot)
    raw = b"\xff\xd8\xfffakejpegbytes"
    resp = client.post("/api/v1/ai/solve", json={"mode": "photo", "image_base64": base64.b64encode(raw).decode()})
    assert resp.status_code == 200, resp.text
    assert resp.json()["answer_html"] == "<p>фото-ответ</p>"
    assert vision_parser.calls == [{"image_bytes": raw, "text": None}]


def test_low_confidence_note_extracted_when_answer_differs_from_quick_answer():
    fake_bot = FakeBot(
        first_message_result=("чистый ответ\n\n⚠️ сверь этот ответ с курсом.", "чистый ответ"),
    )
    client = _client(fake_bot)
    resp = client.post("/api/v1/ai/solve", json={"mode": "text", "text": "вопрос"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer_html"] == "<p>чистый ответ</p>"  # без пометки -- та ушла отдельным полем
    assert body["low_confidence"] is True
    assert body["confidence_note"] == "⚠️ сверь этот ответ с курсом."


def test_ai_refusal_returns_422_and_records_attempts_cost():
    exc = AIRefusalErrorFake(ai_attempts_log=[{"provider": "openai", "status": "refused", "usage": {}}])
    fake_bot = FakeBot(first_message_raises=exc)
    client = _client(fake_bot)
    resp = client.post("/api/v1/ai/solve", json={"mode": "text", "text": "вопрос"})
    assert resp.status_code == 422
    assert fake_bot.attempts_cost_calls == [exc.ai_attempts_log]
    assert fake_bot.AI_CONCURRENCY_GATE.released == 1  # слот всё равно освобождён


def test_generic_exception_returns_500_and_releases_gate():
    fake_bot = FakeBot(first_message_raises=RuntimeError("boom"))
    client = _client(fake_bot)
    resp = client.post("/api/v1/ai/solve", json={"mode": "text", "text": "вопрос"})
    assert resp.status_code == 500
    assert fake_bot.AI_CONCURRENCY_GATE.acquired == 1
    assert fake_bot.AI_CONCURRENCY_GATE.released == 1


def test_concurrency_gate_released_on_success():
    fake_bot = FakeBot()
    client = _client(fake_bot)
    resp = client.post("/api/v1/ai/solve", json={"mode": "text", "text": "вопрос"})
    assert resp.status_code == 200, resp.text
    assert fake_bot.AI_CONCURRENCY_GATE.acquired == 1
    assert fake_bot.AI_CONCURRENCY_GATE.released == 1


def test_requests_left_null_when_unlimited():
    fake_bot = FakeBot(unlimited_ai=True)
    client = _client(fake_bot)
    resp = client.post("/api/v1/ai/solve", json={"mode": "text", "text": "вопрос"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["requests_left"] is None
    assert body["session_active"] is True


def test_requests_left_reflects_remaining_quota():
    fake_bot = FakeBot(requests_left=0)
    client = _client(fake_bot)
    resp = client.post("/api/v1/ai/solve", json={"mode": "text", "text": "вопрос"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["requests_left"] == 0
    assert body["session_active"] is False


def test_ai_solve_requires_auth():
    resp = TestClient(app).post("/api/v1/ai/solve", json={"mode": "text", "text": "вопрос"})
    assert resp.status_code == 401
