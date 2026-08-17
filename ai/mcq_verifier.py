# -*- coding: utf-8 -*-
"""Детерминированный MCQ-verifier на основе эталонной базы (ai/reference_bank.py) — сверяет
выбранный моделью вариант с ОБЪЕКТИВНО известным правильным ответом, для вопросов достаточно
похожих на вопрос из банка. В отличие от ai/validator.py (который только проверяет, что ответ
вообще ссылается НА КАКОЙ-ТО вариант), здесь сверяется, что вариант — ПРАВИЛЬНЫЙ.

Как и ai/math_verifier.py, честно ограничен по охвату: покрывает только вопросы, достаточно
похожие на один из 1040 вопросов теста кафедры анатомии (см. ai/reference_bank.py) — для всего
остального (в том числе MCQ по биологии/физике/химии, которых в эталонной базе просто нет)
возвращает checked=False, не выдавая мнения без основания."""
from __future__ import annotations

import re
from dataclasses import dataclass

from ai import reference_bank
from ai.task import TaskRepresentation

_OPTION_LETTER_RE_CACHE: dict = {}


@dataclass
class MCQVerification:
    checked: bool = False
    matched: bool | None = None
    correct_option: str | None = None
    found_option: str | None = None
    note: str = ""


def _letter_pattern(letter: str) -> re.Pattern:
    """Кэшируем скомпилированные паттерны — одни и те же буквы (а-д) встречаются в каждом
    вопросе эталонной базы, пересобирать regex на каждый вызов незачем."""
    pattern = _OPTION_LETTER_RE_CACHE.get(letter)
    if pattern is None:
        pattern = re.compile(rf"(?:^|[\s:«\"'(]){re.escape(letter.lower())}[.)\s]")
        _OPTION_LETTER_RE_CACHE[letter] = pattern
    return pattern


def extract_chosen_letter(answer: str, options: dict) -> str | None:
    """Пытается понять, какой вариант назвала модель — сначала ищет явное упоминание буквы
    («вариант б», «б)», «ответ: б»), затем, если буква не встретилась явно, ищет в ответе текст
    самого варианта (модель иногда называет вариант текстом, не буквой)."""
    answer_lower = answer.lower()
    for letter in options:
        if _letter_pattern(letter).search(answer_lower):
            return letter
    for letter, text in options.items():
        if text and text.strip().lower() in answer_lower:
            return letter
    return None


def verify_mcq(task: TaskRepresentation, answer: str) -> MCQVerification:
    if task.type != "mcq" or not task.options:
        return MCQVerification(checked=False, note="verifier применяется только к mcq-заданиям со списком вариантов")

    reference = reference_bank.find_reference_match(task.question_text())
    if reference is None:
        return MCQVerification(checked=False, note="совпадений в эталонной базе не найдено")

    chosen = extract_chosen_letter(answer, reference["options"])
    if chosen is None:
        return MCQVerification(
            checked=True, matched=False, correct_option=reference["correct"],
            note="в ответе не удалось распознать выбранный вариант",
        )
    matched = chosen == reference["correct"]
    note = (
        "ответ совпадает с эталонным правильным вариантом" if matched
        else f"эталонный правильный вариант — «{reference['correct']}», модель выбрала «{chosen}»"
    )
    return MCQVerification(
        checked=True, matched=matched, correct_option=reference["correct"], found_option=chosen, note=note,
    )
