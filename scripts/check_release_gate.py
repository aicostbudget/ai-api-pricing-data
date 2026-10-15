"""Verify reviewed immutable release identity; never deploy or publish."""
import argparse
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    from review_gate import DATASET_REPO, WEBSITE_REPO, GateError, GitHubReader, exact_sha, require_manual_dispatch
except ModuleNotFoundError:
    from scripts.review_gate import DATASET_REPO, WEBSITE_REPO, GateError, GitHubReader, exact_sha, require_manual_dispatch

PLAN_SCHEMA = "aicostbudget-daily-pricing-release-plan-v1"

def canonical_bytes(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode("utf-8")

def row_identity(row):
    provider=row.get("provider_id") or row.get("provider");model=row.get("model_id") or row.get("id")
    if not isinstance(provider,str) or not isinstance(model,str) or not provider or not model: raise GateError("Pricing row lacks provider/model identity")
    return provider+"/"+model

def row_digests(rows):
    result={}
    for row in rows:
        identity=row_identity(row)
        if identity in result: raise GateError("Duplicate pricing identity: "+identity)
        result[identity]=hashlib.sha256(canonical_bytes(row)).hexdigest()
    return dict(sorted(result.items()))

def load_approved_plan(root,plan_id,digest):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}",plan_id or ""): raise GateError("Approved release plan ID is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}",digest or ""): raise GateError("Approved release plan digest is invalid")
    path=Path(root)/"release-plans"/(plan_id+".json")
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest: raise GateError("Approved release plan file/digest mismatch")
    plan=json.loads(path.read_text(encoding="utf-8"))
    if plan.get("schema")!=PLAN_SCHEMA or plan.get("release_id")!=plan_id: raise GateError("Approved release plan identity mismatch")
    return plan

