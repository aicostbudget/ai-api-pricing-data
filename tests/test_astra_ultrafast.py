from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import unittest

from scripts.pricing_contract import (
    PricingContractError, calculate_price_record_cost, normalize_canonical_price_records,
    project_v1_compatibility, select_price_record, validate_canonical_price_records,
    validate_normalized_region_contract,
)
from scripts.export_huggingface import public_pricing_components
from scripts.generate_website_projection_v2 import project_pricing_component

ROOT = Path(__file__).resolve().parents[1]
INTERNAL_ID = "openai/gpt-6-astra"
URL = "https://developers.openai.com/api/docs/guides/ultrafast-mode"
EXPECTED = {"short": ("60", "6", "75", "300"), "long": ("120", "12", "150", "450")}
COMPONENTS = ("input", "cached_input", "cache_write", "output")


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def synthetic_ultrafast():
    model = next(x for x in read("data/canonical/models.json") if x["model_id"] == "gpt-6-astra")
    result = []
    for context in ("short", "long"):
        record = deepcopy(next(x for x in model["price_records"] if x["processing_mode"] == "standard" and x["context_class"] == context))
        record["id"] = f"price:{INTERNAL_ID}:ultrafast:{context}:current"
        record["processing_mode"] = "ultrafast"
        record["calculation_default"] = False
        record["effective_from"] = "2026-09-29"
        record["source_refs"] = [URL]
        record["region_policy"] = {
            "pricing_geography": "global_base", "endpoint_geographies": ["global", "regional"],
            "data_residencies": ["global", "us"],
            "availability": {"default": "available", "rules": []}, "price_adjustments": [],
        }
        for charge, amount in zip(record["charges"], EXPECTED[context]):
            charge["id"] = f"{record['id']}:{charge['component']}:text:per_1m_tokens"
            charge["amount"] = amount
        result.append(record)
    return result


