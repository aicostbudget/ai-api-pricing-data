import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts import public_release_identity as identity

SOURCE = "a" * 40
RELEASE = "b" * 40
GENERATED_AT = "2026-11-23T14:56:38Z"
CANONICAL = b'{"models":[]}\n'


def fake_reader(meta=None, source_canonical=CANONICAL, release_canonical=CANONICAL):
    meta = {"source_commit_sha": SOURCE, "generated_at": GENERATED_AT} if meta is None else meta

    def read_blob(revision, path):
        if path == identity.META_PATH and revision == RELEASE:
            return json.dumps(meta).encode("utf-8")
        if path == identity.SOURCE_PATH:
            return source_canonical if revision == SOURCE else release_canonical
        raise subprocess.CalledProcessError(128, ["git", "show"])

    return read_blob


class ResolvePublicIdentityTests(unittest.TestCase):
    def test_reads_the_source_sha_and_generated_at_from_the_committed_meta(self):
        result = identity.resolve_public_identity(RELEASE, fake_reader(), lambda before, after: (before, after) == (SOURCE, RELEASE))
        self.assertEqual(result, {"release_sha": SOURCE, "generated_at": GENERATED_AT})

    def test_pushed_revision_is_never_the_answer(self):
        result = identity.resolve_public_identity(RELEASE, fake_reader(), lambda *_: True)
        self.assertNotEqual(result["release_sha"], RELEASE)

    def test_rejects_a_malformed_source_sha_or_timestamp(self):
        for meta, message in (
            ({"generated_at": GENERATED_AT}, "source_commit_sha"),
            ({"source_commit_sha": "A" * 40, "generated_at": GENERATED_AT}, "source_commit_sha"),
            ({"source_commit_sha": SOURCE[:7], "generated_at": GENERATED_AT}, "source_commit_sha"),
            ({"source_commit_sha": SOURCE}, "generated_at"),
            ({"source_commit_sha": SOURCE, "generated_at": "2026-11-23T14:56:38+08:00"}, "generated_at"),
        ):
            with self.subTest(meta=meta), self.assertRaisesRegex(identity.IdentityError, message):
                identity.resolve_public_identity(RELEASE, fake_reader(meta), lambda *_: True)

    def test_rejects_a_source_commit_that_is_not_an_ancestor(self):
        with self.assertRaisesRegex(identity.IdentityError, "not an ancestor"):
            identity.resolve_public_identity(RELEASE, fake_reader(), lambda *_: False)

    def test_rejects_a_missing_source_commit(self):
        def missing(before, after):
            raise subprocess.CalledProcessError(128, ["git", "merge-base"])

        with self.assertRaisesRegex(identity.IdentityError, "not in this checkout"):
            identity.resolve_public_identity(RELEASE, fake_reader(), missing)

    def test_rejects_an_artifact_commit_that_changed_the_canonical_data(self):
        reader = fake_reader(release_canonical=b'{"models":[{"model_id":"x"}]}\n')
        with self.assertRaisesRegex(identity.IdentityError, "altered authoritative source facts"):
            identity.resolve_public_identity(RELEASE, reader, lambda *_: True)

    def test_rejects_unreadable_meta(self):
        def broken(revision, path):
            return b"not json"

        with self.assertRaisesRegex(identity.IdentityError, "cannot be read as JSON"):
            identity.resolve_public_identity(RELEASE, broken, lambda *_: True)


class RebuildMatchTests(unittest.TestCase):
    def test_clean_status_passes(self):
        identity.assert_rebuild_matches_committed([])
        identity.assert_rebuild_matches_committed(["", "  "])

    def test_any_difference_fails_and_is_listed(self):
        with self.assertRaisesRegex(identity.IdentityError, r"\(2 differ\)") as caught:
            identity.assert_rebuild_matches_committed([" M api/v1/meta.json", "?? data/history/new.jsonl"])
        self.assertIn("api/v1/meta.json", str(caught.exception))
        self.assertIn("data/history/new.jsonl", str(caught.exception))

    def test_a_long_list_is_truncated(self):
        lines = [f" M data/models/m{index}.json" for index in range(identity.MAX_LISTED_DIFFERENCES + 5)]
        with self.assertRaisesRegex(identity.IdentityError, r"and 5 more"):
            identity.assert_rebuild_matches_committed(lines)


