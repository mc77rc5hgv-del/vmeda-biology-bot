"""RAG-lite: перед ПОДРОБНЫМ разбором (quick=False) ищем в собственной базе бота (вопросы/
билеты, уже загруженные в память для других разделов) несколько релевантных фрагментов и
подмешиваем их в запрос к модели, чтобы формулировки и метод совпадали с тем, что реально
требуют на кафедре, а не с общими знаниями модели. Поиск — стеммированный keyword-matching с
IDF-весами (0 токенов, чистый Python); токены тратятся только на сам подмешанный текст, и
только тогда, когда что-то релевантное реально нашлось.

Модуль не импортирует telegram_bot (циклический импорт) — контент передаётся в configure()
один раз при старте бота, после загрузки JSON-файлов."""
import html
import math
import re

TOP_K = 3          # сколько фрагментов подмешиваем максимум за один подробный запрос — на
# многопунктных списках (search_snippets_multi) термины могут разбегаться по разным темам
# (лёгкие/плевра, сердце/перикард, таз/промежность), 2 не хватало на покрытие
SNIPPET_MAX_CHARS = 600  # потолок длины ОДНОГО фрагмента — ограничивает добавленные токены
MIN_COMMON_STEMS = 2  # минимум РАЗНЫХ общих слов с запросом — иначе одно случайное слово уже
                       # может дать высокий взвешенный балл
# Порог по НОРМАЛИЗОВАННОМУ баллу (сумма IDF общих слов / число стеммов в запросе), не по сырой
# сумме: длинный многопунктный ответ (например, список из 9+ анатомических терминов) набирает
# сырую сумму выше короткого точного вопроса просто за счёт объёма слов, даже когда реально
# релевантной темы в индексе вообще нет — на реальном вопросе так подмешался явно посторонний
# материал (эволюция органов дыхания у беспозвоночных вместо анатомии полостей тела). На тех же
# реальных вопросах у настоящих совпадений (митохондрии, коллигативные свойства, закон Ома)
# нормализованный балл 1.3-3.5, у случайных многословных совпадений — 0.8-0.9: порог 1.2 чисто
# разделяет эти два случая.
MIN_SCORE = 1.2

LIST_MARKER_RE = re.compile(r"(?m)^\s*\d+[.)]\s+")  # "9. ", "10. " — нумерация пунктов списка;
# используется и здесь (бить ответ на отдельные пункты для поиска), и в ai.router (не путать
# номер пункта с числом-результатом расчёта)

_HTML_TAG_RE = re.compile(r"<[^>]+>")  # локальная лёгкая версия strip_html_tags — не импортируем
# telegram_bot (циклический импорт), а полноценный докс-раннер тут и не нужен, только снять теги


def _extract_words(text: str) -> list:
    return re.findall(r"[a-zа-яё]+", (text or "").lower().replace("ё", "е"))


def _word_stem(word: str) -> str:
    """Грубый стеммер: отбрасывает окончание, чтобы находить разные словоформы
    ("плазмодий" / "плазмодия" / "плазмодии"). Локальная копия того же алгоритма, что и в
    telegram_bot.py (search_questions_by_keyword) — не импортируется оттуда, чтобы избежать
    циклического импорта; при изменении стеммера менять в обоих местах."""
    n = len(word)
    if n <= 4:
        return word
    if n <= 6:
        return word[:-1]
    return word[:-2]


def _entry_stems(title: str, text: str) -> set:
    words = _extract_words(title) + _extract_words(text)
    return {_word_stem(w) for w in words if len(w) >= 4}


def build_index(
    *, questions: dict, physics_questions: dict, chemistry_theory: dict,
    chemistry_theory_tickets: dict, chemistry_practice_tickets: dict, anatomy: dict,
) -> list:
    """Собирает единый список {subject, title, text, stems} из банков вопросов/ответов бота:
    биология/физика/химия (основная заявленная область AI-помощника) и анатомия (вопросы по
    ней реально задают через этот же AI-режим, и без точных терминов из ANATOMY модель на них
    иногда путает термины по памяти)."""
    raw_entries = []
    for q in questions.values():
        raw_entries.append(("биология", q.get("title", ""), q.get("answer", "")))
    for q in physics_questions.values():
        raw_entries.append(("физика", q.get("title", ""), q.get("answer", "")))
    for topic in chemistry_theory.values():
        raw_entries.append(("химия", topic.get("title", ""), topic.get("content", "")))
    for ticket in list(chemistry_theory_tickets.values()) + list(chemistry_practice_tickets.values()):
        for q in ticket.get("questions", []):
            raw_entries.append(("химия", q.get("title", ""), q.get("answer", "")))
    for section in anatomy.values():
        for topic in section.get("topics", {}).values():
            for item in topic.get("material") or []:
                raw_entries.append(("анатомия", item.get("title", ""), item.get("content", "")))
            for card in topic.get("flashcards") or []:
                raw_entries.append(("анатомия", card.get("front", ""), card.get("back", "")))
    return [
        {"subject": subject, "title": title, "text": text, "stems": _entry_stems(title, text)}
        for subject, title, text in raw_entries
        if title and text
    ]


