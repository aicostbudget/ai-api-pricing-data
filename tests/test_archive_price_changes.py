import json
import re
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "data" / "archive-history" / "price-changes-2024-2026.v1.json"
SCHEMA = ROOT / "schema" / "archive-price-change.schema.json"
MODELS = ROOT / "data" / "canonical" / "models.json"

ARCHIVE_URL = re.compile(r"^https://web\.archive\.org/web/(\d{14})/(https?://.+)$")


def stamp(iso):
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y%m%d%H%M%S")


def numbers(text):
    return {float(x) for x in re.findall(r"[0-9]+(?:\.[0-9]+)?", text.replace(",", ""))}


class ArchivePriceChangesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(ARCHIVE.read_text(encoding="utf-8"))
        cls.records = cls.doc["records"]

    def test_schema_validates(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        jsonschema.validate(self.doc, json.loads(SCHEMA.read_text(encoding="utf-8")))

    def test_ids_unique_and_sorted(self):
        ids = [r["id"] for r in self.records]
        self.assertEqual(len(ids), len(set(ids)))
        keys = [(r["observed_window"]["first_new_snapshot"], r["id"]) for r in self.records]
        self.assertEqual(keys, sorted(keys))

    def test_snapshot_links_match_capture_times(self):
        for r in self.records:
            with self.subTest(r["id"]):
                for side in ("before_snapshot", "after_snapshot"):
                    m = ARCHIVE_URL.match(r[side]["archive_url"])
                    self.assertIsNotNone(m)
                    self.assertEqual(m.group(1), stamp(r[side]["captured_at"]))
                self.assertEqual(r["before_snapshot"]["captured_at"], r["observed_window"]["last_old_snapshot"])
                self.assertEqual(r["after_snapshot"]["captured_at"], r["observed_window"]["first_new_snapshot"])
                self.assertLess(r["before_snapshot"]["captured_at"], r["after_snapshot"]["captured_at"])
                if r["announcement"]:
                    m = ARCHIVE_URL.match(r["announcement"]["archive_url"])
                    self.assertIsNotNone(m)
                    self.assertEqual(m.group(1), stamp(r["announcement"]["archived_at"]))

    def test_prices_appear_in_quotes(self):
        for r in self.records:
            with self.subTest(r["id"]):
                before = numbers(r["before_snapshot"]["quote"])
                after = numbers(r["after_snapshot"]["quote"])
                changed = False
                for field, p in r["prices"].items():
                    if p["before"] is not None:
                        self.assertIn(float(p["before"]), before, field)
                    self.assertIn(float(p["after"]), after, field)
                    changed = changed or p["before"] != p["after"]
                self.assertTrue(changed, "at least one price must change")

    def test_date_basis(self):
        for r in self.records:
            with self.subTest(r["id"]):
                if r["date_basis"] == "snapshot_window":
                    self.assertIsNone(r["effective_from"])
                else:
                    self.assertIsNotNone(r["effective_from"])
                    day = r["effective_from"][:10]
                    self.assertLessEqual(r["observed_window"]["last_old_snapshot"][:10], day)
                    self.assertLessEqual(day, r["observed_window"]["first_new_snapshot"][:10])

    def test_dataset_model_ids_exist(self):
        raw = json.loads(MODELS.read_text(encoding="utf-8"))
        models = raw if isinstance(raw, list) else raw["models"]
        known = {f"{m['provider_id']}/{m['model_id']}" for m in models}
        for r in self.records:
            if r["dataset_model_id"]:
                with self.subTest(r["id"]):
                    self.assertIn(r["dataset_model_id"], known)
                    self.assertTrue(r["dataset_model_id"].startswith(r["provider"] + "/"))


if __name__ == "__main__":
    unittest.main()
