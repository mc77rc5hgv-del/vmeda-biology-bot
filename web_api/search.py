"""Поиск по заголовкам учебных материалов всех предметов.

Индекс строится один раз из того же контент-слоя, что и экраны разделов (content.py для
динамических курсов, static_content.py для остальных): ~4000 заголовков, единицы миллисекунд.
Права здесь не проверяются — роутер фильтрует найденное теми же функциями доступа, что отдают
список раздела, поэтому поиск не раскрывает заголовки, которые пользователь не увидел бы и так.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass

from . import content, static_content

QUERY_MIN_LENGTH = 2
QUERY_MAX_LENGTH = 80


@dataclass(frozen=True)
class SearchEntry:
    subject_id: str
    subject_title: str
    section_id: str
    section_title: str
    group_chain: tuple[str, ...]
    item_id: str
    title: str
    norm_title: str


def normalize(text: str) -> str:
    return " ".join(text.lower().replace("ё", "е").split())


def _is_static(subject_id: str) -> bool:
    return subject_id in static_content.SUPPORTED_SUBJECT_IDS


def subject_detail(tb, subject_id: str) -> dict:
    if _is_static(subject_id):
        return static_content.get_subject_detail(tb, subject_id)
    return content.get_subject_detail(tb.DYNAMIC_COURSES, subject_id)


def _section_detail(tb, subject_id: str, section_id: str) -> dict:
    if _is_static(subject_id):
        return static_content.get_section_detail(tb, subject_id, section_id)
    return content.get_section_detail(tb.DYNAMIC_COURSES, subject_id, section_id)


def _group_detail(tb, subject_id: str, section_id: str, group_id: str) -> dict:
    if _is_static(subject_id):
        return static_content.get_group_detail(tb, subject_id, section_id, group_id)
    return content.get_group_detail(tb.DYNAMIC_COURSES, subject_id, section_id, group_id)


def subject_ids(tb) -> list[str]:
    return [course["id"] for course in tb.DYNAMIC_COURSES] + [
        summary["id"] for summary in static_content.list_subject_summaries(tb)
    ]


def total_items(tb, subject_id: str) -> int | None:
    try:
        return sum(section["item_count"] for section in subject_detail(tb, subject_id)["sections"])
    except content.ContentNotFoundError:
        return None


def build_index(tb) -> list[SearchEntry]:
    entries: list[SearchEntry] = []
    for subject_id in subject_ids(tb):
        try:
            detail = subject_detail(tb, subject_id)
        except content.ContentNotFoundError:
            continue
        for section in detail["sections"]:
            try:
                section_data = _section_detail(tb, subject_id, section["id"])
            except content.ContentNotFoundError:
                continue

            def add(items, chain, section=section, detail=detail):
                for item in items:
                    entries.append(SearchEntry(
                        subject_id, detail["title"], section["id"], section["title"], chain,
                        str(item["id"]), item["title"], normalize(item["title"]),
                    ))

            add(section_data.get("items", []), ())
            pending = [((group["id"],)) for group in section_data.get("groups", [])]
            seen: set[tuple[str, ...]] = set()
            while pending:
                chain = pending.pop()
                if chain in seen:
                    continue
                seen.add(chain)
                try:
                    group_data = _group_detail(tb, subject_id, section["id"], chain[-1])
                except content.ContentNotFoundError:
                    continue
                add(group_data.get("items", []), chain)
                pending.extend(chain + (sub["id"],) for sub in group_data.get("subgroups", []) or [])
    return entries


_cache_lock = threading.Lock()
_cache: tuple[tuple[int, int], list[SearchEntry]] | None = None


def get_index(tb) -> list[SearchEntry]:
    """Контент загружается при импорте бота и не меняется до перезапуска процесса."""
    global _cache
    key = (id(tb), id(tb.DYNAMIC_COURSES))
    cached = _cache
    if cached is not None and cached[0] == key:
        return cached[1]
    with _cache_lock:
        if _cache is None or _cache[0] != key:
            _cache = (key, build_index(tb))
        return _cache[1]


def find(tb, query: str) -> list[SearchEntry]:
    needle = normalize(query)
    if len(needle) < QUERY_MIN_LENGTH:
        return []
    word_start = re.compile(r"(?<![0-9a-zа-я])" + re.escape(needle))
    matches = [entry for entry in get_index(tb) if needle in entry.norm_title]
    # Выше: совпадение с начала заголовка, затем с начала любого слова («кость» → «Плечевая
    # кость» раньше «Вязкость»), затем более короткий заголовок.
    matches.sort(key=lambda entry: (
        not entry.norm_title.startswith(needle),
        word_start.search(entry.norm_title) is None,
        len(entry.norm_title),
    ))
    return matches
