"""Focused regression checks for the October 2026 lifecycle backfill."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.generate_price_change_events import (
    build_dedupe_key, build_event_id, generate_events, load_events, validate_event,
)


ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    ("openai", "gpt-5.3-codex"): ("deprecated", "2026-10-01", "gpt-6-sol", False),
    ("openai", "gpt-5.4-nano"): ("deprecated", "2026-10-01", "gpt-6-luna", False),
    ("openai", "gpt-5.1"): ("deprecated", "2026-10-01", "gpt-6-sol", False),
    ("openai", "tts-1"): ("deprecated", "2026-10-01", "gpt-realtime-2.1-mini", False),
    ("openai", "tts-1-hd"): ("deprecated", "2026-10-01", "gpt-realtime-2.1-mini", False),
    ("openai", "gpt-4o-mini-tts-2025-03-20"): ("deprecated", "2026-10-01", "gpt-realtime-2.1-mini", False),
    ("openai", "gpt-4o-mini-tts-2025-12-15"): ("deprecated", "2026-10-01", "gpt-realtime-2.1-mini", False),
    ("openai", "gpt-5.4-cyber"): ("retired", "2026-10-01", None, False),
    ("xai", "grok-voice-transcribe-1.0"): ("retired", "2026-10-02", "grok-voice-transcribe-2.0", True),
    ("google-gemini", "gemini-2.5-flash-image"): ("retired", "2026-10-02", "gemini-3.1-flash-image-preview", False),
}


class OctoberLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        models = json.loads((ROOT / "data/canonical/models.json").read_text(encoding="utf-8"))
        cls.current = {(m["provider_id"], m["model_id"]): m for m in models}
        snapshot = json.loads((ROOT / "data/snapshots/2026-10-04/prices.json").read_text(encoding="utf-8"))
        cls.before = {(m["provider_id"], m["model_id"]): m for m in snapshot["models"]}

    def test_canonical_targets_keep_recommendations_distinct_from_redirects(self):
        for key, (status, date, replacement, redirect) in TARGETS.items():
            with self.subTest(key=key):
                model = self.current[key]
                if model.get("lifecycle_conflict"):
                    self.assertEqual(model["status"], "unknown")
                    self.assertNotIn("lifecycle", model)
                    self.assertEqual(model["lifecycle_conflict"]["resolution"], "unresolved")
                    self.assertEqual({s["shutdown_date"] for s in model["lifecycle_conflict"]["sources"]}, {"2026-10-02", "2027-03-15"})
                    continue
                lifecycle = model["lifecycle"]
                self.assertEqual(model["status"], status)
                self.assertEqual(lifecycle.get("replacement_model_id"), replacement)
                self.assertEqual(bool(lifecycle.get("scheduled_transition")), redirect)
                if redirect:
                    self.assertEqual(lifecycle["scheduled_transition"]["kind"], "retirement_redirect")
                self.assertEqual(
                    lifecycle["retirement_date"] if status == "retired" else lifecycle["deprecation_date"],
                    date,
                )

    def test_snapshot_delta_emits_lifecycle_truth_without_fake_launch_or_redirect(self):
        before_models = [self.before[key] for key in TARGETS if key in self.before]
        after_models = [self.current[key] for key in TARGETS]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            before = root / "2026-10-04" / "prices.json"
            after = root / "2026-10-05" / "prices.json"
            before.parent.mkdir()
            after.parent.mkdir()
            before.write_text(json.dumps({"models": before_models}), encoding="utf-8")
            after.write_text(json.dumps({"models": after_models}), encoding="utf-8")
            events = generate_events(before, after)
        by_key = {(event["provider_id"], event["model_id"]): event for event in events}
        conflicted = {key for key in TARGETS if self.current[key].get("lifecycle_conflict")}
        self.assertEqual(set(by_key), set(TARGETS) - conflicted)
        self.assertTrue(conflicted.isdisjoint(by_key))
        for key, (status, date, replacement, redirect) in TARGETS.items():
            with self.subTest(key=key):
                if key in conflicted:
                    continue
                event = by_key[key]
                self.assertEqual(event["change_type"], "lifecycle_update")
                self.assertEqual(event["effective_from"], date)
                self.assertEqual(event["new_status"], status)
                self.assertEqual(event["new_lifecycle"].get("replacement_model_id"), replacement)
                if key not in self.before:
                    self.assertIsNone(event["old_status"])
                    self.assertIn("absent from the before snapshot", event["notes"])
                if not redirect:
                    self.assertNotIn("redirect", event["notes"].lower())
                else:
                    self.assertEqual(event["new_lifecycle"]["scheduled_transition"]["kind"], "retirement_redirect")
                if key in {("openai", "gpt-5.4-cyber"), ("google-gemini", "gemini-2.5-flash-image")}:
                    self.assertEqual(event["new_prices"], {"input": None, "cached_input": None, "output": None})
                    self.assertIsNone(event["unit"])

    def test_null_lifecycle_price_is_valid_but_price_events_remain_strict(self):
        existing = load_events(ROOT / "data/price-change-events/events.jsonl")
        lifecycle = next(event.copy() for event in existing if event["change_type"] == "lifecycle_update")
        lifecycle["old_prices"] = {"input": None, "cached_input": None, "output": None}
        lifecycle["new_prices"] = {"input": None, "cached_input": None, "output": None}
        lifecycle["unit"] = None
        lifecycle["dedupe_key"] = build_dedupe_key(lifecycle)
        lifecycle["event_id"] = build_event_id(lifecycle)
        validate_event(lifecycle)

        price = next(event.copy() for event in existing if event["change_type"] == "price_update")
        price["unit"] = None
        price["dedupe_key"] = build_dedupe_key(price)
        price["event_id"] = build_event_id(price)
        with self.assertRaisesRegex(ValueError, "unit must be 1M tokens"):
            validate_event(price)


if __name__ == "__main__":
    unittest.main()
