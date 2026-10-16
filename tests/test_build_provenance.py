import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.build import build_outputs, source_commit_sha
from scripts.daily_pricing_release import ensure_snapshot
from scripts.lib import ROOT, append_history_if_changed, write_json

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

    def test_same_day_lf_snapshot_remains_byte_identical(self):
        generated_at = "2026-10-15T10:15:09Z"
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"SOURCE_COMMIT_SHA": EXPECTED_SHA}
        ):
            output = Path(temp_dir)
            snapshot = output / "data/snapshots/2026-10-15"
            snapshot.mkdir(parents=True)
            for name in ("prices.json", "prices.csv"):
                shutil.copyfile(ROOT / "data/snapshots/2026-10-15" / name, snapshot / name)
            before = {name: hashlib.sha256((snapshot / name).read_bytes()).hexdigest() for name in ("prices.json", "prices.csv")}

            build_outputs(output, generated_at)
            self.assertEqual(ensure_snapshot(output, generated_at), "2026-10-15")
            after = {name: hashlib.sha256((snapshot / name).read_bytes()).hexdigest() for name in ("prices.json", "prices.csv")}

            self.assertEqual(before, after)
            self.assertEqual(before["prices.json"], "7594ed948772905f4438ba086dc377dc54c98e153506fb59feded542a3f0af2d")
            self.assertEqual(before["prices.csv"], "17c6cc40e44eb4b31aac0f956d4c04413d8141219417fe69d4af23e45dfee0da")
            for path in (output / "api/v1/prices.json", output / "api/v1/meta.json", output / "data/prices.json", output / "api/v1/prices.csv"):
                self.assertNotIn(b"\r", path.read_bytes())

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
