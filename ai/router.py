"""Классификация быстрого ответа (какой провайдер обрабатывает подробный разбор), детект отказа
контент-фильтра и ограниченная (не зацикленная) цепочка попыток по провайдерам."""
import logging
import re

from ai.providers import gemini as gemini_provider
from ai.providers import openai as openai_provider
from ai.providers import xai as xai_provider
from ai.rag import LIST_MARKER_RE

logger = logging.getLogger(__name__)

_PROVIDERS = {"openai": openai_provider, "grok": xai_provider, "gemini": gemini_provider}

# Grok (xAI) — задействован ТОЛЬКО на "theory_complex" (см. classify_quick_answer): развёрнутые
# теоретические/тестовые вопросы, где быстрый ответ уже не голая буква, а формулировка,
# требующая реального рассуждения — и где, по наблюдениям, Gemini иногда справляется слабее. НЕ
# трогает "problem" (расчёты и многопунктные списки) — именно микс "быстрый на одной модели,
# подробный на другой" по расчётам раньше давал расхождение в округлении (напр. 100,5°C vs
# 100,4°C на одной и той же задаче) в рамках одной сессии, что и было причиной временно
# выключить Grok целиком; теперь он используется только там, где такого риска нет. Ставь False,
# чтобы снова полностью выключить.
USE_GROK_FOR_DETAILED = True

_PROBLEM_NUMBER_RE = re.compile(r"\d[.,]\d|\d{2,}")
_ANSWER_PREFIX_RE = re.compile(r"^(ответ|answer)\s*[:\-—]?\s*", re.IGNORECASE)
LIST_ANSWER_MIN_ITEMS_FOR_OPENAI = 3  # многопунктный список терминов — держим на OpenAI целиком
THEORY_SIMPLE_MAX_WORDS = 5  # "Ответ: Б", "3) Верно" — короче этого практически гарантированно
# голый выбор варианта, а не развёрнутый факт, требующий реального рассуждения


def classify_quick_answer(answer: str) -> str:
    """Дешёвая эвристика по уже сгенерированному быстрому ответу — без единого лишнего токена.
    ai.prompts.QUICK_SUFFIX просит модель на первом ходу дать ЛИБО букву/номер варианта (тест/
    теория), ЛИБО финальный числовой результат с единицами (расчётная задача), ЛИБО (для
    вопросов с несколькими терминами) короткий пронумерованный список. Возвращает один из трёх
    типов:

    - "problem" — расчёт ИЛИ список из LIST_ANSWER_MIN_ITEMS_FOR_OPENAI+ пунктов; остаётся на
      OpenAI целиком. Список — не потому, что это расчёт, а по реальным наблюдениям: Gemini на
      многопунктных перечнях терминов даёт более короткие и местами неточные формулировки
      (например, спутал «Плевра» с «Плева»), чем OpenAI на том же вопросе. Расчёт определяется по
      дробному числу или числу из 2+ цифр (после вырезания самой нумерации пунктов, чтобы «10.»
      не путалось с результатом вычисления). Безопасный вариант по умолчанию: при сомнении не
      отправляем ответ в модель, которая на нём не проверялась.
    - "theory_simple" — голый выбор варианта («Ответ: Б», «3) Верно», не длиннее
      THEORY_SIMPLE_MAX_WORDS слов после отсечения "Ответ:"-префикса) — уходит в Gemini, дешевле
      OpenAI и не требует глубокого рассуждения, чтобы не ошибиться.
    - "theory_complex" — теоретический вопрос, где быстрый ответ уже развёрнутая формулировка
      (определение, объяснение), не просто буква — уходит в Grok, если он подключён
      (USE_GROK_FOR_DETAILED): такие вопросы требуют более сильного рассуждения, чем Gemini
      надёжно выдаёт, а платить за это здесь оправданно, в отличие от простых MCQ-ответов."""
    if len(LIST_MARKER_RE.findall(answer)) >= LIST_ANSWER_MIN_ITEMS_FOR_OPENAI:
        return "problem"
    stripped = LIST_MARKER_RE.sub("", answer)
    if _PROBLEM_NUMBER_RE.search(stripped):
        return "problem"
    core = _ANSWER_PREFIX_RE.sub("", stripped).strip()
    if len(core.split()) <= THEORY_SIMPLE_MAX_WORDS:
        return "theory_simple"
    return "theory_complex"


