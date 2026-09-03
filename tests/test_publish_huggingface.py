import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.publish_huggingface import (
    ALLOWED_ARTIFACTS,
    AuthFailure,
    NetworkFailure,
    PushFailure,
    RawGitError,
    RemoteChanged,
    UnexpectedHFChange,
    ValidationFailure,
    audit_changed_files,
    classify_git_error,
    clone_latest,
    git_auth_environment,
    publish_huggingface,
    push_fast_forward,
    read_remote_head,
    require_token,
    sanitize_error,
    validate_source_artifacts,
)


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "publish-huggingface.yml"


def git(*args, cwd=None):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout


class HuggingFaceSafePublishTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.remote = self.root / "hf-remote.git"
        self.seed = self.root / "seed"
        self.source = self.root / "source"
        self.source.mkdir()
        self.initial_artifacts = {
            "prices.json": b'{"version":"old"}\n',
            "prices.csv": b"model_id,price\nold,1\n",
            "train.csv": b"model_id,price\nold,1\n",
            "meta.json": b'{"version":"old"}\n',
        }
        self.write_source(self.initial_artifacts)
        self.init_remote(self.initial_artifacts)

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_source(self, artifacts):
        for name, content in artifacts.items():
            (self.source / name).write_bytes(content)

    def init_remote(self, artifacts):
        git("init", "--bare", "--initial-branch=main", str(self.remote))
        git("init", "--initial-branch=main", str(self.seed))
        git("config", "user.name", "HF History Owner", cwd=self.seed)
        git("config", "user.email", "owner@example.test", cwd=self.seed)
        (self.seed / ".gitattributes").write_text("* -text\n", encoding="utf-8")
        (self.seed / "README.md").write_text("HF-only dataset card\n", encoding="utf-8")
        for name, content in artifacts.items():
            (self.seed / name).write_bytes(content)
        git("add", ".", cwd=self.seed)
        git("commit", "-m", "HF independent history", cwd=self.seed)
        git("remote", "add", "origin", str(self.remote), cwd=self.seed)
        git("push", "-u", "origin", "main", cwd=self.seed)

    def publish(self, *, dry_run=False, source_sha="071deb28dbd8d39f53546511b645c0fdf3d7ad51", reader=read_remote_head, repo_url=None):
        output = io.StringIO()
        result = publish_huggingface(
            source_dir=self.source,
            repo_url=str(repo_url or self.remote),
            token="unit-test-token",
            source_sha=source_sha,
            dry_run=dry_run,
            output=output,
            validate_source=lambda _path: None,
            remote_head_reader=reader,
        )
        return result, output.getvalue()

    def remote_head(self):
        return git("--git-dir", str(self.remote), "rev-parse", "refs/heads/main").strip()

    def remote_changed_files(self):
        return set(
            filter(
                None,
                git(
                    "--git-dir",
                    str(self.remote),
                    "diff-tree",
                    "--no-commit-id",
                    "--name-only",
                    "-r",
                    "refs/heads/main",
                ).splitlines(),
            )
        )

    def clone_remote(self, name):
        destination = self.root / name
        git("clone", "--branch", "main", str(self.remote), str(destination))
        git("config", "user.name", "Test Writer", cwd=destination)
        git("config", "user.email", "writer@example.test", cwd=destination)
        return destination

    def init_remote_without_gitattributes(self):
        remote = self.root / "hf-remote-no-attributes.git"
        seed = self.root / "seed-no-attributes"
        git("init", "--bare", "--initial-branch=main", str(remote))
        git("init", "--initial-branch=main", str(seed))
        git("config", "core.autocrlf", "false", cwd=seed)
        git("config", "user.name", "HF History Owner", cwd=seed)
        git("config", "user.email", "owner@example.test", cwd=seed)
        (seed / "README.md").write_text("HF-only dataset card\n", encoding="utf-8", newline="\n")
        for name, content in self.initial_artifacts.items():
            (seed / name).write_bytes(content)
        git("add", ".", cwd=seed)
        git("commit", "-m", "HF independent history without attributes", cwd=seed)
        git("remote", "add", "origin", str(remote), cwd=seed)
        git("push", "-u", "origin", "main", cwd=seed)
        return remote

    def test_all_artifacts_in_sync_creates_no_commit(self):
        before = self.remote_head()
        result, output = self.publish()
        self.assertEqual(result.status, "HF_ALREADY_IN_SYNC")
        self.assertEqual(self.remote_head(), before)
        self.assertIn("HF_ALREADY_IN_SYNC", output)

    def test_clone_is_lf_deterministic_when_external_autocrlf_is_true(self):
        remote = self.init_remote_without_gitattributes()
        external_git_config = {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.autocrlf",
            "GIT_CONFIG_VALUE_0": "true",
        }
        checkout = self.root / "lf-checkout"

        with patch.dict(os.environ, external_git_config):
            with git_auth_environment("unit-test-token", self.root) as env:
                head = read_remote_head(str(remote), "main", env, "unit-test-token")
                clone_latest(str(remote), "main", checkout, env, "unit-test-token", head)

            for name, expected in self.initial_artifacts.items():
                actual = (checkout / name).read_bytes()
                self.assertEqual(actual, expected, name)
                self.assertNotIn(b"\r\n", actual, name)

            result, output = self.publish(dry_run=True, repo_url=remote)
            self.assertEqual(result.status, "HF_ALREADY_IN_SYNC")
            self.assertEqual(result.changed_files, ())
            self.assertIn("HF_ALREADY_IN_SYNC", output)

            self.write_source({"prices.json": b'{"version":"genuinely-new"}\n'})
            changed_result, changed_output = self.publish(dry_run=True, repo_url=remote)
            self.assertEqual(changed_result.status, "DRY_RUN_OK")
            self.assertEqual(changed_result.changed_files, ("prices.json",))
            self.assertIn("file: prices.json", changed_output)

    def test_only_prices_json_update_is_allowed(self):
        self.write_source({"prices.json": b'{"version":"new"}\n'})
        result, _output = self.publish()
        self.assertEqual(result.status, "HF_PUSHED")
        self.assertEqual(self.remote_changed_files(), {"prices.json"})
        checkout = self.clone_remote("inspect-one")
        self.assertEqual((checkout / "README.md").read_text(encoding="utf-8"), "HF-only dataset card\n")
        self.assertEqual((checkout / "prices.json").read_bytes(), (self.source / "prices.json").read_bytes())

    def test_all_four_artifact_updates_are_allowed(self):
        updated = {name: f"updated {name}\n".encode() for name in ALLOWED_ARTIFACTS}
        self.write_source(updated)
        result, _output = self.publish()
        self.assertEqual(result.status, "HF_PUSHED")
        self.assertEqual(self.remote_changed_files(), set(ALLOWED_ARTIFACTS))
        checkout = self.clone_remote("inspect-four")
        for name in ALLOWED_ARTIFACTS:
            self.assertEqual((checkout / name).read_bytes(), updated[name])
        self.assertEqual((checkout / "README.md").read_text(encoding="utf-8"), "HF-only dataset card\n")

    def test_readme_change_is_rejected(self):
        checkout = self.clone_remote("unexpected-readme")
        (checkout / "README.md").write_text("overwritten\n", encoding="utf-8")
        with self.assertRaises(UnexpectedHFChange) as caught:
            audit_changed_files(checkout)
        self.assertIn("file: README.md", str(caught.exception))

    def test_gitattributes_change_is_rejected(self):
        checkout = self.clone_remote("unexpected-attributes")
        (checkout / ".gitattributes").write_text("*.json text\n", encoding="utf-8")
        with self.assertRaises(UnexpectedHFChange) as caught:
            audit_changed_files(checkout)
        self.assertIn("file: .gitattributes", str(caught.exception))

    def test_unexpected_untracked_file_is_rejected(self):
        checkout = self.clone_remote("unexpected-untracked")
        (checkout / "future-hf-only.txt").write_text("preserve me\n", encoding="utf-8")
        with self.assertRaises(UnexpectedHFChange) as caught:
            audit_changed_files(checkout)
        self.assertIn("file: future-hf-only.txt", str(caught.exception))

    def test_remote_head_change_before_push_is_rejected(self):
        self.write_source({"prices.json": b'{"version":"new"}\n'})
        calls = 0

        def changed_reader(repo_url, branch, env, token):
            nonlocal calls
            calls += 1
            current = read_remote_head(repo_url, branch, env, token)
            return current if calls == 1 else "f" * 40

        before = self.remote_head()
        with self.assertRaises(RemoteChanged) as caught:
            self.publish(reader=changed_reader)
        self.assertIn("HF_HEAD_PRE_PUSH", str(caught.exception))
        self.assertEqual(self.remote_head(), before)

    def test_non_fast_forward_push_fails_without_force(self):
        publisher = self.clone_remote("publisher")
        concurrent = self.clone_remote("concurrent")

        (publisher / "prices.json").write_text('{"publisher":true}\n', encoding="utf-8")
        git("add", "prices.json", cwd=publisher)
        git("commit", "-m", "publisher commit", cwd=publisher)

        (concurrent / "meta.json").write_text('{"concurrent":true}\n', encoding="utf-8")
        git("add", "meta.json", cwd=concurrent)
        git("commit", "-m", "concurrent commit", cwd=concurrent)
        git("push", "origin", "main", cwd=concurrent)
        concurrent_head = self.remote_head()

        with git_auth_environment("unit-test-token", self.root) as env:
            with self.assertRaises(PushFailure) as caught:
                push_fast_forward(publisher, "main", env, "unit-test-token")
        self.assertIn("NON_FAST_FORWARD", str(caught.exception))
        self.assertEqual(self.remote_head(), concurrent_head)

    def test_missing_hf_token_is_auth_failure(self):
        with self.assertRaises(AuthFailure) as caught:
            require_token({})
        self.assertEqual(str(caught.exception), "HF_TOKEN is not configured")

    def test_token_is_sanitized_from_errors_and_askpass_file(self):
        token = "hf_secret/value+123"
        raw = RawGitError(
            ["push", "origin", "HEAD:main"],
            128,
            "",
            f"fatal: https://oauth2:{token}@huggingface.co denied {token}",
        )
        classified = classify_git_error(raw, token, operation="push")
        self.assertNotIn(token, str(classified))
        self.assertNotIn(token, sanitize_error(raw, (token,)))
        with git_auth_environment(token, self.root) as env:
            askpass = Path(env["GIT_ASKPASS"])
            self.assertNotIn(token, askpass.read_text(encoding="utf-8"))
        self.assertFalse(askpass.exists())
    def test_network_failure_is_classified_without_token_leak(self):
        token = "hf_network_secret"
        raw = RawGitError(
            ["ls-remote"],
            128,
            "",
            f"fatal: unable to access remote: Could not resolve host; {token}",
        )
        classified = classify_git_error(raw, token, operation="read_remote")
        self.assertIsInstance(classified, NetworkFailure)
        self.assertNotIn(token, str(classified))


    def test_dry_run_does_not_commit_or_push(self):
        self.write_source({"prices.json": b'{"version":"dry-run"}\n'})
        before = self.remote_head()
        result, output = self.publish(dry_run=True)
        self.assertEqual(result.status, "DRY_RUN_OK")
        self.assertEqual(self.remote_head(), before)
        self.assertIn("file: prices.json", output)
        self.assertIn("DRY_RUN_OK", output)

    def test_missing_source_artifact_is_validation_failure(self):
        empty = self.root / "empty-source"
        empty.mkdir()
        with self.assertRaises(ValidationFailure) as caught:
            validate_source_artifacts(empty)
        self.assertIn("source artifact missing", str(caught.exception))

    def test_repository_source_artifacts_pass_preflight(self):
        validate_source_artifacts()

    def test_workflow_is_manual_only_and_uses_minimal_permissions(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("name: Hugging Face Safe Publish", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("push:", workflow)
        self.assertNotIn("pull_request", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertIn("contents: read", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertIn("group: hugging-face-production-publish", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertIn("AUTH_FAILURE: HF_TOKEN is not configured", workflow)
        self.assertIn("VALIDATION_FAILURE", workflow)
        self.assertIn("ref: main", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("GITHUB_SOURCE_SHA: ${{ steps.source.outputs.sha }}", workflow)
        self.assertLess(workflow.index("Require Hugging Face write token"), workflow.index("actions/checkout@v5"))

    def test_production_checker_failure_stops_workflow(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        publisher = workflow.index("python scripts/publish_huggingface.py")
        parity = workflow.index("python scripts/check_hf_production_parity.py")
        success = workflow.index('echo "PUBLISH_SUCCESS"')
        self.assertLess(publisher, parity)
        self.assertLess(parity, success)
        self.assertNotIn("continue-on-error", workflow)
        self.assertIn("PRODUCTION_PARITY_FAILURE", workflow)

    def test_already_in_sync_then_parity_is_success_path(self):
        result, output = self.publish()
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(result.status, "HF_ALREADY_IN_SYNC")
        self.assertIn("HF_ALREADY_IN_SYNC", output)
        self.assertIn("python scripts/check_hf_production_parity.py", workflow)

    def test_commit_message_contains_github_source_sha(self):
        self.write_source({"prices.json": b'{"version":"new"}\n'})
        self.publish(source_sha="ABCDEF1234567890")
        subject = git(
            "--git-dir", str(self.remote), "log", "-1", "--format=%s", "refs/heads/main"
        ).strip()
        self.assertEqual(
            subject,
            "data: publish pricing artifacts from GitHub abcdef1",
        )

    def test_workflow_exposes_boolean_dry_run(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("dry_run:", workflow)
        self.assertIn("type: boolean", workflow)
        self.assertIn("default: false", workflow)
        self.assertIn("python scripts/publish_huggingface.py --dry-run", workflow)
        self.assertIn("if: ${{ ! inputs.dry_run }}", workflow)

    def test_publisher_contains_no_history_rewrite_or_bulk_sync_operations(self):
        publisher = (ROOT / "scripts" / "publish_huggingface.py").read_text(encoding="utf-8")
        for forbidden in (
            "--force",
            "force-with-lease",
            '"pull"',
            '"rebase"',
            '"merge"',
            "rsync",
            "--delete",
            '"mirror"',
        ):
            self.assertNotIn(forbidden, publisher)
        self.assertIn('["push", "origin", f"HEAD:{branch}"]', publisher)


if __name__ == "__main__":
    unittest.main()
