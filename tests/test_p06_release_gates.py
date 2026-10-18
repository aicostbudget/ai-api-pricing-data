import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.review_gate import DATASET_REPO, GateError, GitHubReader, require_manual_dispatch
from scripts.check_release_gate import (
    assert_clean_checkout,
    assert_local_release_identity,
    check_recovery_release,
    verify_production,
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = "7" * 40
SOURCE = "8" * 40
WEBSITE = "5" * 40


class ReviewFixture:
    def __init__(self, environment="github-pages"):
        self.environment = {
            "id": 7, "name": environment,
            "deployment_branch_policy": {"custom_branch_policies": True, "protected_branches": False},
            "protection_rules": [],
        }
        self.branches = {"total_count": 1, "branch_policies": [{"name": "main", "type": "branch"}]}
        self.run = {"head_sha": ARTIFACT, "head_branch": "main", "event": "workflow_dispatch", "run_attempt": 1, "actor": {"login": "fixture-author", "type": "User"}}
        self.permission = {"permission": "admin", "role_name": "admin", "user": {"login": "fixture-author", "type": "User"}}
        self.context = {
            "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REPOSITORY": DATASET_REPO,
            "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": ARTIFACT,
            "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_ACTOR": "fixture-author",
            "RECOVERY_SOURCE_SHA": SOURCE, "RECOVERY_ARTIFACT_SHA": ARTIFACT,
            "RECOVERY_WEBSITE_SHA": WEBSITE, "RECOVERY_ID": "fixture-recovery",
            "RECOVERY_DIGEST": "a" * 64,
        }

    def get(self, path, purpose):
        if "/collaborators/" in path:
            return self.permission
        if path.endswith("/deployment-branch-policies"):
            return self.branches
        if "/actions/runs/" in path:
            return self.run
        if "/environments/" in path:
            return self.environment
        return {"object": {"sha": ARTIFACT if DATASET_REPO in path else WEBSITE}}


class ReviewGateTests(unittest.TestCase):
    def test_exact_maintainer_dispatch_enters_recovery_preflight(self):
        fixture = ReviewFixture()
        self.assertEqual(require_manual_dispatch(fixture.context, fixture.get, "github-pages", "main"), ARTIFACT)
        identity = check_recovery_release(fixture.context, fixture.get, "pages")
        self.assertEqual(identity["artifact_sha"], ARTIFACT)

    def test_non_manual_or_nonmaintainer_dispatch_fails_closed(self):
        fixture = ReviewFixture()
        fixture.context["GITHUB_EVENT_NAME"] = "push"
        with self.assertRaises(GateError):
            check_recovery_release(fixture.context, fixture.get, "pages")
        fixture = ReviewFixture()
        fixture.permission["permission"] = "read"
        fixture.permission["role_name"] = "read"
        with self.assertRaises(GateError):
            check_recovery_release(fixture.context, fixture.get, "pages")

    def test_tokens_are_required_and_never_leaked(self):
        with patch("scripts.review_gate.urlopen") as network:
            with self.assertRaisesRegex(GateError, "GITHUB_TOKEN"):
                GitHubReader({})("/repos/example", "review")
            network.assert_not_called()
        secret = "fixture-secret-do-not-log"
        with patch("scripts.review_gate.urlopen", side_effect=RuntimeError(secret)):
            with self.assertRaises(GateError) as caught:
                GitHubReader({"GITHUB_TOKEN": secret})("/repos/example", "review")
        self.assertNotIn(secret, str(caught.exception))


class RecoveryIdentityTests(unittest.TestCase):
    def blobs(self):
        canonical = b"canonical\n"
        return {
            (SOURCE, "data/canonical/models.json"): canonical,
            (ARTIFACT, "data/canonical/models.json"): canonical,
            (ARTIFACT, "api/v1/meta.json"): json.dumps({"source_commit_sha": SOURCE}).encode(),
        }

    def test_strict_recovery_identity_passes(self):
        blobs = self.blobs()
        result = assert_local_release_identity(
            {"source_sha": SOURCE, "artifact_sha": ARTIFACT, "website_sha": WEBSITE},
            lambda revision, path: blobs[(revision, path)],
            lambda source, artifact: True,
        )
        self.assertEqual(result[:3], (SOURCE, ARTIFACT, WEBSITE))

    def test_recovery_identity_rejects_same_revision_ancestry_and_canonical_drift(self):
        blobs = self.blobs()
        with self.assertRaises(GateError):
            assert_local_release_identity({"source_sha": ARTIFACT, "artifact_sha": ARTIFACT, "website_sha": WEBSITE}, lambda revision, path: blobs[(revision, path)], lambda source, artifact: True)
        with self.assertRaises(GateError):
            assert_local_release_identity({"source_sha": SOURCE, "artifact_sha": ARTIFACT, "website_sha": WEBSITE}, lambda revision, path: blobs[(revision, path)], lambda source, artifact: False)
        blobs[(ARTIFACT, "data/canonical/models.json")] = b"changed"
        with self.assertRaises(GateError):
            assert_local_release_identity({"source_sha": SOURCE, "artifact_sha": ARTIFACT, "website_sha": WEBSITE}, lambda revision, path: blobs[(revision, path)], lambda source, artifact: True)


class CleanInputAndProductionTests(unittest.TestCase):
    def test_clean_checkout_contract_remains_fail_closed(self):
        root = ROOT.resolve()
        assert_clean_checkout(root, reader=lambda *args: str(root) if args[0] == "rev-parse" else "")
        with self.assertRaises(GateError):
            assert_clean_checkout(root, reader=lambda *args: str(root) if args[0] == "rev-parse" else " M data/canonical/models.json\0")

    def test_exact_production_parity_passes_and_http_failure_stops(self):
        expected = {
            "json": {"metadata": {"schema_version": "1.10.0"}, "records": [{"model_id": "fixture"}]},
            "csv": "model_id\nfixture\n",
            "version": {"pricing_fingerprint": "fixture", "schema_version": 3},
        }
        def fetch(url):
            if url.endswith(".csv"):
                return 200, "text/csv", expected["csv"].encode()
            return 200, "application/json", json.dumps(expected["json"] if url.endswith(".json") else expected["version"]).encode()
        verify_production(expected, fetch)
        with self.assertRaises(GateError):
            verify_production(expected, lambda url: (503, "text/html", b"unavailable"))


class WorkflowContractTests(unittest.TestCase):
    def test_ordinary_pages_uses_one_revision_without_old_daily_identity(self):
        text = (ROOT / ".github/workflows/deploy-pages.yml").read_text(encoding="utf-8")
        self.assertIn('branches: ["main"]', text)
        self.assertIn("SOURCE_COMMIT_SHA:", text)
        self.assertIn("actions/deploy-pages@v5", text)
        self.assertIn("verify_pages_deployment.py --release-sha", text)
        for token in ("artifact_sha:", "source_sha:", "website_sha:", "release_plan_id", "release_plan_digest"):
            self.assertNotIn("      " + token, text)

    def test_ordinary_hf_is_one_publish_then_parity_and_recovery_is_explicit(self):
        text = (ROOT / ".github/workflows/publish-huggingface.yml").read_text(encoding="utf-8")
        self.assertIn("  workflow_dispatch:", text)
        self.assertNotIn("\n  push:", text)
        self.assertIn("if: github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'", text)
        self.assertEqual(text.count("name: Publish allowlisted artifacts safely"), 1)
        self.assertIn("name: Validate allowlisted Hugging Face artifacts", text)
        self.assertIn("python -m unittest tests.test_huggingface_export", text)
        self.assertLess(text.index("python scripts/publish_huggingface.py"), text.index("python scripts/check_hf_production_parity.py"))
        self.assertIn("recovery_mode:", text)
        self.assertIn("if: inputs.recovery_mode", text)
        self.assertIn("python scripts/check_release_gate.py --kind hf --recovery", text)
        self.assertIn("environment: hf-release-review", text)
        self.assertNotIn("release_plan_id", text)
        self.assertNotIn("release_plan_digest", text)
        self.assertNotIn("continue-on-error", text)


if __name__ == "__main__":
    unittest.main()
