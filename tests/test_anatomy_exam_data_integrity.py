# -*- coding: utf-8 -*-
"""Standalone integrity checks for the anatomy exam bank and explanations."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "anatomy_exam_test.json"
EXPLANATIONS_PATH = ROOT / "anatomy_explanations_draft.json"


def main() -> None:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    questions = [question for part in data["parts"] for question in part["questions"]]
    by_num = {question["num"]: question for question in questions}

    assert len(questions) == 1040
    assert len(by_num) == 1040
    assert set(by_num) == set(range(1, 1041))

    records: set[tuple] = set()
    for question in questions:
        number = question["num"]
        options = question["options"]
        assert question["question"].strip(), number
        assert 4 <= len(options) <= 5, number
        assert all(str(value).strip() for value in options.values()), number
        assert question["correct"] in options, number
        assert len(set(options.values())) == len(options), number
        assert not any(re.search(r"\d\s*-$", str(value)) for value in options.values()), number

        record = (
            question["question"].strip().casefold(),
            tuple((key, str(value).strip().casefold()) for key, value in options.items()),
        )
        assert record not in records, f"duplicate question {number}"
        records.add(record)

    expected = {
        50: ("г", "к концу 1 года жизни"),
        53: ("в", "3-5 позвонков"),
        72: ("в", "передний"),
        135: ("в", "12,5-13 см"),
        138: ("б", "25-27 см"),
        139: ("б", "10,5-11 см"),
        367: ("б", "во внутреннюю яремную вену"),
        390: ("а", "красный костный мозг и тимус"),
        480: ("а", "поперечная мышца живота"),
        491: ("б", "глазной, верхнечелюстной и нижнечелюстной нервы"),
        494: ("б", "все внутренние мышцы гортани, кроме перстнещитовидной"),
        517: ("б", "капилляры"),
        553: ("д", "верно а и б"),
        565: ("а", "межпозвоночный диск"),
        592: ("в", "27-29 см"),
        593: ("г", "30-31 см"),
        595: ("г", "20 см"),
        636: ("б", "поперечной фасцией"),
        670: ("в", "mm. flexor hallucis brevis et abductor hallucis"),
        730: ("г", "эпителий средней кишки"),
        786: ("г", "медиастинальная плевра"),
        823: ("г", "внутренняя запирательная мышца"),
        843: ("в", "сверху вниз, справа налево и сзади наперёд"),
        978: ("г", "двигательные ядра передних рогов спинного мозга"),
        1013: ("в", "мышцы, поднимающие ребра"),
        1040: ("г", "ампулы полукружных протоков"),
    }
    for number, (letter, answer) in expected.items():
        assert by_num[number]["correct"] == letter, number
        assert by_num[number]["options"][letter] == answer, number

    explanations_data = json.loads(EXPLANATIONS_PATH.read_text(encoding="utf-8"))
    explanations = explanations_data["explanations"]
    assert explanations_data["total_questions"] == 1040
    assert explanations_data["prepared_range"] == [1, 1040]
    assert explanations_data["source_verification"] == "flagged_questions_completed"
    assert explanations_data["blocking_questions"] == {}
    assert set(explanations) == {str(number) for number in range(1, 1041)}
    assert all(str(explanation).strip() for explanation in explanations.values())

    print("anatomy exam integrity: 1040 questions and 1040 explanations: OK")


if __name__ == "__main__":
    main()
