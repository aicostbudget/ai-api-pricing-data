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
    official_announcement_url,
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
        "unit": "per_1m_tokens",
        "currency": "USD",
        "modality": "text",
        "calculation_default": True,
        "condition": {
            "processing_mode": processing_mode,
            "context_class": "short",
            "prompt_token_threshold": None,
            "tier_selection": None,
            "region_policy": "global",
            "effective_from": "2026-07-01",
            "effective_until": None,
        },
        "source_refs": ["source:test-provider:pricing"],
        "verification_status": "verified",
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

    def test_model_added_event_preserves_identity_and_lifecycle(self):
        added = model(model_id="model-new", input_price=0.3, cached_input=0.006, output_price=1.2)
        added.update({
            "status": "active",
            "effective_from": "2026-09-10",
            "official_source_urls": ["https://example.com/pricing", "https://example.com/news"],
        })
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before = root / "2026-07-26" / "prices.json"
            after = root / "2026-07-27" / "prices.json"
            snapshot(before, [])
            snapshot(after, [added])
            events = generate_events(before, after)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["change_type"], "model_added")
        self.assertIsNone(events[0]["old_status"])
        self.assertEqual(events[0]["new_status"], "active")
        self.assertEqual(events[0]["effective_from"], "2026-09-10")

    def test_newly_observed_retired_model_is_lifecycle_update_not_model_added(self):
        retired = model(model_id="historical-model")
        retired.update({
            "status": "retired",
            "effective_from": "2026-08-21",
            "lifecycle": {
                "retirement_date": "2026-09-10",
                "scheduled_transition": {
                    "effective_from": "2026-09-10",
                    "redirect_target_model_id": "replacement-model",
                    "billing_model_id": "replacement-model",
                    "billing_source": "redirect_target",
                },
            },
        })
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before = root / "2026-07-26" / "prices.json"
            after = root / "2026-07-27" / "prices.json"
            snapshot(before, [])
            snapshot(after, [retired])
            events = generate_events(before, after)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["change_type"], "lifecycle_update")
        self.assertEqual(events[0]["old_status"], "active")
        self.assertEqual(events[0]["new_status"], "retired")
        self.assertEqual(events[0]["effective_from"], "2026-09-10")
        self.assertNotEqual(events[0]["effective_from"], "2026-08-21")

    def test_lifecycle_update_is_separate_from_pricing(self):
        before = model()
        before["status"] = "active"
        after = copy.deepcopy(before)
        after["status"] = "retired"
        after["lifecycle"] = {"retirement_date": "2026-09-10"}
        event = self.assert_one_change(before, after, "lifecycle_update")
        self.assertEqual(event["old_prices"], event["new_prices"])
        self.assertEqual(event["old_status"], "active")
        self.assertEqual(event["new_status"], "retired")

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

    def test_component_numeric_format_and_provenance_metadata_do_not_emit(self):
        before = model()
        after = model()
        before["pricing_components"] = [pricing_component("3.750")]
        after["pricing_components"] = [pricing_component("3.75")]
        after["pricing_components"][0]["source_refs"] = ["source:test-provider:updated-pricing-page"]
        after["pricing_components"][0]["verification_status"] = "partially_verified"
        self.assertEqual(self.generated(before, after), [])

    def test_component_unit_change_fails_closed(self):
        before = model()
        after = model()
        before["pricing_components"] = [pricing_component()]
        after["pricing_components"] = [pricing_component()]
        after["pricing_components"][0]["unit"] = "per_request"
        with self.assertRaisesRegex(
            ValueError,
            r"test-provider/model-a: unit changed for .*cache_write_5m.* from 'per_1m_tokens' to 'per_request'",
        ):
            self.generated(before, after)

    def test_component_added_fails_closed(self):
        before = model()
        after = model()
        before["pricing_components"] = []
        after["pricing_components"] = [pricing_component()]
        with self.assertRaisesRegex(ValueError, r"test-provider/model-a: component added .*cache_write_5m"):
            self.generated(before, after)

    def test_component_removed_fails_closed(self):
        before = model()
        after = model()
        before["pricing_components"] = [pricing_component()]
        after["pricing_components"] = []
        with self.assertRaisesRegex(ValueError, r"test-provider/model-a: component removed .*cache_write_5m"):
            self.generated(before, after)

    def test_unchanged_legacy_components_do_not_block_unrelated_event_generation(self):
        before = model()
        after = model()
        legacy_components = [
            {"id": "input_image", "component": "input", "amount": 0.01, "unit": "per_image"},
            {"id": "output_image", "component": "output", "amount": 0.04, "unit": "per_image"},
        ]
        before["pricing_components"] = copy.deepcopy(legacy_components)
        after["pricing_components"] = copy.deepcopy(legacy_components)
        self.assertEqual(self.generated(before, after), [])
        after["pricing_components"][0]["amount"] = 0.02
        with self.assertRaisesRegex(
            ValueError,
            r"Unsupported legacy component semantic change for test-provider/model-a",
        ):
            self.generated(before, after)

    def test_component_condition_change_requires_explicit_semantics(self):
        before = model()
        after = model()
        before["pricing_components"] = [pricing_component("3.75", "standard")]
        after["pricing_components"] = [pricing_component("4.25", "batch")]
        with self.assertRaisesRegex(ValueError, r"test-provider/model-a: condition changed for .*cache_write_5m"):
            self.generated(before, after)

    def test_component_identity_change_requires_explicit_semantics(self):
        before = model()
        after = model()
        before["pricing_components"] = [pricing_component()]
        after["pricing_components"] = [pricing_component()]
        after["pricing_components"][0]["component"] = "cache_write_1h"
        with self.assertRaisesRegex(ValueError, r"test-provider/model-a: component identity changed for .*cache_write_5m"):
            self.generated(before, after)

    def test_component_billing_semantic_metadata_change_fails_closed(self):
        before = model()
        after = model()
        before["pricing_components"] = [pricing_component()]
        after["pricing_components"] = [pricing_component()]
        after["pricing_components"][0]["calculation_default"] = False
        with self.assertRaisesRegex(
            ValueError,
            r"test-provider/model-a: calculation_default changed for .*cache_write_5m.* from True to False",
        ):
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

    def test_regeneration_replaces_stale_semantics_for_same_snapshot_scope(self):
        generated = self.generated(model(), model(input_price=2))
        stale = copy.deepcopy(generated[0])
        stale["change_type"] = "cached_price_added"
        stale["dedupe_key"] = build_dedupe_key(stale)
        stale["event_id"] = build_event_id(stale)
        merged = merge_events([stale], generated)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["change_type"], "price_update")

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
        self.assertEqual(
            CHANGE_TYPES,
            {
                "price_update",
                "cached_price_added",
                "cached_price_removed",
                "component_price_update",
                "temporal_price_schedule_update",
                "model_added",
                "lifecycle_update",
                "successor_transition",
            },
        )
        before = model(provider_id="new-provider", model_id="new-model")
        before["status"] = "active"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before_path = root / "2026-07-26" / "prices.json"
            after_path = root / "2026-07-27" / "prices.json"
            snapshot(before_path, [])
            snapshot(after_path, [before])
            generated = generate_events(before_path, after_path)
            self.assertEqual(len(generated), 1)
            self.assertEqual(generated[0]["change_type"], "model_added")

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
        additions = generate_events(Path("data/snapshots/2026-07-05/prices.json"), REAL_BEFORE)
        self.assertTrue(additions)
        self.assertTrue(all(event["change_type"] == "model_added" for event in additions))

    def test_provider_filter_avoids_unrelated_snapshot_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before = root / "2026-07-26" / "prices.json"
            after = root / "2026-07-27" / "prices.json"
            snapshot(before, [model(provider_id="other", input_price=1), model(provider_id="deepseek", input_price=1)])
            snapshot(after, [model(provider_id="other", input_price=2), model(provider_id="deepseek", input_price=3)])
            events = generate_events(before, after, provider_id="deepseek")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["provider_id"], "deepseek")
        self.assertEqual(events[0]["new_prices"]["input"], 3)

    def test_time_pricing_verification_refresh_is_not_a_price_event(self):
        before = model(provider_id="deepseek")
        before["time_pricing"] = {
            "rate_effective_from": "2026-08-16T16:00:00Z",
            "schedule_verified_at": "2026-08-28T00:00:00Z",
            "schedule_accessed_at": "2026-08-28T00:00:00Z",
            "periods": [{"id": "peak"}],
        }
        after = copy.deepcopy(before)
        after["time_pricing"]["schedule_verified_at"] = "2026-09-13T00:00:00Z"
        after["time_pricing"]["schedule_accessed_at"] = "2026-09-13T00:00:00Z"
        self.assertEqual(self.generated(before, after), [])

    def test_redirect_billing_schedule_preserves_native_before_and_target_after(self):
        native = model(provider_id="provider", model_id="legacy", input_price=2, cached_input=0.2, output_price=4)
        native["status"] = "active"
        native["time_pricing"] = {
            "rate_effective_from": "2026-08-16T16:00:00Z",
            "periods": [{"id": "peak", "pricing": {"input": 2}}],
        }
        retired = copy.deepcopy(native)
        retired["status"] = "retired"
        retired["last_verified_at"] = "2026-09-13T00:00:00Z"
        retired["official_source_urls"] = ["https://example.com/pricing", "https://example.com/updates"]
        retired["lifecycle"] = {
            "retirement_date": "2026-09-10",
            "scheduled_transition": {
                "effective_from": "2026-09-10",
                "billing_source": "redirect_target",
                "billing_model_id": "replacement",
                "redirect_target_model_id": "replacement",
            },
        }
        replacement = model(
            provider_id="provider", model_id="replacement", input_price=1, cached_input=0.1, output_price=2,
        )
        replacement["status"] = "active"
        replacement["last_verified_at"] = "2026-09-13T00:00:00Z"
        replacement["time_pricing"] = {
            "rate_effective_from": "2026-09-10T04:00:00Z",
            "periods": [{"id": "peak", "pricing": {"input": 1}}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before_path = root / "2026-09-09" / "prices.json"
            after_path = root / "2026-09-13" / "prices.json"
            snapshot(before_path, [native])
            snapshot(after_path, [retired, replacement])
            generated = generate_events(before_path, after_path)
        legacy_events = [event for event in generated if event["model_id"] == "legacy"]
        self.assertEqual(
            {event["change_type"] for event in legacy_events},
            {"lifecycle_update", "temporal_price_schedule_update"},
        )
        pricing_event = next(
            event for event in legacy_events if event["change_type"] == "temporal_price_schedule_update"
        )
        self.assertEqual(pricing_event["old_time_pricing"], native["time_pricing"])
        self.assertEqual(pricing_event["new_time_pricing"], replacement["time_pricing"])
        self.assertEqual(pricing_event["effective_from"], "2026-09-10T04:00:00Z")
        self.assertEqual(pricing_event["new_lifecycle"], retired["lifecycle"])

    def test_official_announcement_prefers_current_changelog_over_older_news(self):
        self.assertEqual(
            official_announcement_url({
                "official_source_urls": [
                    "https://api-docs.deepseek.com/quick_start/pricing",
                    "https://api-docs.deepseek.com/updates/",
                    "https://deepseek.com/en/news/deepseek-v4-1-flash/",
                ],
            }),
            "https://api-docs.deepseek.com/updates/",
        )


if __name__ == "__main__":
    unittest.main()
