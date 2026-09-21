"""Official long-context prices and selector boundaries for Issue #22."""
import json
import unittest

from scripts.lib import ROOT, load_models
from scripts.pricing_contract import select_price_record, validate_model_price_records


SPECS = {
    "openai/gpt-5.5": (272000, False, {
        "standard": (("5", "0.5", "30"), ("10", "1", "45")),
        "batch": (("2.5", "0.25", "15"), ("5", "0.5", "22.5")),
        "flex": (("2.5", "0.25", "15"), ("5", "0.5", "22.5")),
    }),
    "google-gemini/gemini-2.5-pro": (200000, False, {
        "standard": (("1.25", "0.125", "10"), ("2.5", "0.25", "15")),
        "batch": (("0.625", "0.125", "5"), ("1.25", "0.25", "7.5")),
        "flex": (("0.625", "0.125", "5"), ("1.25", "0.25", "7.5")),
        "priority": (("2.25", "0.225", "18"), ("4.5", "0.45", "27")),
    }),
    "xai/grok-4.5": (200000, True, {
        "standard": (("2", "0.3", "6"), ("4", "0.6", "12")),
    }),
}


class Issue22LongContextTests(unittest.TestCase):
    def test_canonical_v2_prices_and_boundary_selector(self):
        models = {f"{row['provider_id']}/{row['model_id']}": row for row in load_models()}
        all_prices = json.loads((ROOT / "data/pricing-v2-preview/prices.json").read_text(encoding="utf-8"))
        for model_id, (threshold, inclusive, modes) in SPECS.items():
            with self.subTest(model=model_id):
                model = models[model_id]
                validate_model_price_records(model)
                self.assertIsNone(model["effective_from"])
                self.assertEqual(len(model["price_records"]), 2 * len(modes))
                prices = [row for row in all_prices if row["modelInternalId"] == model_id]
                self.assertEqual(len(prices), 2 * len(modes))
                self.assertEqual(sum(row["calculationDefault"] for row in prices), 1)
                for mode, (short, long) in modes.items():
                    for context, rates in (("short", short), ("long", long)):
                        record_id = f"price:{model_id}:{mode}:{context}:current"
                        record = next(row for row in prices if row["pricingId"] == record_id)
                        self.assertEqual(record["promptTokenThreshold"], threshold)
                        self.assertEqual(record["tierSelection"]["cachedPromptTokensIncluded"], True)
                        self.assertEqual(record["tierSelection"]["wholeRequestPricing"], True)
                        self.assertEqual(record["effectiveFrom"], None)
                        self.assertEqual(record["verificationStatus"], "verified")
                        self.assertTrue(record["sourceRefs"])
                        self.assertEqual(
                            tuple(next(charge["amount"] for charge in record["charges"] if charge["component"] == item)
                                  for item in ("input", "cached_input", "output")), rates)
                        self.assertTrue(all(charge["unit"] == "per_1m_tokens" for charge in record["charges"]))
                    for prompt_tokens in (threshold - 1, threshold, threshold + 1):
                        expected_context = "long" if prompt_tokens > threshold or inclusive and prompt_tokens == threshold else "short"
                        selected = select_price_record(prices, processing_mode=mode, prompt_tokens=prompt_tokens)
                        self.assertEqual(selected["pricingId"], f"price:{model_id}:{mode}:{expected_context}:current")
                if model_id == "xai/grok-4.5":
                    self.assertEqual(select_price_record(prices, processing_mode="batch", prompt_tokens=200000)["selectionStatus"], "unavailable")


if __name__ == "__main__":
    unittest.main()
