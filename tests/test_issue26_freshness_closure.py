import json
import subprocess
import unittest
from copy import deepcopy
from pathlib import Path
from datetime import date
from unittest.mock import patch
from scripts.pricing_contract import normalize_canonical_price_records, select_price_record, calculate_price_record_cost
from tests.freshness_assertions import BASELINE, assert_grok46_contract

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))

class FreshnessClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = {r["provider_id"] + "/" + r["model_id"]: r for r in read("data/canonical/models.json")}
        cls.old = {r["provider_id"] + "/" + r["model_id"]: r for r in json.loads(subprocess.check_output(["git", "show", BASELINE + ":data/canonical/models.json"], cwd=ROOT))}
        cls.projection = {r["canonicalInternalId"]: r for r in read("data/pricing-v2-preview/generated/model-pricing.v2.json")["models"]}

    def test_v1_prices_access_binding_and_identity_universe_are_preserved(self):
        historical_after = {r["provider_id"]+"/"+r["model_id"]: r for r in json.loads(subprocess.check_output(["git", "show", "72ce4a1a7475bbd9c2a394aedf864afec073d494:data/canonical/models.json"], cwd=ROOT))}
        self.assertEqual(set(historical_after), set(self.old))
        for key, current in historical_after.items():
            expected = deepcopy(self.old[key]["pricing"])
            if key == "moonshot-ai/kimi-k2.6":
                expected["batch_cached_input"] = .10
            self.assertEqual(current["pricing"], expected, key)
            for field in ("access_status", "access_evidence", "access_checked_at", "binding_status", "binding_evidence"):
                self.assertEqual(current.get(field), self.old[key].get(field), (key, field))

    def test_failed_supplementary_source_keeps_original_verification(self):
        sources = read("data/pricing-v2-preview/sources.json")
        failed = next(r for r in sources if r["url"] == "https://openai.com/index/gpt-6-astra/")
        self.assertEqual(failed["verifiedAt"], "2026-09-04T17:34:11Z")

    def test_published_kimi_price_and_original_ocr_amount_are_preserved(self):
        kimi = self.models["moonshot-ai/kimi-k2.6"]
        self.assertEqual(kimi["pricing"]["batch_cached_input"], .10)
        self.assertIn("BILLING PRECISION UNCONFIRMED", kimi["notes"])
        component = self.models["mistral-ai/mistral-ocr-4-0"]["pricing_components"][0]
        original = self.old["mistral-ai/mistral-ocr-4-0"]["pricing_components"][0]
        for field in ("id", "amount", "unit", "component", "effective_from"):
            self.assertEqual(component[field], original[field])

    def test_deprecated_is_neither_retired_nor_default_safe(self):
        for key in ("openai/gpt-5", "openai/o3"):
            self.assertEqual(self.models[key]["status"], "deprecated")
            row = self.projection[key]
            self.assertEqual(row["lifecycleStatus"], "deprecated")
            self.assertFalse(row["defaultSafe"])
            self.assertIsNone(row["inputPrice"])
            self.assertIn("deprecated_identity", row["blockedFromDefaultReasons"])
        self.assertEqual(self.projection["openai/gpt-4.1-mini"]["lifecycleStatus"], "active")
        self.assertEqual(self.projection["openai/gpt-4.1-mini"]["status"], "legacy")
        self.assertFalse(self.projection["openai/gpt-4.1-mini"]["defaultSafe"])

    def test_shared_url_refresh_does_not_reverify_unchecked_models(self):
        baseline = json.loads(subprocess.check_output(["git", "show", BASELINE + ":data/pricing-v2-preview/generated/model-pricing.v2.json"], cwd=ROOT))
        before = {r["canonicalInternalId"]: r for r in baseline["models"]}
        for key in ("google-gemini/gemini-3.8-flash-tts", "google-gemini/gemini-3.8-flash-lite-tts", "xai/grok-imagine-image-2.0", "xai/grok-voice-transcribe-2.0"):
            self.assertEqual(self.projection[key]["verifiedAt"], before[key]["verifiedAt"], key)

    def test_gemini_modes_storage_and_year_boundary_are_lossless(self):
        row = self.models["google-gemini/gemini-3.8-flash"]
        records = {(r["processing_mode"], r["pricing_status"]): r for r in row["price_records"]}
        expected = {"standard": ("0.75", "0.075", "3.75"), "batch": ("0.375", "0.0375", "1.875"), "flex": ("0.375", "0.0375", "1.875"), "priority": ("1.35", "0.135", "6.75")}
        self.assertEqual(len(records), 8)
        for mode, amounts in expected.items():
            current, future = records[(mode, "current")], records[(mode, "future")]
            charges = {c["component"]: c for c in current["charges"]}
            self.assertEqual(tuple(charges[k]["amount"] for k in ("input", "cached_input", "output")), amounts)
            self.assertEqual((charges["storage"]["amount"], charges["storage"]["unit"]), ("0.5", "per_1m_tokens_per_hour"))
            self.assertEqual(current["effective_until"], "2026-12-31")
            self.assertEqual(future["effective_from"], "2027-01-01")
            self.assertEqual(next(c for c in future["charges"] if c["component"] == "storage")["amount"], "1")
        self.assertEqual(records[("priority", "current")]["effective_from"], None)

    def test_grok_threshold_and_region_adjustment_select_without_auto_access(self):
        row = self.models["xai/grok-4.6"]
        assert_grok46_contract(self, row)
        records = normalize_canonical_price_records("xai/grok-4.6", row["price_records"], lambda url: url)
        # This fixture asserts the observed quote on its observation day, independent of wall clock.
        class ObservationDate(date):
            @classmethod
            def today(cls): return cls(2026, 10, 9)
        with patch("scripts.pricing_contract.date", ObservationDate):
            for tokens, context in ((199999, "short"), (200000, "long")):
                selected = select_price_record(records, processing_mode="standard", prompt_tokens=tokens, endpoint_geography="us", data_residency="global", at="2026-10-09")
                self.assertEqual(selected["contextClass"], context)
                self.assertEqual(selected["selectionStatus"], "available")
        # An unknown effectiveFrom must still fail closed when the observation becomes historical.
        class FollowingDate(date):
            @classmethod
            def today(cls): return cls(2026, 10, 10)
        with patch("scripts.pricing_contract.date", FollowingDate):
            historical = select_price_record(records, processing_mode="standard", prompt_tokens=199999, endpoint_geography="us", data_residency="global", at="2026-10-09")
            self.assertEqual(historical["selectionStatus"], "unavailable")
            self.assertIn("Historical price coverage is unknown", historical["reason"])

    def test_image_original_identity_and_future_redirect_survive_new_resolution(self):
        row = self.models["xai/grok-imagine-image-quality"]
        self.assertEqual(row["lifecycle"], self.old["xai/grok-imagine-image-quality"]["lifecycle"])
        self.assertEqual(row["status"], "deprecated")
        values = {c["id"]: c["amount"] for c in row["pricing_components"]}
        self.assertEqual(values, {"media_input_image": .01, "output_image_1k": .05, "output_image_1_5k": .06, "output_image_2k": .07})
