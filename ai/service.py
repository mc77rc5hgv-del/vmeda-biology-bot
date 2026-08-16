"""Оркестрация одного AI-запроса: собирает сообщение (текст + сжатая история + RAG-контекст —
НИКОГДА фото, см. ai/vision_parser.py), выбирает провайдера через ai.router и возвращает готовый,
очищенный ответ."""
import re

from ai import prompts, router

ANSWER_TELEGRAM_LIMIT = 3500  # с запасом от лимита Telegram в 4096 символов на сообщение
QUICK_MAX_TOKENS = 550   # короткий первый ответ — только итог, без хода решения; 150 обрезал
# на середине слова вопросы с несколькими пунктами/терминами для перечисления (не тест, не
# расчёт), 400 не оставлял запаса на точные термины без чрезмерного сжатия (см. ai.prompts.
# QUICK_SUFFIX) — потолок реально расходуется только когда контент того требует: не добавляет
# токенов к обычному односложному ответу, только даёт места на многопунктных не жертвовать
# точностью ради краткости
DETAILED_MAX_TOKENS = 1500
HISTORY_MAX_MESSAGES = 6  # сколько последних сообщений истории берём как основу перед сжатием
# (см. _compact_history) — без этого потолка стоимость каждого следующего сообщения в долгой
# сессии растёт почти квадратично
HISTORY_SUMMARY_CHARS = 220  # до скольки символов ужимаем СТАРЫЕ ответы ассистента в истории —
# самый свежий ответ всегда остаётся полным (модели он ещё может понадобиться целиком для
# уточняющего вопроса), а более ранние в диалоге почти всегда нужны только как факт "это уже
# решено и таким был ответ", не дословно


def _compact_history(history: list) -> list:
    """Ужимает историю перед пересылкой модели, поверх среза по HISTORY_MAX_MESSAGES: у всех
    ответов ассистента, кроме самого последнего, обрезаем текст до HISTORY_SUMMARY_CHARS. Модели
    для продолжения диалога почти всегда достаточно краткой памяти "что уже спросили и что уже
    ответили", а не полного текста каждого раунда заново.

    В отличие от прежней версии, здесь больше нет отдельной логики про фото в user-turn'ах —
    начиная с этого рефакторинга фото вообще никогда не попадает в history (см. ai/vision_parser.py:
    оно распознаётся ОДИН раз, дальше по конвейеру передаётся только текст TaskRepresentation),
    так что все user-turn'ы здесь всегда простые строки, ужимать в них нечего."""
    trimmed = (history or [])[-HISTORY_MAX_MESSAGES:]
    last_assistant_idx = max(
        (i for i, m in enumerate(trimmed) if m.get("role") == "assistant"), default=-1
    )
    compact = []
    for i, msg in enumerate(trimmed):
        role = msg.get("role")
        content = msg.get("content")
        if role == "assistant" and isinstance(content, str) and i != last_assistant_idx:
            short = content if len(content) <= HISTORY_SUMMARY_CHARS else content[:HISTORY_SUMMARY_CHARS] + "…"
            compact.append({"role": "assistant", "content": short})
        else:
            compact.append(msg)
    return compact


# Страховка поверх системного промпта — модель иногда всё равно проскальзывает в LaTeX
# (особенно на формулах/расчётах). Чисто текстовая пост-обработка, без обращения к API,
# то есть не расходует ни единого токена.
_LATEX_CLEANUP_PATTERNS = [
    (r"\\text\{([^{}]*)\}", r"\1"),
    (r"_\{([^{}]*)\}", r"\1"),      # подстрочный индекс: K_{b} -> Kb
    (r"\^\{([^{}]*)\}", r"(\1)"),   # надстрочный индекс: SO4^{2-} -> SO4(2-)
    (r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"\1/\2"),
    (r"\\sqrt\{([^{}]*)\}", r"√(\1)"),
    (r"\\cdot", "×"),
    (r"\\times", "×"),
    (r"\\approx", "≈"),
    (r"\\neq", "≠"),
    (r"\\geq|\\ge\b", "≥"),
    (r"\\leq|\\le\b", "≤"),
    (r"\\pm", "±"),
    (r"\\Delta", "Δ"),
    (r"\\delta", "δ"),
    (r"\\alpha", "α"),
    (r"\\beta", "β"),
    (r"\\gamma", "γ"),
    (r"\\,", " "),
    (r"\\left|\\right", ""),
    (r"\\[()\[\]]", ""),   # \( \) \[ \]
    (r"\${1,2}", ""),      # стрей $ / $$ — математические разделители
    (r"\\[a-zA-Z]+", ""),  # любая оставшаяся неопознанная LaTeX-команда
]