def build_stem_idf(index: list) -> dict:
    """Обычные IDF-веса: слова, встречающиеся почти в каждой записи («который», «между»,
    «строение», «функции» — типичные связки для формулировок в стиле «Х, его строение и
    функции») получают низкий вес и почти не влияют на совпадение; редкие тематические слова
    («перикард», «диссоциация», «коллигативные») — высокий. Без этого длинный ответ совпадал по
    общим словам со случайными, вообще не связанными темами (наблюдалось на реальном вопросе)."""
    doc_freq = {}
    for entry in index:
        for stem in entry["stems"]:
            doc_freq[stem] = doc_freq.get(stem, 0) + 1
    n_docs = max(len(index), 1)
    return {stem: math.log((n_docs + 1) / (df + 1)) + 1 for stem, df in doc_freq.items()}


_index = None
_idf = None


def configure(
    *, questions: dict, physics_questions: dict, chemistry_theory: dict,
    chemistry_theory_tickets: dict, chemistry_practice_tickets: dict, anatomy: dict,
) -> None:
    """Вызывается один раз при старте бота, после загрузки JSON-файлов — строит индекс и IDF-веса
    сразу (не лениво), чтобы разовая задержка (~0.1с на текущем объёме) не попала на первый живой
    AI-запрос пользователя. Содержимое исходных словарей не меняется во время работы бота."""
    global _index, _idf
    _index = build_index(
        questions=questions, physics_questions=physics_questions, chemistry_theory=chemistry_theory,
        chemistry_theory_tickets=chemistry_theory_tickets,
        chemistry_practice_tickets=chemistry_practice_tickets, anatomy=anatomy,
    )
    _idf = build_stem_idf(_index)


def _score_entries(query_text: str, index: list, idf: dict) -> list:
    """Возвращает [(score, entry), ...], не отсортировано и без обрезки по limit — общая часть
    для search_snippets (один запрос целиком) и search_snippets_multi (по отдельным пунктам
    списка). score — НОРМАЛИЗОВАННЫЙ IDF-балл (сумма весов общих слов / число стеммов в запросе,
    см. MIN_SCORE) — без обращения к модели, чистое сравнение множеств."""
    query_stems = {_word_stem(w) for w in _extract_words(query_text) if len(w) >= 4}
    if not query_stems:
        return []
    scored = []
    for entry in index:
        common = query_stems & entry["stems"]
        if len(common) < MIN_COMMON_STEMS:
            continue
        score = sum(idf.get(stem, 0.0) for stem in common) / len(query_stems)
        if score >= MIN_SCORE:
            scored.append((score, entry))
    return scored


def search_snippets(query_text: str, limit: int = TOP_K) -> list:
    """Возвращает до `limit` наиболее релевантных записей индекса для ОДНОГО запроса целиком.
    Требует предварительного configure() — до этого индекс пуст, вернёт []."""
    scored = _score_entries(query_text, _index or [], _idf or {})
    scored.sort(key=lambda x: -x[0])
    return [entry for _, entry in scored[:limit]]


def search_snippets_multi(answer_text: str, limit: int = TOP_K) -> list:
    """Как search_snippets, но для многопунктных ответов (список из нескольких терминов)
    сначала бьёт текст на отдельные пункты и ищет по КАЖДОМУ пункту отдельно, а не по всему ответу
    разом. Иначе короткое упоминание одного термина (например, «Плевра») тонет в общем запросе из
    8-13 разных структур из разных систем органов и не проходит порог релевантности ни для одной
    темы — реально наблюдалось: поиск по всему списку целиком находил 0 совпадений, хотя половина
    терминов по отдельности легко находится в базе. Дедуп по (subject, title) с сохранением
    лучшего балла, до `limit` записей суммарно по всем пунктам."""
    items = [p.strip() for p in LIST_MARKER_RE.split(answer_text) if p.strip()]
    if len(items) < 2:
        return search_snippets(answer_text, limit=limit)
    index, idf = _index or [], _idf or {}
    best_by_key = {}
    for item in items:
        for score, entry in _score_entries(item, index, idf):
            key = (entry["subject"], entry["title"])
            if key not in best_by_key or score > best_by_key[key][0]:
                best_by_key[key] = (score, entry)
    scored = list(best_by_key.values())
    scored.sort(key=lambda x: -x[0])
    return [entry for _, entry in scored[:limit]]


def format_context(snippets: list) -> str:
    if not snippets:
        return ""
    blocks = []
    for s in snippets:
        text = html.unescape(_HTML_TAG_RE.sub("", s["text"]))
        if len(text) > SNIPPET_MAX_CHARS:
            text = text[:SNIPPET_MAX_CHARS] + "…"
        blocks.append(f"«{s['title']}» ({s['subject']}): {text}")
    return (
        "Материалы ВМедА по теме (используй эти формулировки и метод, если задание о том же "
        "самом; если задание про другое — просто игнорируй этот блок):\n" + "\n\n".join(blocks)
    )
