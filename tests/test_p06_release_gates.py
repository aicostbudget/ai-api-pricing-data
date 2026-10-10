import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.review_gate import DATASET_REPO, GateError, GitHubReader, require_manual_dispatch
from scripts.check_release_gate import check_release, assert_bundle_identity, verify_production, assert_clean_checkout

ROOT=Path(__file__).resolve().parents[1]
ARTIFACT="72ce4a1a7475bbd9c2a394aedf864afec073d494"
SOURCE="80c2ec4991bcaaf795fe9192946f5ec770d57f48"
WEBSITE="52c0e6f3094feeaf6812e1564aef4818ecdd372c"

class ReviewFixture:
    """Controlled API fixture using known existing SHAs, never creates commits/tags/reviews."""
    def __init__(self,environment="github-pages",branch="main"):
        self.environment={"id":7,"name":environment,"deployment_branch_policy":{"custom_branch_policies":True,"protected_branches":False},"protection_rules":[{"type":"required_reviewers","prevent_self_review":True,"reviewers":[{"type":"User","reviewer":{"id":9}}]}]}
        self.branches={"total_count":1,"branch_policies":[{"name":branch,"type":"branch"}]}
        self.run={"head_sha":ARTIFACT,"head_branch":branch,"event":"workflow_dispatch","run_attempt":1,"actor":{"login":"fixture-author","type":"User"}}
        self.reviews=[{"state":"approved","user":{"id":9,"login":"fixture-reviewer"},"environments":[{"id":7,"name":environment}]}]
        self.permission={"permission":"admin","role_name":"admin","user":{"login":"fixture-author","type":"User"}}
        self.dataset_main=ARTIFACT;self.website_main=WEBSITE;self.tag_target=ARTIFACT
        self.ancestry={"status":"ahead","merge_base_commit":{"sha":SOURCE}}
        self.context={"GITHUB_EVENT_NAME":"workflow_dispatch","GITHUB_REPOSITORY":DATASET_REPO,"GITHUB_REF":"refs/heads/"+branch,"GITHUB_SHA":ARTIFACT,"GITHUB_RUN_ID":"123","GITHUB_RUN_ATTEMPT":"1","GITHUB_ACTOR":"fixture-author","ARTIFACT_SHA":ARTIFACT,"SOURCE_SHA":SOURCE,"WEBSITE_SHA":WEBSITE,"RELEASE_TAG":"fixture-approved-tag"}
    def get(self,path,purpose):
        if "/collaborators/" in path:return self.permission
        if path.endswith("/deployment-branch-policies"):return self.branches
        if path.endswith("/approvals"):return self.reviews
        if "/actions/runs/" in path:return self.run
        if "/environments/" in path:return self.environment
        if "/compare/" in path:return self.ancestry
        if "/git/ref/tags/" in path:return {"ref":"refs/tags/fixture-approved-tag","object":{"type":"commit","sha":self.tag_target}}
        return {"object":{"sha":self.dataset_main if DATASET_REPO in path else self.website_main}}

