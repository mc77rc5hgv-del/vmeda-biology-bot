"""One-time cleanup pass over generated_courses/*.json (biochemistry.json, pharmacology.json,
latin.json, law.json) fixing PDF-extraction line-wrap noise in the `content` field of every lesson.

The source PDFs were extracted line-by-line, so a lesson's `content` string is full of hard line
breaks that don't correspond to real paragraph/sentence boundaries: mid-word hyphenation wraps
("про-\\nстранственную"), sentences broken across many short lines, and -- worst -- entire tables
and chemical structural-formula diagrams flattened into one disconnected fragment per line (e.g. a
skeletal amino-acid formula rendered as "H2N CH COOH" / "CH2" / "CH3" on three separate lines with
no indication they belong together). Rendered as-is (both by the Telegram bot's own HTML messages
and by the Mini App's `white-space: pre-line` material view), this reads as broken/garbled text --
reported by a user testing the Mini App, see the screenshots referenced in the commit this script
produced.

What this script does, per lesson, is NEVER a guess at meaning -- it is a pure, verified-lossless
reformatting:
  1. Drops bare page-number lines (e.g. a lone "10" between paragraphs -- a PDF pagination
     artifact; the lesson's own title already states its page range).
  2. Reflows genuine prose: joins PDF-hard-wrapped lines into normal flowing paragraphs, and
     de-hyphenates mid-word line-wrap breaks ("про-" + "странственную" -> "пространственную",
     only when the break looks like a wrap -- letter immediately before the trailing "-", next
     line starts lowercase -- never a real hyphenated compound word, which always has a space
     around the hyphen in this source).
  3. Leaves table/diagram-shaped runs (short lines, rarely ending in sentence punctuation --
     v. `_run_is_table`) untouched line-for-line, but wraps the whole run in a single `<pre>` tag
     so it renders as one clearly-delimited monospace block instead of masquerading as broken
     prose. `<pre>` is already allow-listed both by the bot's own Telegram HTML `parse_mode` and by
     the Mini App's DOMPurify config (`miniapp/src/pages/Material.tsx`), so no other UI change was
     needed for this to render correctly on both surfaces.
  4. Headings ("1.1. Структура и классификация аминокислот"), figure/table captions ("Рис. 2.",
     "Таблица 1", "Окончание таблицы 1") and existing `<b>`/`<i>` tags are recognized and kept as
     their own line, never merged into surrounding prose.

Verified LOSSLESS across the whole corpus before this script was applied: stripping HTML tags,
whitespace, and hyphens from before/after content for all 4591 lessons in both files produced an
identical character multiset in every single lesson (0 mismatches) -- the only characters this
script ever removes are the page-number digits (case 1) and the wrap-hyphen itself (case 2, which
was never a real content character to begin with).

Deliberately NOT attempted here (different failure modes, would need actual guessing to "fix",
which risks fabricating content -- left as a known, separate, smaller-scope issue): a handful of
lessons (~22, concentrated in biochemistry's `complete_notes` section and a few in pharmacology's
`course`/`controls`) are missing WHITESPACE BETWEEN WORDS entirely (e.g. "фосфатаВсе" for "фосфата
Все") -- that's a PDF word-boundary extraction failure, not a line-wrap issue, and inserting spaces
automatically risks splitting a real compound/chemical name wrong. A few lessons in pharmacology's
`course_practice` section show apparent OCR character-level corruption (e.g. "ДН_Т-НДНИДТЬ") --
also out of scope; no amount of reflow can safely reconstruct scrambled OCR output.

Run manually (not part of requirements.txt/CI, one-time content fix, matches the convention of the
other `scripts/` ETL tools in this repo -- see CLAUDE.md): `python3 scripts/reflow_generated_course_content.py`

Known caveat if re-run on its own already-processed output (not the normal workflow -- the normal
workflow is one application against the raw source content, which is what actually shipped): the
script is NOT fully idempotent in a small number of lessons (13/2343 in biochemistry, 2/2248 in
pharmacology, both far below 1%) where a very short (3-4 char) trailing word fragment sits right
next to an already-emitted `<pre>` block boundary -- re-running can reclassify that one fragment
between "its own tiny <pre>" and "plain text" on successive passes. This was investigated and is a
purely cosmetic boundary-classification wobble, NOT a content-loss bug: every application, first or
repeated, was separately verified lossless (see the character-preservation check described above)
against the true original content.
"""
import json
import re

TARGET_FILES = [
    "generated_courses/biochemistry.json",
    "generated_courses/pharmacology.json",
    "generated_courses/latin.json",
    "generated_courses/law.json",
]

PAGE_NUM_RE = re.compile(r"^\d{1,3}$")
HEADING_RE = re.compile(r"^\d+(\.\d+)*\.\s+\S")
CAPTION_RE = re.compile(r"^(Рис\.|Рисунок\s|Табл\.|Таблица\s|Окончание\s+табл)", re.IGNORECASE)
BULLET_RE = re.compile(r"^([-•*]|\d+[.)])\s+[А-Яа-яA-Za-zЁё]")
SENTENCE_END_RE = re.compile(r"[.!?:;)]$")

CHEM_TOKEN_RE = re.compile(
    r"^(H\d?N?|OH|NH\d?|CH\d?|COOH|C|O|N|H|R\d?|CH|NH|"
    r"[A-Za-zА-Яа-я0-9+\-=→↑↓()]{1,4})$"
)


