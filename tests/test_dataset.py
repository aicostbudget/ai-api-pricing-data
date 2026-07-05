import csv
import hashlib
import json
import subprocess
import sys
import unittest

from scripts.lib import DATA, ROOT, build_dataset, csv_rows, load_models, load_providers


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
        self.assertEqual(dataset, build_dataset())
        with (DATA / "prices.csv").open(encoding="utf-8", newline="") as handle:
            actual_rows = list(csv.DictReader(handle))
        expected_rows = [{k: "" if v is None else str(v) for k, v in row.items()} for row in csv_rows(load_models())]
        self.assertEqual(actual_rows, expected_rows)

    def test_api_outputs_parse(self):
        json.loads((ROOT / "api" / "v1" / "prices.json").read_text(encoding="utf-8"))
        json.loads((ROOT / "api" / "v1" / "meta.json").read_text(encoding="utf-8"))
        self.assertTrue((ROOT / "api" / "v1" / "prices.csv").exists())

    def test_build_reproducible(self):
        before = hashlib.sha256((DATA / "prices.json").read_bytes()).hexdigest()
        subprocess.run([sys.executable, "scripts/build.py"], cwd=ROOT, check=True)
        after = hashlib.sha256((DATA / "prices.json").read_bytes()).hexdigest()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
