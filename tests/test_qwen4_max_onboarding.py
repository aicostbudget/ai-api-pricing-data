from __future__ import annotations

import json
import unittest
from decimal import Decimal
from pathlib import Path

from scripts.pricing_contract import project_v1_compatibility, validate_model_price_records


ROOT = Path(__file__).resolve().parents[1]
PROVIDER = "alibaba-qwen"
MODEL_ID = "qwen4-max"
PAGE = "https://www.alibabacloud.com/help/en/model-studio/qwen4-max"
PRICING_PAGE = "https://www.alibabacloud.com/help/en/model-studio/model-pricing"
# International (Singapore) list prices, USD per 1M tokens, read from the official pages on 2026-11-18
# (reports/price-evidence/alibaba-qwen/qwen4-max).
EXPECTED_CHARGES = {
    "input": Decimal("1.5"),
    "cached_input": Decimal("0.075"),
    "cache_write_5m": Decimal("1.875"),
    "cache_write_1h": Decimal("3"),
    "output": Decimal("4.5"),
}


def read_json(relative_path: str):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


class Qwen4MaxOnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.canonical = {
            (row["provider_id"], row["model_id"]): row for row in read_json("data/canonical/models.json")
        }
        cls.model = cls.canonical[(PROVIDER, MODEL_ID)]
        validate_model_price_records(cls.model)

    def test_identity_sources_and_unknown_release_date(self) -> None:
        model = self.model
        self.assertEqual(model["display_name"], "Qwen4 Max")
        self.assertEqual(model["model_family"], "Qwen")
        self.assertEqual(model["status"], "active")
        self.assertEqual(model["context_window_tokens"], 1_000_000)
        self.assertEqual(model["official_source_url"], PAGE)
        self.assertEqual(model["official_source_urls"], [PAGE, PRICING_PAGE])
        # The official pages carry no release date; unknown values are null, never guessed.
        self.assertIsNone(model["released_at"])
        self.assertIsNone(model["release_evidence"])
        self.assertIsNone(model["effective_from"])
        self.assertEqual(model["access_status"], "public")
        self.assertEqual(model["binding_status"], "approved")
        self.assertEqual(model["binding_evidence"][0]["official_model_id"], MODEL_ID)

    def test_singapore_international_prices_and_v1_projection(self) -> None:
        records = self.model["price_records"]
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["processing_mode"], "standard")
        self.assertTrue(record["calculation_default"])
        self.assertIsNone(record["prompt_token_threshold"])
        charges = {charge["component"]: Decimal(str(charge["amount"])) for charge in record["charges"]}
        self.assertEqual(charges, EXPECTED_CHARGES)
        self.assertEqual(record["region_policy"]["pricing_geography"], "region_specific")
        self.assertEqual(record["region_policy"]["endpoint_geographies"], ["ap-southeast-1"])
        projected = project_v1_compatibility(records)
        self.assertEqual(projected["input"], 1.5)
        self.assertEqual(projected["output"], 4.5)
        self.assertEqual(projected["cached_input"], 0.075)
        self.assertEqual(projected["cache_write"], 1.875)
        self.assertEqual(projected["cache_write_1h"], 3.0)
        self.assertEqual(self.model["pricing"]["cache_write"], 1.875)
        self.assertEqual(self.model["pricing"]["cache_write_1h"], 3.0)

    def test_batch_is_not_borrowed_from_the_beijing_scope(self) -> None:
        # Batch inference is supported only in China (Beijing); the Singapore scope used here has none.
        self.assertIsNone(self.model["pricing"]["batch_input"])
        self.assertIsNone(self.model["pricing"]["batch_output"])
        self.assertFalse(any(row["processing_mode"] == "batch" for row in self.model["price_records"]))
        self.assertIn("Batch inference is not supported in the International (Singapore) scope", self.model["notes"])
        for mainland_value in ("0.707", "2.12", "1.413", "4.24"):
            for record in self.model["price_records"]:
                for charge in record["charges"]:
                    self.assertNotEqual(str(charge["amount"]), mainland_value)
            self.assertNotIn(mainland_value, json.dumps(self.model["pricing"]))

    def test_cheaper_than_qwen3_8_max_and_predecessor_unchanged(self) -> None:
        old = self.canonical[(PROVIDER, "qwen3.8-max")]
        self.assertEqual((old["pricing"]["input"], old["pricing"]["output"], old["pricing"]["cached_input"]), (2.0, 6.0, 0.25))
        self.assertEqual(Decimal(str(self.model["pricing"]["input"])) / Decimal(str(old["pricing"]["input"])), Decimal("0.75"))
        self.assertEqual(Decimal(str(self.model["pricing"]["output"])) / Decimal(str(old["pricing"]["output"])), Decimal("0.75"))
        self.assertNotIn("qwen4-max-preview", {model_id for _, model_id in self.canonical})

    def test_generated_artifacts_and_model_added_event(self) -> None:
        projection = {
            row["canonicalInternalId"]: row
            for row in read_json("data/pricing-v2-preview/generated/model-pricing.v2.json")["models"]
        }
        website = projection[f"{PROVIDER}/{MODEL_ID}"]
        self.assertTrue(website["defaultSafe"])
        self.assertEqual((website["inputPrice"], website["cachedInputPrice"], website["outputPrice"]), (1.5, 0.075, 4.5))
        self.assertEqual({c["component"] for c in website["pricingComponents"]}, set(EXPECTED_CHARGES))
        hf = [row for row in read_json("huggingface/prices.json")["records"]
              if row["provider_id"] == PROVIDER and row["model_id"] == MODEL_ID]
        self.assertEqual(len(hf), 1)
        self.assertEqual(hf[0]["input_price_per_1m_tokens"], 1.5)
        self.assertEqual(read_json(f"api/v1/models/{PROVIDER}/{MODEL_ID}.json"), self.model)
        events = [
            json.loads(line)
            for line in (ROOT / "data/price-change-events/events.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        added = [e for e in events if e["model_id"] == MODEL_ID and e["change_type"] == "model_added"]
        self.assertEqual(len(added), 1)
        self.assertIsNone(added[0]["effective_from"])


if __name__ == "__main__":
    unittest.main()
