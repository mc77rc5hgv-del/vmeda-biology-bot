"""External-payment scaffolding tests. No real keys, network calls or bot data."""
from dataclasses import replace

import pytest

from services.payments.config import CodeePayConfig
from services.payments.contracts import PaymentMismatch, PaymentOrder, PaymentStatus, ProviderNotReady, VerifiedPayment, validate_confirmation
from services.payments.providers.codeepay import CodeePayProvider


def order():
    return PaymentOrder(order_id='order-test', user_id=123, tier_id=21, subject=None,
                        provider='codeepay', amount_minor=12900, currency='RUB', idempotency_key='order-test')


def payment():
    return VerifiedPayment(provider='codeepay', event_id='event-test', provider_payment_id='payment-test',
                           order_id='order-test', amount_minor=12900, currency='RUB', status=PaymentStatus.PAID)


def test_defaults_disabled_and_secrets_not_exposed():
    settings = CodeePayConfig.from_env({})
    assert settings.enabled is False
    assert CodeePayProvider(settings).public_status()['available'] is False
    settings = replace(settings, api_key='synthetic-api-value', webhook_secret='synthetic-webhook-value')  # noqa: S106 — fake fixture
    assert 'synthetic-api-value' not in repr(settings)
    assert 'synthetic-webhook-value' not in repr(settings)
    public = CodeePayProvider(settings).public_status()
    assert 'synthetic' not in str(public)


@pytest.mark.parametrize('env', [{'CODEEPAY_ENABLED': 'yes'}, {'CODEEPAY_TIMEOUT_SECONDS': '0'},
                                {'CODEEPAY_TIMEOUT_SECONDS': '61'}, {'CODEEPAY_TIMEOUT_SECONDS': 'invalid'}])
def test_invalid_settings_fail_closed(env):
    with pytest.raises(ValueError):
        CodeePayConfig.from_env(env)


@pytest.mark.parametrize('url', ['', 'http://payments.example', 'https://user:password@payments.example',
                                'https://payments.example?token=example', 'https://payments.example#fragment'])
def test_no_insecure_or_credential_bearing_api_url(url):
    with pytest.raises(ValueError):
        CodeePayConfig(enabled=True, api_url=url, api_key='synthetic-value').validate_checkout_configuration()


def test_only_official_api_accepts_credentials():
    settings = CodeePayConfig(enabled=True, api_url='https://payments.example/api', api_key='synthetic-value')
    with pytest.raises(ValueError):
        settings.validate_checkout_configuration()
    assert CodeePayProvider(settings).public_status()['available'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled', [False, True])
async def test_unimplemented_provider_never_accepts_money_or_webhooks(enabled, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    provider = CodeePayProvider(CodeePayConfig(enabled=enabled, api_url='https://payments.example', api_key='synthetic-value'))
    with pytest.raises(ProviderNotReady):
        await provider.create_checkout(order())
    with pytest.raises(ProviderNotReady):
        await provider.fetch_payment('payment-test')
    with pytest.raises(ProviderNotReady):
        await provider.verify_webhook(b'{"order_id":"payment-test","status":"paid"}', {'x-signature': 'unverified'})
    assert list(tmp_path.iterdir()) == [], 'Scaffold created or changed persistent data'


@pytest.mark.parametrize('updates', [{'amount_minor': 0}, {'amount_minor': -1}, {'amount_minor': 129.0},
                                    {'amount_minor': True}, {'user_id': True}, {'user_id': 0},
                                    {'tier_id': -1}, {'currency': 'rub'}, {'currency': 'РУБ'},
                                    {'order_id': ''}, {'order_id': 1}, {'idempotency_key': ''}, {'currency': None}])
def test_order_rejects_ambiguous_amounts_and_missing_identity(updates):
    with pytest.raises(ValueError):
        replace(order(), **updates)


def test_verified_confirmation_matches_original_server_order():
    original = order()
    validate_confirmation(original, payment(), provider_payment_id='payment-test')
    assert original == order()  # Validation does not mutate the quote or grant access.


@pytest.mark.parametrize('updates', [{'status': PaymentStatus.PENDING}, {'status': PaymentStatus.FAILED},
                                    {'status': PaymentStatus.CANCELLED}, {'status': 'paid'}, {'provider': 'other'},
                                    {'order_id': 'another-order'}, {'provider_payment_id': 'another-payment'},
                                    {'event_id': ''}, {'amount_minor': 1}, {'amount_minor': 12900.0}, {'currency': 'USD'}])
def test_foreign_underpaid_or_unconfirmed_payment_cannot_pass(updates):
    with pytest.raises(PaymentMismatch):
        validate_confirmation(order(), replace(payment(), **updates), provider_payment_id='payment-test')


@pytest.mark.asyncio
async def test_documented_api_units_headers_and_provider_confirmed_settlement():
    import json
    import httpx
    requests = []
    def respond(request):
        body = json.loads(request.content)
        requests.append((request.url.path, body))
        assert request.headers['X-Api-Key'] == 'test-api-key'
        if request.url.path == '/initiate_payment':
            assert body['method_slug'] == 'sbp' and body['amount'] == 129
            assert body['metadata']['vmeda_order'] == 'order-test'
            return httpx.Response(200, json={'url': 'https://payment.codeepay.xyz/transfer/test', 'order_id': 'provider-test', 'amount': 129})
        assert body == {'order_id': 'provider-test'}
        return httpx.Response(200, json={'payment_order_id': 'provider-test', 'payment_id': 'charge-test', 'payment_method': 'sbp',
            'payment_status': 'success', 'payment_deposited': True, 'payment_amount': 129,
            'payment_deposited_amount': 122.55, 'payment_commission_amount': 6.45,
            'payment_metadata': {'vmeda_order': 'order-test', 'vmeda_proof': 'order-test'}})
    provider = CodeePayProvider(CodeePayConfig.from_env({'CODEEPAY_ENABLED': 'true', 'CODEEPAY_API_KEY': 'test-api-key'}), transport=httpx.MockTransport(respond))
    session = await provider.create_checkout(order())
    result = await provider.verify_webhook(b'{"order_id":"provider-test","amount":1,"status":"paid"}', {})
    validate_confirmation(order(), result, provider_payment_id=session.provider_payment_id)
    assert result.evidence['net_minor'] == 12255 and result.evidence['fee_minor'] == 645
    assert len(requests) == 2, 'Webhook JSON was trusted instead of requerying merchant API'


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [{'payment_deposited': False}, {'payment_deposited': 'true'}, {'payment_amount': True},
                                  {'payment_amount': 1.001}, {'payment_method': 'card'}, {'payment_order_id': 'foreign'},
                                  {'payment_commission_amount': 1}, {'payment_metadata': {}}, {'payment_deposited_amount': -1}])
async def test_malformed_or_unpaid_provider_response_cannot_confirm(change):
    import httpx
    body = {'payment_order_id': 'provider-test', 'payment_id': 'charge-test', 'payment_method': 'sbp',
            'payment_status': 'success', 'payment_deposited': True, 'payment_amount': 129,
            'payment_deposited_amount': 122.55, 'payment_commission_amount': 6.45,
            'payment_metadata': {'vmeda_order': 'order-test', 'vmeda_proof': 'order-test'}}
    body.update(change)
    provider = CodeePayProvider(CodeePayConfig.from_env({'CODEEPAY_ENABLED': 'true', 'CODEEPAY_API_KEY': 'test-api-key'}), transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    with pytest.raises(PaymentMismatch):
        result = await provider.fetch_payment('provider-test')
        validate_confirmation(order(), result, provider_payment_id='provider-test')
