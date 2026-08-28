import copy
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.generate_price_change_events import (
    CHANGE_TYPES,
    EVENTS_PATH,
    build_dedupe_key,
    build_event_id,
    generate_events,
    load_events,
    merge_events,
    validate_event,
    validate_unique_events,
    write_events,
)


REAL_BEFORE = Path("data/snapshots/2026-07-09/prices.json")
REAL_AFTER = Path("data/snapshots/2026-07-27/prices.json")


def model(provider_id="test-provider", model_id="model-a", input_price=1, cached_input=None, output_price=2):
    return {
        "provider_id": provider_id,
        "model_id": model_id,
        "pricing": {
            "currency": "USD",
            "unit": "1M tokens",
            "input": input_price,
            "cached_input": cached_input,
            "output": output_price,
        },
        "official_source_url": "https://example.com/pricing",
        "last_verified_at": "2026-07-27T00:00:00Z",
    }


def snapshot(path: Path, models):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"models": models}), encoding="utf-8")


def pricing_component(amount="3.75", processing_mode="standard"):
    return {
        "pricing_id": "price:test-provider/model-a:standard:short:current",
        "charge_id": "price:test-provider/model-a:standard:short:current:cache_write_5m:text:per_1m_tokens",
        "component": "cache_write_5m",
        "amount": amount,
        "condition": {
            "processing_mode": processing_mode,
            "context_class": "short",
            "prompt_token_threshold": None,
            "tier_selection": None,
            "region_policy": "global",
            "effective_from": "2026-07-01",
            "effective_until": None,
        },
    }


def canonical_event(provider_id="mistral-ai", model_id="mistral-large", change_type="price_update", detected_at="2026-07-27"):
    matches = [
        event
        for event in load_events(EVENTS_PATH)
        if (
            event["provider_id"],
            event["model_id"],
            event["change_type"],
            event["detected_at"],
        )
        == (provider_id, model_id, change_type, detected_at)
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"expected one canonical event for {(provider_id, model_id, change_type, detected_at)}, found {len(matches)}"
        )
    return copy.deepcopy(matches[0])


def refresh_identity(event):
    event["dedupe_key"] = build_dedupe_key(event)
    event["event_id"] = build_event_id(event)
    return event


