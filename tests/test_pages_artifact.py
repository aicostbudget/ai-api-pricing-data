import tempfile
import unittest
from pathlib import Path

from scripts.prepare_pages_artifact import copy_public_pages


class PagesArtifactTests(unittest.TestCase):
    def test_pages_artifact_contains_only_public_api(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "pages-dist"
            manifest = copy_public_pages(output)
            files = set(manifest["files"])

            self.assertEqual(manifest["topLevel"], ["api"])
            self.assertIn("api/v1/prices.json", files)
            self.assertIn("api/v1/prices.csv", files)
            self.assertIn("api/v1/meta.json", files)
            self.assertTrue(any(path.startswith("api/v1/providers/") for path in files))
            self.assertTrue(any(path.startswith("api/v1/models/") for path in files))

            forbidden_prefixes = (
                ".git/",
                ".github/",
                "data/",
                "schema/",
                "scripts/",
                "tests/",
            )
            for path in files:
                self.assertFalse(path.startswith(forbidden_prefixes), path)

            self.assertNotIn("tests/fixtures/website-model-pricing.json", files)
            self.assertFalse(any("__pycache__" in path for path in files))
            self.assertFalse(any(path.startswith("data/pricing-v2-preview/") for path in files))


if __name__ == "__main__":
    unittest.main()
