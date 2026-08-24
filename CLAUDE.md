# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Telegram bot (`telegram_bot.py`, aiogram 3.7.0, Python 3.12) that helps students at ВМедА (Military
Medical Academy) prepare for entrance/subject exams: Biology, Physics, Chemistry, Anatomy, Histology. Content lives
in top-level JSON files loaded into memory at import time. Hosted on Railway, auto-deploying from `main`.

## Commands

Install deps: `pip install -r requirements.txt` (`aiogram==3.7.0` for the bot itself, `python-docx==1.2.0` for the
per-subject Word-file export buttons).

Syntax-check after any edit (fast, no token/network needed):
```
python3 -m py_compile telegram_bot.py
```

Lint (config in `pyproject.toml`; `tests/` gets a scoped ignore for the deliberately compact mock-class style —
see "Known pitfalls"):
```
ruff check .
```
`ruff` isn't in `requirements.txt` (it's a dev-only tool, not a runtime dependency) — install with `pip install ruff`
if it's not already on your PATH. CI installs it explicitly.

Run the bot locally (needs a real `BOT_TOKEN`):
```
BOT_TOKEN=<token> STATS_DIR=/some/writable/dir python3 telegram_bot.py
```

### Tests

Live in `tests/` (one file per feature area: `test_gate.py`, `test_referral_gate.py`, `test_middleware.py`,
`test_battle.py`, `test_battle_remind.py`, `test_admin_stats.py`, `test_bones.py`, `test_handlers.py`,
`test_images.py`, `test_new_sections.py`, `test_new_images.py`, `test_new_material.py`, `test_restore_access.py`,
`test_histology.py`, `test_subscription.py`, `test_admin_lookup.py`, `test_lower_limb_bones.py`,
`test_referral_reminder.py`, and more as features are added). **Always check for an existing test file covering
the area you're touching before writing a new one** — extend the matching file rather than duplicating coverage.

Each test file is a standalone async script that imports `telegram_bot` directly (no pytest) and drives real
handler functions with hand-rolled `FakeUser`/`FakeMsg`/`FakeCB` mocks (see any existing test file for the
pattern). They import `from _bootstrap import tb` instead of `import telegram_bot as tb` directly —
`tests/_bootstrap.py` puts the repo root on `sys.path`, chdirs there for the JSON-file loads at import time, and
points `STATS_DIR` at a fresh `tempfile.mkdtemp()` so every run is isolated from the real `stats.json` and from
other test files, with no manual cleanup needed between runs.

Run everything (CI does this on every push):
```
python3 tests/run_all.py
```
Run a single file the same way you'd run any script:
```
python3 tests/test_foo.py
```
This is the only regression safety net — run the full suite after any change to `telegram_bot.py`.

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
bone_material_ids, bone_images, atlas_images}`. `bones_list`/`bone_material_ids`/`bone_images` let a topic be
browsed either as one continuous `material` sequence or broken down per named bone/structure ("hub" screens) —
see `get_anatomy_bone_hub_*` / `get_bone_*` helpers; only osteology topics (`skull`, `trunk_bones`,
`upper_limb_bones`, `lower_limb_bones`) use this hub structure. Each bone's `bone_images` list mixes two photo
sources under one JSON array, distinguished only by their `credit` string — `get_bone_images(topic_key, bone_id,
kind=None|"slides"|"atlas")` filters at query time (`kind="atlas"` keeps only `ANATOMY_ATLAS_CREDITS` — Неттер/
Гайворонский; `kind="slides"` keeps everything else, i.e. the older "ВМедА, кафедра нормальной анатомии — учебная
презентация" lecture photos) rather than the JSON ever storing them as two separate lists. The bone hub shows a
"📽 Слайды (презентация)" and/or "🖼 Атлас (Неттер/Гайворонский)" button, each only when that bone actually has
images of that kind. Topics with no natural per-bone breakdown (arthrology, myology, and the whole of
`splanchnology`/`angiology`/`neurology`/`sense_organs`) instead carry a flat `atlas_images: [{path, caption,
credit}]` list on the topic dict, shown via a "🖼 Атлас" button (`anatomy_atlas:{topic}:{page}`,
`get_topic_atlas_images`) — same album mechanism as the bone hub's atlas/slides buttons, just keyed by topic
instead of by bone. **`ANATOMY`'s top-level
section dict and topic dict are the only source of truth for navigation** — `get_anatomy_menu_keyboard`,
`get_topic_section_key`, `get_anatomy_topic_data` all iterate `ANATOMY.items()` directly, so adding a whole new
section (e.g. `splanchnology`) is a pure content change, zero code changes, as long as the topic dict shape
matches. Content style convention: Russian terms in `<b>bold</b>`, Latin nomenclature in `<i>italic</i>`,
`━━━━━━━━━━━━━━` (the `DIVIDER` constant) as a visual sub-section break. Sourced from the Гайворонский textbook and
academy handouts — keep new anatomy/histology material consistent with that style and cite Latin terms the same
way. `ANATOMY` currently has 7 sections mirroring Гайворонский's two-volume program: Vol. 1 (locomotor system) —
`osteology`/`arthrology`/`myology`; Vol. 2 (everything else) — `splanchnology`/`angiology`/`neurology`/
`sense_organs`. Atlas photos (Ф. Неттер + И.В. Гайворонский illustrations) live under `images/anatomy/atlas/`,
one file per `<topic-id>-<N>.jpg`; `N` is NOT guaranteed contiguous from 1 (some placeholder illustrations in the
source material were never filled with a real photo) — always discover real files by regex/glob per topic rather
than assuming `range(1, count+1)`.

Every topic across all 7 sections now has non-empty `flashcards`/`matching_sets`/`mnemonics`, **except** the three
osteology bone-hub topics `trunk_bones`/`upper_limb_bones`/`lower_limb_bones` — those still have empty topic-level
study-aid lists because their study aids live per-bone instead (`bone` field on each flashcard/pair/mnemonic,
queried via `get_bone_flashcards`/`get_bone_pairs`/`get_bone_mnemonics`), the same mechanism `skull` already uses
exhaustively (52 flashcards, 6 matching sets, 7 mnemonics, all tagged to specific bone IDs) — the other three
bone-hub topics just haven't had that per-bone treatment done yet.

All four osteology bone-hub topics (`skull`, `trunk_bones`, `upper_limb_bones`, `lower_limb_bones`) additionally
have a `latin_terms: [{la, ru, bone}]` list — 338 terms total, sourced from the official Латинская анатомическая
номенклатура per Гайворонский, each tagged to a specific bone ID exactly like flashcards/pairs/mnemonics above.
`get_bone_latin_terms(topic_key, bone_id)` filters to one bone (powers the "🏛 Латинские термины" button in the
bone hub, `anatomy_bone_latin_start:{topic}:{bone}`); `get_topic_latin_terms(topic_key)` pools every bone's terms
for the whole-topic trainer (`anatomy_latin_start:{topic}`) shown on the topic screen. Both trainers share the
same `ANATOMY_LATIN_SESSIONS` multiple-choice quiz engine (`start_anatomy_latin_session(user_id, topic_key,
bone_id=None)`) — distractors for a per-bone session are still drawn from the *whole topic's* term pool, not just
that bone, so small bones (2-3 terms) still get plausible wrong answers. Topics outside osteology (arthrology,
myology, splanchnology, ...) don't have `latin_terms` at all — the field and its buttons are conditional on
non-empty content, so nothing renders for them.

A third, global trainer lives on the main Anatomy menu screen itself (`anatomy_latin_all_start`, "🏛 Тест по
латинским терминам") — `get_all_latin_terms()` pools `latin_terms` across *every* section/topic in `ANATOMY`
(currently just the 338 osteology terms, since no other section has the field yet, but the pooling is generic so
any future section's terms are picked up automatically). It reuses the same `start_anatomy_latin_session(...,
is_global=True)` / `ANATOMY_LATIN_SESSIONS` engine — `is_global` sessions have `topic_key=bone_id=None` and a
bigger sample (`ANATOMY_LATIN_ALL_SESSION_SIZE`, 20 vs. 15 for topic/bone sessions). Only a *fully completed*
global run (not aborted via "🛑 Закончить") calls `record_anatomy_latin_score(user_id, correct, total)`, which
keeps one personal-best entry per user in `stats["anatomy_latin_scores"][uid] = {best_correct, best_total,
attempts}` — a repeat run only overwrites the stored best if its percent is strictly higher, or tied on a larger
sample (`attempts` still increments either way). `get_anatomy_latin_leaderboard_text(user_id=None)` ranks by
percent (ties broken by raw `best_correct`) and reuses `donor_display_name()` for the row labels — the same
opt-in/anonymous name logic as the donor leaderboard, even though there's no anonymity toggle specific to this
feature (a user who's `donor_hide_name`'d themselves for donations stays hidden here too, incidentally).

Images referenced by content JSON live under `images/<subject>/...` and are resolved relative to `IMAGES_DIR`
(`ANATOMY_IMAGES_DIR`, `HISTOLOGY_IMAGES_DIR`). Anatomy photos are sent as native Telegram albums
(`send_anatomy_album`, via `Message.answer_media_group`) — up to `ANATOMY_ALBUM_PAGE_SIZE` (10, Telegram's
`sendMediaGroup` cap) photos per message, swipeable in place with no further bot round-trips, instead of the
older delete-and-resend single-photo carousel. `sendMediaGroup` itself can't carry a `reply_markup`, so
`send_anatomy_album` follows the album with a small separate text message carrying the prev/next-page and back
buttons. `sendMediaGroup` also requires 2-10 items, not 1-10 — a page whose remaining images total exactly 1 is
sent via plain `answer_photo` instead of a one-item album (`build_input_media_photo` builds the `InputMediaPhoto`
items for the multi-photo case). Other subjects' photo carousels (Biology/Physics/Histology) are unaffected by
this and still hand-roll delete-and-resend on ⬅️/➡️.

Every local-`path` anatomy image is cached by Telegram `file_id` after its first upload
(`ANATOMY_FILE_ID_CACHE`, persisted to `anatomy_file_id_cache.json` under `STATS_DIR`, same async-write pattern as
`save_stats()`) — `_anatomy_image_media(img)` returns the cached `file_id` string instead of a fresh `FSInputFile`
once one exists, so repeat views of the same photo skip re-reading the file from disk and re-uploading it.
`_cache_anatomy_file_id(img, sent_message)` populates the cache from the real `Message.photo` Telegram returns;
it's a safe no-op when `sent_message` has no `.photo` (e.g. test mocks), so tests never need to simulate the cache.

### Operative Surgery (Оперативная хирургия)

A top-level subject (`operative_surgery.json`, loaded via `repositories/knowledge.py` like every other content
bank, handlers in `handlers/operative_surgery.py` — own `Router`, imported at the very end of `telegram_bot.py`
next to `handlers/histology.py`, same reason: needs `tb.OPERATIVE_SURGERY`/`DIVIDER`/`safe_edit_text` already
defined). **Deliberately free for everyone** — no referral gate, no subscription tier references it, callback
prefix `oh:*` never appears in `GATED_CALLBACKS_*`/`GATED_PREFIXES_*`, so it passes through
`referral_gate_middleware` ungated by default like Anatomy's admin bypass or the support/donation screens.

**v2 (current): real full-text content, not a summary-only skeleton.** The section was first shipped (v1) from a
thin source pack that only had real prose for 1 of 13 planned per-lesson facets; it was then rebuilt from a second,
much larger source pack ("VMEDA Operative Surgery Full Content") — a genuine 69-section topographic-anatomy/
operative-surgery text (kafedral practicum + textbook material, `Практикум ВМедА 2017` as top source priority,
same `source_priority` list as v1). `operative_surgery.json`'s schema changed completely as a result:
`curriculum` (23 lesson stubs, one per practicum session) was replaced by `topics` — 61 entries organized into 4
`volumes` (`I`–`IV`, mirroring the source's own "ТОМ I..IV" grouping: конечности → голова/шея → грудь/живот →
забрюшинное пространство/почка/таз), each topic broken into real `subtopics` (`id`, `title`, `text` — HTML-ready,
`**bold**` already converted to `<b>`) totaling ~33K characters of real material across the whole bank, built by a
one-time parser script (not committed — scratchpad-only ETL, see the session that authored this) that walked the
source markdown's `#`/`##`/`###` heading structure. **Nothing here is fabricated** — `text` is the source's own
prose; `quick_review` per topic is mechanically extracted from the source's own callout lines (headings like
"Запомнить"/"Практическое значение"/"Почему это важно" plus any standalone `**bold**` line), falling back to a
one-line-per-subtopic recap (still literal text pulled from `text`, never new content) only for the handful of
topics whose source prose has no such callout at all — so every topic always has *something* to show under
"⚡ Быстро повторить", but it's always traceable back to real sourced text.

