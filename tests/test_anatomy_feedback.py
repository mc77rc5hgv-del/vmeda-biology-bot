import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from services.anatomy_feedback import (
    build_feedback_signature_index,
    build_legacy_explanation_signature_index,
    get_anatomy_answer_feedback,
)


def _question(num=7):
    return {
        "num": num,
        "question": "Какой нерв иннервирует мышцу?",
        "options": {"а": "лучевой нерв", "б": "локтевой нерв", "в": "срединный нерв"},
        "correct": "а",
    }


def test_uses_selected_option_feedback_and_correct_explanation():
    records = {
        "7": {
            "question": "Какой нерв иннервирует мышцу?",
            "correct_text": "лучевой нерв",
            "correct_explanation": "Лучевой нерв обеспечивает требуемую двигательную иннервацию.",
            "wrong_explanations": {
                "2": "Локтевой нерв иннервирует другую группу мышц.",
                "3": "Срединный нерв не подходит к указанной мышце.",
            },
        }
    }
    result = get_anatomy_answer_feedback(
        _question(),
        "б",
        feedback_items=records,
        feedback_by_signature=build_feedback_signature_index(records),
    )
    assert result["wrong_explanation"].startswith("Локтевой нерв")
    assert result["correct_explanation"].startswith("Лучевой нерв")


def test_rejects_same_number_record_from_another_bank_and_uses_signature():
    records = {
        "7": {
            "question": "Совсем другой вопрос",
            "correct_text": "другой ответ",
            "correct_explanation": "Чужое пояснение.",
            "wrong_explanations": {"2": "Чужая ошибка."},
        },
        "1007": {
            "question": "Какой нерв иннервирует мышцу?",
            "correct_text": "лучевой нерв",
            "correct_explanation": "Найдено по устойчивой подписи содержания.",
            "wrong_explanations": {"2": "Локтевой нерв относится к другой зоне."},
        },
    }
    result = get_anatomy_answer_feedback(
        _question(),
        "б",
        feedback_items=records,
        feedback_by_signature=build_feedback_signature_index(records),
    )
    assert result["correct_explanation"] == "Найдено по устойчивой подписи содержания."
    assert "Чужое" not in result["correct_explanation"]


def test_legacy_and_safe_wrong_option_fallbacks_remain_available():
    result = get_anatomy_answer_feedback(
        _question(),
        "в",
        feedback_items={},
        feedback_by_signature={},
        legacy_explanations={"7": "Проверенное общее пояснение по учебнику."},
    )
    assert result["correct_explanation"] == "Проверенное общее пояснение по учебнику."
    assert "срединный нерв" in result["wrong_explanation"]
    assert "лучевой нерв" in result["wrong_explanation"]


def test_correct_choice_has_no_wrong_explanation():
    result = get_anatomy_answer_feedback(
        _question(),
        "а",
        legacy_explanations={"7": "Правильное пояснение."},
    )
    assert result["wrong_explanation"] == ""
    assert result["correct_explanation"] == "Правильное пояснение."


def test_production_legacy_fallback_never_trusts_a_reused_number():
    old_question = {
        "num": 7,
        "question": "Старый вопрос из банка 1040?",
        "options": {"а": "старый правильный", "б": "старый неверный"},
        "correct": "а",
    }
    signature_index = build_legacy_explanation_signature_index(
        [{"questions": [old_question]}],
        {"7": "Пояснение только к старому вопросу."},
    )
    result = get_anatomy_answer_feedback(
        _question(num=7),
        "б",
        legacy_explanations={"7": "Пояснение только к старому вопросу."},
        legacy_explanations_by_signature=signature_index,
    )
    assert "старому вопросу" not in result["correct_explanation"]
    assert "лучевой нерв" in result["correct_explanation"]


if __name__ == "__main__":
    test_uses_selected_option_feedback_and_correct_explanation()
    test_rejects_same_number_record_from_another_bank_and_uses_signature()
    test_legacy_and_safe_wrong_option_fallbacks_remain_available()
    test_correct_choice_has_no_wrong_explanation()
    test_production_legacy_fallback_never_trusts_a_reused_number()
    print("anatomy option-aware feedback: OK")
