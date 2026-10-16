import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.daily_pricing_release import (
    Backend,
    PLAN_SCHEMA,
    ReleaseFailure,
    ReleaseStateStore,
    ShellBackend,
    canonical_bytes,
    classify_changes,
    ensure_snapshot,
    plan_digest,
    prepare_release,
    publish_release,
    release_tag_name,
    row_contract,
    sha256_bytes,
    write_json,
)


def model(model_id, *, price=1, verified="2026-10-15", future=False):
    records=[{"id":f"price:p/{model_id}:standard:current","processing_mode":"standard","pricing_status":"current","charges":[{"component":"input","amount":str(price)}]}]
    if future: records.append({"id":f"price:p/{model_id}:standard:future","processing_mode":"standard","pricing_status":"future","effective_from":"2026-12-01","charges":[{"component":"input","amount":str(price*2)}]})
    return {"provider_id":"p","model_id":model_id,"verified_at":verified,"price_records":records,"pricing":{"input":price}}


def plan_fixture(tmp):
    plan={"schema":PLAN_SCHEMA,"release_id":"pricing-2026-10-15-fixture","generated_at":"2026-10-15T00:00:00Z","snapshot_date":"2026-10-15","snapshot_before":"2026-10-14","dataset_base_sha":"1"*40,"website_base_sha":"2"*40,"canonical_sha256":"a"*64,"models":[{"provider_id":"p","model_id":"m","change_type":"added"}],"source_files":[],"workspace":{"unrelated_files":[]},"projection_contracts":{"v1":{"records":1,"row_digests":{}},"v2":{"records":1,"row_digests":{}}},"tests":[{"name":"fixture","status":"PASS"}]}
    path=Path(tmp)/"plan.json";write_json(path,plan)
    return plan,path,plan_digest(path)


class FakeBackend(Backend):
    def __init__(self, fail=None): self.fail=fail;self.calls=[]
    def hit(self,name,value=None):
        self.calls.append(name)
        if self.fail==name: raise ReleaseFailure("CI_FAILURE" if "ci" in name else "CODE_FAILURE",name,"fixture failure")
        return value
    def verify_plan(self,p,d):self.hit("plan_verified")
    def commit_source(self,p):return self.hit("source_committed","3"*40)
    def generate_artifacts(self,p,s):self.hit("artifacts_generated")
    def commit_artifact(self,p,s):return self.hit("artifact_committed","4"*40)
    def commit_website(self,p,s):return self.hit("website_committed","5"*40)
    def push_dataset(self,p,s):self.hit("dataset_pushed")
    def push_website(self,p,s):self.hit("website_pushed")
    def verify_pre_tag(self,p,d,s,a,w):return self.hit("pre_tag_verified","dataset-2026-10-15-m-aaaaaaaa")
    def push_tag(self,p,s,t):return self.hit("tag_pushed",t)
    def verify_ci(self,a,w):return self.hit("validate_verified",[{"url":"ci"}])
    def deploy_pages(self,s,p):return self.hit("pages_release_preflight_verified",{"url":"pages","release_preflight_verified":True,"production_deployed":True,"production_parity_verified":True})
    def verify_website_production(self,w):self.hit("website_production_verified")
    def publish_hf(self,s,p,dry_run):return self.hit("hf_dry_run_verified" if dry_run else "hf_publish_verified",{"url":"hf-dry" if dry_run else "hf"})
    def verify_hf(self):self.hit("hf_production_verified")


