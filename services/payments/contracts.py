"""Provider-neutral contracts. Provider responses are never subscription entitlements."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Protocol


class PaymentStatus(str, Enum):
    PENDING = 'pending'
    PAID = 'paid'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


class ProviderNotReady(RuntimeError):
    """Checkout / verification is unavailable until the real API contract is implemented."""


class PaymentMismatch(ValueError):
    """A verified provider payment does not match the server's original order."""


@dataclass(frozen=True)
class PaymentOrder:
    # Created on the server from the existing bot's tariff, never from a client's price.
    order_id: str
    user_id: int
    tier_id: int
    subject: str | None
    provider: str
    amount_minor: int
    currency: str
    idempotency_key: str

    def __post_init__(self):
        if any(not isinstance(value, str) or not value.strip() for value in (self.order_id, self.idempotency_key, self.provider)):
            raise ValueError('Order identity is required')
        if type(self.user_id) is not int or self.user_id <= 0 or type(self.tier_id) is not int or self.tier_id <= 0:
            raise ValueError('User and tier must be positive integers')
        if type(self.amount_minor) is not int or self.amount_minor <= 0:
            raise ValueError('Amount must be a positive integer in minor currency units')
        if not isinstance(self.currency, str) or not 3 <= len(self.currency) <= 12 or not self.currency.isascii() or not self.currency.isalpha() or self.currency != self.currency.upper():
            raise ValueError('Currency must be an uppercase ASCII code of 3–12 letters')


@dataclass(frozen=True)
class CheckoutSession:
    order_id: str
    provider_payment_id: str
    checkout_url: str


@dataclass(frozen=True)
class VerifiedPayment:
    """Produced ONLY after authenticating the provider event / server-side status response.

    This type is not an HTTP request schema and must never be built from unverified JSON.
    No callback, redirect or browser status can create one directly.
    """
    provider: str
    event_id: str
    provider_payment_id: str
    order_id: str
    amount_minor: int
    currency: str
    status: PaymentStatus
    # Provider-specific evidence stays private and must not be returned to the miniapp.
    evidence: Mapping[str, object] = field(default_factory=dict, repr=False)


def validate_confirmation(order: PaymentOrder, payment: VerifiedPayment, *, provider_payment_id: str) -> None:
    """Validate against the stored quote before considering any subscription write.

    Idempotency, durable receipts and granting access belong to the authoritative bot owner.
    Passing this function alone does not grant access.
    """
    if payment.status is not PaymentStatus.PAID:
        raise PaymentMismatch('Payment is not confirmed as paid')
    if not payment.event_id or not provider_payment_id or payment.provider_payment_id != provider_payment_id:
        raise PaymentMismatch('Provider payment identity does not match')
    if payment.provider != order.provider or payment.order_id != order.order_id:
        raise PaymentMismatch('Payment belongs to a different order or provider')
    if type(payment.amount_minor) is not int or payment.amount_minor != order.amount_minor or payment.currency != order.currency:
        raise PaymentMismatch('Payment amount or currency does not match the stored quote')


class PaymentProvider(Protocol):
    name: str

    async def create_checkout(self, order: PaymentOrder) -> CheckoutSession: ...

    async def fetch_payment(self, provider_payment_id: str) -> VerifiedPayment: ...

    async def verify_webhook(self, body: bytes, headers: Mapping[str, str]) -> VerifiedPayment: ...
