from __future__ import annotations

import json
import unittest
from decimal import Decimal
from pathlib import Path

from scripts.generate_price_change_events import load_events
from scripts.pricing_contract import (
    normalize_canonical_price_records,
    project_v1_compatibility,
    select_price_record,
    validate_model_price_records,
)


ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "gpt-6.1-sol"
INTERNAL_ID = f"openai/{MODEL_ID}"
OLD_MODEL_ID = "gpt-6-sol"
THRESHOLD = 272_000
EXPECTED_MATRIX = {
    ("standard", "short"): ("2", "0.1", "2.5", "10"),
    ("standard", "long"): ("4", "0.2", "5", "15"),
    ("batch", "short"): ("1", "0.05", "1.25", "5"),
    ("batch", "long"): ("2", "0.1", "2.5", "7.5"),
    ("flex", "short"): ("1", "0.05", "1.25", "5"),
    ("flex", "long"): ("2", "0.1", "2.5", "7.5"),
    ("fast", "short"): ("4", "0.2", "5", "20"),
    ("fast", "long"): ("8", "0.4", "10", "30"),
}
COMPONENTS = ("input", "cached_input", "cache_write", "output")


def read_json(relative_path: str):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def exactly_one(rows, predicate, label: str):
    matches = [row for row in rows if predicate(row)]
    if len(matches) != 1:
        raise AssertionError(f"{label} must appear exactly once, found {len(matches)}")
    return matches[0]


def amounts(record):
    return {charge["component"]: Decimal(str(charge["amount"])) for charge in record["charges"]}


