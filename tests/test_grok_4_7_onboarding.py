from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from scripts.pricing_contract import normalize_canonical_price_records, select_price_record


ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "grok-4.7"
EXPECTED = {
    "short": {"input": "2", "cached_input": "0.5", "output": "6"},
    "long": {"input": "4", "cached_input": "1", "output": "12"},
}


def read(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


class Grok47OnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        canonical = read("data/canonical/models.json")
        cls.xai_models = [row for row in canonical if row["provider_id"] == "xai"]
        cls.model = next(row for row in cls.xai_models if row["model_id"] == MODEL_ID)
        cls.records = normalize_canonical_price_records(
            f"xai/{MODEL_ID}", cls.model["price_records"], lambda value: value
        )

    def test_identity_evidence_context_and_public_api_semantics(self):
        model = self.model
        self.assertEqual(model["display_name"], "Grok 4.7")
        self.assertEqual(model["status"], "active")
        self.assertEqual(model["release_stage"], "stable")
        self.assertEqual(model["effective_from"], "2026-09-21")
        self.assertEqual(model["context_window_tokens"], 500_000)
        self.assertTrue(model["project_context_window"])
        self.assertIn("Supports text and image input with text output", model["notes"])
        self.assertIn("reasoning efforts are low, medium, high (default), and xhigh", model["notes"])
        self.assertIn("not on the public xAI API", model["notes"])
        self.assertIn("Batch API is not supported", model["notes"])
        self.assertNotIn("grok-4.7-fast", {row["model_id"] for row in self.xai_models})
        self.assertTrue(all(record["processing_mode"] == "standard" for record in model["price_records"]))
        self.assertIsNone(model["pricing"]["batch_input"])
        self.assertIsNone(model["pricing"]["batch_output"])
        self.assertIsNone(model["pricing"]["cache_write"])

    def test_exact_200k_boundary_and_whole_request_rates(self):
        self.assertEqual(len(self.records), 2)
        for prompt_tokens, context in ((199_999, "short"), (200_000, "short"), (200_001, "long")):
            selected = select_price_record(
                self.records, processing_mode="standard", prompt_tokens=prompt_tokens
            )
            self.assertEqual(selected["selectionStatus"], "available")
            self.assertEqual(selected["contextClass"], context)
            self.assertEqual(selected["promptTokenThreshold"], 200_000)
            self.assertEqual(
                selected["tierSelection"],
                {
                    "comparison": "less_than_or_equal" if context == "short" else "greater_than",
                    "tokenBasis": "total_prompt_tokens",
                    "cachedPromptTokensIncluded": True,
                    "wholeRequestPricing": True,
                },
            )
            amounts = {charge["component"]: charge["amount"] for charge in selected["charges"]}
            self.assertEqual(amounts, EXPECTED[context])

    def test_us_regional_endpoint_is_a_multiplier_not_a_fake_model(self):
        for record in self.model["price_records"]:
            policy = record["region_policy"]
            self.assertEqual(policy["pricing_geography"], "global_base")
            self.assertEqual(policy["endpoint_geographies"], ["global", "regional"])
            self.assertEqual(policy["data_residencies"], ["global", "us"])
            self.assertEqual(
                policy["price_adjustments"],
                [{
                    "id": "us-regional-endpoint-premium",
                    "operation": "multiply",
                    "factor": "1.10",
                    "selector": {"endpoint_geographies": ["regional"]},
                    "source_refs": [
                        "https://docs.x.ai/developers/advanced-api-usage/regions",
                        "https://docs.x.ai/developers/pricing",
                    ],
                }],
            )

    def test_model_added_event_has_no_fake_previous_price_or_delta(self):
        events = [
            json.loads(line)
            for line in (ROOT / "data/price-change-events/events.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        matches = [e for e in events if e["provider_id"] == "xai" and e["model_id"] == MODEL_ID]
        self.assertEqual(len(matches), 1)
        event = matches[0]
        self.assertEqual(event["change_type"], "model_added")
        self.assertEqual(event["old_prices"], {"input": None, "cached_input": None, "output": None})
        self.assertEqual(event["new_prices"], {"input": 2, "cached_input": 0.5, "output": 6})
        self.assertIsNone(event["old_status"])
        self.assertEqual(event["new_status"], "active")
        self.assertEqual(event["effective_from"], "2026-09-21")

    def test_v1_v2_huggingface_and_monitor_projection(self):
        public = read("api/v1/prices.json")["models"]
        self.assertEqual(sum(row["provider_id"] == "xai" and row["model_id"] == MODEL_ID for row in public), 1)

        projection = read("data/pricing-v2-preview/generated/model-pricing.v2.json")["models"]
        row = next(item for item in projection if item["id"] == MODEL_ID)
        self.assertEqual(row["canonicalInternalId"], "xai/grok-4.7")
        self.assertEqual(row["contextWindow"], "500K")
        self.assertEqual(row["contextWindowTokens"], 500_000)
        self.assertEqual(len(row["pricingTiers"]), 2)
        self.assertEqual(len(row["pricingComponents"]), 6)
        self.assertIsNone(row["batchInputPrice"])
        self.assertIsNone(row["batchOutputPrice"])

        hf = read("huggingface/prices.json")["records"]
        hf_row = next(item for item in hf if item["provider_id"] == "xai" and item["model_id"] == MODEL_ID)
        self.assertEqual(hf_row["pricing_tier_count"], 2)
        self.assertEqual(len(hf_row["pricing_components"]), 6)

    def test_grok_46_canonical_semantics_are_frozen(self):
        grok46 = next(row for row in self.xai_models if row["model_id"] == "grok-4.6")
        digest = hashlib.sha256(
            json.dumps(grok46, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.assertEqual(digest, "43acf46a77f31ba5bcfef9e3feaf6daf99f2c8b77149fac7421f36fb2efa1a44")


if __name__ == "__main__":
    unittest.main()
