"""Grok (xAI) provider — OpenAI-compatible API (same openai package, different base_url/key,
no extra dependency). Used only for bucket=="theory_complex" (see ai.router.route_bucket) —
deliberately scoped away from calculation problems: a mixed quick(OpenAI)/detailed(Grok) pair on a
multi-step calculation could round differently between the two models within one session
(observed live, e.g. 100,5°C vs 100,4°C on the same problem), which is why Grok is never used
for "problem"-classified content regardless of this module being configured."""
import os

XAI_API_KEY = os.getenv("XAI_API_KEY")
MODEL = "grok-4.3"
PRICE_INPUT_PER_1M = 1.25   # $/1M input tokens — держать в синхроне с прайсом xAI
PRICE_OUTPUT_PER_1M = 2.50  # $/1M output tokens
REQUEST_TIMEOUT_SECONDS = 30  # см. ai/providers/openai.py — тот же риск зависшего запроса

_client = None


def get_client():
    """None, если XAI_API_KEY не задан — тогда ai.router просто не выбирает Grok."""
    global _client
    if _client is None and XAI_API_KEY:
        from openai import AsyncOpenAI
        _client = AsyncOpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1", timeout=REQUEST_TIMEOUT_SECONDS)
    return _client


async def call(messages: list, max_tokens: int, model: str = None) -> tuple:
    """Возвращает (текст_ответа, usage) — usage {"input_tokens", "output_tokens"}."""
    client = get_client()
    if client is None:
        raise RuntimeError("Grok недоступен: не задан XAI_API_KEY")
    response = await client.chat.completions.create(
        model=model or MODEL, messages=messages, max_tokens=max_tokens, temperature=0,
    )
    answer = response.choices[0].message.content or "Не удалось получить ответ от AI."
    usage = {
        "input_tokens": getattr(response.usage, "prompt_tokens", 0) if response.usage else 0,
        "output_tokens": getattr(response.usage, "completion_tokens", 0) if response.usage else 0,
    }
    return answer, usage
