"""Read-only Anatomapp course for the Mini App; never replaces the bot's ANATOMY bank."""

import json
from html import escape
from pathlib import Path

COURSE = json.loads(
    (Path(__file__).resolve().parent / "data/anatomapp_course.json").read_text(encoding="utf-8")
)
GROUPS = COURSE["groups"]
TOPICS = COURSE["topics"]


def group_ref(group_id):
    group = GROUPS[group_id]
    return {"id": group_id, "title": group["title"], "item_count": len(group["ids"])}


def group_detail(group_id):
    group = GROUPS[group_id]
    items = [
        {"id": tid, "title": TOPICS[tid]["data"]["name"], "order": i + 1, "total": len(group["ids"])}
        for i, tid in enumerate(group["ids"])
    ]
    refs = {item["id"]: item for item in items}
    return {
        "id": group_id,
        "title": group["title"],
        "parentId": group["parent_id"],
        "items": [] if group["subgroups"] else items,
        "subgroups": [group_ref(gid) for gid in group["subgroups"]],
        "sections": []
        if group["subgroups"]
        else [
            {"title": section["title"], "items": [refs[tid] for tid in section["ids"]]} for section in group["sections"]
        ],
    }


def material(topic_id):
    topic = TOPICS[topic_id]
    data = topic["data"]
    ids = GROUPS[topic["group_id"]]["ids"]
    index = ids.index(topic_id)
    parts = []
    if data.get("lat"):
        parts.append(f"<p><em>{escape(data['lat'])}</em></p>")
    for block in data["theory"]:
        if block["t"] == "p":
            parts.append(f"<p>{escape(block['x']).replace(chr(10), '<br>')}</p>")
        elif block["t"] == "ul":
            parts.append("<ul>" + "".join(f"<li>{escape(item)}</li>" for item in block["items"]) + "</ul>")
        else:
            raise ValueError(f"Unsupported theory block: {block['t']}")
    # Supplemental material is explicitly self-study: answers are revealed on request,
    # never submitted as scored exam results or mixed into existing exam banks.
    for heading, entries in [
        ("Карточки для самопроверки", [(c["front"], c["back"]) for c in data.get("cards", [])]),
        ("Термины и определения", [(p["term"], p["def"]) for p in data.get("pairs", [])]),
    ]:
        if entries:
            parts.append(f"<h2>{heading}</h2>")
            for question, answer in entries:
                parts.append(f"<details><summary>{escape(question)}</summary><p>{escape(answer)}</p></details>")
    if data.get("tests"):
        parts.append("<h2>Вопросы для самопроверки</h2>")
        for test in data["tests"]:
            parts.append(
                f"<p><strong>{escape(test['q'])}</strong></p><ol>"
                + "".join(f"<li>{escape(option)}</li>" for option in test["options"])
                + "</ol>"
            )
            parts.append(
                f"<details><summary>Показать ответ</summary><p>{escape(test['options'][test['correct']])}</p></details>"
            )
    return {
        "id": topic_id,
        "title": data["name"],
        "content_html": "\n".join(parts),
        "sources": [],
        "order": index + 1,
        "total": len(ids),
        "group_id": topic["group_id"],
        "prev_id": ids[index - 1] if index else None,
        "next_id": ids[index + 1] if index + 1 < len(ids) else None,
        "media": [],
    }
