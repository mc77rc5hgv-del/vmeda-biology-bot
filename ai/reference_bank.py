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

# "не"/"нет" и т.п. короче 4 символов и обычным стеммингом (см. _stems, len(w) >= 4) отбрасываются
# как "незначимые" — но именно они меняют смысл вопроса на противоположный: "Какая структура
# относится к X?" и "Какая структура НЕ относится к X?" делят между собой почти весь остальной
# набор слов и легко проходят порог схожести, оставаясь при этом разными вопросами с разными
# правильными ответами. Раз verifier'у можно доверить право поднять ESCALATE, разное "полярности"
# запроса и кандидата должно ЗАПРЕЩАТЬ совпадение целиком, а не просто чуть снижать балл.
#
# Короткие/неизменяемые слова — сравниваются ТОЧНЫМ совпадением токена, не префиксом: "не" как
# startswith-префикс поймал бы "невролог"/"некроз"/"необходимо" и т.п., превратив половину
# медицинской лексики в ложные "маркеры отрицания".
_POLARITY_EXACT_WORDS = ("не", "нет", "ни", "кроме")
# Более длинные слова с изменяемыми окончаниями — startswith безопасен, случайных русских слов,
# начинающихся с этих 6+ буквенных префиксов и не связанных по смыслу, практически не бывает.
_POLARITY_PREFIXES = ("неверн", "исключ")


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


def _polarity_tokens(text: str) -> frozenset:
    """Слова-маркеры отрицания/исключения — сохраняются ЦЕЛИКОМ (без стемминга, длина не важна),
    отдельно от обычных стеммов (см. _POLARITY_EXACT_WORDS/_POLARITY_PREFIXES)."""
    return frozenset(
        w for w in _extract_words(text)
        if w in _POLARITY_EXACT_WORDS or any(w.startswith(p) for p in _POLARITY_PREFIXES)
    )


def _options_stems(options) -> list:
    if isinstance(options, dict):
        texts = options.values()
    else:
        texts = options or []
    return [_stems(t) for t in texts if t and _stems(t)]


_OPTIONS_MATCH_THRESHOLD = 0.6  # доля вариантов запроса, которым нужно найти похожий вариант в
# эталонном вопросе — вопрос может звучать похоже, но если набор вариантов ответа другой, это,
# скорее всего, другой вопрос (или другая версия того же вопроса с другими вариантами) — сверять
# в таком случае с чужим "correct" опасно


def _options_match(query_options, ref_options: dict) -> bool:
    """True, если query_options (список текстов вариантов, как их разобрал vision-парсер) в
    достаточной мере (см. _OPTIONS_MATCH_THRESHOLD) соответствуют вариантам эталонного вопроса.
    Пустой/отсутствующий query_options не блокирует совпадение — если vision-парсер не смог
    вытащить варианты отдельным списком, сверять по ним нечего, но текст вопроса уже прошёл порог
    схожести и полярности, этого достаточно."""
    query_stems_list = _options_stems(query_options)
    if not query_stems_list:
        return True
    ref_stems_list = _options_stems(ref_options)
    if not ref_stems_list:
        return False
    matched = 0
    for q_stems in query_stems_list:
        if any(len(q_stems & r_stems) / max(len(q_stems), len(r_stems)) >= 0.5 for r_stems in ref_stems_list):
            matched += 1
    return matched / len(query_stems_list) >= _OPTIONS_MATCH_THRESHOLD


_index = []  # [{"question", "stems", "polarity", "options", "correct"}]


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
            _index.append({
                "question": question, "stems": _stems(question), "polarity": _polarity_tokens(question),
                "options": options, "correct": correct,
            })


def find_reference_match(question_text: str, options=None) -> dict | None:
    """Возвращает эталонную запись ({"question", "options", "correct"}), максимально похожую на
    question_text (по пересечению стеммов, Jaccard-подобная мера), либо None — если индекс пуст
    (configure() не вызывался), в запросе нет значимых слов, лучшее совпадение ниже MIN_MATCH_SCORE,
    полярность (см. _polarity_tokens) вопроса не совпадает ни с одним кандидатом с таким же
    текстовым сходством, или (если передан options) варианты ответа недостаточно похожи (см.
    _options_match) — сверх текстового сходства это последний барьер против того, чтобы
    "объективный" verifier уверенно подтвердил/опроверг ответ на СОВСЕМ ДРУГОЙ вопрос. Требует
    configure() заранее."""
    query_stems = _stems(question_text)
    if not query_stems or not _index:
        return None
    query_polarity = _polarity_tokens(question_text)
    best_score = 0.0
    best_entry = None
    for entry in _index:
        if entry["polarity"] != query_polarity:
            continue
        common = query_stems & entry["stems"]
        if not common:
            continue
        score = len(common) / max(len(query_stems), len(entry["stems"]))
        if score > best_score:
            best_score = score
            best_entry = entry
    if best_entry is None or best_score < MIN_MATCH_SCORE:
        return None
    if not _options_match(options, best_entry["options"]):
        return None
    return best_entry
