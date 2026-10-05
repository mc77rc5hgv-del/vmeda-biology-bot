"""codeePay boundary prepared for the real API documentation; no guessed endpoints."""
from typing import Mapping

from ..config import CodeePayConfig
from ..contracts import CheckoutSession, PaymentOrder, ProviderNotReady, VerifiedPayment


class CodeePayProvider:
    name = 'codeepay'

    def __init__(self, config: CodeePayConfig):
        self.config = config

    def public_status(self) -> dict:
        # Keys alone cannot make an unimplemented integration ready for live payments.
        return {'provider': self.name, 'available': False, 'reason': 'api_integration_pending'}

    async def create_checkout(self, order: PaymentOrder) -> CheckoutSession:
        raise ProviderNotReady('codeePay checkout requires its documented API contract')

    async def fetch_payment(self, provider_payment_id: str) -> VerifiedPayment:
        raise ProviderNotReady('codeePay payment verification is not implemented')

    async def verify_webhook(self, body: bytes, headers: Mapping[str, str]) -> VerifiedPayment:
        # Do not assume an HMAC algorithm, header name, event shape, amount unit or status.
        raise ProviderNotReady('codeePay webhook authentication is not implemented')
