---
name: add-subject
description: >
  Turn a batch of raw source material (PDFs, DOCX, pasted course text, photo albums,
  manifests, ZIP archives) that the user has dropped for a new medical-exam subject into
  a fully working, tested section of this vmeda-biology-bot Telegram bot. Use this
  whenever the user uploads files and asks to "add [subject]", "добавь предмет",
  "сделай раздел по [теме]", or hands over course material for a subject the bot doesn't
  have yet (or an existing subject that needs a new sub-section, the way Рубежные
  контроли was added to Физиология) — even if they don't spell out the JSON schema,
  handler wiring, or test requirements themselves. Also use it when the user says they're
  tired of manually compiling a course plan before sending material — that pre-digestion
  step is this skill's job, not theirs; they should be able to just hand over the raw
  files.
---

# Add a new subject to vmeda-biology-bot

You've done this three times already in earlier sessions on this repo: Нормальная
физиология (23 topics + 149-question quiz bank), Оперативная хирургия (61 topics across
4 volumes), and Рубежные контроли (11 real exam controls parsed straight from DOCX). This
skill is that playbook written down, so the next one goes just as smoothly without
re-deriving the conventions from scratch.

**Read `CLAUDE.md` first, in full, before touching anything.** It's the live,
actively-maintained architecture doc for this repo — it documents exactly how every
existing subject is wired (data model, handler pattern, menu placement, AI indexing,
access gates) with real examples and the reasoning behind each choice. This skill is a
checklist and pointer, not a replacement for it. If anything here and CLAUDE.md disagree,
CLAUDE.md wins — it changes as the repo evolves and this file might lag.

## The one rule that overrides everything else: zero fabrication

This is the load-bearing value of the whole project, mentioned constantly in CLAUDE.md.
Every fact that ends up in the bot must trace back to something the user actually
supplied. Never invent content, never "fill in" a gap with what you already know about
the subject from training, never smooth over a source that's incomplete or messy by
writing something plausible instead. If the source doesn't cover something, the honest
move is an empty field / a missing button / a documented gap — not a placeholder that
looks like real content. Students are using this to prepare for a real kafedral exam;
a confidently-wrong fact is worse than a visible gap. Every subject built so far
discloses its own honest gaps in CLAUDE.md (Physiology topics 06/07 have zero quiz
questions because the source has no structured content for them; Operative Surgery
volume IV has no control-questions button because the source never had one) — do the
same for whatever you build.

## The second rule: process every file properly, don't skim it

Treat every file the user hands over as material to actually read end to end, not to
sample. A PDF/DOCX can bury its most exam-relevant content on page 40; a folder can mix
real lecture material with a stray unrelated file. Open everything, check page/section
counts against what you actually extracted, and don't silently stop early because the
first few pages looked repetitive — one skipped page for a full-length source is a real
gap in a subject a student is trusting to be complete. If a tool truncates what it hands
you (a PDF reader capping pages, a huge DOCX), explicitly read the rest in follow-up
passes rather than treating the truncated view as the whole document.

## Presentation quality: structure it for how a student actually studies

The goal isn't just "the facts are in there somewhere" — it's material a student can
read at 11pm before an exam and actually retain. Once you've extracted everything, don't
just dump it as one undifferentiated blob:

- Mirror the source's own structure where it has one (headings, numbered questions,
  definition/mechanism/example groupings) rather than flattening everything into plain
  paragraphs — a source that already separates "определение" from "механизм" from
  "клиническое значение" is telling you how the department itself expects the material
  to be studied.
- Use `<b>bold</b>` for key terms and the numbers/names a student needs to actually recall,
  `<i>italic</i>` for Latin nomenclature (the convention already used throughout Anatomy/
  Physiology) — this is what turns a wall of text into something scannable.