def clean_answer(answer: str) -> str:
    for pattern, repl in _LATEX_CLEANUP_PATTERNS:
        answer = re.sub(pattern, repl, answer)
    return re.sub(r" {2,}", " ", answer)


async def solve(
    *, task=None, text: str = None, history: list = None, quick: bool = False,
    bucket: str = None, rag_context: str = None,
) -> tuple:
    """task — TaskRepresentation (см. ai.task), передаётся ТОЛЬКО на первом ходу новой сессии
    (сразу после ai.vision_parser.parse_task) — его text-представление (to_prompt_text()) и
    становится содержимым запроса; фото в этот момент уже никак не участвует, оно было
    использовано один-единственный раз внутри parse_task. Для всех последующих ходов сессии
    (кнопка «Показать решение», уточняющие вопросы) передавай text — task не нужен, он уже есть в
    history первым сообщением.

    quick=True — просит только краткий итоговый ответ на маленьком max_tokens (используется для
    самого первого сообщения новой сессии). rag_context подмешивается ВСЕГДА, когда передан — и
    на quick, и на detailed (архитектурное отличие от старой версии, где RAG участвовал только в
    подробном разборе — первый ответ пользователя должен быть сверен с базой ВМедА сразу, а не
    только после того, как он попросит подробностей).

    bucket — "problem"/"theory_simple"/"theory_complex" (см. ai.router.route_bucket(task)),
    определяет, какой провайдер обрабатывает ПОДРОБНЫЙ разбор (quick=False); на quick=True не
    влияет, короткий ответ всегда идёт на OpenAI.

    rag_context подмешивается ТОЛЬКО в то, что реально уходит модели — НИКОГДА в user_turn,
    который возвращается вызывающему и оседает в истории сессии: история не сжимает user-ходы
    (см. _compact_history — сжимаются только старые ответы ассистента), так что если бы
    rag_context попал в user_turn, он пересылался бы (и переоплачивался) заново на КАЖДОМ
    следующем ходу того же диалога — тот же класс бага, что уже был исправлен для фото (см.
    docstring модуля).

    Возвращает (ответ, user_turn, usage, attempts_log) — user_turn нужен вызывающему коду, чтобы
    дописать этот ход в историю сессии вместе с ответом ассистента; usage — {"input_tokens",
    "output_tokens", "provider"} успешной попытки; attempts_log — список ВСЕХ попыток (см.
    ai.router.try_providers), включая неудачные, для полного учёта себестоимости."""
    text_part = task.to_prompt_text() if task is not None else (text or "")
    if quick:
        text_part = (text_part + prompts.QUICK_SUFFIX) if text_part else prompts.QUICK_SUFFIX.strip()
    if not text_part:
        raise ValueError("Нет ни текста, ни разобранного задания для решения")

    user_turn = {"role": "user", "content": text_part}  # то, что вернётся вызывающему и уйдёт в историю
    sent_content = f"{rag_context}\n\n{text_part}" if rag_context else text_part

    trimmed_history = _compact_history(history)
    messages = [
        {"role": "system", "content": prompts.SYSTEM_PROMPT},
        *trimmed_history,
        {"role": "user", "content": sent_content},
    ]
    max_tokens = QUICK_MAX_TOKENS if quick else DETAILED_MAX_TOKENS

    primary = router.pick_provider(quick, bucket)
    attempts = router.build_attempts(primary)
    provider, answer_raw, usage, attempts_log = await router.try_providers(attempts, messages, max_tokens)

    answer = clean_answer(answer_raw)
    if len(answer) > ANSWER_TELEGRAM_LIMIT:
        answer = answer[:ANSWER_TELEGRAM_LIMIT] + "…\n\n(ответ обрезан)"
    usage["provider"] = provider
    return answer, user_turn, usage, attempts_log


def format_answer_html(answer: str) -> str:
    """Лёгкий markdown от модели (**жирный**, "- " списки, "### заголовки") -> реальные
    HTML-теги Telegram. Сначала экранируем ВЕСЬ текст (защита от случайного/сломанного HTML в
    ответе модели — иначе модель могла бы случайно прислать что-то вроде "<3 ммоль" и сломать
    разметку сообщения), и только потом расставляем свои теги поверх уже экранированного текста —
    значит, наши теги не попадают под повторное экранирование."""
    import html
    escaped = html.escape(answer)
    escaped = re.sub(r"(?m)^#{1,6}\s*(.+)$", r"<b>\1</b>", escaped)  # заголовки ("### X") — модели
    # (особенно Gemini) иногда используют их вопреки системному промпту, где явно просят не надо
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped, flags=re.S)
    escaped = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<i>\1</i>", escaped, flags=re.S)
    escaped = re.sub(r"^[-*]\s+", "• ", escaped, flags=re.M)
    return escaped
