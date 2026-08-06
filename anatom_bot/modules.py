"""Static course structure mirrored from anatomapp.ru's own `MODULES`/`SECTIONS_BY_MODULE`
(index.html, ~line 1000). Kept here as plain data (not fetched live) since the site's per-topic
JSON datasets (osteology-data.json etc.) aren't reliably reachable from the backend and the
module/section shape changes rarely — update this file by hand if the site's course structure
changes.

A progress key on the site looks like "<moduleId>:<topicNum>", e.g. "m1:5".
"""

from __future__ import annotations

from typing import NamedTuple, Optional


class Module(NamedTuple):
    id: str
    title: str
    icon: str
    tag: str
    topic_count: int  # highest `to` across this module's sections


MODULES: list[Module] = [
    Module("m1", "Остеология", "🦴", "МОДУЛЬ 1 · КОСТИ", 37),
    Module("m2", "Синдесмология", "🔗", "МОДУЛЬ 2 · СВЯЗКИ И СУСТАВЫ", 15),
    Module("m3", "Миология", "💪", "МОДУЛЬ 3 · МЫШЦЫ", 15),
    Module("m4", "Спланхнология", "🫁", "МОДУЛЬ 4 · ВНУТРЕННИЕ ОРГАНЫ", 31),
    Module("m6", "Неврология", "🧠", "МОДУЛЬ 5 · НЕРВНАЯ СИСТЕМА", 33),
    Module("m5", "Ангиология", "🫀", "МОДУЛЬ 6 · СЕРДЦЕ И СОСУДЫ", 12),
]

MODULES_BY_ID: dict[str, Module] = {m.id: m for m in MODULES}

# name, icon, from-topic-num, to-topic-num (inclusive), per module.
SECTIONS_BY_MODULE: dict[str, list[tuple[str, str, int, int]]] = {
    "m1": [
        ("Общая остеология. Скелет туловища", "🦴", 1, 4),
        ("Кости черепа", "💀", 5, 24),
        ("Верхняя конечность", "💪", 25, 30),
        ("Нижняя конечность", "🦵", 31, 37),
    ],
    "m2": [
        ("Общая артрология и виды соединений", "🔗", 1, 3),
        ("Соединения туловища и черепа", "🦴", 4, 6),
        ("Суставы верхней конечности", "💪", 7, 11),
        ("Суставы нижней конечности", "🦵", 12, 15),
    ],
    "m3": [
        ("Общая часть. Мышцы туловища", "💪", 1, 5),
        ("Мышцы шеи и головы", "🗣", 6, 7),
        ("Мышцы верхней конечности", "🦾", 8, 11),
        ("Мышцы нижней конечности", "🦵", 12, 15),
    ],
    "m4": [
        ("Пищеварительная система", "🍽", 1, 17),
        ("Дыхательная система", "🫁", 18, 22),
        ("Мочевая система", "🚰", 23, 24),
        ("Половая система", "⚧", 25, 31),
    ],
    "m5": [
        ("Общая ангиология и артерии тела", "🫀", 1, 2),
        ("Артерии головы, шеи и верхней конечности", "🦾", 3, 4),
        ("Артерии туловища и нижней конечности", "🦵", 5, 8),
        ("Венозная система", "🩸", 9, 11),
        ("Лимфатическая система", "💧", 12, 12),
    ],
    "m6": [
        ("ЦНС · Общая часть и спинной мозг", "🧬", 1, 4),
        ("ЦНС · Ствол мозга и мозжечок", "🧠", 5, 8),
        ("ЦНС · Промежуточный и конечный мозг", "🧠", 9, 13),
        ("ЦНС · Желудочки и кровоснабжение", "🩸", 14, 15),
        ("ПНС · Спинномозговые нервы и сплетения", "🕸", 16, 20),
        ("ПНС · Черепные нервы", "🧠", 21, 22),
        ("ПНС · Вегетативная нервная система", "🔄", 23, 26),
        ("Органы чувств · Зрение", "👁", 27, 29),
        ("Органы чувств · Слух и равновесие", "👂", 30, 31),
        ("Органы чувств · Обоняние, вкус, кожа", "👃", 32, 33),
    ],
}

PASS_THRESHOLD = 75  # site's own "passed" cutoff (bestPct >= 75), see topicsOf()/passedN in index.html


def parse_key(key: str) -> Optional[tuple[str, int]]:
    if ":" not in key:
        return None
    module_id, _, num_raw = key.partition(":")
    try:
        return module_id, int(num_raw)
    except ValueError:
        return None


def section_name(module_id: str, topic_num: int) -> str:
    for name, icon, lo, hi in SECTIONS_BY_MODULE.get(module_id, []):
        if lo <= topic_num <= hi:
            return f"{icon} {name}"
    return ""


def describe_key(key: str) -> str:
    """Human label for a progress key, e.g. 'm1:5' -> 'Остеология · Кости черепа (тема №5)'."""
    parsed = parse_key(key)
    if parsed is None:
        return key
    module_id, num = parsed
    module = MODULES_BY_ID.get(module_id)
    module_title = module.title if module else module_id
    section = section_name(module_id, num)
    if section:
        return f"{module_title} · {section} (тема №{num})"
    return f"{module_title} (тема №{num})"
