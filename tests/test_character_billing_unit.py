import json
import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from scripts import validate_pricing_v2_preview as preview_validator
from scripts.export_huggingface import (
    PUBLIC_SCHEMA_VERSION,
    SUPPORTED_PUBLIC_SCHEMA_VERSIONS,
    non_token_summary,
)
from scripts.lib import csv_rows
from scripts.pricing_contract import (
    PricingContractError,
    UNITS,
    calculate_price_record_cost,
    validate_canonical_price_records,
)


ROOT = Path(__file__).resolve().parents[1]


def character_record(unit="per_1m_characters"):
    return {
        "id": "fixture:provider/model:standard:short:current",
        "processing_mode": "standard",
        "context_class": "short",
        "pricing_status": "current",
        "calculation_default": True,
        "prompt_token_threshold": None,
        "effective_from": "2026-10-20",
        "effective_until": None,
        "currency": "USD",
        "charges": [{
            "id": "fixture:provider/model:standard:short:current:input:text:per_1m_characters",
            "component": "input",
            "modality": "text",
            "unit": unit,
            "amount": "13",
        }],
        "region_policy": {
            "pricing_geography": "global_base",
            "endpoint_geographies": ["global"],
            "data_residencies": ["global"],
            "availability": {"default": "available", "rules": []},
            "price_adjustments": [],
        },
        "source_refs": ["https://provider.example/pricing"],
        "verification_status": "verified",
        "checked_at": "2026-10-20T00:00:00Z",
        "verified_at": "2026-10-20T00:00:00Z",
        "billing_note": "Fixture billed from input text characters.",
    }


class CharacterBillingUnitTests(unittest.TestCase):
    def test_schema_and_contract_enums_include_character_unit(self):
        model_schema = json.loads((ROOT / "schema/model.schema.json").read_text(encoding="utf-8"))
        preview_schema = json.loads((ROOT / "schema/pricing-v2-preview.schema.json").read_text(encoding="utf-8"))
        self.assertIn(
            "per_1m_characters",
            model_schema["$defs"]["canonicalCharge"]["properties"]["unit"]["enum"],
        )
        self.assertIn(
            "per_1m_characters",
            preview_schema["$defs"]["chargeRecord"]["properties"]["unit"]["enum"],
        )
        self.assertIn("per_1m_characters", UNITS)
        self.assertIn("per_1m_characters", preview_validator.UNITS)

    def test_multiplier_uses_one_million_characters(self):
        record = character_record()
        charge_id = record["charges"][0]["id"]
        validate_canonical_price_records([record])
        self.assertEqual(
            calculate_price_record_cost(record, usage_quantities={charge_id: 2_000_000}),
            Decimal("26"),
        )

    def test_exports_preserve_character_billing_quantity(self):
        component = {
            "component": "input",
            "modality": "text",
            "unit": "per_1m_characters",
            "amount": "13",
        }
        summary = non_token_summary([component])
        self.assertEqual(
            (summary["unit_price"], summary["billing_unit"], summary["billing_quantity"]),
            (13.0, "per_1m_characters", 1_000_000),
        )
        model = {
            "provider_id": "fixture-provider",
            "model_id": "fixture-model",
            "display_name": "Fixture Model",
            "model_family": "Fixture",
            "status": "preview",
            "pricing": {
                "currency": "USD", "unit": None, "input": None, "output": None,
                "cached_input": None, "cache_write": None, "cache_write_1h": None,
                "batch_input": None, "batch_output": None,
            },
            "pricing_components": [component],
            "official_source_url": "https://provider.example/pricing",
            "accessed_at": "2026-10-20T00:00:00Z",
            "last_verified_at": "2026-10-20T00:00:00Z",
            "effective_from": "2026-10-20",
            "notes": "Fixture only.",
        }
        row = csv_rows([model])[0]
        self.assertEqual(
            (row["unit_price"], row["billing_unit"], row["billing_quantity"]),
            ("13", "per_1m_characters", 1_000_000),
        )

    def test_validators_reject_misspelled_and_unknown_units(self):
        preview_validator.validate_charge_unit("per_1m_characters", "fixture-price")
        for invalid_unit in ("per_1m_charcter", "per_unknown"):
            with self.subTest(unit=invalid_unit):
                record = deepcopy(character_record(invalid_unit))
                with self.assertRaisesRegex(PricingContractError, "unit is invalid"):
                    validate_canonical_price_records([record])
                with self.assertRaisesRegex(SystemExit, "invalid charge unit"):
                    preview_validator.validate_charge_unit(invalid_unit, "fixture-price")

    def test_public_export_contract_advances_without_relabeling_1_10(self):
        self.assertEqual(PUBLIC_SCHEMA_VERSION, "1.11.0")
        self.assertIn("1.10.0", SUPPORTED_PUBLIC_SCHEMA_VERSIONS)


if __name__ == "__main__":
    unittest.main()
