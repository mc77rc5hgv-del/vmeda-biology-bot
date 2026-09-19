"""Draft content/navigation checks; no bot import, database, or subscriptions."""
import copy
import html
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.course_automation.build_pharmacology_draft import compile_draft, paginate, PAGE_LIMIT  # noqa: E402
from scripts.course_automation.schema import validate_telegram_html  # noqa: E402


class DraftTests(unittest.TestCase):
    def setUp(self):
        folder = ROOT / "course_sources/pharmacology"
        self.curriculum = json.loads((folder / "curriculum.json").read_text(encoding="utf-8"))
        self.lessons = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((folder / "lessons").glob("*.json"))]
        self.banks = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in (folder / "assessments").glob("*.json")}

    def test_coverage_is_honest_and_stable(self):
        course, report, markdown = compile_draft(self.lessons, self.curriculum, self.banks)
        self.assertFalse(report["publication_ready"])
        self.assertFalse(report["ai_eligible"])
        self.assertEqual(report["authored_classes"], [5, 6])
        self.assertEqual(report["partial_classes"], [5, 6])
        self.assertEqual(len(report["not_authored"]), 47)
        self.assertEqual(compile_draft(list(reversed(self.lessons)), self.curriculum, self.banks), (course, report, markdown))

    def test_no_text_lost_and_no_empty_menu_entries(self):
        course, _, markdown = compile_draft(self.lessons, self.curriculum, self.banks)
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
            compile_draft(self.lessons + [self.lessons[0]], self.curriculum, self.banks)
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
                compile_draft(lessons, self.curriculum, self.banks)

    def test_original_questions_options_and_table_survive(self):
        course, report, markdown = compile_draft(self.lessons, self.curriculum, self.banks)
        bank = self.banks["class_05.json"]
        self.assertEqual(report["source_questions"], 17)
        self.assertEqual(report["source_practical_tasks"], 3)
        self.assertEqual([len(q.get("options", [])) for q in bank["questions"]],
                         [10, 0, 0, 6, 4, 4, 10, 8, 7, 9, 4, 5, 4, 3, 6, 5, 7])
        self.assertEqual(len(bank["questions"][-1]["match_items"]), 7)
        joined = "\n".join(
            page
            for group in course["sections"][0]["groups"]
            for lesson in group["lessons"]
            for page in lesson["content_pages"]
        )
        for item in bank["questions"] + bank["practical_tasks"]:
            for text in [item["text"]] + item.get("options", []) + item.get("match_items", []):
                self.assertIn(text, markdown)
                self.assertIn(html.escape(text), joined)
        table = bank["practical_tasks"][-1]["table"]
        self.assertEqual(len(table["rows"]), 7)
        self.assertEqual(len(table["columns"]), 3)
        for text in table["rows"] + table["columns"]:
            self.assertIn(text, markdown)
        self.assertIsNone(bank["answer_key"])

    def test_missing_or_mismatched_bank_fails_closed(self):
        with self.assertRaises(ValueError):
            compile_draft(self.lessons, self.curriculum)
        for field, value in (("source_sha256", "wrong"), ("lesson_number", 6), ("answer_key", ["а"])):
            banks = copy.deepcopy(self.banks)
            banks["class_05.json"][field] = value
            with self.assertRaises(ValueError):
                compile_draft(self.lessons, self.curriculum, banks)


if __name__ == "__main__":
    unittest.main()
