import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import prepare_pages_artifact as pages
from scripts.prepare_pages_artifact import copy_public_pages


class PagesArtifactTests(unittest.TestCase):
    def test_all_pages_files_equal_committed_git_blobs(self):
        paths = subprocess.check_output(["git", "-C", str(pages.ROOT), "ls-tree", "-r", "--name-only", "HEAD", "--", "api"]).decode().splitlines()
        expected = {
            path: subprocess.check_output(["git", "-C", str(pages.ROOT), "show", f"HEAD:{path}"])
            for path in paths
        }
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "pages"
            summary = copy_public_pages(output)
            self.assertEqual({path.relative_to(output).as_posix(): path.read_bytes() for path in output.rglob("*") if path.is_file()}, expected)
            self.assertEqual(summary["source_sha"], json.loads(expected["api/v1/meta.json"])["source_commit_sha"])
            self.assertNotEqual(summary["source_sha"], summary["artifact_sha"])

    def test_uncommitted_api_changes_do_not_enter_pages_artifact(self):
        original_root = pages.ROOT
        expected = pages.committed_pages()[0]

        def committed_git(*args):
            return subprocess.check_output(["git", "-C", str(original_root), *args])

        original_run = subprocess.run

        def committed_run(command, **kwargs):
            command = list(command)
            if command[:2] == ["git", "-C"]:
                command[2] = str(original_root)
            return original_run(command, **kwargs)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "checkout"
            (root / "api/v1").mkdir(parents=True)
            (root / "api/v1/meta.json").write_bytes(b'"regenerated metadata"')
            (root / "api/v1/untracked-secret.json").write_bytes(b'"untracked"')
            with patch.object(pages, "ROOT", root), patch.object(pages, "git_bytes", side_effect=committed_git), patch.object(pages.subprocess, "run", side_effect=committed_run):
                output = Path(temp) / "pages"
                copy_public_pages(output)
            self.assertEqual((output / "api/v1/meta.json").read_bytes(), expected["api/v1/meta.json"])
            self.assertFalse((output / "api/v1/untracked-secret.json").exists())

    def assert_bad_source_fails(self, source_sha, error):
        original = pages.git_bytes

        def changed_meta(*args):
            content = original(*args)
            if args[0] == "cat-file":
                try:
                    payload = json.loads(content)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return content
                if isinstance(payload, dict) and "source_commit_sha" in payload:
                    payload["source_commit_sha"] = source_sha
                    return json.dumps(payload).encode()
            return content

        with patch.object(pages, "git_bytes", side_effect=changed_meta), self.assertRaises(error):
            pages.committed_pages()

    def test_malformed_source_sha_fails(self):
        self.assert_bad_source_fails("not-a-sha", ValueError)

    def test_source_sha_cannot_equal_artifact_sha(self):
        artifact = pages.git_bytes("rev-parse", "HEAD").decode().strip()
        self.assert_bad_source_fails(artifact, ValueError)

    def test_nonexistent_source_commit_fails(self):
        self.assert_bad_source_fails("0" * 40, subprocess.CalledProcessError)

    def test_nonancestor_source_commit_fails(self):
        original_run = subprocess.run

        def reject_ancestry(command, **kwargs):
            if "merge-base" in command:
                return subprocess.CompletedProcess(command, 1, b"", b"")
            return original_run(command, **kwargs)

        with patch.object(pages.subprocess, "run", side_effect=reject_ancestry), self.assertRaisesRegex(ValueError, "not an ancestor"):
            pages.committed_pages()

    def test_snapshot_byte_drift_fails(self):
        original = pages.git_bytes

        def changed_snapshot(*args):
            content = original(*args)
            if args[0] == "show" and ":data/snapshots/" in args[1]:
                return content + b"\n"
            return content

        with patch.object(pages, "git_bytes", side_effect=changed_snapshot), self.assertRaisesRegex(ValueError, "snapshot differ"):
            pages.committed_pages()

    def test_workflow_deploys_committed_artifact_with_separate_source_sha(self):
        workflow = (pages.ROOT / ".github/workflows/deploy-pages.yml").read_text()
        self.assertIn('branches: ["main", "master"]', workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("scripts/build.py", workflow)
        self.assertNotIn("SOURCE_COMMIT_SHA:", workflow)
        self.assertEqual(workflow.count("fetch-depth: 0"), 5)
        self.assertIn("needs: [build, release-preflight]", workflow)
        self.assertIn("python -m unittest discover", workflow)
        self.assertIn("python scripts/check_release_gate.py --kind pages", workflow)
        self.assertIn("python scripts/validate.py", workflow)
        self.assertIn('pages-dist --artifact-sha "${{ github.sha }}"', workflow)
        self.assertIn("source_sha: ${{ steps.artifact.outputs.source_sha }}", workflow)
        self.assertIn('--expected-source-sha "${{ needs.build.outputs.source_sha }}" --artifact-sha "${{ github.sha }}"', workflow)

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
