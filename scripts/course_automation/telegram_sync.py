import asyncio
import hashlib
import json
import os
import re
from pathlib import Path


def _require_telethon():
    try:
        from telethon import TelegramClient
    except ImportError as exc:
        raise RuntimeError("Install requirements-automation.txt before Telegram sync") from exc
    return TelegramClient


def _normalized_title(value: str) -> str:
    return re.sub(r"[^a-zа-яё0-9]", "", value.lower())


async def discover_topics(config: dict, workspace: Path) -> dict:
    TelegramClient = _require_telethon()
    from telethon.tl.functions.channels import GetForumTopicsRequest

    api_id = int(os.environ[config.get("api_id_env", "TELEGRAM_API_ID")])
    api_hash = os.environ[config.get("api_hash_env", "TELEGRAM_API_HASH")]
    session = Path(config.get("session_path", ".secrets/vmeda_course_sync"))
    session.parent.mkdir(parents=True, exist_ok=True)
    existing = {_normalized_title(title) for title in config.get("existing_subjects", [])}
    client = TelegramClient(str(session), api_id, api_hash)
    async with client:
        entity = await client.get_entity(config["chat"])
        result = await client(GetForumTopicsRequest(
            channel=entity,
            offset_date=None,
            offset_id=0,
            offset_topic=0,
            limit=100,
            q="",
        ))
    topics = [{
        "topic_id": topic.id,
        "title": topic.title,
        "closed": bool(topic.closed),
        "already_in_bot": _normalized_title(topic.title) in existing,
    } for topic in result.topics]
    output = workspace / "topic_catalog.json"
    output.write_text(json.dumps(topics, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "total": len(topics),
        "missing": sum(not topic["already_in_bot"] for topic in topics),
        "catalog": str(output),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def sync_topic(config: dict, workspace: Path) -> dict:
    TelegramClient = _require_telethon()
    api_id = int(os.environ[config.get("api_id_env", "TELEGRAM_API_ID")])
    api_hash = os.environ[config.get("api_hash_env", "TELEGRAM_API_HASH")]
    session = Path(config.get("session_path", ".secrets/vmeda_course_sync"))
    session.parent.mkdir(parents=True, exist_ok=True)
    chat = config["chat"]
    topic_id = config.get("topic_id")
    allowed = {suffix.lower() for suffix in config.get("extensions", [".pdf", ".docx", ".pptx", ".txt"])}
    state_path = workspace / "sync_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"last_message_id": 0}
    downloads = workspace / "sources"
    downloads.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    client = TelegramClient(str(session), api_id, api_hash)
    async with client:
        async for message in client.iter_messages(chat, min_id=int(state.get("last_message_id", 0)), reverse=True):
            if topic_id is not None and getattr(message, "reply_to_top_id", None) != int(topic_id):
                continue
            state["last_message_id"] = max(int(state.get("last_message_id", 0)), message.id)
            if not message.file:
                continue
            original = message.file.name or f"telegram_{message.id}{message.file.ext or ''}"
            suffix = Path(original).suffix.lower()
            if suffix not in allowed:
                continue
            target = downloads / f"{message.id}_{Path(original).name}"
            await client.download_media(message, file=target)
            records.append({
                "message_id": message.id,
                "date": message.date.isoformat(),
                "original_name": original,
                "path": str(target),
                "sha256": _sha256(target),
            })
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path = workspace / "telegram_manifest.json"
    previous = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    by_hash = {item["sha256"]: item for item in previous}
    by_hash.update({item["sha256"]: item for item in records})
    combined = sorted(by_hash.values(), key=lambda item: item["message_id"])
    manifest_path.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"downloaded": len(records), "total": len(combined), "manifest": str(manifest_path)}


def sync_topic_blocking(config: dict, workspace: Path) -> dict:
    return asyncio.run(sync_topic(config, workspace))


def discover_topics_blocking(config: dict, workspace: Path) -> dict:
    return asyncio.run(discover_topics(config, workspace))
