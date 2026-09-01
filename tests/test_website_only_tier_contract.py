import copy
import json
import subprocess
import unittest
from pathlib import Path

from scripts.generate_pricing_v2_preview import (
    build_website_tier_price_records,
    validate_website_pricing_tiers,
)
from scripts.generate_website_projection_v2 import project_canonical_tier


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "website-only-tier-model-pricing.json"
WEBSITE_ROOT = Path(r"D:\ai-cost-control-tool\aicostguard-english")
CONSUMER_TEST = WEBSITE_ROOT / "scripts" / "test-website-only-tier-contract.mjs"


class WebsiteOnlyTierContractTests(unittest.TestCase):
    def setUp(self):
        self.website = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def generated_records(self, website=None):
        website = website or self.website
        records = build_website_tier_price_records(
            "test-provider/test-tiered-website-only",
            website,
            source_refs=["source:test-provider:official-pricing"],
            verification=website["verificationStatus"],
        )
        self.assertIsNotNone(records)
        return records

    def test_synthetic_website_only_row_generates_existing_v2_tier_semantics(self):
        records = self.generated_records()
        by_context = {record["contextClass"]: record for record in records}
        self.assertEqual(set(by_context), {"short", "long"})
        self.assertEqual(
            {record["pricingId"] for record in records},
            {
                "price:test-provider/test-tiered-website-only:standard:short:current",
                "price:test-provider/test-tiered-website-only:standard:long:current",
            },
        )
        self.assertTrue(by_context["short"]["calculationDefault"])
        self.assertFalse(by_context["long"]["calculationDefault"])
        self.assertEqual(by_context["short"]["tierSelection"]["comparison"], "less_than")
        self.assertEqual(
            by_context["long"]["tierSelection"]["comparison"],
            "greater_than_or_equal",
        )
        for record in records:
            self.assertEqual(record["promptTokenThreshold"], 200000)
            self.assertEqual(record["tierSelection"]["tokenBasis"], "total_prompt_tokens")
            self.assertTrue(record["tierSelection"]["cachedPromptTokensIncluded"])
            self.assertTrue(record["tierSelection"]["wholeRequestPricing"])
            self.assertEqual(record["processingMode"], "standard")
            self.assertEqual(record["pricingStatus"], "current")
            self.assertEqual(record["verificationStatus"], "verified")
            self.assertEqual(
                {charge["component"] for charge in record["charges"]},
                {"input", "cached_input", "output"},
            )

        self.assertEqual(
            {charge["component"]: charge["amount"] for charge in by_context["short"]["charges"]},
            {"input": "1", "cached_input": "0.2", "output": "2"},
        )
        self.assertEqual(
            {charge["component"]: charge["amount"] for charge in by_context["long"]["charges"]},
            {"input": "2", "cached_input": "0.4", "output": "4"},
        )

    def test_generated_projection_is_consumed_by_production_tier_resolver(self):
        records = self.generated_records()
        model = {
            "inputPrice": 1,
            "cachedInputPrice": 0.2,
            "outputPrice": 2,
            "pricingTiers": [project_canonical_tier(record) for record in records],
        }
        result = subprocess.run(
            ["node", str(CONSUMER_TEST)],
            cwd=WEBSITE_ROOT,
            input=json.dumps(model),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"production resolver test failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        self.assertIn("website-only generic tier resolver tests passed", result.stdout)

    def test_missing_cached_price_is_explicitly_allowed_without_derivation(self):
        website = copy.deepcopy(self.website)
        website["pricing_tiers"][0]["cached_input"] = None
        records = self.generated_records(website)
        short = next(record for record in records if record["contextClass"] == "short")
        self.assertNotIn("cached_input", {charge["component"] for charge in short["charges"]})

    def test_rows_without_pricing_tiers_keep_the_legacy_path(self):
        website = copy.deepcopy(self.website)
        del website["pricing_tiers"]
        self.assertIsNone(validate_website_pricing_tiers(website))

    def test_invalid_source_data_is_rejected(self):
        cases = []

        negative = copy.deepcopy(self.website)
        negative["pricing_tiers"][0]["input"] = -1
        cases.append((negative, "invalid or missing input price"))

        zero_threshold = copy.deepcopy(self.website)
        zero_threshold["pricing_tiers"][0]["prompt_token_threshold"] = 0
        cases.append((zero_threshold, "invalid prompt_token_threshold"))

        missing_output = copy.deepcopy(self.website)
        del missing_output["pricing_tiers"][1]["output"]
        cases.append((missing_output, "invalid or missing output price"))

        invalid_comparison = copy.deepcopy(self.website)
        invalid_comparison["pricing_tiers"][0]["threshold_comparison"] = "at_least"
        cases.append((invalid_comparison, "invalid threshold_comparison"))

        invalid_basis = copy.deepcopy(self.website)
        invalid_basis["pricing_tiers"][0]["threshold_token_basis"] = "uncached_input_tokens"
        cases.append((invalid_basis, "invalid threshold_token_basis"))

        duplicate_id = copy.deepcopy(self.website)
        duplicate_id["pricing_tiers"][1]["id"] = "short"
        cases.append((duplicate_id, "duplicate tier id"))

        conflicting = copy.deepcopy(self.website)
        conflicting["pricing_tiers"][1]["threshold_comparison"] = "less_than"
        cases.append((conflicting, "duplicate/conflicting tiers"))

        gap = copy.deepcopy(self.website)
        gap["pricing_tiers"][1]["prompt_token_threshold"] = 200001
        cases.append((gap, "conflicting tiers or gaps"))

        for website, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    validate_website_pricing_tiers(website)


if __name__ == "__main__":
    unittest.main()
