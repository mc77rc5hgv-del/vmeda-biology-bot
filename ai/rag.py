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
import unicodedata

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
    normalized = unicodedata.normalize("NFKD", (text or "").lower().replace("ё", "е"))
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.findall(r"[a-zа-я]+", normalized)


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


RK_CHUNK_CHAR_BUDGET = 500  # заметно меньше SNIPPET_MAX_CHARS (600, см. format_context) —
# каждый рубежный контроль это ~250-450 мелких text/table узлов (реальные вопрос-ответ пары
# кафедрального экзамена), а format_context показывает модели только ПЕРВЫЕ SNIPPET_MAX_CHARS
# символов совпавшей записи: индексировать целый контроль ОДНОЙ записью означало бы, что любой
# факт за пределами первых ~600 символов огромного блоба физически никогда не попадёт в ответ,
# даже если именно он совпал по запросу. Чанки размером ~500 символов почти всегда укладываются
# в лимит показа целиком (вопрос + короткий ответ), не обрезаясь на середине.


def _render_rk_table_for_rag(block: dict) -> str:
    lines = [block["caption"]]
    for row in block["rows"]:
        lines.append(" | ".join(row))
    return "\n".join(lines)


def _chunk_rk_blocks(blocks: list) -> list:
    """Жадно группирует подряд идущие text/table узлы рубежного контроля в чанки ~500 символов
    для RAG-индекса — та же идея, что build_rk_pages() в handlers/physiology.py (никогда не
    разрезает один узел, картинки пропускаются — это готовые фото-изображения без текста,
    индексировать нечего), только с существенно меньшим бюджетом под RAG-сниппет, а не под
    целое Telegram-сообщение."""
    chunks = []
    current: list = []
    current_len = 0

    def flush():
        nonlocal current_len
        if current:
            chunks.append("\n\n".join(current))
            current.clear()
            current_len = 0

    for block in blocks:
        if block["type"] == "image":
            continue
        piece = block["text"] if block["type"] == "text" else _render_rk_table_for_rag(block)
        if current and current_len + 2 + len(piece) > RK_CHUNK_CHAR_BUDGET:
            flush()
        current.append(piece)
        current_len += len(piece) + 2
    flush()
    return chunks


def build_index(
    *, questions: dict, physics_questions: dict, chemistry_theory: dict,
    chemistry_theory_tickets: dict, chemistry_practice_tickets: dict, anatomy: dict,
    operative_surgery: dict = None, physiology: dict = None, extra_entries: list = None,
) -> list:
    """Собирает единый список {subject, title, text, stems, key} из банков вопросов/ответов бота:
    биология/физика/химия (основная заявленная область AI-помощника) и анатомия (вопросы по
    ней реально задают через этот же AI-режим, и без точных терминов из ANATOMY модель на них
    иногда путает термины по памяти). operative_surgery — тем же путём: каждая тема (v2 —
    полнотекстовый материал по 61 теме, не сводка-заглушка, см. CLAUDE.md) индексируется целиком
    (текст всех подтем темы склеен в одну запись), плюс каждая проекция из справочника —
    инструменты/практические станции не индексируются (это голые списки названий без
    объяснительного текста, отвечать по ним нечем). physiology — по одной записи на тему,
    склеенной из sections[] (полнотекстовое содержимое темы), плюс отдельные записи на каждое
    ключевое определение — definitions дают точные, короткие, легко цитируемые формулировки
    терминов, которые полезно находить отдельно от общего текста темы. physiology тем же путём
    даёт boundary_controls (11 реальных рубежных контролей кафедры, см. CLAUDE.md) — каждый
    контроль режется на чанки ~500 символов (_chunk_rk_blocks, картинки без текста пропускаются),
    не индексируется одной огромной записью на контроль: format_context() показывает модели
    только первые SNIPPET_MAX_CHARS символов совпавшей записи, так что мелкие точные чанки —
    единственный способ, которым реальный факт из середины/конца контроля вообще может попасть
    в ответ модели."""
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
    for topic in (operative_surgery or {}).get("topics", []):
        full_text = "\n".join(sub.get("text", "") for sub in topic.get("subtopics", []))
        if full_text.strip():
            raw_entries.append(("оперативная хирургия", topic["title"], full_text))
    for group in (operative_surgery or {}).get("projections", []):
        for item in group.get("items", []):
            raw_entries.append(("оперативная хирургия", item["structure"], item["projection"]))
    for topic in (physiology or {}).get("topics", []):
        full_text = "\n".join(s.get("text", "") for s in topic.get("sections", []))
        if full_text.strip():
            raw_entries.append(("нормальная физиология", topic["title"], full_text))
        for d in topic.get("definitions", []):
            raw_entries.append(("нормальная физиология", d["term"], d["text"]))
    for control in (physiology or {}).get("boundary_controls", []):
        for i, chunk_text in enumerate(_chunk_rk_blocks(control["blocks"]), start=1):
            raw_entries.append(("нормальная физиология", f"{control['title']}, ч. {i}", chunk_text))
    for entry in extra_entries or []:
        raw_entries.append((entry.get("subject", ""), entry.get("title", ""), entry.get("text", "")))
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
    operative_surgery: dict = None, physiology: dict = None, extra_entries: list = None,
) -> None:
    """Вызывается один раз при старте бота, после загрузки JSON-файлов — строит индекс и IDF-веса
    сразу (не лениво), чтобы разовая задержка (~0.1с на текущем объёме) не попала на первый живой
    AI-запрос пользователя. Содержимое исходных словарей не меняется во время работы бота."""
    global _index, _idf
    _index = build_index(
        questions=questions, physics_questions=physics_questions, chemistry_theory=chemistry_theory,
        chemistry_theory_tickets=chemistry_theory_tickets,
        chemistry_practice_tickets=chemistry_practice_tickets, anatomy=anatomy,
        operative_surgery=operative_surgery, physiology=physiology, extra_entries=extra_entries,
    )
    _idf = build_stem_idf(_index)


