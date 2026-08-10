import csv
import json
import re
import unittest
from datetime import datetime, timezone

from scripts.export_huggingface import (
    HF_DIR,
    META_PATH,
    PROJECTION_PATH,
    REQUIRED_UTM,
    expected_public_keys,
    parse_date,
    validate_huggingface_artifacts,
)


class HuggingFaceExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads((HF_DIR / "prices.json").read_text(encoding="utf-8"))
        cls.metadata = cls.payload["metadata"]
        cls.records = cls.payload["records"]
        cls.projection = json.loads(PROJECTION_PATH.read_text(encoding="utf-8"))

    def test_export_artifacts_are_internally_consistent(self):
        validate_huggingface_artifacts()
        self.assertEqual((HF_DIR / "train.csv").read_bytes(), (HF_DIR / "prices.csv").read_bytes())
        with (HF_DIR / "train.csv").open(encoding="utf-8", newline="") as handle:
            self.assertEqual(len(list(csv.DictReader(handle))), len(self.records))

    def test_export_matches_full_public_website_key_set(self):
        actual = {(row["provider_id"], row["model_id"]) for row in self.records}
        self.assertEqual(actual, expected_public_keys(self.projection))
        self.assertEqual(len(actual), len(self.records))
        self.assertEqual(len(self.records), 40, "audited 40-row public Website distribution must not regress to the 22-row HF snapshot")
        self.assertEqual(self.metadata["record_count"], len(self.records))
        self.assertEqual(self.metadata["provider_count"], 7)

    def test_projection_prices_match_and_fallbacks_are_explicit(self):
        projection_by_key = {(row["provider"], row["id"]): row for row in self.projection["models"]}
        fallback_count = 0
        for record in self.records:
            key = (record["provider_id"], record["model_id"])
            projected = projection_by_key[key]
            if projected["inputPrice"] is not None and projected["outputPrice"] is not None:
                self.assertEqual(record["input_price_per_1m_tokens"], projected["inputPrice"], key)
                self.assertEqual(record["cached_input_price_per_1m_tokens"], projected["cachedInputPrice"], key)
                self.assertEqual(record["output_price_per_1m_tokens"], projected["outputPrice"], key)
            else:
                fallback_count += 1
                self.assertIn("legacy fallback", record["notes"], key)
                self.assertNotIn("excluded_default_candidate", projected["blockedFromDefaultReasons"], key)
        self.assertEqual(fallback_count, 4)

    def test_timestamps_preserve_verification_semantics(self):
        pricing_meta = json.loads(META_PATH.read_text(encoding="utf-8"))
        self.assertEqual(self.metadata["generated_at"], pricing_meta["generated_at"])
        self.assertEqual(self.metadata["last_updated"], pricing_meta["last_verified_at"])
        generated_at = datetime.fromisoformat(self.metadata["generated_at"].replace("Z", "+00:00"))
        verified = [
            parse_date(row["last_verified_at"])
            for row in self.records
            if row["last_verified_at"]
        ]
        self.assertGreaterEqual(generated_at, max(verified))
        self.assertLessEqual(generated_at, datetime.now(timezone.utc))
        self.assertTrue(all(value <= datetime.now(timezone.utc) for value in verified))

    def test_prices_are_finite_non_negative_or_null(self):
        for row in self.records:
            for field in (
                "input_price_per_1m_tokens",
                "cached_input_price_per_1m_tokens",
                "output_price_per_1m_tokens",
            ):
                value = row[field]
                if value is not None:
                    self.assertIsInstance(value, (int, float), (row["provider_id"], row["model_id"], field))
                    self.assertGreaterEqual(value, 0, (row["provider_id"], row["model_id"], field))

    def test_dataset_card_uses_utm_only_for_html_acquisition_links(self):
        card = (HF_DIR / "README.md").read_text(encoding="utf-8")
        urls = set(re.findall(r"https://aicostbudget\.com/[^\s)]+", card))
        clean_api_urls = {
            "https://aicostbudget.com/api/datasets/ai-api-pricing.json",
            "https://aicostbudget.com/api/datasets/ai-api-pricing.csv",
        }
        acquisition_urls = {
            "https://aicostbudget.com/en/datasets/ai-api-pricing?utm_source=huggingface&utm_medium=dataset&utm_campaign=ai_api_pricing_dataset",
            "https://aicostbudget.com/en/ai-api-cost-calculator?utm_source=huggingface&utm_medium=dataset&utm_campaign=ai_api_pricing_dataset",
            "https://aicostbudget.com/en/model-pricing-comparison?utm_source=huggingface&utm_medium=dataset&utm_campaign=ai_api_pricing_dataset",
            "https://aicostbudget.com/en/ai-budget-planner?utm_source=huggingface&utm_medium=dataset&utm_campaign=ai_api_pricing_dataset",
        }
        self.assertEqual(urls, clean_api_urls | acquisition_urls)
        for url in acquisition_urls:
            for marker in REQUIRED_UTM:
                self.assertIn(marker, url)
        for url in clean_api_urls:
            self.assertNotRegex(url, r"[?&]utm_")
        self.assertIn("not a separately curated subset", card)


if __name__ == "__main__":
    unittest.main()