class ReviewGateTests(unittest.TestCase):
    def setUp(self):self.fixture=ReviewFixture()
    def check(self):return require_manual_dispatch(self.fixture.context,self.fixture.get,"github-pages","main")
    def test_exact_maintainer_dispatch_enters_preflight(self):self.assertEqual(self.check(),ARTIFACT)
    def test_missing_token_fails_before_network(self):
        with patch("scripts.review_gate.urlopen") as network:
            for purpose,name in [("review","GITHUB_TOKEN"),("website","WEBSITE_REPO_TOKEN")]:
                with self.assertRaisesRegex(GateError,name):GitHubReader({})("/repos/example",purpose)
            network.assert_not_called()
    def test_api_denied_does_not_leak_token_or_allow_review(self):
        with patch("scripts.review_gate.urlopen",side_effect=RuntimeError("fixture-secret-DO-NOT-LOG")):
            with self.assertRaises(GateError) as error:GitHubReader({"GITHUB_TOKEN":"fixture-secret-DO-NOT-LOG"})("/repos/example","review")
            self.assertNotIn("DO-NOT-LOG",str(error.exception))
    def test_missing_environment_or_missing_branch_restriction_rejected(self):
        for env in [{},{"id":7,"name":"github-pages","protection_rules":[]}]:
            self.fixture.environment=env
            with self.assertRaises(GateError):self.check()
    def test_empty_reviewers_and_self_review_options_are_not_hard_dependencies(self):
        for rules in [[],[{"type":"required_reviewers","prevent_self_review":False,"reviewers":[]}],[{"type":"required_reviewers","prevent_self_review":True,"reviewers":[{"type":"User","reviewer":{"id":9}}]}]]:
            self.fixture.environment["protection_rules"]=rules
            self.assertEqual(self.check(),ARTIFACT)
    def test_no_approval_history_is_queried_or_required(self):
        original=self.fixture.get
        def no_history(path,purpose):
            if path.endswith("/approvals"):raise AssertionError("Independent review history must not be read")
            return original(path,purpose)
        self.fixture.reviews=[]
        self.assertEqual(require_manual_dispatch(self.fixture.context,no_history,"github-pages","main"),ARTIFACT)
    def test_nonmaintainer_and_bot_cannot_dispatch_release(self):
        for permission,role,user_type in [("read","read","User"),("write","write","User"),("admin","admin","Bot")]:
            self.fixture.permission={"permission":permission,"role_name":role,"user":{"login":"fixture-author","type":user_type}}
            with self.assertRaises(GateError):self.check()
        self.fixture.permission={"permission":"write","role_name":"maintain","user":{"login":"fixture-author","type":"User"}}
        self.assertEqual(self.check(),ARTIFACT)
    def test_same_human_maintainer_can_approve_own_dispatch(self):
        self.fixture.reviews=[{"state":"rejected","user":{"id":9,"login":"fixture-author"},"environments":[{"id":7,"name":"github-pages"}]}]
        self.assertEqual(self.check(),ARTIFACT)
        self.fixture.context["GITHUB_TRIGGERING_ACTOR"]="other"
        with self.assertRaises(GateError):self.check()
    def test_push_pr_other_branch_repository_and_rerun_rejected(self):
        for key,value in [("GITHUB_EVENT_NAME","push"),("GITHUB_EVENT_NAME","pull_request"),("GITHUB_REF","refs/heads/master"),("GITHUB_REPOSITORY","other/repo"),("GITHUB_RUN_ATTEMPT","2")]:
            original=self.fixture.context.copy();self.fixture.context[key]=value
            with self.assertRaises(GateError):self.check()
            self.fixture.context=original
    def test_review_context_source_mismatch_rejected(self):
        for key,value in [("head_sha",SOURCE),("head_branch","other"),("event","push"),("run_attempt",2),("actor",{"login":"other"})]:
            original=self.fixture.run.copy();self.fixture.run[key]=value
            with self.assertRaises(GateError):self.check()
            self.fixture.run=original
    def test_wildcard_tags_extra_and_missing_branch_policy_rejected(self):
        for names in [[],["*"],["main","other"]]:
            self.fixture.branches={"total_count":len(names),"branch_policies":[{"name":n,"type":"branch"} for n in names]}
            with self.assertRaises(GateError):self.check()
        self.fixture.branches={"total_count":1,"branch_policies":[{"name":"main","type":"tag"}]}
        with self.assertRaises(GateError):self.check()

class ReleaseIdentityTests(unittest.TestCase):
    def setUp(self):self.fixture=ReviewFixture()
    def check(self,kind="pages"):return check_release(self.fixture.context,self.fixture.get,kind)
    def test_correct_existing_commit_identities_enter_preflight_only(self):
        self.assertEqual(self.check()["artifact_sha"],ARTIFACT)
        self.fixture=ReviewFixture("hf-release-review");self.assertEqual(self.check("hf")["website_sha"],WEBSITE)
    def test_arbitrary_or_future_placeholder_ref_rejected(self):
        for key in ["ARTIFACT_SHA","SOURCE_SHA","WEBSITE_SHA"]:
            for value in ["WORKTREE","main","S1",None,""]:
                original=self.fixture.context.copy();self.fixture.context[key]=value
                with self.assertRaises(GateError):self.check()
                self.fixture.context=original
    def test_distinct_source_and_dispatch_sha_required(self):
        self.fixture.context["SOURCE_SHA"]=ARTIFACT
        with self.assertRaises(GateError):self.check()
        self.setUp();self.fixture.context["ARTIFACT_SHA"]=SOURCE
        with self.assertRaises(GateError):self.check()
    def test_moved_dataset_or_website_main_rejected(self):
        for field in ["dataset_main","website_main"]:
            original=getattr(self.fixture,field);setattr(self.fixture,field,SOURCE)
            with self.assertRaises(GateError):self.check()
            setattr(self.fixture,field,original)
    def test_wrong_tag_or_non_ancestor_source_rejected(self):
        self.fixture.tag_target=SOURCE
        with self.assertRaises(GateError):self.check()
        self.setUp();self.fixture.ancestry={"status":"diverged","merge_base_commit":{"sha":SOURCE}}
        with self.assertRaises(GateError):self.check()
    def test_candidate_manifest_cannot_become_formal(self):
        identity=self.check();manifest={"status":"release","git_commit":ARTIFACT,"website_source":{"git_commit":WEBSITE},"release_version":"fixture-approved-tag","projections":{"pricing_v2":{"export_schema":"1.10.0"}}}
        assert_bundle_identity(manifest,identity)
        for key,value in [("source_scope","LOCAL_CANDIDATE"),("status","candidate"),("git_commit",None),("release_version","other-tag")]:
            bad={**manifest,key:value}
            with self.assertRaises(GateError):assert_bundle_identity(bad,identity)

