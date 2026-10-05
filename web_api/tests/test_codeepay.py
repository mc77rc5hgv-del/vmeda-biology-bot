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


def test_https_config_does_not_mean_provider_ready():
    settings = CodeePayConfig(enabled=True, api_url='https://payments.example/api', api_key='synthetic-value')
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
        await provider.verify_webhook(b'{"status":"paid"}', {'x-signature': 'unverified'})
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
