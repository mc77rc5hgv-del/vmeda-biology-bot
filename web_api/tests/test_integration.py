"""Полный путь end-to-end: подписанная initData -> POST /api/v1/auth/telegram -> session token
-> GET /api/v1/me, читающий РЕАЛЬНЫЕ функции бота (services.access через telegram_bot), а не
заглушки. Единственный тест в этом пакете, который действительно импортирует telegram_bot.py --
поэтому единственный, где нужны BOT_TOKEN/STATS_DIR, выставленные ДО первого обращения к
/api/v1/me (см. web_api/bot_state.py -- импорт ленивый, привязан к первому вызову, а не к
импорту самого web_api.main)."""
import hashlib
import hmac
import json
import os
import tempfile
import time
from urllib.parse import urlencode

# ВАЖНО: эти переменные окружения должны быть выставлены до первого запроса к /api/v1/me --
# именно тогда web_api/bot_state.py делает `import telegram_bot`, который читает STATS_DIR/
# BOT_TOKEN на уровне модуля. STATS_DIR указывает на одноразовую временную директорию -- реальный
# stats.json репозитория (которого и так нет в чекауте, см. .gitignore) этот тест не трогает.
TEST_BOT_TOKEN = "123456789:AAIntegrationTestTokenNotReal00000000"
os.environ.setdefault("BOT_TOKEN", TEST_BOT_TOKEN)
_TEST_STATS_DIR = tempfile.mkdtemp(prefix="web_api_test_stats_")
os.environ.setdefault("STATS_DIR", _TEST_STATS_DIR)
os.environ.setdefault("SESSION_SECRET", "integration-test-session-secret")
with open(os.path.join(os.environ["STATS_DIR"], "stats.json"), "w", encoding="utf-8") as _stats_stream:
    json.dump({}, _stats_stream)

# repositories/knowledge.py открывает JSON-файлы контента ОТНОСИТЕЛЬНЫМ путём -- тест должен
# идти из корня репозитория. pytest.ini/pyproject.toml уже задают rootdir там же, где лежит
# telegram_bot.py, так что os.getcwd() при обычном запуске (`pytest` из корня репо) и так верный;
# на всякий случай не полагаемся на порядок запуска других тестовых файлов.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(_REPO_ROOT)

from fastapi.testclient import TestClient  # noqa: E402

from web_api.main import app  # noqa: E402

client = TestClient(app)