def load_committed_approved_plan(root,plan_id,digest,source_sha,artifact_sha):
    """Load the exact approved plan only when the same bytes exist in S1 and S2."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}",plan_id or "") or not re.fullmatch(r"[0-9a-f]{64}",digest or ""):
        raise GateError("RELEASE PLAN MISSING — FORMAL TAG CREATION BLOCKED")
    path="release-plans/"+plan_id+".json"
    def committed(revision):
        try:
            return subprocess.check_output(["git","show",revision+":"+path],cwd=root,stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            raise GateError("RELEASE PLAN MISSING — FORMAL TAG CREATION BLOCKED") from None
    source_bytes=committed(source_sha);artifact_bytes=committed(artifact_sha)
    if source_bytes!=artifact_bytes or hashlib.sha256(source_bytes).hexdigest()!=digest:
        raise GateError("RELEASE PLAN MISSING — FORMAL TAG CREATION BLOCKED")
    try: plan=json.loads(source_bytes.decode("utf-8"))
    except (UnicodeDecodeError,json.JSONDecodeError):
        raise GateError("RELEASE PLAN MISSING — FORMAL TAG CREATION BLOCKED") from None
    if plan.get("schema")!=PLAN_SCHEMA or plan.get("release_id")!=plan_id:
        raise GateError("RELEASE PLAN MISSING — FORMAL TAG CREATION BLOCKED")
    return plan

def assert_local_release_identity(identity,read_blob,is_ancestor):
    source=exact_sha(identity.get("source_sha"),"Source SHA")
    artifact=exact_sha(identity.get("artifact_sha"),"Artifact SHA")
    website=exact_sha(identity.get("website_sha"),"Website SHA")
    if source==artifact: raise GateError("SOURCE AND ARTIFACT SHA MUST BE DISTINCT")
    if not is_ancestor(source,artifact): raise GateError("SOURCE SHA IS NOT A VALID ANCESTOR OF ARTIFACT SHA")
    canonical=read_blob(source,"data/canonical/models.json")
    if canonical!=read_blob(artifact,"data/canonical/models.json"):
        raise GateError("ARTIFACT COMMIT ALTERED AUTHORITATIVE SOURCE FACTS")
    try: meta=json.loads(read_blob(artifact,"api/v1/meta.json"))
    except (UnicodeDecodeError,json.JSONDecodeError):
        raise GateError("PUBLIC ARTIFACT SOURCE PROVENANCE MISMATCH") from None
    if meta.get("source_commit_sha")!=source:
        raise GateError("PUBLIC ARTIFACT SOURCE PROVENANCE MISMATCH")
    return source,artifact,website,canonical

def check_release(context, get, kind):
    if kind not in ("pages", "hf"): raise GateError("Unknown release kind")
    environment = "github-pages" if kind == "pages" else "hf-release-review"
    current_sha = require_manual_dispatch(context, get, environment, "main")
    artifact = exact_sha(context.get("ARTIFACT_SHA"), "Artifact SHA")
    source = exact_sha(context.get("SOURCE_SHA"), "Source SHA")
    website = exact_sha(context.get("WEBSITE_SHA"), "Website SHA")
    if artifact != current_sha or artifact == source: raise GateError("Dispatch artifact identity must match current commit and differ from source")
    tag = context.get("RELEASE_TAG", "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", tag) or ".." in tag or tag.endswith("/"):
        raise GateError("An explicit real release tag is required")
    prefix = "/repos/" + DATASET_REPO
    if get(prefix + "/git/ref/heads/main", "dataset")["object"]["sha"] != artifact:
        raise GateError("Dataset main moved or artifact is not approved main")
    if get("/repos/" + WEBSITE_REPO + "/git/ref/heads/main", "website")["object"]["sha"] != website:
        raise GateError("Website main does not match approved committed consumer")
    ref = get(prefix + "/git/ref/tags/" + quote(tag, safe=""), "dataset")
    if ref.get("ref") != "refs/tags/" + tag: raise GateError("Release tag identity mismatch")
    target = ref["object"]
    for _ in range(4):
        if target.get("type") == "commit": break
        if target.get("type") != "tag": raise GateError("Release tag does not resolve to a commit")
        target = get(prefix + "/git/tags/" + exact_sha(target.get("sha"), "Annotated tag object"), "dataset")["object"]
    if target.get("type") != "commit" or target.get("sha") != artifact: raise GateError("Release tag must resolve to approved artifact SHA")
    ancestry = get(prefix + "/compare/" + source + "..." + artifact, "dataset")
    if ancestry.get("status") != "ahead" or ancestry.get("merge_base_commit", {}).get("sha") != source:
        raise GateError("Real source must be a distinct ancestor of artifact commit")
    plan_id=context.get("RELEASE_PLAN_ID","");plan_digest=context.get("RELEASE_PLAN_DIGEST","")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}",plan_id) or not re.fullmatch(r"[0-9a-f]{64}",plan_digest): raise GateError("Exact approved release plan identity is required")
    return {"artifact_sha":artifact,"source_sha":source,"website_sha":website,"release_tag":tag,"release_plan_id":plan_id,"release_plan_digest":plan_digest}

def assert_bundle_identity(manifest, identity):
    if manifest.get("source_scope") not in (None, "COMMITTED") or manifest.get("status") != "release":
        raise GateError("Formal release rejects LOCAL_CANDIDATE or unqualified bundles")
    if manifest.get("git_commit") != identity["artifact_sha"] or manifest.get("website_source", {}).get("git_commit") != identity["website_sha"] or manifest.get("release_version") != identity["release_tag"]:
        raise GateError("Manifest artifact/consumer/tag identity mismatch")
    if manifest.get("projections", {}).get("pricing_v2", {}).get("export_schema") != "1.10.0":
        raise GateError("Release public contract must be 1.10.0")

def assert_approved_pricing_universe(manifest, files, plan):
    v1 = json.loads(files["github-pages-v1-prices.json"])["models"]
    v2 = json.loads(files["pricing-v2-prices.json"])["records"]
    contracts=plan.get("projection_contracts",{})
    for key,name,rows,manifest_key in (("v1","GitHub Pages V1",v1,"github_pages_v1"),("v2","Pricing V2/HF",v2,"pricing_v2")):
        contract=contracts.get(key,{})
        if manifest["projections"][manifest_key]["records"]!=contract.get("records") or len(rows)!=contract.get("records") or row_digests(rows)!=contract.get("row_digests"):
            raise GateError(name+" differs from the approved release plan")

def assert_clean_checkout(repo, nested_checkout=None, reader=None):
    repo = Path(repo).resolve()
    if reader is None:
        reader = lambda *args: subprocess.check_output(["git", *args], cwd=repo).decode("utf-8")
    if Path(reader("rev-parse", "--show-toplevel").strip()).resolve() != repo:
        raise GateError("Release input is not the expected genuine checkout root")
    allowed = None
    if nested_checkout is not None:
        nested = Path(nested_checkout).resolve()
        if nested.parent != repo or nested.name != "website-source": raise GateError("Unexpected nested consumer checkout")
        allowed = "website-source/"
    entries = [e for e in reader("status", "--porcelain=v1", "-z", "--untracked-files=all").split("\0") if e]
    if any(not (allowed and e[:2] == "??" and e[3:] == allowed) for e in entries):
        raise GateError("Formal release inputs must be clean; never clean the original candidate/user workspace")

def verify_local(identity, website_repo, release_date, output=None):
    from scripts import build_release_bundle as bundle
    from scripts.prepare_pages_artifact import committed_pages
    root = Path(__file__).resolve().parents[1]
    website_repo=Path(website_repo).resolve()
    nested=website_repo if website_repo.parent==root.resolve() and website_repo.name=="website-source" else None
    assert_clean_checkout(root, nested)
    assert_clean_checkout(website_repo)
    def git(repo,*args): return subprocess.check_output(["git",*args],cwd=repo,stderr=subprocess.DEVNULL)
    read_blob=lambda revision,path:git(root,"show",revision+":"+path)
    is_ancestor=lambda source,artifact:subprocess.run(["git","merge-base","--is-ancestor",source,artifact],cwd=root,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
    source,artifact,website,canonical=assert_local_release_identity(identity,read_blob,is_ancestor)
    if git(root,"rev-parse","HEAD").decode().strip()!=identity["artifact_sha"] or git(website_repo,"rev-parse","HEAD").decode().strip()!=identity["website_sha"]:
        raise GateError("Checkout SHA differs from approved committed input")
    plan=load_committed_approved_plan(root,identity["release_plan_id"],identity["release_plan_digest"],source,artifact)
    if hashlib.sha256(canonical).hexdigest()!=plan.get("canonical_sha256"): raise GateError("Canonical differs from the approved release plan")
    if plan.get("dataset_base_sha")!=git(root,"rev-parse",identity["source_sha"]+"^").decode().strip() or plan.get("website_base_sha")!=git(website_repo,"rev-parse",identity["website_sha"]+"^").decode().strip():
        raise GateError("Release commits do not descend directly from approved plan baselines")
    pages,meta_source,meta_artifact = committed_pages(identity["artifact_sha"])
    if (meta_source,meta_artifact)!=(source,artifact): raise GateError("PUBLIC ARTIFACT SOURCE PROVENANCE MISMATCH")
    meta=json.loads(pages["api/v1/meta.json"]);snapshot=meta["generated_at"][:10]
    files=bundle.build_contents(identity["artifact_sha"],website_repo,identity["website_sha"],snapshot,identity["release_tag"],release_date)
    manifest=bundle.verify_contents(files);assert_bundle_identity(manifest,identity)
    assert_approved_pricing_universe(manifest,files,plan)
    if output: bundle.write_bundle(files,output)
    return manifest

def expected_website_export(website_repo):
    # Actual committed Website serializer, not a second Python imitation.
    script = """(async()=>{const fs=require('fs');const {testRuntime}=await import('./scripts/issue26-contract-fixtures.mjs');const p=JSON.parse(fs.readFileSync('data/pricing-v2-projection/model-pricing.v2.json','utf8'));const load=testRuntime(p);const api=load('src/lib/ai-api-pricing-data.ts');const v=load('src/lib/pricing-version.ts');console.log(JSON.stringify({json:api.getDatasetExport(),csv:api.datasetRecordsToCsv(),version:{pricing_fingerprint:v.getPricingFingerprint(),schema_version:v.PRICING_FINGERPRINT_SCHEMA_VERSION}}));})();"""
    return json.loads(subprocess.check_output(["node","-e",script],cwd=website_repo))

def fetch_public(url):
    with urlopen(Request(url,headers={"Cache-Control":"no-cache"}),timeout=20) as response:
        return response.status,response.headers.get("Content-Type",""),response.read()

def verify_production(expected, fetch=fetch_public):
    base="https://aicostbudget.com"
    for suffix,ctype in [("json","application/json"),("csv","text/csv")]:
        status,content_type,body=fetch(base+"/api/datasets/ai-api-pricing."+suffix)
        if status!=200 or ctype not in content_type: raise GateError("Production Website HTTP/content-type failed")
        if suffix=="json":
            if json.loads(body)!=expected["json"]: raise GateError("Production JSON differs from committed Website consumer")
        else:
            rows=lambda text:list(csv.DictReader(io.StringIO(text,newline="")))
            if rows(body.decode("utf-8-sig"))!=rows(expected["csv"]): raise GateError("Production CSV fields differ from committed Website consumer")
    status,ctype,body=fetch(base+"/api/pricing-version")
    if status!=200 or "application/json" not in ctype or json.loads(body)!=expected["version"]:
        raise GateError("Production pricing fingerprint does not match committed consumer")

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind",choices=["pages","hf"],required=True)
    parser.add_argument("--verify-local",action="store_true")
    parser.add_argument("--verify-production",action="store_true")
    parser.add_argument("--website-repo",type=Path)
    parser.add_argument("--bundle-output",type=Path)
    args=parser.parse_args()
    identity=check_release(os.environ,GitHubReader(os.environ),args.kind)
    if args.verify_local:
        if not args.website_repo: raise GateError("Committed Website checkout is required")
        verify_local(identity,args.website_repo,os.environ.get("RELEASE_DATE"),args.bundle_output)
    if args.verify_production:
        if not args.verify_local: raise GateError("Production parity requires prior committed bundle verification")
        verify_production(expected_website_export(args.website_repo))
    print("Reviewed release preflight verified: "+json.dumps(identity))

if __name__=="__main__": main()
