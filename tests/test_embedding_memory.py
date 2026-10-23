"""Offline regression tests: no bot credentials, user databases or network calls."""
import asyncio
from array import array
import json
import math
from pathlib import Path
import random
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai.embedding_cache import load_vectors, save_vectors  # noqa: E402
from ai import rag  # noqa: E402


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "cache.json"

    def test_legacy_cache_and_chunk_boundaries_preserve_every_float(self):
        rng = random.Random(391)
        values = {"a\\\"б": [rng.uniform(-1, 1) for _ in range(1536)],
                  "historical": [0.0, -0.0, 1e-300, 1e300], "empty": []}
        text = json.dumps(values, ensure_ascii=False)
        self.path.write_text(text, encoding="utf-8")
        for chunk in (1, 2, 7, 127, 65536):
            actual = load_vectors(self.path, chunk_size=chunk)
            self.assertEqual(set(actual), set(values))
            for key in values:
                self.assertIsInstance(actual[key], array)
                self.assertEqual(list(actual[key]), values[key])
                self.assertEqual(actual[key].tobytes(), array("d", values[key]).tobytes())
        self.assertEqual(self.path.read_text(encoding="utf-8"), text)

    def test_save_is_readable_by_old_json_loader_and_preserves_all_keys(self):
        values = {"current": array("d", [0.25, -0.5]), "old": array("d", [1.0])}
        save_vectors(self.path, values)
        self.assertEqual(json.loads(self.path.read_text()), {k: list(v) for k, v in values.items()})
        self.assertEqual(load_vectors(self.path), values)

    def test_failed_replace_keeps_original_and_removes_temporary(self):
        original = '{"old": [0.1, 0.2]}'
        self.path.write_text(original)
        with patch("ai.embedding_cache.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                save_vectors(self.path, {"new": array("d", [0.3])})
        self.assertEqual(self.path.read_text(), original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_failed_serialization_keeps_original(self):
        self.path.write_text('{"old": [0.1]}')
        with self.assertRaises(TypeError):
            save_vectors(self.path, {"bad": [object()]})
        self.assertEqual(self.path.read_text(), '{"old": [0.1]}')
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_malformed_cache_is_not_silently_partially_loaded(self):
        for content in ('', '[]', '{', '{"a":[1],}', '{"a":[1]}junk',
                        '{"a":[1], "b":[2', '{"a":null}', '{"a":["x"]}'):
            self.path.write_text(content)
            with self.assertRaises((ValueError, TypeError)):
                load_vectors(self.path, chunk_size=2)
            self.assertEqual(self.path.read_text(), content)

    def test_empty_duplicate_keys_and_whitespace_match_json(self):
        for content in ('{}', ' {  } \n', '{"a":[1],"a":[2]}', '{"a":[1e-3,-2.1E+4]}'):
            self.path.write_text(content)
            self.assertEqual({k: list(v) for k, v in load_vectors(self.path, chunk_size=1).items()},
                             json.loads(content))

    def test_cosine_and_ranking_are_exactly_equal(self):
        rng = random.Random(217)
        query = [rng.uniform(-1, 1) for _ in range(1536)]
        vectors = [[rng.uniform(-1, 1) for _ in query] for _ in range(30)]
        before = [rag._cosine(query, v) for v in vectors]
        after = [rag._cosine(query, array("d", v)) for v in vectors]
        self.assertEqual(before, after)
        self.assertEqual(sorted(range(30), key=before.__getitem__),
                         sorted(range(30), key=after.__getitem__))
        self.assertEqual(rag._cosine(query, array("d", [0.0]*1536)), 0)
        self.assertTrue(math.isfinite(after[0]))

    def test_new_embeddings_are_compact_and_cache_prevents_repurchase(self):
        calls = []

        async def create(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.125, -0.75])])

        client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
        with patch.object(rag.openai_provider, "get_client", return_value=client), \
             patch.object(rag, "_index", [{"key": "k", "title": "t", "text": "x"}]), \
             patch.object(rag, "_embeddings", {}):
            self.assertEqual(asyncio.run(rag.build_embeddings(str(self.path))), 1)
            self.assertIsInstance(rag._embeddings["k"], array)
            self.assertEqual(asyncio.run(rag.build_embeddings(str(self.path))), 0)
            self.assertEqual(len(calls), 1)
            self.assertEqual(json.loads(self.path.read_text()), {"k": [0.125, -0.75]})


if __name__ == "__main__":
    unittest.main()
