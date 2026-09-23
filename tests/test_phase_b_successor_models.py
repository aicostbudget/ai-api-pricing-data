import json
import unittest
from pathlib import Path

from scripts.generate_price_change_events import EVENTS_PATH, generate_events, load_events
from scripts.pricing_contract import validate_model_price_records


ROOT = Path(__file__).resolve().parents[1]
MODEL_IDS = {"gpt-6-sol", "gpt-6-luna", "claude-opus-5-5"}


def read_json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


class PhaseBSuccessorModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = {row["model_id"]: row for row in read_json("data/canonical/models.json")}

    def test_new_models_validate_and_future_announcements_stay_absent(self):
        self.assertTrue(MODEL_IDS <= set(self.models))
        for model_id in MODEL_IDS:
            validate_model_price_records(self.models[model_id])
        self.assertFalse(any("sonnet-5-5" in model_id or "haiku-5-5" in model_id for model_id in self.models))

    def test_predecessor_pricing_and_lifecycle_invariants(self):
        expected = {
            "gpt-5.6-sol": ({"input": 4.0, "cached_input": 0.4, "cache_write": 5.0, "output": 20.0}, None),
            "gpt-5.6-luna": ({"input": 0.2, "cached_input": 0.02, "cache_write": 0.25, "output": 1.2}, None),
            "claude-opus-5": ({"input": 5.0, "cached_input": 0.5, "cache_write": 6.25, "cache_write_1h": 10.0, "output": 25.0}, "2026-07-24"),
        }
        for model_id, (prices, effective_from) in expected.items():
            model = self.models[model_id]
            self.assertEqual({key: model["pricing"][key] for key in prices}, prices)
            self.assertEqual(model["effective_from"], effective_from)
            self.assertEqual(model["status"], "active")
            self.assertNotIn("lifecycle", model)

    def test_gpt6_complete_mode_and_input_token_tier_matrix(self):
        expected = {
            "gpt-6-sol": {"short": (2, 0.2, 2.5, 10), "long": (4, 0.4, 5, 15)},
            "gpt-6-luna": {"short": (0.1, 0.01, 0.125, 0.5), "long": (0.2, 0.02, 0.25, 0.75)},
        }
        factors = {"standard": 1, "batch": 0.5, "flex": 0.5, "fast": 2}
        for model_id, contexts in expected.items():
            model = self.models[model_id]
            self.assertEqual(len(model["price_records"]), 8)
            self.assertEqual(model["cache_eligibility"]["minimum_cacheable_prefix_tokens"], 1024)
            for mode, factor in factors.items():
                for context, base in contexts.items():
                    record = next(row for row in model["price_records"] if row["processing_mode"] == mode and row["context_class"] == context)
                    amounts = {charge["component"]: float(charge["amount"]) for charge in record["charges"]}
                    self.assertEqual(tuple(amounts[key] for key in ("input", "cached_input", "cache_write", "output")), tuple(value * factor for value in base))
                    self.assertEqual(record["tier_selection"]["token_basis"], "input_tokens")
                    self.assertEqual(record["prompt_token_threshold"], 272000)
            for tokens, context in ((272000, "short"), (272001, "long")):
                selected = next(
                    row for row in model["price_records"]
                    if row["processing_mode"] == "standard"
                    and ((row["tier_selection"]["comparison"] == "less_than_or_equal" and tokens <= row["prompt_token_threshold"])
                         or (row["tier_selection"]["comparison"] == "greater_than" and tokens > row["prompt_token_threshold"]))
                )
                self.assertEqual(selected["context_class"], context)

    def test_opus_55_standard_cache_and_fast_contract(self):
        model = self.models["claude-opus-5-5"]
        self.assertEqual(model["context_window_tokens"], 1_000_000)
        self.assertEqual(model["cache_eligibility"]["minimum_cacheable_prefix_tokens"], 512)
        standard = next(row for row in model["price_records"] if row["processing_mode"] == "standard")
        fast = next(row for row in model["price_records"] if row["processing_mode"] == "fast")
        self.assertEqual({charge["component"]: charge["amount"] for charge in standard["charges"]}, {"input": "4", "cache_read": "0.2", "cache_write_5m": "5", "cache_write_1h": "8", "output": "20"})
        self.assertEqual({charge["component"]: charge["amount"] for charge in fast["charges"]}, {"input": "8", "output": "40"})

    def test_generator_emits_both_event_facts_from_explicit_mapping(self):
        generated = generate_events(ROOT / "data/snapshots/2026-09-14/prices.json", ROOT / "data/snapshots/2026-09-23/prices.json")
        target = [event for event in generated if event["model_id"] in MODEL_IDS]
        self.assertEqual(len(target), 6)
        for model_id in MODEL_IDS:
            self.assertEqual({event["change_type"] for event in target if event["model_id"] == model_id}, {"model_added", "successor_transition"})
        mappings = read_json("data/price-change-events/successor-transitions.json")
        self.assertEqual({(row["predecessor_model_id"], row["successor_model_id"]) for row in mappings}, {
            ("gpt-5.6-sol", "gpt-6-sol"), ("gpt-5.6-luna", "gpt-6-luna"), ("claude-opus-5", "claude-opus-5-5"),
        })

    def test_successor_components_never_treat_absence_as_zero(self):
        events = [event for event in load_events(EVENTS_PATH) if event["change_type"] == "successor_transition"]
        self.assertEqual(len(events), 3)
        by_model = {event["successor_model_id"]: event for event in events}
        luna_output = next(row for row in by_model["gpt-6-luna"]["component_comparisons"] if row["component"] == "output")
        self.assertAlmostEqual((float(luna_output["old_amount"]) - float(luna_output["new_amount"])) / float(luna_output["old_amount"]) * 100, 58.3333333)
        opus_fast = [row for row in by_model["claude-opus-5-5"]["component_comparisons"] if row["processing_mode"] == "fast"]
        self.assertEqual({row["component"] for row in opus_fast}, {"input", "output"})
        self.assertTrue(all(row["relation"] == "introduced" and row["old_amount"] is None for row in opus_fast))

    def test_generated_v1_and_v2_coverage(self):
        v1 = {row["model_id"] for row in read_json("data/prices.json")["models"]}
        v2 = {row["internalId"] for row in read_json("data/pricing-v2-preview/models.json")}
        website = {row["canonicalInternalId"] for row in read_json("data/pricing-v2-preview/generated/model-pricing.v2.json")["models"]}
        for model_id in MODEL_IDS:
            provider = "anthropic" if model_id.startswith("claude") else "openai"
            internal_id = f"{provider}/{model_id}"
            self.assertIn(model_id, v1)
            self.assertIn(internal_id, v2)
            self.assertIn(internal_id, website)
            self.assertTrue((ROOT / f"api/v1/models/{provider}/{model_id}.json").exists())


if __name__ == "__main__":
    unittest.main()
