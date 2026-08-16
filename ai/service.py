"""Оркестрация одного AI-запроса: собирает сообщение (текст/фото + сжатая история + RAG-контекст),
выбирает провайдера через ai.router и возвращает готовый, очищенный ответ."""
import base64
import re

from ai import prompts, router
from ai.vision import DETAIL as IMAGE_DETAIL

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
# сессии растёт почти квадратично: на каждый ход модели заново пересылается исходное фото и вся
# переписка целиком
HISTORY_SUMMARY_CHARS = 220  # до скольки символов ужимаем СТАРЫЕ ответы ассистента в истории —
# самый свежий ответ всегда остаётся полным (модели он ещё может понадобиться целиком для
# уточняющего вопроса), а более ранние в диалоге почти всегда нужны только как факт "это уже
# решено и таким был ответ", не дословно


def _compact_history(history: list) -> list:
    """Ужимает историю перед пересылкой модели, поверх среза по HISTORY_MAX_MESSAGES: у
    пользовательских ходов убираем фото (самое дорогое по входным токенам — метка text заменяет
    реальную картинку), у всех ответов ассистента, кроме самого последнего, обрезаем текст до
    HISTORY_SUMMARY_CHARS. Модели для продолжения диалога почти всегда достаточно краткой памяти
    "что уже спросили и что уже ответили", а не полного текста каждого раунда заново — это и есть
    основной резерв экономии токенов в многоходовых сессиях.

    Исключение — САМЫЙ ПОСЛЕДНИЙ ход пользователя: его фото НЕ трогаем. Кнопка «Показать
    решение» и обычные текстовые уточнения сами не пересылают фото повторно — они рассчитывают
    на то, что оно ещё есть в history последнего раунда. Если срезать его и там, модель отвечает
    "не вижу фото задания" вместо разбора — именно этот баг тут и чинится."""
    trimmed = (history or [])[-HISTORY_MAX_MESSAGES:]
    last_assistant_idx = max(
        (i for i, m in enumerate(trimmed) if m.get("role") == "assistant"), default=-1
    )
    last_user_idx = max(
        (i for i, m in enumerate(trimmed) if m.get("role") == "user"), default=-1
    )
    compact = []
    for i, msg in enumerate(trimmed):
        role = msg.get("role")
        content = msg.get("content")
        if role == "user" and isinstance(content, list) and i != last_user_idx:
            text_parts = [p.get("text", "") for p in content if p.get("type") == "text"]
            had_image = any(p.get("type") == "image_url" for p in content)
            text = " ".join(t for t in text_parts if t).strip()
            if had_image:
                text = (text + " [ранее приложено фото задания]").strip()
            compact.append({"role": "user", "content": text or "[фото задания]"})
        elif role == "assistant" and isinstance(content, str) and i != last_assistant_idx:
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
    *, image_bytes: bytes = None, text: str = None, history: list = None, quick: bool = False,
    task_type: str = None, rag_context: str = None,
) -> tuple:
    """history — предыдущие ходы этого диалога (без системного промпта, он добавляется здесь же),
    в формате messages OpenAI. quick=True — просит только краткий итоговый ответ на маленьком
    max_tokens (используется для самого первого сообщения новой сессии — экономит output-токены,
    которые у OpenAI дороже входных; полное решение по шагам генерируется отдельным запросом,
    только если пользователь явно нажмёт «Показать решение»). task_type —
    "theory_simple"/"theory_complex"/"problem"/None, классификация быстрого ответа этой же сессии
    (см. ai.router.classify_quick_answer) — решает, куда уходит подробный разбор (quick=False):
    "theory_simple" в Gemini, "theory_complex" в Grok (если ai.router.USE_GROK_FOR_DETAILED),
    иначе OpenAI; на quick=True не влияет, короткий ответ всегда на OpenAI, он же и определяет
    task_type. rag_context — готовый текст материалов ВМедА (см. ai.rag.format_context),
    подмешивается ТОЛЬКО в отправляемый запрос при quick=False и НИКОГДА не попадает в
    возвращаемый user_turn — иначе он бы каждый раз заново пересылался из истории на следующих
    ходах сессии, как раньше раздувало фото/длинные ответы (см. _compact_history). Возвращает
    (ответ, user_turn, usage) — user_turn нужен вызывающему коду, чтобы дописать этот ход в
    историю сессии вместе с ответом ассистента; usage — {"input_tokens", "output_tokens",
    "provider"} для учёта стоимости."""
    text_part = text or ""
    if quick:
        text_part = (text_part + prompts.QUICK_SUFFIX) if text_part else prompts.QUICK_SUFFIX.strip()
    content = []
    if text_part:
        content.append({"type": "text", "text": text_part})
    if image_bytes:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": IMAGE_DETAIL},
        })
    if not content:
        raise ValueError("Нет ни текста, ни фото для решения")

    user_turn = {"role": "user", "content": content}  # то, что вернётся вызывающему и уйдёт в историю

    send_content = content
    if not quick and rag_context:
        rag_text = f"{rag_context}\n\n{text_part}" if text_part else rag_context
        send_content = [{"type": "text", "text": rag_text}] + [b for b in content if b.get("type") != "text"]

    trimmed_history = _compact_history(history)
    messages = [
        {"role": "system", "content": prompts.SYSTEM_PROMPT},
        *trimmed_history,
        {"role": "user", "content": send_content},
    ]
    max_tokens = QUICK_MAX_TOKENS if quick else DETAILED_MAX_TOKENS

    primary = router.pick_provider(quick, task_type)
    attempts = router.build_attempts(primary)
    provider, answer_raw, usage = await router.try_providers(attempts, messages, max_tokens)

    answer = clean_answer(answer_raw)
    if len(answer) > ANSWER_TELEGRAM_LIMIT:
        answer = answer[:ANSWER_TELEGRAM_LIMIT] + "…\n\n(ответ обрезан)"
    usage["provider"] = provider
    return answer, user_turn, usage


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
