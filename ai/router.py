# -*- coding: utf-8 -*-
"""Роутинг провайдера по уже РАЗОБРАННОМУ заданию (см. ai.task.TaskRepresentation, ai.vision_parser
— классификация происходит ДО решения, не по форме уже полученного ответа, как раньше — см.
CLAUDE.md/обсуждение архитектурных недостатков AI-режима, пункт 3), детект отказа контент-фильтра
и ограниченная (не зацикленная) цепочка попыток по провайдерам с полным журналом попыток (в т.ч.
неудачных — пункт 9 того же обсуждения: раньше стоимость сорвавшихся попыток нигде не учитывалась)."""
import logging
import re

from ai.providers import gemini as gemini_provider
from ai.providers import openai as openai_provider
from ai.providers import xai as xai_provider
from ai.task import TaskRepresentation

logger = logging.getLogger(__name__)

_PROVIDERS = {"openai": openai_provider, "grok": xai_provider, "gemini": gemini_provider}

# Grok (xAI) — задействован ТОЛЬКО на "theory_complex" (см. route_bucket): развёрнутые
# теоретические вопросы, где требуется реальное рассуждение, и где, по наблюдениям, Gemini иногда
# справляется слабее. НЕ трогает "problem" (расчёты и многопунктные списки) — именно микс "быстрый
# на одной модели, подробный на другой" по расчётам раньше давал расхождение в округлении (напр.
# 100,5°C vs 100,4°C на одной и той же задаче) в рамках одной сессии, что и было причиной временно
# выключить Grok целиком; теперь он используется только там, где такого риска нет. Ставь False,
# чтобы снова полностью выключить.
USE_GROK_FOR_DETAILED = True


def route_bucket(task: TaskRepresentation) -> str:
    """Три "бакета" маршрутизации ПОДРОБНОГО разбора (quick=False) — определяются по типу/сложности
    самого ЗАДАНИЯ (см. ai.vision_parser.parse_task, поле "complexity" заполняется парсером по
    формулировке вопроса, а не по будущему ответу):

    - "problem" — calculation ИЛИ list (расчёт или многопунктное перечисление терминов); остаётся
      на OpenAI целиком — на списках терминов Gemini по наблюдениям давал более короткие и местами
      неточные формулировки, а расчёты требуют самосогласованности с быстрым ответом (обе стадии
      идут через OpenAI, см. pick_provider).
    - "theory_simple" — mcq/theory с complexity="simple" — уходит в Gemini, дешевле OpenAI и
      надёжен для простых фактических вопросов без глубокого рассуждения.
    - "theory_complex" — mcq/theory с complexity="complex" (или сложность не определена парсером) —
      уходит в Grok, если он подключён (USE_GROK_FOR_DETAILED): такие вопросы требуют более
      сильного рассуждения, чем Gemini надёжно выдаёт.
    """
    if task.type in ("calculation", "list"):
        return "problem"
    if task.complexity == "simple":
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


def pick_provider(quick: bool, bucket: str) -> str:
    """Имя провайдера для ПЕРВОЙ попытки. quick=True — всегда "openai" (та же модель, что делает
    vision-парсинг задания — самосогласованность между разбором и первым ответом). quick=False:
    "theory_simple" -> "gemini" (если настроен), "theory_complex" -> "grok" (если
    USE_GROK_FOR_DETAILED и настроен), иначе (расчёты, многопунктные списки) -> "openai"."""
    if quick:
        return "openai"
    if bucket == "theory_simple" and gemini_provider.GEMINI_API_KEY:
        return "gemini"
    if bucket == "theory_complex" and USE_GROK_FOR_DETAILED and xai_provider.get_client() is not None:
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
    очереди, пока один не ответит успешно (без исключения и без признаков отказа контент-фильтра)
    — не ретрай в цикле, максимум len(attempts) попыток, каждая на другом провайдере/ключе.

    Возвращает (provider, answer_raw, usage, attempts_log) первой удавшейся попытки. attempts_log
    — [{"provider", "status": "success"/"refused"/"failed", "usage"}, ...] по КАЖДОЙ попытке,
    включая неудачные — сетевой/API-сбой ("failed") не потребляет токены (запрос не дошёл до
    ответа, usage нулевой), а отказ контент-фильтра ("refused") ТОКЕНЫ ТРАТИТ (модель реально
    ответила, просто отказом) и должен учитываться в реальной себестоимости (см. CLAUDE.md,
    архитектурные недостатки AI-режима — пункт 9: раньше стоимость сорвавшихся попыток нигде не
    учитывалась). Если ВСЕ попытки исчерпаны — поднимает исключение последней (обычно
    AIRefusalError, если дело было в контент-фильтре, а не в сбое сети), с прикреплённым
    `.ai_attempts_log` атрибутом, чтобы вызывающий код мог всё равно учесть стоимость попыток."""
    attempts_log = []
    last_exc = None
    for provider in attempts:
        try:
            answer_raw, usage = await _PROVIDERS[provider].call(messages, max_tokens)
            # temperature=0 (внутри каждого provider.call) — для расчётных задач нужен
            # стабильный, воспроизводимый ход решения: без этого один и тот же вопрос давал
            # разный метод и разный ответ при каждом новом запросе
        except Exception as exc:
            attempts_log.append({"provider": provider, "status": "failed", "usage": {"input_tokens": 0, "output_tokens": 0}})
            logger.exception("%s недоступен, пробую следующий вариант, если есть", provider)
            last_exc = exc
            continue
        if looks_like_refusal(answer_raw):
            attempts_log.append({"provider": provider, "status": "refused", "usage": dict(usage)})
            logger.warning("%s отказал (похоже на срабатывание контент-фильтра), пробую следующий вариант, если есть", provider)
            last_exc = AIRefusalError(f"{provider} отказался отвечать (похоже на срабатывание контент-фильтра)")
            continue
        attempts_log.append({"provider": provider, "status": "success", "usage": dict(usage)})
        return provider, answer_raw, usage, attempts_log
    last_exc.ai_attempts_log = attempts_log
    raise last_exc
