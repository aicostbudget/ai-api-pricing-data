from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
KEY = ("openai", "gpt-live-1")
OFFICIAL_HOST = "developers.openai.com"


def read_json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


class GPTLive1CoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        canonical_rows = read_json("data/canonical/models.json")
        cls.canonical_matches = [row for row in canonical_rows if (row["provider_id"], row["model_id"]) == KEY]
        cls.v2 = {
            (row["provider"], row["id"]): row
            for row in read_json("data/pricing-v2-preview/generated/model-pricing.v2.json")["models"]
        }
        cls.hf = {
            (row["provider_id"], row["model_id"]): row
            for row in read_json("huggingface/prices.json")["records"]
        }

    def test_canonical_record_is_exact_verified_and_non_token(self):
        self.assertEqual(len(self.canonical_matches), 1)
        row = self.canonical_matches[0]
        self.assertEqual(row["display_name"], "GPT-Live 1")
        self.assertEqual(row["model_category"], "realtime_voice")
        self.assertEqual((row["status"], row["release_stage"]), ("active", "stable"))
        self.assertEqual(row["effective_from"], "2026-09-10")
        self.assertTrue(all(row["pricing"].get(field) is None for field in (
            "unit", "input", "output", "cached_input", "cache_write", "cache_write_1h", "batch_input", "batch_output"
        )))
        self.assertEqual(len(row["price_records"]), 1)
        record = row["price_records"][0]
        self.assertEqual(record["verification_status"], "verified")
        self.assertEqual(len(record["charges"]), 1)
        charge = record["charges"][0]
        self.assertEqual(
            (charge["component"], charge["modality"], charge["unit"], charge["amount"]),
            ("session_duration", "audio", "per_minute", "0.05"),
        )
        self.assertRegex(record["billing_note"], r"billed per second")
        self.assertRegex(record["billing_note"], r"Backend model and tool usage are billed separately")

    def test_all_sources_are_official_openai_evidence(self):
        row = self.canonical_matches[0]
        urls = row["official_source_urls"]
        self.assertEqual(row["official_source_url"], "https://developers.openai.com/api/docs/models/gpt-live-1")
        self.assertEqual({urlparse(url).hostname for url in urls}, {OFFICIAL_HOST})
        self.assertIn("https://developers.openai.com/api/docs/pricing", urls)
        self.assertIn("https://developers.openai.com/api/docs/changelog", urls)

    def test_public_api_v2_hf_and_csv_preserve_native_billing(self):
        canonical = self.canonical_matches[0]
        self.assertEqual(read_json("api/v1/models/openai/gpt-live-1.json"), canonical)

        v2 = self.v2[KEY]
        self.assertEqual((v2["publicExposure"], v2["verificationStatus"], v2["defaultSafe"]), ("public", "verified", False))
        self.assertEqual((v2["inputPrice"], v2["cachedInputPrice"], v2["outputPrice"]), (None, None, None))
        self.assertRegex(v2["billingNote"], r"billed per second")
        component = v2["pricingComponents"][0]
        self.assertEqual(
            (component["component"], component["modality"], component["unit"], component["amount"]),
            ("session_duration", "audio", "per_minute", "0.05"),
        )

        hf = self.hf[KEY]
        self.assertEqual(
            (hf["input_price_per_1m_tokens"], hf["cached_input_price_per_1m_tokens"], hf["output_price_per_1m_tokens"]),
            (None, None, None),
        )
        self.assertEqual(
            (hf["pricing_unit"], hf["unit_price"], hf["billing_unit"], hf["billing_quantity"], hf["pricing_dimension"]),
            (None, 0.05, "per_minute", 1, "session_duration"),
        )
        self.assertRegex(hf["notes"], r"Backend model and tool usage are billed separately")

        with (ROOT / "data/prices.csv").open(encoding="utf-8", newline="") as handle:
            csv_row = next(row for row in csv.DictReader(handle) if (row["provider_id"], row["model_id"]) == KEY)
        self.assertEqual(
            (csv_row["input"], csv_row["output"], csv_row["unit_price"], csv_row["billing_unit"], csv_row["billing_quantity"], csv_row["pricing_dimension"]),
            ("", "", "0.05", "per_minute", "1", "session_duration"),
        )


if __name__ == "__main__":
    unittest.main()
