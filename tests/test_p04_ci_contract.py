import copy
import json
import re
import tempfile
import unittest
from pathlib import Path, PurePosixPath, PureWindowsPath
from scripts import check_website_candidate as policy
from tests.website_source import release_source_candidates, resolve_release_website_source

ROOT = Path(__file__).resolve().parents[1]

class CheckoutPathTests(unittest.TestCase):
    def test_posix_candidates(self):
        root = PurePosixPath("/home/runner/work/data/data")
        self.assertEqual(release_source_candidates(root, {}), [root / "website-source", root.parent / "ai-cost-control-tool/aicostguard-english"])
    def test_windows_candidates(self):
        root = PureWindowsPath("D:/ai-api-pricing-data")
        self.assertEqual(release_source_candidates(root, {})[0], PureWindowsPath("D:/ai-api-pricing-data/website-source"))
    def fixture(self, base):
        root = base / "dataset"
        for name in ["data/canonical/models.json", "scripts/build_release_bundle.py"]:
            p = root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text("{}")
        return root
    def website(self, root, name="aicostbudget-english"):
        website = root / "website-source"
        for filename in [".git", "package.json", "data/model-pricing.json", "data/pricing-v2-projection/model-pricing.v2.json"]:
            p = website / filename; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps({"name": name}) if filename == "package.json" else "{}")
        return website
    def test_ci_checkout_and_explicit_override(self):
        with tempfile.TemporaryDirectory() as t:
            root = self.fixture(Path(t)); website = self.website(root)
            self.assertEqual(resolve_release_website_source(root, {}), website.resolve())
            self.assertEqual(resolve_release_website_source(root, {"WEBSITE_SOURCE_ROOT": str(website)}), website.resolve())
    def test_missing_checkout_fails_without_skip(self):
        with tempfile.TemporaryDirectory() as t:
            root = self.fixture(Path(t))
            with self.assertRaises(FileNotFoundError): resolve_release_website_source(root, {})
    def test_wrong_dataset_root_fails(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaisesRegex(ValueError, "Dataset"): resolve_release_website_source(Path(t), {})
    def test_wrong_website_repository_fails(self):
        with tempfile.TemporaryDirectory() as t:
            root = self.fixture(Path(t)); self.website(root, "unrelated")
            with self.assertRaisesRegex(ValueError, "identity"): resolve_release_website_source(root, {})
    def test_explicit_missing_override_does_not_fallback(self):
        with tempfile.TemporaryDirectory() as t:
            root = self.fixture(Path(t)); self.website(root)
            with self.assertRaises(FileNotFoundError): resolve_release_website_source(root, {"WEBSITE_SOURCE_ROOT": str(root / "missing")})
    def test_non_checkout_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root = self.fixture(Path(t)); (root / "website-source").mkdir()
            with self.assertRaisesRegex(ValueError, "checkout"): resolve_release_website_source(root, {})

class CandidatePolicyTests(unittest.TestCase):
    def setUp(self):
        # Controlled policy response fixture, never used as a published SHA/artifact.
        self.sha = "a" * 40
        self.context = {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REPOSITORY": policy.DATASET_REPO, "GITHUB_REF": policy.DATASET_BRANCH, "WEBSITE_CANDIDATE_SHA": self.sha, "GITHUB_SHA": "72ce4a1a7475bbd9c2a394aedf864afec073d494", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_ACTOR": "fixture-author"}
        self.environment = {"id":7,"name":policy.ENVIRONMENT,"deployment_branch_policy":{"custom_branch_policies":True,"protected_branches":False},"protection_rules": [{"type": "required_reviewers", "prevent_self_review": True, "reviewers": [{"type": "User","reviewer":{"id":9}}]}]}
        self.main = policy.APPROVED_BASE; self.tip = self.sha
        self.comparison = {"status": "ahead", "merge_base_commit": {"sha": self.main}}
    def get(self, path, purpose):
        if purpose == "review":
            if "/collaborators/" in path: return {"permission":"admin","role_name":"admin","user":{"login":"fixture-author","type":"User"}}
            if path.endswith("/deployment-branch-policies"): return {"total_count":1,"branch_policies":[{"name":"codex/issue26-dataset-candidate","type":"branch"}]}
            if path.endswith("/approvals"): return [{"state":"approved","user":{"id":9,"login":"fixture-reviewer"},"environments":[{"id":7,"name":policy.ENVIRONMENT}]}]
            if "/actions/runs/" in path: return {"head_sha":self.context["GITHUB_SHA"],"head_branch":"codex/issue26-dataset-candidate","event":"workflow_dispatch","run_attempt":1,"actor":{"login":"fixture-author","type":"User"}}
            return self.environment
        if "/compare/" in path: return self.comparison
        return {"object": {"sha": self.main if path.endswith("/heads/main") else self.tip}}
    def test_exact_reviewed_sha_accepted(self):
        self.assertEqual(policy.check_candidate(self.context, self.get), self.sha)
    def test_push_pr_main_other_repository_rejected(self):
        for key, values in {"GITHUB_EVENT_NAME": ["push", "pull_request"], "GITHUB_REF": ["refs/heads/main", "refs/heads/arbitrary"], "GITHUB_REPOSITORY": ["other/repo"]}.items():
            for value in values:
                context = {**self.context, key: value}
                with self.assertRaises(ValueError): policy.check_candidate(context, self.get)
    def test_arbitrary_ref_and_sha_rejected(self):
        for sha in ["main", "codex/other", "", "B" * 40, "b" * 40, self.main]:
            with self.assertRaises(ValueError): policy.check_candidate({**self.context, "WEBSITE_CANDIDATE_SHA": sha}, self.get)
    def test_missing_environment_fails_but_reviewers_not_required(self):
        self.environment = {}
        with self.assertRaises(ValueError): policy.check_candidate(self.context, self.get)
        self.setUp();self.environment["protection_rules"] = []
        self.assertEqual(policy.check_candidate(self.context, self.get), self.sha)
        self.environment["protection_rules"] = [{"type":"required_reviewers","prevent_self_review":False,"reviewers":[]}]
        self.assertEqual(policy.check_candidate(self.context, self.get), self.sha)
    def test_moved_main_diverged_candidate_rejected(self):
        self.main = "c" * 40
        with self.assertRaises(ValueError): policy.check_candidate(self.context, self.get)
        self.main = policy.APPROVED_BASE
        for comparison in [{"status": "diverged"}, {"status": "ahead", "merge_base_commit": {"sha": "d" * 40}}]:
            self.comparison = comparison
            with self.assertRaises(ValueError): policy.check_candidate(self.context, self.get)
    def test_api_failure_is_not_swallowed(self):
        def error(*args): raise PermissionError("token denied")
        with self.assertRaises(PermissionError): policy.check_candidate(self.context, error)
    def test_workflows_preserve_main_and_full_candidate_gates(self):
        for filename in ["validate.yml", "website-pricing-parity.yml"]:
            text = (ROOT / ".github/workflows" / filename).read_text(encoding="utf-8")
            normal, candidate = text.split("  reviewed-website-candidate:", 1)
            self.assertIn("ref: main", normal)
            self.assertIn("inputs.website_candidate_sha == ''", normal)
            self.assertIn("environment: pricing-candidate-review", candidate)
            self.assertIn("python scripts/check_website_candidate.py", candidate)
            self.assertLess(candidate.index("check_website_candidate.py"), candidate.index("ref: ${{ inputs.website_candidate_sha }}"))
            self.assertNotIn("continue-on-error", text); self.assertNotIn("|| true", text)
            if filename == "validate.yml":
                self.assertIn("python -m unittest discover -s tests", candidate)
                self.assertIn("python scripts/validate.py", candidate)

if __name__ == "__main__": unittest.main()
