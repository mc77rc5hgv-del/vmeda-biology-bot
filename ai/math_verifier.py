# -*- coding: utf-8 -*-
"""Детерминированный математический verifier для calculation-заданий — пересчитывает результат
по РАСПОЗНАННОЙ формуле и сравнивает с числом, которое реально попало в ответ модели, вместо
поверхностной проверки ai.validator ("есть ли в ответе вообще хоть одна цифра").

Намеренно НЕ претендует на универсальный вывод формулы по произвольному тексту задачи — это
потребовало бы либо ещё одного обращения к модели (сам себя противоречит: "детерминированно, без
токенов"), либо полноценной системы компьютерной алгебры. Вместо этого держит РЕЕСТР явно
распознаваемых формул (см. _VERIFIERS, register()) для конкретных типов расчётов, которые реально
встречаются в программе ВМедА — сегодня закон Ома и pH раствора СТРОГО по концентрации [H+]/[H3O+]
(НЕ по [OH-]/щелочам — см. _verify_ph). Задание, чья формула не распознана (или распознана
недостаточно уверенно — например pH щёлочи, где формула через [H+] неприменима), помечается как
checked=False — verifier честно молчит, а не выдаёт уверенный, но ничем не подтверждённый вердикт.
Ложное "подтверждение" неправильного ответа хуже отсутствия verifier'а вообще, поэтому при
малейшем сомнении в применимости формулы или в единицах — checked=False, а не рискованная догадка.

Формулы матчатся по task.values/task.units (структурированные поля из ai.vision_parser), а НЕ
регэкспом по сырому тексту вопроса — единица должна ТОЧНО (после нормализации СИ-приставок)
совпасть с одним из известных написаний величины (см. _UNIT_MULTIPLIERS), а не просто содержать
букву-подстроку: раньше "а" как признак ампер могло случайно совпасть внутри "Па"/"га" и т.п."""
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

# Маркеры итогового ответа — если хотя бы один встретился в ответе, доверяем ТОЛЬКО числам ПОСЛЕ
# последнего такого маркера, а не первому/ближайшему числу во всём тексте. Иначе в подробном
# решении промежуточное число (или даже число из условия, повторённое в ходе решения) могло
# случайно оказаться ближе к ожидаемому значению, чем реальный (неверный) финальный ответ модели —
# то есть verifier мог бы "подтвердить" ответ, который сама модель в итоге назвала неправильно.
_FINAL_ANSWER_MARKER_RE = re.compile(r"(?:итог|ответ|результат)\s*[:\-—]?\s*", re.IGNORECASE)


@dataclass
class MathVerification:
    checked: bool = False  # была ли вообще применена формула — False, если ни одна не распознана
    matched: bool | None = None  # None, если checked=False; иначе — совпал ли пересчёт с ответом
    formula_name: str | None = None
    expected_value: float | None = None
    found_value: float | None = None  # число, реально сверенное с expected (см. _answer_numbers)
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


def _answer_numbers(answer: str) -> list:
    """Числа для сверки с пересчётом — если в ответе есть маркер итога ("Итог:"/"Ответ:"/
    "Результат:"), берём числа ТОЛЬКО после ПОСЛЕДНЕГО такого маркера; иначе (короткий quick-ответ
    без явного маркера — обычный случай) — все числа в ответе, как раньше."""
    matches = list(_FINAL_ANSWER_MARKER_RE.finditer(answer or ""))
    if matches:
        after_marker = _extract_numbers(answer[matches[-1].end():])
        if after_marker:
            return after_marker
    return _extract_numbers(answer)


