from __future__ import annotations

import json
import os
import unittest
from decimal import Decimal
from pathlib import Path

from scripts.generate_website_projection_v2 import build_projection
from scripts.pricing_contract import (
    normalize_canonical_price_records,
    project_v1_compatibility,
    select_price_record,
    validate_model_price_records,
)


ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "gemini-4-argon"
INTERNAL_ID = f"google-gemini/{MODEL_ID}"
EXPECTED = {
    "2026-11-30": {
        "standard": ("2", "0.1", "10"),
        "batch": ("1", "0.05", "5"),
        "flex": ("1", "0.05", "5"),
        "priority": ("3.6", "0.18", "18"),
    },
    "2026-12-01": {
        "standard": ("4", "0.2", "20"),
        "batch": ("2", "0.1", "10"),
        "flex": ("2", "0.1", "10"),
        "priority": ("7.2", "0.36", "36"),
    },
}


def read_json(relative_path: str):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def exactly_one(rows, predicate, label: str):
    matches = [row for row in rows if predicate(row)]
    if len(matches) != 1:
        raise AssertionError(f"{label} must appear exactly once, found {len(matches)}")
    return matches[0]


class Gemini4ArgonOnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = exactly_one(
            read_json("data/canonical/models.json"),
            lambda row: row["provider_id"] == "google-gemini" and row["model_id"] == MODEL_ID,
            "canonical Gemini 4 Argon",
        )
        validate_model_price_records(cls.model)
        cls.normalized = normalize_canonical_price_records(
            INTERNAL_ID,
            cls.model["price_records"],
            lambda url: url,
        )

    def test_identity_capabilities_and_v1_contract(self) -> None:
        model = self.model
        self.assertEqual(model["display_name"], "Gemini 4 Argon")
        self.assertEqual(model["status"], "active")
        self.assertEqual(model["release_stage"], "stable")
        self.assertEqual(model["released_at"], "2026-10-13")
        self.assertEqual(model["context_window_tokens"], 1_048_576)
        self.assertEqual(model["max_output_tokens"], 65_536)
        self.assertEqual(model["access_status"], "public")
        self.assertEqual(model["binding_status"], "approved")
        self.assertIn("Long Decode", model["notes"])
        self.assertIn("Only implicit caching", model["notes"])
        self.assertIn("No Free Tier", model["notes"])
        self.assertIn("Grounding is priced separately", model["notes"])
        self.assertEqual(project_v1_compatibility(model["price_records"]), model["pricing"])

    def test_exact_eight_record_matrix_and_date_boundary(self) -> None:
        records = self.model["price_records"]
        self.assertEqual(len(records), 8)
        self.assertEqual(sum(record["calculation_default"] for record in records), 1)
        self.assertEqual(
            {(record["processing_mode"], record["pricing_status"]) for record in records},
            {(mode, status) for mode in EXPECTED["2026-11-30"] for status in ("current", "future")},
        )
        self.assertEqual(len({record["id"] for record in records}), 8)
        self.assertEqual(len({charge["id"] for record in records for charge in record["charges"]}), 24)
        for record in records:
            self.assertEqual(
                {charge["component"] for charge in record["charges"]},
                {"input", "cached_input", "output"},
            )
            self.assertNotIn("grounding", {charge["component"] for charge in record["charges"]})

        for date, expected_modes in EXPECTED.items():
            for mode, expected_amounts in expected_modes.items():
                selected = select_price_record(
                    self.normalized,
                    processing_mode=mode,
                    prompt_tokens=0,
                    at=date,
                )
                self.assertEqual(selected["selectionStatus"], "available")
                amounts = {charge["component"]: charge["amount"] for charge in selected["charges"]}
                self.assertEqual(
                    (amounts["input"], amounts["cached_input"], amounts["output"]),
                    expected_amounts,
                )
                self.assertEqual(
                    Decimal(amounts["cached_input"]) / Decimal(amounts["input"]),
                    Decimal("0.05"),
                )

    def test_generated_v1_v2_pages_and_huggingface_candidates(self) -> None:
        for path in ("data/prices.json", "api/v1/prices.json"):
            payload = read_json(path)
            exactly_one(
                payload["models"],
                lambda row: row["provider_id"] == "google-gemini" and row["model_id"] == MODEL_ID,
                f"{path} Gemini 4 Argon",
            )
        self.assertEqual(
            read_json("api/v1/models/google-gemini/gemini-4-argon.json"),
            self.model,
        )

        prices = [
            row for row in read_json("data/pricing-v2-preview/prices.json")
            if row["modelInternalId"] == INTERNAL_ID
        ]
        self.assertEqual(len(prices), 8)
        projection = exactly_one(
            read_json("data/pricing-v2-preview/generated/model-pricing.v2.json")["models"],
            lambda row: row["canonicalInternalId"] == INTERNAL_ID,
            "Pricing V2 Gemini 4 Argon",
        )
        self.assertTrue(projection["defaultSafe"])
        self.assertEqual(
            projection["selectedPriceRecordId"],
            f"price:{INTERNAL_ID}:standard:short:current:introductory_2026",
        )
        self.assertEqual(len(projection["priceRecords"]), 8)
        self.assertEqual(len(projection["pricingComponents"]), 24)

        hf = exactly_one(
            read_json("huggingface/prices.json")["records"],
            lambda row: row["provider_id"] == "google-gemini" and row["model_id"] == MODEL_ID,
            "Hugging Face Gemini 4 Argon",
        )
        self.assertEqual(hf["input_price_per_1m_tokens"], 2)
        self.assertEqual(hf["cached_input_price_per_1m_tokens"], 0.1)
        self.assertEqual(hf["output_price_per_1m_tokens"], 10)
        self.assertEqual(len(hf["pricing_components"]), 24)

    def test_website_projection_switches_on_exact_effective_date(self) -> None:
        website_root = Path(os.environ["WEBSITE_SOURCE_ROOT"])
        expected = {
            "2026-11-30T23:59:59Z": ("current:introductory_2026", 2, 0.1, 10),
            "2026-12-01T00:00:00Z": ("future:standard_2026_12", 4, 0.2, 20),
        }
        for effective_at, (id_suffix, input_price, cached_price, output_price) in expected.items():
            artifact, _ = build_projection(
                effective_at,
                website_dataset=website_root / "data/model-pricing.json",
                generated_at_value=effective_at,
                existing_artifact=None,
            )
            row = exactly_one(
                artifact["models"],
                lambda candidate: candidate["canonicalInternalId"] == INTERNAL_ID,
                f"Gemini 4 Argon projection at {effective_at}",
            )
            self.assertTrue(row["selectedPriceRecordId"].endswith(id_suffix))
            self.assertEqual(row["inputPrice"], input_price)
            self.assertEqual(row["cachedInputPrice"], cached_price)
            self.assertEqual(row["outputPrice"], output_price)


if __name__ == "__main__":
    unittest.main()
