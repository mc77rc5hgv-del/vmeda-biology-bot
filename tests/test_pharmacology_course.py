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
    required = {"theory", "tables", "practicum", "recipes", "control_1", "control_3", "control_4", "control_5", "control_6", "credit_tickets", "credit_tests", "tickets", "ticket_practice"}
    assert required <= sections.keys()
    assert len(sections["tables"]["lessons"]) >= 455
    assert len({m["path"] for l in sections["tables"]["lessons"] for m in l.get("media", [])}) == 455
    assert len(sections["all_tests"]["lessons"]) >= 300
    assert report["source_count"] == 34
    assert sum(f["status"] == "duplicate" for f in report["files"]) == 2
    assert all(f["coverage"] in {"course", "reference", "duplicate"} for f in report["files"])
    assert len(knowledge["entries"]) >= 2000
    assert len([e for e in tb.ai_rag._index if e["subject"] == "фармакология"]) == len(knowledge["entries"])
    snippets, usage = await tb.ai_rag.search_for_task(tb.TaskRepresentation(raw_text="фармакокинетика биодоступность период полувыведения"), subject_filter="фармакология")
    assert usage["input_tokens"] == 0 and snippets
    assert all(item["subject"] == "фармакология" for item in snippets)
    print("PHARMACOLOGY COURSE + AI: OK")


if __name__ == "__main__": asyncio.run(main())
