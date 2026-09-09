import csv
import json
import unittest
from decimal import Decimal

from scripts.lib import ROOT, load_models, load_providers
from scripts.pricing_contract import PricingContractError, calculate_graduated_usage_cost, validate_model_price_records


WEBSITE = ROOT.parent / "ai-cost-control-tool" / "aicostguard-english"
MODEL_KEY = ("azure", "prebuilt-read")
COMMERCIAL_REGIONS = {
    "australiaeast", "brazilsouth", "canadacentral", "centralindia", "centralus", "eastasia",
    "eastus", "eastus2", "francecentral", "germanywestcentral", "italynorth", "japaneast",
    "japanwest", "koreacentral", "northcentralus", "northeurope", "norwayeast", "qatarcentral",
    "southafricanorth", "southcentralus", "southeastasia", "swedencentral", "switzerlandnorth",
    "switzerlandwest", "uaenorth", "uksouth", "westcentralus", "westeurope", "westus", "westus2",
    "westus3",
}


class AzureDocumentIntelligenceReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = {(row["provider_id"], row["model_id"]): row for row in load_models()}
        cls.model = cls.models[MODEL_KEY]
        cls.records = cls.model["price_records"]
        cls.v2_models = json.loads((ROOT / "data/pricing-v2-preview/models.json").read_text(encoding="utf-8"))
        cls.v2_prices = json.loads((ROOT / "data/pricing-v2-preview/prices.json").read_text(encoding="utf-8"))
        cls.website_projection = json.loads((WEBSITE / "data/pricing-v2-projection/model-pricing.v2.json").read_text(encoding="utf-8"))
        cls.hf = json.loads((ROOT / "huggingface/prices.json").read_text(encoding="utf-8"))

    def test_provider_and_exact_identity_are_narrow(self):
        providers = {row["provider_id"]: row for row in load_providers()}
        self.assertEqual(providers["azure"]["display_name"], "Microsoft Azure")
        self.assertEqual(self.model["model_id"], "prebuilt-read")
        self.assertEqual(self.model["model_category"], "document_parsing")
        self.assertEqual(self.model["release_stage"], "stable")
        self.assertIn("2024-11-30 API", self.model["notes"])
        self.assertNotIn(("azure", "prebuilt-layout"), self.models)

    def test_s0_standard_contract_has_only_two_paid_graduated_tiers(self):
        validate_model_price_records(self.model)
        self.assertEqual([row["processing_mode"] for row in self.records], ["standard", "standard"])
        self.assertEqual([row["usage_tier"]["tier_start"] for row in self.records], [0, 1_000_000])
        self.assertEqual([row["usage_tier"]["tier_end"] for row in self.records], [1_000_000, None])
        self.assertEqual([row["charges"][0]["amount"] for row in self.records], ["1.5", "0.6"])
        self.assertTrue(all(row["charges"][0]["component"] == "document_page" for row in self.records))
        self.assertTrue(all(row["charges"][0]["unit"] == "per_1000_pages" for row in self.records))
        self.assertTrue(all(row["usage_tier"]["billing_period"] == "calendar_month" for row in self.records))
        self.assertTrue(all(row["usage_tier"]["tier_mode"] == "graduated" for row in self.records))
        self.assertTrue(all(row["usage_tier"]["usage_scope"] == "unknown" for row in self.records))
        self.assertTrue(all(row["usage_tier"]["free_allowance"] == 0 for row in self.records))
        self.assertTrue(all(row["calculation_default"] is False for row in self.records))
        self.assertNotIn("conditional_usage_allowances", self.model)

    def test_commercial_regions_are_explicit_and_government_is_not_admitted(self):
        for row in self.records:
            policy = row["region_policy"]
            self.assertEqual(policy["pricing_geography"], "region_specific")
            self.assertEqual(set(policy["endpoint_geographies"]), COMMERCIAL_REGIONS)
            self.assertEqual(policy["price_adjustments"], [])
            self.assertFalse(any(region.startswith("usgov") for region in policy["endpoint_geographies"]))
        for region in ("eastus", "westeurope", "southeastasia"):
            self.assertEqual(calculate_graduated_usage_cost(self.records, 2_000_000, endpoint_geography=region), Decimal("2100"))
        with self.assertRaisesRegex(PricingContractError, "outside price record"):
            calculate_graduated_usage_cost(self.records, 1, endpoint_geography="usgovarizona")

    def test_tier_boundaries_are_graduated(self):
        expected = {
            0: Decimal("0"),
            1: Decimal("0.0015"),
            999_999: Decimal("1499.9985"),
            1_000_000: Decimal("1500"),
            1_000_001: Decimal("1500.0006"),
            2_000_000: Decimal("2100"),
        }
        for pages, cost in expected.items():
            self.assertEqual(calculate_graduated_usage_cost(self.records, pages), cost)

    def test_f0_batch_government_and_token_scalars_are_absent(self):
        self.assertTrue(all(self.model["pricing"][field] is None for field in (
            "unit", "input", "output", "cached_input", "cache_write", "cache_write_1h", "batch_input", "batch_output"
        )))
        serialized = json.dumps(self.model).lower()
        self.assertTrue(all(row["processing_mode"] == "standard" for row in self.records))
        self.assertFalse(any("batch" in row["id"].lower() for row in self.records))
        self.assertNotIn("free_allowance\": 500", serialized)
        self.assertNotIn("usgov", serialized)
        self.assertTrue(all(any("prices.azure.com" in source for source in row["source_refs"]) for row in self.records))
        self.assertTrue(all(row["verified_at"].startswith("2026-09-09") for row in self.records))

    def test_v2_api_hf_and_website_are_lossless(self):
        v2_model = next(row for row in self.v2_models if row["internalId"] == "azure/prebuilt-read")
        self.assertEqual(v2_model["canonicalOfficialId"], "prebuilt-read")
        v2_prices = [row for row in self.v2_prices if row["modelInternalId"] == "azure/prebuilt-read"]
        self.assertEqual(len(v2_prices), 2)
        self.assertEqual([row["usageTier"]["tierStart"] for row in v2_prices], [0, 1_000_000])

        api_model = json.loads((ROOT / "api/v1/models/azure/prebuilt-read.json").read_text(encoding="utf-8"))
        self.assertEqual(api_model["price_records"], self.records)
        with (ROOT / "api/v1/prices.csv").open(encoding="utf-8", newline="") as handle:
            api_csv = next(row for row in csv.DictReader(handle) if (row["provider_id"], row["model_id"]) == MODEL_KEY)
        self.assertEqual(json.loads(api_csv["price_records_json"]), self.records)

        website = next(row for row in self.website_projection["models"] if row["canonicalInternalId"] == "azure/prebuilt-read")
        self.assertFalse(website["defaultSafe"])
        self.assertEqual(len(website["pricingComponents"]), 2)
        self.assertNotIn("conditionalUsageAllowances", website)

        hf = next(row for row in self.hf["records"] if (row["provider_id"], row["model_id"]) == MODEL_KEY)
        self.assertIsNone(hf["unit_price"])
        self.assertIsNone(hf["billing_unit"])
        self.assertEqual(len(hf["pricing_components"]), 2)
        self.assertEqual(hf["conditional_usage_allowances"], [])

    def test_existing_ocr_providers_remain_present(self):
        for key in (
            ("cohere", "parse-v5.0"),
            ("mistral-ai", "mistral-ocr-4-0"),
            ("mistral-ai", "mistral-ocr-4-1"),
            ("google-cloud", "OCR_PROCESSOR"),
            ("aws", "DetectDocumentText"),
        ):
            self.assertIn(key, self.models)


if __name__ == "__main__":
    unittest.main()
