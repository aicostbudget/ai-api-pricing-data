from __future__ import annotations

import json
import unittest
from decimal import Decimal
from pathlib import Path

from scripts.pricing_contract import (
    normalize_canonical_price_records,
    project_v1_compatibility,
    select_price_record,
    validate_model_price_records,
)


ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "gpt-6-astra"
INTERNAL_ID = f"openai/{MODEL_ID}"
THRESHOLD = 272_000
EXPECTED_MATRIX = {
    ("standard", "short"): ("10", "1", "12.5", "50"),
    ("standard", "long"): ("20", "2", "25", "75"),
    ("batch", "short"): ("5", "0.5", "6.25", "25"),
    ("batch", "long"): ("10", "1", "12.5", "37.5"),
    ("flex", "short"): ("5", "0.5", "6.25", "25"),
    ("flex", "long"): ("10", "1", "12.5", "37.5"),
    ("fast", "short"): ("20", "2", "25", "100"),
    ("fast", "long"): ("40", "4", "50", "150"),
}
COMPONENTS = ("input", "cached_input", "cache_write", "output")


def read_json(relative_path: str):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def exactly_one(rows, predicate, label: str):
    matches = [row for row in rows if predicate(row)]
    if len(matches) != 1:
        raise AssertionError(f"{label} must appear exactly once, found {len(matches)}")
    return matches[0]


