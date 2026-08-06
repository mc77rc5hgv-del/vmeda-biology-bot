"""Tests for the in-Telegram study sessions and the content loader behind them."""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import tb  # noqa: F401,E402

import content  # noqa: E402
import quiz  # noqa: E402

HAS_CONTENT = content.has_content()
USER = 4242


@unittest.skipUnless(HAS_CONTENT, "content.json missing")
class ContentTests(unittest.TestCase):
    def test_every_module_has_topics(self):
        for module_id in ("m1", "m2", "m3", "m4", "m5", "m6"):
            self.assertTrue(content.topics_of(module_id), f"{module_id} has no topics")

    def test_topic_numbers_are_unique_within_a_module(self):
        for module_id, topics in content.MODULES_CONTENT.items():
            nums = [t["num"] for t in topics]
            self.assertEqual(len(nums), len(set(nums)), f"duplicate topic numbers in {module_id}")

    def test_m6_numbering_matches_the_sites_offsets(self):
        # The site concatenates cns + pns(+15) + sense(+26) into module 6.
        nums = [t["num"] for t in content.topics_of("m6")]
        self.assertEqual(min(nums), 1)
        self.assertEqual(max(nums), 33)

    def test_test_questions_have_valid_correct_index(self):
        bad = []
        for module_id, topics in content.MODULES_CONTENT.items():
            for topic in topics:
                for question in topic.get("tests", []):
                    options = question.get("options") or []
                    correct = question.get("correct")
                    if not isinstance(correct, int) or not 0 <= correct < len(options):
                        bad.append((module_id, topic["num"], question.get("q", "")[:40]))
        self.assertEqual(bad[:5], [], f"{len(bad)} questions have an out-of-range correct index")

    def test_search_finds_a_known_topic(self):
        self.assertTrue(content.search_topics("череп"))

    def test_search_ignores_too_short_queries(self):
        self.assertEqual(content.search_topics("а"), [])

    def test_pair_question_has_four_distinct_options(self):
        pairs = content.all_pairs()
        question = content.build_pair_question(pairs[0], pairs[:300], random.Random(7))
        self.assertEqual(len(question["options"]), 4)
        self.assertEqual(len(set(question["options"])), 4, "duplicate option text")
        self.assertEqual(question["options"][question["correct"]], pairs[0]["def"])


@unittest.skipUnless(HAS_CONTENT, "content.json missing")
class SessionTests(unittest.TestCase):
    def tearDown(self):
        quiz.end_session(USER)

    def test_test_session_scores_and_finishes(self):
        session = quiz.start_test(USER, "m1", 5, rng=random.Random(1))
        self.assertIsNotNone(session)
        total = session.total
        for _ in range(total):
            item = session.current()
            quiz.answer_choice(session, item["correct"])
        self.assertTrue(session.finished)
        self.assertEqual(session.correct, total)
        self.assertEqual(len(session.reward_keys), total)
        self.assertEqual(session.wrong, [])

    def test_wrong_answers_are_collected(self):
        session = quiz.start_test(USER, "m1", 5, rng=random.Random(2))
        item = session.current()
        wrong_index = (item["correct"] + 1) % len(item["options"])
        is_correct, _ = quiz.answer_choice(session, wrong_index)
        self.assertFalse(is_correct)
        self.assertEqual(len(session.wrong), 1)
        self.assertIn("options", session.wrong[0], "mistake must keep its options for re-drilling")

    def test_blitz_spans_the_whole_course(self):
        session = quiz.start_blitz(USER, rng=random.Random(3))
        self.assertIsNotNone(session)
        self.assertEqual(session.mode, "blitz")
        self.assertIsNone(session.topic_num)
        modules = {item["module_id"] for item in session.items}
        self.assertGreater(len(modules), 1, "blitz should draw from more than one module")

    def test_flash_session_self_grades(self):
        session = quiz.start_flash(USER, "m1", 5, rng=random.Random(4))
        self.assertIsNotNone(session)
        quiz.answer_flash(session, True)
        self.assertEqual(session.correct, 1)
        self.assertEqual(session.index, 1)
        self.assertTrue(session.reward_keys[0].startswith("f:"))

    def test_terms_session_builds_choices(self):
        session = quiz.start_terms(USER, "m1", 5, rng=random.Random(5))
        self.assertIsNotNone(session)
        self.assertEqual(session.mode, "match")
        self.assertTrue(all(len(item["options"]) >= 2 for item in session.items))

    def test_mistakes_session_recovers_options_from_content(self):
        # A mistake stored by the website carries no options; the bot must look them up.
        question = content.sample_tests("m1", 5, limit=1, rng=random.Random(6))[0]
        state = {"mistakes": [{"q": question["q"], "moduleId": "m1", "topicNum": 5}]}
        session = quiz.start_mistakes(USER, state, rng=random.Random(6))
        self.assertIsNotNone(session)
        self.assertTrue(session.items[0]["options"])

    def test_mistakes_session_empty_without_mistakes(self):
        self.assertIsNone(quiz.start_mistakes(USER, {"mistakes": []}))

    def test_solved_mistakes_are_tracked(self):
        question = content.sample_tests("m1", 5, limit=1, rng=random.Random(8))[0]
        state = {"mistakes": [{"q": question["q"], "moduleId": "m1", "topicNum": 5}]}
        session = quiz.start_mistakes(USER, state, rng=random.Random(8))
        item = session.current()
        quiz.answer_choice(session, item["correct"])
        self.assertEqual(session.solved, [question["q"]])

    def test_stale_sessions_are_swept(self):
        session = quiz.start_test(USER, "m1", 5, rng=random.Random(9))
        session.started_at -= quiz.SESSION_TTL_SECONDS + 60
        quiz.start_test(9999, "m1", 5, rng=random.Random(9))  # any start triggers the sweep
        self.assertIsNone(quiz.get_session(USER))
        quiz.end_session(9999)


if __name__ == "__main__":
    unittest.main()
