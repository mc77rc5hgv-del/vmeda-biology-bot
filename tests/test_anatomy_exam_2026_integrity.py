# -*- coding: utf-8 -*-
"""Standalone, exhaustive checks for the current 1073-question anatomy bank and feedback."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BANK_PATH = ROOT / "anatomy_exam_test_2026.json"
FEEDBACK_PATH = ROOT / "anatomy_exam_feedback_1073.json"
LETTERS = "абвгд"


def main() -> None:
    bank = json.loads(BANK_PATH.read_text(encoding="utf-8"))
    assert bank["bank_version"] == "vmeda_anatomy_2026_1073"
    assert bank["answer_key_origin"] == "expert_derived_from_textbooks_not_official_moodle_key"
    assert bank["total_questions"] == 1073
    assert len(bank["parts"]) == 12
    assert bank["review_required_count"] == 54

    questions = [question for part in bank["parts"] for question in part["questions"]]
    assert [question["num"] for question in questions] == list(range(1, 1074))
    for question in questions:
        assert question["question"].strip(), question["num"]
        assert 3 <= len(question["options"]) <= 5, question["num"]
        assert list(question["options"]) == list(LETTERS[: len(question["options"])]), question["num"]
        assert question["correct"] in question["options"], question["num"]
        assert len(set(question["options"].values())) == len(question["options"]), question["num"]

    feedback = json.loads(FEEDBACK_PATH.read_text(encoding="utf-8"))
    assert feedback["bank_version"] == bank["bank_version"]
    assert feedback["total_questions"] == 1073
    assert feedback["prepared_questions"] == 1073
    assert feedback["complete"] is True
    assert set(feedback["items"]) == {str(number) for number in range(1, 1074)}

    for question in questions:
        item = feedback["items"][str(question["num"])]
        correct_index = LETTERS.index(question["correct"]) + 1
        assert item["question"] == question["question"], question["num"]
        assert item["correct_option"] == correct_index, question["num"]
        assert item["correct_text"] == question["options"][question["correct"]], question["num"]
        assert len(item["correct_explanation"]) >= 80, question["num"]
        expected_wrong = {
            str(index)
            for index in range(1, len(question["options"]) + 1)
            if index != correct_index
        }
        assert set(item["wrong_explanations"]) == expected_wrong, question["num"]
        assert all(len(text) >= 35 for text in item["wrong_explanations"].values()), question["num"]
        assert item["sources"], question["num"]

    print("anatomy 2026 bank + option-aware feedback: 1073/1073 OK")


if __name__ == "__main__":
    main()
