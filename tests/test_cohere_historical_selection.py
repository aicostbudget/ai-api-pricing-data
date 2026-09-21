"""Unknown effective dates must not turn today's verified prices into historical facts."""
import json
import unittest
from copy import deepcopy
from datetime import date

from scripts.lib import ROOT, load_models
from scripts.pricing_contract import select_price_record


class CohereHistoricalSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prices = json.loads((ROOT / "data/pricing-v2-preview/prices.json").read_text(encoding="utf-8"))
        cls.cohere = next(row for row in prices if row["modelInternalId"] == "cohere/command-r-plus-08-2024")
        cls.known = next(row for row in prices if row["modelInternalId"] == "anthropic/claude-opus-5" and row["processingMode"] == "standard")
        cls.model = next(row for row in load_models() if (row["provider_id"], row["model_id"]) == ("cohere", "command-r-plus-08-2024"))

    def select(self, records, at):
        return select_price_record(records, processing_mode="standard", prompt_tokens=1000, at=at)

    def test_cohere_official_effective_date_stays_unknown(self):
        self.assertIsNone(self.model["effective_from"])
        self.assertIsNone(self.cohere["effectiveFrom"])
        self.assertEqual({charge["component"]: charge["amount"] for charge in self.cohere["charges"]}, {"input": "2.5", "output": "10"})

    def test_unsupported_2024_boundaries_are_explicitly_unavailable(self):
        for day in ("2024-07-31", "2024-08-01", "2024-08-30"):
            with self.subTest(day=day):
                result = self.select([self.cohere], day)
                self.assertEqual(result["selectionStatus"], "unavailable")
                self.assertIn("Historical price coverage is unknown", result["reason"])
                self.assertNotIn("charges", result)

    def test_current_verified_price_is_still_selected(self):
        for day in (None, date.today().isoformat()):
            with self.subTest(day=day):
                result = self.select([self.cohere], day)
                self.assertEqual(result["selectionStatus"], "available")
                self.assertEqual(result["pricingId"], self.cohere["pricingId"])

    def test_dated_historical_record_wins_over_unknown_current_record(self):
        historical = deepcopy(self.cohere)
        historical["pricingId"] = "fixture:dated-historical"
        historical["pricingStatus"] = "historical"
        historical["effectiveFrom"] = "2024-08-30"
        historical["effectiveUntil"] = "2024-08-31"
        selected = self.select([self.cohere, historical], "2024-08-30")
        self.assertEqual(selected["pricingId"], historical["pricingId"])
        self.assertEqual(selected["selectionStatus"], "available")
        self.assertEqual(self.select([self.cohere, historical], "2024-09-01")["selectionStatus"], "unavailable")
        self.assertEqual(self.select([self.cohere, historical], None)["pricingId"], self.cohere["pricingId"])

    def test_known_effective_boundary_and_other_models_remain_unchanged(self):
        self.assertEqual(self.known["effectiveFrom"], "2026-07-24")
        self.assertEqual(self.select([self.known], "2026-07-23")["selectionStatus"], "unavailable")
        self.assertEqual(self.select([self.known], "2026-07-24")["pricingId"], self.known["pricingId"])

    def test_generic_unknown_start_is_not_a_negative_infinity(self):
        other = deepcopy(self.cohere)
        other["modelInternalId"] = "fixture/another-model"
        self.assertEqual(self.select([other], "2024-07-31")["selectionStatus"], "unavailable")
        self.assertEqual(self.select([other], None)["selectionStatus"], "available")


