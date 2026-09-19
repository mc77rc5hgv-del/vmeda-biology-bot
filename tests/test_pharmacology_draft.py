"""Draft content/navigation checks; no bot import, database, or subscriptions."""
import copy
import html
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.course_automation.build_pharmacology_draft import compile_draft, paginate, PAGE_LIMIT
from scripts.course_automation.schema import validate_telegram_html


class DraftTests(unittest.TestCase):
    def setUp(self):
        folder = ROOT / "course_sources/pharmacology"
        self.curriculum = json.loads((folder / "curriculum.json").read_text(encoding="utf-8"))
        self.lessons = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((folder / "lessons").glob("*.json"))]

    def test_coverage_is_honest_and_stable(self):
        course, report, markdown = compile_draft(self.lessons, self.curriculum)
        self.assertFalse(report["publication_ready"])
        self.assertFalse(report["ai_eligible"])
        self.assertEqual(report["authored_classes"], [5, 6])
        self.assertEqual(report["partial_classes"], [5, 6])
        self.assertEqual(len(report["not_authored"]), 47)
        self.assertEqual(compile_draft(list(reversed(self.lessons)), self.curriculum), (course, report, markdown))

    def test_no_text_lost_and_no_empty_menu_entries(self):
        course, _, markdown = compile_draft(self.lessons, self.curriculum)
        for authored, group in zip(self.lessons, course["sections"][0]["groups"]):
            self.assertEqual(len(group["lessons"]), 4)
            for section, item in zip(authored["sections"], group["lessons"]):
                joined = "\n\n".join(item["content_pages"])
                self.assertEqual(item["content"], item["content_pages"][0])
                for page in item["content_pages"]:
                    self.assertLessEqual(len(page), PAGE_LIMIT)
                    self.assertEqual(validate_telegram_html(page), [])
                for block in section["blocks"]:
                    self.assertIn(html.escape(block["text"]), joined)
                    self.assertIn(block["text"], markdown)

    def test_html_is_escaped_and_blocks_are_not_truncated(self):
        pages = paginate([{"title": "<b>не тег</b>", "text": "A & B < C"}])
        self.assertIn("&lt;b&gt;", pages[0])
        self.assertEqual(validate_telegram_html(pages[0]), [])
        with self.assertRaises(ValueError):
            paginate([{"title": "Large", "text": "x" * PAGE_LIMIT}])

    def test_duplicate_missing_source_and_false_approval_rejected(self):
        with self.assertRaises(ValueError):
            compile_draft(self.lessons + [self.lessons[0]], self.curriculum)
        for mutate in (
            lambda x: x.update(ai_eligible=True),
            lambda x: x.update(status="verified"),
            lambda x: x.update(outstanding=[]),
            lambda x: x.update(number=99),
            lambda x: x["sections"][0]["blocks"][0].update(source_ids=["missing"]),
        ):
            lessons = copy.deepcopy(self.lessons)
            mutate(lessons[0])
            with self.assertRaises(ValueError):
                compile_draft(lessons, self.curriculum)


if __name__ == "__main__":
    unittest.main()
