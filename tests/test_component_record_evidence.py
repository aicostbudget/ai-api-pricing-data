import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


class ComponentRecordEvidenceTest(unittest.TestCase):
    """Component-only models carry verification dates on every price record (2026-11-03).

    Before, only historical components got checkedAt/verifiedAt, so current records of
    Mistral OCR 4.1, Cohere Parse v5 and the image models showed no verification date.
    """

    def setUp(self):
        canonical = load("data/canonical/models.json")
        models = canonical if isinstance(canonical, list) else canonical["models"]
        self.component_only = {
            f"{model['provider_id']}/{model['model_id']}": model
            for model in models
            if model.get("pricing_components") and not model.get("price_records")
        }

    def test_fixture_is_not_empty(self):
        self.assertIn("mistral-ai/mistral-ocr-4-1", self.component_only)
        self.assertIn("cohere/parse-v5.0", self.component_only)

    def test_preview_records_carry_model_verification(self):
        prices = load("data/pricing-v2-preview/prices.json")
        records = prices if isinstance(prices, list) else prices.get("prices") or prices["records"]
        for internal_id, model in self.component_only.items():
            mine = [record for record in records if record["pricingId"].startswith(f"price:{internal_id}:")]
            self.assertTrue(mine, internal_id)
            for record in mine:
                self.assertEqual(record.get("verifiedAt"), model["last_verified_at"], record["pricingId"])
                self.assertEqual(record.get("checkedAt"), model["accessed_at"], record["pricingId"])

    def test_projection_current_records_are_dated(self):
        projection = load("data/pricing-v2-preview/generated/model-pricing.v2.json")
        checked = set()
        for row in projection["models"]:
            internal_id = f"{row['provider']}/{row['id']}"
            if internal_id not in self.component_only:
                continue
            checked.add(internal_id)
            for record in row.get("priceRecords") or []:
                self.assertTrue(record.get("verifiedAt"), record["pricingId"])
                self.assertTrue(record.get("checkedAt"), record["pricingId"])
        self.assertIn("mistral-ai/mistral-ocr-4-1", checked)
        self.assertIn("cohere/parse-v5.0", checked)


if __name__ == "__main__":
    unittest.main()