class UndatedCurrentPriceSelectionTests(unittest.TestCase):
    # These 29 models have a single applicable Standard/short record at 1K
    # prompt tokens, an unknown effectiveFrom, and no dated historical record.
    # The six remaining undated models need usage, region, or variant selection.
    ORDINARY_MODEL_IDS = (
        "anthropic/claude-haiku-4.5",
        "anthropic/claude-opus-4.8",
        "anthropic/claude-sonnet-4.6",
        "google-gemini/gemini-2.5-flash",
        "google-gemini/gemini-2.5-pro",
        "google-gemini/gemini-3.5-flash-lite",
        "mistral-ai/codestral-2508",
        "mistral-ai/ministral-14b-2512",
        "mistral-ai/ministral-3b-2512",
        "mistral-ai/ministral-8b-2512",
        "mistral-ai/mistral-large",
        "mistral-ai/mistral-medium-3-5",
        "mistral-ai/mistral-small-2603",
        "moonshot-ai/kimi-k2.6",
        "moonshot-ai/kimi-k2.7-code",
        "moonshot-ai/kimi-k3",
        "openai/gpt-4.1",
        "openai/gpt-5",
        "openai/gpt-5.4-mini",
        "openai/gpt-5.5",
        "openai/gpt-5.6-luna",
        "openai/gpt-5.6-terra",
        "openai/o3",
        "xai/grok-4.20-0309-non-reasoning",
        "xai/grok-4.20-0309-reasoning",
        "xai/grok-4.20-multi-agent-0309",
        "xai/grok-4.3",
        "xai/grok-4.5",
        "xai/grok-4.6",
    )

    @classmethod
    def setUpClass(cls):
        cls.prices = json.loads((ROOT / "data/pricing-v2-preview/prices.json").read_text(encoding="utf-8"))
        cls.snapshot = json.loads((ROOT / "data/snapshots/2026-09-14/prices.json").read_text(encoding="utf-8"))

    def test_ordinary_undated_prices_are_current_only_at_date_precision(self):
        self.assertEqual(len(self.ORDINARY_MODEL_IDS), 29)
        observed_at = self.snapshot["generated_at"]
        self.assertTrue(observed_at.startswith("2026-09-14T"))
        snapshot_ids = {row["provider_id"] + "/" + row["model_id"] for row in self.snapshot["models"]}
        self.assertTrue(set(self.ORDINARY_MODEL_IDS) <= snapshot_ids)
        for model_id in self.ORDINARY_MODEL_IDS:
            with self.subTest(model_id=model_id):
                rows = [row for row in self.prices if row["modelInternalId"] == model_id]
                current = [row for row in rows if row.get("pricingStatus", "current") == "current"]
                self.assertTrue(current)
                self.assertTrue(all(row["effectiveFrom"] is None for row in current))
                self.assertFalse(any(row.get("pricingStatus") == "historical" for row in rows))
                self.assertTrue(all(row["sourceRefs"] for row in current))
                expected_id = f"price:{model_id}:standard:short:current"
                self.assertIn(expected_id, {row["pricingId"] for row in current})
                today = select_price_record(rows, processing_mode="standard", prompt_tokens=1000)
                self.assertEqual(today["selectionStatus"], "available")
                self.assertEqual(today["pricingId"], expected_id)
                for at in (observed_at[:10], observed_at):
                    past = select_price_record(rows, processing_mode="standard", prompt_tokens=1000, at=at)
                    self.assertEqual(past["selectionStatus"], "unavailable")
                    self.assertNotIn("charges", past)

    def test_explicit_dated_interval_still_selects_at_both_boundaries(self):
        template = next(row for row in self.prices if row["modelInternalId"] == "openai/gpt-5.6-terra" and row["processingMode"] == "standard" and row["contextClass"] == "short")
        historical = deepcopy(template)
        historical["pricingId"] = "fixture:explicit-historical-interval"
        historical["pricingStatus"] = "historical"
        historical["effectiveFrom"] = "2026-08-01"
        historical["effectiveUntil"] = "2026-08-31"
        for at in ("2026-08-01", "2026-08-15", "2026-08-31"):
            with self.subTest(at=at):
                selected = select_price_record([template, historical], processing_mode="standard", prompt_tokens=1000, at=at)
                self.assertEqual(selected["pricingId"], historical["pricingId"])
                self.assertEqual(selected["selectionStatus"], "available")
        after = select_price_record([template, historical], processing_mode="standard", prompt_tokens=1000, at="2026-09-01")
        self.assertEqual(after["selectionStatus"], "unavailable")


if __name__ == "__main__":
    unittest.main()