**Control questions follow the source's own granularity, not a forced per-topic one.** The source only writes
questions at two levels: topic `"01"` ("Общая оперативная техника") has its own list (the source's own §1.8) —
`topics[0]["control_questions"]` — and volumes I/II/III each end with a "Контроль тома" cross-topic list, stored
as `volume["control_questions"]`. **Volume IV has no such list in the source at all** — `get_oh_volume_keyboard()`
simply doesn't render a "📋 Контрольные вопросы тома" button for it, and no other topic besides `"01"` gets a
"❓ Контрольные вопросы" button on its topic-hub screen (`get_oh_topic_keyboard()` only adds it when
`topic["control_questions"]` is non-empty) — same "honest gap, no invented content" principle as v1, just scoped
tighter now that almost everything else is real. The source itself never supplies an answer key for these
questions either, so they're rendered as a plain self-check list ("ответ ищи в полном материале"), not a
tap-to-reveal quiz — building reveal-answer infrastructure for a question bank with no verified answers would risk
serving a wrong "official" answer nobody actually wrote.

`instrument_groups` (11 groups, 97 real kafedral instrument names — the list/naming/grouping is still exactly the
exam album's own official structure) and `projections` (6 anatomical-area groups — верхняя/нижняя конечность,
суставы, голова, лицо, шея — instead of one flat 15-entry list, 28 entries total) come from the same source's own
reference sections (§65/§66) and are fully populated, same as v1. New in v2: `practical_stations` (2 groups —
"Конечности, голова, шея" and "Грудь, живот, забрюшинное пространство, таз", 24 real station names total from the
source's own §67), reachable from the root menu ("🎓 Практические станции") the same way instruments/projections
are.

**Instrument PHOTOS went through three deliveries and are, deliberately, NOT all from the kafedral album.** The
first two photo packs (10 groups, 93 positions, real crops from the kafedral exam album, position-by-position
mapped and verified against each pack's own `manifest.json`) were fully replaced by a third pack the user
explicitly asked for after being warned about its provenance: that pack's own `README.txt` states 94 of its 97
photos are generic product photos pulled from commercial listings (Yandex Market, uno-med.ru, cm-instrumente.ru —
"a typical example of an instrument with this name", not the department's own physical copy); only 3 positions
(a new group's two items plus one tracheostomy hook) are real crops from the reference album. The user was told
this in plain terms — including the licensing/attribution risk of redistributing third-party commercial-site
photos — and chose to proceed anyway, so this is a deliberate, informed tradeoff (full photographic coverage +
one new instrument group the album packs never covered, at the cost of photo authenticity), not an oversight.
Each item carries `image_source: "web"|"reference_album"` precisely so this provenance isn't lost — `image_source`
is metadata only, not read by any handler logic (`oh_group_has_photos()` still keys off `"image" in item`, not
the source), kept for future traceability if the department ever wants to swap specific positions back to real
album crops. `get_oh_instruments_text()` carries an explicit disclaimer ("Фото — типовые образцы... могут немного
отличаться от конкретного экземпляра на кафедре") for exactly this reason — the one place in this whole section
where a screen text is honest about NOT being 1:1 with the department's own physical instrument.

The new 11th group — "Инструменты для пластинчатых швов" (plate/lead-shot sutures, 4 items: an eye-instrument
set, two real-album crops of the metal plates and wire/lead beads, and crampon forceps) — didn't exist in either
of the first two packs; it's the only genuinely new instrument content this delivery added, the other 93
positions are the same album-sourced list, just with new photos wired to them. Also note the third pack's own
`group_number` field is a WITHIN-group index (1..N per group), unlike the WHOLE-album `id` (1..97) — don't
confuse the two when reading `manifest.json` archives kept for reference.

`handlers/operative_surgery.py`'s `oh_group_has_photos(group)` requires EVERY item in a group to have `image`
before switching that group to photo mode — a group is never shown as a partially-filled album with unexplained
gaps, it's all-or-nothing, same "honest gap" principle as everywhere else in this section (today: all 11 groups
qualify). A photographed group (`send_oh_instrument_album`, `oh:instr_group:{idx}:{page}`) is sent as a native
Telegram album exactly like Anatomy's `send_anatomy_album` (`OH_INSTR_ALBUM_PAGE_SIZE = 10` — `sendMediaGroup`'s
own cap, a lone-item page falls back to `answer_photo`; captions are the instrument's real name) — including its
own `file_id` cache (`OH_FILE_ID_CACHE`/`oh_instrument_file_id_cache.json` under `STATS_DIR`, same reasoning and
shape as `ANATOMY_FILE_ID_CACHE`: skip re-uploading a photo Telegram has already seen). Images live under
`images/operative_surgery/instruments/{01..11}/{NN}.{jpg|png}` — filenames are the position number, not the
(Cyrillic, space-containing) name from the source album; the real name lives in the JSON `name` field, and every
`{group_folder}/{file}` → `image` mapping was asserted 1:1 against the manifest's own `name` field (and its
declared `sha256`) at copy time, never inferred from filename order alone. The group-picker keyboard
(`get_oh_instruments_keyboard()`) prefixes a photographed group's button with 📷 (today: all 11).
`docs/operative_surgery_instruments_inventory.md` is a generated (not hand-maintained) group→instrument→image-path
listing for manual spot-checking — regenerate it from `operative_surgery.json` rather than hand-editing if the
instrument data ever changes.

Navigation is `oh:menu` → `oh:volumes` → `oh:volume:{id}:{page}` (paginated, `OH_TOPIC_PAGE_SIZE = 10` — volume
III alone has 25 topics) → `oh:topic:{id}` (hub screen: intro + "📖 Полный материал"/"⚡ Быстро повторить"/
optional "❓ Контрольные вопросы") → `oh:material:{id}:{page}` (one subtopic per page, prev/next). Projections/
stations follow the same two-level "group list → group contents" shape (`oh:projections`→`oh:proj_group:{idx}`,
`oh:stations`→`oh:station_group:{idx}`); instruments follow it too but its `oh:instruments`→`oh:instr_group:{idx}:{page}`
group-contents step branches on `oh_group_has_photos()` as described above.

Search (`oh:search_prompt` → `OH_SEARCH_PENDING` (a plain `set[user_id]`, not a multi-step dict like
`ADMIN_PENDING`/`ASSISTANT_PENDING`) → `handle_oh_search_query`) is defined directly in `telegram_bot.py`, NOT
inside `handlers/operative_surgery.py`, and positioned in the file BEFORE `handle_keyword_search` (the
Biology-keyword-search fallback that unconditionally handles any plain-text message with no `SkipHandler` guard).
This ordering is load-bearing: message handlers registered via `dp.include_router()` at the very end of the file
(same spot as the rest of this section) would land AFTER `handle_keyword_search` in the dispatch chain, so it
would swallow every OH search query before `handle_oh_search_query` ever saw it. Same reasoning `ADMIN_PENDING`/
`ASSISTANT_PENDING`'s own text handlers already live in `telegram_bot.py` rather than their respective handler
modules — see `handlers/admin.py`'s own docstring for the precedent. `search_operative_surgery()` now searches all
four data shapes (topics by title/full subtopic text, instruments, projections, stations) and returns a 4-tuple,
up from v1's 3.

`ai.rag.build_index()`/`configure()` take an `operative_surgery: dict = None` parameter (default `None` keeps the
function's existing callers, including `scripts/`-level ones that don't pass it, working unchanged) and index
every topic's full subtopic text (concatenated into one entry per topic) plus every `projections` item — 61 + 28
entries. `instrument_groups`/`practical_stations` are deliberately NOT indexed (bare name lists with no
explanatory prose to ground an answer in). Because this content is now genuine topographic anatomy, RAG queries
about body cavities/organs legitimately surface both `"анатомия"` and `"оперативная хирургия"` matches side by
side (see `tests/test_ai_mvp.py`'s check 25c) — that's real cross-subject grounding, not noise. `ai/prompts.py`'s
`SYSTEM_PROMPT` and the AI section's own menu copy (`get_ai_menu_text()`/`get_ai_announcement_text()`) mention
"оперативной хирургии" alongside the other four subjects for the same reason anatomy was added there earlier.

### Normal Physiology (Нормальная физиология)

A top-level subject (`physiology.json`, loaded via `repositories/knowledge.py` like every other content bank,
handlers in `handlers/physiology.py` — own `Router`, imported at the very end of `telegram_bot.py` next to
`handlers/histology.py`/`handlers/operative_surgery.py`, same "needs `tb.PHYSIOLOGY`/`DIVIDER`/`safe_edit_text`
already defined" reason). **Free for everyone** — no referral gate, no subscription tier references it, callback
prefix `phys:*` never appears in `GATED_CALLBACKS_*`/`GATED_PREFIXES_*`, same choice as Operative Surgery.

**Content is entirely and only from the user's own source pack** — 23 topics parsed out of a pasted Markdown
course whose own citations name exactly three working files («Том 1 1.pdf», «Том 2 1.pdf», «Физа учебник.pdf») —
no volume-3 topics were ever generated. Built by a one-time ETL pass (scratchpad-only, not committed to the repo —
same "ETL script stays out of the repo" convention as Operative Surgery's v2 parser): `parse.py` walks the
source's own `##`/`###` heading structure per topic into the schema below, `build_quiz.py` then appends a
question bank mined only from already-parsed structured fields. `physiology.json`'s top level is `meta`
(`section_id, title, institution, source_files[], scope_note, provenance_note`) and `topics[]` (23 entries) and
`quiz_questions[]` (149 entries: `definition:9, next_step:82, cause_effect:28, comparison:30`).
`meta.source_files` holds the real academic citations shown on the "ℹ️ Об источниках" screen (Шмидт/Тевс 1996 and
Покровский/Коротько 1997 — the two textbooks the working PDF files above were themselves excerpts of), not the
internal working filenames; `meta.scope_note` (chapters 1-23, no volume-3 reconstruction) documents the same
honest-incompleteness fact but isn't rendered on that screen — only `source_files` + `provenance_note` are
(`get_phys_sources_text()` in `handlers/physiology.py`).

Each topic is `{topic_id, order, title, short_title, source_file, source_pages, source_text, what_to_know[],
definitions[{term,text}], mechanisms[{name,intro,steps[]}], cause_effect[], regulation[], comparisons[{caption,
headers[],rows[{aspect,values[]}]}], remember[], confusions[], quick_review[], control_questions[],
sections[{heading,text}], deepening[{heading,text}]}`. `sections` is the one field beyond what the schema was
originally scoped to — a full-fidelity, nothing-lost expansion of the topic along its own `###` subheadings,
needed because topics 11-23 don't follow the canonical "что нужно знать/определения/механизм/..." shape at all,
they just launch into ad-hoc domain subheadings ("Оптическая система", "Сетчатка", ...); without `sections` that
content would be silently dropped. "📖 Читать конспект" always renders from `sections` (completeness guarantee);
"🧠 Учить по шагам" uses the specialized fields wherever the source actually populated them — an empty list
simply contributes no card of that kind, never a fabricated placeholder (`build_phys_learn_cards()` in
`handlers/physiology.py`).

**Quiz bank honesty**: every question is mechanically derived from an already-parsed structured field
(`definitions`/`mechanisms`' next-step pairs/`cause_effect`/`comparisons`) — never invented — and every distractor
is a real fact about a DIFFERENT term/step/topic (plausible, never fabricated). Topics `"06"`/`"07"` have zero
structured content in the source and therefore honestly have **zero** quiz questions — their only self-check is
the source's own ungraded `control_questions` list (no answer key exists for them, same reasoning as Operative
Surgery's own ungraded control-questions screens). Of the 8 question types named in the original spec, only 4
(`definition`/`next_step`/`cause_effect`/`comparison`) are auto-generated as graded questions — `find_error`/
`sequence`/`missing_step`/`free_recall` were deliberately not built, since grading them safely would either need
another model call (defeating "zero fabrication, zero runtime generation") or risk inventing a plausible-but-wrong
"correct" answer never actually stated in the source.

**Progress/mastery/SRS** (`stats["physiology_progress"][uid][topic_id]`): `opened_at, completed_cards,
total_cards, correct_answers, total_answers, mechanism_correct, mechanism_total, last_score, best_score, mastery,
last_studied_at, next_review_at, review_stage`. Mastery is `round(100 * (0.4 * completed_cards/total_cards + 0.4 *
correct_answers/total_answers + 0.2 * mechanism_correct/mechanism_total))` (`_phys_recalc_mastery()`) —
`mechanism_*` tracks only `next_step`/`cause_effect` answers specifically (the "successful mechanism reproduction"
leg of the formula), a subset of `total_answers`. A card only ever counts as studied on an explicit "Понятно ✅"
tap (`cb_phys_learn_ok`) or an answered mini-check — never merely on being opened/viewed (`cb_phys_learn` alone
never touches `completed_cards`). `phys_topic_status()` derives one of `not_started/learning/studied/needs_review/
mastered` from these counters at read time — **never stored**, so it can't drift out of sync. The SRS is a
deliberately simple, transparent, hand-tunable stage scheduler (`PHYS_SRS_STAGE_DAYS = [1, 3, 7, 14, 30]`, NOT
claimed to be an "optimal"/evidence-based spaced-repetition algorithm) — only a **fully completed** quiz session
(not aborted via "🛑 Закончить") calls `phys_record_quiz_session_complete()`, which advances one stage on a ≥60%
score or resets to stage 0 on a worse one, and sets `next_review_at = now + PHYS_SRS_STAGE_DAYS[stage] * 86400`.

**Favorites** (`stats["physiology_favorites"][uid] = {"topics": [topic_id, ...]}`) are topic-level only — a
simplification versus the originally-specified three-way split (favorite topics / saved individual cards /
missed-question review), disclosed here as a deliberate scope cut, not an oversight. Missed questions aren't
tracked as a separate bookmark list either; `get_phys_progress_text()`'s "🔁 Пора повторить" section (topics whose
`next_review_at` has passed) is the closest equivalent, driven by the SRS schedule instead of a per-question list.

Navigation: `phys:menu` → `phys:topics:{page}` (`PHYS_TOPIC_PAGE_SIZE = 8`) → `phys:topic:{id}` (topic-card hub:
intro + status + mode buttons) → `phys:learn:{id}:{idx}` (step-by-step cards, `phys:learn_ok:{id}:{idx}` marks
studied and advances) / `phys:read:{id}:{idx}` (sequential `sections[]` reading, prev/next, a defensive
>3800-char truncate-at-paragraph-boundary fallback for the rare oversized section — the dataset's real max is 889
chars, well under Telegram's cap, so this is a safety net, not a load-bearing splitter) / `phys:quick:{id}`
(condensed ~2-5-minute review: 🎯 Суть / 🔗 Главная цепочка / 📌 Обязательно назвать / ⚠️ Не перепутать / ❓
Проверь себя) / `phys:quiz_start:{id}` (graded quiz session, `PHYS_QUIZ_SESSIONS[user_id]` in-memory dict, same
shape as `ANATOMY_LATIN_SESSIONS`/`HISTOLOGY_GUESS_SESSIONS` — popped on completion/abort, `phys:quiz_stop`
reuses the same summary renderer with an `aborted` flag) / `phys:chains:{id}:{idx}` (vertical arrow-chain display
of `cause_effect`/`mechanisms` steps, only offered when a topic actually has that content) / `phys:cmp:{id}:{idx}`
(two-sided mobile comparison cards via `render_phys_comparison_body()` — shared by both the dedicated screen and
the "Учить по шагам" comparison card, NEVER rendered as a raw Markdown table). `phys:mini:{id}:{back_idx}` fires
a single random question from the topic's quiz pool (from a learn card or the quick-review screen); its answer
handler (`cb_phys_mini_answer`) re-derives the question by `question_id` looked up fresh in
`PHYSIOLOGY["quiz_questions"]` rather than trusting a pool index to stay stable across the two separate callback
round-trips — a correctness safeguard, not an optimization.

Search (`search_physiology()`, plain case-insensitive substring match across title/`what_to_know`/definitions/
`sections`headings+text — not a 4th independent copy of the tiny stemmer already duplicated in `telegram_bot.py`/
`ai/rag.py`/`ai/reference_bank.py`, a deliberate scope decision given four flat-ish text fields per topic) is
defined directly in `telegram_bot.py` as `PHYS_SEARCH_PENDING` (a plain `set[user_id]`) +
`handle_phys_search_query`, positioned BEFORE `handle_keyword_search` — same load-bearing ordering reason as
`handle_oh_search_query` (see Operative Surgery above): a handler registered via `dp.include_router()` at the end
of the file would land after the Biology keyword-search catch-all in the dispatch chain and never see a
Physiology search query at all.

`ai.rag.build_index()`/`configure()` take a `physiology: dict = None` parameter (default `None` keeps every
existing caller working unchanged) and index one entry per topic (its `sections[]` concatenated into one blob)
plus one entry per `definitions[]` term (short, precisely-quotable — useful to find independently of the
surrounding topic text). `ai/prompts.py`'s `SYSTEM_PROMPT` mentions "нормальной физиологии" alongside the other
subjects for the same reason Anatomy/Operative Surgery were added there.

### Access control (two independent gates)

1. **Referral gate** (`referral_gate_middleware`, an `@dp.update.outer_middleware()`): gates only Biology/Physics/
   Chemistry via an allowlist split per subject (`GATED_CALLBACKS_BIOLOGY`/`_PHYSICS`/`_CHEMISTRY` +
   matching `GATED_PREFIXES_*`), classified by `get_gated_subject(data) -> "biology"|"physics"|"chemistry"|None`;
   `is_gated_callback` is just `get_gated_subject(data) is not None`. Anything not listed there passes through
   ungated by default. For callback events the middleware checks `has_subject_access(user_id, subject)` — NOT the
   blanket `has_free_access()` — because the cheapest tariff (49₽, "3 дня — один предмет") only grants access to
   ONE chosen subject (`stats["subscriptions"][uid]["restricted_subject"]`); every other tier leaves
   `restricted_subject = None`, which `has_subject_access` treats as "all three". For plain message events (not
   tied to one subject) it falls back to the blanket `has_free_access()`. Free access requires
   `REFERRAL_FULL_ACCESS_THRESHOLD` (2) referrals **brought in the current calendar month** — below that,
   `REFERRAL_WARNING_THRESHOLD` (3) free attempts (one warning per `REFERRAL_WARNING_COOLDOWN_SECONDS`, 4h)
   before a hard block. **Referral-based access is recurring, not a one-time-forever unlock**: every gating
   check (`has_free_access`, `has_subject_access`, `chemistry_tickets_access_ok`, the Histology bypass below)
   compares against `get_referral_count_this_month(user_id)` (`services/access.py`), not the lifetime
   `get_referral_count(user_id)` — a user who reached the threshold in March and brings zero new referrals
   in April loses access again on April 1st; referrals don't carry over or "bank" across months.
   `get_referral_count_this_month`/`_current_referral_month_key`/`_increment_referral_month_count` follow the
   same month-key + running-total-reset-on-new-period shape as `ai_used_monthly` elsewhere in the file;
   `stats["referral_monthly"][uid] = {"month": "YYYY-MM", "count": int}` holds the running counter, incremented
   from inside `register_referral()` on every genuinely NEW referral (same anti-fraud dedup via
   `stats["referred_by"]` as before — re-registering an already-credited referred user is still a no-op for
   both the lifetime list and the monthly counter). `get_referral_count(user_id)` (the lifetime, never-reset
   total) is unchanged and still drives the referral leaderboard, the referral battle, and the "invited N
   people total" line in `register_referral()`'s instant Telegram notification and in
   `get_referral_status_text()` — those are informational, not access-gating, so they deliberately stay
   lifetime-cumulative even though the actual gate no longer is. The admin stats screen's "Меньше N
   рефералов" cohort count (`cb_admin_stats`/`get_assistant_stats_text`) is ALSO deliberately left on the
   lifetime count — a monthly version of that particular metric would read as "nearly everyone" at the start
   of every month and stop being a useful trend line, so it intentionally answers a different question
   ("how many users have historically referred fewer than N people ever") than the live access gate does.
2. **Anatomy/Histology gates** (`anatomy_access_ok` / `histology_access_ok`): separate boolean functions, not part
   of the referral allowlist — public-flag-gated (`ANATOMY_PUBLIC` / `HISTOLOGY_PUBLIC`, both currently `False`)
   until admin flips them, bypassed by admin, by `has_subscription_anatomy_access()`/`has_subscription_histology_access()`
   (per-tier `anatomy`/`histology_until_rule` flags — see Subscriptions below), or (Histology only) by reaching
   `REFERRAL_FULL_ACCESS_THRESHOLD` referrals **this month** — same monthly-recurring free-access rule as
   Biology/Physics/Chemistry (`handlers/histology.py`'s `histology_permanently_unlocked()` keeps its name from
   the old one-time-forever model — it's still accurate in the sense that it's not tied to the trial/warning
   countdown `has_histology_temp_access()` uses, just no longer "permanent" in the referral branch specifically).
   Anatomy currently has no referral bypass, only admin/a subscription tier with `anatomy: True`, or a manual
   per-user demo grant (`stats["manual_anatomy_demo_granted"]`, a plain list of IDs mirroring
   `manual_access_granted`'s shape but scoped to Anatomy only — granted/revoked from the admin panel by username/ID,
   same `ADMIN_PENDING` prompt pattern as the blanket grant/revoke, actions `grant_anatomy_demo`/`revoke_anatomy_demo`).

   **Anatomy is additionally split section-by-section into a free half and a paid half** (a growth-funnel design —
   free sections hook new users, the paid sections upsell engaged ones). `ANATOMY_FREE_SECTIONS` lists which of the
   10 Kafarov module keys (`module1_osteology` … `module10_clinical`) are free to everyone regardless of
   `anatomy_access_ok()`; the other modules still require it. `anatomy_section_access_ok(user_id, section_key)` is
   the per-section predicate — `True` immediately if `section_key in ANATOMY_FREE_SECTIONS`, else falls back to
   `anatomy_access_ok(user_id)` — and every anatomy handler that used to gate on the blanket `anatomy_access_ok()`
   now resolves the relevant section first (directly for section-level handlers, via `get_topic_section_key(topic_key)`
   for topic/bone-level ones) and checks this instead. Per the "hide vs. relabel" pitfall below, `anatomy_menu`
   itself is never gated — it always renders all 10 sections, prefixing paid ones the user can't access yet with
   `🔒` rather than hiding them or blocking the whole menu. The global Latin-terminology quiz
   (`anatomy_latin_all_start`/`anatomy_latin_leaderboard`) is left ungated on purpose: today its only data source is
   `module1_osteology`'s `latin_terms`, which is itself a free section — if a future paid module ever gets
   `latin_terms`, this trainer needs to move onto `anatomy_section_access_ok` too, since it currently pools every
   section's terms indiscriminately.

   **Anatomy has a top-level split independent of the free/paid module split above**: `anatomy_root` (bound to the
   "🦴 Анатомия" button in the main menu and in the admin Anatomy-announcement broadcast — `anatomy_menu` itself is
   no longer a direct entry point) shows two options — "📚 Весь курс анатомии" (`anatomy_menu`, unchanged: the
   10-section module list described above) and "🎓 Экзамен" (`anatomy_exam_menu`, three entries: "🖐 Вопросы
   практики"/"📖 Вопросы теории" are stubs pending content, "✅ ТЕСТ" is live). ТЕСТ is the official 1040-question
   test bank of the ВМедА normal-anatomy department (Гайворонский и др., 2021, `anatomy_exam_test.json`,
   `ANATOMY_EXAM_TEST_PARTS`), split into 10 fixed parts of ~102-106 questions each (5 parts "Базовая часть", 5
   "Лечебное дело" — mirrors the two answer-key sections of the source document) — **always free for everyone**,
   with no gate check at all, independent of `ANATOMY_FREE_SECTIONS`/subscriptions, same reasoning as the global
   Latin quiz. A part is answered as one full sequential pass in source order (`ANATOMY_EXAM_TEST_SESSIONS`, not a
   random sample like `ANATOMY_LATIN_SESSIONS`), with an early-stop button and, after finishing (or stopping
   early), a "❌ Разбор ошибок" review screen (`ANATOMY_EXAM_TEST_MISTAKES`, paginated one mistake at a time,
   marking both the correct option and — if different — the one the user picked) for every question answered
   wrong. `anatomy.json`'s bone/topic gate machinery (`anatomy_section_access_ok`, `get_topic_section_key`, etc.)
   is untouched by any of this — ТЕСТ questions aren't tied to `ANATOMY` topics/sections at all, just to their own
   flat `anatomy_exam_test.json` part list.

   **ТЕСТ has a per-user normal/rating mode toggle** (`get_anatomy_exam_test_mode`/`set_anatomy_exam_test_mode`,
   `stats["anatomy_exam_test_mode"][uid]`, default `"normal"`) — a button on the part-list menu flips it
   (`anatomy_exam_test_mode_toggle`) and immediately re-renders that same menu via the shared
   `render_anatomy_exam_test_menu()` helper (both the `anatomy_exam_test_menu` handler and the toggle handler call
   it, so the menu text/keyboard is never duplicated). `start_anatomy_exam_test_session()` snapshots the mode into
   the session as `is_rating` at start time — switching the mode preference mid-run does not retroactively affect
   a session already in progress, and the question screen shows a 🏆/🎯 icon reflecting which mode that particular
   session is running in. Only a **fully completed** rating-mode part (not aborted via "🛑 Закончить") calls
   `record_anatomy_exam_test_score()`, which accumulates (not "best of") into `stats["anatomy_exam_test_scores"][uid]
   = {correct, total, attempts}` — every scored part adds its correct/total on top of the running total, unlike
   `anatomy_latin_scores`' personal-best-per-attempt model, since parts vary in size (102 vs 106) and a cumulative
   total rewards both accuracy and volume across the 10-part bank. `get_anatomy_exam_test_leaderboard_text()`
   ranks by raw `correct` count (ties broken by percent) and reuses `donor_display_name()`/
   `ANATOMY_LATIN_LEADERBOARD_MSG_LIMIT` for name display and the same length-safe truncation as the Latin
   leaderboard.

   **Histology also has its own trial+warning gate** (`histology_gate_ok`, called explicitly at the top of each
   histology handler — `histology_menu`/`_topic`/`_specimen`/`_img`/`_guess_start` — not a middleware, since the
   referral gate's `has_free_access()` can't be reused here without breaking the subscription-scope distinction
   between "gated" and "all"/early-histology tiers). First-ever visit silently grants a `TEMP_ACCESS_GRANT_SECONDS`
   (7-day) trial in `stats["histology_temp_access"][uid]`; subsequent visits during the trial fire up to
   `HISTOLOGY_WARNING_THRESHOLD` (3) non-blocking nudge warnings (`stats["histology_warnings"]`, same
   count+cooldown shape as `referral_warnings`) before falling back to the locked screen — whichever happens
   first, the trial expiring or the 3 warnings being exhausted. `histology_access_ok(user_id)` is the pure
   predicate (safe to call from menu labels/tests, no side effects); `histology_gate_ok(callback)` is the
   stateful version used inside handlers (grants the trial, increments warnings, renders the block/warning
   screens) — don't call the async gate version where you just need a boolean check.

`has_free_access(user_id)` is the umbrella predicate composing: admin, referral threshold, manual grant
(`stats["manual_access_granted"]`), temp access (`stats["temporary_access"]`), active subscription. It does not
cover Anatomy/Histology — those check `anatomy_access_ok`/`histology_access_ok`/`histology_gate_ok` directly, and
Histology's own trial uses a separate `stats["histology_temp_access"]` dict so it never interacts with the
general recovery-grant `stats["temporary_access"]` used for Biology/Physics/Chemistry.

**Section promos** (`start_section_promo(section, duration_seconds)` / `is_section_promo_active(section)`,
stored in `stats["section_promos"][section] = until_ts`): a time-boxed global override that makes one section free
for everyone regardless of referrals/subscription, e.g. "open Histology to all for 24h" via the admin panel
(`admin_histology_promo_confirm` → `admin_histology_promo_go`, mirrors the referral-battle start pattern and
broadcasts an announcement). Self-expires — no timer task needed, the access check just compares against
`time.time()`. The section key `"global"` is special-cased: it's checked (in addition to each subject's own
promo key) inside `has_free_access()`, `has_subject_access()`, and `histology_permanently_unlocked()` — so
activating it (admin panel → "🎉 Снять все ограничения всем на 24ч", `admin_global_promo_confirm` →
`admin_global_promo_go`, `GLOBAL_PROMO_SECONDS`) opens Biology/Physics/Chemistry/Histology simultaneously with
one broadcast (`announce_global_promo_start()`), unlike the single-section Histology promo above.
**Deliberately excluded**: `anatomy_access_ok()` does NOT check `"global"` — Anatomy stays admin/subscription-only
even during a global promo, since the section is still `ANATOMY_PUBLIC = False` ("in development"), not merely
gated like the other subjects. Likewise `biology_tickets_download_ok()` never checks any promo/referral state at
all (subscription or admin only) — biology ticket *downloads* are always paid, independent of any promo.

### Subscriptions (`SUBSCRIPTION_TIERS`)

Twenty dict entries. **Tiers 1-11 are the old lineup, ALL retired** (`"retired": True`) — kept in the dict
forever, unchanged, so historical buyers' grants (and any admin/gift subscriptions already recorded in
`stats["subscriptions"]`) keep resolving to the exact title/price/expiry/entitlements they were sold, but
excluded from every purchase-facing surface (`ACTIVE_SUBSCRIPTION_TIERS = {t: cfg for t, cfg in
SUBSCRIPTION_TIERS.items() if not cfg.get("retired")}`, iterated by all menus/keyboards/announcements instead of
the raw dict). **Tiers 20-29 are the current lineup** (2026/27 academic year — a "pick your course" set,
see below). **Never repurpose a retired (or any existing) tier's numeric key for a different product** —
`stats["subscriptions"]` only stores the tier id, and some display paths re-derive text by looking the id back up
in `SUBSCRIPTION_TIERS` live, so reusing an id would silently reinterpret what an existing payer already bought.
IDs 12-19 are deliberately skipped (reserved/unused) between the two lineups. Active tiers today: 20 (99₽, 7-day
one-subject "Пересдача"), 21 (129₽, 30-day B+P+C), 22 (249₽, "Все пересдачи" until `NOV_1_2026_CUTOFF`), 23 (299₽,
until `JAN_1_2027_CUTOFF`), 24 (599₽, "Зимняя сессия", adds Anatomy+Histology, until `MAR_1_2027_CUTOFF`), 25
(849₽, "Весь первый курс", until `FIRST_YEAR_END_2027`), 26 (1290₽, "До конца второго курса", full scope +
downloads + cheat_sheets, until `SECOND_YEAR_END_2027` — **the same cutoff constant retired tier 9 uses**, since
both promise "through the end of 2nd year"; do not change it without checking tier-9 holders too), 27 (1690₽,
"VMedA MAX", `2*365` days, full scope), 29 (3299₽, "5 лет", `5*365` days, full scope), 28 (3899₽, "Вся академия",
`6*365` days, full scope). 28 and 29 are deliberately **not** shown in the curated per-course screens or badged
"HOT" — positioned as premium/long-horizon upsells, only reachable via "📦 Все тарифы" (see the shop UI note
below); their `menu_number` (10 and 9 respectively) keeps 29 listed just ahead of the pricier 28 on that flat
screen even though 29 was added to the dict after 28. Add a new tier with a fresh unused key above 29, never
reuse 1-11 or a retired id.

**Migrating pricing/lineups**: when retiring a whole generation of tiers in favor of a new one (as happened going
from 1-11 to 20-28), never rewrite existing `stats["subscriptions"]` records to point at new tier ids, and never
touch a retired tier's stored fields — the whole point of the retire-and-add-new pattern is that old grants keep
resolving via their own frozen `SUBSCRIPTION_TIERS[old_id]` entry, forever, with zero migration step.

Each tier is a dict of `title/short/price_rub/price_stars/emoji/benefits/...` plus:
- **Expiry** — `duration_days` (relative, from purchase) XOR `expires_at` (a fixed absolute timestamp constant —
  `OCT_2026_CUTOFF`, `NOV_END_2026_CUTOFF`, `FEB_2027_CUTOFF`, `SECOND_YEAR_END_2027` for the retired 1-11 lineup;
  `NOV_1_2026_CUTOFF`, `JAN_1_2027_CUTOFF`, `MAR_1_2027_CUTOFF`, `FIRST_YEAR_END_2027` for the current 20-28
  lineup — all defined in `services/access.py`). `grant_subscription()` resolves whichever is set into the stored
  `sub["expires"]`; `format_subscription_expiry()` doesn't care which path produced it.
- **`subject_choice_required`** — currently only tier 20 (99₽, 7 days; tier 5, 49₽/3 days, played this role in the
  retired lineup). The buyer picks exactly one of biology/physics/chemistry before paying
  (`sub_subject:{tier}:{subject}` → `buy_sub_stars_subj:`/`buy_sub_rubles_subj:`, the Stars invoice payload
  becomes `sub_stars_{tier}_{subject|-}_{chat_id}_{ts}`); the choice is stored as `sub["restricted_subject"]`.
  This is why the referral gate had to become subject-aware (see above) — it's the only kind of tier that doesn't
  unlock all three gated subjects at once.
- **`histology_until_rule`** — `None` (no Histology), `"expiry"` (Histology lasts exactly as long as the
  subscription itself), or a literal timestamp (an independent, possibly-earlier cutoff — retired tier 1 uses
  `JULY_END_2026`). `grant_subscription()` snapshots this into `sub["histology_access"]` (bool) +
  `sub["histology_until"]` (timestamp or `None` = "tied to the subscription's own `expires`") **at grant time**
  — never re-derive it from a live global constant, or changing that constant later would retroactively shrink a
  promise already sold to existing payers. (`TIER1_HISTOLOGY_DEADLINE`, end of 2026, is kept only as a read-only
  fallback for tier-1 grants made *before* this snapshot field existed — `_sub_has_histology()` checks
  `"histology_access" in sub` first and only falls back to the legacy `scope`/`early_histology`/`tier==1` fields
  when it's missing.)
- **`anatomy`** / **`biology_download`** / **`cheat_sheets`** — plain bools, also snapshotted onto the sub record
  at grant time (`_sub_has_anatomy()`/`_sub_has_biology_download()` fall back to legacy `scope == "all"` for
  pre-migration grants, same reasoning as Histology above). `cheat_sheets` only gates a menu entry/flag so far —
  the actual printable-cheat-sheet *content* doesn't exist yet, that's a separate content-authoring task.
- **`subscription_version`** — `2` on every tier in the current (20-28) lineup; absent on every retired (1-11)
  tier. `grant_subscription()` snapshots `cfg.get("subscription_version", 1)` onto the sub record at grant time —
  so a *fresh* grant of an old tier id (e.g. an admin comping a legacy tier by hand) still ends up correctly
  tagged version 1, matching a pre-existing record that never had the field at all. Nothing reads this field to
  gate content access — it exists purely to select which VMedA AI quota plan applies (see below); never let it
  leak into content-access predicates.
- **`ai_limit_type`** (`"period"` — a fixed pool for the whole subscription lifetime, no reset; or `"monthly"` —
  resets every calendar month) **+ `ai_limit`** (int) — present on every tier in the 20-28 lineup, absent from
  1-11. This is a completely separate quota system from the AI section's ordinary free daily limit
  (`AI_FREE_DAILY_LIMIT`, `get_ai_usage_today`/`increment_ai_usage`/`stats["ai_usage"]`) — see
  `_sub_ai_plan()`/`sub_ai_requests_left()`/`_increment_sub_ai_usage()` in the "VMedA AI" section of
  `telegram_bot.py`. `_sub_ai_plan(user_id)` returns `(None, None)` for anyone without an active
  `subscription_version >= 2` subscription, in which case `ai_requests_left()` transparently falls back to the
  ordinary free daily limit — content-access rights and AI-request rights are deliberately independent axes.
  Usage counters (`ai_used_period` int, or `ai_used_monthly: {"month": "YYYY-MM", "count": int}`) live *inside*
  the subscription record itself, so they reset automatically whenever the user buys a new subscription (a fresh
  `grant_subscription()` call overwrites the whole record). **Legacy paid subscriptions** (`subscription_version`
  absent, i.e. reads as `1`) get a flat `LEGACY_PAID_AI_MONTHLY_BONUS` (currently 60/month) on top of their
  frozen content rights — this bonus is computed at read time, never written into the old record, so it can't
  violate the "never touch an existing sub record" rule.

### Subscription shop UI — course picker (2026/27 lineup)

The "💎 Подписка" entry point (`subscription_menu` callback, `cb_subscription_menu`) opens a **course picker**
first (`get_subscription_course_picker_text/_keyboard` — "1️⃣ Первый курс" / "2️⃣ Второй курс" / "📦 Все тарифы"),
not a flat tier list directly — with 10 active tiers a single undifferentiated screen was both unreadable and not
targeted at what a given student actually needs. Nothing about the choice is persisted; it lives entirely in
callback_data for that one screen transition. `subscription_course:{year1|year2}` renders a curated ≤4-tier list
per `FIRST_YEAR_TIER_IDS`/`SECOND_YEAR_AUTUMN_TIER_IDS`/`SECOND_YEAR_WINTER_TIER_IDS` (`_course_tier_ids()`); the
2nd-course list itself flips from the autumn/resit set to the winter set at `NOV_1_2026_CUTOFF` (`_second_year_tier_ids()`)
— the same instant tier 22 "Все пересдачи" itself expires, so the shop stops recommending a resit-season tier the
moment resit season is over. `subscription_all_tiers` (`cb_subscription_all_tiers`) is the *original* flat-list
screen — `get_subscription_menu_text`/`_keyboard` themselves are unchanged in behavior, just no longer the direct
target of the main entry point; every course screen and the picker itself link to it as a "not what I wanted"
escape hatch. Tiers 28 ("Вся академия") and 29 ("5 лет") are deliberately **absent** from every curated course
screen (only reachable via "📦 Все тарифы") and carry no badge — positioned as upsell/premium options, not a
default recommendation. Because 10 tiers' full benefit lists no longer fit Telegram's 4096-char cap on one screen, the flat "все тарифы"
view shows only each tier's *first* benefit line + price; the full list is one tap away on the tier's own detail
screen (`get_sub_tier_text`, unchanged, still shows every benefit).

Never hardcode a price/tier list in marketing copy — use `cheapest_active_tier(predicate)` (and its shortcuts
`cheapest_gated3_tier()`/`cheapest_histology_tier()`/`cheapest_anatomy_tier()`/`cheapest_biology_download_tier()`)
or iterate `ACTIVE_SUBSCRIPTION_TIERS` directly, same reasoning as the "values duplicated out of
SUBSCRIPTION_TIERS" pitfall below. `get_tier_upsell_text(tier_id)`/`get_tier_upsell_keyboard(tier_id)` show
whichever active tier is next-cheapest-above the given one (empty string / `None` if `tier_id` is already the
most expensive) — shown both on the pre-payment tier detail screen and on the post-purchase confirmation
(Stars and admin-rubles paths). Telegram caps `callback.answer(..., show_alert=True)` text at ~200 characters —
`get_anatomy_dev_alert_text()` (used by the 15 in-handler "Anatomy still locked" alerts) mentions only the single
cheapest anatomy-granting tier for this reason, unlike the full locked-screen text which lists all of them.

Stars payments go through the real Telegram Bot API invoice flow (`send_invoice` → `pre_checkout_query` →
`successful_payment`, `currency="XTR"`); rubles payments have no real gateway — the buyer is deep-linked to
`@vmeda_helper` to pay manually. `handle_pre_checkout` validates `sub_stars_*` payloads before answering — parses
the tier id out of the payload, rejects (`ok=False, error_message=...`) if the tier doesn't exist or is retired, and
rejects if `total_amount` doesn't match the tier's `price_stars` (or its 10%-discount variant) — so a stale/tampered
invoice payload can't sneak through pre-checkout. `handle_successful_payment` is idempotent against Telegram
redelivering the same `successful_payment` event twice: it keys `payment.telegram_payment_charge_id` into
`stats["processed_payment_charge_ids"]` and checks it BEFORE granting anything — a charge id already seen there
short-circuits to a no-op (logged, nothing re-granted, no duplicate spend/donation) instead of re-running the
subscription-grant/donation branches a second time.

Two independent paths grant a rubles subscription, and both must keep working:
1. **One-tap confirm** (fast path) — the moment the buyer taps "💵 Оплатить X₽" (`cb_buy_sub_rubles`/`_subj`),
   every `ADMIN_IDS` entry immediately gets a `admin_confirm_sub:{tier}:{user_id}:{subject|-}` inline button via
   `notify_admins_of_payment_request()` — the admin just taps it once they see the transfer land, no typing.
   `cb_admin_confirm_sub` guards against two admins racing each other on the same request (checks whether
   `stats["subscriptions"][uid]` already has this exact tier granted via `"rubles"` in the last 10 minutes before
   granting again — the second tap edits its own message to "already confirmed" instead of double-granting/
   double-notifying the buyer). The same message also carries a `❌ Отклонить` button
   (`admin_reject_sub:{tier}:{user_id}:{subject|-}`, `cb_admin_reject_sub`) for when the buyer never actually
   transfers the money — it just edits the admin's own copy of the request to a closed state, grants nothing, and
   doesn't block a real confirm later (rejecting is purely about clearing the admin's own notification, not a
   durable "declined" flag on the request).
2. **Manual flow** (unchanged, kept as a fallback) — `ADMIN_PENDING` (`record_subscription_username` →
   `record_subscription_tier` → `record_subscription_subject` if the chosen tier requires one), for cases where
   the admin wants to grant a subscription without the buyer having gone through the purchase flow at all — in
   practice this has become the "comp a subscription to a friend for free" path, not a paid one.

Both paths funnel into the same `grant_subscription_and_notify_buyer()` — the single place that calls
`grant_subscription()` and sends the buyer their "🎉 активирована" message + tier upsell, so the confirmation
text/upsell logic never has to be kept in sync across three call sites by hand. Its `method` argument doubles as
the payment-revenue signal in `cb_admin_stats`: the one-tap path passes `"rubles"` (a real transfer the admin
just confirmed) and Stars passes `"stars"`, both counted in "💰 Платежи"; the manual flow passes `"rubles_manual"`
instead, which is deliberately excluded from `sub_revenue_rubles` — manually-granted subscriptions still count
toward "Всего куплено" / per-tier active totals (they're real active subscriptions), just not toward revenue.
This distinction only applies going forward — historical `"rubles"`-tagged subscriptions granted through the
manual flow before this split existed aren't retroactively reclassified, since nothing in the stored data
distinguishes which of them were actually paid off-platform vs. free comps.

The tier-selection step of the manual flow sends a `ReplyKeyboardMarkup` (`get_admin_tier_reply_keyboard()`, one
button per active tier, digit-prefixed so the parser can `re.match(r"\d+", raw)` out of either a tapped button or
hand-typed text) instead of making the admin memorize/type a bare number — remember `ReplyKeyboardMarkup` can
only be sent via `message.answer(...)` (a new message), never attached to `safe_edit_text`/`edit_text`, unlike
the `InlineKeyboardBuilder` markup used everywhere else in the file.

### Three admin roles

`is_admin(user_id)` (`user_id in ADMIN_IDS`, a hardcoded set) is the only role with unrestricted access to the
full `get_admin_menu()` tree. Two separate, narrower roles exist alongside it, each its own flat list in `stats`,
each granted/revoked from the main admin panel via the standard `ADMIN_PENDING` username/ID flow (see below) —
**deliberately not merged into one "elevated" role**, since they grant non-overlapping capabilities and merging
them would silently over-grant whichever capability came second:

- **Assistant admin** (`is_assistant_admin`/`stats["assistant_admins"]`) — full content access to every gated
  section via `is_admin_or_assistant()` (used ONLY in content gates: `has_subject_access`, `has_free_access`,
  `biology_tickets_download_ok`, `chemistry_tickets_access_ok`, anatomy maintenance-mode bypass, etc.), plus a
  tiny separate panel (`get_assistant_admin_menu_keyboard()`, reached via `/admin` — assistants never see or reach
  `admin_panel`/`get_admin_menu()`) offering only a reduced stats view (`get_assistant_stats_text()`, no
  subscriptions/payments) and a moderated DM (`assistant_dm_prompt` → queued in `ASSISTANT_DM_REQUESTS` → a real
  admin must `assistant_dm_approve`/`_reject` before it actually sends). Zero admin-panel rights (grant/revoke
  access, subscriptions, broadcasts) by design.
- **Payment admin** (`is_payment_admin`/`stats["payment_admins"]`) — the inverse scope: zero content-access
  bypass, but (1) receives the same one-tap RUB payment-confirm push notification real admins get
  (`notify_admins_of_payment_request()` iterates `ADMIN_IDS | set(stats["payment_admins"])`) and can tap
  `cb_admin_confirm_sub`/`cb_admin_reject_sub` exactly like a real admin, and (2) can reach the "📣 Анонсы"
  submenu (see Broadcasts below) via its own tiny panel (`get_payment_admin_menu_keyboard()`, one button, reached
  via `/admin` → `payment_admin_panel`). `get_admin_announcements_keyboard(back_callback)` and every
  `cb_admin_announce_*_confirm`/`_go` handler are gated `is_admin(...) or is_payment_admin(...)` and take a
  `back_callback` parameter precisely so a payment admin's "🔙 Назад" (both mid-flow and on the post-broadcast
  success screen) returns to `payment_admin_panel` instead of the `admin_panel` it can't reach — never hardcode
  `admin_panel` as the back target on a screen reachable by this role.

Neither narrower role should ever be extended to cover the other's territory (e.g. don't add payment-confirm
rights to `is_assistant_admin`, or content access to `is_payment_admin`) — if a future role needs both, add a
fourth flat list rather than widening one of these two past its documented contract.

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

### App timezone

`APP_TIMEZONE` (`telegram_bot.py`, a fixed `timezone(timedelta(hours=3))`, i.e. MSK) plus `local_now()`/
`local_today()` are the single source of truth for every recurring daily/monthly period boundary — the free AI
daily limit (`get_ai_usage_today`/`increment_ai_usage`), the paid-tier monthly AI quota
(`_current_ai_month_key`), the referral monthly gate (`services/access.py`'s `_current_referral_month_key`), the
cost-circuit-breaker hour/day windows (`_current_hour_key`/`_current_day_key`), and the once-a-day helperchat
promo. Before this they all called `date.today()`/`datetime.now()` directly, i.e. the CONTAINER's local time
(UTC on Railway) — "a new day"/"a new month" flipped up to 3 hours later than it actually did in Moscow, where
every student and admin actually is. A fixed offset (not `zoneinfo("Europe/Moscow")`) is deliberate: Russia has
had no DST transitions since 2014, so MSK is UTC+3 year-round, and a fixed offset can't fail at runtime on a
minimal Docker image that happens to be missing system tzdata the way `zoneinfo` could.

`services/access.py`'s subscription-tier cutoff constants (`OCT_2026_CUTOFF` and friends) are built the same way,
via `_msk_deadline(year, month, day)` (MSK midnight of that calendar date, as a timestamp) instead of
`time.mktime(date(...).timetuple())` (container-local midnight). This only changes the instant a cutoff constant
evaluates to for **future** `grant_subscription()` calls — it does NOT retroactively touch any `sub["expires"]`
value already stored on an existing subscription record, since those are plain floats snapshotted once at grant
time and never recomputed. `format_subscription_expiry()` was fixed for the same reason in the other direction:
it used to format an expiry timestamp via the container's local timezone, which could show the wrong calendar
DAY for a timestamp close to a UTC/MSK day boundary (e.g. 23:30 UTC is already 02:30 MSK the next day) — it now
formats via `APP_TIMEZONE` explicitly instead of relying on system local time.

### Broadcasts

Admin-triggered mass messages follow one recurring shape: a `_confirm` handler computes the target cohort and
shows a preview + confirm button, a `_go` handler re-validates the cohort (it may have changed) and calls
`_broadcast()` (all users) or `_broadcast_to(cohort, text, keyboard=None)` (a filtered list), then increments
`stats["broadcast_count"]`. Reuse this shape for new admin broadcasts rather than inventing a new one.

The `admin_announce_*_confirm` "send this to everyone" broadcasts specifically (subscription, support, Anatomy,
Anatomy-exam, Latin-quiz, VMedA AI, rollcall — one-shot feature-announcement blasts, as opposed to targeted
reminders like the referral/discount ones) live in their own submenu off the main admin panel
(`get_admin_announcements_keyboard()` / `cb_admin_announcements_menu`, `callback_data="admin_announcements_menu"`)
instead of each getting its own top-level button — same "submenu off the main panel" shape as
`admin_battle_menu`/`get_admin_battle_keyboard()`. Each announcement's own `_confirm`/`_go` pair and its
"❌ Отмена" button are unchanged except the cancel button now returns to the Анонсы submenu
(`admin_announcements_menu`) instead of jumping all the way back to `admin_panel` — mirrors how the battle
submenu's own cancel buttons return to `admin_battle_menu`. A new announcement broadcast should add its
`_confirm`/`_go` handlers the same way as before, then add ONE button inside `get_admin_announcements_keyboard()`
— never a new top-level button in `get_admin_menu()` — to avoid re-flattening the panel back out. This submenu is
also reachable by the payment-admin role, not just full admins — see "Three admin roles" above for why its
`back_callback` parameter exists.

### Group roll-call (перекличка)

Recruits one point-of-contact per group. `ROLLCALL_GROUP_COUNT` (45) generates group names on the fly via
`rollcall_group_name(n) -> "25-ЛД/СТ-{n}"` — group names are never stored, only `stats["rollcall_confirmed"][group]
= {"user_id", "confirmed_at"}` once an admin has confirmed one. Tapping an unclaimed group does **not** lock it —
multiple people can tap the same group and get the `@vmeda_helper` deep-link screen; the group only locks (button
becomes `"✅ {group}"` / `callback_data="rollcall_taken"`) once an admin taps confirm, mirroring the one-tap
payment-confirm pattern (`notify_admins_of_rollcall_request()` pings every `ADMIN_IDS` entry the moment someone
taps a group, `cb_rollcall_confirm` grants and guards against two admins racing the same group the same way
`cb_admin_confirm_sub` does for payments). The reward is a flat `TEMP_ACCESS_GRANT_SECONDS` (7-day) blanket grant
via `stats["temporary_access"]` — the same mechanism the referral-exhausted recovery broadcast uses — not a real
`SUBSCRIPTION_TIERS` entry, since it's promotional and unlocks only Biology/Physics/Chemistry (not
Histology/Anatomy, which check their own subscription-specific flags, not `has_temp_access()`).

### VMedA AI (AI-помощник) — pipeline architecture

The `ai/` package is a self-contained pipeline that never imports `telegram_bot` (to avoid a
circular import) — content/config is handed in once via `ai_rag.configure()` (called right after
the JSON banks load, near the top of `telegram_bot.py`) and `ai_rag.build_embeddings()` (fired as a
background `asyncio.create_task()` from `main()`, keyed to a `STATS_DIR`-based cache file so it
doesn't block bot startup/polling). Everything that needs `stats`/`save_stats()` (quota, cost
tracking, the answer cache) stays in `telegram_bot.py`; the `ai/` modules themselves are pure
functions/classes over their inputs.

`telegram_bot.ai_provider_available()` — `bool(OPENAI_API_KEY) or bool(ai_gemini.GEMINI_API_KEY)` — is the single
predicate the AI section's UI gates on (`get_ai_menu_text()`'s "🔧 Идут финальные настройки" line,
`cb_ai_solve_start()`'s block), replacing an old hard `if not OPENAI_API_KEY` check. It reflects that the
pipeline already has a real fallback to Gemini alone: `ai.vision_parser.parse_task()` tries OpenAI then Gemini for
photo parsing, and `ai.router.build_attempts("openai")` appends `"gemini"` as a fallback whenever
`GEMINI_API_KEY` is set — even on the `quick=True` path, whose *primary* provider is always OpenAI. So a
deployment with only `GEMINI_API_KEY` configured (no `OPENAI_API_KEY` at all) can genuinely serve AI requests end
to end and must not be told the section is unavailable. `XAI_API_KEY`/Grok is deliberately excluded from this
predicate — it's never used for vision parsing and never a fallback for the quick-answer step, only an optional
detailed-answer provider for `bucket=="theory_complex"`.

Pipeline, in call order, for the **first** message of a session (photo or text):
1. **`ai/vision_parser.py`** (`parse_task(*, image_bytes=None, text=None)`) — the ONLY place a
   photo is ever sent to a model, exactly once. Tries OpenAI first, then Gemini if configured
   (`_PARSE_ATTEMPTS` — same fallback shape as `ai.router.try_providers`, since Gemini's `call()`
   already accepts the same OpenAI-style `messages` and converts `image_url` blocks to `inline_data`
   itself); Gemini has no `response_format=json_object` guarantee (raw HTTP call, not the OpenAI SDK),
   so its response is stripped of a possible ```` ```json ```` fence before parsing. Returns a
   `TaskRepresentation` (see `ai/task.py`: `subject/type/complexity/question/options/values/units/
   subquestions/confidence/raw_text`) plus usage for cost tracking. Only if BOTH providers fail (no
   keys, network error, non-JSON response from both) does it degrade to a raw-text task with
   `confidence=0.0` instead of raising — the rest of the pipeline always has *something* to work
   with, never a hard failure at this step. `type`/`complexity` are classified from the QUESTION
   itself, not from a later answer — this is what lets `ai.router.route_bucket(task)` pick a
   provider before any answer exists (replaced the old `classify_quick_answer()`, which inferred
   provider from the shape of an already-generated reply).
2. **Exact-match answer cache** (`telegram_bot.get_cached_ai_answer`, called from inside
   `get_first_message_ai_answer` BEFORE anything else — including RAG, see next item) — keyed by
   `TaskRepresentation.fingerprint()` — normalizes word order and folds in `values` so two different
   phrasings of the same question with the same numbers collide, but two different numbers never do.
   A hit here is free of RAG/embedding/solver cost — this ordering (cache check strictly before RAG)
   is deliberate: RAG used to run for every first message regardless, so even a cache HIT was paying
   for an embedding call before the cache was ever consulted. **This cache is still keyed by the
   PARSED task, though** — reaching it at all requires `ai_vision_parser.parse_task()` to have
   already run (to get a `TaskRepresentation` to fingerprint), so a hit here is free of RAG/solver
   cost but NOT free of the parser call itself. For photos this is unavoidable (there is no
   fingerprint without recognizing the image first); for TEXT questions, `handle_ai_text_input`
   additionally checks `get_raw_text_precache_answer()` *before* calling `parse_task()` at all — see
   the raw-text pre-cache below, which is what actually makes a repeat TEXT question free end to
   end. **A freshly generated answer is never auto-trusted into the cache** —
   `submit_ai_answer_for_moderation()` queues it as `"pending"` in `stats["ai_answer_cache"]`; only an
   admin approving it via the moderation queue (admin panel → "🤖 Модерация AI-кэша",
   `handlers/admin.py`: `cb_admin_ai_cache_queue`/`_approve`/`_reject`) makes it servable to other
   users. Rejecting doesn't block the question forever — the next occurrence generates (and re-queues)
   a fresh candidate. `submit_ai_answer_for_moderation()` never overwrites an already-`"approved"`
   entry with a new candidate; only `moderate_ai_cache_entry()` can change an approved entry's fate.

   **Raw-text pre-cache** (`get_raw_text_precache_answer()`/`record_raw_text_alias()`,
   `stats["ai_raw_text_aliases"]: {raw_fingerprint -> parsed_fingerprint}`) — text-only (photos have
   no text to fingerprint before parsing). `handle_ai_text_input` calls
   `get_raw_text_precache_answer(message.text)` before `ai_vision_parser.parse_task()` on the first
   message of a session: it fingerprints the RAW text the same way `TaskRepresentation.fingerprint()`
   would (via `TaskRepresentation(raw_text=text).fingerprint()` — `question` empty means
   `question_text()` falls back to `raw_text`, so this is genuinely the same normalization, not a
   second implementation to keep in sync by hand), looks up whether that exact raw text has been seen
   before, and if so, whether its PARSED fingerprint is now `get_cached_ai_answer`-approved — a hit
   skips the vision-parser call, RAG, and the solver entirely, so a literal repeat of the same raw
   text is truly free end to end. `record_raw_text_alias()` is called unconditionally after every
   first-message parse (hit or fresh generation alike) so the alias is ready the moment that
   candidate later gets approved — it does NOT attempt to catch different phrasings of the same
   question (the parser may reword text and extract `values`/`units` that raw text alone doesn't
   have, so a paraphrase gets a different parsed fingerprint and this pre-cache simply misses,
   falling through to the normal parse path) — only literal repeats of one exact raw text, which is
   exactly what happens when many students paste the same question from a shared ticket/test bank.
   Deliberately does not attempt to be more clever than that: a false pre-cache HIT would serve a
   possibly-wrong cached answer without the parser or verifiers ever getting a chance to catch it.
3. **`ai/rag.py`** (`search_for_task(task, limit=TOP_K) -> (snippets, usage)`) — runs on a cache
   MISS, before BOTH the quick and the detailed answer (not just the detailed one, unlike the
   original MVP). Hybrid: a keyword/IDF layer (`_score_entries`, zero tokens, always available) plus
   an optional OpenAI-embeddings semantic layer (`text-embedding-3-small`, cosine similarity,
   `MIN_COSINE`/`SEMANTIC_SCORE_SCALE`) that only engages when `OPENAI_API_KEY` is set —
   `_embed_query`/`_embed_queries`/`build_embeddings` degrade to `None`/no-op otherwise, so the
   feature is fully functional (keyword-only) with no key at all. Embeddings are cached to disk keyed
   by `_entry_key()` (a content hash, not a list index), so re-running `build_embeddings()` on every
   bot restart only pays for genuinely new/changed content. `build_embeddings(cache_path, max_items)`
   caps how many missing entries get embedded in ONE call — `max_items` defaults to
   `MAX_EMBEDDING_BUILD_ITEMS_PER_START` (500) unless the caller overrides it; `telegram_bot.main()`
   passes `AI_MAX_EMBEDDING_BUILD_ITEMS_PER_START` (env-overridable) and gates the whole call behind
   `AI_BUILD_EMBEDDINGS_ON_START` (env `AI_BUILD_EMBEDDINGS_ON_START=0` skips it entirely) — without
   this, a lost/corrupted/non-persistent cache file (or a bot stuck crash-looping) would re-pay to
   embed the WHOLE content base on every single restart; with the cap, a full rebuild instead spreads
   across several restarts, each picking up more of the still-missing entries (the incremental
   per-batch disk save inside `build_embeddings` already makes this safe — nothing already embedded
   is ever re-paid for). Returns the count actually embedded this call, so the caller/logs can see
   rebuild progress. `task.type == "list"` with
   `task.subquestions` filled queries each subquestion separately and unions the results (a single
   blob query over a 13-item list was observed to match nothing, even when half the items
   individually ground fine) — the old `search_snippets_multi()` did the same thing by regex-splitting
   the model's own numbered-list ANSWER text; the new version splits on the parser's structured field
   instead, which is the whole point of having `TaskRepresentation`. The number of distinct queries
   fired per task is capped at `MAX_RAG_QUERIES` (8) — a vision-parsed task with an unusually long
   `subquestions` list (e.g. 25 items) must not fire one embedding call per item; the capped queries
   then ALL go out as a SINGLE batched call (`_embed_queries()`, `client.embeddings.create(input=[...])`
   accepts a list natively) instead of one API call per query — `_embed_query` (singular) still exists
   unchanged for the few call sites that only ever need one embedding at a time. `search_for_task()`
   returns `(snippets, usage)`, not just `snippets` — the caller (`telegram_bot.ensure_rag_context()`)
   folds `usage` into `record_ai_cost({**usage, "provider": "openai-embeddings"})` whenever
   `input_tokens` is nonzero, so embedding spend shows up as its own line in `get_ai_cost_stats_block()`
   instead of silently under-reporting total AI cost. `ensure_rag_context(session)` is the single
   entry point that computes-once/caches `session["rag_context"]` — `None` is the "not computed yet"
   sentinel (distinct from `""`, "computed, no snippets found"); `get_first_message_ai_answer()` calls
   it only on a cache miss, and `cb_ai_show_explanation`/the "later message in the same session"
   branches of `handle_ai_photo_input`/`handle_ai_text_input` call it too, so a session whose FIRST
   message was served from cache (and therefore never computed RAG) still gets a real, on-demand RAG
   context the moment it's actually needed (e.g. "Показать решение по шагам") instead of silently
   running ungrounded for the rest of that session.
4. **`ai/service.py`** (`solve(*, task=None, text=None, history=None, quick=False, bucket=None,
   rag_context=None)`) — only called on a cache MISS. `task` is passed only on the first turn of a
   session (its `to_prompt_text()` becomes the request content); every later turn passes `text`
   instead, since the task is already the first entry in `history`. `rag_context` is mixed into what
   actually gets SENT to the model but is deliberately kept OUT of the returned/stored `user_turn` —
   history isn't compacted on user turns (only old assistant turns get shortened, see
   `_compact_history`), so baking `rag_context` into `user_turn` would resend and re-bill the same
   grounding text on every subsequent turn of the session (the same cost-runaway class of bug that
   photos-in-history used to cause, before photos stopped entering history at all).
5. **`ai/validator.py`** (`validate_answer(task, answer)`) — pure-Python structural sanity checks,
   zero model calls: a `"calculation"` answer with no digit, an `"mcq"` answer that names none of
   `task.options`, a `"list"` answer with far fewer lines than `task.subquestions`, an empty answer,
   or `ai.router.looks_like_refusal()` firing. Does NOT check factual correctness — only "does this
   look like a plausible answer to this specific question shape".
   **`ai/math_verifier.py`** (`verify_calculation(task, answer)`) goes one level further, but ONLY
   for `task.type == "calculation"`: an actual independent recompute-and-compare, not just a shape
   check — this is what catches a wrong-but-plausible-looking number (e.g. `pH = 3.2` when the
   correct value is `3.7`), which `validate_answer` structurally cannot, since it only checks that
   *some* digit is present. Deliberately does NOT attempt to infer an arbitrary formula from free
   text (that would need either another model call, defeating "zero tokens", or a full CAS) —
   instead it holds a small, explicit registry of formulas it can recognize with confidence (today:
   Ohm's law, pH from `[H+]`/`[H3O+]`), matched via `task.values`/`task.units` (the parser's own
   structured fields) with unit strings compared EXACTLY against a known dict of SI-prefixed
   spellings (`_UNIT_MULTIPLIERS` — "А"/"мА"/"мкА", etc.), not by substring — a substring check on
   "а" for amperes previously risked matching inside unrelated units like "Па". The pH formula
   additionally requires the condition's own key to explicitly name the ion (`H+`/`H3O+`/`Н+`, see
   `_H_ION_KEY_MARKERS`) and bails out entirely (`checked=False`) if the question mentions a base
   (`_BASE_MARKERS` — NaOH, KOH, "гидроксид", "щёлочь", ...): pH of a base isn't `-log10([OH-])`,
   and applying the formula anyway would confidently return a wrong-by-14-minus-pOH answer. A
   question whose formula isn't in the registry (or isn't safely applicable) comes back
   `checked=False` — the verifier stays silent rather than guessing; a false "confirmation" is worse
   than no verifier at all. When it does have an opinion, it compares against `RELATIVE_TOLERANCE`
   (5%, generous enough for rounding, not for a wrong digit) and flags a ≥10× gap specifically as a
   likely unit/order-of-magnitude mix-up — and it grades the number found *after* a final-answer
   marker ("Итог:"/"Ответ:"/"Результат:") when the answer has one, not just the closest number
   anywhere in the text, so a correct intermediate value can't accidentally validate a wrong final
   claim in a detailed solution.
   **`ai/reference_bank.py`** + **`ai/mcq_verifier.py`** do the same job as the math verifier, but
   for `task.type == "mcq"`, against an actually objective source: the 1040-question official test
   bank of the ВМедА normal-anatomy department (`anatomy_exam_test.json`, the same content that
   powers "🎓 Экзамен → ✅ ТЕСТ" — see `ANATOMY_EXAM_TEST_PARTS`), each question already carrying a
   verified correct option. This is deliberately the ONLY subject/format the codebase treats this
   way — Biology/Physics/Chemistry/Anatomy-theory content is all free-text (`title`+`answer`), with
   no objectively-checkable "correct" field, so grading it would need another model call as judge
   (defeating "zero tokens"). `reference_bank.configure(ANATOMY_EXAM_TEST_PARTS)` (called at startup
   next to `ai_rag.configure()`) builds a keyword/stem index over the 1040 questions;
   `find_reference_match(question_text, options=None)` returns the closest match only above
   `MIN_MATCH_SCORE` (0.6 Jaccard-style overlap) — high on purpose, since a wrong match would
   silently hand back *someone else's* correct answer. Two more guards sit on top of the text score:
   negation/exclusion words ("не"/"нет"/"кроме"/"неверно"/"исключение") are tracked as a separate
   "polarity" token set (see `_POLARITY_EXACT_WORDS`/`_POLARITY_PREFIXES` — short words match
   exactly, not by prefix, so "не" doesn't swallow unrelated words like "невролог") and a query's
   polarity must match a candidate's EXACTLY, since normal keyword stemming drops words shorter
   than 4 characters and would otherwise treat "какая структура относится к X" and "какая структура
   НЕ относится к X" as the same question; and if the caller passes `options` (the parser's own
   `task.options`), they must be sufficiently similar (`_options_match`, ≥60% of query options
   found a plausible match) to the reference question's options, or the match is rejected — similar
   question text with a different set of answer choices is too risky to trust. `mcq_verifier.
   verify_mcq(task, answer)` then extracts which option letter the model's answer names (by
   explicit letter mention — matched at a delimiter OR end-of-string, so a bare "Ответ: Б" with
   nothing trailing the letter still counts — or by the option's own text) and compares it to the
   matched question's `correct` field.
6. **`ai/confidence.py`** (`decide(task, validation, *, rag_grounded=False, from_cache=False,
   math_verification=None, mcq_verification=None)`) — combines parse confidence + RAG grounding +
   the validator's verdict + (for calculations/mcq) the math/MCQ verifier's verdict into
   `SERVE`/`VERIFY`/`ESCALATE` (`_fold_verifier()` applies the same match-bonus/mismatch-penalty
   logic to both verifiers, since they're structurally identical signals — "does this answer agree
   with an objectively known-correct value"). A verifier MISMATCH (either one) forces `ESCALATE`
   directly, overriding everything else — disagreeing with an independent recompute or a verified
   answer key is stronger evidence than any structural heuristic; a `checked=False` verdict (formula/
   reference question not recognized) is a complete no-op on the score, never nudges the decision
   either way.
   `from_cache=True` always short-circuits to `SERVE` (trust was already established by admin
   moderation). `ESCALATE` does **not** trigger a hidden retry with a stronger model — `quick=True`
   requests are deliberately pinned to OpenAI only (self-consistency with the detailed step that
   follows), so there is no stronger provider to actually fall back to at this stage. Its real effect
   is queue priority: `get_next_pending_ai_cache_entry()` sorts pending moderation entries
   `ESCALATE` → `VERIFY` → `SERVE` (oldest-first within each tier) instead of pure arrival order, and
   `VERIFY`/`ESCALATE` results get `AI_LOW_CONFIDENCE_NOTE` appended to what's shown to the user —
   `session["quick_answer"]` (the canonical anchor `ai.prompts.explain_followup_text()` uses for the
   "show step-by-step" follow-up) always stays the ORIGINAL, unmarked answer so the warning text never
   leaks into what the model is asked to explain.

   **`ai.prompts.explain_followup_text(quick_answer, task_type)`** — the "🧠 Показать решение по
   шагам" follow-up prompt is branched by `task.type` (`cb_ai_show_explanation` passes
   `session["task"].type`), not one wording for every task shape. A real production case is why:
   the old universal wording ("explain HOW you got exactly this answer") is exactly right for
   `"calculation"` (there really is a step-by-step derivation to show) and works for `"mcq"`
   (explain why the right option is right and the others aren't), but for `"list"`/`"theory"`
   questions it made the model narrate its OWN reasoning process ("сначала я определил термины,
   затем собрал информацию...") instead of giving useful content — observed live on a list-type
   anatomy question. `"list"`/`"theory"` now get a content-focused instruction instead: expand each
   term (definition, structure/topography, significance), explicitly call out distinctions between
   similar/easily-confused terms ("X ≠ Y"), end with an exam-focused "what to remember" summary, and
   explicitly forbid narrating the reasoning process. All variants share one `_EXPLAIN_ANCHOR` (the
   canonical-answer anchor described above) so the consistency guarantee isn't lost per type. A
   missing/unrecognized `task_type` (e.g. a session whose first message was served from the
   raw-text pre-cache, which never parses and so never learns a real type) falls back to the
   original generic wording rather than guessing.

**`ai/router.py`** (`route_bucket`/`pick_provider`/`build_attempts`/`try_providers`) — `quick=True`
always uses OpenAI; `quick=False` routes by `bucket` (`"problem"` — calculation/list, stays on OpenAI
for self-consistency with the quick step; `"theory_simple"` — Gemini if configured; `"theory_complex"`
— Grok if `USE_GROK_FOR_DETAILED` and configured). `try_providers()` returns a full `attempts_log`
(`[{"provider", "status": "success"|"refused"|"failed", "usage"}, ...]`) — a `"refused"` attempt (the
model answered, just with a content-filter refusal) DID spend real tokens and must be billed;
`"failed"` (network/API error) never reaches a response, so its usage is always zero. On total
failure the raised exception (usually `AIRefusalError`) carries this log as `.ai_attempts_log`, so
even a fully-failed request's partial cost can still be recovered.
`telegram_bot.record_ai_attempts_cost(attempts_log)` is the one function that should ever record AI
cost from a `solve()`/`get_first_message_ai_answer()` call — it iterates every attempt (not just the
final one) and skips only zero-usage `"failed"` entries.

`AI_SESSIONS[user_id]` caches `task`/`bucket`/`rag_context` computed once at first-message time —
`is_first = session["task"] is None` gates both handlers (`handle_ai_photo_input`/
`handle_ai_text_input`): a later photo in the same session still gets vision-parsed (every photo is
parsed exactly once, the moment it arrives — never resent as raw bytes to the solver), but is no
longer treated as "first" and doesn't recompute `bucket`/`rag_context`.

**`AI_USER_LOCKS[user_id]`** (`asyncio.Lock`, `_get_ai_user_lock()`) is a SEPARATE dict from
`AI_SESSIONS`, deliberately never touched by `start_ai_session()` — closes a race the per-session
`session["processing"]` flag alone cannot: `start_ai_session()` REPLACES the whole
`AI_SESSIONS[user_id]` dict wholesale (a fresh `"processing": False`), so if a user taps "AI" again
while a previous request from the OLD session object is still mid-flight (holding that old dict's
`processing=True`), the new session's own `processing` flag reads `False` and would let a second,
quota-charging model call fire concurrently with the first — a duplicate spend the old flag can't
see, because it lives inside the very object being swapped out. All three cost-incurring entry
points (`handle_ai_photo_input`, `handle_ai_text_input`, `cb_ai_show_explanation`) now ALSO check
`lock.locked()` immediately after the existing `session["processing"]` check (same reject-not-queue
UX: silently drop the duplicate, don't wait for the lock) before acquiring it via `async with lock:`
for the request's full duration — the two checks aren't redundant, `session["processing"]` still
catches a same-session double-tap exactly as before, `lock.locked()` catches the cross-session case
the flag was blind to. `end_ai_session(user_id)` pops `AI_SESSIONS[user_id]` unconditionally but only pops
`AI_USER_LOCKS[user_id]` when `lock.locked()` is `False` — popping a currently-held lock would let a future
`_get_ai_user_lock()` call lazily create a second, different `Lock` object for the same user, defeating the very
mutual-exclusion guarantee the lock exists for. The check-and-pop is safe as one synchronous block: no `await`
sits between reading `.locked()` and the `pop()`, so nothing else on the event loop can acquire the lock in
between. Without this cleanup `AI_USER_LOCKS` would grow one entry per distinct user forever and never shrink.

**Provider request timeouts** — `ai/providers/openai.py` and `ai/providers/xai.py` both construct their
`AsyncOpenAI` client with `timeout=REQUEST_TIMEOUT_SECONDS` (30s; the SDK default is several minutes), and
`ai/providers/gemini.py`'s raw `aiohttp` call already used `aiohttp.ClientTimeout(total=30)`. A hung upstream
request needs to fail fast — `ai.router.try_providers()` catches any exception (a timeout raises like any other
provider failure) as a generic `"failed"` attempt and moves on to the next provider in the fallback chain, so a
stuck OpenAI call no longer holds `AI_USER_LOCKS`/`AI_CONCURRENCY_GATE` slots open indefinitely or leaves a user
waiting with no fallback.

**Bot-wide AI safety net** (on top of the per-user quota/lock above — a traffic spike is many
*different* users, each within their own daily quota, so a per-user limit alone can't cap total
concurrent spend):
- **`MAX_AI_CONCURRENT_REQUESTS`** (`AI_MAX_CONCURRENT_REQUESTS` env var, default 10) +
  `AI_CONCURRENCY_GATE` (an `_AIConcurrencyGate` instance) — all three cost-incurring entry points
  call `AI_CONCURRENCY_GATE.try_acquire()` as the LAST check before committing to the request (after
  the lock/breaker/quota checks, right before `async with lock:`) and reply with a short "too many
  requests right now" notice instead of queuing when it returns `False`; `release()` runs in the same
  `finally` block that resets `session["processing"]`. `try_acquire()` is a single **synchronous**
  method with no `await` inside — the "is a slot free" check and the "take it" increment happen as
  one unsplittable step, so no other coroutine on the event loop can ever observe a free slot between
  those two operations and also take it (the exact bug an earlier version had: the check and the
  increment lived in two separate statements with real `await` points — `callback.answer()`,
  `async with lock:` — in between, so two coroutines could both pass the check while the counter was
  at `MAX-1` and both increment, pushing the count above the intended ceiling). Checking
  `try_acquire()` LAST (not first, like the old check) matters too — it must be the final gate before
  the slot is actually consumed, or an early return further down (e.g. the quota check) would leak an
  acquired slot that never gets `release()`d. Deliberately not a bare `asyncio.Semaphore`: `async with
  semaphore` queues a caller until a slot frees rather than rejecting immediately, which is the wrong
  UX here (silently waiting is the same load buildup this gate exists to prevent, just invisible to
  the user) and `Semaphore` has no public non-blocking "try acquire" to build a reject-not-queue check
  on top of.
- **Cost circuit breaker** (`stats["ai_cost_windows"]`, `_update_ai_cost_windows()` called from inside
  `record_ai_cost()` on every recorded cost — including RAG/embedding cost, so a runaway RAG loop
  trips it too) — buckets spend into an hour window and a day window (same `*_key` + running-total
  reset-on-new-period shape as `ai_used_monthly` elsewhere in the file) and compares each against
  `AI_COST_HOUR_LIMIT_USD`/`AI_COST_DAY_LIMIT_USD` (env-overridable, default $5/hour, $30/day).
  Crossing either sets `breaker_tripped`, checked by `ai_circuit_breaker_tripped()` at the same four
  entry points as the concurrency/lock checks (plus `cb_ai_solve_start`, so a tripped breaker also
  blocks *starting* a new session, not just continuing one already open) — AI is fully disabled for
  everyone until an admin clears it. **Does NOT auto-clear on its own** when the next hour/day
  starts — that's deliberate: silently reopening after an hour would let a real problem repeat
  unnoticed. `reset_ai_circuit_breaker()` is the only way to clear it, wired to a
  "🔓 Сбросить AI-автовыключатель" button that `get_admin_stats_keyboard()` (`handlers/admin.py`)
  shows on the admin stats screen only while tripped — `cb_admin_stats` also prints the current
  hour/day spend + limits inline when tripped, so the admin doesn't need to dig through
  `get_ai_cost_stats_block()` to see why. `record_ai_cost()` fires a one-time Telegram alert to every
  `ADMIN_IDS` entry the moment `breaker_tripped` flips (`breaker_alerted` guards against re-sending on
  every subsequent blocked request) — scheduled via `asyncio.get_running_loop().create_task(...)`
  since `record_ai_cost()` itself is synchronous (called from many non-async call sites) but the alert
  needs to `await bot.send_message`.

**`scripts/ai_benchmark.py`** measures real pipeline accuracy against `ai/reference_bank.py`'s 1040
questions — same "not part of the bot/requirements.txt, run manually, costs real tokens" pattern as
`scripts/ai_model_compare.py`. Runs the actual `ai.vision_parser -> ai.router.route_bucket ->
ai.rag.search_for_task -> ai.service.solve(quick=True) -> ai.validator/ai.mcq_verifier ->
ai.confidence.decide` chain per question, grades the quick answer against the known-correct option,
and reports accuracy overall/by-part/by-`confidence_action`, plus a `verifier_flagging_rate` that is
deliberately a self-consistency check (the benchmark tests against the SAME bank the verifier reads
from, so it measures "did the confidence router correctly flag every wrong answer as ESCALATE",
not "does the verifier catch errors on held-out questions" — a value well under 100% means a
matching/extraction bug, not verifier weakness). Only unit-tested for its deterministic parts
(`tests/test_ai_benchmark.py`: `format_question_text`/`sample_questions`/`summarize`/
`format_report`/`format_comparison`/`estimate_result_cost_usd`, plus the `--confirm-cost` gate
itself, which IS safe to exercise in CI — it `sys.exit(1)`s before any provider call) —
`run_one()`/full successful `main()` runs make real provider calls and are exercised manually.
`--output`/`--compare-with` exist specifically so "did this architecture change actually help" can
be answered by diffing two JSON runs, not by impression. **Two independent cost guards**, since a
copy-pasted `--all` command (1040 real questions) with no other flags is an easy accident:
`CONFIRM_COST_QUESTION_THRESHOLD` (200) — any run requesting more questions than this (`--all` or a
large `--sample`) refuses to start at all (`sys.exit(1)`, explicit stderr message) unless
`--confirm-cost` is also passed; and `--max-cost-usd`, which lets a large confirmed run still bound
itself — `estimate_result_cost_usd()` (a deliberately rough OpenAI-price-only estimate, not real
billing) accumulates as each question finishes, and once the running total reaches the cap, every
further queued question is skipped (`error: "skipped: --max-cost-usd cap reached"`, no provider
call at all) rather than launched — remaining in-flight questions already past the semaphore still
finish normally, so the cap can be overshot slightly by however many are concurrently in flight
(bounded by `--concurrency`), not blown open-endedly.

## Known pitfalls (bug classes that have already recurred)

- **Per-topic keyboard labels hardcoded to one topic.** `get_anatomy_topic_keyboard()`'s bones-list button was
  hardcoded `"🦴 Кости черепа (по каждой кости)"` — correct only for the `skull` topic — and stayed that way
  through `trunk_bones`/`upper_limb_bones`/`lower_limb_bones` being added, showing "Кости черепа" on unrelated
  topics for months before it got noticed. When a keyboard/text function is reused across multiple
  topics/subjects/tiers, grep its literal strings for a name that only applies to the *first* case it was written
  for.
- **UI elements hidden by access/state instead of relabeled.** The `get_main_menu()` subscription button used to
  be `if not has_free_access(user_id): show button` — once a user crossed the referral threshold the entry point
  to subscriptions vanished from the menu entirely, with no path back to it. Prefer always showing an entry point
  with a state-dependent label (`"Подписка без рефералов"` vs `"Моя подписка"`) over conditionally hiding it —
  hiding silently removes discoverability and is easy to ship without noticing in testing (the admin/test account
  usually *has* access, so the hidden state never gets exercised).
- **Values duplicated out of `SUBSCRIPTION_TIERS` into hand-written text.** Prices and tier facts got hardcoded
  into `get_referral_status_text()`, `get_subscription_announcement_text()`, and a stray teaser line, separately
  from `SUBSCRIPTION_TIERS` itself. Changing a price (e.g. tier 1: 79₽→89₽) meant grepping the whole file for the
  old literal. Prefer `SUBSCRIPTION_TIERS[n]['price_rub']` interpolation over restating a price/duration/scope as
  a literal, even in one-off marketing copy.