class CommandLineTests(unittest.TestCase):
    """The command line against a real two-commit repository: source commit, then artifact commit."""

    def git(self, root, *args):
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
        return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env).stdout.decode().strip()

    def make_repository(self, root, meta_names_source=True, change_canonical=False):
        self.git(root, "init", "-q")
        (root / "data/canonical").mkdir(parents=True)
        (root / "data/canonical/models.json").write_bytes(CANONICAL)
        self.git(root, "add", "-A")
        self.git(root, "commit", "-q", "-m", "data: prepare pricing source")
        source = self.git(root, "rev-parse", "HEAD")
        (root / "api/v1").mkdir(parents=True)
        named = source if meta_names_source else "c" * 40
        (root / "api/v1/meta.json").write_text(json.dumps({"source_commit_sha": named, "generated_at": GENERATED_AT}), encoding="utf-8")
        if change_canonical:
            (root / "data/canonical/models.json").write_bytes(b'{"models":[1]}\n')
        self.git(root, "add", "-A")
        self.git(root, "commit", "-q", "-m", "data: publish pricing artifacts")
        return source

    def run_cli(self, root, *argv):
        environment = {key: value for key, value in os.environ.items() if key != "GITHUB_OUTPUT"}
        out, err = StringIO(), StringIO()
        with patch.object(identity, "ROOT", root), patch.dict(os.environ, environment, clear=True), redirect_stdout(out), redirect_stderr(err):
            code = identity.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_resolve_prints_the_source_commit_not_the_head(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.make_repository(root)
            head = self.git(root, "rev-parse", "HEAD")
            code, out, err = self.run_cli(root, "resolve")
            self.assertEqual((code, err), (0, ""))
            self.assertIn(f"release_sha={source}", out)
            self.assertNotIn(head, out)
            self.assertIn(f"generated_at={GENERATED_AT}", out)

    def test_resolve_writes_the_github_output_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            root.mkdir()
            source = self.make_repository(root)
            output = Path(temp) / "github-output"
            with patch.object(identity, "ROOT", root), patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}), redirect_stdout(StringIO()):
                self.assertEqual(identity.main(["resolve"]), 0)
            self.assertEqual(output.read_text(encoding="utf-8").splitlines(), [f"release_sha={source}", f"generated_at={GENERATED_AT}"])

    def test_resolve_fails_when_meta_names_a_commit_that_is_not_in_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_repository(root, meta_names_source=False)
            code, _, err = self.run_cli(root, "resolve")
            self.assertEqual(code, 1)
            self.assertIn("not in this checkout", err)

    def test_resolve_fails_when_the_artifact_commit_changed_canonical_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_repository(root, change_canonical=True)
            code, _, err = self.run_cli(root, "resolve")
            self.assertEqual(code, 1)
            self.assertIn("altered authoritative source facts", err)

    def test_check_rebuild_passes_on_a_clean_tree_and_fails_on_any_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_repository(root)
            self.assertEqual(self.run_cli(root, "check-rebuild")[0], 0)
            (root / "api/v1/meta.json").write_text("{}", encoding="utf-8")
            code, _, err = self.run_cli(root, "check-rebuild")
            self.assertEqual(code, 1)
            self.assertIn("api/v1/meta.json", err)
            self.git(root, "checkout", "--", "api")
            (root / "data/history").mkdir()
            (root / "data/history/new.jsonl").write_text("{}\n", encoding="utf-8")
            code, _, err = self.run_cli(root, "check-rebuild")
            self.assertEqual(code, 1)
            self.assertIn("data/history/new.jsonl", err)


class WorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (identity.ROOT / ".github/workflows/deploy-pages.yml").read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()

    def test_public_identity_comes_from_the_committed_meta_not_the_pushed_commit(self):
        for line in self.lines:
            if "SOURCE_COMMIT_SHA:" in line or "--release-sha" in line:
                self.assertNotIn("github.sha", line, line)
                self.assertIn("steps.identity.outputs.release_sha", line)
                self.assertIn("inputs.recovery_source_sha", line)

    def test_identity_is_resolved_before_the_build_and_the_rebuild_is_checked_before_publishing(self):
        positions = {name: self.text.index(name) for name in (
            "public_release_identity.py resolve",
            "python scripts/build.py",
            "public_release_identity.py check-rebuild",
            "prepare_pages_artifact.py",
            "actions/deploy-pages@v5",
        )}
        self.assertEqual(list(positions.values()), sorted(positions.values()))

    def test_the_build_uses_the_committed_generated_at(self):
        self.assertIn("PUBLIC_GENERATED_AT: ${{ steps.identity.outputs.generated_at }}", self.text)
        self.assertIn('--generated-at "$PUBLIC_GENERATED_AT"', self.text)

    def test_recovery_keeps_its_explicit_identity_and_skips_the_new_steps(self):
        for command in ("public_release_identity.py resolve", "public_release_identity.py check-rebuild"):
            index = self.lines.index(next(line for line in self.lines if command in line))
            step = "\n".join(self.lines[max(0, index - 4): index + 1])
            self.assertIn("if: ${{ !inputs.recovery_mode }}", step, command)


if __name__ == "__main__":
    unittest.main()
