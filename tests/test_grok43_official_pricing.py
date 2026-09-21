"""Grok 4.3 official rates, modes, and exact 200k prompt boundary."""
import json
import unittest
from datetime import date

from scripts.lib import ROOT, load_models
from scripts.pricing_contract import select_price_record


class Grok43OfficialPricingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        all_prices = json.loads((ROOT / "data/pricing-v2-preview/prices.json").read_text(encoding="utf-8"))
        cls.prices = [row for row in all_prices if row["modelInternalId"] == "xai/grok-4.3"]
        cls.other_grok = [row for row in all_prices if row["modelInternalId"] == "xai/grok-4.5"]
        cls.model = next(row for row in load_models() if (row["provider_id"], row["model_id"]) == ("xai", "grok-4.3"))

    def test_verified_current_model_and_source_identity(self):
        self.assertEqual(self.model["status"], "active")
        self.assertIsNone(self.model["effective_from"])
        self.assertEqual(self.model["last_verified_at"], "2026-09-20T13:28:36Z")
        self.assertEqual(len(self.prices), 6)
        self.assertEqual(sum(row["calculationDefault"] for row in self.prices), 1)
        self.assertTrue(all(row["verificationStatus"] == "verified" and row["sourceRefs"] for row in self.prices))

    def test_modes_prices_and_exact_boundary(self):
        expected = {
            "standard": (("1.25", "0.2", "2.5"), ("2.5", "0.4", "5")),
            "batch": (("1", "0.16", "2"), ("2", "0.32", "4")),
            "priority": (("2.5", "0.4", "5"), ("5", "0.8", "10")),
        }
        for mode, contexts in expected.items():
            for tokens, context in ((199999, "short"), (200000, "long"), (200001, "long")):
                with self.subTest(mode=mode, tokens=tokens):
                    record = select_price_record(self.prices, processing_mode=mode, prompt_tokens=tokens)
                    self.assertEqual(record["pricingId"], f"price:xai/grok-4.3:{mode}:{context}:current")
                    self.assertEqual(tuple(c["amount"] for c in record["charges"]), contexts[context == "long"])
                    self.assertEqual({c["component"] for c in record["charges"]}, {"input", "cached_input", "output"})
                    self.assertEqual(record["promptTokenThreshold"], 200000)
                    self.assertTrue(record["tierSelection"]["cachedPromptTokensIncluded"])
                    self.assertTrue(record["tierSelection"]["wholeRequestPricing"])

    def test_unavailable_mode_and_other_grok_isolation(self):
        self.assertEqual(select_price_record(self.prices, processing_mode="flex", prompt_tokens=1)["selectionStatus"], "unavailable")
        self.assertEqual(select_price_record(self.other_grok, processing_mode="batch", prompt_tokens=200000)["selectionStatus"], "unavailable")
        self.assertEqual(select_price_record(self.other_grok, processing_mode="standard", prompt_tokens=200000)["pricingId"],
                         "price:xai/grok-4.5:standard:long:current")

    def test_redirected_grok_3_resolves_every_billing_source(self):
        projection = json.loads((ROOT / "data/pricing-v2-preview/generated/model-pricing.v2.json").read_text(encoding="utf-8"))
        redirected = next(row for row in projection["models"] if row["id"] == "grok-3")
        self.assertEqual(redirected["redirectedBilling"]["billingModelInternalId"], "xai/grok-4.3")
        known_refs = set(redirected["sourceRefs"])
        for component in redirected["pricingComponents"]:
            self.assertLessEqual(set(component["sourceRefs"]), known_refs)


if __name__ == "__main__":
    unittest.main()
