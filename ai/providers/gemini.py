"""Gemini provider — прямой HTTP-вызов Gemini API, в обход google-genai SDK: он требует
pydantic>=2.12.5, несовместимую с версией, зафиксированной aiogram. Используется для
bucket=="theory_simple" (см. ai.router.route_bucket) — дешевле OpenAI и надёжен для простых
MCQ-ответов — а также как последний резерв, если OpenAI сам отказался отвечать (контент-фильтр)."""
import os
import aiohttp

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = "gemini-2.5-flash-lite"
PRICE_INPUT_PER_1M = 0.10   # $/1M input tokens — держать в синхроне с прайсом Google AI
PRICE_OUTPUT_PER_1M = 0.40  # $/1M output tokens
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _messages_to_contents(messages: list) -> tuple:
    """Gemini не понимает наш OpenAI-формат messages (roles user/assistant/system, content —
    строка или список text/image_url блоков) — у него свой contents[]/systemInstruction формат
    с ролями user/model. Возвращает (system_text, contents) — на вход всегда идёт то же самое
    messages, что строится для OpenAI/Grok (оба OpenAI-совместимы), конвертация нужна только
    на этой одной границе."""
    system_text = ""
    contents = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if role == "system":
            system_text = content if isinstance(content, str) else ""
            continue
        gemini_role = "model" if role == "assistant" else "user"
        if isinstance(content, str):
            parts = [{"text": content}]
        else:
            parts = []
            for block in content:
                if block.get("type") == "text" and block.get("text"):
                    parts.append({"text": block["text"]})
                elif block.get("type") == "image_url":
                    url = block.get("image_url", {}).get("url", "")
                    if url.startswith("data:"):
                        header, _, b64_data = url.partition(",")
                        mime_type = header[len("data:"):].split(";")[0] or "image/jpeg"
                        parts.append({"inline_data": {"mime_type": mime_type, "data": b64_data}})
            if not parts:
                parts = [{"text": ""}]
        contents.append({"role": gemini_role, "parts": parts})
    return system_text, contents


async def call(messages: list, max_tokens: int, model: str = None) -> tuple:
    """Прямой HTTP-вызов Gemini API. trust_env=True обязателен, иначе aiohttp игнорирует
    HTTPS_PROXY окружения. Возвращает (текст_ответа, usage) — usage в том же формате
    {"input_tokens", "output_tokens"}, что и у OpenAI-совместимых провайдеров."""
    system_text, contents = _messages_to_contents(messages)
    payload = {"contents": contents, "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens}}
    if system_text:
        payload["systemInstruction"] = {"parts": [{"text": system_text}]}
    url = API_URL.format(model=model or MODEL)
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(trust_env=True, timeout=timeout) as session:
        async with session.post(url, params={"key": GEMINI_API_KEY}, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    usage_meta = data.get("usageMetadata", {})
    usage = {
        "input_tokens": usage_meta.get("promptTokenCount", 0),
        "output_tokens": usage_meta.get("candidatesTokenCount", 0),
    }
    return text, usage
