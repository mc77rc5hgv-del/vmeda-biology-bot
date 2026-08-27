import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .extract import extract_sources
from .pipeline import load_config, publish, workspace_for
from .processor import run_codex
from .schema import load_and_validate
from .telegram_sync import discover_topics_blocking, sync_topic_blocking

mcp = FastMCP("vmeda-course-automation")


def _context(config_path: str):
    config = load_config(Path(config_path))
    return config, workspace_for(config)


@mcp.tool()
def discover_telegram_subjects(config_path: str) -> str:
    """List forum topics and mark subjects that are already present in the bot."""
    config, workspace = _context(config_path)
    return json.dumps(discover_topics_blocking(config["telegram"], workspace), ensure_ascii=False)


@mcp.tool()
def sync_telegram_topic(config_path: str) -> str:
    """Download new course files from the configured Telegram group topic."""
    config, workspace = _context(config_path)
    return json.dumps(sync_topic_blocking(config["telegram"], workspace), ensure_ascii=False)


@mcp.tool()
def extract_course_sources(config_path: str) -> str:
    """Extract text from newly downloaded PDF, DOCX, PPTX and text files."""
    _, workspace = _context(config_path)
    return json.dumps(extract_sources(workspace), ensure_ascii=False)


@mcp.tool()
def build_course_with_codex(config_path: str) -> str:
    """Run Codex over extracted sources and create a validated course specification."""
    config, workspace = _context(config_path)
    return str(run_codex(config, workspace))


@mcp.tool()
def validate_course(config_path: str) -> str:
    """Validate the generated course without modifying the bot."""
    _, workspace = _context(config_path)
    course = load_and_validate(workspace / "course_spec.json")
    return json.dumps({"valid": True, "id": course["id"], "sections": len(course["sections"])}, ensure_ascii=False)


@mcp.tool()
def publish_course(config_path: str) -> str:
    """Publish a validated course into generated_courses for the Telegram bot."""
    config, workspace = _context(config_path)
    return str(publish(config, workspace))


if __name__ == "__main__":
    mcp.run()
