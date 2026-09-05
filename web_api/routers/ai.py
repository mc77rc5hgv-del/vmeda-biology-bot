"""VMedA AI поверх HTTP -- единственный маршрут, который реально вызывает AI-пайплайн бота
(ai/vision_parser.py, ai/rag.py, ai/service.py, ai/confidence.py и т.д.), а не просто отдаёт уже
готовый JSON-контент, как остальные роутеры этого пакета. Ничего не переизобретает: тот же
tb.get_first_message_ai_answer(), те же гварды (ai_circuit_breaker_tripped/ai_quota_ok/
per-user-lock/AI_CONCURRENCY_GATE), тот же учёт стоимости, что и у бота -- см. handle_ai_text_input/
handle_ai_photo_input в telegram_bot.py, которым этот эндпоинт умышленно зеркалит порядок проверок
шаг в шаг, чтобы квота/автовыключатель/себестоимость считались ОДИНАКОВО независимо от того, кто
спрашивает -- бот или Mini App (общий stats["ai_usage"]/stats["ai_cost_totals"], ключ user_id).

Отличие от бота: здесь НЕТ многоходовой сессии (AI_SESSIONS/"Показать решение по шагам"/
уточняющие вопросы) -- экран Mini App одноразовый ("Разобрать задание" -> один ответ, см.
miniapp/src/pages/Ai.tsx), поэтому для каждого запроса собирается одноразовый локальный словарь
той же формы, что и AI_SESSIONS[user_id] (task/messages/rag_context/bucket/quick_answer), и НИКОГДА
не пишется в само AI_SESSIONS -- иначе следующее произвольное текстовое сообщение пользователя БОТУ
в Telegram неожиданно попало бы в AI-режим (is_ai_session_active смотрит именно в AI_SESSIONS)."""
import base64
import binascii
import logging

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_current_user_id, get_fresh_bot_module
from ..schemas import AiSolveRequest, AiSolveResponse

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])
logger = logging.getLogger(__name__)


def _requests_left(tb, user_id: int) -> int | None:
    return None if tb.has_unlimited_ai(user_id) else tb.ai_requests_left(user_id)


async def _acquire_or_503(tb, user_id: int):
    """Проверяет автовыключатель/квоту/лок/слот конкурентности в ТОМ ЖЕ порядке, что и бот (см.
    docstring модуля) и либо бросает подходящий HTTPException, либо возвращает уже захваченный
    lock -- вызывающий код обязан использовать его как `async with lock:` и в finally вызвать
    tb.AI_CONCURRENCY_GATE.release() РОВНО один раз."""
    if not tb.ai_provider_available():
        raise HTTPException(status_code=503, detail="AI пока не настроен на сервере.")
    if tb.ai_circuit_breaker_tripped():
        raise HTTPException(
            status_code=503,
            detail="AI временно отключён из-за высокой нагрузки — администраторы уже знают, попробуй позже.",
        )
    if not tb.ai_quota_ok(user_id):
        raise HTTPException(status_code=429, detail="На сегодня бесплатные AI-запросы закончились, попробуй завтра.")
    lock = tb._get_ai_user_lock(user_id)  # noqa: SLF001 -- тот же приватный хелпер, что и у бота
    if lock.locked():
        raise HTTPException(status_code=429, detail="Предыдущий запрос ещё обрабатывается — подожди немного.")
    if not tb.AI_CONCURRENCY_GATE.try_acquire():
        raise HTTPException(
            status_code=503,
            detail="Сейчас слишком много запросов к AI одновременно — попробуй через минуту.",
        )
    return lock