class Gpt61SolProductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.canonical_models = read_json("data/canonical/models.json")
        cls.model = exactly_one(
            cls.canonical_models,
            lambda row: row["provider_id"] == "openai" and row["model_id"] == MODEL_ID,
            "canonical GPT-6.1 Sol",
        )
        cls.old_model = exactly_one(
            cls.canonical_models,
            lambda row: row["provider_id"] == "openai" and row["model_id"] == OLD_MODEL_ID,
            "canonical GPT-6 Sol",
        )
        validate_model_price_records(cls.model)
        cls.records = cls.model["price_records"]
        cls.normalized = normalize_canonical_price_records(INTERNAL_ID, cls.records, lambda url: url)

    def test_identity_lifecycle_sources_and_v1_projection(self) -> None:
        self.assertEqual(self.model["display_name"], "GPT-6.1 Sol")
        self.assertEqual(self.model["model_family"], "GPT-6")
        self.assertEqual(self.model["status"], "active")
        self.assertEqual(self.model["release_stage"], "stable")
        self.assertEqual(self.model["context_window_tokens"], 1_050_000)
        self.assertEqual(self.model["effective_from"], "2026-09-29")
        self.assertIn("128,000 max output tokens", self.model["notes"])
        self.assertEqual(
            self.model["official_source_url"],
            "https://developers.openai.com/api/docs/models/gpt-6.1-sol",
        )
        self.assertIn("https://developers.openai.com/api/docs/pricing", self.model["official_source_urls"])
        self.assertIn("https://developers.openai.com/api/docs/changelog", self.model["official_source_urls"])
        projected = project_v1_compatibility(self.records)
        projected.pop("batch_cached_input")
        expected = dict(self.model["pricing"])
        expected.pop("batch_cached_input")
        self.assertEqual(projected, expected)

    def test_exact_processing_context_matrix_and_tab_trap_prices(self) -> None:
        self.assertEqual(len(self.records), 8)
        self.assertEqual(
            {(row["processing_mode"], row["context_class"]) for row in self.records},
            set(EXPECTED_MATRIX),
        )
        self.assertEqual(sum(row["calculation_default"] for row in self.records), 1)
        charge_ids = [charge["id"] for row in self.records for charge in row["charges"]]
        self.assertEqual(len(charge_ids), 32)
        self.assertEqual(len(charge_ids), len(set(charge_ids)))
        for row in self.records:
            key = (row["processing_mode"], row["context_class"])
            actual = {charge["component"]: str(charge["amount"]) for charge in row["charges"]}
            self.assertEqual(tuple(actual[name] for name in COMPONENTS), EXPECTED_MATRIX[key])
        self.assertEqual(EXPECTED_MATRIX[("standard", "short")], ("2", "0.1", "2.5", "10"))
        self.assertEqual(EXPECTED_MATRIX[("batch", "short")], ("1", "0.05", "1.25", "5"))
        self.assertEqual(EXPECTED_MATRIX[("flex", "short")], ("1", "0.05", "1.25", "5"))
        self.assertEqual(EXPECTED_MATRIX[("fast", "short")], ("4", "0.2", "5", "20"))

    def test_threshold_contract_and_boundaries(self) -> None:
        for row in self.records:
            self.assertEqual(row["prompt_token_threshold"], THRESHOLD)
            self.assertNotEqual(row["prompt_token_threshold"], 200_000)
            expected_comparison = "less_than_or_equal" if row["context_class"] == "short" else "greater_than"
            self.assertEqual(row["tier_selection"]["comparison"], expected_comparison)
            self.assertEqual(row["tier_selection"]["token_basis"], "input_tokens")
            self.assertTrue(row["tier_selection"]["cached_prompt_tokens_included"])
            self.assertTrue(row["tier_selection"]["whole_request_pricing"])
        for mode in ("standard", "batch", "flex", "fast"):
            for token_count, expected_context in ((THRESHOLD, "short"), (THRESHOLD + 1, "long")):
                selected = select_price_record(
                    self.normalized,
                    processing_mode=mode,
                    prompt_tokens=token_count,
                    at="2026-09-30",
                )
                self.assertEqual(selected["selectionStatus"], "available")
                self.assertEqual(selected["contextClass"], expected_context)

    def test_mode_and_long_context_ratios(self) -> None:
        indexed = {(row["processing_mode"], row["context_class"]): amounts(row) for row in self.records}
        for context in ("short", "long"):
            standard = indexed[("standard", context)]
            for mode in ("batch", "flex"):
                self.assertEqual(indexed[(mode, context)], {key: value * Decimal("0.5") for key, value in standard.items()})
            self.assertEqual(indexed[("fast", context)], {key: value * Decimal("2") for key, value in standard.items()})
        for mode in ("standard", "batch", "flex", "fast"):
            short = indexed[(mode, "short")]
            long = indexed[(mode, "long")]
            for component in ("input", "cached_input", "cache_write"):
                self.assertEqual(long[component], short[component] * Decimal("2"))
            self.assertEqual(long["output"], short["output"] * Decimal("1.5"))

    def test_regional_uplift_and_eu_mode_availability(self) -> None:
        for row in self.records:
            adjustments = row["region_policy"]["price_adjustments"]
            self.assertEqual(len(adjustments), 1)
            self.assertEqual(adjustments[0]["factor"], "1.10")
            rules = row["region_policy"]["availability"]["rules"]
            if row["processing_mode"] == "fast":
                self.assertEqual(len(rules), 1)
                self.assertEqual(rules[0]["status"], "unavailable")
                self.assertEqual(rules[0]["selector"]["data_residencies"], ["eu"])
            else:
                self.assertEqual(rules, [])
        for mode in ("standard", "batch", "flex"):
            selected = select_price_record(
                self.normalized,
                processing_mode=mode,
                prompt_tokens=THRESHOLD,
                endpoint_geography="regional",
                data_residency="eu",
                at="2026-09-30",
            )
            self.assertEqual(selected["selectionStatus"], "available")
        unavailable = select_price_record(
            self.normalized,
            processing_mode="fast",
            prompt_tokens=THRESHOLD,
            endpoint_geography="regional",
            data_residency="eu",
            at="2026-09-30",
        )
        self.assertEqual(unavailable["selectionStatus"], "unavailable")

    def test_old_gpt_6_sol_is_unchanged_and_keeps_ten_percent_cache_rate(self) -> None:
        old_standard_short = exactly_one(
            self.old_model["price_records"],
            lambda row: row["processing_mode"] == "standard" and row["context_class"] == "short",
            "old GPT-6 Sol Standard short record",
        )
        self.assertEqual(amounts(old_standard_short)["cached_input"], Decimal("0.2"))
        new_standard_short = exactly_one(
            self.records,
            lambda row: row["processing_mode"] == "standard" and row["context_class"] == "short",
            "new GPT-6.1 Sol Standard short record",
        )
        self.assertEqual(amounts(new_standard_short)["cached_input"], Decimal("0.1"))
        self.assertNotIn("lifecycle", self.old_model)
        self.assertEqual(self.old_model["status"], "active")

    def test_snapshots_and_price_change_event(self) -> None:
        before_models = read_json("data/snapshots/2026-09-29/prices.json")["models"]
        after_models = read_json("data/snapshots/2026-09-30/prices.json")["models"]
        self.assertFalse(any(row["provider_id"] == "openai" and row["model_id"] == MODEL_ID for row in before_models))
        exactly_one(after_models, lambda row: row["provider_id"] == "openai" and row["model_id"] == MODEL_ID, "after snapshot GPT-6.1 Sol")
        old_before = exactly_one(before_models, lambda row: row["provider_id"] == "openai" and row["model_id"] == OLD_MODEL_ID, "before snapshot GPT-6 Sol")
        old_after = exactly_one(after_models, lambda row: row["provider_id"] == "openai" and row["model_id"] == OLD_MODEL_ID, "after snapshot GPT-6 Sol")
        self.assertEqual(old_before, old_after)

        events = load_events(ROOT / "data/price-change-events/events.jsonl")
        event = exactly_one(
            events,
            lambda row: row["provider_id"] == "openai" and row["model_id"] == MODEL_ID and row["change_type"] == "model_added",
            "GPT-6.1 Sol model_added event",
        )
        self.assertEqual(event["effective_from"], "2026-09-29")
        self.assertEqual(event["source_snapshot_before"], "data/snapshots/2026-09-29/prices.json")
        self.assertEqual(event["source_snapshot_after"], "data/snapshots/2026-09-30/prices.json")
        self.assertFalse(any(row["model_id"] == MODEL_ID and row["change_type"] == "successor_transition" for row in events))
        self.assertFalse(
            any(
                row["model_id"] == OLD_MODEL_ID
                and row["change_type"] in {"price_update", "component_price_update", "lifecycle_update"}
                for row in events
            )
        )

    def test_generated_v2_public_api_website_and_hf_contract(self) -> None:
        v2_prices = [row for row in read_json("data/pricing-v2-preview/prices.json") if row["modelInternalId"] == INTERNAL_ID]
        self.assertEqual(len(v2_prices), 8)
        self.assertEqual(sum(len(row["charges"]) for row in v2_prices), 32)
        identity = exactly_one(
            read_json("data/pricing-v2-preview/model-identity-registry.json"),
            lambda row: row["internalId"] == INTERNAL_ID,
            "Pricing V2 GPT-6.1 Sol identity",
        )
        self.assertEqual(identity["identityType"], "canonical_model")

        for path in ("data/prices.json", "api/v1/prices.json"):
            exactly_one(
                read_json(path)["models"],
                lambda row: row["provider_id"] == "openai" and row["model_id"] == MODEL_ID,
                f"{path} GPT-6.1 Sol",
            )
        self.assertEqual(read_json("api/v1/models/openai/gpt-6.1-sol.json"), self.model)

        website = exactly_one(
            read_json("data/pricing-v2-preview/generated/model-pricing.v2.json")["models"],
            lambda row: row["canonicalInternalId"] == INTERNAL_ID,
            "Website projection GPT-6.1 Sol",
        )
        self.assertTrue(website["defaultSafe"])
        self.assertEqual(website["inputPrice"], 2)
        self.assertEqual(website["cachedInputPrice"], 0.1)
        self.assertEqual(website["outputPrice"], 10)
        self.assertEqual(len(website["pricingComponents"]), 32)
        modes = {component["condition"]["processingMode"] for component in website["pricingComponents"]}
        contexts = {component["condition"]["contextClass"] for component in website["pricingComponents"]}
        components = {component["component"] for component in website["pricingComponents"]}
        self.assertEqual(modes, {"standard", "batch", "flex", "fast"})
        self.assertEqual(contexts, {"short", "long"})
        self.assertEqual(components, set(COMPONENTS))

        hf = exactly_one(
            read_json("huggingface/prices.json")["records"],
            lambda row: row["provider_id"] == "openai" and row["model_id"] == MODEL_ID,
            "Hugging Face GPT-6.1 Sol",
        )
        self.assertEqual(hf["input_price_per_1m_tokens"], 2)
        self.assertEqual(hf["cached_input_price_per_1m_tokens"], 0.1)
        self.assertEqual(hf["output_price_per_1m_tokens"], 10)
        self.assertEqual(len(hf["pricing_components"]), 32)


if __name__ == "__main__":
    unittest.main()
