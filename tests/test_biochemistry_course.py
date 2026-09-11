# -*- coding: utf-8 -*-
import asyncio
import html
import json
import re
from pathlib import Path

from docx import Document

from _bootstrap import tb
from scripts.course_automation.schema import validate_course


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u00a0", " ")).strip()


async def main():
    root = Path(__file__).resolve().parents[1]
    course = json.loads((root / "generated_courses" / "biochemistry.json").read_text(encoding="utf-8"))
    report_dir = root / "generated_reports" / "biochemistry"
    report = json.loads((report_dir / "coverage_report.json").read_text(encoding="utf-8"))
    manifest = json.loads((report_dir / "source_manifest.json").read_text(encoding="utf-8"))
    extraction = json.loads((report_dir / "extraction_report.json").read_text(encoding="utf-8"))
    knowledge = json.loads((root / "generated_knowledge" / "biochemistry_ai.json").read_text(encoding="utf-8"))
    source_path = root / manifest["sources"][0]["stored_path"]

    assert validate_course(course) == []
    assert course["course"] == 2 and course["show_sources"] is False
    assert {section["id"] for section in course["sections"]} == {
        "guide", "foundations", "metabolism", "regulation", "clinical", "reference",
    }
    assert all("groups" in section and section["groups"] for section in course["sections"])
    groups = {
        group["id"]: group
        for section in course["sections"]
        for group in section["groups"]
    }
    assert {f"class_{number}" for number in range(1, 20)} <= set(groups)
    assert {"about", "contents", "reference_20", "reference_21"} <= set(groups)

    lessons = [
        lesson
        for section in course["sections"]
        for group in section["groups"]
        for lesson in group["lessons"]
    ]
    assert len(lessons) == report["lesson_count"] >= 280
    assert all(len(lesson["content"]) <= 3500 for lesson in lessons)
    assert all(
        len(page) <= 3500
        for lesson in lessons
        for page in lesson.get("content_pages", [lesson["content"]])
    )
    assert len({lesson["id"] for lesson in lessons}) == len(lessons)
    assert not any(lesson["title"] in {"Ходы определения", "Контроль к допуску"} for lesson in lessons)
    controls = [lesson for lesson in lessons if lesson.get("question_count")]
    assert len(controls) == 13
    assert sum(lesson["question_count"] for lesson in controls) == 107
    assert all(lesson["title"].endswith(f"{lesson['question_count']} вопросов") for lesson in controls)
    assert report["source_exclusive"] is True
    assert report["practical_class_count"] == 19
    assert report["source_nonempty_paragraphs"] == report["mapped_nonempty_paragraphs"] == 2120
    assert report["verbatim_coverage_percent"] == 100
    assert report["media_count"] == 0
    assert extraction["readable"] is True and extraction["failures"] == []
    assert extraction["tables"] == extraction["embedded_media"] == 0
    assert source_path.is_file() and manifest["sources"][0]["sha256"] == (
        "3e756a1002fc3b44a519abba42f5fa949bf02f86f0f80d30f9aadc71c903dd73"
    )

    # Every non-empty DOCX paragraph survives verbatim after harmless whitespace normalization.
    # Titles shortened for Telegram buttons remain complete inside lesson content.
    rendered = _norm("\n".join(
        html.unescape(re.sub(r"<[^>]+>", "", page))
        for lesson in lessons
        for page in lesson.get("content_pages", [lesson["content"]])
    ))
    source_paragraphs = [_norm(p.text) for p in Document(source_path).paragraphs if p.text.strip()]
    assert len(source_paragraphs) == 2120
    assert all(paragraph in rendered for paragraph in source_paragraphs)
    assert "Пируватдегидрогеназный комплекс" in rendered
    assert "Приложение. Цифры, которые спрашивают" in rendered
    course_index = next(i for i, item in enumerate(tb.DYNAMIC_COURSES) if item["id"] == "biochemistry")
    assert not tb.dynamic_course_under_maintenance("biochemistry")

    # Bot navigation: six compact top-level blocks, then 19 class groups, paginated lesson
    # lists and previous/next controls inside each class.
    course_callbacks = [
        button.callback_data
        for row in tb.get_dynamic_course_keyboard(course_index).inline_keyboard
        for button in row
        if button.callback_data
    ]
    assert all(f"dyn_s:{course_index}:{section_index}" in course_callbacks for section_index in range(6))
    foundations_callbacks = [
        button.callback_data
        for row in tb.get_dynamic_section_keyboard(course_index, 1).inline_keyboard
        for button in row
        if button.callback_data
    ]
    assert all(f"dyn_g:{course_index}:1:{group_index}:0" in foundations_callbacks for group_index in range(6))
    class_14_keyboard = tb.dynamic_course_handlers.get_dynamic_group_keyboard(course_index, 3, 3, 0)
    class_14_callbacks = [
        button.callback_data
        for row in class_14_keyboard.inline_keyboard
        for button in row
        if button.callback_data
    ]
    assert sum(value.startswith(f"dyn_gl:{course_index}:3:3:") for value in class_14_callbacks) == 8
    assert f"dyn_g:{course_index}:3:3:1" in class_14_callbacks
    assert "noop" in class_14_callbacks
    lesson_rows = [
        row for row in class_14_keyboard.inline_keyboard
        if row and row[0].callback_data.startswith(f"dyn_gl:{course_index}:3:3:")
    ]
    assert len(lesson_rows) == 8 and all(len(row) == 1 for row in lesson_rows)
    class_1_keyboard = tb.dynamic_course_handlers.get_dynamic_group_keyboard(course_index, 1, 0, 0)
    class_1_labels = [row[0].text for row in class_1_keyboard.inline_keyboard[:8]]
    assert class_1_labels[:4] == [
        "Обзор занятия",
        "Допуск к занятию",
        "Опыт · Биуретовая реакция",
        "Опыт · Нингидриновая реакция",
    ]
    assert all(not label.startswith("Ходы определения ·") for label in class_1_labels)
    class_1_second_page = tb.dynamic_course_handlers.get_dynamic_group_keyboard(course_index, 1, 0, 1)
    assert any(
        button.text == "Контроль · 6 вопросов"
        for row in class_1_second_page.inline_keyboard
        for button in row
    )
    first_lesson_callbacks = [
        button.callback_data
        for row in tb.dynamic_course_handlers.get_dynamic_group_lesson_keyboard(course_index, 3, 3, 0).inline_keyboard
        for button in row
        if button.callback_data
    ]
    assert f"dyn_gl:{course_index}:3:3:1" in first_lesson_callbacks
    assert f"dyn_gl:{course_index}:3:3:-1" not in first_lesson_callbacks

    class_17 = groups["class_17"]
    control_index = next(i for i, lesson in enumerate(class_17["lessons"]) if lesson.get("question_count"))
    assert len(class_17["lessons"][control_index]["content_pages"]) > 1
    control_keyboard = tb.dynamic_course_handlers.get_dynamic_group_lesson_keyboard(
        course_index, 4, 2, control_index, 0,
    )
    control_callbacks = [
        button.callback_data
        for row in control_keyboard.inline_keyboard
        for button in row
        if button.callback_data
    ]
    assert "noop" in control_callbacks
    assert f"dyn_glp:{course_index}:4:2:{control_index}:1" in control_callbacks
    assert all(len(row) <= 4 for row in control_keyboard.inline_keyboard)

    entries = knowledge["entries"]
    assert knowledge["visibility"] == "ai_only" and len(entries) >= 450
    assert knowledge["quality"]["source_exclusive"] is True
    assert all(entry["subject"] == "биохимия" for entry in entries)
    assert len([entry for entry in tb.ai_rag._index if entry["subject"] == "биохимия"]) == len(entries)
    snippets, usage = await tb.ai_rag.search_for_task(
        tb.TaskRepresentation(raw_text="состав пируватдегидрогеназного комплекса и его коферменты"),
        subject_filter="биохимия",
    )
    assert usage["input_tokens"] == 0
    assert snippets and all(item["subject"] == "биохимия" for item in snippets)
    assert any("пируват" in item["text"].casefold() and "кофермент" in item["text"].casefold() for item in snippets)
    print("BIOCHEMISTRY PRACTICUM COURSE: OK")


if __name__ == "__main__":
    asyncio.run(main())