def _value_float(raw) -> float | None:
    try:
        return float(str(raw).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


# Точные (не подстрокой) соответствия НОРМАЛИЗОВАННОЙ строки единицы (нижний регистр, без
# пробелов) множителю к базовой единице СИ — покрывает основные СИ-приставки, которые реально
# встречаются в школьных/вузовских задачах (мА/кОм/кВ и т.п.).
_UNIT_MULTIPLIERS = {
    "current": {
        "а": 1.0, "ампер": 1.0, "ампера": 1.0, "амперы": 1.0,
        "ма": 1e-3, "миллиампер": 1e-3, "мка": 1e-6, "микроампер": 1e-6,
    },
    "voltage": {
        "в": 1.0, "вольт": 1.0, "вольта": 1.0,
        "мв": 1e-3, "милливольт": 1e-3, "кв": 1e3, "киловольт": 1e3,
    },
    "resistance": {
        "ом": 1.0, "ома": 1.0,
        "ком": 1e3, "килоом": 1e3, "моом": 1e6, "мегаом": 1e6,
    },
}


def _find_by_unit(task: TaskRepresentation, quantity: str) -> float | None:
    """Первое значение из task.values, чья единица (task.units) ТОЧНО совпадает (после
    нормализации регистра/пробелов) с одним из известных написаний величины quantity
    ("current"/"voltage"/"resistance", см. _UNIT_MULTIPLIERS) — возвращает значение, приведённое
    к базовой единице СИ (А/В/Ом)."""
    multipliers = _UNIT_MULTIPLIERS[quantity]
    for key, unit in task.units.items():
        unit_norm = (unit or "").strip().lower().replace(" ", "")
        if unit_norm in multipliers:
            raw = _value_float(task.values.get(key))
            if raw is not None:
                return raw * multipliers[unit_norm]
    return None


_VERIFIERS = []  # [(name, match_fn)] — match_fn(task) -> float | None (пересчитанное ожидаемое
# значение, либо None, если формула не подходит к этому конкретному заданию)


def register(name: str):
    def deco(fn):
        _VERIFIERS.append((name, fn))
        return fn
    return deco


_OHM_TOPIC_RE = re.compile(r"закон\s+ома|\bом(?:а|ов|у)?\b", re.IGNORECASE)


@register("закон Ома (U = I × R)")
def _verify_ohms_law(task: TaskRepresentation) -> float | None:
    text = f"{task.question} {task.raw_text}"
    if not _OHM_TOPIC_RE.search(text) and not (
        "ток" in text.lower() and "напряжен" in text.lower() and "сопротивлен" in text.lower()
    ):
        return None  # без явного упоминания темы — слишком высокий риск ложного срабатывания
    r = _find_by_unit(task, "resistance")
    i = _find_by_unit(task, "current")
    u = _find_by_unit(task, "voltage")
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


# Ключ значения должен ЯВНО указывать на ион водорода/гидроксония — не любую концентрацию с
# единицей "моль" (см. предыдущую версию этого файла и разбор в CLAUDE.md): "0.01 моль/л NaOH"
# тоже содержит концентрацию в моль/л, но это [OH-], а не [H+], и pH через -log10([OH-]) даёт
# заведомо неверный (обратный, через 14-pOH) результат — уверенно неправильный, а не просто грубый.
_H_ION_KEY_MARKERS = ("h+", "h3o+", "н+")
# Явные признаки того, что вопрос вообще про основание/щёлочь — если сработали, формула через
# [H+] неприменима в принципе, даже если ключ значения почему-то выглядит как ион водорода.
_BASE_MARKERS = ("гидроксид", "щёлоч", "щелоч", "основан", "naoh", "koh", "oh-", "он-", "гидроксил")


@register("pH раствора (pH = -log10[H+], только по явно обозначенной [H+]/[H3O+])")
def _verify_ph(task: TaskRepresentation) -> float | None:
    text = f"{task.question} {task.raw_text}".lower()
    if "ph" not in text and "рн" not in text:
        return None
    if any(marker in text for marker in _BASE_MARKERS):
        return None  # вопрос про щёлочь/основание — pH тут не считается через [H+], молчим
    for key, unit in task.units.items():
        key_norm = re.sub(r"[^a-zа-я0-9+]", "", key.lower())
        if any(marker in key_norm for marker in _H_ION_KEY_MARKERS) and "моль" in (unit or "").lower():
            conc = _value_float(task.values.get(key))
            if conc is not None and conc > 0:
                return -math.log10(conc)
    return None


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
    с числом из _answer_numbers(answer) (приоритет — числа после маркера итога, см. выше), и
    возвращает вердикт. Ни одна распознанная формула — checked=False, verifier не имеет мнения об
    этом задании."""
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

        found_numbers = _answer_numbers(answer)
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
