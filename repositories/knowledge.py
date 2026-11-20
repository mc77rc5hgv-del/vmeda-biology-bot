"""Загрузка всего контента бота (билеты/вопросы/теория по предметам, анатомия, гистология) из
JSON-файлов репозитория — раньше эти open()/json.load() вызовы были разбросаны по самому началу
telegram_bot.py, теперь единая точка входа. Каждый файл читается один раз при импорте модуля;
порядок загрузки и обработка (["topics"], ["tickets"], ["parts"], ["sections"]) сохранены один в
один с прежним кодом, чтобы не менять поведение бота — telegram_bot.py просто реэкспортирует эти
же имена (см. блок "ЗАГРУЗКА ДАННЫХ" там), так что все существующие обращения вида QUESTIONS[...]/
ANATOMY[...] по всему файлу остаются нетронутыми.

Пути — относительные, как и раньше: модуль должен импортироваться с корнем репозитория в качестве
текущей рабочей директории (см. CLAUDE.md — это уже требование для самого telegram_bot.py, здесь
ничего не меняется)."""
import json

from services.anatomy_feedback import (
    build_feedback_signature_index,
    build_legacy_explanation_signature_index,
)

with open("tickets.json", "r", encoding="utf-8") as f:
    TICKETS = json.load(f)
TICKETS_DICT = {str(t["num"]): t for t in TICKETS}

with open("questions.json", "r", encoding="utf-8") as f:
    QUESTIONS = json.load(f)

with open("physics_questions.json", "r", encoding="utf-8") as f:
    PHYSICS_QUESTIONS = json.load(f)

with open("physics_grade45.json", "r", encoding="utf-8") as f:
    PHYSICS_GRADE45_QUESTIONS = json.load(f)

with open("physics_extra_questions.json", "r", encoding="utf-8") as f:
    PHYSICS_EXTRA_QUESTIONS = json.load(f)

with open("chemistry_labs.json", "r", encoding="utf-8") as f:
    CHEMISTRY_LABS = json.load(f)

with open("chemistry_theory.json", "r", encoding="utf-8") as f:
    CHEMISTRY_THEORY = json.load(f)["topics"]

with open("chemistry_tasks.json", "r", encoding="utf-8") as f:
    CHEMISTRY_TASKS = json.load(f)["topics"]

with open("chemistry_theory_tickets.json", "r", encoding="utf-8") as f:
    CHEMISTRY_THEORY_TICKETS = json.load(f)["tickets"]

with open("chemistry_practice_tickets.json", "r", encoding="utf-8") as f:
    CHEMISTRY_PRACTICE_TICKETS = json.load(f)["tickets"]

with open("physics_tasks.json", "r", encoding="utf-8") as f:
    PHYSICS_TASKS = json.load(f)["topics"]

with open("physics_test_tickets.json", "r", encoding="utf-8") as f:
    PHYSICS_TEST_TICKETS = json.load(f)["tickets"]

with open("physics_task_tickets.json", "r", encoding="utf-8") as f:
    PHYSICS_TASK_TICKETS = json.load(f)["tickets"]

with open("physics_theory_tickets.json", "r", encoding="utf-8") as f:
    PHYSICS_THEORY_TICKETS = json.load(f)["tickets"]

with open("anatomy.json", "r", encoding="utf-8") as f:
    ANATOMY = json.load(f)

with open("anatomy_exam_test.json", "r", encoding="utf-8") as f:
    _ANATOMY_EXAM_LEGACY_PAYLOAD = json.load(f)
ANATOMY_EXAM_LEGACY_TEST_PARTS = _ANATOMY_EXAM_LEGACY_PAYLOAD["parts"]

with open("anatomy_exam_test_2026.json", "r", encoding="utf-8") as f:
    _ANATOMY_EXAM_CURRENT_PAYLOAD = json.load(f)
ANATOMY_EXAM_TEST_PARTS = _ANATOMY_EXAM_CURRENT_PAYLOAD["parts"]
ANATOMY_EXAM_BANK_VERSION = _ANATOMY_EXAM_CURRENT_PAYLOAD["bank_version"]
ANATOMY_EXAM_REVIEW_REQUIRED_COUNT = _ANATOMY_EXAM_CURRENT_PAYLOAD.get("review_required_count", 0)

with open("anatomy_explanations_draft.json", "r", encoding="utf-8") as f:
    ANATOMY_EXAM_TEST_EXPLANATIONS = json.load(f)["explanations"]

ANATOMY_EXAM_LEGACY_EXPLANATIONS_BY_SIGNATURE = build_legacy_explanation_signature_index(
    ANATOMY_EXAM_LEGACY_TEST_PARTS,
    ANATOMY_EXAM_TEST_EXPLANATIONS,
)

# Подробные пояснения привязаны одновременно к номеру вопроса и к сигнатуре
# «текст вопроса + правильный ответ». Это важно: исторический банк из 1040 вопросов и новый
# банк 2026 года из 1073 вопросов имеют разную нумерацию. Сигнатура не позволяет показать
# студенту объяснение от другого вопроса и не требует менять сохранённые номера ошибок/попыток.
try:
    with open("anatomy_exam_feedback_1073.json", "r", encoding="utf-8") as f:
        ANATOMY_EXAM_TEST_FEEDBACK_ITEMS = json.load(f).get("items", {})
except FileNotFoundError:
    # Файл готовится отдельно и проходит полную проверку 1073/1073 перед публикацией. Бот
    # остаётся работоспособным во время сборки, используя прежние общие объяснения.
    ANATOMY_EXAM_TEST_FEEDBACK_ITEMS = {}

ANATOMY_EXAM_TEST_FEEDBACK_BY_SIGNATURE = build_feedback_signature_index(
    ANATOMY_EXAM_TEST_FEEDBACK_ITEMS
)

with open("anatomy_exam_theory.json", "r", encoding="utf-8") as f:
    ANATOMY_EXAM_THEORY_SECTIONS = json.load(f)["sections"]

with open("anatomy_exam_practice.json", "r", encoding="utf-8") as f:
    ANATOMY_EXAM_PRACTICE_SECTIONS = json.load(f)["sections"]

with open("histology.json", "r", encoding="utf-8") as f:
    HISTOLOGY = json.load(f)

with open("operative_surgery.json", "r", encoding="utf-8") as f:
    OPERATIVE_SURGERY = json.load(f)

with open("physiology.json", "r", encoding="utf-8") as f:
    PHYSIOLOGY = json.load(f)
