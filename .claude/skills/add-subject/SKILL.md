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
- Are there images? What format, how many, do they have real captions/attribution?
- Is there a citation/source-file/page-number field per item? Keep it as data even if
  (per the current pattern in this repo — Physiology explicitly does this on user
  request) it never gets rendered in the UI. Provenance stays in the JSON as metadata for
  traceability; whether to *display* it is a separate, explicit product decision — don't
  assume either way, ask if it's not obvious from how similar content is already handled.

## Step 2: Design the JSON schema

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
main menu, or a new mode inside an existing subject? That decides which.

## Step 3: Write the one-time ETL script — in the scratchpad, not the repo

Write a Python parser in your scratchpad directory that turns the raw source into the
JSON schema from Step 2. This script is **never committed** — every subject built so far
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

## Step 4: Verify losslessness before trusting the output

Don't just eyeball the parser output. Reconstruct the text from your parsed
nodes/fields and diff it against the raw source with `difflib.SequenceMatcher`, expecting
a similarity ratio of 1.0 (modulo whitespace collapsing) — this is what caught every real
bug in the Рубежные контроли import (a mis-parsed table, a swallowed trailing sentence).
If a manifest gives you SHA-256 hashes for source files and images, verify every single
one after copying, both against the manifest and again after the file lands in its final
repo location — catches truncation/corruption during copy, not just parsing bugs.

## Step 5: Images — this repo's own convention, not the source's assumed one

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

## Step 6: Build `handlers/<subject>.py`

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

## Step 7: Message-length safety

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

## Step 8: Wire the menu entry point

Check `COURSE_SUBJECTS` in `telegram_bot.py` (the "1️⃣ Первый курс" / "2️⃣ Второй курс"
grouping) — decide which course(s) the new subject belongs in, or whether it needs its
own top-level main-menu button instead. Default to **free for everyone, no referral gate,
no subscription check** — this has been the choice for every subject added recently
(Operative Surgery, Physiology) unless the user explicitly asks for gating. If gating is
wanted, `services/access.py` has the referral-gate and subscription-tier machinery; ask
before wiring a new subject into either, since it changes real user access and revenue.

## Step 9: Wire into VMedA AI's RAG grounding (ask first if unclear whether this is wanted)

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

## Step 10: Tests — `tests/test_<subject>.py`

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
  rendering, search) — see existing test files for the pattern per feature type.

**Check for an existing test file covering the area you're touching before writing a new
one** if this is an addition to an existing subject rather than a brand-new one.

## Step 11: Document it in CLAUDE.md

Add a subsection matching the depth and style of the existing subject sections — what the
data model is, why any non-obvious design choices were made (the "why", not just the
"what"), navigation flow, any honest scope limitations. This is what makes the *next*
"add a subject" request fast too, and what keeps this skill itself from going stale the
way the Anatomy exam "Вопросы практики/теории are stubs" line did after those sections
were actually finished.

## Step 12: Verify before shipping

```
python3 -m py_compile telegram_bot.py handlers/<subject>.py
ruff check .
python3 tests/run_all.py
```

All three must be clean. `tests/run_all.py` is the only regression safety net for the
whole bot — a change that breaks an unrelated subject's tests is a real regression, not
noise to explain away.

## Step 13: Ship it

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

## Step 14: Report back

Summarize plainly: which files were created/changed, where the new dataset lives and how
to regenerate it (the scratchpad ETL script's location, even though it's not committed —
so the user could ask for it again if needed), exact content counts (topics/questions/
images — whatever's countable), test results, and any honestly-disclosed scope
limitations or gaps in the source material. This mirrors how every subject built so far
has been reported — it's what lets the user trust the "no fabrication" claim instead of
just taking it on faith.