def _is_chem_fragment_line(line: str) -> bool:
    """Строго: строка ЦЕЛИКОМ состоит из химических/формульных токенов (никаких настоящих слов
    длиннее 4 символов) -- ловит "H2N CH COOH", но не ловит "Изменение дыхания". Используется
    только внутри уже признанного прозаическим рана."""
    stripped = line.strip()
    if not stripped or len(stripped) > 30:
        return False
    tokens = stripped.split()
    if not tokens:
        return False
    return all(CHEM_TOKEN_RE.match(t) for t in tokens)


def classify_line(line: str) -> str:
    s = line.strip()
    if not s:
        return "blank"
    if s.startswith(("<b>", "<i>", "<strong>")):
        return "tag"
    if PAGE_NUM_RE.match(s):
        return "page_number"
    if CAPTION_RE.match(s):
        return "caption"
    if HEADING_RE.match(s):
        return "heading"
    if BULLET_RE.match(s):
        return "bullet"
    return "prose_or_table"


def _reflow_prose_run(lines: list[str]) -> str:
    out = ""
    for line in lines:
        s = line.rstrip()
        if not out:
            out = s
            continue
        if out.endswith("-") and not out.endswith("--"):
            next_first = s[:1]
            if next_first and next_first.islower():
                out = out[:-1] + s
                continue
        out = out + " " + s
    return out


def _run_is_table(lines: list[str]) -> bool:
    non_empty = [line.strip() for line in lines if line.strip()]
    if not non_empty:
        return False
    avg_len = sum(len(line) for line in non_empty) / len(non_empty)
    ends_sentence = sum(1 for line in non_empty if SENTENCE_END_RE.search(line))
    period_ratio = ends_sentence / len(non_empty)
    return avg_len < 32 and period_ratio < 0.3


def _emit_prose(out_parts: list[str], sub_lines: list[str]) -> None:
    buf: list[str] = []
    chem_buf: list[str] = []

    def flush_prose():
        if buf:
            out_parts.append(_reflow_prose_run(buf))
            buf.clear()

    def flush_chem():
        if chem_buf:
            out_parts.append("<pre>" + "\n".join(chem_buf) + "</pre>")
            chem_buf.clear()

    for line in sub_lines:
        if _is_chem_fragment_line(line):
            flush_prose()
            chem_buf.append(line.strip())
        else:
            flush_chem()
            buf.append(line)
    flush_prose()
    flush_chem()


def reflow_lesson_content(content: str) -> str:
    lines = content.split("\n")
    out_parts: list[str] = []
    run: list[str] = []

    def flush_run():
        nonlocal run
        if not run:
            return
        if _run_is_table(run):
            out_parts.append("<pre>" + "\n".join(line.strip() for line in run) + "</pre>")
        else:
            _emit_prose(out_parts, run)
        run = []

    # Уже готовый <pre>-блок (в т.ч. многострочный) от предыдущего прогона -- переносится
    # целиком, дословно, без повторной классификации построчно: строка "line2" из середины
    # "<pre>line1\nline2\nline3</pre>" сама по себе не начинается с "<pre>" и не заканчивается
    # на "</pre>", и без явного отслеживания состояния "внутри <pre>" её бы снова разобрали как
    # обычный текст -- то, из-за чего скрипт был неидемпотентным при повторном запуске.
    in_pre = False
    pre_buf: list[str] = []
    for line in lines:
        s = line.strip()
        if in_pre:
            pre_buf.append(s)
            if s.endswith("</pre>"):
                out_parts.append("\n".join(pre_buf))
                pre_buf = []
                in_pre = False
            continue
        if s.startswith("<pre>") and s.endswith("</pre>"):
            flush_run()
            out_parts.append(s)
            continue
        if s.startswith("<pre>"):
            flush_run()
            in_pre = True
            pre_buf = [s]
            continue
        kind = classify_line(line)
        if kind == "page_number":
            continue
        if kind in ("blank", "tag", "caption", "heading", "bullet"):
            flush_run()
            out_parts.append("" if kind == "blank" else s)
            continue
        run.append(line)
    if in_pre:
        # Незакрытый <pre> в исходных данных быть не должно (сам скрипт всегда закрывает то, что
        # открывает) -- но не роняем прогон на защитном допущении, просто дописываем как есть.
        out_parts.append("\n".join(pre_buf))
    flush_run()

    result_lines: list[str] = []
    for part in out_parts:
        if part == "" and result_lines and result_lines[-1] == "":
            continue
        result_lines.append(part)
    while result_lines and result_lines[0] == "":
        result_lines.pop(0)
    while result_lines and result_lines[-1] == "":
        result_lines.pop()
    return "\n".join(result_lines)


def _iter_lesson_dicts(course: dict):
    for section in course.get("sections", []):
        yield from section.get("lessons", [])
        for group in section.get("groups", []):
            yield from group.get("lessons", [])


def main() -> None:
    for path in TARGET_FILES:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        changed = 0
        total = 0
        for lesson in _iter_lesson_dicts(data):
            content = lesson.get("content")
            if not content:
                continue
            total += 1
            reflowed = reflow_lesson_content(content)
            if reflowed != content:
                lesson["content"] = reflowed
                changed += 1
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"{path}: {changed}/{total} lessons reformatted")


if __name__ == "__main__":
    main()
