import csv
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.lib import (
    DATA,
    ROOT,
    append_history_if_changed,
    build_dataset,
    csv_rows,
    history_entry,
    comparable_history,
    load_models,
    load_providers,
    utc_now,
    utc_today,
)


def copy_build_fixture(output_root: Path) -> Path:
    output_data = output_root / "data"
    output_data.mkdir(parents=True)
    for filename in ("prices.json", "prices.csv"):
        shutil.copy2(DATA / filename, output_data / filename)
    for dirname in ("history", "snapshots"):
        shutil.copytree(DATA / dirname, output_data / dirname)
    return output_data


def run_isolated_build(output_root: Path) -> None:
    subprocess.run(
        [sys.executable, "scripts/build.py", "--output-root", str(output_root)],
        cwd=ROOT,
        check=True,
    )


class DatasetTests(unittest.TestCase):
    def test_counts_and_duplicates(self):
        providers = load_providers()
        models = load_models()
        self.assertEqual(len({item["provider_id"] for item in providers}), len(providers))
        self.assertEqual(len({(item["provider_id"], item["model_id"]) for item in models}), len(models))
        self.assertEqual(len(providers), 7)
        self.assertEqual(len(models), 25)

    def test_verified_additions_and_price_corrections(self):
        by_key = {(model["provider_id"], model["model_id"]): model for model in load_models()}
        expected = {
            ("google-gemini", "gemini-3.6-flash"): (1.5, 0.15, 7.5, 0.75, 3.75, None),
            ("google-gemini", "gemini-3.5-flash-lite"): (0.3, 0.03, 2.5, 0.15, 1.25, None),
            ("xai", "grok-4.5"): (2.0, 0.3, 6.0, None, None, None),
        }
        for key, values in expected.items():
            row = by_key[key]
            self.assertEqual(
                (
                    row["pricing"]["input"],
                    row["pricing"]["cached_input"],
                    row["pricing"]["output"],
                    row["pricing"]["batch_input"],
                    row["pricing"]["batch_output"],
                    row["effective_from"],
                ),
                values,
            )
            self.assertEqual(row["last_verified_at"], "2026-08-08T18:00:00Z")

        self.assertEqual(
            tuple(by_key[("openai", "gpt-5.6-terra")]["pricing"][field] for field in ("input", "cached_input", "output")),
            (2.0, 0.2, 12.0),
        )
        self.assertEqual(
            tuple(by_key[("openai", "gpt-5.6-luna")]["pricing"][field] for field in ("input", "cached_input", "output")),
            (0.2, 0.02, 1.2),
        )
        self.assertIsNone(by_key[("openai", "gpt-5.6-terra")]["effective_from"])
        self.assertIsNone(by_key[("openai", "gpt-5.6-luna")]["effective_from"])

    def test_no_negative_prices_and_sources(self):
        for model in load_models():
            self.assertTrue(model["official_source_url"].startswith("https://"))
            for value in model["pricing"].values():
                if isinstance(value, (int, float)):
                    self.assertGreaterEqual(value, 0)

    def test_claude_opus_5_public_v1_record_is_present(self):
        by_key = {(model["provider_id"], model["model_id"]): model for model in load_models()}
        opus5 = by_key[("anthropic", "claude-opus-5")]
        opus48 = by_key[("anthropic", "claude-opus-4.8")]
        self.assertEqual(opus5["display_name"], "Claude Opus 5")
        self.assertEqual(opus5["status"], "active")
        self.assertEqual(opus5["effective_from"], "2026-07-24")
        self.assertEqual(opus5["pricing"]["input"], 5.0)
        self.assertEqual(opus5["pricing"]["output"], 25.0)
        self.assertEqual(opus5["pricing"]["cached_input"], 0.5)
        self.assertEqual(opus5["pricing"]["cache_write"], 6.25)
        self.assertEqual(opus5["pricing"]["cache_write_1h"], 10.0)
        self.assertEqual(opus5["pricing"]["batch_input"], 2.5)
        self.assertEqual(opus5["pricing"]["batch_output"], 12.5)
        self.assertEqual(opus48["display_name"], "Claude Opus 4.8")
        self.assertEqual(opus48["status"], "active")

    def test_json_csv_consistency(self):
        dataset = json.loads((DATA / "prices.json").read_text(encoding="utf-8"))
        self.assertEqual(dataset, build_dataset(dataset["generated_at"]))
        with (DATA / "prices.csv").open(encoding="utf-8", newline="") as handle:
            actual_rows = list(csv.DictReader(handle))
        expected_rows = [{k: "" if v is None else str(v) for k, v in row.items()} for row in csv_rows(load_models())]
        self.assertEqual(actual_rows, expected_rows)

    def test_generated_at_is_real_utc_and_consistent(self):
        dataset = json.loads((DATA / "prices.json").read_text(encoding="utf-8"))
        meta = json.loads((ROOT / "api" / "v1" / "meta.json").read_text(encoding="utf-8"))
        generated_at = dataset["generated_at"]
        self.assertEqual(generated_at, meta["generated_at"])
        self.assertNotEqual(generated_at, "1970-01-01T00:00:00Z")
        self.assertRegex(generated_at, re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"))
        parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        self.assertIsNotNone(parsed.tzinfo)
        latest_verified_at = max(
            datetime.fromisoformat(model["last_verified_at"].replace("Z", "+00:00"))
            for model in load_models()
        )
        self.assertGreaterEqual(parsed, latest_verified_at)

    def test_verification_timestamps_are_not_in_the_future(self):
        now = datetime.now(timezone.utc)
        for model in load_models():
            for field in ("accessed_at", "last_verified_at"):
                parsed = datetime.fromisoformat(model[field].replace("Z", "+00:00"))
                self.assertLessEqual(parsed, now, f"{model['provider_id']}/{model['model_id']} {field}")

    def test_api_outputs_parse(self):
        json.loads((ROOT / "api" / "v1" / "prices.json").read_text(encoding="utf-8"))
        json.loads((ROOT / "api" / "v1" / "meta.json").read_text(encoding="utf-8"))
        self.assertTrue((ROOT / "api" / "v1" / "prices.csv").exists())

    def test_build_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            output_data = copy_build_fixture(output_root)
            before = json.loads((output_data / "prices.json").read_text(encoding="utf-8"))
            run_isolated_build(output_root)
            after = json.loads((output_data / "prices.json").read_text(encoding="utf-8"))
            before["generated_at"] = after["generated_at"]
            self.assertEqual(before, after)

    def test_build_twice_preserves_history_without_duplicate_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            output_data = copy_build_fixture(output_root)

            def line_counts() -> dict[str, int]:
                return {
                    str(path.relative_to(output_data)): len(path.read_text(encoding="utf-8").splitlines())
                    for path in sorted((output_data / "history").glob("*/*.jsonl"))
                }

            before = line_counts()
            run_isolated_build(output_root)
            after_first = line_counts()
            run_isolated_build(output_root)
            after_second = line_counts()
            self.assertTrue(before)
            self.assertEqual(after_first, after_second)
            for key, count in before.items():
                self.assertGreaterEqual(after_first[key], count)

    def test_history_records_are_valid_jsonl_with_required_fields(self):
        required = {
            "recorded_at",
            "provider_id",
            "model_id",
            "pricing",
            "official_source_url",
            "effective_from",
            "last_verified_at",
            "notes",
        }
        history_paths = sorted((DATA / "history").glob("*/*.jsonl"))
        self.assertTrue(history_paths)
        for path in history_paths:
            for line in path.read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                self.assertFalse(required - record.keys(), path)

    def test_no_semantic_duplicate_history_entries(self):
        for path in sorted((DATA / "history").glob("*/*.jsonl")):
            seen = set()
            for line in path.read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                key = json.dumps(comparable_history(record), sort_keys=True)
                self.assertNotIn(key, seen, path)
                seen.add(key)

    def test_price_change_adds_history_entry(self):
        model = load_models()[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            first = history_entry(model, utc_now())
            self.assertTrue(append_history_if_changed(path, first))
            self.assertFalse(append_history_if_changed(path, history_entry(model, utc_now())))
            changed_model = json.loads(json.dumps(model))
            changed_model["pricing"]["input"] = 999999
            self.assertTrue(append_history_if_changed(path, history_entry(changed_model, utc_now())))
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 2)

    def test_build_preserves_old_snapshots_and_uses_utc_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            output_data = copy_build_fixture(output_root)
            old_snapshot = output_data / "snapshots" / "1999-12-31"
            marker = old_snapshot / "marker.txt"
            old_snapshot.mkdir(parents=True, exist_ok=True)
            marker.write_text("keep\n", encoding="utf-8")
            run_isolated_build(output_root)
            self.assertTrue(marker.exists())
            today_snapshot = output_data / "snapshots" / utc_today()
            self.assertTrue((today_snapshot / "prices.json").exists())
            self.assertTrue((today_snapshot / "prices.csv").exists())


if __name__ == "__main__":
    unittest.main()
