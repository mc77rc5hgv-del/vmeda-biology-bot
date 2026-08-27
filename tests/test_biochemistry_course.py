# -*- coding: utf-8 -*-
import asyncio
import json
from pathlib import Path

from _bootstrap import tb
from scripts.course_automation.schema import validate_course


async def main():
    root = Path(__file__).resolve().parents[1]
    course = json.loads((root / "generated_courses" / "biochemistry.json").read_text(encoding="utf-8"))
    report = json.loads((root / ".course-automation" / "biochemistry" / "coverage_report.json").read_text(encoding="utf-8"))
    knowledge = json.loads((root / "generated_knowledge" / "biochemistry_ai.json").read_text(encoding="utf-8"))

    assert validate_course(course) == []
    assert course["course"] == 2
    section_ids = {section["id"] for section in course["sections"]}
    assert {"core_course", "practicum", "control_1", "control_2", "control_3", "credit", "exam_tickets", "exam_questions", "exam_practical"} <= section_ids
    assert report["original_source_count"] == 15
    assert all(source["included_lessons"] > 0 for source in report["sources"])
    assert report["lesson_count"] >= 1000
    assert report["media_count"] >= 1
    assert any(course["id"] == "biochemistry" for course in tb.DYNAMIC_COURSES)
    assert all(len(lesson["content"]) <= 3500 for section in course["sections"] for lesson in section["lessons"])
    sections = {section["id"]: section for section in course["sections"]}
    assert len(sections["introduction"]["lessons"]) <= 10
    assert len(sections["control_1"]["lessons"]) >= 8
    assert len(sections["control_3"]["lessons"]) >= 8
    assert len(sections["tests"]["lessons"]) >= 1000
    assert len({lesson["content"] for lesson in sections["complete_notes"]["lessons"]}) == len(sections["complete_notes"]["lessons"])

    entries = knowledge["entries"]
    assert knowledge["visibility"] == "ai_only" and len(entries) >= 500
    assert all(entry["subject"] == "биохимия" for entry in entries)
    assert len([entry for entry in tb.ai_rag._index if entry["subject"] == "биохимия"]) == len(entries)
    snippets, usage = await tb.ai_rag.search_for_task(
        tb.TaskRepresentation(raw_text="состав пируватдегидрогеназного комплекса и его коферменты"),
        subject_filter="биохимия",
    )
    assert usage["input_tokens"] == 0
    assert snippets and all(item["subject"] == "биохимия" for item in snippets)
    assert any("пируват" in item["text"].casefold() and "кофермент" in item["text"].casefold() for item in snippets)
    print("BIOCHEMISTRY COURSE: OK")


if __name__ == "__main__":
    asyncio.run(main())
