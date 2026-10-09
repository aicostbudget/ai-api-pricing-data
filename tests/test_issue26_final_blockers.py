import json
import subprocess
import unittest
from datetime import datetime, timezone
from pathlib import Path
from scripts.generate_website_projection_v2 import build_pricing_components, build_price_records, parse_effective_at, select_structured_price

ROOT = Path(__file__).resolve().parents[1]
BASE = "80c2ec4991bcaaf795fe9192946f5ec770d57f48"

def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))

class FinalBlockerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = {r["provider_id"] + "/" + r["model_id"]: r for r in json.loads(subprocess.check_output(["git", "show", BASE + ":data/canonical/models.json"], cwd=ROOT))}
        cls.after = {r["provider_id"] + "/" + r["model_id"]: r for r in read("data/canonical/models.json")}
        cls.projection = {r["canonicalInternalId"]: r for r in read("data/pricing-v2-preview/generated/model-pricing.v2.json")["models"]}

    def test_only_ocr_and_kimi_canonical_changes_with_one_published_rate_correction(self):
        self.assertEqual(set(self.after), set(self.before))
        for key in self.after:
            if key not in {"mistral-ai/mistral-ocr-4-0", "moonshot-ai/kimi-k2.6"}:
                self.assertEqual(self.after[key], self.before[key], key)
            expected = dict(self.before[key]["pricing"])
            if key == "moonshot-ai/kimi-k2.6": expected["batch_cached_input"] = .10
            self.assertEqual(self.after[key]["pricing"], expected, key)
        kimi = self.after["moonshot-ai/kimi-k2.6"]
        self.assertEqual(kimi["pricing"]["batch_cached_input"], .10)
        self.assertIn("BILLING PRECISION UNCONFIRMED", kimi["notes"])

    def test_documented_retirement_is_separate_from_actual_http_availability(self):
        ocr = self.after["mistral-ai/mistral-ocr-4-0"]
        self.assertEqual(ocr["status"], "retired")
        self.assertEqual(ocr["lifecycle"], {"deprecation_date": "2026-09-29", "retirement_date": "2026-09-30", "replacement_model_id": "mistral-ocr-4-1"})
        self.assertNotIn("scheduled_transition", ocr["lifecycle"])
        self.assertIn("actual authenticated API availability and HTTP 404 behavior have not been tested", ocr["notes"])
        self.assertNotIn("aliases", ocr)

    def test_base_ocr_history_does_not_import_other_billing_items(self):
        ocr = self.after["mistral-ai/mistral-ocr-4-0"]
        self.assertEqual(len(ocr["pricing_components"]), 1)
        component = ocr["pricing_components"][0]
        self.assertEqual((component["component"], component["unit"], component["amount"], component["processing_mode"]), ("document_page", "per_1000_pages", 4, "standard"))
        self.assertEqual((component["pricing_status"], component["effective_from"], component["effective_until"]), ("historical", "2026-06-23", "2026-09-29"))
        self.assertFalse(component["calculation_default"])
        self.assertTrue(any("/_next/static/chunks/" in url for url in ocr["official_source_urls"]))

    def test_history_display_cannot_select_current_billing_or_default_calculation(self):
        key = "mistral-ai/mistral-ocr-4-0"
        rows = [r for r in read("data/pricing-v2-preview/prices.json") if r["modelInternalId"] == key]
        at = parse_effective_at("2026-10-09T00:00:00Z")
        self.assertIsNone(select_structured_price({key: rows}, key, at, {}))
        self.assertIsNone(build_pricing_components(rows, at, {}))
        self.assertIsNone(build_price_records(rows, at, {}))
        shown = build_pricing_components(rows, at, {}, display_historical=True)
        self.assertEqual(shown[0]["amount"], "4")
        self.assertFalse(shown[0]["calculationDefault"])
        current = self.projection[key]
        self.assertEqual(current["pricingSourceType"], "canonical_verified_structured_price")
        self.assertEqual(current["governanceClass"], "HISTORICAL_REFERENCE")
        self.assertFalse(current["defaultSafe"])
        self.assertIsNone(current["selectedPriceRecordId"])
        self.assertIsNone(current["selectedBillingPriceRecordId"])
        self.assertEqual(current["priceRecords"][0]["pricingStatus"], "historical")
        self.assertEqual(current["priceRecords"][0]["verifiedAt"], self.after[key]["last_verified_at"])
        self.assertEqual(current["verifiedAt"], self.after[key]["last_verified_at"])
        actual = datetime.fromisoformat(current["verifiedAt"].replace("Z", "+00:00"))
        self.assertLessEqual(actual, datetime.now(timezone.utc))

    def test_other_models_verification_and_access_facts_do_not_drift(self):
        prior = json.loads(subprocess.check_output(["git", "show", BASE + ":data/pricing-v2-preview/generated/model-pricing.v2.json"], cwd=ROOT))
        for row in prior["models"]:
            key = row["canonicalInternalId"]
            if key in {"mistral-ai/mistral-ocr-4-0", "moonshot-ai/kimi-k2.6"}: continue
            for field in ("lifecycleStatus", "defaultSafe", "inputPrice", "outputPrice", "verifiedAt", "checkedAt", "accessStatus", "bindingStatus"):
                self.assertEqual(self.projection[key].get(field), row.get(field), (key, field))
