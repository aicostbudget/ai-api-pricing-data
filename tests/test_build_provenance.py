import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.build import build_outputs, resolve_snapshot_id, source_commit_sha
from scripts.lib import ROOT, append_history_if_changed, next_snapshot_id, snapshot_ids, write_json

EXPECTED_SHA = "c" * 40


class BuildProvenanceTests(unittest.TestCase):
    def test_write_json_uses_exact_utf8_lf_bytes(self):
        value = {"z": [1, 2], "a": "café"}
        expected = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            Path, "write_text", side_effect=AssertionError("write_json must use binary output")
        ):
            path = Path(temp_dir) / "nested" / "value.json"
            write_json(path, value)
            self.assertEqual(path.read_bytes(), expected)
            self.assertNotIn(b"\r", path.read_bytes())
            self.assertFalse(path.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_history_append_uses_exact_binary_line_and_deduplicates(self):
        entry = {"provider_id": "p", "model_id": "m", "pricing": {"input": 1}}
        expected = json.dumps(entry, sort_keys=True).encode("utf-8") + b"\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "history" / "m.jsonl"
            handle = MagicMock()
            context = MagicMock()
            context.__enter__.return_value = handle
            with patch.object(Path, "open", return_value=context) as open_mock:
                self.assertTrue(append_history_if_changed(path, entry))
            open_mock.assert_called_once_with("ab")
            handle.write.assert_called_once_with(expected)
            self.assertNotIn(b"\r", expected)
            self.assertFalse(expected.startswith(b"\xef\xbb\xbf"))

            path.write_bytes(expected)
            before = path.read_bytes()
            self.assertFalse(append_history_if_changed(path, entry))
            self.assertEqual(path.read_bytes(), before)

    def test_explicit_generated_at_controls_snapshot_date(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"SOURCE_COMMIT_SHA": EXPECTED_SHA}
        ), patch("scripts.build.utc_today", return_value="2099-12-31", create=True):
            output = Path(temp_dir)
            build_outputs(output, "2001-02-03T04:05:06Z")
            self.assertTrue((output / "data/snapshots/2001-02-03/prices.json").is_file())
            self.assertTrue((output / "data/snapshots/2001-02-03/prices.csv").is_file())
            self.assertFalse((output / "data/snapshots/2099-12-31").exists())

    def test_historical_2026_10_15_snapshot_sha256_is_unchanged(self):
        expected = {
            "prices.json": "7594ed948772905f4438ba086dc377dc54c98e153506fb59feded542a3f0af2d",
            "prices.csv": "17c6cc40e44eb4b31aac0f956d4c04413d8141219417fe69d4af23e45dfee0da",
        }
        snapshot = ROOT / "data/snapshots/2026-10-15"
        for name, expected_sha256 in expected.items():
            content = (snapshot / name).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), expected_sha256)
            content.decode("utf-8")
            self.assertNotIn(b"\r", content)
            self.assertFalse(content.startswith(b"\xef\xbb\xbf"))

    def test_current_build_is_byte_deterministic_with_explicit_generated_at(self):
        generated_at = "2026-10-15T10:15:09Z"
        relative_paths = (
            "api/v1/prices.json",
            "api/v1/prices.csv",
            "data/snapshots/2026-10-15/prices.json",
            "data/snapshots/2026-10-15/prices.csv",
        )
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir, patch.dict(
            os.environ, {"SOURCE_COMMIT_SHA": EXPECTED_SHA}
        ):
            first = Path(first_dir)
            second = Path(second_dir)
            build_outputs(first, generated_at)
            build_outputs(second, generated_at)

            first_bytes = {path: (first / path).read_bytes() for path in relative_paths}
            second_bytes = {path: (second / path).read_bytes() for path in relative_paths}
            self.assertEqual(first_bytes, second_bytes)
            self.assertEqual(first_bytes["api/v1/prices.json"], first_bytes["data/snapshots/2026-10-15/prices.json"])
            self.assertEqual(first_bytes["api/v1/prices.csv"], first_bytes["data/snapshots/2026-10-15/prices.csv"])
            self.assertEqual(sorted(path.name for path in (first / "data/snapshots").iterdir()), ["2026-10-15"])
            self.assertEqual(sorted(path.name for path in (second / "data/snapshots").iterdir()), ["2026-10-15"])
            for path, content in first_bytes.items():
                decoded = content.decode("utf-8")
                self.assertTrue(decoded)
                self.assertNotIn(b"\r", content, path)
                self.assertFalse(content.startswith(b"\xef\xbb\xbf"), path)
                self.assertTrue(content.endswith(b"\n"), path)
                if path.endswith(".json"):
                    json.loads(decoded)

    def test_same_day_release_writes_a_new_snapshot_and_never_rewrites_the_existing_one(self):
        generated_at = "2026-10-15T18:00:00Z"
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            existing = output / "data/snapshots/2026-10-15"
            existing.mkdir(parents=True)
            for name in ("prices.json", "prices.csv"):
                shutil.copyfile(ROOT / "data/snapshots/2026-10-15" / name, existing / name)
            before = {name: (existing / name).read_bytes() for name in ("prices.json", "prices.csv")}

            snapshot_id = next_snapshot_id(snapshot_ids(output / "data/snapshots"), generated_at[:10])
            self.assertEqual(snapshot_id, "2026-10-15-2")
            build_outputs(output, generated_at, snapshot_id)

            self.assertEqual(before, {name: (existing / name).read_bytes() for name in before})
            for name in ("prices.json", "prices.csv"):
                self.assertEqual((output / "data/snapshots/2026-10-15-2" / name).read_bytes(), (output / "api/v1" / name).read_bytes())

    def test_default_build_targets_the_latest_snapshot_of_the_day(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshots = Path(temp_dir)
            for name in ("2026-10-15", "2026-10-15-2"):
                (snapshots / name).mkdir()
            self.assertEqual(resolve_snapshot_id(snapshots, "2026-10-15", None), "2026-10-15-2")
            self.assertEqual(resolve_snapshot_id(snapshots, "2026-10-16", None), "2026-10-16")
            with self.assertRaisesRegex(ValueError, "does not match generated_at date"):
                resolve_snapshot_id(snapshots, "2026-10-16", "2026-10-15-3")

    def test_environment_sha_is_written_to_public_meta_only(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"SOURCE_COMMIT_SHA": EXPECTED_SHA}
        ):
            output = Path(temp_dir)
            build_outputs(output)
            meta = json.loads((output / "api/v1/meta.json").read_text(encoding="utf-8"))
            prices = json.loads((output / "api/v1/prices.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["source_commit_sha"], EXPECTED_SHA)
            self.assertNotIn("source_commit_sha", prices)
            self.assertTrue(all("source_commit_sha" not in model for model in prices["models"]))

    def test_invalid_environment_sha_is_rejected(self):
        with patch.dict(os.environ, {"SOURCE_COMMIT_SHA": "short"}):
            with self.assertRaisesRegex(ValueError, "40 lowercase hexadecimal"):
                source_commit_sha()


if __name__ == "__main__":
    unittest.main()
