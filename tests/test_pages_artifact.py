import json
import tempfile
import unittest
from pathlib import Path

from scripts import prepare_pages_artifact as pages


SHA = "a" * 40


class PagesArtifactTests(unittest.TestCase):
    def fixture(self, root: Path, source_sha=SHA):
        (root / "api/v1/providers").mkdir(parents=True)
        (root / "api/v1/models").mkdir(parents=True)
        (root / "data/snapshots/2026-10-18").mkdir(parents=True)
        prices = json.dumps({"models": []}).encode()
        csv = b"provider_id,model_id\n"
        (root / "api/v1/meta.json").write_text(json.dumps({"source_commit_sha": source_sha, "generated_at": "2026-10-18T00:00:00Z"}), encoding="utf-8")
        (root / "api/v1/prices.json").write_bytes(prices)
        (root / "api/v1/prices.csv").write_bytes(csv)
        (root / "api/v1/providers/deepseek.json").write_text("{}", encoding="utf-8")
        (root / "api/v1/models/deepseek-flash.json").write_text("{}", encoding="utf-8")
        (root / "data/snapshots/2026-10-18/prices.json").write_bytes(prices)
        (root / "data/snapshots/2026-10-18/prices.csv").write_bytes(csv)

    def test_single_approved_revision_prepares_exact_generated_api(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            output = Path(temp) / "pages"
            self.fixture(root)
            summary = pages.copy_public_pages(output, SHA, root)
            self.assertEqual(summary["release_sha"], SHA)
            self.assertEqual(summary["topLevel"], ["api"])
            self.assertEqual((output / "api/v1/prices.json").read_bytes(), (root / "api/v1/prices.json").read_bytes())

    def test_release_revision_must_match_public_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            self.fixture(root, "b" * 40)
            with self.assertRaisesRegex(ValueError, "approved release SHA"):
                pages.workspace_pages(root, SHA)

    def test_malformed_release_revision_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            self.fixture(root, "bad")
            with self.assertRaisesRegex(ValueError, "full lowercase Git SHA"):
                pages.workspace_pages(root, "bad")

    def test_snapshot_byte_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            self.fixture(root)
            (root / "data/snapshots/2026-10-18/prices.json").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "snapshot differ"):
                pages.workspace_pages(root, SHA)

    def test_pages_artifact_contains_only_allowlisted_api(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            output = Path(temp) / "pages"
            self.fixture(root)
            (root / "scripts").mkdir()
            (root / "scripts/secret.py").write_text("secret", encoding="utf-8")
            manifest = pages.copy_public_pages(output, SHA, root)
            self.assertTrue(all(path.startswith("api/") for path in manifest["files"]))
            self.assertFalse((output / "scripts").exists())

    def test_workflow_builds_once_and_deploys_single_revision(self):
        workflow = (pages.ROOT / ".github/workflows/deploy-pages.yml").read_text(encoding="utf-8")
        self.assertIn('branches: ["main"]', workflow)
        self.assertEqual(workflow.count("python scripts/build.py"), 1)
        self.assertIn("SOURCE_COMMIT_SHA:", workflow)
        self.assertIn("prepare_pages_artifact.py pages-dist --release-sha", workflow)
        self.assertIn("verify_pages_deployment.py --release-sha", workflow)
        self.assertIn("actions/deploy-pages@v5", workflow)
        self.assertNotIn("release_plan_id", workflow)
        self.assertNotIn("release_plan_digest", workflow)


if __name__ == "__main__":
    unittest.main()
