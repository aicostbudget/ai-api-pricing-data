"""Fail-closed gate used only by explicitly selected Forward Recovery."""
from __future__ import annotations

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
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from review_gate import DATASET_REPO, WEBSITE_REPO, GateError, GitHubReader, exact_sha, require_manual_dispatch
except ModuleNotFoundError:
    from scripts.review_gate import DATASET_REPO, WEBSITE_REPO, GateError, GitHubReader, exact_sha, require_manual_dispatch

from scripts.forward_recovery import (
    RecoveryContractError,
    load_committed_recovery_plan,
    recovery_tag_name,
    validate_projection_contract,
    validate_recovery_chain,
    validate_website_reuse_contract,
)


def canonical_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def assert_local_release_identity(identity, read_blob, is_ancestor):
    source = exact_sha(identity.get("source_sha"), "Recovery source SHA")
    artifact = exact_sha(identity.get("artifact_sha"), "Recovery artifact SHA")
    website = exact_sha(identity.get("website_sha"), "Recovery Website SHA")
    if source == artifact:
        raise GateError("Recovery source and artifact revisions must be distinct")
    if not is_ancestor(source, artifact):
        raise GateError("Recovery source revision is not an ancestor of its artifact revision")
    canonical = read_blob(source, "data/canonical/models.json")
    if canonical != read_blob(artifact, "data/canonical/models.json"):
        raise GateError("ARTIFACT COMMIT ALTERED AUTHORITATIVE SOURCE FACTS")
    try:
        meta = json.loads(read_blob(artifact, "api/v1/meta.json"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise GateError("Recovery public provenance is invalid") from None
    if meta.get("source_commit_sha") != source:
        raise GateError("Recovery public provenance does not identify its source revision")
    return source, artifact, website, canonical


def check_recovery_release(context, get, kind):
    if kind not in ("pages", "hf"):
        raise GateError("Unknown release kind")
    environment = "github-pages" if kind == "pages" else "hf-release-review"
    current_sha = require_manual_dispatch(context, get, environment, "main")
    source = exact_sha(context.get("RECOVERY_SOURCE_SHA"), "Recovery source SHA")
    artifact = exact_sha(context.get("RECOVERY_ARTIFACT_SHA"), "Recovery artifact SHA")
    website = exact_sha(context.get("RECOVERY_WEBSITE_SHA"), "Recovery Website SHA")
    if current_sha != artifact or source == artifact:
        raise GateError("Recovery dispatch identity does not match its artifact revision")
    recovery_id = context.get("RECOVERY_ID", "")
    digest = context.get("RECOVERY_DIGEST", "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", recovery_id or ""):
        raise GateError("Exact Recovery identity is required")
    if not re.fullmatch(r"[0-9a-f]{64}", digest or ""):
        raise GateError("Exact Recovery digest is required")
    if get(f"/repos/{DATASET_REPO}/git/ref/heads/main", "dataset")["object"]["sha"] != artifact:
        raise GateError("Dataset main moved from the approved Recovery artifact")
    if get(f"/repos/{WEBSITE_REPO}/git/ref/heads/main", "website")["object"]["sha"] != website:
        raise GateError("Website main moved from the approved Recovery consumer")
    return {
        "source_sha": source, "artifact_sha": artifact, "website_sha": website,
        "recovery_id": recovery_id, "recovery_digest": digest,
    }


def assert_clean_checkout(repo, nested_checkout=None, reader=None):
    repo = Path(repo).resolve()
    if reader is None:
        reader = lambda *args: subprocess.check_output(["git", *args], cwd=repo).decode("utf-8")
    if Path(reader("rev-parse", "--show-toplevel").strip()).resolve() != repo:
        raise GateError("Recovery input is not the expected checkout root")
    allowed = None
    if nested_checkout is not None:
        nested = Path(nested_checkout).resolve()
        if nested.parent != repo or nested.name != "website-source":
            raise GateError("Unexpected nested Website checkout")
        allowed = "website-source/"
    entries = [entry for entry in reader("status", "--porcelain=v1", "-z", "--untracked-files=all").split("\0") if entry]
    if any(not (allowed and entry[:2] == "??" and entry[3:] == allowed) for entry in entries):
        raise GateError("Recovery inputs must be clean")


def assert_recovery_pricing_universe(files, plan):
    try:
        v1 = json.loads(files["github-pages-v1-prices.json"])["models"]
        v2 = json.loads(files["pricing-v2-prices.json"])["records"]
        contracts = plan["projection_contracts"]
        validate_projection_contract(contracts["pages_v1"], v1, files["github-pages-v1-prices.json"], files["github-pages-v1-prices.csv"], "Pages V1")
        validate_projection_contract(contracts["pricing_v2_hf"], v2, files["pricing-v2-prices.json"], files["pricing-v2-prices.csv"], "Pricing V2/HF")
    except (KeyError, TypeError, RecoveryContractError) as error:
        raise GateError(str(error)) from None


def verify_recovery_local(identity, website_repo, release_date=None, output=None):
    from scripts import build_release_bundle as bundle
    from scripts.prepare_pages_artifact import recovery_committed_pages
    website_repo = Path(website_repo).resolve()
    nested = website_repo if website_repo.parent == ROOT.resolve() and website_repo.name == "website-source" else None
    assert_clean_checkout(ROOT, nested)
    assert_clean_checkout(website_repo)

    def git(repo, *args):
        return subprocess.check_output(["git", *args], cwd=repo, stderr=subprocess.DEVNULL)

    read_blob = lambda revision, path: git(ROOT, "show", revision + ":" + path)
    source, artifact, website, canonical = assert_local_release_identity(
        identity, read_blob,
        lambda before, after: subprocess.run(["git", "merge-base", "--is-ancestor", before, after], cwd=ROOT).returncode == 0,
    )
    read_committed = lambda revision, path: git(ROOT, "show", revision + ":" + path)
    try:
        plan, source_plan, artifact_plan = load_committed_recovery_plan(
            ROOT, identity["recovery_id"], identity["recovery_digest"], source, artifact, read_committed,
        )
        validate_recovery_chain(
            plan, source_plan, artifact_plan, identity["recovery_digest"], source, artifact,
            lambda revision: git(ROOT, "rev-parse", revision + "^").decode().strip(),
            read_committed,
            lambda before, after: git(ROOT, "diff", "--name-only", before, after).decode().splitlines(),
            lambda tag: git(ROOT, "rev-parse", "refs/tags/" + tag).decode().strip(),
            lambda tag: git(ROOT, "rev-parse", "refs/tags/" + tag + "^{}").decode().strip(),
        )
    except (subprocess.CalledProcessError, RecoveryContractError) as error:
        raise GateError(str(error)) from None
    if hashlib.sha256(canonical).hexdigest() != plan["canonical_sha256"]:
        raise GateError("Recovery canonical digest changed")
    expected = expected_website_export(website_repo)
    contract = plan["website_contract"]
    try:
        validate_website_reuse_contract(contract, expected, website, git(website_repo, "rev-parse", website + "^").decode().strip())
    except RecoveryContractError as error:
        raise GateError(str(error)) from None
    if identity.get("release_tag", recovery_tag_name(plan)) != recovery_tag_name(plan):
        raise GateError("Recovery tag differs from the approved identity")
    pages, meta_source, meta_artifact = recovery_committed_pages(artifact)
    if (meta_source, meta_artifact) != (source, artifact):
        raise GateError("Recovery public provenance mismatch")
    snapshot = json.loads(pages["api/v1/meta.json"])["generated_at"][:10]
    tag = recovery_tag_name(plan)
    files = bundle.build_contents(artifact, website_repo, website, snapshot, tag, release_date)
    manifest = bundle.verify_contents(files)
    assert_recovery_pricing_universe(files, plan)
    if output:
        bundle.write_bundle(files, output)
    return manifest


def expected_website_export(website_repo):
    script = """(async()=>{const fs=require('fs');const {testRuntime}=await import('./scripts/issue26-contract-fixtures.mjs');const p=JSON.parse(fs.readFileSync('data/pricing-v2-projection/model-pricing.v2.json','utf8'));const load=testRuntime(p);const api=load('src/lib/ai-api-pricing-data.ts');const v=load('src/lib/pricing-version.ts');console.log(JSON.stringify({json:api.getDatasetExport(),csv:api.datasetRecordsToCsv(),version:{pricing_fingerprint:v.getPricingFingerprint(),schema_version:v.PRICING_FINGERPRINT_SCHEMA_VERSION}}));})();"""
    return json.loads(subprocess.check_output(["node", "-e", script], cwd=website_repo))


def fetch_public(url):
    with urlopen(Request(url, headers={"Cache-Control": "no-cache"}), timeout=20) as response:
        return response.status, response.headers.get("Content-Type", ""), response.read()


def verify_production(expected, fetch=fetch_public, approved_contract=None):
    base = "https://aicostbudget.com"
    for suffix, content_type in (("json", "application/json"), ("csv", "text/csv")):
        status, actual_type, body = fetch(base + "/api/datasets/ai-api-pricing." + suffix)
        if status != 200 or content_type not in actual_type:
            raise GateError("Production Website HTTP/content-type failed")
        if suffix == "json":
            actual = json.loads(body)
            if actual != expected["json"]:
                raise GateError("Production JSON differs from committed Website consumer")
            if approved_contract and hashlib.sha256(canonical_bytes(actual)).hexdigest() != approved_contract["production_json_sha256"]:
                raise GateError("Production JSON digest differs from approved Recovery contract")
        else:
            rows = lambda text: list(csv.DictReader(io.StringIO(text, newline="")))
            if rows(body.decode("utf-8-sig")) != rows(expected["csv"]):
                raise GateError("Production CSV differs from committed Website consumer")
            if approved_contract and hashlib.sha256(body).hexdigest() != approved_contract["production_csv_sha256"]:
                raise GateError("Production CSV digest differs from approved Recovery contract")
    status, actual_type, body = fetch(base + "/api/pricing-version")
    version = json.loads(body) if status == 200 and "application/json" in actual_type else None
    if version != expected["version"]:
        raise GateError("Production pricing fingerprint does not match committed consumer")
    if approved_contract and (
        version.get("pricing_fingerprint") != approved_contract["pricing_fingerprint"]
        or version.get("schema_version") != approved_contract["schema_version"]
        or hashlib.sha256(canonical_bytes(version)).hexdigest() != approved_contract["pricing_manifest_sha256"]
    ):
        raise GateError("Production pricing manifest differs from approved Recovery contract")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=["pages", "hf"], required=True)
    parser.add_argument("--recovery", action="store_true", required=True)
    args = parser.parse_args()
    identity = check_recovery_release(os.environ, GitHubReader(os.environ), args.kind)
    print("Forward Recovery preflight verified: " + json.dumps(identity))


if __name__ == "__main__":
    main()
