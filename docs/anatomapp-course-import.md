# Anatomy course in the Mini App

Imported only into `Анатомия → Курс` from `mc77rc5hgv-del/Anatomapp`, commit `e82ab964e01492138edb8361abe0f5fabda2b043` (README identifies @Vmeda_anatom_bot).

143 topics: osteology 37, syndesmology 15, myology 15, splanchnology 31, neurology 33 (CNS 15, PNS 11, senses 7), angiology 12. Module order, all 31 subsection headings, three neurological branches, complete theory, Latin names, cards, term pairs and self-study questions are preserved. No decorative images are imported. Questions show answers in expandable self-study disclosures and do not modify exam scores.

`generated_courses/anatomy_miniapp.json` stores source file hashes, original topic numbers and unmodified source data. To reproduce, download index.html and all eight *-data.json files at the pinned commit and run `python tools/import_anatomapp_course.py SOURCE_DIRECTORY`. Python literal parsing reads only the three hierarchy declarations; source application code is never executed.

The API exposes distinct stable `anatomapp_*` IDs, with server-side maintenance/subscription/tester checks inherited from existing permissions. Neurology children inherit the parent's paid gate. Bot `anatomy.json`, Telegram handlers and exam banks are unchanged. All 107 legacy topic routes and module routes remain supported for existing history, bookmarks and resume links. No database migration or data deletion is performed.

Verification: all 143 material bodies/navigation paths and gates, exact topic coverage, legacy links and persisted learning records, full API suite, bot tests, synchronization checks, frontend build and lint. External source text was copied, not medically re-reviewed in this change.
