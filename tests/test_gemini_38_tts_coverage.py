from __future__ import annotations

import json
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_IDS = ("gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts")
MODES = ("standard", "batch", "flex", "priority")
# Google dropped context caching for both models (pricing rows gone between 2026-10-08 and 2026-10-09).
CURRENT = {
    "gemini-3.8-flash-tts": {
        "standard": ("0.50", "9.00"),
        "batch": ("0.25", "4.50"),
        "flex": ("0.25", "4.50"),
        "priority": ("0.90", "16.20"),
    },
    "gemini-3.8-flash-lite-tts": {
        "standard": ("0.50", "6.00"),
        "batch": ("0.25", "3.00"),
        "flex": ("0.25", "3.00"),
        "priority": ("0.90", "10.80"),
    },
}


def read_json(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


class Gemini38TtsCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.canonical = read_json("data/canonical/models.json")
        cls.models = {(row["provider_id"], row["model_id"]): row for row in cls.canonical}
        cls.v2 = {row["id"]: row for row in read_json("data/pricing-v2-preview/generated/model-pricing.v2.json")["models"]}
        cls.sources = read_json("data/pricing-v2-preview/sources.json")
        cls.sources_by_id = {row["sourceId"]: row for row in cls.sources}
        cls.hf = {row["model_id"]: row for row in read_json("huggingface/prices.json")["records"]}
        cls.events = [json.loads(line) for line in (ROOT / "data/price-change-events/events.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_canonical_identity_modalities_and_limits(self):
        self.assertNotIn(("google-gemini", "gemini-3.1-flash-tts-preview"), self.models)
        for model_id in MODEL_IDS:
            row = self.models[("google-gemini", model_id)]
            self.assertEqual(row["status"], "active")
            self.assertEqual(row["release_stage"], "stable")
            self.assertEqual(row["input_modality"], "text")
            self.assertEqual(row["output_modality"], "audio")
            self.assertEqual(row["context_window_tokens"], 8192)
            self.assertIn("16,384", row["notes"])
            self.assertIn("25 tokens per second", row["notes"])
            self.assertIsNone(row["pricing"]["output"])
            self.assertIsNone(row["pricing"]["batch_output"])
            self.assertIsNone(row["pricing"]["cached_input"])
            self.assertIsNone(row["pricing"]["batch_cached_input"])
            self.assertIn("Context caching is not supported", row["notes"])

    def test_all_current_and_future_prices_are_exact(self):
        for model_id in MODEL_IDS:
            records = self.models[("google-gemini", model_id)]["price_records"]
            self.assertEqual(len(records), 8)
            self.assertEqual(sum(bool(row["calculation_default"]) for row in records), 1)
            for mode in MODES:
                current = next(row for row in records if row["processing_mode"] == mode and row["pricing_status"] == "current")
                future = next(row for row in records if row["processing_mode"] == mode and row["pricing_status"] == "future")
                expected = CURRENT[model_id][mode]
                self.assertEqual(current["effective_until"], "2026-12-31")
                self.assertEqual(future["effective_from"], "2027-01-01")
                self.assertFalse(future["calculation_default"])
                for record, multiplier in ((current, 1), (future, 2)):
                    charges = {(item["component"], item["modality"], item["unit"]): item["amount"] for item in record["charges"]}
                    values = tuple(Decimal(value) * multiplier for value in expected)
                    self.assertEqual(set(charges), {("input", "text", "per_1m_tokens"), ("output", "audio", "per_1m_tokens")})
                    self.assertEqual(Decimal(charges[("input", "text", "per_1m_tokens")]), values[0])
                    self.assertEqual(Decimal(charges[("output", "audio", "per_1m_tokens")]), values[1])

    def test_projection_and_hugging_face_preserve_structured_containment(self):
        for model_id in MODEL_IDS:
            projection = self.v2[model_id]
            self.assertFalse(projection["defaultSafe"])
            self.assertIsNone(projection["selectedPriceRecordId"])
            # Without cache-storage charges the audio-output record must still be the verified billing record.
            self.assertEqual(projection["selectedBillingPriceRecordId"], f"price:google-gemini/{model_id}:standard:current")
            self.assertEqual(projection["verifiedAt"], self.models[("google-gemini", model_id)]["last_verified_at"])
            self.assertTrue(projection["verifiedSourceRefs"])
            self.assertIsNone(projection["inputPrice"])
            self.assertIsNone(projection["outputPrice"])
            self.assertEqual(len(projection["priceRecords"]), 8)
            self.assertEqual(len(projection["pricingComponents"]), 16)
            self.assertFalse(any(item["unit"] == "per_1m_tokens_per_hour" for item in projection["pricingComponents"]))
            exported = self.hf[model_id]
            self.assertIsNone(exported["input_price_per_1m_tokens"])
            self.assertIsNone(exported["output_price_per_1m_tokens"])
            self.assertEqual(len(exported["pricing_components"]), 16)

    def test_official_google_sources_are_unique_and_back_numeric_pricing(self):
        source_ids = [row["sourceId"] for row in self.sources]
        source_urls = [row["url"] for row in self.sources]
        self.assertEqual(len(source_ids), len(set(source_ids)))
        self.assertEqual(len(source_urls), len(set(source_urls)))
        expected_urls = {
            "https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash-tts",
            "https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash-lite-tts",
            "https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-8-text-to-speech/",
        }
        self.assertTrue(expected_urls.issubset(source_urls))
        for model_id in MODEL_IDS:
            model_url = f"https://ai.google.dev/gemini-api/docs/models/{model_id}"
            for record in self.models[("google-gemini", model_id)]["price_records"]:
                self.assertIn("https://ai.google.dev/gemini-api/docs/pricing", record["source_refs"])
                self.assertIn(model_url, record["source_refs"])
            for component in self.v2[model_id]["pricingComponents"]:
                urls = {self.sources_by_id[source_ref]["url"] for source_ref in component["sourceRefs"]}
                self.assertIn("https://ai.google.dev/gemini-api/docs/pricing", urls)
                self.assertIn(model_url, urls)
                self.assertTrue(all(url.startswith("https://ai.google.dev/") for url in urls))

    def test_monitor_records_additions_and_cache_removal_without_fake_successor_or_price_cut(self):
        events = [event for event in self.events if event["model_id"] in MODEL_IDS]
        self.assertEqual(
            sorted((event["model_id"], event["change_type"]) for event in events),
            sorted((model_id, change_type) for model_id in MODEL_IDS for change_type in ("model_added", "cached_price_removed")),
        )
        for event in events:
            if event["change_type"] == "cached_price_removed":
                self.assertEqual(event["old_prices"], {"cached_input": 0.125, "input": 0.5, "output": None})
                self.assertEqual(event["new_prices"], {"cached_input": None, "input": 0.5, "output": None})
        self.assertFalse(any("gemini-3.1-flash-tts-preview" in json.dumps(event) for event in self.events))


if __name__ == "__main__":
    unittest.main()