class ChangePlanningTests(unittest.TestCase):
    def test_new_ga_model(self):
        changes=classify_changes([model("old")],[model("old"),model("new")])
        self.assertEqual([(c["model_id"],c["change_type"]) for c in changes],[("new","added")])

    def test_existing_price_change(self):
        changes=classify_changes([model("m",price=1)],[model("m",price=2)])
        self.assertEqual(changes[0]["change_type"],"pricing")
        self.assertNotEqual(changes[0]["before_sha256"],changes[0]["after_sha256"])

    def test_multiple_models_in_one_batch(self):
        changes=classify_changes([], [model("a"),model("b")])
        self.assertEqual([c["model_id"] for c in changes],["a","b"])

    def test_current_and_future_periods_are_hashed(self):
        current=row_contract([model("m",future=True)])
        changed=row_contract([model("m",price=2,future=True)])
        self.assertNotEqual(current["row_digests"],changed["row_digests"])

    def test_verification_only_has_no_price_change(self):
        changes=classify_changes([model("m",verified="2026-10-14")],[model("m",verified="2026-10-15")])
        self.assertEqual(changes[0]["change_type"],"verification_metadata")
        self.assertEqual(changes[0]["old_pricing"],changes[0]["new_pricing"])

    def test_no_change_has_no_release(self):
        self.assertEqual(classify_changes([model("m")],[copy.deepcopy(model("m"))]),[])

    def test_tag_name_is_readable_deterministic_and_collision_resistant(self):
        single={"snapshot_date":"2026-10-15","canonical_sha256":"abcdef12"+"0"*56,"models":[{"model_id":"Grok Voice 3.0"}]}
        multiple={**single,"models":[{"model_id":"a"},{"model_id":"b"}]}
        self.assertEqual(release_tag_name(single),"dataset-2026-10-15-grok-voice-3-0-abcdef12")
        self.assertEqual(release_tag_name(multiple),"dataset-2026-10-15-pricing-abcdef12")
        self.assertNotEqual(release_tag_name(single),release_tag_name({**single,"canonical_sha256":"12345678"+"0"*56}))

    def test_same_day_snapshot_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/"api/v1").mkdir(parents=True);(root/"data/snapshots/2026-10-15").mkdir(parents=True)
            (root/"api/v1/prices.json").write_bytes(b"new");(root/"api/v1/prices.csv").write_bytes(b"new")
            (root/"data/snapshots/2026-10-15/prices.json").write_bytes(b"old");(root/"data/snapshots/2026-10-15/prices.csv").write_bytes(b"old")
            with self.assertRaisesRegex(ReleaseFailure,"already exists with different bytes"):ensure_snapshot(root,"2026-10-15T00:00:00Z")

    def test_prepare_writes_reviewable_plan_from_local_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"dataset";website=Path(tmp)/"website"
            (root/".git").mkdir(parents=True);(website/".git").mkdir(parents=True)
            (root/"data/canonical").mkdir(parents=True);(root/"api/v1").mkdir(parents=True);(root/"huggingface").mkdir();(root/"data/snapshots/2026-10-14").mkdir(parents=True)
            (website/"data").mkdir(parents=True)
            write_json(root/"data/canonical/models.json",[model("old"),model("new")]);write_json(website/"data/model-pricing.json",[])
            write_json(root/"api/v1/prices.json",{"models":[model("old"),model("new")]});write_json(root/"huggingface/prices.json",{"records":[model("old"),model("new")]})
            (root/"data/snapshots/2026-10-14/prices.json").write_text("{}")
            base=json.dumps([model("old")])
            def fake_git(repo,*args,**kwargs):
                if args[:2]==("rev-parse","HEAD"):return "1"*40 if repo==root else "2"*40
                if args[:2]==("show","1"*40+":data/canonical/models.json"):return base
                if args[0]=="diff":return "data/canonical/models.json" if repo==root else ""
                if args[0]=="ls-files":return "data/snapshots/2026-10-15/prices.json\ndata/snapshots/2026-10-15/prices.csv" if repo==root else ""
                raise AssertionError(args)
            def fake_generators(r,w,g):return "2026-10-15",[{"name":"fixture","status":"PASS"}]
            with patch("scripts.daily_pricing_release.git",side_effect=fake_git):
                plan,path,digest=prepare_release(root,website,"2026-10-15T00:00:00Z",fake_generators,lambda repo,cwd:"1"*40 if repo.endswith("pricing-data") else "2"*40)
            self.assertEqual(plan["models"][0]["model_id"],"new");self.assertTrue(path.is_file());self.assertEqual(plan_digest(path),digest)

    def test_prepare_rejects_no_canonical_diff_before_generators(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"dataset";website=Path(tmp)/"website"
            (root/".git").mkdir(parents=True);(website/".git").mkdir(parents=True)
            (root/"data/canonical").mkdir(parents=True);(website/"data").mkdir(parents=True)
            rows=[model("unchanged")];write_json(root/"data/canonical/models.json",rows);write_json(website/"data/model-pricing.json",[])
            def fake_git(repo,*args,**kwargs):
                if args[:2]==("rev-parse","HEAD"):return "1"*40 if repo==root else "2"*40
                if args[0]=="show":return json.dumps(rows)
                raise AssertionError(args)
            generators=Mock()
            with patch("scripts.daily_pricing_release.git",side_effect=fake_git):
                with self.assertRaisesRegex(ReleaseFailure,"No canonical model change"):
                    prepare_release(root,website,"2026-10-15T00:00:00Z",generators,lambda repo,cwd:"1"*40 if repo.endswith("pricing-data") else "2"*40)
            generators.assert_not_called()


class PublishRecoveryTests(unittest.TestCase):
    def execute(self,tmp,backend):
        plan,path,digest=plan_fixture(tmp);store=ReleaseStateStore(Path(tmp),plan["release_id"])
        return publish_release(plan,path,digest,store,backend),store

    def test_happy_path_runs_every_stage_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend=FakeBackend();result,store=self.execute(tmp,backend)
            self.assertEqual(result["status"],"PRODUCTION VERIFIED");self.assertEqual(len(backend.calls),15)
            self.assertTrue(result["verification"]["pages_release_preflight"])
            self.assertTrue(result["verification"]["pages_production_deployed"])
            self.assertTrue(result["verification"]["pages_production_parity"])

    def test_remote_main_move_stops_before_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend=FakeBackend("plan_verified")
            with self.assertRaises(ReleaseFailure):self.execute(tmp,backend)
            self.assertNotIn("source_committed",backend.calls)

    def test_event_generation_failure_resumes_after_s1(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan,path,digest=plan_fixture(tmp);store=ReleaseStateStore(Path(tmp),plan["release_id"]);first=FakeBackend("artifacts_generated")
            with self.assertRaises(ReleaseFailure):publish_release(plan,path,digest,store,first)
            second=FakeBackend();publish_release(plan,path,digest,store,second)
            self.assertNotIn("source_committed",second.calls);self.assertIn("artifacts_generated",second.calls)

    def test_ci_failure_is_not_treated_as_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ReleaseFailure,"fixture failure"):self.execute(tmp,FakeBackend("validate_verified"))

    def test_hostinger_lag_resumes_without_repush_or_redeploy(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan,path,digest=plan_fixture(tmp);store=ReleaseStateStore(Path(tmp),plan["release_id"]);first=FakeBackend("website_production_verified")
            with self.assertRaises(ReleaseFailure):publish_release(plan,path,digest,store,first)
            second=FakeBackend();publish_release(plan,path,digest,store,second)
            self.assertNotIn("dataset_pushed",second.calls);self.assertNotIn("pages_release_preflight_verified",second.calls);self.assertEqual(second.calls[0],"website_production_verified")

    def test_hf_dry_run_failure_blocks_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend=FakeBackend("hf_dry_run_verified")
            with self.assertRaises(ReleaseFailure):self.execute(tmp,backend)
            self.assertNotIn("hf_publish_verified",backend.calls)

    def test_hf_successful_publish_is_not_repeated_after_parity_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan,path,digest=plan_fixture(tmp);store=ReleaseStateStore(Path(tmp),plan["release_id"]);first=FakeBackend("hf_production_verified")
            with self.assertRaises(ReleaseFailure):publish_release(plan,path,digest,store,first)
            second=FakeBackend();publish_release(plan,path,digest,store,second)
            self.assertEqual(second.calls,["hf_production_verified"])

    def test_existing_tag_stage_is_not_repeated(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan,path,digest=plan_fixture(tmp);store=ReleaseStateStore(Path(tmp),plan["release_id"]);first=FakeBackend("validate_verified")
            with self.assertRaises(ReleaseFailure):publish_release(plan,path,digest,store,first)
            second=FakeBackend();publish_release(plan,path,digest,store,second)
            self.assertNotIn("tag_pushed",second.calls)

    def test_existing_remote_tag_is_never_accepted_or_moved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);website=root/"website";website.mkdir();plan,path,digest=plan_fixture(tmp);artifact="4"*40
            backend=ShellBackend(root,website,path,digest)
            def fake_run(args,cwd):
                if args[:3]==["git","ls-remote","--tags"]:return artifact+"\trefs/tags/"+release_tag_name(plan)
                raise AssertionError(args)
            with patch("scripts.daily_pricing_release.git",return_value=""),patch.object(backend,"_run",side_effect=fake_run):
                with self.assertRaisesRegex(ReleaseFailure,"REFUSING TO MOVE OR OVERWRITE"):
                    backend.push_tag(plan,artifact,release_tag_name(plan))

    def test_existing_local_tag_is_never_accepted_or_moved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);website=root/"website";website.mkdir();plan,path,digest=plan_fixture(tmp);artifact="4"*40
            backend=ShellBackend(root,website,path,digest)
            with patch("scripts.daily_pricing_release.git",return_value=artifact),patch.object(backend,"_run",return_value=""):
                with self.assertRaisesRegex(ReleaseFailure,"REFUSING TO MOVE OR OVERWRITE"):
                    backend.push_tag(plan,artifact,release_tag_name(plan))

    def test_pre_tag_failure_blocks_tag_validate_and_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend=FakeBackend("pre_tag_verified")
            with self.assertRaises(ReleaseFailure):self.execute(tmp,backend)
            self.assertNotIn("tag_pushed",backend.calls);self.assertNotIn("validate_verified",backend.calls);self.assertNotIn("pages_release_preflight_verified",backend.calls)

    def test_website_dataset_parity_failure_blocks_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);website=root/"website";website.mkdir();plan,path,digest=plan_fixture(tmp);backend=ShellBackend(root,website,path,digest)
            with patch("scripts.check_release_gate.verify_local"),patch.object(backend,"_remote_main",side_effect=["4"*40,"5"*40]),patch.object(backend,"_run",side_effect=ReleaseFailure("VALIDATION_SCRIPT_FAILURE","pre_tag_verified","fixture")):
                with self.assertRaisesRegex(ReleaseFailure,"PRICING V2 PARITY FAILED"):
                    backend.verify_pre_tag(plan,digest,"3"*40,"4"*40,"5"*40)

    def test_official_tag_path_has_no_force_update(self):
        source=Path(__file__).resolve().parents[1]/"scripts/daily_pricing_release.py"
        text=source.read_text(encoding="utf-8")
        self.assertNotIn('"--force"',text);self.assertNotIn('"-f", "refs/tags/',text)

    def test_dispatched_workflows_keep_distinct_failure_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);website=root/"website";website.mkdir();plan,path,digest=plan_fixture(tmp);backend=ShellBackend(root,website,path,digest)
            cases=[("deploy-pages.yml",None,"release","pages_release_preflight_verified"),("publish-huggingface.yml",["dry_run=true"],"dry","hf_dry_run_verified"),("publish-huggingface.yml",["dry_run=false"],"publish","hf_publish_verified")]
            for workflow,extra,suffix,stage in cases:
                state={"workflow_run_ids":{f"{workflow}:{suffix}":7}}
                with patch.object(backend,"_wait_run_id",return_value={}) as wait:
                    backend._dispatch(workflow,state,plan,extra)
                    wait.assert_called_once_with(7,stage)

    def test_pages_workflow_success_without_deploy_or_parity_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);website=root/"website";website.mkdir();plan,path,digest=plan_fixture(tmp);backend=ShellBackend(root,website,path,digest)
            push_only={"conclusion":"success","jobs":[{"name":"build","conclusion":"success","steps":[]},{"name":"release-preflight","conclusion":"skipped","steps":[]},{"name":"deploy","conclusion":"skipped","steps":[]}]}
            with patch.object(backend,"_dispatch",return_value=push_only):
                with self.assertRaisesRegex(ReleaseFailure,"without complete preflight/deploy/production parity evidence"):
                    backend.deploy_pages({},plan)

    def test_pages_manual_release_requires_successful_deploy_and_parity_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);website=root/"website";website.mkdir();plan,path,digest=plan_fixture(tmp);backend=ShellBackend(root,website,path,digest)
            release={"conclusion":"success","jobs":[{"name":"release-preflight","conclusion":"success","steps":[]},{"name":"deploy","conclusion":"success","steps":[{"name":"Deploy approved Pages artifact","conclusion":"success"},{"name":"Verify public Pages deployment","conclusion":"success"}]}]}
            with patch.object(backend,"_dispatch",return_value=release):
                evidence=backend.deploy_pages({},plan)
            self.assertTrue(evidence["release_preflight_verified"])
            self.assertTrue(evidence["production_deployed"])
            self.assertTrue(evidence["production_parity_verified"])

    def test_modified_plan_cannot_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan,path,digest=plan_fixture(tmp);store=ReleaseStateStore(Path(tmp),plan["release_id"]);write_json(path,{**plan,"generated_at":"changed"})
            with self.assertRaisesRegex(ReleaseFailure,"identity does not match"):publish_release(plan,path,digest,store,FakeBackend())


if __name__=="__main__":unittest.main()
