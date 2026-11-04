import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.generate_price_change_events import (
    EVENTS_PATH,
    build_dedupe_key,
    build_event_id,
    generate_events,
    load_events,
    scheduled_price_changes,
    validate_event,
)
from tests.test_price_change_events import REAL_AFTER, REAL_BEFORE, model, snapshot


def with_real_snapshots(event):
    """validate_event requires tracked repository snapshots; temp-dir paths would fail for an unrelated reason."""
    event = copy.deepcopy(event)
    event["source_snapshot_before"] = REAL_BEFORE.as_posix()
    event["source_snapshot_after"] = REAL_AFTER.as_posix()
    event["dedupe_key"] = build_dedupe_key(event)
    event["event_id"] = build_event_id(event)
    return event


def record(status, effective_from, amounts, mode="standard", default=False, modality="text", record_id=None):
    record_id = record_id or f"price:test-provider/model-a:{mode}:short:{status}:{effective_from}"
    return {
        "id": record_id,
        "pricing_status": status,
        "processing_mode": mode,
        "context_class": "short",
        "prompt_token_threshold": None,
        "calculation_default": default,
        "effective_from": effective_from,
        "charges": [
            {
                "id": f"{record_id}:{component}",
                "component": component,
                "amount": amount,
                "unit": "per_1m_tokens",
                "modality": modality if component == "output" else "text",
            }
            for component, amount in amounts.items()
        ],
        "source_refs": ["https://example.com/pricing", "https://example.com/changelog"],
        "verified_at": "2026-07-27T00:00:00Z",
    }


CURRENT = {"input": "2", "cached_input": "0.10", "output": "10"}
DOUBLED = {"input": "4", "cached_input": "0.20", "output": "20"}


def scheduled_model(with_future=True, future_date="2026-12-01", future_amounts=None):
    item = model(input_price=2, cached_input=0.1, output_price=10)
    item.update({
        "status": "active",
        "display_name": "Model A",
        "official_source_urls": ["https://example.com/pricing", "https://example.com/changelog"],
    })
    item["price_records"] = [
        record("current", "2026-07-01", CURRENT, default=True),
        record("current", "2026-07-01", {"input": "1", "cached_input": "0.05", "output": "5"}, mode="batch"),
    ]
    if with_future:
        item["price_records"] += [
            record("future", future_date, future_amounts or DOUBLED),
            record("future", future_date, CURRENT, mode="batch"),
        ]
    return item


