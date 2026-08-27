# -*- coding: utf-8 -*-
import json
from pathlib import Path

from _bootstrap import tb
from scripts.course_automation.schema import validate_course


def main():
    root = Path(__file__).resolve().parents[1]
    course = json.loads((root / "generated_courses" / "biochemistry.json").read_text(encoding="utf-8"))
    report = json.loads((root / ".course-automation" / "biochemistry" / "coverage_report.json").read_text(encoding="utf-8"))

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
    print("BIOCHEMISTRY COURSE: OK")


if __name__ == "__main__":
    main()