class PriceChangeEventTests(unittest.TestCase):
    def generated(self, before_model, after_model):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before = root / "2026-07-26" / "prices.json"
            after = root / "2026-07-27" / "prices.json"
            snapshot(before, [before_model])
            snapshot(after, [after_model])
            return generate_events(before, after)

    def assert_one_change(self, before_model, after_model, change_type):
        events = self.generated(before_model, after_model)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["change_type"], change_type)
        return events[0]

    def test_input_price_decrease_and_increase_generate_price_update(self):
        decrease = self.assert_one_change(model(input_price=2), model(input_price=1), "price_update")
        increase = self.assert_one_change(model(input_price=1), model(input_price=2), "price_update")
        self.assertEqual(decrease["old_prices"]["input"], 2)
        self.assertEqual(decrease["new_prices"]["input"], 1)
        self.assertEqual(increase["old_prices"]["input"], 1)
        self.assertEqual(increase["new_prices"]["input"], 2)

    def test_output_price_decrease_and_increase_generate_price_update(self):
        decrease = self.assert_one_change(model(output_price=3), model(output_price=2), "price_update")
        increase = self.assert_one_change(model(output_price=2), model(output_price=3), "price_update")
        self.assertEqual(decrease["old_prices"]["output"], 3)
        self.assertEqual(decrease["new_prices"]["output"], 2)
        self.assertEqual(increase["old_prices"]["output"], 2)
        self.assertEqual(increase["new_prices"]["output"], 3)

    def test_cached_input_added_and_removed_are_distinct(self):
        added = self.assert_one_change(model(cached_input=None), model(cached_input=0.2), "cached_price_added")
        removed = self.assert_one_change(model(cached_input=0.2), model(cached_input=None), "cached_price_removed")
        self.assertIsNone(added["old_prices"]["cached_input"])
        self.assertIsNone(removed["new_prices"]["cached_input"])

    def test_component_only_cache_write_change_generates_detailed_event(self):
        before = model()
        after = model()
        before["pricing_components"] = [pricing_component("3.75")]
        after["pricing_components"] = [pricing_component("4.25")]
        event = self.assert_one_change(before, after, "component_price_update")
        self.assertEqual(event["old_prices"], event["new_prices"])
        self.assertEqual(event["component_changes"], [{
            "pricing_id": "price:test-provider/model-a:standard:short:current",
            "charge_id": "price:test-provider/model-a:standard:short:current:cache_write_5m:text:per_1m_tokens",
            "component": "cache_write_5m",
            "old_amount": "3.75",
            "new_amount": "4.25",
            "condition": pricing_component()["condition"],
        }])

    def test_component_numeric_format_metadata_and_add_remove_do_not_emit(self):
        before = model()
        after = model()
        before["pricing_components"] = [pricing_component("3.750")]
        after["pricing_components"] = [pricing_component("3.75")]
        self.assertEqual(self.generated(before, after), [])
        after["pricing_components"] = []
        self.assertEqual(self.generated(before, after), [])

    def test_component_condition_change_requires_explicit_semantics(self):
        before = model()
        after = model()
        before["pricing_components"] = [pricing_component("3.75", "standard")]
        after["pricing_components"] = [pricing_component("4.25", "batch")]
        with self.assertRaises(ValueError):
            self.generated(before, after)

    def test_no_event_for_identical_prices_verified_date_source_url_or_numeric_format(self):
        before = model(input_price=1, cached_input=None, output_price=2)
        after = copy.deepcopy(before)
        after["last_verified_at"] = "2026-07-28T00:00:00Z"
        after["official_source_url"] = "https://example.com/new-pricing"
        after["pricing"]["input"] = 1.0
        self.assertEqual(self.generated(before, after), [])

    def test_invalid_negative_bool_nan_infinity_and_missing_identity_fail(self):
        invalid_values = [-1, True, math.nan, math.inf]
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.generated(model(input_price=value), model(input_price=1))
        broken_provider = model()
        broken_provider["provider_id"] = ""
        with self.assertRaises(ValueError):
            self.generated(broken_provider, model())
        broken_model = model()
        broken_model["model_id"] = ""
        with self.assertRaises(ValueError):
            self.generated(broken_model, model())

    def test_first_observed_allows_missing_effective_date(self):
        event = canonical_event()
        self.assertIsNone(event["effective_from"])
        self.assertEqual(event["date_basis"], "first_observed")
        validate_event(event)

    def test_provider_announced_and_official_changelog_require_effective_date(self):
        for basis in ("provider_announced", "official_changelog"):
            event = canonical_event()
            event["date_basis"] = basis
            with self.subTest(basis=basis):
                with self.assertRaises(ValueError):
                    validate_event(event)

    def test_change_type_must_match_actual_price_delta(self):
        cached_added = canonical_event("xai", "grok-4.3", "cached_price_added")
        cached_added["change_type"] = "price_update"
        with self.assertRaises(ValueError):
            validate_event(cached_added)
        price_update = canonical_event()
        price_update["change_type"] = "cached_price_added"
        with self.assertRaises(ValueError):
            validate_event(price_update)

    def test_invalid_urls_dates_and_source_paths_fail(self):
        cases = []
        bad_url = canonical_event()
        bad_url["official_source_url"] = "https://"
        cases.append(bad_url)
        bad_order = canonical_event()
        bad_order["verified_at"] = "2026-07-26"
        cases.append(bad_order)
        same_source = canonical_event()
        same_source["source_snapshot_after"] = same_source["source_snapshot_before"]
        cases.append(same_source)
        escaped = canonical_event()
        escaped["source_snapshot_before"] = "../outside/prices.json"
        cases.append(escaped)
        absolute = canonical_event()
        absolute["source_snapshot_before"] = str(Path.cwd() / "data" / "snapshots" / "2026-07-09" / "prices.json")
        cases.append(absolute)
        missing = canonical_event()
        missing["source_snapshot_before"] = "data/snapshots/1999-01-01/prices.json"
        cases.append(missing)
        for event in cases:
            with self.subTest(event=event):
                with self.assertRaises(ValueError):
                    validate_event(event)

    def test_dedupe_and_event_id_are_stable_against_metadata_and_key_order(self):
        event = canonical_event()
        original_key = event["dedupe_key"]
        original_id = event["event_id"]
        changed = copy.deepcopy(event)
        changed["verified_at"] = "2026-07-28"
        changed["effective_from"] = "2026-07-26"
        changed["date_basis"] = "provider_announced"
        changed["announcement_url"] = "https://example.com/changelog"
        changed["notes"] = "Manual note."
        changed["official_source_url"] = "https://example.com/new-source"
        self.assertEqual(build_dedupe_key(changed), original_key)
        self.assertEqual(build_event_id(changed), original_id)
        reordered = json.loads(json.dumps(changed, sort_keys=False))
        self.assertEqual(build_dedupe_key(reordered), original_key)

    def test_repeated_runs_and_manual_metadata_backfill_do_not_duplicate(self):
        generated = generate_events(REAL_BEFORE, REAL_AFTER)
        merged = merge_events([], generated)
        self.assertEqual(len(merged), 2)
        backfilled = copy.deepcopy(merged[0])
        backfilled["effective_from"] = "2026-07-26"
        backfilled["date_basis"] = "provider_announced"
        backfilled["announcement_url"] = "https://example.com/changelog"
        backfilled["notes"] = "Manual announcement backfill."
        merged_again = merge_events([backfilled, merged[1]], generated)
        self.assertEqual(len(merged_again), 2)
        kept = next(event for event in merged_again if event["dedupe_key"] == backfilled["dedupe_key"])
        self.assertEqual(kept["effective_from"], "2026-07-26")
        self.assertEqual(kept["announcement_url"], "https://example.com/changelog")
        self.assertEqual(kept["notes"], "Manual announcement backfill.")

    def test_cli_idempotency_and_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "events.jsonl"
            command = [
                sys.executable,
                "scripts/generate_price_change_events.py",
                "--before",
                str(REAL_BEFORE),
                "--after",
                str(REAL_AFTER),
                "--output",
                str(output),
            ]
            subprocess.run(command, check=True, capture_output=True, text=True)
            first = output.read_bytes()
            subprocess.run(command, check=True, capture_output=True, text=True)
            second = output.read_bytes()
            self.assertEqual(first, second)
            dry_output = Path(tmp) / "dry-run.jsonl"
            dry = subprocess.run(command[:-2] + ["--output", str(dry_output), "--dry-run"], check=True, capture_output=True, text=True)
            self.assertFalse(dry_output.exists())
            self.assertEqual(len([line for line in dry.stdout.splitlines() if line.strip()]), 2)

    def test_load_events_rejects_malformed_jsonl_and_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text("{not json}\n", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                load_events(path)
        event = canonical_event()
        with self.assertRaises(ValueError):
            validate_unique_events([event, copy.deepcopy(event)])
        same_dedupe = copy.deepcopy(event)
        same_dedupe["event_id"] = "different:event:id"
        with self.assertRaises(ValueError):
            validate_unique_events([event, same_dedupe])

    def test_schema_enum_matches_actual_generator_scope(self):
        self.assertEqual(CHANGE_TYPES, {"price_update", "cached_price_added", "cached_price_removed", "component_price_update"})
        before = model(provider_id="new-provider", model_id="new-model")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before_path = root / "2026-07-26" / "prices.json"
            after_path = root / "2026-07-27" / "prices.json"
            snapshot(before_path, [])
            snapshot(after_path, [before])
            self.assertEqual(generate_events(before_path, after_path), [])

    def test_required_real_events_are_present_with_canonical_semantics(self):
        events = load_events(EVENTS_PATH)
        by_identity = {
            (event["provider_id"], event["model_id"], event["change_type"], event["detected_at"]): event
            for event in events
        }
        mistral = by_identity[("mistral-ai", "mistral-large", "price_update", "2026-07-27")]
        self.assertEqual(mistral["change_type"], "price_update")
        self.assertEqual(mistral["old_prices"], {"input": 2, "cached_input": None, "output": 6})
        self.assertEqual(mistral["new_prices"], {"input": 0.5, "cached_input": 0.05, "output": 1.5})
        xai = by_identity[("xai", "grok-4.3", "cached_price_added", "2026-07-27")]
        self.assertEqual(xai["change_type"], "cached_price_added")
        self.assertEqual(xai["old_prices"], {"input": 1.25, "cached_input": None, "output": 2.5})
        self.assertEqual(xai["new_prices"], {"input": 1.25, "cached_input": 0.2, "output": 2.5})
        gpt = by_identity[("openai", "gpt-5.6-sol", "price_update", "2026-08-22")]
        self.assertEqual(gpt["old_prices"], {"input": 5, "cached_input": 0.5, "output": 30})
        self.assertEqual(gpt["new_prices"], {"input": 4, "cached_input": 0.4, "output": 20})

    def test_current_event_set_has_no_duplicate_gpt_reverse_or_false_sonnet_event(self):
        events = load_events(EVENTS_PATH)
        gpt = [
            event
            for event in events
            if event["provider_id"] == "openai"
            and event["model_id"] == "gpt-5.6-sol"
            and event["change_type"] == "price_update"
        ]
        self.assertEqual(len(gpt), 1)
        self.assertFalse(
            any(
                event["old_prices"] == {"input": 4, "cached_input": 0.4, "output": 20}
                and event["new_prices"] == {"input": 5, "cached_input": 0.5, "output": 30}
                for event in gpt
            )
        )
        self.assertFalse(
            any(
                event["provider_id"] == "anthropic"
                and event["model_id"] == "claude-sonnet-5"
                and event["change_type"] == "price_update"
                for event in events
            )
        )

    def test_real_snapshot_diff_has_two_events_and_other_models_do_not_change(self):
        events = generate_events(REAL_BEFORE, REAL_AFTER)
        self.assertEqual(len(events), 2)
        changed = {(event["provider_id"], event["model_id"]) for event in events}
        self.assertEqual(changed, {("mistral-ai", "mistral-large"), ("xai", "grok-4.3")})
        self.assertEqual(generate_events(Path("data/snapshots/2026-07-05/prices.json"), REAL_BEFORE), [])


if __name__ == "__main__":
    unittest.main()
