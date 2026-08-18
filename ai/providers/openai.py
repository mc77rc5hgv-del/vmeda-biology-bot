"""OpenAI provider — gpt-4o-mini. Always used for the quick answer, and stays the sole
provider (both quick and detailed) for calculation problems and multi-item lists, where
self-consistency between the two steps matters. Also the default fallback target when
Grok/Gemini fail or refuse (see ai.router)."""
import os

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # без него AI-раздел показывает "временно недоступен"
MODEL = "gpt-4o-mini"
PRICE_INPUT_PER_1M = 0.15   # $/1M input tokens — держать в синхроне с реальным прайсом OpenAI
PRICE_OUTPUT_PER_1M = 0.60  # $/1M output tokens
REQUEST_TIMEOUT_SECONDS = 30  # без этого SDK по умолчанию ждёт до 10 минут — зависший запрос
                               # держал бы AI_USER_LOCKS/concurrency-слот, а ai.router.try_providers
                               # не переходил бы к следующему провайдеру

_client = None


def get_client():
    """Ленивая инициализация клиента — импортируем openai только когда он реально нужен,
    и только если ключ вообще задан (иначе AI-раздел просто показывает "недоступен")."""
    global _client
    if _client is None and OPENAI_API_KEY:
        from openai import AsyncOpenAI
        _client = AsyncOpenAI(api_key=OPENAI_API_KEY, timeout=REQUEST_TIMEOUT_SECONDS)
    return _client


async def call(messages: list, max_tokens: int, model: str = None) -> tuple:
    """Возвращает (текст_ответа, usage) — usage {"input_tokens", "output_tokens"}."""
    client = get_client()
    if client is None:
        raise RuntimeError("OpenAI недоступен: не задан OPENAI_API_KEY")
    response = await client.chat.completions.create(
        model=model or MODEL, messages=messages, max_tokens=max_tokens, temperature=0,
    )
    answer = response.choices[0].message.content or "Не удалось получить ответ от AI."
    usage = {
        "input_tokens": getattr(response.usage, "prompt_tokens", 0) if response.usage else 0,
        "output_tokens": getattr(response.usage, "completion_tokens", 0) if response.usage else 0,
    }
    return answer, usage
