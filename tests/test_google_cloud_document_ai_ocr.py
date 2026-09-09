import csv
import json
import subprocess
import unittest
from decimal import Decimal
from pathlib import Path

from scripts.lib import ROOT, load_models, load_providers
from scripts.pricing_contract import PricingContractError, calculate_graduated_usage_cost, validate_canonical_price_records


WEBSITE = Path(r"D:\ai-cost-control-tool\aicostguard-english")
MODEL_KEY = ("google-cloud", "OCR_PROCESSOR")


class GoogleCloudDocumentAiOcrTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = {(row["provider_id"], row["model_id"]): row for row in load_models()}
        cls.model = cls.models[MODEL_KEY]
        cls.v2_models = json.loads((ROOT / "data/pricing-v2-preview/models.json").read_text(encoding="utf-8"))
        cls.v2_prices = json.loads((ROOT / "data/pricing-v2-preview/prices.json").read_text(encoding="utf-8"))
        cls.website_projection = json.loads((WEBSITE / "data/pricing-v2-projection/model-pricing.v2.json").read_text(encoding="utf-8"))
        cls.hf = json.loads((ROOT / "huggingface/prices.json").read_text(encoding="utf-8"))

    def test_provider_and_exact_processor_identity_are_separate_from_gemini(self):
        providers = {row["provider_id"] for row in load_providers()}
        self.assertIn("google-cloud", providers)
        self.assertIn("google-gemini", providers)
        self.assertEqual(self.model["model_id"], "OCR_PROCESSOR")
        self.assertEqual(self.model["display_name"], "Enterprise Document OCR")
        self.assertEqual(self.model["model_category"], "document_parsing")
        self.assertNotIn(MODEL_KEY[1], {model_id for provider, model_id in self.models if provider == "google-gemini"})

    def test_canonical_contract_preserves_page_tiers_and_null_token_scalars(self):
        self.assertTrue(all(self.model["pricing"][field] is None for field in (
            "unit", "input", "output", "cached_input", "cache_write", "cache_write_1h", "batch_input", "batch_output"
        )))
        records = self.model["price_records"]
        validate_canonical_price_records(records)
        self.assertEqual([record["usage_tier"]["tier_start"] for record in records], [0, 1000, 5000000])
        self.assertEqual([record["usage_tier"]["tier_end"] for record in records], [1000, 5000000, None])
        self.assertEqual([record["charges"][0]["amount"] for record in records], ["0", "1.5", "0.6"])
        self.assertTrue(all(record["charges"][0]["component"] == "document_page" for record in records))
        self.assertTrue(all(record["charges"][0]["unit"] == "per_1000_pages" for record in records))
        self.assertTrue(all(record["usage_tier"]["billing_period"] == "calendar_month" for record in records))
        self.assertTrue(all(record["usage_tier"]["tier_mode"] == "graduated" for record in records))
        self.assertTrue(all(record["usage_tier"]["usage_scope"] == "unknown" for record in records))
        self.assertTrue(all(record["usage_tier"]["free_allowance"] == 1000 for record in records))
        self.assertTrue(all(record["verification_status"] == "verified" for record in records))
        self.assertTrue(all("cloud.google.com" in url for record in records for url in record["source_refs"]))

    def test_generic_contract_rejects_gaps(self):
        records = json.loads(json.dumps(self.model["price_records"]))
        records[1]["usage_tier"]["tier_start"] = 1001
        with self.assertRaisesRegex(PricingContractError, "gap or overlap"):
            validate_canonical_price_records(records)

    def test_official_boundary_math(self):
        records = self.model["price_records"]
        expected = {
            0: Decimal("0"),
            1000: Decimal("0"),
            1001: Decimal("0.0015"),
            5000000: Decimal("7498.5"),
            5000001: Decimal("7498.5006"),
            6000000: Decimal("8098.5"),
        }
        for pages, cost in expected.items():
            self.assertEqual(calculate_graduated_usage_cost(records, pages), cost)

    def test_v2_public_api_hf_and_website_are_lossless(self):
        v2_model = next(row for row in self.v2_models if row["internalId"] == "google-cloud/OCR_PROCESSOR")
        self.assertEqual(v2_model["canonicalOfficialId"], "OCR_PROCESSOR")
        v2_prices = [row for row in self.v2_prices if row["modelInternalId"] == "google-cloud/OCR_PROCESSOR"]
        self.assertEqual(len(v2_prices), 3)
        self.assertEqual([row["usageTier"]["tierStart"] for row in v2_prices], [0, 1000, 5000000])

        api_model = json.loads((ROOT / "api/v1/models/google-cloud/OCR_PROCESSOR.json").read_text(encoding="utf-8"))
        self.assertEqual(api_model["price_records"], self.model["price_records"])
        with (ROOT / "api/v1/prices.csv").open(encoding="utf-8", newline="") as handle:
            api_csv = next(row for row in csv.DictReader(handle) if (row["provider_id"], row["model_id"]) == MODEL_KEY)
        self.assertEqual(json.loads(api_csv["price_records_json"]), self.model["price_records"])

        website = next(row for row in self.website_projection["models"] if row["canonicalInternalId"] == "google-cloud/OCR_PROCESSOR")
        self.assertFalse(website["defaultSafe"])
        self.assertEqual(len(website["pricingComponents"]), 3)
        self.assertEqual([item["condition"]["usageTier"]["freeAllowance"] for item in website["pricingComponents"]], [1000, 1000, 1000])

        hf = next(row for row in self.hf["records"] if (row["provider_id"], row["model_id"]) == MODEL_KEY)
        self.assertIsNone(hf["unit_price"])
        self.assertIsNone(hf["billing_unit"])
        self.assertEqual(len(hf["pricing_components"]), 3)
        self.assertEqual([item["condition"]["usage_tier"]["tier_end"] for item in hf["pricing_components"]], [1000, 5000000, None])

    def test_gemini_projection_is_byte_equivalent_to_starting_commit(self):
        baseline = json.loads(subprocess.run(
            ["git", "show", "d3ef123808180905bcc25ac52ea3e1b23438b71f:data/canonical/models.json"],
            cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8",
        ).stdout)
        before = [row for row in baseline if row["provider_id"] == "google-gemini"]
        after = [row for row in load_models() if row["provider_id"] == "google-gemini"]
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