class ScheduledPriceChangeTests(unittest.TestCase):
    def generated(self, before_models, after_models, before_id="2026-07-26", after_id="2026-07-27"):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before = root / before_id / "prices.json"
            after = root / after_id / "prices.json"
            snapshot(before, before_models)
            snapshot(after, after_models)
            return generate_events(before, after)

    def test_new_future_record_announces_scheduled_change_of_default_mode(self):
        events = self.generated([scheduled_model(with_future=False)], [scheduled_model()])
        self.assertEqual([event["change_type"] for event in events], ["scheduled_price_change"])
        event = events[0]
        self.assertEqual(event["old_prices"], {"input": 2, "cached_input": 0.1, "output": 10})
        self.assertEqual(event["new_prices"], {"input": 4, "cached_input": 0.2, "output": 20})
        self.assertEqual(event["effective_from"], "2026-12-01")
        self.assertEqual(event["detected_at"], "2026-07-27")
        self.assertEqual(event["date_basis"], "provider_announced")
        self.assertEqual(event["official_source_url"], "https://example.com/pricing")
        self.assertEqual(event["announcement_url"], "https://example.com/changelog")
        self.assertIn("not an applied price change", event["notes"])
        validate_event(with_real_snapshots(event))

    def test_model_added_with_future_record_also_announces_schedule(self):
        events = self.generated([], [scheduled_model()])
        self.assertEqual(sorted(event["change_type"] for event in events), ["model_added", "scheduled_price_change"])

    def test_unchanged_reverified_or_renamed_schedule_is_not_reannounced(self):
        after = scheduled_model()
        for item in after["price_records"]:
            item["verified_at"] = "2026-08-01T00:00:00Z"
            item["id"] = item["id"] + ":renamed"
        after["last_verified_at"] = "2026-08-01T00:00:00Z"
        self.assertEqual(self.generated([scheduled_model()], [after]), [])

    def test_moved_date_or_new_amount_is_a_new_announcement(self):
        moved = self.generated([scheduled_model()], [scheduled_model(future_date="2027-01-01")])
        self.assertEqual([(e["change_type"], e["effective_from"]) for e in moved], [("scheduled_price_change", "2027-01-01")])
        repriced = self.generated([scheduled_model()], [scheduled_model(future_amounts={"input": "3", "cached_input": "0.15", "output": "15"})])
        self.assertEqual([e["new_prices"]["input"] for e in repriced], [3])

    def test_same_prices_on_different_dates_have_distinct_identity(self):
        first = self.generated([scheduled_model(with_future=False)], [scheduled_model()])[0]
        second = self.generated([scheduled_model(with_future=False)], [scheduled_model(future_date="2027-01-01")])[0]
        self.assertNotEqual(first["dedupe_key"], second["dedupe_key"])

    def test_non_default_mode_only_schedule_and_audio_output_emit_nothing(self):
        batch_only = scheduled_model(with_future=False)
        batch_only["price_records"].append(record("future", "2026-12-01", CURRENT, mode="batch"))
        self.assertEqual(scheduled_price_changes(batch_only), {})
        audio = scheduled_model(with_future=False)
        audio["price_records"] = [
            record("current", "2026-07-01", {"input": "0.5", "output": "9"}, default=True, modality="audio"),
            record("future", "2026-12-01", {"input": "1", "output": "18"}, modality="audio"),
        ]
        self.assertEqual(scheduled_price_changes(audio), {})

    def test_past_dated_or_deprecated_schedule_emits_nothing(self):
        self.assertEqual(self.generated([scheduled_model(with_future=False)], [scheduled_model(future_date="2026-07-27")]), [])
        deprecated = scheduled_model()
        deprecated["status"] = "deprecated"
        before = scheduled_model(with_future=False)
        before["status"] = "deprecated"
        self.assertEqual(self.generated([before], [deprecated]), [])

    def test_price_update_keeps_announced_effective_date_when_schedule_takes_effect(self):
        flipped = scheduled_model(with_future=False)
        flipped["pricing"].update({"input": 4, "cached_input": 0.2, "output": 20})
        flipped["price_records"] = [record("current", "2026-12-01", DOUBLED, default=True)]
        events = self.generated([scheduled_model()], [flipped], before_id="2026-11-30", after_id="2026-12-01")
        self.assertEqual([event["change_type"] for event in events], ["price_update"])
        self.assertEqual(events[0]["effective_from"], "2026-12-01")
        self.assertEqual(events[0]["date_basis"], "provider_announced")

    def test_validation_rejects_malformed_scheduled_events(self):
        event = with_real_snapshots(self.generated([scheduled_model(with_future=False)], [scheduled_model()])[0])
        validate_event(event)

        def broken(**changes):
            candidate = copy.deepcopy(event)
            candidate.update(changes)
            candidate["dedupe_key"] = build_dedupe_key(candidate)
            candidate["event_id"] = build_event_id(candidate)
            return candidate

        for candidate in (
            broken(new_prices=copy.deepcopy(event["old_prices"])),
            broken(effective_from=None, date_basis="first_observed"),
            broken(effective_from="2026-07-27"),
        ):
            with self.assertRaisesRegex(ValueError, "scheduled_price_change"):
                validate_event(candidate)

    def test_backfilled_gemini_schedules_are_in_the_event_file(self):
        scheduled = {
            event["model_id"]: event
            for event in load_events(EVENTS_PATH)
            if event["change_type"] == "scheduled_price_change"
        }
        self.assertEqual(scheduled["gemini-4-argon"]["effective_from"], "2026-12-01")
        self.assertEqual(scheduled["gemini-4-argon"]["new_prices"], {"input": 4, "cached_input": 0.2, "output": 20})
        for model_id in ("gemini-3.8-flash", "gemini-3.6-flash"):
            self.assertEqual(scheduled[model_id]["effective_from"], "2027-01-01")
            self.assertEqual(scheduled[model_id]["new_prices"], {"input": 1.5, "cached_input": 0.15, "output": 7.5})
        for event in scheduled.values():
            self.assertTrue(event["official_source_url"].startswith("https://ai.google.dev/"))


if __name__ == "__main__":
    unittest.main()
