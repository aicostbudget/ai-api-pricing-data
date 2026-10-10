"""Verify reviewed immutable release identity; never deploy or publish."""
import argparse
import csv
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
    return {"artifact_sha":artifact,"source_sha":source,"website_sha":website,"release_tag":tag}

def assert_bundle_identity(manifest, identity):
    if manifest.get("source_scope") not in (None, "COMMITTED") or manifest.get("status") != "release":
        raise GateError("Formal release rejects LOCAL_CANDIDATE or unqualified bundles")
    if manifest.get("git_commit") != identity["artifact_sha"] or manifest.get("website_source", {}).get("git_commit") != identity["website_sha"] or manifest.get("release_version") != identity["release_tag"]:
        raise GateError("Manifest artifact/consumer/tag identity mismatch")
    if manifest.get("projections", {}).get("pricing_v2", {}).get("export_schema") != "1.10.0":
        raise GateError("Release public contract must be 1.10.0")

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
    assert_clean_checkout(root, website_repo)
    assert_clean_checkout(website_repo)
    def git(repo,*args): return subprocess.check_output(["git",*args],cwd=repo)
    if git(root,"rev-parse","HEAD").decode().strip()!=identity["artifact_sha"] or git(website_repo,"rev-parse","HEAD").decode().strip()!=identity["website_sha"]:
        raise GateError("Checkout SHA differs from approved committed input")
    if git(root,"show",identity["source_sha"]+":data/canonical/models.json") != git(root,"show",identity["artifact_sha"]+":data/canonical/models.json"):
        raise GateError("Artifact commit altered authoritative source facts")
    pages,source,artifact = committed_pages(identity["artifact_sha"])
    if (source,artifact)!=(identity["source_sha"],identity["artifact_sha"]): raise GateError("Committed API provenance differs from approved source/artifact")
    meta=json.loads(pages["api/v1/meta.json"]);snapshot=meta["generated_at"][:10]
    files=bundle.build_contents(identity["artifact_sha"],website_repo,identity["website_sha"],snapshot,identity["release_tag"],release_date)
    manifest=bundle.verify_contents(files);assert_bundle_identity(manifest,identity)
    if manifest["projections"]["github_pages_v1"]["records"]!=88 or manifest["projections"]["pricing_v2"]["records"]!=86:
        raise GateError("Approved pricing universe changed; re-review required")
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