@router.post("/solve", response_model=AiSolveResponse)
async def ai_solve(
    payload: AiSolveRequest,
    user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> AiSolveResponse:
    if payload.mode not in ("text", "photo"):
        raise HTTPException(status_code=400, detail="mode должен быть 'text' или 'photo'")
    if payload.mode == "text" and not (payload.text or "").strip():
        raise HTTPException(status_code=400, detail="text пуст")
    if payload.mode == "photo" and not payload.image_base64:
        raise HTTPException(status_code=400, detail="image_base64 пуст")

    lock = await _acquire_or_503(tb, user_id)
    async with lock:
        try:
            if payload.mode == "photo":
                try:
                    raw_bytes = base64.b64decode(payload.image_base64, validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise HTTPException(status_code=400, detail="image_base64 повреждён") from exc
                image_bytes = tb.resize_image_for_ai(raw_bytes)
                task_repr, parse_usage = await tb.ai_vision_parser.parse_task(image_bytes=image_bytes)
                if parse_usage.get("input_tokens") or parse_usage.get("output_tokens"):
                    tb.record_ai_cost(parse_usage)
                clean_answer, low_confidence, note = await _solve_first_message(tb, user_id, task_repr)
            else:
                text = payload.text.strip()
                precache = tb.get_raw_text_precache_answer(text)
                if precache is not None:
                    cached_answer, _text_part = precache
                    clean_answer, low_confidence, note = cached_answer, False, None
                else:
                    task_repr, parse_usage = await tb.ai_vision_parser.parse_task(text=text)
                    if parse_usage.get("input_tokens") or parse_usage.get("output_tokens"):
                        tb.record_ai_cost(parse_usage)
                    clean_answer, low_confidence, note = await _solve_first_message(tb, user_id, task_repr)
                    tb.record_raw_text_alias(text, task_repr)
        except tb.AIRefusalError as exc:
            logger.warning("AI отказался ответить пользователю %s через Mini App", user_id)
            tb.record_ai_attempts_cost(getattr(exc, "ai_attempts_log", []))
            raise HTTPException(
                status_code=422,
                detail=(
                    "AI отказался отвечать на это задание — похоже, сработал фильтр содержимого "
                    "провайдера. Эта попытка не списана с дневного лимита — попробуй переформулировать "
                    "вопрос или прислать его текстом."
                ),
            ) from exc
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Ошибка при обработке AI-запроса из Mini App от пользователя %s", user_id)
            tb.record_ai_attempts_cost(getattr(exc, "ai_attempts_log", []))
            raise HTTPException(status_code=500, detail="Не удалось получить ответ от AI. Попробуй ещё раз позже.") from exc
        finally:
            tb.AI_CONCURRENCY_GATE.release()

    requests_left = _requests_left(tb, user_id)
    return AiSolveResponse(
        answer_html=tb.ai_service.format_answer_html(clean_answer),
        low_confidence=low_confidence,
        confidence_note=note,
        requests_left=requests_left,
        session_active=requests_left is None or requests_left > 0,
    )


async def _solve_first_message(tb, user_id: int, task_repr) -> tuple[str, bool, str | None]:
    """Обёртка над tb.get_first_message_ai_answer с тем же одноразовым session-словарём, что и
    AI_SESSIONS[user_id] у бота (см. docstring модуля) -- возвращает (чистый_ответ_без_пометки,
    low_confidence, текст_пометки_или_None). session["quick_answer"], которое выставляет сама
    get_first_message_ai_answer, -- это ИСХОДНЫЙ ответ без AI_LOW_CONFIDENCE_NOTE; если
    возвращённый display_answer с ним не совпал, значит пометка низкой уверенности была дописана
    -- сравнение строк вместо повторной реализации confidence-логики, которая уже целиком прожита
    внутри get_first_message_ai_answer (см. её собственный докстринг про ai.confidence.decide)."""
    session = {
        "task": task_repr, "messages": [], "rag_context": None, "bucket": tb.ai_router.route_bucket(task_repr),
        "quick_answer": None,
    }
    display_answer, _user_turn = await tb.get_first_message_ai_answer(user_id, session, task_repr)
    clean_answer = session.get("quick_answer") or display_answer
    low_confidence = display_answer != clean_answer
    note = tb.AI_LOW_CONFIDENCE_NOTE.strip() if low_confidence else None
    return clean_answer, low_confidence, note
