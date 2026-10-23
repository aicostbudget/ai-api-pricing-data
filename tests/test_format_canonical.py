import json
import tempfile
import unittest
from pathlib import Path

from scripts.format_canonical import CANONICAL, is_normalized, normalized_text


class FormatCanonicalTests(unittest.TestCase):
    def test_repository_canonical_is_normalized(self):
        self.assertTrue(is_normalized(CANONICAL), "run python scripts/format_canonical.py")

    def test_normalization_keeps_content_and_key_order(self):
        rows = [{"provider_id": "x", "model_id": "b", "notes": "Café"}, {"z": 1, "a": [1, 2]}]
        sloppy = '[{"provider_id":"x","model_id":"b","notes":"Caf\\u00e9"},\n{"z": 1,"a":[1,2]}]'
        text = normalized_text(sloppy)
        self.assertEqual(json.loads(text), rows)
        self.assertEqual([list(row) for row in json.loads(text)], [list(row) for row in rows])
        self.assertIn("Café", text, "UTF-8 is written as-is, not escaped")
        self.assertTrue(text.endswith("}\n]\n"))
        self.assertEqual(normalized_text(text), text, "normalization is idempotent")

    def test_is_normalized_detects_a_misindented_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            path.write_text(normalized_text('[{"a": 1}]'), encoding="utf-8")
            self.assertTrue(is_normalized(path))
            path.write_text('[\n{\n  "a": 1\n}\n]\n', encoding="utf-8")
            self.assertFalse(is_normalized(path))


if __name__ == "__main__":
    unittest.main()