class Gpt6AstraProductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = exactly_one(
            read_json("data/canonical/models.json"),
            lambda row: row["provider_id"] == "openai" and row["model_id"] == MODEL_ID,
            "canonical GPT-6 Astra",
        )
        validate_model_price_records(cls.model)
        cls.records = cls.model["price_records"]
        cls.normalized = normalize_canonical_price_records(
            INTERNAL_ID,
            cls.records,
            lambda url: url,
        )

    def test_identity_lifecycle_and_v1_projection(self) -> None:
        self.assertEqual(self.model["display_name"], "GPT-6 Astra")
        self.assertEqual(self.model["model_family"], "GPT-6")
        self.assertEqual(self.model["status"], "active")
        self.assertEqual(self.model["release_stage"], "stable")
        self.assertEqual(self.model["context_window_tokens"], 1_050_000)
        self.assertEqual(self.model["effective_from"], "2026-09-03")
        projected = project_v1_compatibility(self.records)
        projected.pop("batch_cached_input")
        self.assertEqual(projected, self.model["pricing"])

    def test_exact_eight_record_matrix_and_unique_ids(self) -> None:
        self.assertEqual(len(self.records), 8)
        self.assertEqual(
            {(row["processing_mode"], row["context_class"]) for row in self.records},
            set(EXPECTED_MATRIX),
        )
        self.assertEqual(sum(row["calculation_default"] for row in self.records), 1)
        record_ids = [row["id"] for row in self.records]
        charge_ids = [charge["id"] for row in self.records for charge in row["charges"]]
        self.assertEqual(len(record_ids), len(set(record_ids)))
        self.assertEqual(len(charge_ids), 32)
        self.assertEqual(len(charge_ids), len(set(charge_ids)))
        for row in self.records:
            key = (row["processing_mode"], row["context_class"])
            amounts = {charge["component"]: str(charge["amount"]) for charge in row["charges"]}
            self.assertEqual(tuple(amounts[name] for name in COMPONENTS), EXPECTED_MATRIX[key])
            self.assertEqual(row["prompt_token_threshold"], THRESHOLD)
            self.assertEqual(row["tier_selection"]["token_basis"], "total_prompt_tokens")
            self.assertTrue(row["tier_selection"]["cached_prompt_tokens_included"])
            self.assertTrue(row["tier_selection"]["whole_request_pricing"])

    def test_threshold_boundaries_for_every_mode(self) -> None:
        for mode in ("standard", "batch", "flex", "fast"):
            for token_count, expected_context in (
                (THRESHOLD - 1, "short"),
                (THRESHOLD, "short"),
                (THRESHOLD + 1, "long"),
            ):
                selected = select_price_record(
                    self.normalized,
                    processing_mode=mode,
                    prompt_tokens=token_count,
                    at="2026-09-04",
                )
                self.assertEqual(selected["selectionStatus"], "available")
                self.assertEqual(selected["contextClass"], expected_context)
                self.assertEqual(selected["pricingId"], f"price:{INTERNAL_ID}:{mode}:{expected_context}:current")

    def test_regional_uplift_and_fast_eu_unavailability(self) -> None:
        for (mode, context), expected in EXPECTED_MATRIX.items():
            token_count = THRESHOLD if context == "short" else THRESHOLD + 1
            selected = select_price_record(
                self.normalized,
                processing_mode=mode,
                prompt_tokens=token_count,
                endpoint_geography="regional",
                data_residency="us",
                at="2026-09-04",
            )
            self.assertEqual(selected["selectionStatus"], "available")
            actual = {charge["component"]: Decimal(charge["amount"]) for charge in selected["charges"]}
            self.assertEqual(
                tuple(actual[name] for name in COMPONENTS),
                tuple(Decimal(amount) * Decimal("1.10") for amount in expected),
            )
            self.assertEqual(selected["appliedPriceAdjustmentIds"], ["regional-data-residency-uplift"])

        for token_count in (THRESHOLD, THRESHOLD + 1):
            unavailable = select_price_record(
                self.normalized,
                processing_mode="fast",
                prompt_tokens=token_count,
                endpoint_geography="regional",
                data_residency="eu",
                at="2026-09-04",
            )
            self.assertEqual(unavailable["selectionStatus"], "unavailable")
            self.assertIn("Fast mode is unavailable", unavailable["reason"])

    def test_generated_v2_public_api_website_and_hf_parity(self) -> None:
        v2_prices = [
            row for row in read_json("data/pricing-v2-preview/prices.json")
            if row["modelInternalId"] == INTERNAL_ID
        ]
        self.assertEqual(len(v2_prices), 8)
        self.assertEqual(sum(len(row["charges"]) for row in v2_prices), 32)
        self.assertEqual(sum(row["calculationDefault"] for row in v2_prices), 1)

        for path in ("data/prices.json", "api/v1/prices.json"):
            payload = read_json(path)
            row = exactly_one(
                payload["models"],
                lambda item: item["provider_id"] == "openai" and item["model_id"] == MODEL_ID,
                f"{path} GPT-6 Astra",
            )
            self.assertEqual(row["pricing"], self.model["pricing"])
        self.assertEqual(read_json("api/v1/models/openai/gpt-6-astra.json"), self.model)

        website = exactly_one(
            read_json("data/pricing-v2-preview/generated/model-pricing.v2.json")["models"],
            lambda row: row["canonicalInternalId"] == INTERNAL_ID,
            "Website projection GPT-6 Astra",
        )
        self.assertTrue(website["defaultSafe"])
        self.assertEqual(website["selectedPriceRecordId"], f"price:{INTERNAL_ID}:standard:short:current")
        self.assertEqual(website["selectedBatchPriceRecordId"], f"price:{INTERNAL_ID}:batch:short:current")
        self.assertEqual(len(website["pricingComponents"]), 32)
        self.assertEqual(len(website["pricingTiers"]), 2)

        compatibility_preview = exactly_one(
            read_json("data/pricing-v2-preview/generated/model-pricing.website-preview.json"),
            lambda row: row.get("canonicalInternalId") == INTERNAL_ID,
            "Website compatibility preview GPT-6 Astra",
        )
        self.assertEqual(
            compatibility_preview["defaultPriceRecordId"],
            website["selectedPriceRecordId"],
        )
        compatibility_without_alias = dict(compatibility_preview)
        compatibility_without_alias.pop("defaultPriceRecordId")
        self.assertEqual(compatibility_without_alias, website)

        hf = exactly_one(
            read_json("huggingface/prices.json")["records"],
            lambda row: row["provider_id"] == "openai" and row["model_id"] == MODEL_ID,
            "Hugging Face GPT-6 Astra",
        )
        self.assertEqual(hf["input_price_per_1m_tokens"], 10)
        self.assertEqual(hf["cached_input_price_per_1m_tokens"], 1)
        self.assertEqual(hf["output_price_per_1m_tokens"], 50)
        self.assertEqual(len(hf["pricing_components"]), 32)
        self.assertEqual(hf["pricing_tier_count"], 2)


if __name__ == "__main__":
    unittest.main()
