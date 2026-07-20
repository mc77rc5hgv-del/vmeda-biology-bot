# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Telegram bot (`telegram_bot.py`, aiogram 3.7.0, Python 3.12) that helps students at ВМедА (Military
Medical Academy) prepare for entrance/subject exams: Biology, Physics, Chemistry, Anatomy, Histology. Content lives
in top-level JSON files loaded into memory at import time. Hosted on Railway, auto-deploying from `main`.

## Commands

Install deps: `pip install -r requirements.txt` (single dependency: `aiogram==3.7.0`).

Syntax-check after any edit (fast, no token/network needed):
```
python3 -m py_compile telegram_bot.py
```

Run the bot locally (needs a real `BOT_TOKEN`):
```
BOT_TOKEN=<token> STATS_DIR=/some/writable/dir python3 telegram_bot.py
```

### Tests

There is no `tests/` directory in the repo — the test suite lives entirely in the session scratchpad
(`/tmp/claude-.../scratchpad/test_*.py`, one file per feature area: `test_gate.py`, `test_referral_gate.py`,
`test_middleware.py`, `test_battle.py`, `test_battle_remind.py`, `test_admin_stats.py`, `test_bones.py`,
`test_handlers.py`, `test_images.py`, `test_new_sections.py`, `test_new_images.py`, `test_new_material.py`,
`test_restore_access.py`, `test_histology.py`, `test_subscription.py`, `test_admin_lookup.py`,
`test_lower_limb_bones.py`, `test_referral_reminder.py`, and more as features are added). Because they never got
committed, **always check the scratchpad for existing tests before writing new ones** — extend the matching file
rather than duplicating coverage.

Each test file is a standalone async script that imports `telegram_bot` directly (no pytest) and drives real
handler functions with hand-rolled `FakeUser`/`FakeMsg`/`FakeCB` mocks (see any existing test file for the pattern).
Run one with fresh state:
```
rm -f "$SCRATCH/stats.json" "$SCRATCH/stats.json.tmp"
BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11" STATS_DIR="$SCRATCH" python3 "$SCRATCH/test_foo.py"
```
`$SCRATCH` is the session's scratchpad directory. `STATS_DIR` must point there (not the repo) so tests never touch
real `stats.json`. Run every `test_*.py` in the scratchpad after any change to `telegram_bot.py` — the suite is the
only regression safety net.

### Deploy

The dev branch is `claude/vmed-exam-prep-bot-q88a5i`; Railway auto-deploys from `main`. Standard flow after tests
pass:
```
rm -f stats.json stats.json.tmp   # never commit real runtime stats
git add <files> && git commit -m "..."
git push -u origin claude/vmed-exam-prep-bot-q88a5i
git fetch origin main claude/vmed-exam-prep-bot-q88a5i
git checkout main
git merge --ff-only origin/main
git merge --ff-only claude/vmed-exam-prep-bot-q88a5i
git push origin main
git checkout claude/vmed-exam-prep-bot-q88a5i
```

## Architecture

`telegram_bot.py` is organized into banner-commented sections (`grep -n "^# ===="`  to jump between them) — roughly,
in file order: data loading, stats persistence, referral system, paid subscriptions, referral battle, donations,
hidden tickets, keyword search, keyboards, Biology flashcard mode, Physics, Chemistry, deep links, message
handlers, admin panel, main menu, subscription UI/payment, Chemistry theory/tasks/labs, Biology tickets/questions,
Physics tasks, Anatomy, Histology. There is no router/blueprint split — everything registers on one global `dp`.

### Content data model

Each subject has its own top-level JSON loaded once at import (`TICKETS`, `QUESTIONS`, `PHYSICS_QUESTIONS`,
`CHEMISTRY_*`, `ANATOMY`, `HISTOLOGY`, etc.) and its own family of handlers/keyboards — there's no shared "quiz
engine" abstraction between subjects, so a change to one subject's flow (e.g. Biology flashcards) does not
automatically apply to another.

`ANATOMY` (in `anatomy.json`) and `HISTOLOGY` (in `histology.json`) share a deeper nested schema:
`section -> topics{} -> topic{material[], flashcards[], matching_sets[], mnemonics[], picture_quiz[], bones_list,
bone_material_ids, bone_images}`. `bones_list`/`bone_material_ids`/`bone_images` let a topic be browsed either as
one continuous `material` sequence or broken down per named bone/structure ("hub" screens) — see
`get_anatomy_bone_hub_*` / `get_bone_*` helpers. Content style convention: Russian terms in `<b>bold</b>`, Latin
nomenclature in `<i>italic</i>`, `━━━━━━━━━━━━━━` (the `DIVIDER` constant) as a visual sub-section break. Sourced
from the Гайворонский textbook and academy handouts — keep new anatomy/histology material consistent with that
style and cite Latin terms the same way.

