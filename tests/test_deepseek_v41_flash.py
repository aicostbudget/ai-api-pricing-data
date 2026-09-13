import json
import unittest
from pathlib import Path

from tests.website_source import resolve_website_source


ROOT = Path(__file__).resolve().parents[1]
WEBSITE = resolve_website_source(ROOT)
OFFICIAL_PRICING = "https://api-docs.deepseek.com/quick_start/pricing"
OFFICIAL_CHANGELOG = "https://api-docs.deepseek.com/updates/"
VISION_EXP_RELEASE_DATE = "2026-08-21"
OFFICIAL_NEWS = "https://deepseek.com/en/news/deepseek-v4-1-flash/"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


class DeepSeekV41FlashTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.canonical = read_json(ROOT / "data/canonical/models.json")
        cls.identities = read_json(ROOT / "data/pricing-v2-preview/model-identity-registry.json")
        cls.v2 = read_json(ROOT / "data/pricing-v2-preview/generated/model-pricing.v2.json")["models"]
        cls.api = read_json(ROOT / "api/v1/providers/deepseek.json")["models"]
        cls.hf = read_json(ROOT / "huggingface/prices.json")["records"]
        cls.website = read_json(WEBSITE / "data/pricing-v2-projection/model-pricing.v2.json")["models"]
        cls.monitor = read_json(WEBSITE / "data/pricing-v2-projection/price-change-events.v1.json")["events"]

    def canonical_model(self, model_id):
        return next(row for row in self.canonical if row["provider_id"] == "deepseek" and row["model_id"] == model_id)

    def identity(self, model_id):
        return next(row for row in self.identities if row["internalId"] == f"deepseek/{model_id}")

    def projected(self, rows, model_id):
        return next(row for row in rows if row["provider"] == "deepseek" and row["id"] == model_id)

    def test_flash_canonical_identity_sources_and_prices(self):
        model = self.canonical_model("deepseek-flash")
        self.assertEqual(model["display_name"], "DeepSeek V4.1 Flash")
        self.assertEqual(model["status"], "active")
        self.assertEqual(model["effective_from"], "2026-09-10")
        self.assertEqual({key: model["pricing"][key] for key in (
            "currency", "unit", "input", "cached_input", "output",
        )}, {
            "currency": "USD", "unit": "1M tokens", "input": 0.3,
            "cached_input": 0.006, "output": 1.2,
        })
        self.assertEqual(
            set(model["official_source_urls"]),
            {OFFICIAL_PRICING, OFFICIAL_CHANGELOG, OFFICIAL_NEWS},
        )
        identity = self.identity("deepseek-flash")
        self.assertEqual(identity["canonicalOfficialId"], "deepseek-flash")
        self.assertEqual(identity["routingBehavior"], "direct")

    def test_peak_and_off_peak_schedule_is_preserved(self):
        schedule = self.canonical_model("deepseek-flash")["time_pricing"]
        self.assertEqual(schedule["rate_effective_from"], "2026-09-10T04:00:00Z")
        periods = {row["id"]: row for row in schedule["periods"]}
        self.assertEqual(periods["peak"]["pricing"], {
            "currency": "USD", "unit": "1M tokens", "input": 0.3,
            "cached_input": 0.006, "output": 1.2,
        })
        self.assertEqual(periods["peak"]["active_weekdays"], [
            "monday", "tuesday", "wednesday", "thursday", "friday",
        ])
        self.assertEqual(periods["peak"]["time_windows"], [
            {"start": "01:00", "end": "04:00"},
            {"start": "06:00", "end": "10:00"},
        ])
        self.assertEqual(periods["off_peak"]["pricing"], {
            "currency": "USD", "unit": "1M tokens", "input": 0.15,
            "cached_input": 0.003, "output": 0.6,
        })
        self.assertTrue(periods["off_peak"]["all_other_times"])

    def test_legacy_models_are_retired_but_resolvable_and_billed_as_flash(self):
        for model_id in ("deepseek-v4-flash", "deepseek-v4-flash-vision-exp"):
            canonical = self.canonical_model(model_id)
            self.assertEqual(canonical["status"], "retired")
            transition = canonical["lifecycle"]["scheduled_transition"]
            self.assertEqual(transition["effective_from"], "2026-09-10")
            self.assertTrue(transition["source_slug_remains_resolvable"])
            self.assertEqual(transition["redirect_target_model_id"], "deepseek-flash")
            self.assertEqual(transition["billing_model_id"], "deepseek-flash")
            self.assertEqual(transition["billing_source"], "redirect_target")
            identity = self.identity(model_id)
            self.assertEqual(identity["lifecycleStatus"], "retired")
            self.assertEqual(identity["routingBehavior"], "retired_redirect")
            self.assertEqual(identity["redirectTargetInternalId"], "deepseek/deepseek-flash")
            self.assertEqual(identity["billingModelInternalId"], "deepseek/deepseek-flash")

    def test_v4_pro_continues_current_service_without_future_redirect(self):
        model = self.canonical_model("deepseek-v4-pro")
        self.assertEqual(model["status"], "active")
        self.assertNotIn("lifecycle", model)
        self.assertEqual({key: model["pricing"][key] for key in (
            "currency", "unit", "input", "cached_input", "output",
        )}, {
            "currency": "USD", "unit": "1M tokens", "input": 1.32,
            "cached_input": 0.044, "output": 3.96,
        })
        identity = self.identity("deepseek-v4-pro")
        self.assertEqual(identity["routingBehavior"], "direct")
        self.assertIsNone(identity["redirectTargetInternalId"])
        self.assertIsNone(identity["billingModelInternalId"])
        self.assertIsNone(identity.get("scheduledTransition"))
        forbidden = [event for event in self.monitor if event["modelId"] == "deepseek-v4-pro" and event.get("effectiveFrom", "").startswith("2026-09-14")]
        self.assertEqual(forbidden, [])

    def test_v2_api_website_and_hf_pricing_parity(self):
        expected = (0.3, 0.006, 1.2)
        for rows in (self.v2, self.website):
            row = self.projected(rows, "deepseek-flash")
            self.assertEqual((row["inputPrice"], row["cachedInputPrice"], row["outputPrice"]), expected)
            self.assertEqual(row["timePricing"]["rateEffectiveFrom"], "2026-09-10T04:00:00Z")
        api = next(row for row in self.api if row["model_id"] == "deepseek-flash")
        self.assertEqual((api["pricing"]["input"], api["pricing"]["cached_input"], api["pricing"]["output"]), expected)
        hf = next(row for row in self.hf if row["provider_id"] == "deepseek" and row["model_id"] == "deepseek-flash")
        self.assertEqual((hf["input_price_per_1m_tokens"], hf["cached_input_price_per_1m_tokens"], hf["output_price_per_1m_tokens"]), expected)
        self.assertEqual(hf["time_pricing"]["rateEffectiveFrom"], "2026-09-10T04:00:00Z")

    def test_launch_retirement_and_pricing_events_are_unique(self):
        current = [event for event in self.monitor if event["providerId"] == "deepseek" and event["detectedAt"] == "2026-09-13"]
        self.assertEqual(len({event["eventId"] for event in current}), len(current))
        self.assertEqual(sorted((event["modelId"], event["changeType"]) for event in current), [
            ("deepseek-flash", "model_added"),
            ("deepseek-v4-flash", "lifecycle_update"),
            ("deepseek-v4-flash", "temporal_price_schedule_update"),
            ("deepseek-v4-flash-vision-exp", "lifecycle_update"),
        ])
        vision_events = [event for event in current if event["modelId"] == "deepseek-v4-flash-vision-exp"]
        self.assertEqual(len(vision_events), 1)
        vision_retirement = vision_events[0]
        self.assertEqual(vision_retirement["effectiveFrom"], "2026-09-10")
        self.assertEqual(vision_retirement["oldStatus"], "active")
        self.assertEqual(vision_retirement["newStatus"], "retired")
        self.assertEqual(
            vision_retirement["newLifecycle"]["scheduled_transition"]["redirect_target_model_id"],
            "deepseek-flash",
        )
        self.assertFalse(any(
            event["modelId"] == "deepseek-v4-flash-vision-exp"
            and event["changeType"] == "model_added"
            and event.get("effectiveFrom") == "2026-09-10"
            for event in self.monitor
        ))
        self.assertEqual(VISION_EXP_RELEASE_DATE, "2026-08-21")
        temporal = next(event for event in current if event["changeType"] == "temporal_price_schedule_update")
        self.assertEqual(temporal["effectiveFrom"], "2026-09-10T04:00:00Z")
        self.assertEqual(temporal["announcementUrl"], OFFICIAL_CHANGELOG)
        self.assertEqual(temporal["newStatus"], "retired")
        self.assertEqual(
            temporal["newLifecycle"]["scheduled_transition"]["billing_model_id"],
            "deepseek-flash",
        )


if __name__ == "__main__":
    unittest.main()
