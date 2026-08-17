# -*- coding: utf-8 -*-
"""Confidence-роутинг: объединяет сигналы уверенности с разных этапов конвейера (уверенность
vision-парсера в разборе самого задания, была ли найдена релевантная база РАГ, прошёл ли ответ
детерминированный валидатор — см. ai/validator.py) в одно решение, что делать с готовым ответом:

- SERVE — отдать как есть.
- VERIFY — отдать, но честно предупредить пользователя, что ответ не прошёл автоматическую
  проверку (см. SYSTEM_PROMPT: "если не уверен — прямо скажи об этом" — тот же принцип, только
  применённый программно, а не только на усмотрение модели).
- ESCALATE — самый тревожный случай. У quick-ответа (см. ai.router.pick_provider) сегодня НЕТ
  более сильного провайдера, на который можно было бы реально переключиться — quick всегда идёт
  через OpenAI, это осознанное архитектурное решение (самосогласованность с последующим подробным
  разбором). Поэтому ESCALATE здесь не запускает скрытый повторный запрос к модели (это было бы
  фиктивной сложностью без реального механизма за ней) — это сигнал ПРИОРИТЕТА для очереди
  модерации (см. telegram_bot.get_next_pending_ai_cache_entry): такие ответы поднимаются в начало
  очереди, чтобы админ увидел самые подозрительные генерации в первую очередь, а не в порядке
  поступления.

Модуль не обращается к модели сам — чистая функция от уже посчитанных сигналов, поэтому не стоит
ни одного токена."""
from __future__ import annotations

from dataclasses import dataclass, field

from ai.task import TaskRepresentation
from ai.validator import ValidationResult

SERVE = "serve"
VERIFY = "verify"
ESCALATE = "escalate"

LOW_PARSE_CONFIDENCE = 0.4  # ниже — vision-парсер сам не уверен, что верно разобрал вопрос
ESCALATE_THRESHOLD = -0.7   # штраф валидатора настолько велик, что это уже не просто "проверь"
VERIFY_SCORE_THRESHOLD = 0.7


@dataclass
class ConfidenceDecision:
    action: str  # SERVE / VERIFY / ESCALATE
    score: float  # агрегированный балл — для лога/админ-очереди, пользователю не показывается
    reasons: list = field(default_factory=list)


def decide(
    task: TaskRepresentation, validation: ValidationResult, *,
    rag_grounded: bool = False, from_cache: bool = False,
) -> ConfidenceDecision:
    """from_cache=True — ответ уже одобрен админом через кэш точных совпадений (см.
    telegram_bot.get_cached_ai_answer): доверие установлено модерацией заранее, пересчитывать
    нечего — всегда SERVE немедленно, без обращения к validation/task вообще."""
    if from_cache:
        return ConfidenceDecision(SERVE, 1.0, ["ответ из промодерированного кэша"])

    score = 1.0
    reasons = []

    if task.confidence < LOW_PARSE_CONFIDENCE:
        score -= 0.3
        reasons.append(f"низкая уверенность разбора задания ({task.confidence:.2f})")

    if rag_grounded:
        score += 0.1
        reasons.append("подкреплено материалами базы ВМедА")

    score += validation.confidence_adjustment
    reasons.extend(validation.warnings)

    if not validation.passed and validation.confidence_adjustment <= ESCALATE_THRESHOLD:
        return ConfidenceDecision(ESCALATE, score, reasons)
    if not validation.passed or score < VERIFY_SCORE_THRESHOLD:
        return ConfidenceDecision(VERIFY, score, reasons)
    return ConfidenceDecision(SERVE, score, reasons)
