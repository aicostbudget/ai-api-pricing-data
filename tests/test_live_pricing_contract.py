from __future__ import annotations

import unittest
import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from scripts.generate_website_projection_v2 import (
    build_pricing_components,
    parse_effective_at,
    public_dataset_v15_compatible,
)
from scripts.pricing_contract import (
    calculate_price_record_cost,
    normalize_canonical_price_records,
    select_price_record,
    validate_canonical_price_records,
    validate_model_price_records,
)


SOURCE = "https://example.com/official"
CHECKED_AT = "2026-09-21T08:58:31Z"


def charge(
    charge_id: str,
    component: str,
    modality: str,
    unit: str,
    amount: str,
    **selectors,
) -> dict:
    return {
        "id": charge_id,
        "component": component,
        "modality": modality,
        "unit": unit,
        "amount": amount,
        **selectors,
    }


def price_record(
    record_id: str,
    charges: list[dict],
    *,
    transport: str | None = None,
    calculation_default: bool = True,
) -> dict:
    record = {
        "id": record_id,
        "processing_mode": "standard",
        "context_class": "short",
        "pricing_status": "current",
        "calculation_default": calculation_default,
        "prompt_token_threshold": None,
        "effective_from": None,
        "effective_until": None,
        "currency": "USD",
        "charges": charges,
        "region_policy": {
            "pricing_geography": "global_base",
            "endpoint_geographies": ["global"],
            "data_residencies": ["global"],
            "availability": {"default": "available", "rules": []},
            "price_adjustments": [],
        },
        "source_refs": [SOURCE],
        "verification_status": "verified",
        "checked_at": CHECKED_AT,
        "verified_at": CHECKED_AT,
        "billing_note": "Live pricing compatibility fixture.",
    }
    if transport is not None:
        record["transport"] = transport
    return record


def normalized(records: list[dict], model_id: str = "provider/model") -> list[dict]:
    return normalize_canonical_price_records(model_id, records, lambda value: value)


class LivePricingContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.models = {
            (row["provider_id"], row["model_id"]): row
            for row in json.loads((root / "data/canonical/models.json").read_text(encoding="utf-8"))
        }
        cls.projection = {
            row["canonicalInternalId"]: row
            for row in json.loads((root / "data/pricing-v2-preview/generated/model-pricing.v2.json").read_text(encoding="utf-8"))["models"]
        }
        cls.hf = {
            (row["provider_id"], row["model_id"]): row
            for row in json.loads((root / "huggingface/prices.json").read_text(encoding="utf-8"))["records"]
        }

    def test_grok_rest_and_streaming_are_mutually_selectable(self):
        records = [
            price_record(
                "price:xai/grok-voice-transcribe-2.0:rest",
                [charge("charge:grok:rest", "session_duration", "audio", "per_hour", "0.10")],
                transport="rest",
            ),
            price_record(
                "price:xai/grok-voice-transcribe-2.0:streaming",
                [charge("charge:grok:streaming", "session_duration", "audio", "per_hour", "0.20")],
                transport="streaming",
                calculation_default=False,
            ),
        ]
        validate_canonical_price_records(records)
        projected = normalized(records, "xai/grok-voice-transcribe-2.0")
        rest = select_price_record(projected, processing_mode="standard", prompt_tokens=0, transport="rest")
        streaming = select_price_record(projected, processing_mode="standard", prompt_tokens=0, transport="streaming")
        self.assertEqual(rest["charges"][0]["amount"], "0.1")
        self.assertEqual(streaming["charges"][0]["amount"], "0.2")
        with self.assertRaisesRegex(Exception, "transport"):
            select_price_record(projected, processing_mode="standard", prompt_tokens=0)

    def test_multimodal_components_project_without_collisions(self):
        base = "price:google-gemini/gemini-3.8-live:standard:short:current"
        records = [price_record(base, [
            charge(base + ":input:text", "input", "text", "per_1m_tokens", "0.75"),
            charge(base + ":input:audio", "input", "audio", "per_1m_tokens", "3"),
            charge(base + ":input:image", "input", "image", "per_1m_tokens", "1"),
            charge(base + ":input:video", "input", "video", "per_1m_tokens", "1"),
            charge(base + ":output:text", "output", "text", "per_1m_tokens", "4.5"),
            charge(base + ":output:audio", "output", "audio", "per_1m_tokens", "12"),
        ])]
        components = build_pricing_components(
            normalized(records, "google-gemini/gemini-3.8-live"),
            parse_effective_at(CHECKED_AT),
            {},
        )
        self.assertEqual(len(components), 6)
        self.assertIn(("input", "audio"), {(item["component"], item["modality"]) for item in components})

    def test_alternative_measurements_are_not_added_together(self):
        base = "price:google-gemini/gemini-3.8-live:standard:short:current"
        record = price_record(base, [
            charge(base + ":audio:tokens", "input", "audio", "per_1m_tokens", "3", alternative_group="audio_input"),
            charge(base + ":audio:minutes", "input", "audio", "per_minute", "0.005", alternative_group="audio_input"),
        ])
        validate_canonical_price_records([record])
        token_cost = calculate_price_record_cost(
            record,
            usage_quantities={base + ":audio:tokens": 1_000_000},
            alternative_selections={"audio_input": base + ":audio:tokens"},
        )
        minute_cost = calculate_price_record_cost(
            record,
            usage_quantities={base + ":audio:minutes": 60},
            alternative_selections={"audio_input": base + ":audio:minutes"},
        )
        self.assertEqual(token_cost, Decimal("3"))
        self.assertEqual(minute_cost, Decimal("0.3"))

    def test_optional_transcription_charge_requires_feature(self):
        record = price_record("price:gemini/live", [
            charge("charge:audio-output", "output", "audio", "per_1m_tokens", "12"),
            charge(
                "charge:output-transcription",
                "output",
                "text",
                "per_1m_tokens",
                "4.5",
                optional_feature="output_audio_transcription",
            ),
        ])
        usage = {"charge:audio-output": 1_000_000, "charge:output-transcription": 1_000_000}
        self.assertEqual(calculate_price_record_cost(record, usage_quantities=usage), Decimal("12"))
        self.assertEqual(
            calculate_price_record_cost(
                record,
                usage_quantities=usage,
                enabled_features={"output_audio_transcription"},
            ),
            Decimal("16.5"),
        )

    def test_default_model_metadata_is_independent_of_lifecycle(self):
        base_model = {
            "provider_id": "xai",
            "model_id": "grok-voice-transcribe-1.0",
            "status": "active",
            "pricing": {
                "currency": "USD",
                "unit": None,
                "input": None,
                "output": None,
                "cached_input": None,
                "cache_write": None,
                "cache_write_1h": None,
                "batch_input": None,
                "batch_output": None,
            },
            "official_source_url": SOURCE,
            "official_source_urls": [SOURCE],
            "model_selection": {
                "default_when_model_omitted": False,
                "explicit_model_id_supported": True,
                "source_refs": [SOURCE],
                "checked_at": CHECKED_AT,
                "verified_at": CHECKED_AT,
            },
            "price_records": [price_record("price:xai/grok-voice-transcribe-1.0:rest", [
                charge("charge:grok-1:rest", "session_duration", "audio", "per_hour", "0.10")
            ], transport="rest")],
        }
        validate_model_price_records(base_model)
        current = deepcopy(base_model)
        current["model_id"] = "grok-voice-transcribe-2.0"
        current["model_selection"]["default_when_model_omitted"] = True
        validate_model_price_records(current)
        self.assertEqual((base_model["status"], current["status"]), ("active", "active"))

    def test_public_dataset_accepts_lossless_live_components(self):
        row = {
            "pricingComponents": [
                {
                    "component": "input",
                    "modality": "audio",
                    "unit": unit,
                    "alternativeGroup": "audio_input",
                    "condition": {},
                }
                for unit in ("per_1m_tokens", "per_minute")
            ]
        }
        self.assertTrue(public_dataset_v15_compatible(row))

    def test_onboarded_models_are_lossless_across_canonical_v2_and_hf(self):
        for model_id, is_default in (
            ("grok-voice-transcribe-1.0", False),
            ("grok-voice-transcribe-2.0", True),
        ):
            canonical = self.models[("xai", model_id)]
            self.assertEqual(canonical["status"], "active")
            self.assertEqual(canonical["model_selection"]["default_when_model_omitted"], is_default)
            self.assertEqual(
                {record["transport"]: record["charges"][0]["amount"] for record in canonical["price_records"]},
                {"rest": "0.10", "streaming": "0.20"},
            )
            projected = self.projection[f"xai/{model_id}"]
            self.assertEqual({item["condition"]["transport"] for item in projected["pricingComponents"]}, {"rest", "streaming"})
            self.assertEqual(projected["modelSelection"]["defaultWhenModelOmitted"], is_default)
            self.assertEqual(self.hf[("xai", model_id)]["model_selection"]["default_when_model_omitted"], is_default)

        for model_id in ("gemini-3.8-live", "gemini-3.8-live-extended-thinking"):
            canonical = self.models[("google-gemini", model_id)]
            charges = canonical["price_records"][0]["charges"]
            self.assertEqual(len(charges), 12)
            self.assertEqual({charge.get("alternative_group") for charge in charges if charge.get("alternative_group")}, {"audio_input", "image_input", "video_input", "audio_output"})
            self.assertEqual({charge.get("optional_feature") for charge in charges if charge.get("optional_feature")}, {"input_audio_transcription", "output_audio_transcription"})
            projected = self.projection[f"google-gemini/{model_id}"]
            self.assertEqual(len(projected["pricingComponents"]), 12)
            public_components = self.hf[("google-gemini", model_id)]["pricing_components"]
            self.assertEqual(len(public_components), 12)
            self.assertTrue(any(item.get("alternative_group") == "audio_input" for item in public_components))
            self.assertTrue(any(item.get("optional_feature") == "output_audio_transcription" for item in public_components))


if __name__ == "__main__":
    unittest.main()
