from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.generate_price_change_events import generate_events


ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "gemini-3.7-flash": "gemini-3.8-flash",
    "gemini-3.5-flash": "gemini-3.6-flash",
}


def read_json(relative_path: str):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


class GeminiFlashDeprecationRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.models = {
            row["model_id"]: row
            for row in read_json("data/canonical/models.json")
            if row["provider_id"] == "google-gemini"
        }

    def test_deprecated_endpoints_keep_identity_history_and_successor(self) -> None:
        for model_id, successor_id in TARGETS.items():
            with self.subTest(model_id=model_id):
                model = self.models[model_id]
                successor = self.models[successor_id]
                self.assertEqual(model["status"], "deprecated")
                self.assertEqual(model["lifecycle"], {
                    "deprecation_date": "2026-10-08",
                    "replacement_model_id": successor_id,
                })
                self.assertNotIn("retirement_date", model["lifecycle"])
                self.assertNotIn("scheduled_transition", model["lifecycle"])
                self.assertIn("automatically routed", model["notes"])
                self.assertIn("not shutting down", model["notes"])
                self.assertTrue(model["pricing"])
                self.assertEqual(successor["status"], "active")
                self.assertNotEqual(model["model_id"], successor["model_id"])

    def test_official_evidence_and_public_projection_fail_closed(self) -> None:
        projection = {
            row["canonicalInternalId"]: row
            for row in read_json("data/pricing-v2-preview/generated/model-pricing.v2.json")["models"]
        }
        for model_id, successor_id in TARGETS.items():
            with self.subTest(model_id=model_id):
                model = self.models[model_id]
                self.assertIn("https://ai.google.dev/gemini-api/docs/changelog", model["official_source_urls"])
                self.assertIn("https://ai.google.dev/gemini-api/docs/deprecations", model["official_source_urls"])
                row = projection[f"google-gemini/{model_id}"]
                self.assertEqual(row["lifecycleStatus"], "deprecated")
                self.assertEqual(row["deprecationDate"], "2026-10-08")
                self.assertIsNone(row["retirementDate"])
                self.assertEqual(row["replacementInternalId"], f"google-gemini/{successor_id}")
                self.assertFalse(row["defaultSafe"])
                self.assertIsNone(row["selectedPriceRecordId"])

    def test_no_decision_model_is_publicly_integrated_without_task_contract(self) -> None:
        canonical_ids = {
            (row["provider_id"], row["model_id"])
            for row in read_json("data/canonical/models.json")
        }
        self.assertNotIn(("azure", "Microsoft-Decision-1"), canonical_ids)
        self.assertNotIn(("microsoft", "Microsoft-Decision-1"), canonical_ids)

    def test_pending_lifecycle_events_use_lifecycle_evidence(self) -> None:
        events = generate_events(
            ROOT / "data/snapshots/2026-10-09/prices.json",
            ROOT / "data/snapshots/2026-10-13/prices.json",
            provider_id="google-gemini",
            model_ids=set(TARGETS),
        )
        self.assertEqual(len(events), 2)
        self.assertEqual({event["model_id"] for event in events}, set(TARGETS))
        for event in events:
            self.assertEqual(event["change_type"], "lifecycle_update")
            self.assertEqual(
                event["official_source_url"],
                "https://ai.google.dev/gemini-api/docs/deprecations",
            )
            self.assertEqual(
                event["announcement_url"],
                "https://ai.google.dev/gemini-api/docs/changelog",
            )
            self.assertEqual(event["source_snapshot_before"], "data/snapshots/2026-10-09/prices.json")
            self.assertEqual(event["source_snapshot_after"], "data/snapshots/2026-10-13/prices.json")


if __name__ == "__main__":
    unittest.main()