def _score_entries(query_text: str, index: list, idf: dict, min_common_stems: int = MIN_COMMON_STEMS) -> list:
    """Возвращает [(score, entry), ...], не отсортировано и без обрезки по limit — общая часть
    для search_snippets (один запрос целиком) и search_snippets_multi (по отдельным пунктам
    списка). score — НОРМАЛИЗОВАННЫЙ IDF-балл (сумма весов общих слов / число стеммов в запросе,
    см. MIN_SCORE) — без обращения к модели, чистое сравнение множеств."""
    query_stems = {_word_stem(w) for w in _extract_words(query_text) if len(w) >= 4}
    if not query_stems:
        return []
    # A long pasted list is not one semantic query: with large subject corpora it can overlap a
    # random long lesson on enough generic medical terms to produce false grounding. Structured
    # list tasks are searched item-by-item by search_for_task(), so reject only the diffuse blob.
    if len(query_stems) > 60:
        return []
    scored = []
    for entry in index:
        common = query_stems & entry["stems"]
        if len(common) < min_common_stems:
            continue
        score = sum(idf.get(stem, 0.0) for stem in common) / len(query_stems)
        if score >= MIN_SCORE:
            scored.append((score, entry))
    return scored


# ==================== ГИБРИДНЫЙ СЛОЙ: ЭМБЕДДИНГИ (семантический поиск) ====================
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_PRICE_PER_1M = 0.02  # $/1M токенов — держать в синхроне с прайсом OpenAI; эмбеддинги
# биллятся только по входным токенам, отдельной "output"-цены у них нет
EMBEDDING_BATCH_SIZE = 100  # сколько текстов эмбеддим за один вызов API
MIN_COSINE = 0.5  # порог семантического совпадения — эмбеддинги дают смысловую близость даже
# при полном отсутствии общих слов, поэтому порог держим консервативным: по наблюдениям для
# text-embedding-3-small >=0.5 обычно означает "та же тема", ниже — уже случайные совпадения
# общей лексики предметной области, а не реальная релевантность
SEMANTIC_SCORE_SCALE = 3.0  # приводит косинусное сходство (0..1) к той же шкале, что и
# нормализованный keyword-балл (типичные сильные совпадения 1.3-3.5, см. MIN_SCORE), чтобы два
# сигнала были сравнимы при объединении в hybrid-скор
MAX_RAG_QUERIES = 8  # верхний предел числа отдельных "запросов" на одно задание — без него
# task.type=="list" с большим числом task.subquestions (vision-парсер в принципе может выделить
# и 20-30 пунктов из сложного многосоставного задания) отправлял бы по отдельному embedding-
# запросу на КАЖДЫЙ пункт; теперь не только ограничено сверху, но и все запросы уходят ОДНИМ
# батч-вызовом API (см. _embed_queries), а не по одному на пункт

MAX_EMBEDDING_BUILD_ITEMS_PER_START = 500  # верхний бюджет build_embeddings() ЗА ОДИН вызов
# (обычно — за один старт бота) по умолчанию, если вызывающий код не передал свой max_items.
# Без этого потерянный/повреждённый/не-персистентный кэш-файл (или бот в crash-loop) на КАЖДОМ
# рестарте пытался бы заново оплатить эмбеддинги ВСЕЙ базы разом. С бюджетом полный пересчёт при
# потере кэша растягивается на несколько рестартов подряд — каждый добивает ещё до max_items
# записей, а уже посчитанные (см. incremental-сохранение по батчам в build_embeddings) остаются
# в кэше и не переоплачиваются следующим рестартом.

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


