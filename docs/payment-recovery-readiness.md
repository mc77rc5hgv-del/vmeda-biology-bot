# Payment recovery and readiness

Production data paths and schemas are retained. No user, subscription, payment,
learning row or old event is removed. Billing snapshots are verified before
startup recovery; interrupted `creating` rows become `creation_unknown` with
an additional event. The changes do not enable public access or merge the
separate anatomy-course import.

## Dependency update

The bot/API share pinned aiogram 3.31.0, aiohttp 3.14.4, FastAPI 0.142.2,
Starlette 1.7.0, Pydantic 2.13.5 and Uvicorn 0.54.0. requirements.txt contains
the tested production graph. `pip check` succeeds; OSV querybatch reports no
advisories for the 42 locked packages at the time of verification. This is a
point-in-time check, not a promise against future vulnerabilities.

## Creation recovery

Only documented validation rejection (422) and authentication rejection
(401/403) permit retry of the same preserved quote/key. Timeouts, 400, 5xx,
invalid successful responses and cancellation remain ambiguous and MUST NOT
create another invoice automatically. Unknown creation blocks new quotes until
reconciled, without silently expiring the guard after an hour.

A webhook with an unknown provider ID triggers a fresh authenticated get_payment.
Recovery requires an EXISTING local quote with matching merchant metadata,
secret proof, RUB amount and provider identity. Successful recovery binds the
provider ID and returns the original order to polling or settles it exactly once.
It never accepts callback payload amount/status as evidence. A callback arriving
before the checkout response cannot overwrite the durable paid state.

codeePay exposes no documented lookup by merchant order/creation idempotency key.
If the response was lost and no callback arrives, recovery requires an operator
finding the provider invoice ID in the merchant cabinet. Blind automatic creation
would risk double payment and is deliberately forbidden.

## Admin UI and API

Bot: Admin panel -> SBP codeePay -> select a problematic order.

- `bind`: enter provider invoice ID plus a reason. The API checks the immutable
  quote; a verified paid invoice is settled, an unpaid one resumes polling.
- `close_not_created`: after checking the merchant cabinet, record the explicit
  finding that no invoice exists. The preserved quote becomes creation_closed;
  the user can request a new quote. This is a human assertion, not provider-
  authenticated evidence of absence. A late VERIFIED payment can still recover
  the closed historical quote; no payment is discarded.
- `apply_review`: re-read paid status and re-evaluate the current entitlement.
  Only safe original-tier grants are allowed; downgrade/term reduction is refused.
  Financial totals are not counted again: the resolution log has method
  admin_resolution, price 0, and references the original payment.
- `keep_existing`: after customer agreement, record the reason and preserve
  the current subscription. This resolves support handling without pretending
  a refund or an additional grant took place. Refunds still require the merchant
  support process; no automatic refund endpoint is documented in this API.

Each bot action has an input preview and confirmation. All runtime actions require
an administrator and a 10–1000-character reason. API equivalent:
POST /api/v1/subscriptions/admin/sbp/{order_id}/reconcile
with action, provider_id (bind only), note; actor comes from signed auth.
Receipts retain their original fields and append resolution_history; the existing
billing events journal records recovery/decisions. Repeated settlement/resolution
must not grant twice. Card-transfer and Stars flows remain available.

## Health endpoints

/livez: process liveness, no dependency calls.
/healthz and /readyz: 200 ready or 503 unavailable; cache disabled; no identities.
Gateway checks its existing read-only learning DB and owner readiness.
Owner checks the running sync API, remote learning storage, and, if SBP is enabled,
billing configuration, ledger integrity, polling task/heartbeat and observed
provider health. Polling periodically reads a known invoice status without creating
invoices or moving money; an empty journal cannot independently attest upstream
acceptance before the first request. Failures do not stop the Telegram bot.
/internal/sync/storage: token-protected gateway storage readiness, no owner recursion.
Railway's existing /healthz check now covers dependencies; do not use /livez as
release readiness. Both owner and gateway must be upgraded for the new contract.

## Validation

All tests use synthetic identities, mock provider calls and isolated temporary
stats/learning/billing files. Live validation must use read-only health/status;
no production order is reconciled automatically as part of deployment.
