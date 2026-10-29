import io
import tempfile
import unittest
import urllib.error
from pathlib import Path

from scripts.check_hf_history_parity import HistoryDriftError, check_with_retry
from scripts.check_hf_production_parity import NetworkFailureError
from scripts.export_huggingface_history import HISTORY_HF_DIR
from scripts.publish_huggingface import (
    HISTORY_ARTIFACTS,
    HISTORY_COMMIT_PREFIX,
    ValidationFailure,
    publish_huggingface,
    read_remote_head,
    validate_history_artifacts,
)
from tests.test_publish_huggingface import git

ROOT = Path(__file__).resolve().parents[1]


class PublishPriceHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.remote = self.root / "history-remote.git"
        self.seed = self.root / "seed"
        self.source = self.root / "source"
        self.source.mkdir()
        git("init", "--bare", "--initial-branch=main", str(self.remote))
        git("init", "--initial-branch=main", str(self.seed))
        git("config", "user.name", "HF History Owner", cwd=self.seed)
        git("config", "user.email", "owner@example.test", cwd=self.seed)
        (self.seed / ".gitattributes").write_text("* -text\n", encoding="utf-8")
        (self.seed / "README.md").write_text("HF-only price history card\n", encoding="utf-8")
        for name in HISTORY_ARTIFACTS:
            (self.seed / name).write_bytes(f"{name} v1\n".encode())
            (self.source / name).write_bytes(f"{name} v1\n".encode())
        git("add", ".", cwd=self.seed)
        git("commit", "-m", "initial history", cwd=self.seed)
        git("remote", "add", "origin", str(self.remote), cwd=self.seed)
        git("push", "-u", "origin", "main", cwd=self.seed)

    def tearDown(self):
        self.temp_dir.cleanup()

    def publish(self):
        output = io.StringIO()
        result = publish_huggingface(
            source_dir=self.source,
            repo_url=str(self.remote),
            token="unit-test-token",
            source_sha="72bed39aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            output=output,
            validate_source=lambda _path: None,
            remote_head_reader=read_remote_head,
            artifacts=HISTORY_ARTIFACTS,
            metadata_only_change=lambda _source, _clone: False,
            commit_prefix=HISTORY_COMMIT_PREFIX,
        )
        return result, output.getvalue()

    def test_in_sync_history_is_a_no_op(self):
        before = git("--git-dir", str(self.remote), "rev-parse", "refs/heads/main").strip()
        result, output = self.publish()
        self.assertEqual(result.status, "HF_ALREADY_IN_SYNC")
        self.assertIn("HF_ALREADY_IN_SYNC", output)
        self.assertEqual(git("--git-dir", str(self.remote), "rev-parse", "refs/heads/main").strip(), before)

    def test_pushes_only_the_history_csvs_and_keeps_the_card(self):
        (self.source / "price_snapshots.csv").write_bytes(b"price_snapshots.csv v2\n")
        result, output = self.publish()
        self.assertEqual(result.status, "HF_PUSHED")
        self.assertEqual(result.changed_files, ("price_snapshots.csv",))
        self.assertIn("HF_PUSHED: ", output)
        changed = git(
            "--git-dir", str(self.remote), "diff-tree", "--no-commit-id", "--name-only", "-r", "refs/heads/main"
        ).split()
        self.assertEqual(changed, ["price_snapshots.csv"])
        subject = git("--git-dir", str(self.remote), "log", "-1", "--format=%s", "refs/heads/main").strip()
        self.assertEqual(subject, "data: publish price history from GitHub 72bed39")
        card = git("--git-dir", str(self.remote), "show", "refs/heads/main:README.md")
        self.assertEqual(card, "HF-only price history card\n")

    def test_missing_source_csv_is_rejected(self):
        (self.source / "price_changes.csv").unlink()
        with self.assertRaises(ValidationFailure):
            self.publish()


class PriceHistorySourceValidationTests(unittest.TestCase):
    def test_committed_history_is_valid(self):
        validate_history_artifacts()

    def test_stale_history_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir)
            for name in HISTORY_ARTIFACTS:
                (source / name).write_bytes((HISTORY_HF_DIR / name).read_bytes())
            (source / "price_changes.csv").write_text("stale\n", encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "price_changes.csv"):
                validate_history_artifacts(source)


class PriceHistoryParityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.expected = Path(self.temp_dir.name)
        for name in HISTORY_ARTIFACTS:
            (self.expected / name).write_bytes(f"{name}\nrow\n".encode())

    def tearDown(self):
        self.temp_dir.cleanup()

    def check(self, fetch, attempts=1):
        output = io.StringIO()
        try:
            check_with_retry(
                expected_dir=self.expected,
                base_url="https://example.test/resolve/main",
                attempts=attempts,
                fetch_bytes=fetch,
                sleep=lambda _s: None,
                output=output,
            )
        finally:
            self.output = output.getvalue()

    def test_identical_files_pass_even_with_crlf(self):
        self.check(lambda url, _t: (self.expected / url.split("/")[-1].split("?")[0]).read_bytes().replace(b"\n", b"\r\n"))
        self.assertIn("HISTORY_PARITY: PASS", self.output)

    def test_changed_or_missing_file_is_drift(self):
        def fetch(url, _timeout):
            if "price_changes.csv" in url:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            return b"different\n"

        with self.assertRaises(HistoryDriftError) as caught:
            self.check(fetch, attempts=2)
        self.assertEqual(caught.exception.files, ["price_snapshots.csv", "price_changes.csv"])
        self.assertIn("\nDATA_DRIFT\n", self.output)

    def test_network_failure_is_not_drift(self):
        def fetch(_url, _timeout):
            raise urllib.error.URLError("offline")

        with self.assertRaises(NetworkFailureError):
            self.check(fetch)
        self.assertNotIn("DATA_DRIFT", self.output)


class PriceHistoryWorkflowTests(unittest.TestCase):
    def test_history_is_published_after_pricing_parity_from_committed_data(self):
        workflow = (ROOT / ".github/workflows/publish-huggingface.yml").read_text(encoding="utf-8")
        order = [
            "python scripts/check_hf_production_parity.py",
            "git checkout -- data",
            "python scripts/publish_huggingface.py --target history",
            "python scripts/check_hf_history_parity.py",
        ]
        positions = [workflow.index(marker) for marker in order]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("python scripts/publish_huggingface.py --target history --dry-run", workflow)
        self.assertNotIn("continue-on-error", workflow)

    def test_contract_republish_watches_and_compares_the_history(self):
        workflow = (ROOT / ".github/workflows/hf-contract-republish.yml").read_text(encoding="utf-8")
        self.assertIn('      - "huggingface-history/**"', workflow)
        self.assertIn("python scripts/check_hf_history_parity.py", workflow)
        self.assertIn("grep -q '^DATA_DRIFT$' parity.log", workflow)


if __name__ == "__main__":
    unittest.main()
