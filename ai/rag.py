"""RAG: перед ЛЮБЫМ ответом модели (и коротким, и подробным — см. CLAUDE.md/обсуждение
архитектурных недостатков AI-режима, пункт 2: раньше база ВМедА подмешивалась только в подробный
разбор, первый быстрый ответ уходил "в общие знания модели") ищем в собственной базе бота
(вопросы/билеты, уже загруженные в память для других разделов) несколько релевантных фрагментов и
подмешиваем их в запрос к модели, чтобы формулировки и метод совпадали с тем, что реально требуют
на кафедре.

Гибридный поиск (пункт 5 того же обсуждения): базовый слой — стеммированный keyword-matching с
IDF-весами (0 токенов, чистый Python, работает всегда, даже без ключа OpenAI). Поверх него, если
доступен OPENAI_API_KEY — семантический слой на эмбеддингах (text-embedding-3-small): находит
смысловые совпадения, которые keyword-поиск пропускает (синонимы, разная формулировка вопроса и
материала). Эмбеддинги базы считаются один раз и кэшируются на диск (see build_embeddings) —
одна и та же база не переоплачивается на каждый перезапуск бота; эмбеддинг запроса считается на
каждый вызов search_for_task (недорого, один короткий текст). Деградирует грациозно на каждом
уровне: нет ключа/сети/кэша -> просто keyword-скор, как раньше.

Модуль не импортирует telegram_bot (циклический импорт) — контент передаётся в configure()
один раз при старте бота, после загрузки JSON-файлов; путь до файла кэша эмбеддингов (внутри
STATS_DIR) тоже передаётся снаружи, а не берётся из окружения напрямую."""
import hashlib
import html
import json
import logging
import math
import re

from ai.providers import openai as openai_provider

logger = logging.getLogger(__name__)

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


def _entry_key(subject: str, title: str, text: str) -> str:
    """Стабильный идентификатор записи индекса — используется ключом в кэше эмбеддингов
    (см. build_embeddings): пересобирается из содержимого, а не порядкового номера, поэтому
    переживает изменение порядка/добавление записей в исходных JSON без потери уже посчитанных
    эмбеддингов для НЕизменившихся записей."""
    return hashlib.sha256(f"{subject}\n{title}\n{text}".encode("utf-8")).hexdigest()[:24]


