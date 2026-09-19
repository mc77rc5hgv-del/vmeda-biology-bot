"""Compile editorial lessons for local review, never into runtime course/AI paths.

Run: python -m scripts.course_automation.build_pharmacology_draft
The JSON uses the existing bot course schema; it is NOT a complete replacement.
"""
import html
import json
from pathlib import Path

from scripts.course_automation.schema import validate_course

ROOT = Path(__file__).resolve().parents[2]
AUTHORING = ROOT / "course_sources/pharmacology"
OUTPUT = ROOT / ".course-automation/pharmacology-review/draft"
FLOW = ("prepare", "understand", "practice", "recall")
PAGE_LIMIT = 3200  # Leave room for bot title and pagination outside the content.


def validate_lesson(lesson: dict, allowed_numbers: set[int]) -> None:
    if type(lesson.get("number")) is not int or lesson["number"] not in allowed_numbers:
        raise ValueError("Lesson number must exist in the curriculum")
    if lesson.get("id") != f"pharma_class_{lesson['number']:02d}":
        raise ValueError("Stable class ID does not match lesson number")
    if lesson.get("status") != "editorial_draft" or lesson.get("ai_eligible") is not False:
        raise ValueError("This compiler accepts AI-ineligible editorial drafts only")
    if lesson.get("coverage") not in {"partial", "complete"}:
        raise ValueError("Explicit coverage is required")
    if lesson["coverage"] == "partial" and not lesson.get("outstanding"):
        raise ValueError("Partial lesson must identify missing material")
    if not isinstance(lesson.get("title"), str) or not lesson["title"].strip():
        raise ValueError("Lesson title is required")
    refs = lesson.get("source_refs", [])
    source_ids = {ref["id"] for ref in refs}
    if not refs or len(source_ids) != len(refs):
        raise ValueError("Unique source references are required")
    if tuple(s["id"] for s in lesson["sections"]) != FLOW:
        raise ValueError("Exactly four ordered study sections are required")
    for section in lesson["sections"]:
        if not section.get("title") or not section.get("blocks"):
            raise ValueError("Empty navigation sections are not allowed")
        for block in section["blocks"]:
            if not all(isinstance(block.get(k), str) and block[k].strip() for k in ("title", "text")):
                raise ValueError("Each block must contain a title and substantive text")
            if set(block.get("source_ids", [])) - source_ids:
                raise ValueError("Unknown block source reference")


def paginate(blocks: list[dict]) -> list[str]:
    """Keep complete explanations together; refuse oversized blocks, never truncate."""
    pages, current = [], ""
    for block in blocks:
        rendered = f"<b>{html.escape(block['title'])}</b>\n{html.escape(block['text'])}"
        if len(rendered) > PAGE_LIMIT:
            raise ValueError("Editorial block too long: split it at a semantic boundary")
        candidate = current + ("\n\n" if current else "") + rendered
        if len(candidate) > PAGE_LIMIT:
            pages.append(current)
            current = rendered
        else:
            current = candidate
    if current:
        pages.append(current)
    return pages


def compile_draft(lessons: list[dict], curriculum: dict) -> tuple[dict, dict, str]:
    lessons = sorted(lessons, key=lambda item: item["number"])
    allowed = {l["number"] for m in curriculum["modules"] for l in m["lessons"]}
    groups, seen, markdown = [], set(), [
        "# Фармакология — редакционный просмотр",
        "Не опубликовано. Неполный учебный черновик, не официальный ключ кафедры. "
        "Он не заменяет весь практикум и не включён в VMedA AI.",
    ]
    for lesson in lessons:
        validate_lesson(lesson, allowed)
        if lesson["number"] in seen:
            raise ValueError("Duplicate class number")
        seen.add(lesson["number"])
        group = {"id": lesson["id"], "title": f"{lesson['number']}. {lesson['title']}", "lessons": []}
        markdown += [f"## Занятие {lesson['number']}. {lesson['title']}",
                     "### Ещё предстоит проверить и дополнить",
                     "\n".join(f"- {item}" for item in lesson["outstanding"])]
        for section in lesson["sections"]:
            pages = paginate(section["blocks"])
            group["lessons"].append({
                "id": f"{lesson['id']}_{section['id']}", "title": section["title"],
                "content": pages[0], "content_pages": pages,
                "sources": [r.get("file", r.get("url", "")) for r in lesson["source_refs"]],
            })
            markdown.append(f"### {section['title']}")
            for block in section["blocks"]:
                markdown += [f"#### {block['title']}", block["text"]]
        markdown.append("### Источники и границы проверки")
        for ref in lesson["source_refs"]:
            label = ref.get("file", ref.get("url", ""))
            locator = f"; страницы PDF: {', '.join(map(str, ref['pdf_pages']))}" if "pdf_pages" in ref else ""
            markdown.append(f"- {label}{locator}. {ref.get('review', '')}")
        groups.append(group)
    if not groups:
        raise ValueError("No authored lessons found")
    course = {
        "id": "pharmacology", "course": 2, "title": "Фармакология · редакционный черновик",
        "emoji": "💊", "ai_mode": None, "show_sources": True,
        "description": "Неполный материал для локальной редакции. Не публиковать вместо полного курса.",
        "sections": [{"id": "course", "title": "Курс · черновик", "groups": groups}],
    }
    errors = validate_course(course)
    if errors:
        raise ValueError("; ".join(errors))
    report = {
        "publication_ready": False, "ai_eligible": False, "runtime_files_changed": False,
        "authored_classes": sorted(seen), "curriculum_classes": len(allowed),
        "not_authored": sorted(allowed - seen),
        "partial_classes": [l["number"] for l in lessons if l["coverage"] == "partial"],
        "review_required": {str(l["number"]): l["outstanding"] for l in lessons},
        "navigation_items_per_class": 4,
        "self_check_mode": "static_questions_then_explanations_not_interactive_scoring",
    }
    return course, report, "\n\n".join(markdown) + "\n"


def main() -> None:
    curriculum = json.loads((AUTHORING / "curriculum.json").read_text(encoding="utf-8"))
    lessons = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((AUTHORING / "lessons").glob("*.json"))]
    course, report, markdown = compile_draft(lessons, curriculum)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, data in (("course.json", course), ("coverage.json", report)):
        (OUTPUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / "review.md").write_text(markdown, encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