- Break content into short paragraphs and real lists (`•`/numbered), not run-on
  sentences — a numbered list that a naive parser flattened into one paragraph is a bug,
  not a formatting choice (see Step 5's ETL gotchas).
- Use `DIVIDER` (`━━━━━━━━━━━━━━`) the way every existing subject does, to mark a visual
  break between a title and its content, or between sub-sections on the same screen.
- If the content is naturally chunked (a topic, a numbered question, a control-work
  variant), give it its own screen/page rather than cramming several units into one long
  message — see Step 8 on pagination for the mechanics, but the paragraph-boundary
  splitting there should follow content units, not just character counts.
- None of this means paraphrasing or "improving" the source's wording — reformatting for
  readability (line breaks, bold, dividers) is presentation, not content, and stays
  strictly separate from the zero-fabrication rule above: the *words* stay the source's
  own, only the *layout* is yours to design.

## Step 1: Understand the raw material before designing anything

Don't ask the user to pre-summarize the files into a course plan — that's exactly the
manual step this skill exists to remove. Just read what they gave you: open the PDFs/DOCX,
unzip the archive, read the manifest if there is one. Figure out:

- What's the natural unit of content? A flat list of numbered Q&A pairs (like Рубежные
  контроли)? Topic chapters with sub-sections (like Physiology's `sections[]`)? A
  curriculum of lessons (like Operative Surgery's `topics[]`/`volumes`)?
- Does the source already have an extraction manifest with SHA-256 hashes and image
  placeholders (as the Рубежные контроли archive did)? If so, trust its `extraction_policy`
  field for how literally the text was pulled from the original document — that tells you
  whether blank-line-separated blocks are real source paragraphs 1:1, which matters for
  how conservative you can be about restructuring vs. preserving order exactly.
- Are there images or diagrams? What format, how many, do they have real captions/
  attribution — see Step 2 below for what to do with them.
- Does the material include контрольные работы / рубежные работы / зачёты / экзамены
  (as opposed to plain study material)? See Step 3 below — these get their own treatment,
  not just another topic.
- Is there a citation/source-file/page-number field per item? Keep it as data even if
  (per the current pattern in this repo — Physiology explicitly does this on user
  request) it never gets rendered in the UI. Provenance stays in the JSON as metadata for
  traceability; whether to *display* it is a separate, explicit product decision — don't
  assume either way, ask if it's not obvious from how similar content is already handled.

## Step 2: Images and diagrams — include the good ones, extract text from the readable ones

Source material for a medical subject often comes with photos and schematic diagrams that
are genuinely part of what a student needs to learn (an anatomical illustration, a
labeled diagram of a mechanism, a graph) — don't discard these as an afterthought, they
carry real teaching content plain text can't.

- **Judge quality before including an image.** A clear, legible, well-cropped image
  belongs in the bot. A blurry phone photo, a heavily-compressed scan where labels are
  unreadable, or a duplicate/near-duplicate of an image already included isn't worth
  shipping — it wastes the student's time squinting at something they can't actually
  read. When in doubt on a borderline case, err toward including it (the same "honest
  gap" principle that already applies to text: Operative Surgery's third instrument photo
  pack shipped web-sourced photos with disclosed provenance rather than nothing at all)
  but flag the quality tradeoff to the user in your final report rather than silently
  deciding for them.
- **If an image's content is really text** (a scanned page, a table rendered as an image,
  a slide full of labels) and the text is legibly extractable, extract it and fold it
  into the course material as real text — don't leave genuinely readable information
  trapped in an image a student can't search or that a small phone screen renders
  unreadably small. This still falls under zero-fabrication: transcribe what the image
  actually says, verify it against the image again before trusting it (the same
  "don't just eyeball it" standard as Step 6's losslessness check), and if a word or
  number is genuinely illegible, mark it as such rather than guessing a plausible value.
- **If an image is primarily a diagram/illustration** (not text-as-image), keep it as an
  image node/field rather than trying to describe it in prose — a description is a lossy,
  editorialized stand-in for the real thing when the original is perfectly usable as a
  photo. Follow Step 6 below for how images are stored and delivered.

## Step 3: Контрольные работы / рубежные работы / зачёты / экзамены — always their own subsection

If the material includes graded assessments — control works, rubezh (checkpoint) exams,
credit tests, final exams — these are not just more study topics to fold into the regular
topic list. Give them their own clearly-labeled subsection within the subject (the way
"📋 Рубежные контроли" sits alongside Physiology's regular topic list, reachable from the
subject's own menu, not buried inside a topic) — that mirrors how a student actually
thinks about their coursework: "material to learn from" and "the specific graded work I
need to pass" are different mental categories, and burying the second inside the first
makes it hard to find right before it matters.

Structure the assessment content the way the source itself organizes it, and make it easy
to navigate at the point of use:

- If the source is split into **variants** (билет/вариант N, several parallel versions of
  the same assessment), keep that structure — list variants, let the student pick one,
  then browse that variant's own questions. Don't merge variants into one undifferentiated
  pile; a student preparing for a specific variant needs to find exactly that one.
- If the source is one continuous **numbered list of questions** (as most of the Рубежные
  контроли controls were), browse by question — a paginated reading flow (see Step 8) is
  the right shape, not a variant picker that doesn't exist in the source.
- Preserve whatever the source itself provides — a real answer key, worked answers, or
  (honestly, per the zero-fabrication rule) just the questions with no key if that's all
  the source has. Rendering a bare self-check list instead of inventing a tap-to-reveal
  quiz for content with no verified answer key is the established pattern (Operative
  Surgery's control questions, Рубежные контроли's own ungraded self-check) — don't build
  a graded quiz UI on top of an answer you're not sure is right.
- Keep this content-viewing feature scoped to what's actually there — a full quiz/SRS/
  mastery layer is a separate, bigger feature decision (Physiology's own regular quiz
  bank has one, Рубежные контроли deliberately doesn't) and shouldn't be assumed by
  default; ask if it's unclear whether the user wants graded self-testing on top of the
  assessment content or just convenient browsing.

## Step 4: Design the JSON schema

There are two canonical shapes already in use — pick whichever actually matches the
source instead of forcing a mismatch:

1. **Topic + specialized fields** (Physiology's `topics[]`): each topic has named fields
   for different content kinds (`definitions[]`, `mechanisms[]`, `cause_effect[]`, etc.)
   *plus* a `sections[]` full-fidelity backbone for whatever doesn't fit the named
   fields — never let content silently disappear because it doesn't match your schema's
   named slots. Use this when the source has recognizable recurring structure (definitions,
   mechanisms, comparisons) that's worth surfacing as its own UI mode, on top of a plain
   reading mode.
2. **Ordered block stream** (Рубежные контроли's `blocks[]`): a flat list of
   `{type: "text"|"image"|"table", ..., provenance}` nodes in strict source order. Use
   this when the source is closer to a linear document (an exam Q&A list, a lecture
   transcript) where inventing topic-level structure would mean editorializing content
   that should just be preserved as-is. Every node carries `provenance`
   (`source_docx`/`source_file`, `location`, and — for images — their own `sha256`) even
   if nothing in the UI ever prints it.

Either way: add the new bank as its own top-level JSON file (`repositories/knowledge.py`
loads it, `telegram_bot.py` re-exports the name) *or* as a new top-level key inside an
existing subject's JSON if it's naturally a sub-section of something already there (this
is what Рубежные контроли did — `physiology.json["boundary_controls"]`, sibling to
`topics`/`quiz_questions`). Ask yourself: is this a new subject a student picks from the
main menu, or a new mode inside an existing subject? That decides which. An assessment
subsection from Step 3 usually gets its own top-level key too, sibling to the regular
topic bank, for the same reason.

## Step 5: Write the one-time ETL script — in the scratchpad, not the repo

Write a Python parser in your scratchpad directory that turns the raw source into the
JSON schema from Step 4. This script is **never committed** — every subject built so far
followed this convention, the parser is single-use tooling for this one import, not
maintained code. Don't try to build a generic reusable parser; write the smallest thing
that correctly handles *this* source's actual shape.

Watch for real gotchas that have bitten this before:
- A blank-line-delimited "paragraph" splitting rule will break a list of bullet points
  that has its own blank lines between items — you may need to detect and re-merge runs
  of list-item lines before treating each blank-separated block as independent.
- A source's own trailing sentence sometimes gets glued onto the wrong block with no
  blank line separating it (an artifact of the original document → text extraction, not
  something you introduced) — never silently drop it and never force it into a field it
  doesn't belong in (e.g. a stray sentence after a table's last row is not a table cell);
  split it into its own node right after, preserving order.
- If the source came from a copy-pasted AI conversation (ChatGPT, etc.), check for leaked
  UI chrome ("4o", "Regenerate response", the assistant's own name) and content drift
  where a later paste answers a completely different question than the one titled — this
  has happened in this exact repo before (see git history around `questions.json` fixes).

## Step 6: Verify losslessness before trusting the output

Don't just eyeball the parser output. Reconstruct the text from your parsed
nodes/fields and diff it against the raw source with `difflib.SequenceMatcher`, expecting
a similarity ratio of 1.0 (modulo whitespace collapsing) — this is what caught every real
bug in the Рубежные контроли import (a mis-parsed table, a swallowed trailing sentence).
If a manifest gives you SHA-256 hashes for source files and images, verify every single
one after copying, both against the manifest and again after the file lands in its final
repo location — catches truncation/corruption during copy, not just parsing bugs.

## Step 7: Images — this repo's own convention, not the source's assumed one

Images go under `images/<subject>/...` (e.g. `images/physiology/boundary_controls/rk_01/media/...`),
resolved relative to `IMAGES_DIR` in `telegram_bot.py`. A source archive's own manifest
may assume a *different* path convention (Рубежные контроли's manifest assumed
`content/physiology/...`, which doesn't exist in this repo) — remap paths to this repo's
convention when writing image references into your JSON, don't copy the source's assumed
layout verbatim.

For sending images in Telegram, follow the file_id-caching pattern already used
everywhere (`ANATOMY_FILE_ID_CACHE`, `OH_FILE_ID_CACHE`, `PHYS_RK_FILE_ID_CACHE`): a small
JSON cache under `STATS_DIR`, keyed by image path, populated from `sent_message.photo` on
first send. Without it, every repeat view re-reads the file from disk and re-uploads it to
Telegram.

## Step 8: Build `handlers/<subject>.py`

Own `aiogram.Router`, imported late at the very end of `telegram_bot.py` (after
`PHYSIOLOGY`/`DIVIDER`/`safe_edit_text`/etc. it needs are already defined) —
`handlers/operative_surgery.py` and `handlers/physiology.py` are the templates to copy the
shape from:

```python
from handlers import <subject> as <subject>_handlers  # noqa: E402 — deliberately late

dp.include_router(<subject>_handlers.router)

get_<subject>_menu_text = <subject>_handlers.get_<subject>_menu_text
# ... flat re-export every public get_*/cb_* name so tb.<name> works from tests too
```

**One real exception to "handlers own their own screens":** if the subject needs a
plain-text search prompt (a pending-state text handler triggered by *any* next message,
not a callback), it can't live in the Router module — `dp.include_router()`
registrations land at the very end of the dispatch chain, after
`handle_keyword_search` (the Biology catch-all with no guard), so a search handler
registered that way would never see its query. Put the `*_SEARCH_PENDING` set and its
message handler directly in `telegram_bot.py`, positioned before
`handle_keyword_search` — see `handle_oh_search_query`/`handle_phys_search_query` for
the exact placement and the comment explaining why.

## Step 9: Message-length safety

Telegram's hard cap is 4096 chars per text message, 1024 for a photo caption
(`CAPTION_LIMIT`). Never truncate content to fit — paginate instead, and only split at
real content boundaries (a paragraph, a block, a topic section), never mid-sentence.
`build_rk_pages()` in `handlers/physiology.py` is a clean, small reference implementation:
greedily group consecutive text/table nodes up to a safe budget (~3500 chars leaves
headroom for the page header), and give every image its own page since a photo can't be
merged into an already-sent text message. If you're mixing text and photo messages in one
navigable sequence, use delete-and-resend on every ⬅️/➡️ tap (same as Biology/Physics/
Histology carousels and the Рубежные контроли reader) — `edit_text` can't turn a text
message into a photo message or back.

## Step 10: Wire the menu entry point — and actually verify the access/subscription logic

Check `COURSE_SUBJECTS` in `telegram_bot.py` (the "1️⃣ Первый курс" / "2️⃣ Второй курс"
grouping) — decide which course(s) the new subject belongs in, or whether it needs its
own top-level main-menu button instead. Default to **free for everyone, no referral gate,
no subscription check** — this has been the choice for every subject added recently
(Operative Surgery, Physiology) unless the user explicitly asks for gating.

Whichever you pick, don't just assume it works — access control is exactly the kind of
thing that's silently wrong until someone checks, and getting it wrong either locks
paying-adjacent content nobody can reach or leaks something that was supposed to cost
money. Actually verify, don't just wire and move on:

- **Free-for-everyone** (the default): confirm the new subject's callback-data prefixes
  are genuinely absent from `GATED_CALLBACKS_*`/`GATED_PREFIXES_*` in `services/access.py`
  — `referral_gate_middleware` only gates what's on that explicit allowlist, so "absent"
  already means "ungated", but write an actual test asserting
  `tb.is_gated_callback("<subject>:menu")` (and any other top-level entry callback) is
  `False`, so a future accidental addition to the allowlist gets caught instead of
  silently locking a subject that's supposed to stay open.
- **Gated** (only if the user explicitly asks): first figure out *which* of the two
  existing gating shapes this matches, rather than inventing a third — Biology/Physics/
  Chemistry use the shared `referral_gate_middleware` allowlist (subject-aware, checks
  `has_subject_access`); Anatomy/Histology instead use their own dedicated
  `*_access_ok()` boolean predicate plus per-tier flags snapshotted onto
  `SUBSCRIPTION_TIERS` entries. Picking the wrong shape means re-deriving edge cases
  (subject-restricted tiers, admin bypass, temp-access grants, monthly-recurring referral
  thresholds) that the existing shape already handles correctly.
- If the new subject needs its own `SUBSCRIPTION_TIERS` flag (the way `anatomy`/
  `histology_until_rule` work), **never reuse or repurpose an existing tier's numeric
  key** — `stats["subscriptions"]` stores only the tier id, so reusing one would silently
  reinterpret what an existing payer already bought. Add a new key above the current
  highest, and snapshot the grant onto the subscription record at `grant_subscription()`
  time, not derived live from a global constant later (see CLAUDE.md's Subscriptions
  section for exactly why — a later constant change must never retroactively shrink a
  promise already sold).
- Either way, write tests that actually exercise the boundary: admin always gets in;
  a non-admin with no qualifying access is blocked (and — if gated — sees a real path to
  get access, not a dead end); a non-admin who does qualify (real referral count, real
  granted subscription) gets in; if there's a promo/global-override mechanism in play,
  check explicitly whether the new subject is meant to respond to it or deliberately
  stays excluded the way Anatomy excludes itself from the global promo. Don't infer
  "it probably works" from the gate function's code — actually call it both ways in a
  test with a real fake user id.
- Check the main menu / course menu against the "hide vs. relabel" pitfall in CLAUDE.md:
  if access depends on a subscription/referral state, the entry point should always be
  visible with a state-dependent label (locked vs. unlocked), never conditionally hidden
  — a hidden entry point is easy to ship without noticing, since the admin/test account
  usually already has access and never exercises the hidden state.
- If the new subject (or its assessment subsection from Step 3) is meant to be paid-only,
  keep in mind VMedA AI's RAG grounding (Step 11) is a **separate, already-decoupled axis**
  in this codebase — indexing paid content for AI grounding doesn't currently check
  per-subject access at all (documented in CLAUDE.md: "content-access rights and AI-
  request rights are deliberately independent axes"). That's an existing, intentional
  product decision, not something this skill should silently override — but flag it to
  the user if the new subject is paid, so the tradeoff (AI can ground answers in paid
  content for free-tier AI users) is a conscious choice, not a surprise.

## Step 11: Wire into VMedA AI's RAG grounding (ask first if unclear whether this is wanted)

`ai/rag.py`'s `build_index()`/`configure()` take the new subject's data as a parameter
and add entries to the shared index other students' AI questions can retrieve from.
**Never index one giant blob per topic/control** — `format_context()` only ever shows the
model the first `SNIPPET_MAX_CHARS` (600) characters of whatever entry matched, so a
10,000-character entry silently makes every fact past the first ~600 characters
unreachable even on a perfect keyword match. Chunk into small, focused pieces instead
(~500 chars, see `_chunk_rk_blocks`/`RK_CHUNK_CHAR_BUDGET` in `ai/rag.py` for the exact
pattern) — small enough that a matched chunk almost always survives the truncation whole.
Skip indexing bare name lists with no explanatory prose (instrument lists, station
names) — there's nothing in them to ground an answer with.

## Step 12: Tests — `tests/test_<subject>.py`

Every existing test file in this repo is a standalone script (no pytest) that imports
`from _bootstrap import tb` and drives real handler functions with hand-rolled
`FakeUser`/`FakeMsg`/`FakeCB` mocks plus an `HTMLParser`-based `check_html()` helper
(asserts tag balance and the 4096-char cap). Copy the shape from
`tests/test_physiology_rk.py` or `tests/test_operative_surgery.py` — numbered
`# ---- N. ... ----` checks with a `print("N. ...: OK")` after each. Cover at minimum:

- **Dataset integrity**: exact counts match what you actually parsed, unique IDs, no
  leftover parser markers (`{{IMAGE:`, raw markdown table syntax, etc.) in rendered text,
  every image path resolves to a real file whose SHA-256 matches what's stored in the
  dataset itself (self-contained — don't depend on the original source archive still
  existing on disk, it won't survive to CI or a fresh clone).
- **Navigation**: menu → list → detail, pagination boundaries (first page has no "back",
  last has no "forward"), unknown ID / out-of-range page rejected with an alert and no
  crash.
- Whatever's specific to this subject's UI modes (quiz engine, image delivery, table
  rendering, search, variant picker for assessments) — see existing test files for the
  pattern per feature type.

**Check for an existing test file covering the area you're touching before writing a new
one** if this is an addition to an existing subject rather than a brand-new one.

## Step 13: Document it in CLAUDE.md

Add a subsection matching the depth and style of the existing subject sections — what the
data model is, why any non-obvious design choices were made (the "why", not just the
"what"), navigation flow, any honest scope limitations. This is what makes the *next*
"add a subject" request fast too, and what keeps this skill itself from going stale the
way the Anatomy exam "Вопросы практики/теории are stubs" line did after those sections
were actually finished.

## Step 14: Verify before shipping

```
python3 -m py_compile telegram_bot.py handlers/<subject>.py
ruff check .
python3 tests/run_all.py
```

All three must be clean. `tests/run_all.py` is the only regression safety net for the
whole bot — a change that breaks an unrelated subject's tests is a real regression, not
noise to explain away.

## Step 15: Ship it

```
rm -f stats.json stats.json.tmp   # never commit real runtime stats
git add <files>
git commit -m "..."
git push -u origin claude/vmed-exam-prep-bot-q88a5i
```

**Never merge to `main` unless explicitly asked.** Railway auto-deploys from `main`; the
dev branch is where work lands by default. If asked to merge, follow the exact sequence
in CLAUDE.md's "Deploy" section (fetch, fast-forward main onto both, push, switch back to
dev).

## Step 16: Report back

Summarize plainly: which files were created/changed, where the new dataset lives and how
to regenerate it (the scratchpad ETL script's location, even though it's not committed —
so the user could ask for it again if needed), exact content counts (topics/questions/
images — whatever's countable), which images were included vs. left out and why, whether
any image text was OCR'd into the material, test results, and any honestly-disclosed
scope limitations or gaps in the source material. This mirrors how every subject built so
far has been reported — it's what lets the user trust the "no fabrication" claim instead
of just taking it on faith.
