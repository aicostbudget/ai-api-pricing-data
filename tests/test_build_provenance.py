import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build import build_outputs, source_commit_sha

EXPECTED_SHA = "c" * 40


class BuildProvenanceTests(unittest.TestCase):
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
