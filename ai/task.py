# -*- coding: utf-8 -*-
"""TaskRepresentation — структурированное представление разобранного задания. Общая валюта между
vision-парсером, RAG, solver'ом, кэшем точных совпадений и валидатором: все они работают с этим
объектом, а не с сырым текстом/фото на каждом шаге по отдельности (см. ai/vision_parser.py —
единственное место, где вообще участвует фото; дальше по конвейеру передаётся только это
представление, приведённое к тексту).

Модуль не импортирует telegram_bot (циклический импорт) и ничего не хранит на диск сам —
только структура данных + чистые функции над ней."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

# Типы задания — определяют и то, как валидатор проверяет ответ, и то, в какой "бакет" роутера
# (см. ai.router.route_bucket) уходит подробный разбор.
TASK_TYPES = ("calculation", "mcq", "list", "theory", "unknown")
COMPLEXITY_LEVELS = ("simple", "complex")  # применимо только к type in ("mcq", "theory") —
# насколько сложного рассуждения требует сам вопрос, определяется парсером по ФОРМУЛИРОВКЕ
# задания, а не по будущему ответу (в отличие от старого classify_quick_answer(), см. CLAUDE.md/
# обсуждение архитектурных недостатков AI-режима — пункт 3: "тип задания по ответу, а не по
# заданию" был реальной проблемой, эта классификация её устраняет).

_WORD_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)


@dataclass
class TaskRepresentation:
    subject: str | None = None       # "biology" / "physics" / "chemistry" / "anatomy" / None
    type: str = "unknown"            # один из TASK_TYPES
    complexity: str | None = None    # один из COMPLEXITY_LEVELS, только для type in (mcq, theory)
    question: str = ""               # текст задания как его понял парсер (может быть переформулирован из OCR)
    options: list[str] = field(default_factory=list)      # варианты ответа (MCQ)
    values: dict[str, str] = field(default_factory=dict)    # данные условия, например {"m": "10", "V": "2"}
    units: dict[str, str] = field(default_factory=dict)      # единицы для values, например {"m": "г", "V": "л"}
    subquestions: list[str] = field(default_factory=list)  # отдельные пункты, если вопрос многосоставной
    confidence: float = 0.0          # уверенность ПАРСЕРА в том, что задание прочитано и понято верно (0..1)
    raw_text: str = ""               # полный текст, как его увидел парсер (OCR/исходный текст) — fallback,
    # используется, если структурированные поля выше не заполнились (ошибка парсинга) и как
    # источник для RAG-эмбеддингов/fingerprint, если question почему-то пуст

    def is_usable(self) -> bool:
        """False — парсинг фактически провалился (не осталось вообще никакого текста задания),
        вызывающий код должен упасть на старый путь (raw text/фото без структуры)."""
        return bool(self.question.strip() or self.raw_text.strip())

    def question_text(self) -> str:
        return self.question.strip() or self.raw_text.strip()

    def to_prompt_text(self) -> str:
        """Текстовое представление задания для отправки модели — единственное, что solver
        когда-либо видит после первого прохода парсера (фото НЕ пересылается повторно)."""
        lines = [self.question_text()]
        if self.values:
            values_line = ", ".join(
                f"{k} = {v}{(' ' + self.units[k]) if k in self.units else ''}"
                for k, v in self.values.items()
            )
            lines.append(f"Дано: {values_line}")
        if self.options:
            lines.append("Варианты ответа: " + "; ".join(self.options))
        if self.subquestions:
            lines.append("Пункты вопроса:\n" + "\n".join(f"- {s}" for s in self.subquestions))
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "subject": self.subject, "type": self.type, "complexity": self.complexity,
            "question": self.question, "options": self.options, "values": self.values,
            "units": self.units, "subquestions": self.subquestions,
            "confidence": self.confidence, "raw_text": self.raw_text,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TaskRepresentation:
        return cls(
            subject=data.get("subject"), type=data.get("type", "unknown"),
            complexity=data.get("complexity"), question=data.get("question", ""),
            options=list(data.get("options") or []), values=dict(data.get("values") or {}),
            units=dict(data.get("units") or {}), subquestions=list(data.get("subquestions") or []),
            confidence=float(data.get("confidence") or 0.0), raw_text=data.get("raw_text", ""),
        )

    def fingerprint(self) -> str:
        """Ключ для кэша точных совпадений (ai.answer_cache) — нормализует текст задания
        (нижний регистр, только буквы/цифры, пробелы схлопнуты) перед хэшированием, чтобы разные
        формулировки одного и того же вопроса ("Сколько хромосом в соматической клетке человека?"
        vs "сколько хромосом в соматической клетке человека") давали один и тот же fingerprint.
        Значения условия (values) подмешиваются в нормализованный текст — иначе два РАЗНЫХ
        расчёта с одинаковой формулировкой вопроса, но разными исходными числами, схлопнулись бы
        в одну запись кэша с чужим ответом."""
        normalized_words = _WORD_RE.findall(self.question_text().lower().replace("ё", "е"))
        values_words = []
        for k, v in sorted(self.values.items()):
            values_words.extend(_WORD_RE.findall(f"{k}{v}".lower()))
        payload = " ".join(sorted(normalized_words) + sorted(values_words))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