def build_signed_init_data(bot_token: str, user: dict, auth_date: int | None = None) -> str:
    fields = {
        "user": json.dumps(user),
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAH_integration_test",
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_healthz():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_full_auth_and_me_flow_for_unknown_user():
    """Пользователь, которого бот никогда раньше не видел (случайный ID) -- /api/v1/me не должен
    падать, а должен вернуть честные дефолты: нет доступа, нет подписки, не админ, 0 рефералов."""
    unknown_user_id = 900123456789  # заведомо не в ADMIN_IDS и не в тестовых фикстурах
    init_data = build_signed_init_data(
        TEST_BOT_TOKEN, {"id": unknown_user_id, "first_name": "Незнакомец", "username": "unknown_guy"}
    )

    auth_resp = client.post("/api/v1/auth/telegram", json={"init_data": init_data})
    assert auth_resp.status_code == 200, auth_resp.text
    body = auth_resp.json()
    assert body["user_id"] == unknown_user_id
    # Профиль -- из initData (самой свежей), не из stats.json, где этого пользователя вообще нет.
    assert body["first_name"] == "Незнакомец"
    assert body["username"] == "unknown_guy"
    session_token = body["session_token"]
    assert session_token

    me_resp = client.get("/api/v1/me", headers={"Authorization": f"Bearer {session_token}"})
    assert me_resp.status_code == 200, me_resp.text
    me = me_resp.json()
    assert me["user_id"] == unknown_user_id
    assert me["referral_count"] == 0
    assert me["referral_count_this_month"] == 0
    assert me["has_free_access"] is False
    assert me["has_active_subscription"] is False
    assert me["subscription_tier_title"] is None
    assert me["is_admin"] is False


def test_auth_rejects_forged_init_data():
    forged = build_signed_init_data("999999999:WrongTokenEntirely0000000000000000", {"id": 1, "first_name": "X"})
    resp = client.post("/api/v1/auth/telegram", json={"init_data": forged})
    assert resp.status_code == 401


def test_me_rejects_missing_authorization_header():
    resp = client.get("/api/v1/me")
    assert resp.status_code == 401


def test_me_rejects_tampered_session_token():
    resp = client.get("/api/v1/me", headers={"Authorization": "Bearer not.a.valid.token"})
    assert resp.status_code == 401


def test_me_reflects_real_referral_and_admin_state():
    """Настоящая интеграция с services.access -- заводим реферала и назначаем админа НАПРЯМУЮ
    через telegram_bot.stats (как это делают существующие тесты в tests/, см. _bootstrap.py), а
    затем убеждаемся, что /api/v1/me видит ровно то же, что увидел бы сам бот."""
    import telegram_bot as tb  # уже импортирован предыдущими тестами (лениво, через bot_state)

    referrer_id = 900_222_333_444
    referred_id = 900_555_666_777
    tb.stats["total_users"].update([referrer_id, referred_id])
    tb.stats["referrals"][str(referrer_id)] = [referred_id]
    current_month = tb.local_today().strftime("%Y-%m")
    tb.stats["referral_monthly"][str(referrer_id)] = {"month": current_month, "count": 2}
    tb.save_stats()
    # The legacy API reads the file; wait for the queued test data write.
    tb._stats_executor.submit(lambda: None).result()

    init_data = build_signed_init_data(TEST_BOT_TOKEN, {"id": referrer_id, "first_name": "Реферер"})
    session_token = client.post("/api/v1/auth/telegram", json={"init_data": init_data}).json()["session_token"]

    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {session_token}"}).json()
    assert me["referral_count"] == 1
    assert me["referral_count_this_month"] == 2
    assert me["has_free_access"] is True  # >= REFERRAL_FULL_ACCESS_THRESHOLD (2) в этом месяце

    tb.stats["total_users"].discard(referrer_id)
    tb.stats["total_users"].discard(referred_id)
    tb.stats["referrals"].pop(str(referrer_id), None)
    tb.stats["referral_monthly"].pop(str(referrer_id), None)
    tb.save_stats()
    tb._stats_executor.submit(lambda: None).result()


def test_subscription_storefront_and_invoice_are_server_authoritative():
    import copy
    from unittest.mock import AsyncMock
    from web_api.deps import get_current_user_id, get_fresh_bot_module
    from web_api import bot_state
    from web_api.subscriptions import parse_payload
    tb = bot_state.get_bot_module()
    uid = 913987654
    app.dependency_overrides[get_current_user_id] = lambda: uid
    app.dependency_overrides[get_fresh_bot_module] = lambda: tb
    original_create = tb.bot.create_invoice_link
    tb.bot.create_invoice_link = AsyncMock(return_value='https://t.me/$test-invoice')
    before = copy.deepcopy(tb.stats)
    try:
        response = client.get('/api/v1/subscriptions/catalog')
        assert response.status_code == 200, response.text
        catalog = response.json()
        assert catalog['plans']
        assert all(plan['id'] in tb.ACTIVE_SUBSCRIPTION_TIERS for plan in catalog['plans'])
        assert all(plan['price_stars'] == tb.SUBSCRIPTION_TIERS[plan['id']]['price_stars'] for plan in catalog['plans'])
        assert len(catalog['current']['access']) == 11
        assert client.post('/api/v1/subscriptions/invoice', json={'tier_id': 21, 'price_stars': 1}).status_code == 422
        assert client.post('/api/v1/subscriptions/invoice', json={'tier_id': 21, 'user_id': uid + 1}).status_code == 422
        for body in ({'tier_id': 1}, {'tier_id': 30}, {'tier_id': 20}, {'tier_id': 20, 'subject': 'anatomy'}):
            assert client.post('/api/v1/subscriptions/invoice', json=body).status_code == 409
        created = client.post('/api/v1/subscriptions/invoice', json={'tier_id': 21})
        assert created.status_code == 200, created.text
        args = tb.bot.create_invoice_link.call_args.kwargs
        signed = parse_payload(tb, args['payload'])
        assert signed['user_id'] == uid
        assert signed['amount'] == tb.SUBSCRIPTION_TIERS[21]['price_stars']
        assert args['currency'] == 'XTR' and args['provider_token'] == ''
        assert args['prices'][0].amount == signed['amount']
        assert client.get('/api/v1/subscriptions/payments/' + created.json()['payment_id']).json()['status'] == 'processing'
        from aiogram.exceptions import TelegramNetworkError
        from aiogram.methods import CreateInvoiceLink
        tb.bot.create_invoice_link.side_effect = TelegramNetworkError(method=CreateInvoiceLink(title='test', description='test', payload='test', currency='XTR', prices=[]), message='synthetic timeout')
        assert client.post('/api/v1/subscriptions/invoice', json={'tier_id': 21}).status_code == 503
        assert tb.stats == before, 'viewing tariffs / creating invoices changed user data'
    finally:
        tb.bot.create_invoice_link = original_create
        app.dependency_overrides.clear()
    assert client.get('/api/v1/subscriptions/catalog').status_code == 401
    assert client.post('/api/v1/subscriptions/invoice', json={'tier_id': 21}).status_code == 401
