# -*- coding: utf-8 -*-
"""Регрессии стандарта качества VMEDA AI: формат, предметный профиль и защита от бедных ответов."""
import json

from ai import prompts, validator
from ai.service import DETAILED_MAX_TOKENS, QUICK_MAX_TOKENS
from ai.task import TaskRepresentation
from ai.vision_parser import _parse_json_response


def test_anatomy_profile_requires_latin_and_full_nerve_structure():
    system = prompts.system_prompt_for("anatomy")
    assert "латинском" in system
    assert "корешки" in system
    assert "ход" in system
    assert "область иннервации" in system
    assert "Перед отправкой молча проверь" in system


def test_original_user_format_requirements_survive_parser_paraphrase():
    task = TaskRepresentation(
        subject="anatomy",
        type="theory",
        question="Чем образовано шейное сплетение?",
        raw_text="Шейное сплетение чем образовано? Подробно. С анатомическими терминами на латыни",
    )
    prompt = task.to_prompt_text()
    assert "Исходная формулировка пользователя" in prompt
    assert "Подробно" in prompt
    assert "на латыни" in prompt


def test_cache_fingerprint_separates_subject_and_requested_depth():
    base = TaskRepresentation(
        subject="anatomy", type="theory", question="Расскажи о сплетении",
        raw_text="Расскажи о сплетении кратко",
    )
    detailed = TaskRepresentation(
        subject="anatomy", type="theory", question="Расскажи о сплетении",
        raw_text="Расскажи о сплетении подробно с терминами на латыни",
    )
    physiology = TaskRepresentation(
        subject="physiology", type="theory", question="Расскажи о сплетении",
        raw_text="Расскажи о сплетении кратко",
    )
    assert base.fingerprint() != detailed.fingerprint()
    assert base.fingerprint() != physiology.fingerprint()


def test_quality_gate_repairs_short_detailed_theory_but_not_short_request():
    detailed = TaskRepresentation(
        subject="anatomy", type="theory", question="Шейное сплетение",
        raw_text="Шейное сплетение. Подробно, с латинскими терминами",
    )
    assert validator.needs_expansion(detailed, "Образовано передними ветвями C1–C4.")

    short = TaskRepresentation(
        subject="anatomy", type="theory", question="Шейное сплетение",
        raw_text="Кратко: чем образовано шейное сплетение?",
    )
    assert not validator.needs_expansion(short, "Образовано передними ветвями C1–C4.")


def test_parser_accepts_every_miniapp_medical_subject():
    for subject in (
        "biology", "physics", "chemistry", "anatomy", "histology", "latin",
        "physiology", "operative_surgery", "biochemistry", "pharmacology", "law",
    ):
        task = _parse_json_response(json.dumps({
            "subject": subject,
            "type": "theory",
            "complexity": "simple",
            "question": "Вопрос",
            "options": [],
            "values": {},
            "units": {},
            "subquestions": [],
            "confidence": 1,
            "raw_text": "Вопрос",
        }))
        assert task.subject == subject


def test_answer_budgets_allow_full_exam_ready_response():
    assert QUICK_MAX_TOKENS >= 1800
    assert DETAILED_MAX_TOKENS >= 3200
