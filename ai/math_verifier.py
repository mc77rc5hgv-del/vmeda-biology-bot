# -*- coding: utf-8 -*-
"""Детерминированный математический verifier для calculation-заданий — пересчитывает результат
по РАСПОЗНАННОЙ формуле и сравнивает с числом, которое реально попало в ответ модели, вместо
поверхностной проверки ai.validator ("есть ли в ответе вообще хоть одна цифра").

Намеренно НЕ претендует на универсальный вывод формулы по произвольному тексту задачи — это
потребовало бы либо ещё одного обращения к модели (сам себя противоречит: "детерминированно, без
токенов"), либо полноценной системы компьютерной алгебры. Вместо этого держит РЕЕСТР явно
распознаваемых формул (см. _VERIFIERS, register()) для конкретных типов расчётов, которые реально
встречаются в программе ВМедА — сегодня закон Ома и pH раствора по концентрации [H+]. Задание, чья
формула не распознана, помечается как checked=False — verifier честно молчит, а не выдаёт
уверенный, но ничем не подтверждённый вердикт.

Формулы матчатся по task.values/task.units (структурированные поля из ai.vision_parser), а НЕ
регэкспом по сырому тексту вопроса — единица "5 В" в values/units однозначно означает вольты,
тогда как то же "в" в сыром тексте почти всегда просто предлог ("в растворе"), и regex по прозе
даёт слишком много ложных срабатываний."""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field

from ai.task import TaskRepresentation

logger = logging.getLogger(__name__)

RELATIVE_TOLERANCE = 0.05  # 5% — не пытаемся ловить погрешность округления модели, только
# реальные расхождения; погрешность в пределах разумного округления не должна давать ESCALATE

_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


@dataclass
class MathVerification:
    checked: bool = False  # была ли вообще применена формула — False, если ни одна не распознана
    matched: bool | None = None  # None, если checked=False; иначе — совпал ли пересчёт с ответом
    formula_name: str | None = None
    expected_value: float | None = None
    found_value: float | None = None  # ближайшее к expected число, найденное в ответе модели
    note: str = ""
    reasons: list = field(default_factory=list)


def _extract_numbers(text: str) -> list:
    """Числа и в русской записи (запятая), и в обычной (точка)."""
    numbers = []
    for raw in _NUMBER_RE.findall(text or ""):
        try:
            numbers.append(float(raw.replace(",", ".")))
        except ValueError:
            continue
    return numbers


def _value_float(raw) -> float | None:
    try:
        return float(str(raw).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def _find_by_unit(task: TaskRepresentation, unit_keywords: tuple) -> float | None:
    """Первое значение из task.values, чья единица (task.units) содержит одно из unit_keywords
    (без учёта регистра) — например ("ом",) найдёт значение с единицей "Ом"/"ом"."""
    for key, unit in task.units.items():
        if any(kw in (unit or "").lower() for kw in unit_keywords):
            return _value_float(task.values.get(key))
    return None


_VERIFIERS = []  # [(name, match_fn)] — match_fn(task) -> float | None (пересчитанное ожидаемое
# значение, либо None, если формула не подходит к этому конкретному заданию)


def register(name: str):
    def deco(fn):
        _VERIFIERS.append((name, fn))
        return fn
    return deco


@register("закон Ома (U = I × R)")
def _verify_ohms_law(task: TaskRepresentation) -> float | None:
    text = f"{task.question} {task.raw_text}".lower()
    if "ом" not in text and not ("ток" in text and "напряжен" in text and "сопротивлен" in text):
        return None  # без явного упоминания темы — слишком высокий риск ложного срабатывания
    r = _find_by_unit(task, ("ом",))
    i = _find_by_unit(task, ("ампер", "а"))
    u = _find_by_unit(task, ("вольт", "в"))
    known = sum(x is not None for x in (r, i, u))
    if known != 2:
        return None  # нужно ровно два известных из трёх, третье — искомое
    if u is None:
        return i * r
    if r is None:
        return u / i if i else None
    if i is None:
        return u / r if r else None
    return None


@register("pH раствора (pH = -log10[H+])")
def _verify_ph(task: TaskRepresentation) -> float | None:
    text = f"{task.question} {task.raw_text}".lower()
    if "ph" not in text and "рн" not in text:
        return None
    conc = _find_by_unit(task, ("моль",))
    if conc is None or conc <= 0:
        return None
    return -math.log10(conc)


def _relative_close(found: float, expected: float, tol: float = RELATIVE_TOLERANCE) -> bool:
    if found == 0 and expected == 0:
        return True
    return abs(found - expected) <= tol * max(abs(found), abs(expected), 1e-9)


def _order_of_magnitude_mismatch(found: float, expected: float) -> bool:
    """True, если found и expected отличаются минимум в 10 раз — отдельно от обычного допуска:
    расхождение в разы почти всегда значит перепутанные единицы или потерянный/лишний множитель
    (например, забытый перевод г в кг), а не погрешность округления."""
    if found == 0 or expected == 0:
        return found != expected
    ratio = abs(found) / abs(expected)
    return ratio >= 10 or ratio <= 0.1


def verify_calculation(task: TaskRepresentation, answer: str) -> MathVerification:
    """Прогоняет задание через реестр известных формул (см. register() выше) — как только
    какая-то формула распознаёт задание (match_fn вернул не None), сверяет пересчитанный результат
    с БЛИЖАЙШИМ числом, реально найденным в ответе модели, и возвращает вердикт. Ни одна
    распознанная формула — checked=False, verifier не имеет мнения об этом задании."""
    if task.type != "calculation":
        return MathVerification(checked=False, note="verifier применяется только к calculation-заданиям")

    for name, match_fn in _VERIFIERS:
        try:
            expected = match_fn(task)
        except Exception:
            logger.exception("Формула «%s» упала на разборе задания, пробую следующую, если есть", name)
            continue
        if expected is None:
            continue

        found_numbers = _extract_numbers(answer)
        if not found_numbers:
            return MathVerification(
                checked=True, matched=False, formula_name=name, expected_value=expected,
                note=f"формула «{name}» распознана, но в ответе не найдено ни одного числа для сверки",
                reasons=[f"пересчёт по формуле «{name}» даёт {expected:.4g}, но в ответе нет чисел"],
            )
        best = min(found_numbers, key=lambda n: abs(n - expected))
        if _relative_close(best, expected):
            return MathVerification(
                checked=True, matched=True, formula_name=name, expected_value=expected, found_value=best,
                note=f"пересчёт по формуле «{name}» подтверждает ответ модели",
                reasons=[f"пересчёт по формуле «{name}» подтверждён ({expected:.4g} ≈ {best:.4g})"],
            )
        magnitude_note = " — похоже на потерянный/лишний порядок величины (перепутанные единицы?)" \
            if _order_of_magnitude_mismatch(best, expected) else ""
        note = f"пересчёт по формуле «{name}» даёт {expected:.4g}, в ответе ближайшее число {best:.4g}{magnitude_note}"
        return MathVerification(
            checked=True, matched=False, formula_name=name, expected_value=expected, found_value=best,
            note=note, reasons=[note],
        )

    return MathVerification(checked=False, note="ни одна из известных формул не распознана в этом задании")