class CleanInputTests(unittest.TestCase):
    def test_genuine_clean_checkout_and_exact_nested_consumer_allowed(self):
        root=ROOT.resolve()
        reader=lambda *args:str(root) if args[0]=="rev-parse" else "?? website-source/\0"
        assert_clean_checkout(root,root/"website-source",reader)
        assert_clean_checkout(root,reader=lambda *args:str(root) if args[0]=="rev-parse" else "")
    def test_dirty_unrelated_inputs_or_wrong_root_fail_closed(self):
        root=ROOT.resolve()
        for status in [" M data/canonical/models.json\0","?? untracked-user-file\0","?? website-source/other\0"]:
            with self.assertRaises(GateError):assert_clean_checkout(root,root/"website-source",lambda *args:str(root) if args[0]=="rev-parse" else status)
        with self.assertRaises(GateError):assert_clean_checkout(root,reader=lambda *args:str(root.parent))

class ProductionParityTests(unittest.TestCase):
    def setUp(self):
        self.expected={"json":{"metadata":{"schema_version":"1.10.0"},"records":[{"model_id":"fixture","promotion":{"list":1,"end":None}}]},"csv":"model_id,pricing_components_json\nfixture,[]\n","version":{"pricing_fingerprint":"fixture-hash","schema_version":3}}
    def fetch(self,url):
        if url.endswith(".csv"):return 200,"text/csv; charset=utf-8",self.expected["csv"].encode()
        return 200,"application/json",json.dumps(self.expected["json"] if url.endswith(".json") else self.expected["version"]).encode()
    def test_exact_full_production_contract_and_fingerprint_pass(self):verify_production(self.expected,self.fetch)
    def test_missing_promotion_or_wrong_fingerprint_fails(self):
        for target in ["json","version"]:
            expected=copy.deepcopy(self.expected)
            if target=="json":del expected[target]["records"][0]["promotion"]
            else:expected[target]["pricing_fingerprint"]="different"
            with self.assertRaises(GateError):verify_production(expected,self.fetch)
    def test_csv_loss_and_http_fail_closed(self):
        bad={**self.expected,"csv":"model_id,pricing_components_json\nfixture,{}\n"}
        with self.assertRaises(GateError):verify_production(bad,self.fetch)
        with self.assertRaises(GateError):verify_production(self.expected,lambda url:(503,"text/html",b"unavailable"))

class WorkflowContractTests(unittest.TestCase):
    def test_pages_push_keeps_full_preflight_but_no_production_permission(self):
        text=(ROOT/".github/workflows/deploy-pages.yml").read_text(encoding="utf-8")
        build,review,deploy=text.split("  release-preflight:")[0],text.split("  release-preflight:")[1].split("  deploy:")[0],text.split("  deploy:")[1]
        self.assertIn('branches: ["main", "master"]',build)
        self.assertIn("python -m unittest discover",build);self.assertIn("test-dataset-pricing-components-parity",build)
        self.assertNotIn("pages: write",build);self.assertNotIn("id-token: write",build)
        self.assertIn("environment: github-pages",review);self.assertIn("check_release_gate.py --kind pages --verify-local",review)
        self.assertIn("needs: [build, release-preflight]",deploy);self.assertIn("needs.release-preflight.outputs.eligible == 'true'",deploy)
        self.assertLess(deploy.index("check_release_gate.py"),deploy.index("actions/deploy-pages"))
        self.assertIn("verify_pages_deployment.py",deploy)
        self.assertNotIn("continue-on-error",text);self.assertNotIn("|| true",text)
    def test_hf_is_manually_authorized_pinned_and_dry_by_default(self):
        text=(ROOT/".github/workflows/publish-huggingface.yml").read_text(encoding="utf-8")
        self.assertIn("default: true",text);self.assertIn("environment: hf-release-review",text)
        self.assertIn("GITHUB_SOURCE_SHA: ${{ inputs.artifact_sha }}",text)
        self.assertNotIn("ref: main",text);self.assertNotIn("push:",text)
        self.assertIn("needs.release-preflight.outputs.eligible == 'true'",text)
        self.assertLess(text.index("--verify-production"),text.index("python scripts/publish_huggingface.py"))
        self.assertLess(text.index("python scripts/publish_huggingface.py"),text.index("python scripts/check_hf_production_parity.py"))
        self.assertNotIn("continue-on-error",text)
    def test_no_long_lived_review_pat_or_missing_secret_fallback(self):
        for name in ["validate.yml","website-pricing-parity.yml","deploy-pages.yml","publish-huggingface.yml"]:
            text=(ROOT/".github/workflows"/name).read_text(encoding="utf-8")
            self.assertIn("actions: read",text);self.assertIn("GITHUB_TOKEN: ${{ github.token }}",text)
            self.assertNotIn("CANDIDATE_REVIEW_TOKEN",text)

if __name__=="__main__":unittest.main()
