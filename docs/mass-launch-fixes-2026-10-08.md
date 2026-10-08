# Fixes following the October 8 readiness audit

Scope: existing single bot owner, gateway, shared learning journal and deployed Mini App.
No new bot poller, live database restore, data-path change, destructive migration, user
list reset, statistics reset, subscription reset or payment-ledger truncation.

## Changes

- R01: identical Telegram edits are no-ops. An undeletable old message no longer prevents
  sending a new text/image answer. Covers biology and other callers of the shared helper.
- R02: launcher and server public mode use the same environment policy. Public entry never
  grants subject/payment/admin access. Production access mode is not changed by this PR.
- R03: bounded, coalescing durable stats writer; independent futures, atomic replace/fsync,
  cooperative copying and shutdown flush. Unknown fields and all users are preserved.
  Under continuous mutations a consistent synchronous fallback after three retries prevents
  starving payment persistence. This fallback can still briefly delay the event loop;
  the change does not claim zero latency or replace the entire legacy store with PostgreSQL.
- R04/R09: bounded auth/user/billing/callback rate windows, payload/text/base64 limits,
  image-byte/pixel validation before decode, no invalid-original forwarding, clean 401
  for malformed signatures, bounded session-token format.
- R05/R12/R14: memory session fallback, no preview after authenticated-session loss,
  invalidate section/group/material access, server navigation journal, dated bookmarks,
  serialized navigation writes, stable quiz delivery IDs, request AND body-read deadlines.
- R06/R07: bounded invoice/recovery admission BEFORE reservation, hard provider deadlines,
  bounded provider parallelism and small background batches. Excess requests fail safely
  without creating quotes. Verification progress keeps a healthy slow batch ready.
- R08: private independent S3 bucket, hourly/startup additive stats/billing/learning snapshots,
  SHA256 manifests, authenticated upload/download verification and isolated restore checks.
  No automatic deletion of historical copies. Services use Railway reference variables;
  credentials are never committed. Initial offsite verification must be observed in logs.
- R10/R11/R13: profile counts merged native progress without double counting; course-size
  denominators, additive Moscow-day activity journal, delivery IDs reject changed retries.
  Old journal rows remain intact. Previously overwritten activity dates cannot be recreated.
  Elapsed minutes are not invented from event counts; the home prompt does not promise them.
- R15/R16: shared bounded HTTP pools, streamed media, gateway overload response, protected
  `/internal/sync/operations` (backup state, billing queue/progress and stats barriers),
  read-only scheduled readiness monitoring and isolated mixed HTTP load in CI.
- R17: production Node static server without runtime `npx` installs. DOMPurify 3.4.16 and
  source-map-js 1.2.2 are pinned local packages containing unchanged upstream production
  files, licences and SHA256 provenance. Vendoring is the fallback for inaccessible npm
  in this execution environment. Indexed-source-map regression checks and scheduled
  dependency scanning are added. Production uses the committed package lock.
- R18: new invoices use a callback URL without a pathname secret. A callback is only a hint:
  merchant-authenticated codeePay fetch, immutable order/proof/amount/currency and receipt
  idempotency remain mandatory. Legacy callback URLs remain supported for existing invoices;
  platform logs containing older callback paths must retain restricted access.

The existing published frontend is mirrored into main so CI tests the same UI being shipped.
The frontend deployment branch receives the same UI fixes separately. Layout and subject icons
are unchanged. Known OCR splits in law are corrected without changing material IDs. Latin
availability and the actual histology practical-image coverage are disclosed accurately;
missing medically verified images are not replaced with arbitrary pictures. Pharmacology
maintenance remains visible. Generic image zoom has keyboard controls and focus restoration.
The separate, unpublished anatomy import PR21 is not merged as part of these fixes.

## Validation and remaining release acceptance

All application writes during local testing use fresh synthetic directories. No real bank
charges, Telegram broadcasts or production load tests are performed. Sandbox blocks TCP
listeners and Chromium, so actual owner/gateway HTTP integration is delegated to GitHub CI;
local ASGI proxy, SQLite, financial, backup restore and durability checks run independently.
Standalone bot/API local harness bounds selector waits because socket wakeup is prohibited;
application source is not patched for the sandbox.

Public rollout still requires an agreed simultaneous peak and latency/error budget, real
Telegram iOS/Android/Desktop checks, a legitimate bank return/confirmation rehearsal, and
observation of verified offsite owner AND learning copies. The CI load check uses local
synthetic volumes, not Railway media/AI/bank production capacity. A queue rejection is
intentional overload protection, not evidence of supporting unlimited simultaneous payments.
Continuous-write fallback latency and unverified medical images remain explicit limitations.
