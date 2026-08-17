# -*- coding: utf-8 -*-
"""Детерминированный валидатор ответа против TaskRepresentation — чистый Python, без единого
обращения к модели, поэтому не стоит ни одного токена. НЕ проверяет фактическую правильность
ответа (для этого нужен был бы отдельный, гораздо более дорогой механизм — например, второй
проход модели или сверка с эталонной базой) — только "похоже ли это вообще на валидный ответ на
заданный вопрос": расчёт без единой цифры, тест без ссылки хоть на один вариант, многопунктный
список с заметно меньшим числом строк, чем пунктов в задании, явный отказ вместо ответа. Каждая
найденная нестыковка снижает итоговую уверенность (см. ai/confidence.py — их накопление и решает,
можно ли отдавать ответ как есть)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ai.router import looks_like_refusal
from ai.task import TaskRepresentation

_NUMBER_RE = re.compile(r"\d")


@dataclass
class ValidationResult:
    passed: bool = True
    warnings: list = field(default_factory=list)
    confidence_adjustment: float = 0.0  # накопленный штраф (отрицательный) — см. ai/confidence.py

    def _flag(self, warning: str, penalty: float) -> None:
        self.passed = False
        self.warnings.append(warning)
        self.confidence_adjustment -= penalty


def validate_answer(task: TaskRepresentation, answer: str) -> ValidationResult:
    result = ValidationResult()
    answer_text = (answer or "").strip()

    if not answer_text:
        result._flag("пустой ответ", 1.0)
        return result

    if looks_like_refusal(answer_text):
        result._flag("похоже на отказ модели, а не на ответ по существу", 1.0)
        return result

    if task.type == "calculation" and not _NUMBER_RE.search(answer_text):
        result._flag("расчётное задание, но в ответе нет ни одной цифры", 0.4)

    if task.type == "mcq" and task.options:
        answer_lower = answer_text.lower()
        option_letters = {opt.strip()[:1].lower() for opt in task.options if opt.strip()}
        mentions_option_text = any(
            opt.strip().lower() in answer_lower for opt in task.options if opt.strip()
        )
        mentions_letter = any(
            re.search(rf"(?:^|[\s:«\"']){re.escape(letter)}[.)\s]", answer_lower)
            for letter in option_letters if letter
        )
        if not mentions_option_text and not mentions_letter:
            result._flag("тест с вариантами, но ответ не ссылается ни на один из них", 0.3)

    if task.type == "list" and task.subquestions:
        # грубая эвристика покрытия: в кратком ответе на список обычно одна строка на пункт —
        # заметно меньше строк, чем пунктов в задании, обычно значит часть пунктов пропущена
        answer_lines = [ln for ln in answer_text.splitlines() if ln.strip()]
        if len(answer_lines) < max(1, len(task.subquestions) // 2):
            result._flag(
                f"в задании {len(task.subquestions)} пунктов, а в ответе заметно меньше строк — "
                "похоже, часть пунктов пропущена",
                0.25,
            )

    return result
