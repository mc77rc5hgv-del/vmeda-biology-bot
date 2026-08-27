import argparse
import json
import shutil
from pathlib import Path

from .extract import extract_sources
from .processor import run_codex
from .schema import load_and_validate
from .telegram_sync import discover_topics_blocking, sync_topic_blocking

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_config(path: Path) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    for key in ("slug", "title", "telegram"):
        if key not in config:
            raise ValueError(f"Missing config field: {key}")
    return config


def workspace_for(config: dict) -> Path:
    root = Path(config.get("workspace_root", ".course-automation"))
    if not root.is_absolute():
        root = REPO_ROOT / root
    workspace = root / config["slug"]
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def publish(config: dict, workspace: Path) -> Path:
    source = workspace / "course_spec.json"
    course = load_and_validate(source)
    if course["id"] != config["slug"]:
        raise ValueError("course_spec.json id does not match config slug")
    destination_dir = REPO_ROOT / "generated_courses"
    destination_dir.mkdir(exist_ok=True)
    destination = destination_dir / f"{config['slug']}.json"
    shutil.copy2(source, destination)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a VMEDA course from a Telegram topic")
    parser.add_argument(
        "command",
        choices=["discover", "sync", "extract", "process", "validate", "publish", "run-all"],
    )
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    config = load_config(args.config)
    workspace = workspace_for(config)
    result = None
    if args.command == "discover":
        result = discover_topics_blocking(config["telegram"], workspace)
        print(json.dumps(result, ensure_ascii=False))
    if args.command in {"sync", "run-all"}:
        result = sync_topic_blocking(config["telegram"], workspace)
        print(json.dumps(result, ensure_ascii=False))
    if args.command in {"extract", "run-all"}:
        result = extract_sources(workspace)
        print(json.dumps(result, ensure_ascii=False))
    if args.command in {"process", "run-all"}:
        result = run_codex(config, workspace)
        print(result)
    if args.command == "validate":
        load_and_validate(workspace / "course_spec.json")
        print("VALID")
    if args.command in {"publish", "run-all"}:
        result = publish(config, workspace)
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
