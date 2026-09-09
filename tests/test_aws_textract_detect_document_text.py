import csv
import json
import subprocess
import unittest
from decimal import Decimal

from scripts.lib import ROOT, load_models, load_providers
from scripts.pricing_contract import (
    PricingContractError,
    calculate_graduated_usage_cost,
    calculate_usage_cost_with_allowance,
    validate_model_price_records,
)
from tests.website_source import resolve_website_source


WEBSITE = resolve_website_source(ROOT)
MODEL_KEY = ("aws", "DetectDocumentText")


class AwsTextractDetectDocumentTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = {(row["provider_id"], row["model_id"]): row for row in load_models()}
        cls.model = cls.models[MODEL_KEY]
        cls.records = cls.model["price_records"]
        cls.allowance = cls.model["conditional_usage_allowances"][0]
        cls.v2_models = json.loads((ROOT / "data/pricing-v2-preview/models.json").read_text(encoding="utf-8"))
        cls.v2_prices = json.loads((ROOT / "data/pricing-v2-preview/prices.json").read_text(encoding="utf-8"))
        cls.website_projection = json.loads((WEBSITE / "data/pricing-v2-projection/model-pricing.v2.json").read_text(encoding="utf-8"))
        cls.hf = json.loads((ROOT / "huggingface/prices.json").read_text(encoding="utf-8"))

    def test_provider_and_operation_identity_are_narrow(self):
        providers = {row["provider_id"]: row for row in load_providers()}
        self.assertEqual(providers["aws"]["display_name"], "Amazon Web Services")
        self.assertEqual(self.model["model_id"], "DetectDocumentText")
        self.assertEqual(self.model["model_category"], "document_parsing")
        self.assertIn("synchronous Basic OCR", self.model["notes"])
        self.assertNotIn(("aws", "StartDocumentTextDetection"), self.models)
        self.assertFalse(any(provider == "aws" and model_id.startswith("Analyze") for provider, model_id in self.models))

    def test_paid_contract_preserves_graduated_page_tiers_and_regions(self):
        validate_model_price_records(self.model)
        self.assertEqual([row["usage_tier"]["tier_start"] for row in self.records], [0, 1000000])
        self.assertEqual([row["usage_tier"]["tier_end"] for row in self.records], [1000000, None])
        self.assertEqual([row["charges"][0]["amount"] for row in self.records], ["1.5", "0.6"])
        self.assertTrue(all(row["charges"][0]["unit"] == "per_1000_pages" for row in self.records))
        self.assertTrue(all(row["usage_tier"]["free_allowance"] == 0 for row in self.records))
        self.assertTrue(all(row["usage_tier"]["tier_mode"] == "graduated" for row in self.records))
        self.assertTrue(all(row["region_policy"]["pricing_geography"] == "region_specific" for row in self.records))
        self.assertTrue(all(len(row["region_policy"]["endpoint_geographies"]) == 16 for row in self.records))

    def test_conditional_trial_is_not_a_standard_free_tier(self):
        self.assertEqual(self.allowance["offer_type"], "short_term_trial")
        self.assertEqual(self.allowance["eligibility"], {"customer_status": "new_customer", "account_plan": "paid"})
        self.assertEqual(self.allowance["allowance"], 1000)
        self.assertEqual(self.allowance["billing_period"], "calendar_month")
        self.assertEqual(self.allowance["duration"], {"value": 3, "unit": "month", "starts_on": "offer_activation"})
        self.assertEqual(len(self.allowance["region_selector"]["endpoint_geographies"]), 14)
        self.assertNotIn("us-gov-east-1", self.allowance["region_selector"]["endpoint_geographies"])

    def test_standard_and_conditional_boundary_math(self):
        expected = {
            0: Decimal("0"),
            1: Decimal("0.0015"),
            1000000: Decimal("1500"),
            1000001: Decimal("1500.0006"),
            2000000: Decimal("2100"),
        }
        for pages, cost in expected.items():
            self.assertEqual(calculate_graduated_usage_cost(self.records, pages), cost)
        self.assertEqual(
            calculate_usage_cost_with_allowance(self.records, 1000, allowance=self.allowance, eligible=True),
            Decimal("0"),
        )
        self.assertEqual(
            calculate_usage_cost_with_allowance(self.records, 1001, allowance=self.allowance, eligible=True),
            Decimal("0.0015"),
        )
        self.assertEqual(
            calculate_usage_cost_with_allowance(self.records, 1000, allowance=self.allowance, eligible=False),
            Decimal("1.5"),
        )

    def test_region_adjustment_math_and_allowance_scope(self):
        self.assertEqual(
            calculate_graduated_usage_cost(self.records, 2000000, endpoint_geography="us-west-1"),
            Decimal("2940.0"),
        )
        self.assertEqual(
            calculate_graduated_usage_cost(self.records, 2000000, endpoint_geography="us-gov-east-1"),
            Decimal("2646.00"),
        )
        with self.assertRaisesRegex(PricingContractError, "does not cover"):
            calculate_usage_cost_with_allowance(
                self.records,
                1000,
                allowance=self.allowance,
                eligible=True,
                endpoint_geography="us-gov-east-1",
            )

    def test_v2_api_hf_and_website_are_lossless(self):
        v2_model = next(row for row in self.v2_models if row["internalId"] == "aws/DetectDocumentText")
        self.assertEqual(v2_model["canonicalOfficialId"], "DetectDocumentText")
        self.assertEqual(v2_model["conditionalUsageAllowances"][0]["allowance"], 1000)
        v2_prices = [row for row in self.v2_prices if row["modelInternalId"] == "aws/DetectDocumentText"]
        self.assertEqual(len(v2_prices), 2)
        self.assertEqual([row["usageTier"]["tierStart"] for row in v2_prices], [0, 1000000])

        api_model = json.loads((ROOT / "api/v1/models/aws/DetectDocumentText.json").read_text(encoding="utf-8"))
        self.assertEqual(api_model["price_records"], self.records)
        self.assertEqual(api_model["conditional_usage_allowances"], [self.allowance])
        with (ROOT / "api/v1/prices.csv").open(encoding="utf-8", newline="") as handle:
            api_csv = next(row for row in csv.DictReader(handle) if (row["provider_id"], row["model_id"]) == MODEL_KEY)
        self.assertEqual(json.loads(api_csv["price_records_json"]), self.records)
        self.assertEqual(json.loads(api_csv["conditional_usage_allowances_json"]), [self.allowance])

        website = next(row for row in self.website_projection["models"] if row["canonicalInternalId"] == "aws/DetectDocumentText")
        self.assertFalse(website["defaultSafe"])
        self.assertEqual(website["conditionalUsageAllowances"][0]["eligibility"]["customerStatus"], "new_customer")
        self.assertEqual(len(website["pricingComponents"]), 2)

        hf = next(row for row in self.hf["records"] if (row["provider_id"], row["model_id"]) == MODEL_KEY)
        self.assertEqual(hf["conditional_usage_allowances"][0]["allowance"], 1000)
        self.assertEqual(len(hf["pricing_components"]), 2)

    def test_google_cloud_ocr_and_gemini_regressions_are_preserved(self):
        self.assertIn(("google-cloud", "OCR_PROCESSOR"), self.models)
        baseline = json.loads(subprocess.run(
            ["git", "show", "d3ef123808180905bcc25ac52ea3e1b23438b71f:data/canonical/models.json"],
            cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8",
        ).stdout)
        before = [row for row in baseline if row["provider_id"] == "google-gemini"]
        after = [row for row in load_models() if row["provider_id"] == "google-gemini"]
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
