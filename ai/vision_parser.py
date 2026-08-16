# -*- coding: utf-8 -*-
"""Один проход через vision-модель: фото/текст задания -> TaskRepresentation. Единственное место
во всём AI-конвейере, где вообще участвует изображение — после этого шага дальше по конвейеру
(RAG, кэш точных совпадений, solver, валидатор) передаётся только текст, ни один следующий вызов
модели фото повторно не видит (см. ai/task.py, ai/prompts.VISION_PARSE_PROMPT)."""
from __future__ import annotations

import base64
import json
import logging

from ai import prompts
from ai.providers import openai as openai_provider
from ai.task import COMPLEXITY_LEVELS, TASK_TYPES, TaskRepresentation
from ai.vision import DETAIL as IMAGE_DETAIL

logger = logging.getLogger(__name__)

PARSE_MAX_TOKENS = 900  # структурированный JSON компактнее свободного текста-ответа


def _coerce_str_dict(value) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items() if k is not None and v is not None}


def _coerce_str_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if v is not None and str(v).strip()]


def _parse_json_response(raw: str) -> TaskRepresentation:
    """Максимально снисходительный разбор — модель обычно возвращает валидный JSON (response_format
    json_object это гарантирует синтаксически), но лишние/неверные по типу поля не должны ронять
    весь AI-ответ пользователю, только деградировать до менее точного TaskRepresentation."""
    data = json.loads(raw)
    subject = data.get("subject")
    if subject not in ("biology", "physics", "chemistry", "anatomy"):
        subject = None
    task_type = data.get("type")
    if task_type not in TASK_TYPES:
        task_type = "unknown"
    complexity = data.get("complexity")
    if complexity not in COMPLEXITY_LEVELS:
        complexity = None
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    return TaskRepresentation(
        subject=subject, type=task_type, complexity=complexity,
        question=str(data.get("question") or ""), options=_coerce_str_list(data.get("options")),
        values=_coerce_str_dict(data.get("values")), units=_coerce_str_dict(data.get("units")),
        subquestions=_coerce_str_list(data.get("subquestions")), confidence=confidence,
        raw_text=str(data.get("raw_text") or ""),
    )


async def parse_task(*, image_bytes: bytes | None = None, text: str | None = None) -> tuple:
    """Делает РОВНО один вызов модели (OpenAI — та же, что уже используется для быстрого ответа,
    отдельного провайдера под это заводить не нужно). Возвращает (TaskRepresentation, usage) —
    usage в том же формате {"input_tokens", "output_tokens", "provider"}, что и провайдеры, чтобы
    вызывающий код мог учесть стоимость через record_ai_cost() как обычный AI-запрос. При любой
    ошибке (сеть, не-JSON ответ, отказ модели, отсутствие ключа) возвращает деградированный
    TaskRepresentation с raw_text = исходный текст (если был) и confidence=0.0, а НЕ поднимает
    исключение — вызывающий код (ai.service.solve) должен суметь продолжить работу и на тексте
    без структуры, просто с более низкой уверенностью."""
    content = []
    content.append({"type": "text", "text": prompts.VISION_PARSE_PROMPT + (f"\n\nТекст от пользователя: {text}" if text else "")})
    if image_bytes:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": IMAGE_DETAIL},
        })
    messages = [{"role": "user", "content": content}]

    client = openai_provider.get_client()
    if client is None:
        return TaskRepresentation(raw_text=text or "", confidence=0.0), {
            "input_tokens": 0, "output_tokens": 0, "provider": "openai",
        }

    try:
        response = await client.chat.completions.create(
            model=openai_provider.MODEL, messages=messages, max_tokens=PARSE_MAX_TOKENS,
            temperature=0, response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        usage = {
            "input_tokens": getattr(response.usage, "prompt_tokens", 0) if response.usage else 0,
            "output_tokens": getattr(response.usage, "completion_tokens", 0) if response.usage else 0,
            "provider": "openai",
        }
        task = _parse_json_response(raw)
        if not task.is_usable() and text:
            task.raw_text = text
        return task, usage
    except Exception:
        logger.exception("Не удалось распарсить задание через vision-парсер, использую текст как есть")
        return TaskRepresentation(raw_text=text or "", confidence=0.0), {
            "input_tokens": 0, "output_tokens": 0, "provider": "openai",
        }
