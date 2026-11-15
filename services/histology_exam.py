"""Shared exam content for the Telegram bot and mini-app."""
import json
import random
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def test_bank() -> dict:
    with (ROOT / "histology_exam_tests.json").open(encoding="utf-8") as stream:
        return json.load(stream)


@lru_cache(maxsize=1)
def test_questions() -> dict:
    return {question["id"]: question for question in test_bank()["questions"]}


@lru_cache(maxsize=1)
def _topic_questions() -> dict[str, list[dict]]:
    groups = defaultdict(list)
    for question in test_questions().values():
        groups[question["module_id"]].append(question)
    return dict(groups)


def test_topics() -> list[dict]:
    groups = _topic_questions()
    return [{**topic, "question_count": len(groups[topic["id"]])} for topic in test_bank()["modules"]]


def start_test(module_id: str | None = None) -> list[dict]:
    if module_id is not None:
        questions = _topic_questions()[module_id]
        return random.sample(questions, len(questions))
    eligible = [q for q in test_questions().values() if q["qa"]["eligible_for_study_scoring"]]
    return random.sample(eligible, test_bank()["exam_rules"]["questions_per_attempt"])


def test_catalog() -> list[dict]:
    return [
        {"id": q["id"], "number": q["number"], "question": q["question"], "module_id": q["module_id"]}
        for q in test_questions().values()
    ]


def public_question(question: dict) -> dict:
    return {key: question[key] for key in ("id", "number", "question", "options")}


def review_answer(question: dict) -> dict:
    return {
        "correct_option": question["correct_option"],
        "source_correct_option": question["source_correct_option"],
        "explanation": question["explanation"],
    }


def exam_grade(correct: int) -> str:
    for band in test_bank()["exam_rules"]["thresholds"]:
        if band["min_correct"] <= correct <= band["max_correct"]:
            return band["grade"]
    raise ValueError("Оценка за пределами экзаменационной шкалы")


@lru_cache(maxsize=1)
def theory_sections() -> list[dict]:
    text = (ROOT / "histology_exam_theory.md").read_text(encoding="utf-8")
    start = text.index('<a id="hist-theory-001">')
    first_section = text.rfind("\n## ", 0, start)
    sections = []
    for block in re.split(r"(?m)^## ", text[first_section:].strip())[1:]:
        section_title, _, content = block.partition("\n")
        questions = []
        for entry in re.split(r'(?m)^<a id="hist-theory-\d{3}"></a>\s*', content)[1:]:
            heading, _, answer = entry.strip().partition("\n")
            match = re.fullmatch(r"### (\d+)\. (.+)", heading)
            if match is None:
                raise ValueError(f"Некорректный заголовок вопроса: {heading}")
            number = int(match[1])
            paragraphs = []
            for paragraph in re.split(r"\n\s*\n", answer.strip()):
                label, _, body = paragraph.removeprefix("**").partition("** ")
                paragraphs.append({"label": label, "text": body})
            questions.append({"number": number, "title": match[2], "paragraphs": paragraphs})
        sections.append({"id": questions[0]["number"], "title": section_title, "questions": questions})
    return sections


def theory_catalog() -> list[dict]:
    return [
        {
            "id": section["id"],
            "title": section["title"],
            "questions": [{"number": q["number"], "title": q["title"]} for q in section["questions"]],
        }
        for section in theory_sections()
    ]


@lru_cache(maxsize=1)
def theory_questions() -> dict:
    return {q["number"]: q for section in theory_sections() for q in section["questions"]}