async def build_embeddings(cache_path: str = None, max_items: int = None) -> int:
    """Считает эмбеддинги для записей ТЕКУЩЕГО индекса (после configure()), которых ещё нет
    в кэше — вызывать один раз при старте бота, желательно фоновой задачей (не блокируя запуск
    polling), т.к. на первом прогоне это может занять заметное время. Инкрементально: запись
    индексируется по содержимому (см. _entry_key), поэтому неизменившиеся записи между
    перезапусками бота не переоплачиваются и не пересчитываются — платится только за реально
    новый/изменившийся контент.

    max_items ограничивает БЮДЖЕТ этого конкретного вызова (по умолчанию —
    MAX_EMBEDDING_BUILD_ITEMS_PER_START, передайте None явно, чтобы снять ограничение вовсе) — если
    записей без эмбеддинга больше, чем max_items, эмбедятся только первые max_items, остальные
    останутся "missing" и будут подхвачены СЛЕДУЮЩИМ вызовом (обычно — следующим рестартом бота),
    а не оплачены все разом за один раз. Возвращает число реально проэмбеженных записей за этот
    вызов (0 — нет клиента/индекса/новых записей).

    Полностью необязательный шаг — RAG прекрасно работает и без него (просто без семантического
    слоя, только keyword/IDF, как раньше), поэтому любая ошибка (нет ключа, сеть, лимиты API)
    только логируется, не роняет бота и не блокирует обычные keyword-совпадения."""
    global _embeddings
    if cache_path:
        _embeddings = _load_embeddings_cache(cache_path)
    client = openai_provider.get_client()
    if client is None or not _index:
        return 0
    missing = [e for e in _index if e["key"] not in _embeddings]
    if not missing:
        return 0
    budget = MAX_EMBEDDING_BUILD_ITEMS_PER_START if max_items is None else max_items
    if budget is not None and len(missing) > budget:
        logger.warning(
            "RAG: %d записей без эмбеддинга, но бюджет этого запуска ограничен %d — остальные "
            "будут посчитаны следующим запуском build_embeddings() (обычно — следующим рестартом бота)",
            len(missing), budget,
        )
        missing = missing[:budget]
    embedded = 0
    try:
        for i in range(0, len(missing), EMBEDDING_BATCH_SIZE):
            batch = missing[i:i + EMBEDDING_BATCH_SIZE]
            texts = [f"{e['title']}: {e['text'][:2000]}" for e in batch]
            response = await client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
            for entry, item in zip(batch, response.data):
                _embeddings[entry["key"]] = item.embedding
            embedded += len(batch)
            if cache_path:
                _save_embeddings_cache(cache_path, _embeddings)  # сохраняем инкрементально, батч
                # за батчем — обрыв на середине (сеть/рестарт бота) не теряет уже посчитанное
        logger.info(
            "RAG: посчитаны эмбеддинги для %d новых записей базы (всего в кэше %d)",
            embedded, len(_embeddings),
        )
    except Exception:
        logger.exception(
            "Не удалось посчитать эмбеддинги базы RAG — семантический поиск будет недоступен, "
            "keyword-поиск продолжит работать как обычно"
        )
    return embedded


async def _embed_query(text: str):
    """None при любой проблеме (нет ключа, сеть, лимиты) — вызывающий код просто не получает
    семантический сигнал и работает на чистом keyword-поиске, как раньше. Одиночный запрос —
    для батча НЕСКОЛЬКИХ запросов одним вызовом API см. _embed_queries."""
    client = openai_provider.get_client()
    if client is None or not text.strip():
        return None
    try:
        response = await client.embeddings.create(model=EMBEDDING_MODEL, input=[text[:4000]])
        return response.data[0].embedding
    except Exception:
        logger.exception("Не удалось получить эмбеддинг запроса для RAG — используется только keyword-поиск")
        return None