Images referenced by content JSON live under `images/<subject>/...` and are resolved relative to `IMAGES_DIR`
(`ANATOMY_IMAGES_DIR`, `HISTOLOGY_IMAGES_DIR`). Photo carousels are hand-rolled per section (delete-and-resend a
new photo message on ⬅️/➡️, not Telegram media groups — `sendMediaGroup` doesn't support `reply_markup`, so a
button-driven album isn't possible without losing the nav buttons).

### Access control (two independent gates)

1. **Referral gate** (`referral_gate_middleware`, an `@dp.update.outer_middleware()`): gates only Biology/Physics/
   Chemistry via an allowlist (`GATED_CALLBACKS` + `GATED_PREFIXES`, checked by `is_gated_callback`) — anything not
   explicitly listed there passes through ungated by default. Free access requires
   `REFERRAL_FULL_ACCESS_THRESHOLD` (2) referrals; below that, `REFERRAL_WARNING_THRESHOLD` (3) free attempts (one
   warning per `REFERRAL_WARNING_COOLDOWN_SECONDS`, 4h) before a hard block.
2. **Anatomy/Histology gates** (`anatomy_access_ok` / `histology_access_ok`): separate boolean functions, not part
   of the referral allowlist — public-flag-gated (`ANATOMY_PUBLIC` / `HISTOLOGY_PUBLIC`, both currently `False`)
   until admin flips them, bypassed by admin or by a subscription with the matching scope.

`has_free_access(user_id)` is the umbrella predicate composing: admin, referral threshold, manual grant
(`stats["manual_access_granted"]`), temp access (`stats["temporary_access"]`), active subscription.

### Subscriptions (`SUBSCRIPTION_TIERS`)

Four tiers keyed 1-4, each a dict of `title/short/scope/duration_days/price_rub/price_stars/emoji/benefits/...`
(`scope` is `"gated"` — Biology/Physics/Chemistry only — or `"all"` — also unlocks Anatomy/Histology early).
Stars payments go through the real Telegram Bot API invoice flow (`send_invoice` → `pre_checkout_query` → 
`successful_payment`, `currency="XTR"`); rubles payments have no real gateway — the buyer is deep-linked to
`@vmeda_helper` and an admin manually confirms/records the tier via the `ADMIN_PENDING` flow. Adding a 5th tier or
changing prices only requires editing the `SUBSCRIPTION_TIERS` dict — the UI/keyboards iterate it dynamically.

### Admin panel pending-action state machine

`ADMIN_PENDING: dict[user_id -> {"action": ..., ...}]` drives every multi-step admin text-input flow (grant/revoke
access, DM a user, record a manual donation, grant a subscription, restore access, etc.). A single
`@dp.message(F.text) async def handle_admin_pending_action(message)` dispatches on `action`, gated by
`is_admin(...) and admin_id in ADMIN_PENDING`, and `raise SkipHandler`s when not applicable so other text handlers
still run. `resolve_user_by_username(raw)` accepts either a `@username` or a raw numeric Telegram ID (looked up in
`stats["total_users"]`) — always prefer it over writing a new username-only lookup.

### Stats persistence

`stats` is a module-level dict populated by `load_stats()` at import and mutated in place everywhere; every write
path must call `save_stats()` (dispatches the JSON write to a single-worker `ThreadPoolExecutor` so it never blocks
the event loop). `load_stats()` has two branches — existing-file `.setdefault(...)` migrations and a fresh-default
dict literal — that must be updated together whenever a new top-level stats key is introduced, or old deployments
will `KeyError` on the migration path. `stats["total_users"]` is a `set` in memory, serialized to/from a `list` for
JSON.

### Broadcasts

Admin-triggered mass messages follow one recurring shape: a `_confirm` handler computes the target cohort and
shows a preview + confirm button, a `_go` handler re-validates the cohort (it may have changed) and calls
`_broadcast()` (all users) or `_broadcast_to(cohort, text, keyboard=None)` (a filtered list), then increments
`stats["broadcast_count"]`. Reuse this shape for new admin broadcasts rather than inventing a new one.