class UltrafastContractTests(unittest.TestCase):
    def setUp(self):
        self.ultrafast = synthetic_ultrafast()
        model = next(x for x in read("data/canonical/models.json") if x["model_id"] == "gpt-6-astra")
        self.records = [x for x in model["price_records"] if x["processing_mode"] != "ultrafast"] + self.ultrafast
        self.normalized = [x for x in normalize_canonical_price_records(INTERNAL_ID, self.records, lambda url: url) if x["processingMode"] == "ultrafast"]

    def test_canonical_and_normalization_preserve_mode_and_unique_ids(self):
        validate_canonical_price_records(self.records)
        self.assertEqual({x["processingMode"] for x in self.normalized}, {"ultrafast"})
        self.assertEqual(len({x["pricingId"] for x in self.normalized}), 2)
        self.assertEqual(len({c["chargeId"] for x in self.normalized for c in x["charges"]}), 8)
        self.assertTrue(all(not x["calculationDefault"] for x in self.normalized))
        for x in self.normalized:
            validate_normalized_region_contract(x)

    def test_schemas_accept_new_mode_without_removing_old_modes(self):
        expected = {"standard", "batch", "flex", "priority", "fast", "ultrafast"}
        paths = (("schema/model.schema.json", "canonicalPriceRecord", "processing_mode"),
                 ("schema/pricing-v2-preview.schema.json", "priceRecord", "processingMode"))
        for file, definition, field in paths:
            schema = read(file)
            self.assertEqual(set(schema["$defs"][definition]["properties"][field]["enum"]), expected)
        event = read("schema/price-change-event.schema.json")
        enums = []
        def visit(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == "processing_mode": enums.append(set(child["enum"]))
                    visit(child)
            elif isinstance(value, list):
                for child in value: visit(child)
        visit(event)
        self.assertEqual(enums, [expected])

    def test_invalid_modes_are_rejected_without_fallback(self):
        bad = deepcopy(self.records)
        bad[0]["processing_mode"] = "unknown-mode"
        with self.assertRaises(PricingContractError): validate_canonical_price_records(bad)
        for mode in ("unknown-mode", "fast", "standard"):
            if mode == "unknown-mode":
                with self.assertRaises(PricingContractError):
                    select_price_record(self.normalized, processing_mode=mode, prompt_tokens=1, at="2026-10-08")
            else:
                self.assertEqual(select_price_record(self.normalized, processing_mode=mode, prompt_tokens=1, at="2026-10-08")["selectionStatus"], "unavailable")

    def test_threshold_and_full_request_cost(self):
        for tokens, context in ((272000, "short"), (272001, "long")):
            selected = select_price_record(self.normalized, processing_mode="ultrafast", prompt_tokens=tokens, at="2026-10-08")
            self.assertEqual(selected["contextClass"], context)
            self.assertTrue(selected["tierSelection"]["wholeRequestPricing"])
            self.assertEqual(tuple(c["amount"] for c in selected["charges"]), EXPECTED[context])
            canonical_selected = next(x for x in self.ultrafast if x["context_class"] == context)
            cost = calculate_price_record_cost(canonical_selected, usage_quantities={canonical_selected["charges"][0]["id"]: tokens})
            self.assertEqual(cost, Decimal(tokens) * Decimal(EXPECTED[context][0]) / Decimal(1000000))
        self.assertEqual(cost, Decimal("32.64012"))
        self.assertNotEqual(cost, Decimal("16.32012"))

    def test_region_allowlist_blocks_eu_and_other_residencies(self):
        for geography, residency, expected in (("global", "global", "available"), ("regional", "us", "available"),
                                               ("regional", "eu", "unavailable"), ("regional", "apac", "unavailable")):
            selected = select_price_record(self.normalized, processing_mode="ultrafast", prompt_tokens=272001,
                                           endpoint_geography=geography, data_residency=residency, at="2026-10-08")
            self.assertEqual(selected["selectionStatus"], expected)

    def test_existing_modes_defaults_and_saved_basis_remain_stable(self):
        model = next(x for x in read("data/canonical/models.json") if x["model_id"] == "gpt-6-astra")
        old = [x for x in model["price_records"] if x["processing_mode"] != "ultrafast"]
        extended = old + self.ultrafast
        self.assertEqual(project_v1_compatibility(extended), project_v1_compatibility(old))
        before = normalize_canonical_price_records(INTERNAL_ID, old, lambda url: url)
        after = normalize_canonical_price_records(INTERNAL_ID, extended, lambda url: url)
        for mode in ("standard", "batch", "flex", "fast"):
            for tokens in (272000, 272001):
                args = dict(processing_mode=mode, prompt_tokens=tokens, at="2026-09-04")
                a = select_price_record(before, **args)
                b = select_price_record(after, **args)
                self.assertEqual(a, b)
                fingerprint = lambda x: hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                self.assertEqual(fingerprint(a), fingerprint(b))
        # The existing explicit selector requires a mode; no new implicit fallback is introduced.
        with self.assertRaises(TypeError): select_price_record(after, prompt_tokens=1)

    def test_components_keep_mode_region_and_source_provenance(self):
        projected = [project_pricing_component(x, c) for x in self.normalized for c in x["charges"]]
        row = {"provider": "openai", "id": "gpt-6-astra", "pricingComponents": projected, "sourceRefs": [URL], "sourceUrls": [URL]}
        public = public_pricing_components(row)
        self.assertEqual(len(public), 8)
        self.assertTrue(all(c["condition"]["processing_mode"] == "ultrafast" for c in public))
        self.assertTrue(all(c["source_urls"] == [URL] for c in public))
        self.assertTrue(all(c["condition"]["region_selector"]["dataResidencies"] == ["global", "us"] for c in public))


class UltrafastIntegrationTests(unittest.TestCase):
    def test_authoritative_records_and_projections_keep_evidence_and_old_components(self):
        model = next(x for x in read("data/canonical/models.json") if x["model_id"] == "gpt-6-astra")
        self.assertEqual(len(model["price_records"]), 10)
        ultra = [x for x in model["price_records"] if x["processing_mode"] == "ultrafast"]
        self.assertEqual(len(ultra), 2)
        normalized = normalize_canonical_price_records(INTERNAL_ID, model["price_records"], lambda url: url)
        for context, rates in EXPECTED.items():
            row = next(x for x in ultra if x["context_class"] == context)
            self.assertEqual(tuple(c["amount"] for c in row["charges"]), rates)
            self.assertFalse(row["calculation_default"])
            self.assertEqual(row["effective_from"], "2026-09-29")
            self.assertEqual(row["checked_at"], row["verified_at"])
            self.assertGreater(row["verified_at"], model["last_verified_at"])
            self.assertIn(URL, row["source_refs"])
            for phrase in ('Responses API', 'service_tier="ultrafast"', '500,000 TPM', '1,000,000 TPM', '5,000,000 TPM', 'not programmatically enforced'):
                self.assertIn(phrase, row["billing_note"])
        projection = next(x for x in read("data/pricing-v2-preview/generated/model-pricing.v2.json")["models"] if x["id"] == "gpt-6-astra")
        hf = next(x for x in read("huggingface/prices.json")["records"] if x["model_id"] == "gpt-6-astra")
        self.assertEqual(len(projection["priceRecords"]), 10)
        self.assertEqual(len(hf["pricing_components"]), 40)
        self.assertEqual(len([c for c in hf["pricing_components"] if c["condition"]["processing_mode"] != "ultrafast"]), 32)
        self.assertEqual(projection["selectedPriceRecordId"], f"price:{INTERNAL_ID}:standard:short:current")
        for c in hf["pricing_components"]:
            if c["condition"]["processing_mode"] == "ultrafast":
                original = next(x for x in ultra if x["context_class"] == c["condition"]["context_class"])
                self.assertEqual(c["last_verified_at"], original["verified_at"])
                self.assertEqual(c["checked_at"], original["checked_at"])
                self.assertEqual(c["billing_note"], original["billing_note"])
                self.assertEqual(c["condition"]["region_selector"]["dataResidencies"], ["global", "us"])
        for geography, residency, status in (("global", "global", "available"), ("regional", "us", "available"),
                                           ("regional", "eu", "unavailable"), ("global", "eu", "unavailable"),
                                           ("regional", "apac", "unavailable"), ("regional", "global", "unavailable")):
            selected = select_price_record(normalized, processing_mode="ultrafast", prompt_tokens=272001,
                                           endpoint_geography=geography, data_residency=residency, at="2026-10-08")
            self.assertEqual(selected["selectionStatus"], status)


if __name__ == "__main__":
    unittest.main()
