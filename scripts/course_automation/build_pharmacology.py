"""Build the complete VMEDA pharmacology subject from supplied materials."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from scripts.course_automation.build_biochemistry import (
    chunks, docx_text, lesson, multiple_choice_lessons, numbered_lessons, page_lessons, pdf_pages,
)


def ocr_lessons(repo: Path, filename: str, prefix: str, label: str, with_media: bool = False) -> list[dict]:
    records = json.loads((repo / ".course-automation" / "pharmacology" / "extracted" / f"{filename}.ocr.json").read_text(encoding="utf-8"))
    result = []
    for record in records:
        text = record["text"]
        if len(text) < 25 and not (with_media and record.get("media")):
            continue
        if len(text) < 25:
            text = "Содержимое таблицы представлено на исходном изображении; автоматическое распознавание текста недостаточно надёжно."
        parts = chunks(text)
        for part, body in enumerate(parts, 1):
            media = None
            if with_media and part == 1 and record.get("media"):
                media = [{"path": record["media"], "caption": f"Таблица из источника, стр. {record['page']}"}]
            result.append(lesson(f"{prefix}_p{record['page']}_{part}", f"{label}: стр. {record['page']}" + (f", часть {part}" if len(parts) > 1 else ""), body, f"{filename}, стр. {record['page']}", media))
    return result


def document_chunks(prefix: str, path: Path, title: str) -> list[dict]:
    return [lesson(f"{prefix}_{i}", f"{title}, часть {i}", body, path.name)
            for i, body in enumerate(chunks(docx_text(path)), 1)]


def main(repo: Path) -> None:
    workspace = repo / ".course-automation" / "pharmacology"
    sources = workspace / "sources"
    sections = []
    sections.append({"id": "general", "title": "Общая фармакология", "lessons": page_lessons("general", pdf_pages(sources / "Общая Фармакология.pdf"), "Общая Фармакология.pdf", "Общая фармакология")})
    sections.append({"id": "theory", "title": "Полный курс — теория", "lessons": document_chunks("theory", sources / "теория фарма-1.docx", "Теория фармакологии")})
    sections.append({"id": "theory_answers", "title": "Теория с ответами", "lessons": page_lessons("answers", pdf_pages(sources / "ФЛ ТЕОРИЯ (ответы)-1.pdf"), "ФЛ ТЕОРИЯ (ответы)-1.pdf", "Теория с ответами")})
    sections.append({"id": "lesson_14", "title": "Занятие №14", "lessons": ocr_lessons(repo, "Занятие Nº 14.pdf", "lesson14", "Занятие №14")})
    sections.append({"id": "tables", "title": "Атлас фармакологических таблиц", "lessons": ocr_lessons(repo, "Фарма все таблицы.pdf", "table", "Фармакологическая таблица", True)})
    sections.append({"id": "practicum", "title": "Практикум", "lessons": ocr_lessons(repo, "Фармакология практикум.pdf", "practice", "Практикум")})
    sections.append({"id": "recipes", "title": "Рецептура", "lessons": document_chunks("recipe", sources / "Все Рецепты.docx", "Рецепт") + page_lessons("recipe_fix", pdf_pages(sources / "РЕЦЕПТЫ С ИСПРАВЛЕНИЯМИ.pdf"), "РЕЦЕПТЫ С ИСПРАВЛЕНИЯМИ.pdf", "Исправленная рецептура")})

    controls = [
        ("control_1", "Контрольная работа №1", "фарма к кр 1.docx", "docx"),
        ("control_3", "Контрольная работа №3", "Кр3 фарма.pdf", "pdf"),
        ("control_3_extra", "Контрольная работа №3 — дополнительный материал", "ФАРМАКОЛОГИЯ КР 3.pdf", "pdf"),
        ("control_4", "Контрольная работа №4", "кр4.pdf", "pdf"),
        ("control_5", "Контрольная работа №5 — теория", "Фарма.Теория кр 5.pdf", "pdf"),
        ("control_5_tests", "Контрольная работа №5 — тесты", "рк5т.docx", "docx_test"),
        ("control_6", "Контрольная работа №6", "кр6.pdf", "pdf"),
    ]
    for sid, title, filename, kind in controls:
        path = sources / filename
        if kind == "pdf": lessons = page_lessons(sid, pdf_pages(path), filename, title)
        elif kind == "docx_test": lessons = multiple_choice_lessons(sid, path, "Задание")
        else: lessons = numbered_lessons(sid, docx_text(path), filename, "Вопрос")
        sections.append({"id": sid, "title": title, "lessons": lessons})

    sections.append({"id": "credit_tickets", "title": "Зачёт — билеты", "lessons": page_lessons("credit", pdf_pages(sources / "ЗАЧЕТ_ФАРМА_билеты_с_небольшой_редакцией.pdf"), "ЗАЧЕТ_ФАРМА_билеты_с_небольшой_редакцией.pdf", "Зачётный билет") + document_chunks("credit_11_20", sources / "зачет фарма билеты 11-20.docx", "Билеты 11–20")})
    sections.append({"id": "credit_tests", "title": "Зачёт — тесты", "lessons": multiple_choice_lessons("credit_test", sources / "ФАРМА ЗАЧЕТ ТЕСТЫ.docx", "Зачётный тест")})
    sections.append({"id": "tickets", "title": "Билеты по фармакологии", "lessons": document_chunks("ticket", sources / "билеты по фарме.docx", "Билет")})
    sections.append({"id": "ticket_practice", "title": "Практическая часть билетов — ответы", "lessons": document_chunks("ticket_pr", sources / "ФЛ ПРАКТИКА ОТВЕТЫ (билеты).docx", "Практический билет")})

    test_sources = [
        ("all_tests", "Все тесты", "farma_testy_vse.docx", "docx"),
        ("fl_tests", "Тесты ФЛ", "ФЛ ТЕСТЫ.pdf", "pdf"),
        ("ticket_tests", "Тесты по билетам", "тесты по билетам фарма-2.pdf", "pdf"),
        ("tests_answers", "Тесты с ответами", "тесты фармакология+ ответы .pdf", "pdf"),
    ]
    for sid, title, filename, kind in test_sources:
        path = sources / filename
        lessons = multiple_choice_lessons(sid, path, "Тест") if kind == "docx" else page_lessons(sid, pdf_pages(path), filename, title)
        sections.append({"id": sid, "title": title, "lessons": lessons})

    reference_files = [
        "Учебник_ФЛ_Виноградов_Каткова_2016.pdf", "Kharkevich_D_A_-_Farmakologia_Uchebnik_12-e_izdanie.pdf",
        "Фарма Аляутдин (синяя книга).pdf", "МегаСлобж_compressed.pdf", "Фармакология на ладонях (2).pdf",
        "29d9ccd763f5b9416427b5caae678382.pdf", "c5db0f9b4e6e06d1fde6854b15adf12e.pdf", "ФАРМА2.pdf",
    ]
    reference_lessons = []
    for idx, filename in enumerate(reference_files, 1):
        pages = pdf_pages(sources / filename)
        reference_lessons += page_lessons(f"ref{idx}", pages[:10], filename, f"Навигация: {Path(filename).stem}")
    sections.append({"id": "references", "title": "Учебники и дополнительные материалы", "lessons": reference_lessons})

    course = {"id": "pharmacology", "course": 2, "title": "Фармакология", "emoji": "💊", "description": "Полный курс ВМедА: теория, таблицы препаратов, практикум, рецептура, контрольные работы, тесты, зачёт и билеты. Дозировки и клинические рекомендации сверяйте с актуальными официальными инструкциями.", "sections": sections}
    (repo / "generated_courses" / "pharmacology.json").write_text(json.dumps(course, ensure_ascii=False, indent=2), encoding="utf-8")

    originals = [p for p in sources.iterdir() if p.suffix.lower() in {".pdf", ".doc", ".docx"} and not (p.suffix.lower() == ".docx" and (sources / f"{p.stem}.doc").exists())]
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in originals}
    groups = {}
    for name, digest in hashes.items(): groups.setdefault(digest, []).append(name)
    used = {src.split(",")[0] for section in sections for item in section["lessons"] for src in item.get("sources", [])}
    files = []
    for p in sorted(originals, key=lambda x: x.name.casefold()):
        dup_group = groups[hashes[p.name]]
        canonical = sorted(dup_group, key=lambda name: ("(2)" in name, len(name), name.casefold()))[0]
        duplicate = len(dup_group) > 1 and p.name != canonical
        derived_name = f"{p.stem}.docx" if p.suffix.lower() == ".doc" else None
        is_used = p.name in used or (derived_name in used if derived_name else False)
        files.append({"file": p.name, "sha256": hashes[p.name], "status": "duplicate" if duplicate else "processed", "same_as": canonical if duplicate else None, "coverage": "duplicate" if duplicate else ("course" if is_used else "reference")})
    report = {"subject": "Фармакология", "source_count": len(originals), "section_count": len(sections), "lesson_count": sum(len(s["lessons"]) for s in sections), "media_count": sum(len(l.get("media", [])) for s in sections for l in s["lessons"]), "files": files}
    (workspace / "coverage_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("source_count", "section_count", "lesson_count", "media_count")}, ensure_ascii=False))


if __name__ == "__main__": main(Path(sys.argv[1]).resolve())
