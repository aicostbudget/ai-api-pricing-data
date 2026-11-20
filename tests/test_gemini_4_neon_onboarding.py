from __future__ import annotations

import json
import unittest
from decimal import Decimal
from pathlib import Path

from scripts.pricing_contract import project_v1_compatibility, validate_model_price_records


ROOT = Path(__file__).resolve().parents[1]
PROVIDER = "google-gemini"
MODEL_ID = "gemini-4-neon"
PRICING_PAGE = "https://ai.google.dev/gemini-api/docs/pricing"
MODEL_PAGE = "https://ai.google.dev/gemini-api/docs/models/gemini-4-neon"
CHANGELOG = "https://ai.google.dev/gemini-api/docs/changelog"
# Paid-tier list prices, USD per 1M tokens, read from the official pages on 2026-11-20
# (reports/price-evidence/google-gemini/gemini-4-neon).
EXPECTED = {
    "standard": {"input": "3", "cached_input": "0.15", "output": "15"},
    "batch": {"input": "1.5", "cached_input": "0.075", "output": "7.5"},
    "flex": {"input": "1.5", "cached_input": "0.075", "output": "7.5"},
    "priority": {"input": "5.4", "cached_input": "0.27", "output": "27"},
}


def read_json(relative_path: str):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


class Gemini4NeonOnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.canonical = {
            (row["provider_id"], row["model_id"]): row for row in read_json("data/canonical/models.json")
        }
        cls.model = cls.canonical[(PROVIDER, MODEL_ID)]
        validate_model_price_records(cls.model)

    def test_identity_sources_and_release_date(self) -> None:
        model = self.model
        self.assertEqual(model["display_name"], "Gemini 4 Neon")
        self.assertEqual(model["model_family"], "Gemini 4")
        self.assertEqual(model["status"], "active")
        self.assertEqual(model["context_window_tokens"], 1_048_576)
        self.assertEqual(model["official_source_url"], PRICING_PAGE)
        self.assertEqual(model["official_source_urls"], [PRICING_PAGE, MODEL_PAGE, CHANGELOG])
        # The Gemini API changelog lists Gemini 4 Neon as generally available on November 18, 2026.
        self.assertEqual(model["released_at"], "2026-11-18")
        self.assertEqual(model["effective_from"], "2026-11-18")
        self.assertEqual(model["release_evidence"]["url"], CHANGELOG)
        self.assertEqual(model["access_status"], "public")
        self.assertEqual(model["binding_evidence"][0]["official_model_id"], MODEL_ID)
        self.assertIn("paid tier only", model["notes"])
        self.assertIn("not available on the Free tier", model["notes"])

    def test_paid_tier_prices_by_processing_mode(self) -> None:
        records = self.model["price_records"]
        self.assertEqual(sorted(row["processing_mode"] for row in records), sorted(EXPECTED))
        for record in records:
            mode = record["processing_mode"]
            self.assertEqual(record["context_class"], "short")
            self.assertEqual(record["pricing_status"], "current")
            self.assertEqual(record["effective_from"], "2026-11-18")
            self.assertIsNone(record["effective_until"], f"{mode} must not carry a scheduled step")
            self.assertEqual(record["region_policy"]["pricing_geography"], "global_base")
            charges = {charge["component"]: Decimal(str(charge["amount"])) for charge in record["charges"]}
            self.assertEqual(charges, {key: Decimal(value) for key, value in EXPECTED[mode].items()}, mode)
        self.assertEqual([row["processing_mode"] for row in records if row["calculation_default"]], ["standard"])

    def test_priority_is_1_8x_and_batch_flex_are_half_of_standard(self) -> None:
        standard = {key: Decimal(value) for key, value in EXPECTED["standard"].items()}
        for key, value in standard.items():
            self.assertEqual(Decimal(EXPECTED["batch"][key]), value / 2)
            self.assertEqual(Decimal(EXPECTED["flex"][key]), value / 2)
            self.assertEqual(Decimal(EXPECTED["priority"][key]), value * Decimal("1.8"))
        # Implicit cache hits are priced 95% below input.
        self.assertEqual(standard["cached_input"], standard["input"] * Decimal("0.05"))

    def test_v1_projection_and_neighbours_unchanged(self) -> None:
        projected = project_v1_compatibility(self.model["price_records"])
        self.assertEqual((projected["input"], projected["output"], projected["cached_input"]), (3.0, 15.0, 0.15))
        self.assertEqual((self.model["pricing"]["batch_input"], self.model["pricing"]["batch_output"]), (1.5, 7.5))
        self.assertEqual(self.model["pricing"]["batch_cached_input"], 0.075)
        hydrogen = self.canonical[(PROVIDER, "gemini-4-hydrogen")]
        self.assertEqual((hydrogen["pricing"]["input"], hydrogen["pricing"]["output"]), (1.5, 7.5))
        # Neon lists at exactly twice Hydrogen's launch price on every Standard line.
        self.assertEqual(self.model["pricing"]["input"], hydrogen["pricing"]["input"] * 2)
        self.assertEqual(self.model["pricing"]["output"], hydrogen["pricing"]["output"] * 2)
        self.assertEqual(self.model["pricing"]["cached_input"], hydrogen["pricing"]["cached_input"] * 2)


if __name__ == "__main__":
    unittest.main()
