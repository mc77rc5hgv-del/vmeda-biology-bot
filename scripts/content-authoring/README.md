# Content-authoring scripts

One-off Python scripts used to generate/expand/restructure the top-level content JSON files
(`anatomy.json`, `histology.json`, `physics_*.json`, `chemistry_tasks.json`, etc.) from source
material (textbook excerpts, PDF page exports, Gaivoronsky handouts). Archived here for
provenance — so a future editor can see how a given section of content was produced and adapt
the same approach, not because these are meant to be re-run as-is.

Notes:
- Most were run once from the repo root with hardcoded relative paths (e.g. `open("anatomy.json")`)
  and mutated the JSON in place; a few reference absolute paths from the authoring session's
  scratchpad (e.g. `organize_images.py`'s `SRC`) that no longer exist.
- Naming reflects the order/context they were written in (`build_myology1.py` .. `build_myology14.py`,
  `expand_batch1.py` .. `expand_batch6.py`, `add_topic2.py` .. `add_topic14_15.py`) rather than a
  designed pipeline — there's no single entry point.
- None of these are imported by `telegram_bot.py` or the test suite; they're a historical record,
  not runtime code.
