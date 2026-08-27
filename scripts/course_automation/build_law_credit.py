"""Build the law credit question bank without paraphrasing supplied answers."""
import hashlib
import html
import json
import re
from pathlib import Path

from pypdf import PdfReader

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = REPO_ROOT / ".course-automation" / "law"
SOURCE = WORKSPACE / "sources" / "ОТВЕТЫ ЗАЧЕТ ПВ.pdf"
DUPLICATE = WORKSPACE / "sources" / "право1.pdf"
SPEC = WORKSPACE / "course_spec.json"
ASSET_DIR = REPO_ROOT / "generated_assets" / "law"

IMAGE_QUESTION_MAP = {
    2: [4], 3: [7, 8], 4: [9], 5: [11], 9: [20], 11: [23], 12: [25],
    13: [27, 27], 14: [28], 15: [30], 17: [35], 22: [48],
    28: [63, 63, 63], 35: [75, 75], 39: [81],
}

SECTION_RANGES = [
    ("theory", "Теория государства и права", 1, 14),
    ("constitutional", "Конституционное право", 15, 24),
    ("civil", "Гражданское право", 25, 36),
    ("family", "Семейное право", 37, 41),
    ("labor", "Трудовое право", 42, 61),
    ("administrative", "Административное право", 62, 63),
    ("criminal", "Уголовное право", 64, 69),
    ("medical", "Медицинское право", 70, 74),
    ("military", "Военная служба", 75, 76),
    ("international", "Международное право", 77, 80),
    ("social_norms", "Социальные нормы", 81, 81),
]


def normalize(value: str) -> str:
    value = value.replace("\u00ad", "").replace("\xa0", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def split_content(value: str, limit: int = 3000) -> list[str]:
    paragraphs = [part.strip() for part in value.split("\n") if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        pieces = [paragraph[i:i + limit] for i in range(0, len(paragraph), limit)]
        for piece in pieces:
            candidate = f"{current}\n{piece}".strip()
            if current and len(candidate) > limit:
                chunks.append(current)
                current = piece
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks


def extract_questions() -> list[dict]:
    pages = [normalize(page.extract_text() or "") for page in PdfReader(SOURCE).pages]
    full_text = "\n".join(f"\n[Страница {index}]\n{text}" for index, text in enumerate(pages, 1))
    headings = []
    cursor = 0
    for number in range(1, 82):
        match = re.search(rf"(?m)^\s*{number}\.\s+([^\n]{{8,260}})", full_text[cursor:])
        if not match:
            raise ValueError(f"Question {number} was not found in sequence")
        start = cursor + match.start()
        headings.append((number, start, normalize(match.group(1))))
        cursor += match.end()
    questions = []
    for index, (number, start, heading) in enumerate(headings):
        end = headings[index + 1][1] if index + 1 < len(headings) else len(full_text)
        block = full_text[start:end]
        heading_match = re.match(rf"\s*{number}\.\s*(.+?\.)\s*", block, re.DOTALL)
        if heading_match:
            heading = normalize(heading_match.group(1)).replace("\n", " ")
            answer_start = heading_match.end()
        else:
            answer_start = block.find("\n") + 1
        answer = normalize(re.sub(r"\[Страница \d+\]", "", block[answer_start:]))
        preceding_pages = [int(value) for value in re.findall(r"\[Страница (\d+)\]", full_text[:start])]
        page = preceding_pages[-1] if preceding_pages else 1
        page_numbers = [int(value) for value in re.findall(r"\[Страница (\d+)\]", block)]
        if page_numbers:
            page_end = max(page_numbers)
        else:
            page_end = page
        questions.append({"number": number, "title": heading, "answer": answer, "page": page, "page_end": page_end})
    return questions


def build() -> dict:
    questions = extract_questions()
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    for stale_asset in ASSET_DIR.iterdir():
        if stale_asset.is_file():
            stale_asset.unlink()
    media_by_question: dict[int, list[dict]] = {}
    reader = PdfReader(SOURCE)
    for page_number, question_numbers in IMAGE_QUESTION_MAP.items():
        for image_index, source_image in enumerate(reader.pages[page_number - 1].images, 1):
            question_number = question_numbers[min(image_index - 1, len(question_numbers) - 1)]
            extension = Path(source_image.name).suffix.lower() or ".png"
            target = ASSET_DIR / f"q{question_number}_p{page_number}_{image_index}{extension}"
            target.write_bytes(source_image.data)
            media_by_question.setdefault(question_number, []).append({
                "path": target.relative_to(REPO_ROOT).as_posix(),
                "caption": f"Схема к вопросу {question_number}, стр. {page_number}",
            })
    sections = []
    coverage = []
    for section_id, section_title, first, last in SECTION_RANGES:
        lessons = []
        for question in questions[first - 1:last]:
            answer_chunks = split_content(question["answer"])
            if not answer_chunks and media_by_question.get(question["number"]):
                answer_chunks = ["Ответ представлен на схеме из предоставленного материала."]
            if not answer_chunks:
                raise ValueError(f"Question {question['number']} has neither answer text nor media")
            for part_index, chunk in enumerate(answer_chunks, 1):
                suffix = f"_p{part_index}" if len(answer_chunks) > 1 else ""
                part_title = f" — часть {part_index}" if len(answer_chunks) > 1 else ""
                locator = f"стр. {question['page']}"
                if question["page_end"] > question["page"]:
                    locator += f"–{question['page_end']}"
                lessons.append({
                    "id": f"q{question['number']}{suffix}",
                    "title": f"{question['number']}. {question['title']}{part_title}",
                    "content": "<b>Ответ из материала</b>\n\n" + html.escape(chunk),
                    "sources": [f"{SOURCE.name}, {locator}"],
                    **({"media": media_by_question.get(question["number"], [])}
                       if part_index == 1 and media_by_question.get(question["number"]) else {}),
                })
            coverage.append({
                "question": question["number"],
                "title": question["title"],
                "lessons": len(answer_chunks),
                "source": SOURCE.name,
            })
        sections.append({"id": section_id, "title": section_title, "lessons": lessons})
    course = {
        "id": "law",
        "course": 1,
        "title": "Зачёт по правоведению",
        "emoji": "⚖️",
        "description": (
            "81 вопрос с ответами из предоставленного зачётного материала. "
            "Нормативные сведения сверяйте с действующей редакцией законодательства."
        ),
        "sections": sections,
    }
    SPEC.write_text(json.dumps(course, ensure_ascii=False, indent=2), encoding="utf-8")
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    duplicate_hash = hashlib.sha256(DUPLICATE.read_bytes()).hexdigest() if DUPLICATE.exists() else None
    manifest = {
        "subject": "Правоведение",
        "mode": "credit_only",
        "primary": {"file": SOURCE.name, "sha256": source_hash, "pages": 39},
        "duplicates": ([{"file": DUPLICATE.name, "sha256": duplicate_hash, "same_as": SOURCE.name}]
                       if duplicate_hash == source_hash else []),
        "excluded_from_course": ["22-23Общее.docx — учебный план, пользователь запросил только зачёт"],
    }
    (WORKSPACE / "source_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (WORKSPACE / "coverage_report.json").write_text(
        json.dumps({"questions": coverage, "covered": len(coverage), "expected": 81}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return course


if __name__ == "__main__":
    result = build()
    print(json.dumps({
        "sections": len(result["sections"]),
        "lessons": sum(len(section["lessons"]) for section in result["sections"]),
    }, ensure_ascii=False))
