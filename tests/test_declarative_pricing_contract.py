from __future__ import annotations

import json
import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from scripts.export_huggingface import public_pricing_components
from scripts.generate_pricing_v2_preview import build_declarative_price_records, public_source_urls
from scripts.generate_website_projection_v2 import (
    build_canonical_pricing_tiers,
    project_pricing_component,
)
from scripts.pricing_contract import (
    PricingContractError,
    normalize_canonical_price_records,
    project_v1_compatibility,
    select_price_record,
    validate_canonical_price_records,
    validate_model_price_records,
    validate_normalized_region_contract,
)


ROOT = Path(__file__).resolve().parents[1]
PRICING_URL = "https://developers.openai.com/api/docs/pricing"
REGION_URL = "https://developers.openai.com/api/docs/guides/your-data"
FAST_URL = "https://developers.openai.com/api/docs/guides/fast-mode"
THRESHOLD = 272_000

ASTRA_LIKE_PRICES = {
    ("standard", "short"): ("10", "1", "12.5", "50"),
    ("standard", "long"): ("20", "2", "25", "75"),
    ("batch", "short"): ("5", "0.5", "6.25", "25"),
    ("batch", "long"): ("10", "1", "12.5", "37.5"),
    ("flex", "short"): ("5", "0.5", "6.25", "25"),
    ("flex", "long"): ("10", "1", "12.5", "37.5"),
    ("fast", "short"): ("20", "2", "25", "100"),
    ("fast", "long"): ("40", "4", "50", "150"),
}


def astra_like_records() -> list[dict]:
    """Architecture-only fixture; this is deliberately not production canonical data."""

    records = []
    for (mode, context), values in ASTRA_LIKE_PRICES.items():
        record_id = f"fixture:complex-model:{mode}:{context}:current"
        availability_rules = []
        if mode == "fast":
            availability_rules.append(
                {
                    "id": "fast-eu-residency-exclusion",
                    "selector": {"data_residencies": ["eu"]},
                    "status": "unavailable",
                    "reason": "Fixture Fast processing is unavailable with EU data residency.",
                    "source_refs": [FAST_URL],
                }
            )
        records.append(
            {
                "id": record_id,
                "processing_mode": mode,
                "context_class": context,
                "pricing_status": "current",
                "calculation_default": mode == "standard" and context == "short",
                "prompt_token_threshold": THRESHOLD,
                "tier_selection": {
                    "comparison": "less_than_or_equal" if context == "short" else "greater_than",
                    "token_basis": "total_prompt_tokens",
                    "cached_prompt_tokens_included": True,
                    "whole_request_pricing": True,
                },
                "effective_from": "2026-09-03",
                "effective_until": None,
                "currency": "USD",
                "charges": [
                    {
                        "id": f"{record_id}:{component}:text:per_1m_tokens",
                        "component": component,
                        "modality": "text",
                        "unit": "per_1m_tokens",
                        "amount": amount,
                    }
                    for component, amount in zip(
                        ("input", "cached_input", "cache_write", "output"),
                        values,
                        strict=True,
                    )
                ],
                "region_policy": {
                    "pricing_geography": "global_base",
                    "endpoint_geographies": ["global", "regional"],
                    "data_residencies": ["global", "us", "eu"],
                    "availability": {
                        "default": "available",
                        "rules": availability_rules,
                    },
                    "price_adjustments": [
                        {
                            "id": "regional-endpoint-uplift",
                            "selector": {"endpoint_geographies": ["regional"]},
                            "operation": "multiply",
                            "factor": "1.10",
                            "source_refs": [REGION_URL],
                        }
                    ],
                },
                "source_refs": [PRICING_URL],
                "verification_status": "verified",
                "checked_at": "2026-09-04T00:00:00Z",
                "verified_at": "2026-09-04T00:00:00Z",
                "billing_note": "Architecture-only complex pricing fixture.",
            }
        )
    return records


