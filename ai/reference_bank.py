# -*- coding: utf-8 -*-
"""Эталонная база вопросов с ОБЪЕКТИВНО известным правильным ответом — единственный источник
контента в боте такого рода. Собрана из официального теста кафедры нормальной анатомии ВМедА
(см. anatomy_exam_test.json, Гайворонский и др., 2021 — тот же банк из 1040 вопросов, что питает
раздел "🎓 Экзамен → ✅ ТЕСТ"): каждый вопрос уже имеет проверенный вариант ответа, сверять не с
чем гадать. Биология/Физика/Химия сюда сознательно НЕ входят — их контент в боте это free-text
теория (title+answer), без объективно проверяемого "правильного варианта"; сверить с ним ответ
модели можно было бы только ещё одним обращением к модели-судье, а это уже не "детерминированно,
без токенов".

Используется:
1. ai.mcq_verifier — сверяет выбранный моделью вариант с известным правильным, если вопрос
   пользователя достаточно похож на вопрос из банка (тот же принцип, что ai/math_verifier.py для
   calculation-заданий, только на основе поиска, а не распознавания формулы).
2. scripts/ai_benchmark.py — прогоняет реальный конвейер по выборке из этого банка и измеряет
   фактическую точность на объективно проверяемых вопросах.

Модуль не импортирует telegram_bot (циклический импорт) — контент передаётся в configure() один
раз при старте (см. telegram_bot.py, рядом с ai_rag.configure())."""
from __future__ import annotations

import re

_WORD_RE = re.compile(r"[a-zа-яё]+")

MIN_MATCH_SCORE = 0.6  # доля пересечения стеммов вопроса пользователя со стеммами эталонного —
# высокий порог осознанно: ложное совпадение с ДРУГИМ вопросом того же банка вернуло бы чужой
# "correct" и дало бы verifier, который уверенно врёт — лучше не найти совпадение вообще (checked
# =False), чем найти неправильное


def _extract_words(text: str) -> list:
    return _WORD_RE.findall((text or "").lower().replace("ё", "е"))


def _word_stem(word: str) -> str:
    """Тот же грубый стеммер, что и в ai/rag.py — локальная копия, не импортируется оттуда,
    чтобы эталонная база не зависела от модуля RAG (независимые концепции, даже если алгоритм
    совпадает); при изменении стеммера менять в обоих местах."""
    n = len(word)
    if n <= 4:
        return word
    if n <= 6:
        return word[:-1]
    return word[:-2]


def _stems(text: str) -> set:
    return {_word_stem(w) for w in _extract_words(text) if len(w) >= 4}


_index = []  # [{"question": str, "stems": set, "options": {letter: text}, "correct": letter}]


def configure(parts: list) -> None:
    """parts — ANATOMY_EXAM_TEST_PARTS (см. repositories/knowledge.py): список частей теста,
    каждая с "questions": [{"question", "options": {letter: text}, "correct": letter}, ...].
    Пропускает записи без валидных options/correct — источник контроллируется вручную и такого
    не бывает, но проверка дешёвая, а тихая деградация лучше падения при загрузке бота."""
    global _index
    _index = []
    for part in parts or []:
        for q in part.get("questions", []):
            question = q.get("question", "")
            options = q.get("options")
            correct = q.get("correct")
            if not question or not isinstance(options, dict) or correct not in options:
                continue
            _index.append({"question": question, "stems": _stems(question), "options": options, "correct": correct})


def find_reference_match(question_text: str) -> dict | None:
    """Возвращает эталонную запись ({"question", "options", "correct"}), максимально похожую на
    question_text (по пересечению стеммов, Jaccard-подобная мера), либо None — если индекс пуст
    (configure() не вызывался), в запросе нет значимых слов, или лучшее совпадение всё равно ниже
    MIN_MATCH_SCORE. Требует configure() заранее."""
    query_stems = _stems(question_text)
    if not query_stems or not _index:
        return None
    best_score = 0.0
    best_entry = None
    for entry in _index:
        common = query_stems & entry["stems"]
        if not common:
            continue
        score = len(common) / max(len(query_stems), len(entry["stems"]))
        if score > best_score:
            best_score = score
            best_entry = entry
    if best_entry is None or best_score < MIN_MATCH_SCORE:
        return None
    return best_entry
