import csv
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from scripts.lib import (
    DATA,
    ROOT,
    append_history_if_changed,
    build_dataset,
    csv_rows,
    history_entry,
    load_models,
    load_providers,
    utc_now,
    utc_today,
)


class DatasetTests(unittest.TestCase):
    def test_counts_and_duplicates(self):
        providers = load_providers()
        models = load_models()
        self.assertEqual(len({item["provider_id"] for item in providers}), len(providers))
        self.assertEqual(len({(item["provider_id"], item["model_id"]) for item in models}), len(models))
        self.assertEqual(len(providers), 7)

    def test_no_negative_prices_and_sources(self):
        for model in load_models():
            self.assertTrue(model["official_source_url"].startswith("https://"))
            for value in model["pricing"].values():
                if isinstance(value, (int, float)):
                    self.assertGreaterEqual(value, 0)

    def test_json_csv_consistency(self):
        dataset = json.loads((DATA / "prices.json").read_text(encoding="utf-8"))
        self.assertEqual(dataset, build_dataset(dataset["generated_at"]))
        with (DATA / "prices.csv").open(encoding="utf-8", newline="") as handle:
            actual_rows = list(csv.DictReader(handle))
        expected_rows = [{k: "" if v is None else str(v) for k, v in row.items()} for row in csv_rows(load_models())]
        self.assertEqual(actual_rows, expected_rows)

    def test_generated_at_is_real_utc_and_consistent(self):
        dataset = json.loads((DATA / "prices.json").read_text(encoding="utf-8"))
        meta = json.loads((ROOT / "api" / "v1" / "meta.json").read_text(encoding="utf-8"))
        generated_at = dataset["generated_at"]
        self.assertEqual(generated_at, meta["generated_at"])
        self.assertNotEqual(generated_at, "1970-01-01T00:00:00Z")
        self.assertRegex(generated_at, re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"))
        parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        self.assertIsNotNone(parsed.tzinfo)

    def test_api_outputs_parse(self):
        json.loads((ROOT / "api" / "v1" / "prices.json").read_text(encoding="utf-8"))
        json.loads((ROOT / "api" / "v1" / "meta.json").read_text(encoding="utf-8"))
        self.assertTrue((ROOT / "api" / "v1" / "prices.csv").exists())

    def test_build_reproducible(self):
        before = json.loads((DATA / "prices.json").read_text(encoding="utf-8"))
        subprocess.run([sys.executable, "scripts/build.py"], cwd=ROOT, check=True)
        after = json.loads((DATA / "prices.json").read_text(encoding="utf-8"))
        before["generated_at"] = after["generated_at"]
        self.assertEqual(before, after)

    def test_build_twice_preserves_history_without_duplicate_entries(self):
        def line_counts() -> dict[str, int]:
            return {
                str(path.relative_to(DATA)): len(path.read_text(encoding="utf-8").splitlines())
                for path in sorted((DATA / "history").glob("*/*.jsonl"))
            }

        before = line_counts()
        subprocess.run([sys.executable, "scripts/build.py"], cwd=ROOT, check=True)
        after_first = line_counts()
        subprocess.run([sys.executable, "scripts/build.py"], cwd=ROOT, check=True)
        after_second = line_counts()
        self.assertTrue(before)
        self.assertEqual(after_first, after_second)
        for key, count in before.items():
            self.assertGreaterEqual(after_first[key], count)

    def test_history_records_are_valid_jsonl_with_required_fields(self):
        required = {
            "recorded_at",
            "provider_id",
            "model_id",
            "pricing",
            "official_source_url",
            "effective_from",
            "last_verified_at",
            "notes",
        }
        history_paths = sorted((DATA / "history").glob("*/*.jsonl"))
        self.assertTrue(history_paths)
        for path in history_paths:
            for line in path.read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                self.assertFalse(required - record.keys(), path)

    def test_price_change_adds_history_entry(self):
        model = load_models()[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            first = history_entry(model, utc_now())
            self.assertTrue(append_history_if_changed(path, first))
            self.assertFalse(append_history_if_changed(path, history_entry(model, utc_now())))
            changed_model = json.loads(json.dumps(model))
            changed_model["pricing"]["input"] = 999999
            self.assertTrue(append_history_if_changed(path, history_entry(changed_model, utc_now())))
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 2)

    def test_build_preserves_old_snapshots_and_uses_utc_date(self):
        old_snapshot = DATA / "snapshots" / "1999-12-31"
        marker = old_snapshot / "marker.txt"
        old_snapshot.mkdir(parents=True, exist_ok=True)
        marker.write_text("keep\n", encoding="utf-8")
        try:
            subprocess.run([sys.executable, "scripts/build.py"], cwd=ROOT, check=True)
            self.assertTrue(marker.exists())
            today_snapshot = DATA / "snapshots" / utc_today()
            self.assertTrue((today_snapshot / "prices.json").exists())
            self.assertTrue((today_snapshot / "prices.csv").exists())
        finally:
            shutil.rmtree(old_snapshot, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
