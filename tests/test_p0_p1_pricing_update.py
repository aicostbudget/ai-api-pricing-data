import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.lib import select_time_pricing_period


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


class P0P1PricingUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.canonical = read_json("data/canonical/models.json")
        cls.canonical_by_id = {row["model_id"]: row for row in cls.canonical}
        cls.v2_models = read_json("data/pricing-v2-preview/models.json")
        cls.v2_prices = read_json("data/pricing-v2-preview/prices.json")
        cls.v2_projection = read_json("data/pricing-v2-preview/generated/model-pricing.v2.json")["models"]

    def deepseek(self, model_id):
        return self.canonical_by_id[model_id]

    def period_at(self, model_id, timestamp):
        value = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
        return select_time_pricing_period(self.deepseek(model_id)["time_pricing"], value)["id"]

    def test_weekday_boundaries_and_weekends(self):
        monday = {
            "2026-08-31T00:59:00Z": "off_peak",
            "2026-08-31T01:00:00Z": "peak",
            "2026-08-31T03:59:00Z": "peak",
            "2026-08-31T04:00:00Z": "off_peak",
            "2026-08-31T05:59:00Z": "off_peak",
            "2026-08-31T06:00:00Z": "peak",
            "2026-08-31T09:59:00Z": "peak",
            "2026-08-31T10:00:00Z": "off_peak",
        }
        weekend = {
            "2026-08-29T01:00:00Z": "off_peak",
            "2026-08-29T02:00:00Z": "off_peak",
            "2026-08-29T06:00:00Z": "off_peak",
            "2026-08-29T09:59:00Z": "off_peak",
            "2026-08-30T01:00:00Z": "off_peak",
            "2026-08-30T03:00:00Z": "off_peak",
            "2026-08-30T06:00:00Z": "off_peak",
            "2026-08-30T09:59:00Z": "off_peak",
        }
        regression = {
            "2026-08-28T09:59:00Z": "peak",
            "2026-08-28T10:00:00Z": "off_peak",
            "2026-08-29T01:00:00Z": "off_peak",
        }
        for model_id in ("deepseek-v4-flash", "deepseek-v4-pro"):
            for timestamp, expected in {**monday, **weekend, **regression}.items():
                with self.subTest(model=model_id, timestamp=timestamp):
                    self.assertEqual(self.period_at(model_id, timestamp), expected)

    def test_deepseek_exact_prices_fallback_and_schedule_evidence(self):
        expected = {
            "deepseek-v4-flash": {
                "off_peak": {"input": 0.22, "cached_input": 0.007, "output": 0.66},
                "peak": {"input": 0.44, "cached_input": 0.014, "output": 1.32},
            },
            "deepseek-v4-pro": {
                "off_peak": {"input": 0.66, "cached_input": 0.022, "output": 1.98},
                "peak": {"input": 1.32, "cached_input": 0.044, "output": 3.96},
            },
        }
        for model_id, prices in expected.items():
            model = self.deepseek(model_id)
            self.assertNotIn("pricing_tiers", model)
            time_pricing = model["time_pricing"]
            self.assertEqual(time_pricing["rate_effective_from"], "2026-08-16T16:00:00Z")
            self.assertIsNone(time_pricing["schedule_effective_from"])
            self.assertEqual(time_pricing["recurrence"], "weekly")
            self.assertEqual(time_pricing["default_period_id"], "off_peak")
            periods = {period["id"]: period for period in time_pricing["periods"]}
            for period_id, period_prices in prices.items():
                actual = {field: periods[period_id]["pricing"][field] for field in period_prices}
                self.assertEqual(actual, period_prices)
            for field in ("input", "cached_input", "output"):
                self.assertEqual(prices["peak"][field], 2 * prices["off_peak"][field])
                self.assertEqual(model["pricing"][field], prices["peak"][field])

    def test_deepseek_history_v2_and_website_projection_preserve_temporal_pricing(self):
        v2_model_by_id = {row["internalId"]: row for row in self.v2_models}
        v2_prices_by_model = {}
        for row in self.v2_prices:
            v2_prices_by_model.setdefault(row["modelInternalId"], []).append(row)
        projection_by_id = {row["id"]: row for row in self.v2_projection}

        for model_id in ("deepseek-v4-flash", "deepseek-v4-pro"):
            internal_id = f"deepseek/{model_id}"
            prices = [row for row in v2_prices_by_model[internal_id] if row.get("temporalCondition")]
            self.assertEqual({row["temporalCondition"]["periodId"] for row in prices}, {"peak", "off_peak"})
            self.assertTrue(all(row["processingMode"] == "standard" for row in prices))
            self.assertTrue(all(row["contextClass"] == "short" for row in prices))
            peak = next(row for row in prices if row["temporalCondition"]["periodId"] == "peak")
            self.assertEqual(v2_model_by_id[internal_id]["defaultPriceRecordId"], peak["pricingId"])
            self.assertEqual(peak["effectiveFrom"], "2026-08-16T16:00:00Z")
            self.assertIsNone(peak["temporalCondition"]["scheduleEffectiveFrom"])
            self.assertEqual(
                peak["temporalCondition"]["activeWeekdays"],
                ["monday", "tuesday", "wednesday", "thursday", "friday"],
            )
            history_lines = (ROOT / f"data/history/deepseek/{model_id}.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertIn("time_pricing", json.loads(history_lines[-1]))
            website_time_pricing = projection_by_id[model_id]["timePricing"]
            self.assertEqual({period["id"] for period in website_time_pricing["periods"]}, {"peak", "off_peak"})

    def test_gemini_transcribe_exact_prices_modalities_and_unsupported_modes(self):
        expected = {
            "gemini-3.5-transcribe": ("2", "12"),
            "gemini-3.5-transcribe-live": ("3.5", "21"),
        }
        v2_model_by_id = {row["internalId"]: row for row in self.v2_models}
        for model_id, (input_amount, output_amount) in expected.items():
            canonical = self.canonical_by_id[model_id]
            self.assertEqual(canonical["status"], "active")
            self.assertEqual(canonical["release_stage"], "stable")
            self.assertEqual(canonical["input_modality"], "audio")
            self.assertEqual(canonical["output_modality"], "text")
            for field in ("cached_input", "cache_write", "cache_write_1h", "batch_input", "batch_output"):
                self.assertIsNone(canonical["pricing"][field])

            internal_id = f"google-gemini/{model_id}"
            prices = [row for row in self.v2_prices if row["modelInternalId"] == internal_id]
            self.assertEqual(len(prices), 1)
            price = prices[0]
            self.assertEqual(price["processingMode"], "standard")
            charges = {row["component"]: row for row in price["charges"]}
            self.assertEqual(charges["input"]["amount"], input_amount)
            self.assertEqual(charges["input"]["modality"], "audio")
            self.assertEqual(charges["output"]["amount"], output_amount)
            self.assertEqual(charges["output"]["modality"], "text")
            self.assertEqual(v2_model_by_id[internal_id]["releaseStage"], "stable")
            self.assertEqual(v2_model_by_id[internal_id]["lifecycleStatus"], "active")

    def test_gemini_flash_promotional_and_future_price_lifecycle(self):
        for model_id in ("gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash"):
            canonical = self.canonical_by_id[model_id]
            self.assertEqual(
                {field: canonical["pricing"][field] for field in ("input", "cached_input", "output", "batch_input", "batch_cached_input", "batch_output")},
                {"input": 0.75, "cached_input": 0.075, "output": 3.75, "batch_input": 0.375, "batch_cached_input": 0.0375, "batch_output": 1.875},
            )
            periods = {period["id"]: period for period in canonical["pricing_periods"]}
            self.assertEqual(periods["introductory_2026"]["effective_until"], "2026-12-31")
            self.assertTrue(periods["introductory_2026"]["calculation_default"])
            self.assertEqual(periods["standard_2027"]["effective_from"], "2027-01-01")
            current_until = datetime.fromisoformat(periods["introductory_2026"]["effective_until"]).date()
            future_from = datetime.fromisoformat(periods["standard_2027"]["effective_from"]).date()
            self.assertEqual(current_until + timedelta(days=1), future_from)
            self.assertEqual(
                {field: periods["standard_2027"]["pricing"][field] for field in ("input", "cached_input", "output", "batch_input", "batch_cached_input", "batch_output")},
                {"input": 1.5, "cached_input": 0.15, "output": 7.5, "batch_input": 0.75, "batch_cached_input": 0.075, "batch_output": 3.75},
            )
            internal_id = f"google-gemini/{model_id}"
            prices = [row for row in self.v2_prices if row["modelInternalId"] == internal_id]
            self.assertEqual(len(prices), 4)
            self.assertEqual({row["pricingStatus"] for row in prices}, {"current", "future"})
            for boundary, expected_status in (("2026-12-31", "current"), ("2027-01-01", "future")):
                for processing_mode in ("standard", "batch"):
                    selected = [
                        row for row in prices
                        if row["processingMode"] == processing_mode
                        and (row["effectiveFrom"] is None or row["effectiveFrom"] <= boundary)
                        and (row["effectiveUntil"] is None or boundary <= row["effectiveUntil"])
                    ]
                    self.assertEqual(len(selected), 1)
                    self.assertEqual(selected[0]["pricingStatus"], expected_status)
            batch_by_status = {
                row["pricingStatus"]: {charge["component"]: charge["amount"] for charge in row["charges"]}
                for row in prices if row["processingMode"] == "batch"
            }
            self.assertEqual(batch_by_status["current"]["cached_input"], "0.0375")
            self.assertEqual(batch_by_status["future"]["cached_input"], "0.075")
            projection = next(row for row in self.v2_projection if row["id"] == model_id)
            self.assertEqual(projection["selectedPriceEffectiveUntil"], "2026-12-31")
            future_components = [
                component for component in projection["pricingComponents"]
                if component["condition"]["effectiveFrom"] == "2027-01-01"
            ]
            self.assertEqual(len(future_components), 6)

        gemini_38 = self.canonical_by_id["gemini-3.8-flash"]
        self.assertEqual(gemini_38["effective_from"], "2026-09-02")
        self.assertEqual(gemini_38["context_window_tokens"], 1048576)
        self.assertEqual(gemini_38["status"], "active")
        self.assertEqual(gemini_38["release_stage"], "stable")
        self.assertEqual(gemini_38["pricing"]["unit"], "1M tokens")
        self.assertEqual(gemini_38["official_source_url"], "https://ai.google.dev/gemini-api/docs/pricing")
        self.assertIn("https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash", gemini_38["official_source_urls"])
        self.assertIn("https://ai.google.dev/gemini-api/docs/deprecations", gemini_38["official_source_urls"])

        gemini_38_projection = next(row for row in self.v2_projection if row["id"] == "gemini-3.8-flash")
        self.assertEqual(gemini_38_projection["lifecycleStatus"], "active")
        self.assertEqual(gemini_38_projection["releaseStage"], "stable")
        self.assertTrue(gemini_38_projection["defaultSafe"])

        gemini_37 = self.canonical_by_id["gemini-3.7-flash"]
        self.assertEqual(gemini_37["status"], "active")
        self.assertEqual(gemini_37["release_stage"], "stable")
        self.assertNotIn(gemini_37["status"], {"deprecated", "retired", "shutdown", "end_of_life"})

    def test_claude_fable_and_mythos_5_1_pricing_and_lifecycle(self):
        expected_prices = {
            "input": 10.0,
            "output": 50.0,
            "cached_input": 0.25,
            "cache_write": 12.5,
            "cache_write_1h": 20.0,
            "batch_input": 5.0,
            "batch_output": 25.0,
        }
        v2_model_by_id = {row["internalId"]: row for row in self.v2_models}
        projection_by_id = {row["id"]: row for row in self.v2_projection}

        for model_id, expected_availability, expected_status in (
            ("claude-fable-5-1", "Standard", "latest"),
            ("claude-mythos-5-1", "Limited availability", "limited"),
        ):
            with self.subTest(model=model_id):
                canonical = self.canonical_by_id[model_id]
                self.assertEqual(canonical["status"], "active")
                self.assertEqual(canonical["release_stage"], "stable")
                self.assertEqual(canonical["pricing"], {"currency": "USD", "unit": "1M tokens", **expected_prices})

                internal_id = f"anthropic/{model_id}"
                v2_model = v2_model_by_id[internal_id]
                self.assertEqual(v2_model["lifecycleStatus"], "active")
                self.assertEqual(v2_model["availability"], expected_availability)
                self.assertEqual(v2_model["verificationStatus"], "verified")

                projection = projection_by_id[model_id]
                self.assertEqual(projection["status"], expected_status)
                self.assertEqual(projection["lifecycleStatus"], "active")
                self.assertEqual(projection["availability"], expected_availability)
                self.assertTrue(projection["defaultSafe"])
                self.assertEqual(projection["publicExposure"], "public")
                self.assertEqual(projection["inputPrice"], 10)
                self.assertEqual(projection["cachedInputPrice"], 0.25)
                self.assertEqual(projection["outputPrice"], 50)
                self.assertEqual(projection["batchInputPrice"], 5)
                self.assertEqual(projection["batchOutputPrice"], 25)

        for previous_model_id in ("claude-fable-5", "claude-mythos-5"):
            previous = projection_by_id[previous_model_id]
            self.assertEqual(previous["lifecycleStatus"], "active")
            self.assertNotIn(previous["status"], {"deprecated", "retired"})
            self.assertEqual(previous["cachedInputPrice"], 1)

        self.assertEqual(projection_by_id["claude-fable-5"]["status"], "active")
        self.assertNotIn(projection_by_id["claude-fable-5"]["status"], {"latest", "legacy", "deprecated", "retired"})
        self.assertEqual(projection_by_id["claude-fable-5-1"]["status"], "latest")
        self.assertEqual(
            sum(
                row["status"] == "latest"
                for row in self.v2_projection
                if row["provider"] == "anthropic" and row["id"] in {"claude-fable-5", "claude-fable-5-1"}
            ),
            1,
        )
        self.assertEqual(projection_by_id["claude-mythos-5"]["status"], "limited")
        self.assertEqual(projection_by_id["claude-mythos-5-1"]["status"], "limited")

        all_model_ids = set(self.canonical_by_id) | set(projection_by_id)
        for invalid_id in (
            "claude-fable-5.1",
            "claude-fable-5_1",
            "claude-fable-5-01",
            "claude-mythos-5.1",
            "claude-mythos-5_1",
        ):
            self.assertNotIn(invalid_id, all_model_ids)

    def test_non_token_models_are_not_misrepresented(self):
        parse = self.canonical_by_id["parse-v5.0"]
        for field in (
            "input",
            "cached_input",
            "output",
            "cache_write",
            "cache_write_1h",
            "batch_input",
            "batch_output",
        ):
            self.assertIsNone(parse["pricing"][field], field)
        self.assertNotIn("gemini-omni-1.1-flash", self.canonical_by_id)
        self.assertNotIn("gemini-omni-flash-preview", self.canonical_by_id)
        schema = read_json("schema/pricing-v2-preview.schema.json")
        units = schema["$defs"]["chargeRecord"]["properties"]["unit"]["enum"]
        for unit in ("per_1m_tokens", "per_1000_pages", "per_minute", "per_second", "per_image", "per_request"):
            self.assertIn(unit, units)

    def test_deepseek_price_change_events_are_temporal(self):
        events = [json.loads(line) for line in (ROOT / "data/price-change-events/events.jsonl").read_text(encoding="utf-8").splitlines()]
        for model_id in ("deepseek-v4-flash", "deepseek-v4-pro"):
            event = next(row for row in events if row["model_id"] == model_id and row["change_type"] == "temporal_price_schedule_update")
            self.assertIsNone(event["old_time_pricing"])
            self.assertEqual(event["new_time_pricing"]["recurrence"], "weekly")
            self.assertEqual(event["effective_from"], "2026-08-16T16:00:00Z")
            self.assertIsNone(event["new_time_pricing"]["schedule_effective_from"])


if __name__ == "__main__":
    unittest.main()
