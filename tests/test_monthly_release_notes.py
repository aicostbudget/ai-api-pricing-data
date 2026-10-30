import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import monthly_release_notes as notes

ROOT = Path(__file__).resolve().parents[1]
DATASET = {
    "model_count": 3, "provider_count": 2, "last_verified_at": "2026-10-30T08:35:21Z",
    "models": [
        {"provider_id": "openai", "model_id": "gpt-6-sol", "display_name": "GPT-6 Sol"},
        {"provider_id": "openai", "model_id": "gpt-5.6-sol", "display_name": "GPT-5.6 Sol"},
        {"provider_id": "google-gemini", "model_id": "flash-tts", "display_name": "Flash TTS"},
    ],
}


def event(provider, model, kind, day, **fields):
    return {"provider_id": provider, "model_id": model, "change_type": kind, "detected_at": day,
            "official_source_url": "https://example.com/pricing", **fields}


class MonthlyReleaseNotesTests(unittest.TestCase):
    def render(self, events):
        return notes.render("2026-10", events, DATASET, "2026-10-30-4")

    def test_sections_counts_and_formatting(self):
        text = self.render([
            event("google-gemini", "flash-tts", "cached_price_removed", "2026-10-25",
                  old_prices={"input": 0.5, "cached_input": 0.125, "output": None},
                  new_prices={"input": 0.5, "cached_input": None, "output": None}),
            event("openai", "gpt-6-sol", "model_added", "2026-10-27", new_prices={"input": 1, "output": 5}),
            event("openai", "gpt-6-sol", "successor_transition", "2026-10-27", predecessor_model_id="gpt-5.6-sol"),
            event("openai", "gpt-5.6-sol", "lifecycle_update", "2026-10-05", old_status="active", new_status="deprecated",
                  new_lifecycle={"deprecation_date": "2026-10-01", "retirement_date": "2027-04-01", "replacement_model_id": "gpt-6-sol"}),
        ])
        self.assertIn("## AI API prices in October 2026", text)
        self.assertIn("4 changes across 2 providers", text)
        self.assertIn("cached input $0.125 → none", text)
        self.assertIn("| GPT-6 Sol | $1.00 / $5.00 |", text)
        self.assertIn("replaces GPT-5.6 Sol", text)
        self.assertIn("active → deprecated, deprecated 2026-10-01, retires 2027-04-01, replacement GPT-6 Sol", text)
        self.assertIn("[Google Gemini](https://aicostbudget.com/en/providers/google-gemini-api-pricing?", text)
        self.assertIn("utm_content=release_2026-10", text)
        self.assertIn("Snapshot `2026-10-30-4`: 3 models from 2 providers, last verified 2026-10-30.", text)

    def test_unchanged_status_is_not_repeated(self):
        text = self.render([event("openai", "gpt-5.6-sol", "lifecycle_update", "2026-10-05",
                                  old_status="deprecated", new_status="deprecated", new_lifecycle={})])
        self.assertIn("| deprecated |", text)
        self.assertNotIn("deprecated → deprecated", text)

    def test_month_filter_and_empty_month_exit_code(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "data/price-change-events").mkdir(parents=True)
            (root / notes.EVENTS).write_text(json.dumps(event("openai", "gpt-6-sol", "model_added", "2026-09-30")) + "\n", encoding="utf-8")
            self.assertEqual(notes.load_events(root, "2026-10"), [])
            self.assertEqual(len(notes.load_events(root, "2026-09")), 1)
            script = [sys.executable, str(ROOT / "scripts/monthly_release_notes.py"), "--root", str(root), "--snapshot", "x", "--check"]
            self.assertEqual(subprocess.run([*script, "--month", "2026-10"], capture_output=True).returncode, notes.NO_EVENTS)
            self.assertEqual(subprocess.run([*script, "--month", "2026-09"], capture_output=True).returncode, 0)

    def test_workflow_is_monthly_bundled_and_dry_run_by_default(self):
        workflow = (ROOT / ".github/workflows/monthly-release.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "0 9 1 * *"', workflow)
        self.assertIn("scripts/build_release_bundle.py", workflow)
        self.assertIn("scripts/monthly_release_notes.py", workflow)
        self.assertIn('tag="dataset-${month}"', workflow)
        self.assertIn("github.event_name == 'schedule' || inputs.dry_run == false", workflow)
        dry_run = workflow.split("dry_run:", 1)[1].split("permissions:", 1)[0]
        self.assertIn("default: true", dry_run)


if __name__ == "__main__":
    unittest.main()
