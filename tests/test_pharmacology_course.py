# -*- coding: utf-8 -*-
import asyncio
import json
from pathlib import Path

from _bootstrap import tb
from scripts.course_automation.schema import validate_course


async def main():
    root = Path(__file__).resolve().parents[1]
    course = json.loads((root / "generated_courses" / "pharmacology.json").read_text(encoding="utf-8"))
    knowledge = json.loads((root / "generated_knowledge" / "pharmacology_ai.json").read_text(encoding="utf-8"))
    report = json.loads((root / ".course-automation" / "pharmacology" / "coverage_report.json").read_text(encoding="utf-8"))
    assert validate_course(course) == [] and course["course"] == 2
    sections = {section["id"]: section for section in course["sections"]}
    assert list(sections) == ["course", "controls", "credit", "exam"]
    assert course["ai_mode"] == "pharmacology" and course["show_sources"] is False
    groups = {group["id"]: group for section in course["sections"] for group in section["groups"]}
    assert {"foundations", "course_theory", "drug_groups", "drug_comparison", "course_practice", "prescription", "control_one", "control_three", "control_four", "control_five", "control_six", "credit_questions", "credit_testing", "exam_theory", "exam_practice", "exam_tests"} == set(groups)
    assert len(groups["drug_comparison"]["lessons"]) >= 455
    assert len({m["path"] for l in groups["drug_comparison"]["lessons"] for m in l.get("media", [])}) == 455
    assert len(groups["exam_tests"]["lessons"]) >= 400
    assert report["source_count"] == 34
    assert sum(f["status"] == "duplicate" for f in report["files"]) == 2
    assert all(f["coverage"] in {"course", "reference", "duplicate"} for f in report["files"])
    assert len(knowledge["entries"]) >= 2000
    assert len([e for e in tb.ai_rag._index if e["subject"] == "фармакология"]) == len(knowledge["entries"])
    snippets, usage = await tb.ai_rag.search_for_task(tb.TaskRepresentation(raw_text="фармакокинетика биодоступность период полувыведения"), subject_filter="фармакология")
    assert usage["input_tokens"] == 0 and snippets
    assert all(item["subject"] == "фармакология" for item in snippets)

    course_index = next(i for i, item in enumerate(tb.DYNAMIC_COURSES) if item["id"] == "pharmacology")
    labels = [button.text for row in tb.get_dynamic_course_keyboard(course_index).inline_keyboard for button in row]
    assert labels[:5] == ["📚 КУРС", "📝 КОНТРОЛЬНЫЕ", "✅ ЗАЧЁТ", "🎓 ЭКЗАМЕН", "🤖 VMedA AI по предмету"]
    assert not any(".pdf" in label.lower() or ".doc" in label.lower() for label in labels)
    from handlers import dynamic_courses as dc
    first_page = dc.get_dynamic_group_keyboard(course_index, 0, 3, 0)
    first_callbacks = [button.callback_data for row in first_page.inline_keyboard for button in row]
    assert len([cb for cb in first_callbacks if cb and cb.startswith("dyn_gl:")]) == dc.LESSONS_PER_PAGE
    assert any(cb == f"dyn_g:{course_index}:0:3:1" for cb in first_callbacks)
    print("PHARMACOLOGY COURSE + AI: OK")


if __name__ == "__main__": asyncio.run(main())