def build_index(
    *, questions: dict, physics_questions: dict, chemistry_theory: dict,
    chemistry_theory_tickets: dict, chemistry_practice_tickets: dict, anatomy: dict,
) -> list:
    """Собирает единый список {subject, title, text, stems, key} из банков вопросов/ответов бота:
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
        {
            "subject": subject, "title": title, "text": text, "stems": _entry_stems(title, text),
            "key": _entry_key(subject, title, text),
        }
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


# ==================== ГИБРИДНЫЙ СЛОЙ: ЭМБЕДДИНГИ (семантический поиск) ====================
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_BATCH_SIZE = 100  # сколько текстов эмбеддим за один вызов API
MIN_COSINE = 0.5  # порог семантического совпадения — эмбеддинги дают смысловую близость даже
# при полном отсутствии общих слов, поэтому порог держим консервативным: по наблюдениям для
# text-embedding-3-small >=0.5 обычно означает "та же тема", ниже — уже случайные совпадения
# общей лексики предметной области, а не реальная релевантность
SEMANTIC_SCORE_SCALE = 3.0  # приводит косинусное сходство (0..1) к той же шкале, что и
# нормализованный keyword-балл (типичные сильные совпадения 1.3-3.5, см. MIN_SCORE), чтобы два
# сигнала были сравнимы при объединении в hybrid-скор

_embeddings: dict = {}  # entry["key"] -> vector (list[float])


def _load_embeddings_cache(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_embeddings_cache(path: str, embeddings: dict) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(embeddings, f)
    except OSError:
        logger.exception("Не удалось сохранить кэш эмбеддингов RAG на диск")


async def build_embeddings(cache_path: str = None) -> None:
    """Считает эмбеддинги для всех записей ТЕКУЩЕГО индекса (после configure()), которых ещё нет
    в кэше — вызывать один раз при старте бота, желательно фоновой задачей (не блокируя запуск
    polling), т.к. на первом прогоне это может занять заметное время. Инкрементально: запись
    индексируется по содержимому (см. _entry_key), поэтому неизменившиеся записи между
    перезапусками бота не переоплачиваются и не пересчитываются — платится только за реально
    новый/изменившийся контент.

    Полностью необязательный шаг — RAG прекрасно работает и без него (просто без семантического
    слоя, только keyword/IDF, как раньше), поэтому любая ошибка (нет ключа, сеть, лимиты API)
    только логируется, не роняет бота и не блокирует обычные keyword-совпадения."""
    global _embeddings
    if cache_path:
        _embeddings = _load_embeddings_cache(cache_path)
    client = openai_provider.get_client()
    if client is None or not _index:
        return
    missing = [e for e in _index if e["key"] not in _embeddings]
    if not missing:
        return
    try:
        for i in range(0, len(missing), EMBEDDING_BATCH_SIZE):
            batch = missing[i:i + EMBEDDING_BATCH_SIZE]
            texts = [f"{e['title']}: {e['text'][:2000]}" for e in batch]
            response = await client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
            for entry, item in zip(batch, response.data):
                _embeddings[entry["key"]] = item.embedding
            if cache_path:
                _save_embeddings_cache(cache_path, _embeddings)  # сохраняем инкрементально, батч
                # за батчем — обрыв на середине (сеть/рестарт бота) не теряет уже посчитанное
        logger.info(
            "RAG: посчитаны эмбеддинги для %d новых записей базы (всего в кэше %d)",
            len(missing), len(_embeddings),
        )
    except Exception:
        logger.exception(
            "Не удалось посчитать эмбеддинги базы RAG — семантический поиск будет недоступен, "
            "keyword-поиск продолжит работать как обычно"
        )


async def _embed_query(text: str):
    """None при любой проблеме (нет ключа, сеть, лимиты) — вызывающий код просто не получает
    семантический сигнал и работает на чистом keyword-поиске, как раньше."""
    client = openai_provider.get_client()
    if client is None or not text.strip():
        return None
    try:
        response = await client.embeddings.create(model=EMBEDDING_MODEL, input=[text[:4000]])
        return response.data[0].embedding
    except Exception:
        logger.exception("Не удалось получить эмбеддинг запроса для RAG — используется только keyword-поиск")
        return None


def _cosine(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _hybrid_score_entries(query_text: str, query_embedding, index: list, idf: dict) -> list:
    """Объединяет keyword/IDF-скор (_score_entries) и семантический скор (косинус с эмбеддингом
    запроса, если он передан) — запись проходит, если пройден ХОТЯ БЫ ОДИН порог (keyword
    MIN_SCORE или семантический MIN_COSINE), итоговый скор — сумма обеих компонент (0, если
    соответствующий сигнал не сработал/недоступен)."""
    combined: dict[str, list] = {}
    for score, entry in _score_entries(query_text, index, idf):
        combined[entry["key"]] = [score, entry]
    if query_embedding:
        for entry in index:
            vector = _embeddings.get(entry["key"])
            if not vector:
                continue
            cosine = _cosine(query_embedding, vector)
            existing = combined.get(entry["key"])
            if cosine < MIN_COSINE and existing is None:
                continue
            semantic_component = cosine * SEMANTIC_SCORE_SCALE
            if existing is None:
                combined[entry["key"]] = [semantic_component, entry]
            else:
                existing[0] += semantic_component
    return [(score, entry) for score, entry in combined.values()]


async def search_for_task(task, limit: int = TOP_K) -> list:
    """Гибридный поиск (keyword+эмбеддинги, см. модульный docstring) по УЖЕ РАЗОБРАННОМУ заданию
    (ai.task.TaskRepresentation) — точка входа для нового конвейера: вызывается ДО первого ответа
    модели, и на quick, и на detailed (в отличие от старого search_snippets/search_snippets_multi,
    который участвовал только в подробном разборе). Для заданий с несколькими пунктами
    (task.type == "list" и заполнен subquestions) ищет по КАЖДОМУ пункту отдельно и объединяет
    результаты (та же идея, что и старый search_snippets_multi, но источник пунктов —
    структурированное поле парсера, а не построчный разбор уже готового ответа модели, см. пункт 3
    архитектурного разбора AI-режима — классификация должна идти по заданию, не по ответу)."""
    index, idf = _index or [], _idf or {}
    queries = task.subquestions if (task.type == "list" and task.subquestions) else [task.question_text()]
    best_by_key = {}
    for query in queries:
        if not query.strip():
            continue
        query_embedding = await _embed_query(query)
        for score, entry in _hybrid_score_entries(query, query_embedding, index, idf):
            key = (entry["subject"], entry["title"])
            if key not in best_by_key or score > best_by_key[key][0]:
                best_by_key[key] = (score, entry)
    scored = sorted(best_by_key.values(), key=lambda x: -x[0])
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
