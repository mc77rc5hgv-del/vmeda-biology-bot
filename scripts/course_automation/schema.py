import json
import re
from html.parser import HTMLParser
from pathlib import Path

SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
# "pre" was missing here even though scripts/reflow_generated_course_content.py already relies
# on it (table/diagram-shaped source runs get wrapped in a single <pre> block) and both render
# surfaces already accept it -- Telegram's own HTML parse_mode, and the Mini App's DOMPurify
# config (see ALLOWED_TAGS there). This validator's own allow-list had simply never been updated
# to match, so every lesson using <pre> failed validate_course() even though it renders correctly
# on both surfaces.
ALLOWED_TAGS = {"b", "i", "code", "u", "s", "pre"}


class _SafeTelegramHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in ALLOWED_TAGS or attrs:
            self.errors.append(f"unsupported HTML tag or attributes: {tag}")
            return
        self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag not in ALLOWED_TAGS or not self.stack or self.stack.pop() != tag:
            self.errors.append(f"unbalanced HTML tag: {tag}")

    def close(self) -> None:
        super().close()
        if self.stack:
            self.errors.append("unclosed HTML tags")


def validate_telegram_html(value: str) -> list[str]:
    parser = _SafeTelegramHTMLParser()
    try:
        parser.feed(value)
        parser.close()
    except Exception as exc:
        return [f"invalid HTML: {exc}"]
    return parser.errors


def validate_course(course: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(course, dict):
        return ["course must be an object"]
    slug = course.get("id")
    if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug):
        errors.append("id must match ^[a-z][a-z0-9_]{1,30}$")
    for key in ("title", "emoji", "description"):
        if not isinstance(course.get(key), str) or not course[key].strip():
            errors.append(f"{key} must be a non-empty string")
    if course.get("course", 2) not in (1, 2):
        errors.append("course must be 1 or 2")
    if course.get("ai_mode") is not None and course.get("ai_mode") not in {"latin", "pharmacology"}:
        errors.append("ai_mode is unsupported")
    sections = course.get("sections")
    if not isinstance(sections, list) or not sections:
        errors.append("sections must be a non-empty array")
        return errors
    section_ids: set[str] = set()
    lesson_ids: set[str] = set()
    for section_index, section in enumerate(sections):
        prefix = f"sections[{section_index}]"
        if not isinstance(section, dict):
            errors.append(f"{prefix} must be an object")
            continue
        section_id = section.get("id")
        if not isinstance(section_id, str) or not SLUG_RE.fullmatch(section_id):
            errors.append(f"{prefix}.id is invalid")
        elif section_id in section_ids:
            errors.append(f"duplicate section id: {section_id}")
        else:
            section_ids.add(section_id)
        if not isinstance(section.get("title"), str) or not section["title"].strip():
            errors.append(f"{prefix}.title must be non-empty")
        groups = section.get("groups")
        if groups is not None:
            if not isinstance(groups, list) or not groups:
                errors.append(f"{prefix}.groups must be a non-empty array")
                continue
            lessons = []
            for group_index, group in enumerate(groups):
                gp = f"{prefix}.groups[{group_index}]"
                if not isinstance(group, dict):
                    errors.append(f"{gp} must be an object")
                    continue
                if not isinstance(group.get("id"), str) or not SLUG_RE.fullmatch(group["id"]):
                    errors.append(f"{gp}.id is invalid")
                if not isinstance(group.get("title"), str) or not group["title"].strip():
                    errors.append(f"{gp}.title must be non-empty")
                group_lessons = group.get("lessons")
                if not isinstance(group_lessons, list) or not group_lessons:
                    errors.append(f"{gp}.lessons must be a non-empty array")
                else:
                    lessons.extend(group_lessons)
        else:
            lessons = section.get("lessons")
        if not isinstance(lessons, list) or not lessons:
            errors.append(f"{prefix}.lessons must be a non-empty array")
            continue
        for lesson_index, lesson in enumerate(lessons):
            lp = f"{prefix}.lessons[{lesson_index}]"
            if not isinstance(lesson, dict):
                errors.append(f"{lp} must be an object")
                continue
            lesson_id = lesson.get("id")
            if not isinstance(lesson_id, str) or not SLUG_RE.fullmatch(lesson_id):
                errors.append(f"{lp}.id is invalid")
            elif lesson_id in lesson_ids:
                errors.append(f"duplicate lesson id: {lesson_id}")
            else:
                lesson_ids.add(lesson_id)
            for key in ("title", "content"):
                if not isinstance(lesson.get(key), str) or not lesson[key].strip():
                    errors.append(f"{lp}.{key} must be non-empty")
            if isinstance(lesson.get("content"), str) and len(lesson["content"]) > 3500:
                errors.append(f"{lp}.content exceeds 3500 characters; split it into smaller lessons")
            if isinstance(lesson.get("content"), str):
                errors.extend(f"{lp}.content: {error}" for error in validate_telegram_html(lesson["content"]))
            content_pages = lesson.get("content_pages")
            if content_pages is not None:
                if not isinstance(content_pages, list) or not content_pages or not all(
                    isinstance(page, str) and page.strip() for page in content_pages
                ):
                    errors.append(f"{lp}.content_pages must be a non-empty array of strings")
                else:
                    if lesson.get("content") != content_pages[0]:
                        errors.append(f"{lp}.content must equal the first content page")
                    for page_index, page in enumerate(content_pages):
                        if len(page) > 3500:
                            errors.append(f"{lp}.content_pages[{page_index}] exceeds 3500 characters")
                        errors.extend(
                            f"{lp}.content_pages[{page_index}]: {error}"
                            for error in validate_telegram_html(page)
                        )
            sources = lesson.get("sources", [])
            if not isinstance(sources, list) or not all(isinstance(item, str) for item in sources):
                errors.append(f"{lp}.sources must be an array of strings")
            media = lesson.get("media", [])
            if not isinstance(media, list):
                errors.append(f"{lp}.media must be an array")
            else:
                for media_index, item in enumerate(media):
                    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                        errors.append(f"{lp}.media[{media_index}] must contain a path")
                    if isinstance(item, dict) and not isinstance(item.get("caption", ""), str):
                        errors.append(f"{lp}.media[{media_index}].caption must be a string")
    return errors


def load_and_validate(path: Path) -> dict:
    course = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_course(course)
    if errors:
        raise ValueError("Invalid course specification:\n- " + "\n- ".join(errors))
    return course
