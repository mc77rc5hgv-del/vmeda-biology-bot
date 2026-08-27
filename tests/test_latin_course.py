# -*- coding: utf-8 -*-
import asyncio
import json
from pathlib import Path

from _bootstrap import tb
from scripts.course_automation.schema import validate_course


def callback_data(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row if button.callback_data]


async def main():
    root = Path(__file__).resolve().parents[1]
    latin = json.loads((root / "generated_courses" / "latin.json").read_text(encoding="utf-8"))
    law = json.loads((root / "generated_courses" / "law.json").read_text(encoding="utf-8"))
    knowledge = json.loads((root / "generated_knowledge" / "latin_ai.json").read_text(encoding="utf-8"))

    assert validate_course(latin) == []
    assert latin["course"] == 1 and law["course"] == 1
    assert latin["ai_mode"] == "latin"
    placeholder = latin["sections"][0]["lessons"][0]["content"]
    assert "за неделю до зачёта" in placeholder

    latin_index = next(i for i, course in enumerate(tb.DYNAMIC_COURSES) if course["id"] == "latin")
    keyboard = tb.get_dynamic_course_keyboard(latin_index)
    assert f"dyn_ai:{latin_index}" in callback_data(keyboard)
    assert "course_menu:1" in callback_data(keyboard)

    entries = knowledge["entries"]
    assert knowledge["visibility"] == "ai_only"
    assert len(entries) >= 100
    assert {entry["source"] for entry in entries} == {
        "ЛАТЫНЬ КЛИНИЧЕСКАЯ ТЕРМИНОЛОГИЯ.pdf", "латынь фарма.pdf", "латынь.pdf", "Словарь Л-Р.docx",
    }
    assert any(entry["method"].startswith("ocr") for entry in entries)
    assert any(entry["method"] == "text" for entry in entries)
    assert len([entry for entry in tb.ai_rag._index if entry["subject"] == "латинский язык"]) == len(entries)
    snippets, usage = await tb.ai_rag.search_for_task(
        tb.TaskRepresentation(raw_text="acetabulum"), subject_filter="латинский язык",
    )
    assert usage["input_tokens"] == 0
    assert snippets and all(item["subject"] == "латинский язык" for item in snippets)
    assert any(any(word.startswith("acetabul") for word in tb.ai_rag._extract_words(item["text"]))
               for item in snippets)

    original_available = tb.ai_provider_available
    original_quota = tb.ai_quota_ok
    original_breaker = tb.ai_circuit_breaker_tripped
    tb.ai_provider_available = lambda: True
    tb.ai_quota_ok = lambda _uid: True
    tb.ai_circuit_breaker_tripped = lambda: False

    class User: id = 88001
    class Message:
        def __init__(self): self.edits = []
        async def edit_text(self, text, **kwargs): self.edits.append((text, kwargs))
    class Callback:
        from_user = User()
        message = Message()
        answers = []
        async def answer(self, text=None, **kwargs): self.answers.append((text, kwargs))

    try:
        callback = Callback()
        await tb.begin_ai_session(callback, mode="latin")
        assert tb.AI_SESSIONS[User.id]["mode"] == "latin"
        assert "Латинский язык" in callback.message.edits[-1][0]
        tb.end_ai_session(User.id)
    finally:
        tb.ai_provider_available = original_available
        tb.ai_quota_ok = original_quota
        tb.ai_circuit_breaker_tripped = original_breaker

    print("LATIN COURSE + SPECIALIZED AI: OK")


if __name__ == "__main__":
    asyncio.run(main())