async def _embed_queries(texts: list) -> tuple:
    """Батчевый эмбеддинг НЕСКОЛЬКИХ запросов ОДНИМ вызовом API вместо одного вызова на каждый
    текст — OpenAI embeddings endpoint нативно принимает список input. Возвращает
    (embeddings, usage): embeddings — список того же порядка и длины, что texts (None на месте
    пустого текста); usage — {"input_tokens", "output_tokens": 0} суммарно по батчу, чтобы
    вызывающий код мог учесть реальную стоимость (см. telegram_bot.record_ai_cost) — раньше
    стоимость эмбеддингов запроса нигде не фиксировалась. Деградирует в (все None, нулевой usage)
    при любой проблеме (нет ключа, сеть, лимиты), как и _embed_query."""
    zero_usage = {"input_tokens": 0, "output_tokens": 0}
    if not texts:
        return [], dict(zero_usage)
    client = openai_provider.get_client()
    if client is None:
        return [None] * len(texts), dict(zero_usage)
    non_empty = [(i, t) for i, t in enumerate(texts) if t.strip()]
    if not non_empty:
        return [None] * len(texts), dict(zero_usage)
    try:
        response = await client.embeddings.create(
            model=EMBEDDING_MODEL, input=[t[:4000] for _, t in non_empty],
        )
        results = [None] * len(texts)
        for (idx, _), item in zip(non_empty, response.data):
            results[idx] = item.embedding
        usage = {
            "input_tokens": getattr(response.usage, "total_tokens", 0) if response.usage else 0,
            "output_tokens": 0,
        }
        return results, usage
    except Exception:
        logger.exception("Не удалось получить батч эмбеддингов запросов для RAG — используется только keyword-поиск")
        return [None] * len(texts), dict(zero_usage)


def _cosine(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _hybrid_score_entries(
    query_text: str, query_embedding, index: list, idf: dict,
    min_common_stems: int = MIN_COMMON_STEMS,
) -> list:
    """Объединяет keyword/IDF-скор (_score_entries) и семантический скор (косинус с эмбеддингом
    запроса, если он передан) — запись проходит, если пройден ХОТЯ БЫ ОДИН порог (keyword
    MIN_SCORE или семантический MIN_COSINE), итоговый скор — сумма обеих компонент (0, если
    соответствующий сигнал не сработал/недоступен)."""
    combined: dict[str, list] = {}
    for score, entry in _score_entries(query_text, index, idf, min_common_stems=min_common_stems):
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


async def search_for_task(task, limit: int = TOP_K, subject_filter: str | None = None) -> tuple:
    """Гибридный поиск (keyword+эмбеддинги, см. модульный docstring) по УЖЕ РАЗОБРАННОМУ заданию
    (ai.task.TaskRepresentation) — точка входа для нового конвейера: вызывается ДО первого ответа
    модели, и на quick, и на detailed (в отличие от старого search_snippets/search_snippets_multi,
    который участвовал только в подробном разборе). Для заданий с несколькими пунктами
    (task.type == "list" и заполнен subquestions) ищет по КАЖДОМУ пункту отдельно и объединяет
    результаты (та же идея, что и старый search_snippets_multi, но источник пунктов —
    структурированное поле парсера, а не построчный разбор уже готового ответа модели, см. пункт 3
    архитектурного разбора AI-режима — классификация должна идти по заданию, не по ответу).

    Число отдельных запросов урезано до MAX_RAG_QUERIES (см. константу) — без этого предела
    многопунктное задание с большим числом subquestions могло бы породить непропорционально много
    embedding-запросов на один-единственный AI-запрос пользователя; все они при этом уходят ОДНИМ
    батч-вызовом API (_embed_queries), а не по одному на пункт.

    Возвращает (snippets, usage) — usage {"input_tokens", "output_tokens": 0} суммарно по всем
    embedding-запросам этого вызова (нулевой, если семантический слой не участвовал вообще — нет
    ключа, все запросы деградировали, или запросов не было), чтобы вызывающий код мог учесть
    реальную стоимость (см. telegram_bot.record_ai_cost)."""
    index = _index or []
    if subject_filter:
        index = [entry for entry in index if entry["subject"] == subject_filter]
        idf = build_stem_idf(index)
    else:
        # Private subject corpora are only available through their explicit subject mode.
        index = [entry for entry in index if entry["subject"] != "латинский язык"]
        idf = build_stem_idf(index)
    queries = task.subquestions if (task.type == "list" and task.subquestions) else [task.question_text()]
    queries = [q for q in queries if q and q.strip()][:MAX_RAG_QUERIES]
    if not queries:
        return [], {"input_tokens": 0, "output_tokens": 0}

    query_embeddings, usage = await _embed_queries(queries)

    best_by_key = {}
    for query, query_embedding in zip(queries, query_embeddings):
        min_common = 1 if subject_filter else MIN_COMMON_STEMS
        for score, entry in _hybrid_score_entries(
            query, query_embedding, index, idf, min_common_stems=min_common,
        ):
            key = (entry["subject"], entry["title"])
            if key not in best_by_key or score > best_by_key[key][0]:
                best_by_key[key] = (score, entry)
    scored = sorted(best_by_key.values(), key=lambda x: -x[0])
    return [entry for _, entry in scored[:limit]], usage


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
