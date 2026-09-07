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
    # Биохимия v2 (см. commit message) -- раздел сведён только к экзамену/зачёту/тестам, убраны
    # неструктурированные конспект/практикум/введение (источник "сдвинутого" текста с потерей
    # пробелов между словами, реальная жалоба пользователя). original_source_count/lesson_count/
    # media_count ниже описывают ИСТОРИЧЕСКИЙ прогон автоматизации (что было извлечено из PDF
    # изначально), а не текущую живую структуру -- не трогаем их при последующей ручной чистке.
    section_ids = {section["id"] for section in course["sections"]}
    assert section_ids == {"exam", "credit", "tests_and_controls"}
    assert report["original_source_count"] == 15
    assert all(source["included_lessons"] > 0 for source in report["sources"])
    assert report["lesson_count"] >= 1000
    assert report["media_count"] >= 1
    assert any(course["id"] == "biochemistry" for course in tb.DYNAMIC_COURSES)

    def _all_lessons(section: dict) -> list[dict]:
        if "groups" in section:
            return [lesson for group in section["groups"] for lesson in group["lessons"]]
        return section["lessons"]

    assert all(len(lesson["content"]) <= 3500 for section in course["sections"] for lesson in _all_lessons(section))
    sections = {section["id"]: section for section in course["sections"]}
    groups = {
        group["id"]: group
        for section in course["sections"] if "groups" in section
        for group in section["groups"]
    }
    assert len(sections["credit"]["lessons"]) >= 100
    assert len(groups["control_1"]["lessons"]) >= 8
    assert len(groups["control_3"]["lessons"]) >= 8
    assert len(groups["tests"]["lessons"]) >= 1000
    # Та же проверка "нет случайно задвоенных страниц", что раньше стояла на complete_notes
    # (убран целиком) -- credit устроен той же генерацией "одна страница PDF -- один урок" и
    # подвержен тому же классу ошибки.
    assert len({lesson["content"] for lesson in sections["credit"]["lessons"]}) == len(sections["credit"]["lessons"])

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
