from __future__ import annotations

import json
import unittest
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
KEYS = {
    "grok-voice-2.0": ("deprecated", "2026-07-29"),
    "grok-voice-3.0": ("active", "2026-10-14"),
}
OFFICIAL_HOST = "docs.x.ai"


def read_json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


class GrokVoice3ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows = read_json("data/canonical/models.json")
        cls.models = {
            row["model_id"]: row
            for row in rows
            if row["provider_id"] == "xai" and row["model_id"] in KEYS
        }
        cls.v2 = {
            (row["provider"], row["id"]): row
            for row in read_json("data/pricing-v2-preview/generated/model-pricing.v2.json")["models"]
        }
        cls.hf = {
            row["model_id"]: row
            for row in read_json("huggingface/prices.json")["records"]
            if row["provider_id"] == "xai" and row["model_id"] in KEYS
        }

    def test_exact_model_identities_and_non_token_prices(self):
        self.assertEqual(set(self.models), set(KEYS))
        expected_charges = {
            ("session_duration", "audio", "per_minute", "0.08"),
            ("input", "text", "per_text_input", "0.004"),
        }
        for model_id, (status, effective_from) in KEYS.items():
            with self.subTest(model_id=model_id):
                row = self.models[model_id]
                self.assertEqual((row["status"], row["effective_from"]), (status, effective_from))
                self.assertEqual(row["model_category"], "realtime_voice")
                self.assertTrue(all(row["pricing"].get(field) is None for field in (
                    "unit", "input", "output", "cached_input", "cache_write",
                    "cache_write_1h", "batch_input", "batch_output",
                )))
                self.assertEqual(len(row["price_records"]), 1)
                record = row["price_records"][0]
                self.assertTrue(record["calculation_default"])
                self.assertEqual(record["verification_status"], "verified")
                self.assertEqual({
                    (charge["component"], charge["modality"], charge["unit"], charge["amount"])
                    for charge in record["charges"]
                }, expected_charges)
                self.assertRegex(record["billing_note"], r"additive")
                self.assertRegex(record["billing_note"], r"not token-priced")

    def test_dynamic_alias_points_only_to_3_0(self):
        self.assertEqual(self.models["grok-voice-3.0"]["aliases"], ["grok-voice-latest"])
        self.assertNotIn("aliases", self.models["grok-voice-2.0"])

    def test_2_0_is_deprecated_without_invented_eol(self):
        lifecycle = self.models["grok-voice-2.0"]["lifecycle"]
        self.assertEqual(lifecycle, {
            "deprecation_date": "2026-10-14",
            "replacement_model_id": "grok-voice-3.0",
        })
        self.assertNotIn("retirement_date", lifecycle)
        self.assertNotIn("retirement_notice_date", lifecycle)

    def test_all_sources_are_direct_official_xai_evidence(self):
        for model_id, row in self.models.items():
            with self.subTest(model_id=model_id):
                self.assertEqual({urlparse(url).hostname for url in row["official_source_urls"]}, {OFFICIAL_HOST})
                self.assertIn("https://docs.x.ai/developers/pricing", row["official_source_urls"])
                self.assertIn("https://docs.x.ai/developers/release-notes", row["official_source_urls"])

    def test_api_and_v2_preserve_both_components_without_flattening(self):
        expected = {
            ("session_duration", "audio", "per_minute", "0.08"),
            ("input", "text", "per_text_input", "0.004"),
        }
        for model_id in KEYS:
            with self.subTest(model_id=model_id):
                v2 = self.v2[("xai", model_id)]
                self.assertEqual({
                    (component["component"], component["modality"], component["unit"], component["amount"])
                    for component in v2["pricingComponents"]
                }, expected)
                api = read_json(f"api/v1/models/xai/{model_id}.json")
                self.assertEqual(api, self.models[model_id])

    def test_hugging_face_preserves_units_and_lifecycle_without_fake_alias_model(self):
        self.assertEqual(set(self.hf), set(KEYS))
        self.assertFalse(any(
            row["model_id"] == "grok-voice-latest"
            for row in read_json("huggingface/prices.json")["records"]
        ))
        self.assertEqual(self.hf["grok-voice-2.0"]["availability"], "deprecated")
        self.assertEqual(self.hf["grok-voice-3.0"]["availability"], "active")
        for model_id, row in self.hf.items():
            with self.subTest(model_id=model_id):
                self.assertEqual({
                    (charge["component"], charge["modality"], charge["unit"], charge["amount"])
                    for charge in row["pricing_components"]
                }, {
                    ("session_duration", "audio", "per_minute", "0.08"),
                    ("input", "text", "per_text_input", "0.004"),
                })
                self.assertIsNone(row["input_price_per_1m_tokens"])
                self.assertIsNone(row["output_price_per_1m_tokens"])


if __name__ == "__main__":
    unittest.main()