class AIRefusalError(RuntimeError):
    """Провайдер ответил без ошибки, но это отказ от контент-фильтра ("Извините, но я не могу
    помочь с этой просьбой"), а не реальный разбор задания — отдельный тип, чтобы вызывающий код
    не показывал этот текст как обычный ответ и не списывал за него дневную квоту пользователя."""


_REFUSAL_RE = re.compile(
    r"не могу (помочь|предоставить|ответить|обсуждать|выполнить эт)|"
    r"i (?:can'?t|cannot|am unable to|won'?t) (?:help|assist|provide|answer)",
    re.IGNORECASE,
)


def looks_like_refusal(answer: str) -> bool:
    """«Не могу» (1-е лицо, сама модель о себе) — надёжный маркер отказа; «не может»/«не могут»
    (3-е лицо, про молекулы/организмы в самом объяснении) под него не попадает. Смотрим только на
    начало ответа — отказы провайдеры дают сразу, не посреди корректного объяснения, поэтому не
    рискуем ложным срабатыванием на длинных настоящих ответах."""
    return bool(_REFUSAL_RE.search(answer[:150]))


def pick_provider(quick: bool, task_type: str) -> str:
    """Имя провайдера для ПЕРВОЙ попытки. quick=True — всегда "openai": по форме этого самого
    ответа потом определяется task_type. quick=False: "theory_simple" -> "gemini" (если
    настроен), "theory_complex" -> "grok" (если USE_GROK_FOR_DETAILED и настроен), иначе
    (расчёты, многопунктные списки, task_type=None) -> "openai" — там важна самосогласованность
    быстрого и подробного ответа одной моделью."""
    if quick:
        return "openai"
    if task_type == "theory_simple" and gemini_provider.GEMINI_API_KEY:
        return "gemini"
    if task_type == "theory_complex" and USE_GROK_FOR_DETAILED and xai_provider.get_client() is not None:
        return "grok"
    return "openai"


def build_attempts(primary: str) -> list:
    """Список провайдеров для последовательных попыток (см. try_providers) — не ретрай в цикле,
    максимум 2 попытки. primary != "openai" -> [primary, "openai"] (откат при сбое/отказе Grok
    или Gemini, если OpenAI настроен). primary == "openai" и Gemini настроен -> ["openai",
    "gemini"] — последний резерв именно на отказ контент-фильтра, даже для расчётов/списков, где
    Gemini обычно не используется: отказ пользователю хуже, чем чуть менее аккуратный, но
    реальный ответ."""
    attempts = [primary]
    if primary != "openai":
        if openai_provider.get_client() is not None:
            attempts.append("openai")
    elif gemini_provider.GEMINI_API_KEY:
        attempts.append("gemini")
    return attempts


async def try_providers(attempts: list, messages: list, max_tokens: int) -> tuple:
    """attempts — имена провайдеров в порядке приоритета (см. build_attempts). Пробует по
    очереди, пока один не ответит успешно (без исключения и без признаков отказа
    контент-фильтра) — не ретрай в цикле, максимум len(attempts) попыток, каждая на другом
    провайдере/ключе. Возвращает (provider, answer_raw, usage) первой удавшейся попытки; если
    ВСЕ попытки исчерпаны — поднимает исключение последней (обычно AIRefusalError, если дело
    было в контент-фильтре, а не в сбое сети)."""
    last_exc = None
    for provider in attempts:
        try:
            answer_raw, usage = await _PROVIDERS[provider].call(messages, max_tokens)
            # temperature=0 (внутри каждого provider.call) — для расчётных задач нужен
            # стабильный, воспроизводимый ход решения: без этого один и тот же вопрос давал
            # разный метод и разный ответ при каждом новом запросе
            if looks_like_refusal(answer_raw):
                raise AIRefusalError(f"{provider} отказался отвечать (похоже на срабатывание контент-фильтра)")
            return provider, answer_raw, usage
        except Exception as exc:
            logger.exception("%s недоступен или отказал, пробую следующий вариант, если есть", provider)
            last_exc = exc
    raise last_exc
