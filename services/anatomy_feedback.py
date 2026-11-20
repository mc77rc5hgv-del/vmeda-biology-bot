"""Option-aware educational feedback for the anatomy exam bank.

The detailed 2026 bank stores feedback by source question number and by 1-based option
index.  The live bot historically used a different 1040-question ordering and Cyrillic option
letters.  This module deliberately validates question/correct-answer text before using a record
and also builds a content signature index.  A same-number question from another bank therefore
cannot receive an unrelated explanation.
"""

from __future__ import annotations

import re
from typing import Any, Mapping


OPTION_LETTERS = "абвгд"


def _normalize(value: object) -> str:
    text = str(value or "").casefold().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]+", " ", text).strip()


def _correct_text(question: Mapping[str, Any]) -> str:
    correct = str(question.get("correct", ""))
    return str(question.get("options", {}).get(correct, ""))


def feedback_signature(question_text: object, correct_text: object) -> str:
    return f"{_normalize(question_text)}\n{_normalize(correct_text)}"


def build_feedback_signature_index(
    feedback_items: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for record in (feedback_items or {}).values():
        if not isinstance(record, Mapping):
            continue
        signature = feedback_signature(record.get("question"), record.get("correct_text"))
        if signature.strip() and signature not in result:
            result[signature] = record
    return result


def build_legacy_explanation_signature_index(
    parts: list[Mapping[str, Any]],
    explanations: Mapping[str, str],
) -> dict[str, str]:
    """Index old-bank explanations by content, never by a reusable numeric position."""

    result: dict[str, str] = {}
    for part in parts:
        for question in part.get("questions", []):
            if not isinstance(question, Mapping):
                continue
            explanation = str(explanations.get(str(question.get("num")), "")).strip()
            if not explanation:
                continue
            signature = feedback_signature(question.get("question"), _correct_text(question))
            if signature.strip() and signature not in result:
                result[signature] = explanation
    return result


def _matching_record(
    question: Mapping[str, Any],
    feedback_items: Mapping[str, Mapping[str, Any]] | None,
    feedback_by_signature: Mapping[str, Mapping[str, Any]] | None,
) -> Mapping[str, Any] | None:
    expected_signature = feedback_signature(question.get("question"), _correct_text(question))
    direct = (feedback_items or {}).get(str(question.get("num")))
    if isinstance(direct, Mapping):
        direct_signature = feedback_signature(direct.get("question"), direct.get("correct_text"))
        if direct_signature == expected_signature:
            return direct
    return (feedback_by_signature or {}).get(expected_signature)


def _chosen_option_index(question: Mapping[str, Any], chosen: str) -> int | None:
    letters = [letter for letter in OPTION_LETTERS if letter in question.get("options", {})]
    try:
        return letters.index(chosen) + 1
    except ValueError:
        return None


def get_anatomy_answer_feedback(
    question: Mapping[str, Any],
    chosen: str,
    *,
    feedback_items: Mapping[str, Mapping[str, Any]] | None = None,
    feedback_by_signature: Mapping[str, Mapping[str, Any]] | None = None,
    legacy_explanations: Mapping[str, str] | None = None,
    legacy_explanations_by_signature: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return selected-option and correct-answer explanations without exposing the key early."""

    correct = str(question.get("correct", ""))
    options = question.get("options", {})
    chosen_text = str(options.get(chosen, ""))
    correct_text = str(options.get(correct, ""))
    record = _matching_record(question, feedback_items, feedback_by_signature)

    correct_explanation = ""
    source_warning = ""
    wrong_explanation = ""
    if record:
        correct_explanation = str(record.get("correct_explanation", "")).strip()
        source_warning = str(record.get("source_question_warning", "")).strip()
        if chosen != correct:
            wrong_map = record.get("wrong_explanations", {})
            if isinstance(wrong_map, Mapping):
                option_index = _chosen_option_index(question, chosen)
                wrong_explanation = str(
                    wrong_map.get(chosen)
                    or (wrong_map.get(str(option_index)) if option_index is not None else "")
                    or ""
                ).strip()

    if not correct_explanation:
        signature = feedback_signature(question.get("question"), correct_text)
        correct_explanation = str(
            (legacy_explanations_by_signature or {}).get(signature, "")
        ).strip()
    if not correct_explanation and legacy_explanations_by_signature is None:
        # Backward-compatible path for isolated callers that still operate solely on the
        # historical bank. Production supplies the signature index and never trusts a number
        # that can refer to a different question in another bank version.
        correct_explanation = str((legacy_explanations or {}).get(str(question.get("num")), "")).strip()
    if not correct_explanation:
        correct_explanation = (
            f"Правильный вариант — «{correct_text}». Он соответствует ключевому признаку, "
            "который проверяется в формулировке вопроса."
        )

    if chosen != correct and not wrong_explanation:
        wrong_explanation = (
            f"Вариант «{chosen_text}» не соответствует требуемому в вопросе признаку или "
            f"анатомическому отношению. В данном задании им является «{correct_text}»; "
            "различие раскрыто в пояснении правильного ответа ниже."
        )

    if chosen != correct and chosen_text:
        # Quote the learner's exact choice before the explanation.  Besides making the
        # feedback easier to scan, this preserves meaningful punctuation and qualifiers
        # from the source option instead of relying on the prose to repeat them verbatim.
        wrong_explanation = f"{wrong_explanation}\n\nВы выбрали: «{chosen_text}»"

    return {
        "wrong_explanation": wrong_explanation,
        "correct_explanation": correct_explanation,
        "source_warning": source_warning,
    }
