"""Build a traceable, deduplicated biochemistry corpus for VMedA AI."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COURSE = REPO / "generated_courses" / "biochemistry.json"
OUTPUT = REPO / "generated_knowledge" / "biochemistry_ai.json"
INCLUDED = {
    "introduction", "core_course", "complete_notes", "practicum", "control_1",
    "control_2", "control_2_boundary", "control_3", "credit", "exam_tickets",
}


def clean_html(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(value)).strip()


def chunks(value: str, limit: int = 1500) -> list[str]:
    units = [unit.strip() for unit in re.split(r"\n{2,}|(?<=[.!?])\s+(?=[А-ЯA-Z])", value) if unit.strip()]
    result, current = [], ""
    for unit in units:
        pieces = [unit[i:i + limit] for i in range(0, len(unit), limit)]
        for piece in pieces:
            candidate = f"{current}\n{piece}".strip()
            if current and len(candidate) > limit:
                result.append(current)
                current = piece
            else:
                current = candidate
    if current:
        result.append(current)
    return result


def main() -> None:
    course = json.loads(COURSE.read_text(encoding="utf-8"))
    entries, seen = [], set()
    for section in course["sections"]:
        if section["id"] not in INCLUDED:
            continue
        for item in section["lessons"]:
            text = clean_html(item["content"])
            if len(text) < 80:
                continue
            for part, fragment in enumerate(chunks(text), 1):
                fingerprint = re.sub(r"\W+", "", fragment).casefold()
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                source = item.get("sources", ["Биохимия"])[0]
                entries.append({
                    "subject": "биохимия",
                    "title": f"{section['title']}: {item['title']}, фрагмент {part}",
                    "text": fragment,
                    "source": source.split(",")[0],
                    "locator": source.partition(",")[2].strip() or "раздел курса",
                    "method": "verified_course_text",
                })
    if len(entries) < 300:
        raise RuntimeError(f"Biochemistry corpus unexpectedly small: {len(entries)}")
    OUTPUT.write_text(json.dumps({
        "subject": "biochemistry", "visibility": "ai_only", "entries": entries,
        "quality": {"deduplicated": True, "assessment_without_answers_excluded": True},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"entries": len(entries), "characters": sum(len(e["text"]) for e in entries)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