def astra_like_model() -> dict:
    records = astra_like_records()
    return {
        "provider_id": "fixture-provider",
        "model_id": "complex-model",
        "display_name": "Complex Model Fixture",
        "model_family": "Fixture",
        "status": "active",
        "pricing": project_v1_compatibility(records),
        "price_records": records,
        "official_source_url": PRICING_URL,
        "official_source_urls": [PRICING_URL, REGION_URL, FAST_URL],
        "accessed_at": "2026-09-04T00:00:00Z",
        "last_verified_at": "2026-09-04T00:00:00Z",
        "effective_from": "2026-09-03",
        "notes": "Test fixture only.",
    }


def generic_records() -> list[dict]:
    return [
        {
            "id": "fixture:provider-x/model-x:standard:short:current",
            "processing_mode": "standard",
            "context_class": "short",
            "pricing_status": "current",
            "calculation_default": True,
            "prompt_token_threshold": None,
            "effective_from": "2026-01-01",
            "effective_until": None,
            "currency": "USD",
            "charges": [
                {
                    "id": "fixture:provider-x/model-x:standard:short:current:request",
                    "component": "request",
                    "modality": "text",
                    "unit": "per_request",
                    "amount": "0.003",
                }
            ],
            "region_policy": {
                "pricing_geography": "global_base",
                "endpoint_geographies": ["global"],
                "data_residencies": ["global"],
                "availability": {"default": "available", "rules": []},
                "price_adjustments": [],
            },
            "source_refs": ["https://provider-x.example/pricing"],
            "verification_status": "verified",
            "checked_at": "2026-01-02T00:00:00Z",
            "verified_at": "2026-01-02T00:00:00Z",
            "billing_note": "Generic per-request fixture.",
        }
    ]


def canonical_from_v2(records: list[dict]) -> list[dict]:
    converted = []
    for record in records:
        item = {
            "id": record["pricingId"],
            "processing_mode": record["processingMode"],
            "context_class": record["contextClass"],
            "pricing_status": record.get("pricingStatus", "current"),
            "calculation_default": record["calculationDefault"],
            "prompt_token_threshold": record["promptTokenThreshold"],
            "effective_from": record["effectiveFrom"],
            "effective_until": record["effectiveUntil"],
            "currency": record["currency"],
            "charges": [
                {
                    "id": charge["chargeId"],
                    "component": charge["component"],
                    "modality": charge["modality"],
                    "unit": charge["unit"],
                    "amount": charge["amount"],
                }
                for charge in record["charges"]
            ],
            "region_policy": {
                "pricing_geography": "global_base",
                "endpoint_geographies": ["global"],
                "data_residencies": ["global"],
                "availability": {"default": "available", "rules": []},
                "price_adjustments": [],
            },
            "source_refs": record["sourceRefs"],
            "verification_status": record["verificationStatus"],
            "checked_at": "2026-09-04T00:00:00Z",
            "verified_at": "2026-09-04T00:00:00Z",
            "billing_note": record["billingNote"],
        }
        if record.get("tierSelection"):
            tier = record["tierSelection"]
            item["tier_selection"] = {
                "comparison": tier["comparison"],
                "token_basis": tier["tokenBasis"],
                "cached_prompt_tokens_included": tier["cachedPromptTokensIncluded"],
                "whole_request_pricing": tier["wholeRequestPricing"],
            }
        converted.append(item)
    return converted


class DeclarativePricingContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.records = astra_like_records()
        self.normalized = normalize_canonical_price_records(
            "fixture-provider/complex-model",
            self.records,
            lambda url: f"source:{url.rsplit('/', 1)[-1]}",
        )

    def test_astra_like_fixture_is_declared_by_schema_and_validates_contract(self) -> None:
        schema = json.loads((ROOT / "schema" / "model.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["price_records"]["items"]["$ref"], "#/$defs/canonicalPriceRecord")
        record_schema = schema["$defs"]["canonicalPriceRecord"]
        self.assertFalse(record_schema["additionalProperties"])
        self.assertTrue(
            {
                "processing_mode",
                "context_class",
                "charges",
                "tier_selection",
                "region_policy",
                "source_refs",
                "checked_at",
                "verified_at",
            }
            <= set(record_schema["properties"])
        )
        v2_schema = json.loads(
            (ROOT / "schema" / "pricing-v2-preview.schema.json").read_text(encoding="utf-8")
        )
        v2_record_properties = v2_schema["$defs"]["priceRecord"]["properties"]
        self.assertTrue(
            {
                "regionSelector",
                "defaultAvailabilityStatus",
                "availabilityRules",
                "priceAdjustments",
                "checkedAt",
                "verifiedAt",
            }
            <= set(v2_record_properties)
        )
        validate_model_price_records(astra_like_model())
        model = astra_like_model()
        source_map = {url: f"source:{index}" for index, url in enumerate(public_source_urls(model))}
        generated = build_declarative_price_records(
            "fixture-provider/complex-model",
            model,
            {"id": "website-fixture-id"},
            source_map,
        )
        self.assertEqual(generated, [
            {**record, "sourceDatasetIds": {"publicDatasetIds": ["complex-model"], "websiteIds": ["website-fixture-id"]}}
            for record in normalize_canonical_price_records(
                "fixture-provider/complex-model",
                model["price_records"],
                source_map,
            )
        ])
        self.assertEqual(len(self.normalized), 8)
        self.assertEqual(sum(len(record["charges"]) for record in self.normalized), 32)
        self.assertEqual(
            {(record["processingMode"], record["contextClass"]) for record in self.normalized},
            set(ASTRA_LIKE_PRICES),
        )

    def test_threshold_boundaries_and_whole_request_selection_for_every_mode(self) -> None:
        for mode in ("standard", "batch", "flex", "fast"):
            with self.subTest(mode=mode, prompt_tokens=THRESHOLD - 1):
                selected = select_price_record(
                    self.normalized,
                    processing_mode=mode,
                    prompt_tokens=THRESHOLD - 1,
                    at="2026-09-05",
                )
                self.assertEqual(selected["contextClass"], "short")
            with self.subTest(mode=mode, prompt_tokens=THRESHOLD):
                selected = select_price_record(
                    self.normalized,
                    processing_mode=mode,
                    prompt_tokens=THRESHOLD,
                    at="2026-09-05",
                )
                self.assertEqual(selected["contextClass"], "short")
            with self.subTest(mode=mode, prompt_tokens=THRESHOLD + 1):
                selected = select_price_record(
                    self.normalized,
                    processing_mode=mode,
                    prompt_tokens=THRESHOLD + 1,
                    at="2026-09-05",
                )
                self.assertEqual(selected["contextClass"], "long")
                actual = {charge["component"]: charge["amount"] for charge in selected["charges"]}
                expected = dict(zip(("input", "cached_input", "cache_write", "output"), ASTRA_LIKE_PRICES[(mode, "long")], strict=True))
                self.assertEqual(actual, expected)

    def test_region_adjustment_is_decimal_and_availability_is_not_a_price(self) -> None:
        global_record = select_price_record(
            self.normalized,
            processing_mode="standard",
            prompt_tokens=1,
            at="2026-09-05",
        )
        regional_record = select_price_record(
            self.normalized,
            processing_mode="standard",
            prompt_tokens=1,
            endpoint_geography="regional",
            at="2026-09-05",
        )
        global_amounts = {charge["component"]: Decimal(charge["amount"]) for charge in global_record["charges"]}
        regional_amounts = {charge["component"]: Decimal(charge["amount"]) for charge in regional_record["charges"]}
        self.assertTrue(all(regional_amounts[key] == value * Decimal("1.10") for key, value in global_amounts.items()))
        self.assertEqual(regional_record["appliedPriceAdjustmentIds"], ["regional-endpoint-uplift"])

        unavailable = select_price_record(
            self.normalized,
            processing_mode="fast",
            prompt_tokens=1,
            data_residency="eu",
            at="2026-09-05",
        )
        self.assertEqual(unavailable["selectionStatus"], "unavailable")
        self.assertNotIn("charges", unavailable)
        self.assertNotEqual(unavailable.get("requestedProcessingMode"), "standard")

    def test_record_level_provenance_and_v1_projection(self) -> None:
        first = self.normalized[0]
        self.assertEqual(first["checkedAt"], "2026-09-04T00:00:00Z")
        self.assertEqual(first["verifiedAt"], "2026-09-04T00:00:00Z")
        self.assertEqual(first["verificationStatus"], "verified")
        self.assertTrue(first["sourceRefs"])
        self.assertEqual(
            project_v1_compatibility(self.records),
            {
                "currency": "USD",
                "unit": "1M tokens",
                "input": 10,
                "output": 50,
                "cached_input": 1,
                "cache_write": 12.5,
                "cache_write_1h": None,
                "batch_input": 5,
                "batch_cached_input": 0.5,
                "batch_output": 25,
            },
        )

    def test_website_and_hf_component_projection_preserve_region_contract(self) -> None:
        fast = next(
            record
            for record in self.normalized
            if record["processingMode"] == "fast" and record["contextClass"] == "short"
        )
        component = project_pricing_component(fast, fast["charges"][0])
        condition = component["condition"]
        self.assertEqual(condition["regionSelector"]["pricingGeography"], "global_base")
        self.assertEqual(condition["defaultAvailabilityStatus"], "available")
        self.assertEqual(condition["availabilityRules"][0]["availabilityStatus"], "unavailable")
        self.assertEqual(condition["priceAdjustments"][0]["factor"], "1.1")

        source_ref = component["sourceRefs"][0]
        public = public_pricing_components(
            {
                "provider": "Fixture Provider",
                "id": "complex-model",
                "sourceRefs": [source_ref],
                "sourceUrls": [PRICING_URL],
                "pricingComponents": [component],
            }
        )[0]
        public_condition = public["condition"]
        self.assertEqual(public_condition["region_selector"], condition["regionSelector"])
        self.assertEqual(public_condition["default_availability_status"], "available")
        self.assertEqual(public_condition["availability_rules"], condition["availabilityRules"])
        self.assertEqual(public_condition["price_adjustments"], condition["priceAdjustments"])

    def test_generic_provider_fixture_has_no_provider_or_family_dependency(self) -> None:
        records = generic_records()
        validate_canonical_price_records(records)
        normalized = normalize_canonical_price_records("provider-x/model-x", records, lambda value: value)
        selected = select_price_record(
            normalized,
            processing_mode="standard",
            prompt_tokens=123,
            at="2026-02-01",
        )
        self.assertEqual(selected["selectionStatus"], "available")
        self.assertEqual(selected["modelInternalId"], "provider-x/model-x")
        self.assertEqual(selected["charges"][0]["amount"], "0.003")

    def test_existing_gpt56_terra_new_path_matches_legacy_semantics(self) -> None:
        legacy = [
            record
            for record in json.loads((ROOT / "data" / "pricing-v2-preview" / "prices.json").read_text(encoding="utf-8"))
            if record["modelInternalId"] == "openai/gpt-5.6-terra"
        ]
        canonical = canonical_from_v2(legacy)
        normalized = normalize_canonical_price_records("openai/gpt-5.6-terra", canonical, lambda value: value)
        semantic_fields = (
            "pricingId",
            "modelInternalId",
            "processingMode",
            "pricingStatus",
            "contextClass",
            "promptTokenThreshold",
            "tierSelection",
            "effectiveFrom",
            "effectiveUntil",
            "currency",
            "charges",
            "sourceRefs",
            "billingNote",
            "verificationStatus",
            "calculationDefault",
        )
        self.assertEqual(
            [{field: record.get(field) for field in semantic_fields} for record in normalized],
            [{field: record.get(field) for field in semantic_fields} for record in legacy],
        )
        for mode in ("standard", "batch", "flex", "fast"):
            for prompt_tokens in (THRESHOLD, THRESHOLD + 1):
                selected = select_price_record(
                    normalized,
                    processing_mode=mode,
                    prompt_tokens=prompt_tokens,
                    at="2026-09-05",
                )
                expected_context = "short" if prompt_tokens == THRESHOLD else "long"
                expected = next(
                    record for record in legacy
                    if record["processingMode"] == mode and record["contextClass"] == expected_context
                )
                self.assertEqual(selected["pricingId"], expected["pricingId"])
                self.assertEqual(selected["charges"], expected["charges"])

        canonical_model = next(
            model
            for model in json.loads((ROOT / "data" / "canonical" / "models.json").read_text(encoding="utf-8"))
            if model["provider_id"] == "openai" and model["model_id"] == "gpt-5.6-terra"
        )
        projection = project_v1_compatibility(canonical)
        projection.pop("batch_cached_input")
        self.assertEqual(projection, canonical_model["pricing"])
        self.assertEqual(build_canonical_pricing_tiers(normalized), build_canonical_pricing_tiers(legacy))

    def test_validation_rejects_required_failure_modes(self) -> None:
        cases = {}

        duplicate_record = deepcopy(self.records)
        duplicate_record[1]["id"] = duplicate_record[0]["id"]
        cases["duplicate pricing IDs"] = duplicate_record

        duplicate_charge = deepcopy(self.records)
        duplicate_charge[1]["charges"][0]["id"] = duplicate_charge[0]["charges"][0]["id"]
        cases["duplicate charge IDs"] = duplicate_charge

        invalid_mode = deepcopy(self.records)
        invalid_mode[0]["processing_mode"] = "turbo"
        cases["invalid processing mode"] = invalid_mode

        invalid_context = deepcopy(self.records)
        invalid_context[0]["context_class"] = "huge"
        cases["invalid context class"] = invalid_context

        invalid_threshold = deepcopy(self.records)
        invalid_threshold[0]["prompt_token_threshold"] = -1
        cases["invalid threshold"] = invalid_threshold

        overlap = deepcopy(self.records)
        extra = deepcopy(overlap[0])
        extra["id"] += ":overlap"
        for charge in extra["charges"]:
            charge["id"] += ":overlap"
        overlap.append(extra)
        cases["overlapping records"] = overlap

        ambiguous_default = deepcopy(self.records)
        ambiguous_default[1]["calculation_default"] = True
        cases["ambiguous defaults"] = ambiguous_default

        invalid_selector = deepcopy(self.records)
        invalid_selector[0]["region_policy"]["endpoint_geographies"] = ["Regional"]
        cases["invalid region selector"] = invalid_selector

        contradictory = deepcopy(self.records)
        contradictory[-2]["region_policy"]["availability"]["rules"].append(
            {
                "id": "fast-eu-enabled",
                "selector": {"data_residencies": ["eu"]},
                "status": "available",
                "reason": "Contradictory test rule.",
                "source_refs": [FAST_URL],
            }
        )
        cases["contradictory availability"] = contradictory

        zero_adjustment = deepcopy(self.records)
        zero_adjustment[0]["region_policy"]["price_adjustments"][0]["factor"] = "0"
        cases["non-positive adjustment"] = zero_adjustment

        missing_refs = deepcopy(self.records)
        missing_refs[0]["source_refs"] = []
        cases["missing source refs"] = missing_refs

        unverified = deepcopy(self.records)
        unverified[0]["verification_status"] = "review_required"
        cases["unverified production record"] = unverified

        for label, records in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(PricingContractError):
                    validate_canonical_price_records(records)

    def test_model_validation_rejects_unknown_source_and_v1_mismatch(self) -> None:
        model = astra_like_model()
        model["price_records"][0]["source_refs"] = ["https://unknown.example/pricing"]
        with self.assertRaisesRegex(PricingContractError, "official_source_urls"):
            validate_model_price_records(model)

        model = astra_like_model()
        model["pricing"]["input"] = 999
        with self.assertRaisesRegex(PricingContractError, "lossy V1 projection"):
            validate_model_price_records(model)

        model = astra_like_model()
        model["pricing_tiers"] = [{"legacy": True}]
        with self.assertRaisesRegex(PricingContractError, "cannot coexist"):
            validate_model_price_records(model)

    def test_v2_region_validator_rejects_invalid_normalized_contract(self) -> None:
        record = deepcopy(self.normalized[0])
        known_refs = set(record["sourceRefs"])
        known_refs.update(record["availabilityRules"][0]["sourceRefs"] if record["availabilityRules"] else [])
        known_refs.update(record["priceAdjustments"][0]["sourceRefs"])
        validate_normalized_region_contract(record, known_source_refs=known_refs)

        record["priceAdjustments"][0]["factor"] = "0"
        with self.assertRaises(PricingContractError):
            validate_normalized_region_contract(record, known_source_refs=known_refs)


if __name__ == "__main__":
    unittest.main()
