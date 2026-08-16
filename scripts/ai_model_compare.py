#!/usr/bin/env python3
"""Standalone quality benchmark: gpt-4o-mini vs Gemini 2.5 Flash-Lite on real exam-style
photos/questions, run side by side so a human can judge which answers are actually better.

DELIBERATELY NOT part of the bot (telegram_bot.py / requirements.txt) or the deployed bot
process on Railway -- it has its own dependencies (see ai_model_compare.requirements.txt)
so it can never conflict with aiogram's pinned pydantic version or otherwise affect the live
bot. Run it locally / in a scratch environment, never wired into Telegram.

Usage:
    pip install -r scripts/ai_model_compare.requirements.txt
    export OPENAI_API_KEY=...
    export GEMINI_API_KEY=...
    python3 scripts/ai_model_compare.py photo1.jpg photo2.jpg "Что такое диффузия?"

Each argument is either a path to an image file or a plain-text question. Results are
printed to stdout and also written to ai_model_compare_results.txt next to this script.
"""
import asyncio
import base64
import os
import sys
from pathlib import Path

OPENAI_MODEL = "gpt-4o-mini"
GEMINI_MODEL = "gemini-flash-lite-latest"  # gemini-2.5-flash-lite вернул 404 для новых API-ключей

# Same system prompt as the live bot's AI feature (telegram_bot.py, AI_SYSTEM_PROMPT) --
# kept as a plain copy here on purpose, so this script never has to import telegram_bot.py
# (which would pull in aiogram, BOT_TOKEN, and every content JSON file just to run a benchmark).
SYSTEM_PROMPT = (
    "Ты — AI-помощник для студентов ВМедА (Военно-медицинская академия им. С.М. Кирова), "
    "помогаешь готовиться к вступительным и текущим экзаменам по биологии, физике и химии. "
    "Пользователь прислал фото или текст задания, теста, билета или контрольной. Определи, что "
    "это за задание, и дай решение: сначала кратко укажи итоговый ответ, затем поясни ход решения "
    "по шагам. Если это тест с вариантами ответа — явно укажи букву/номер правильного варианта. "
    "Если не уверен в ответе — прямо скажи об этом, не выдавай догадку за точный факт. "
    "Отвечай на русском языке, без markdown-разметки (обычный текст)."
)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def load_case(arg: str) -> dict:
    path = Path(arg)
    if path.suffix.lower() in IMAGE_EXTENSIONS and path.is_file():
        return {"label": path.name, "image_bytes": path.read_bytes(), "text": None}
    return {"label": arg[:40], "image_bytes": None, "text": arg}


async def ask_openai(case: dict) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "(пропущено — OPENAI_API_KEY не задан)"
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=api_key)
    content = []
    if case["text"]:
        content.append({"type": "text", "text": case["text"]})
    if case["image_bytes"]:
        b64 = base64.b64encode(case["image_bytes"]).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    try:
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            max_tokens=1500,
        )
        return response.choices[0].message.content or "(пустой ответ)"
    except Exception as e:
        return f"(ошибка: {e})"


async def ask_gemini(case: dict) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "(пропущено — GEMINI_API_KEY не задан)"
    from google import genai
    from google.genai import types
    # trust_env=True — иначе aiohttp внутри SDK игнорирует HTTPS_PROXY и не может достучаться
    # до Google из окружений с обязательным исходящим прокси.
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(async_client_args={"trust_env": True}),
    )
    parts = []
    if case["text"]:
        parts.append(case["text"])
    if case["image_bytes"]:
        parts.append(types.Part.from_bytes(data=case["image_bytes"], mime_type="image/jpeg"))
    try:
        response = await client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=parts,
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, max_output_tokens=1500),
        )
        return response.text or "(пустой ответ)"
    except Exception as e:
        return f"(ошибка: {e})"


async def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cases = [load_case(arg) for arg in sys.argv[1:]]
    lines = []
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['label']} ...", file=sys.stderr)
        openai_answer, gemini_answer = await asyncio.gather(ask_openai(case), ask_gemini(case))
        block = (
            f"{'=' * 70}\n"
            f"ЗАДАНИЕ {i}: {case['label']}\n"
            f"{'=' * 70}\n\n"
            f"--- gpt-4o-mini (OpenAI) ---\n{openai_answer}\n\n"
            f"--- gemini-2.5-flash-lite (Gemini) ---\n{gemini_answer}\n"
        )
        lines.append(block)
        print(block)

    out_path = Path(__file__).with_name("ai_model_compare_results.txt")
    out_path.write_text("\n\n".join(lines), encoding="utf-8")
    print(f"\nРезультаты сохранены в {out_path}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
