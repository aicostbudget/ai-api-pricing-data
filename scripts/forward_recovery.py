"""Fail-closed contracts for a new forward-only recovery release identity."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


RECOVERY_PLAN_SCHEMA = "aicostbudget-forward-recovery-plan-v1"
RECOVERY_STATE_SCHEMA = "aicostbudget-forward-recovery-state-v1"
DATASET_REPO = "aicostbudget/ai-api-pricing-data"
WEBSITE_REPO = "linqiang-max/aicostbudget"
PLAN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
SHA_RE = re.compile(r"[0-9a-f]{40}")
DIGEST_RE = re.compile(r"[0-9a-f]{64}")

HISTORICAL_FIELDS = {
    "historical_source_sha",
    "historical_artifact_sha",
    "historical_tag",
    "historical_tag_object_sha",
    "historical_tag_target_sha",
    "legacy_identity_status",
    "legacy_plan_status",
    "expected_stale_pages_identity",
    "expected_stale_hf_identity",
}
PROJECTION_FIELDS = {
    "record_count",
    "provider_count",
    "provider_ids",
    "model_ids",
    "row_digests",
    "json_sha256",
    "csv_sha256",
}
WEBSITE_REUSE_FIELDS = {
    "mode",
    "website_sha",
    "website_parent_sha",
    "schema_version",
    "production_json_sha256",
    "production_csv_sha256",
    "pricing_fingerprint",
    "pricing_manifest_sha256",
}
RECOVERY_ARTIFACT_EXACT = {
    "README.md",
    "api/v1/meta.json",
    "api/v1/prices.json",
    "api/v1/prices.csv",
    "data/prices.json",
    "data/prices.csv",
    "data/price-change-events/events.jsonl",
    "huggingface/prices.json",
    "huggingface/prices.csv",
    "huggingface/train.csv",
    "huggingface/meta.json",
    "huggingface-history/price_snapshots.csv",
    "huggingface-history/price_changes.csv",
}
RECOVERY_ARTIFACT_PREFIXES = (
    "api/v1/models/",
    "api/v1/providers/",
    "data/models/",
    "data/providers/",
    "data/history/",
    "data/pricing-v2-preview/",
    "data/snapshots/",
)


class RecoveryContractError(ValueError):
    """The approved recovery identity or its evidence is incomplete or changed."""


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _required(mapping: Mapping[str, Any], fields: set[str], label: str) -> None:
    missing = sorted(field for field in fields if field not in mapping)
    if missing:
        raise RecoveryContractError(f"{label} missing required fields: {', '.join(missing)}")


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise RecoveryContractError(f"{label} must be an exact lowercase commit SHA")
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not DIGEST_RE.fullmatch(value):
        raise RecoveryContractError(f"{label} must be an exact lowercase SHA-256")
    return value


def _utc(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        raise RecoveryContractError(f"{label} must be an explicit UTC timestamp")
    return value


def row_identity(row: Mapping[str, Any]) -> str:
    provider = row.get("provider_id") or row.get("provider")
    model = row.get("model_id") or row.get("id")
    if not isinstance(provider, str) or not provider or not isinstance(model, str) or not model:
        raise RecoveryContractError("Pricing row lacks provider/model identity")
    return f"{provider}/{model}"


def projection_contract(rows: Iterable[Mapping[str, Any]], json_bytes: bytes, csv_bytes: bytes) -> dict[str, Any]:
    rows = list(rows)
    identities: dict[str, str] = {}
    providers: set[str] = set()
    for row in rows:
        identity = row_identity(row)
        if identity in identities:
            raise RecoveryContractError(f"Duplicate pricing identity: {identity}")
        providers.add(identity.split("/", 1)[0])
        identities[identity] = sha256_bytes(canonical_bytes(row))
    csv_rows = list(csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig"), newline="")))
    csv_ids = [row_identity(row) for row in csv_rows]
    if len(csv_ids) != len(set(csv_ids)) or set(csv_ids) != set(identities):
        raise RecoveryContractError("Projection JSON/CSV identity sets differ")
    return {
        "record_count": len(rows),
        "provider_count": len(providers),
        "provider_ids": sorted(providers),
        "model_ids": sorted(identities),
        "row_digests": dict(sorted(identities.items())),
        "json_sha256": sha256_bytes(json_bytes),
        "csv_sha256": sha256_bytes(csv_bytes),
    }


def website_contract_from_export(expected: Mapping[str, Any], website_sha: str, website_parent_sha: str) -> dict[str, Any]:
    version = expected.get("version", {})
    manifest = expected.get("manifest", version)
    return {
        "mode": "reuse",
        "website_sha": _sha(website_sha, "Website SHA"),
        "website_parent_sha": _sha(website_parent_sha, "Website parent SHA"),
        "schema_version": version.get("schema_version"),
        "production_json_sha256": sha256_bytes(canonical_bytes(expected.get("json"))),
        "production_csv_sha256": sha256_bytes(str(expected.get("csv", "")).encode("utf-8")),
        "pricing_fingerprint": version.get("pricing_fingerprint"),
        "pricing_manifest_sha256": sha256_bytes(canonical_bytes(manifest)),
    }


def validate_website_reuse_contract(contract: Mapping[str, Any], expected: Mapping[str, Any], remote_main_sha: str, parent_sha: str) -> None:
    _required(contract, WEBSITE_REUSE_FIELDS, "website_contract")
    if contract.get("mode") != "reuse":
        raise RecoveryContractError("Only explicitly approved Website reuse is supported by this recovery path")
    actual = website_contract_from_export(expected, remote_main_sha, parent_sha)
    if dict(contract) != actual:
        raise RecoveryContractError("Website reuse identity or production digest contract changed")


def validate_projection_contract(contract: Mapping[str, Any], rows: Iterable[Mapping[str, Any]], json_bytes: bytes, csv_bytes: bytes, label: str) -> None:
    _required(contract, PROJECTION_FIELDS, label)
    actual = projection_contract(rows, json_bytes, csv_bytes)
    if dict(contract) != actual:
        raise RecoveryContractError(f"{label} differs from the approved recovery plan")


def validate_recovery_plan(plan: Mapping[str, Any], recovery_id: str | None = None) -> None:
    if plan.get("schema") != RECOVERY_PLAN_SCHEMA:
        raise RecoveryContractError("Recovery plan schema mismatch")
    required = {
        "schema",
        "recovery_id",
        "dataset_base_sha",
        "canonical_sha256",
        "snapshot_generated_at",
        "recovery_created_at",
        "recovery_reason",
        "historical_context",
        "projection_contracts",
        "website_contract",
    }
    _required(plan, required, "recovery plan")
    value = plan.get("recovery_id")
    if not isinstance(value, str) or not PLAN_ID_RE.fullmatch(value) or (recovery_id is not None and value != recovery_id):
        raise RecoveryContractError("Recovery plan identity mismatch")
    _sha(plan.get("dataset_base_sha"), "dataset_base_sha")
    _digest(plan.get("canonical_sha256"), "canonical_sha256")
    _utc(plan.get("snapshot_generated_at"), "snapshot_generated_at")
    _utc(plan.get("recovery_created_at"), "recovery_created_at")
    if not isinstance(plan.get("recovery_reason"), str) or not plan["recovery_reason"].strip():
        raise RecoveryContractError("recovery_reason must be non-empty")
    historical = plan.get("historical_context")
    if not isinstance(historical, Mapping):
        raise RecoveryContractError("historical_context must be an object")
    _required(historical, HISTORICAL_FIELDS, "historical_context")
    for field in ("historical_source_sha", "historical_artifact_sha", "historical_tag_object_sha", "historical_tag_target_sha"):
        _sha(historical.get(field), field)
    if historical["historical_source_sha"] == historical["historical_artifact_sha"] or historical["historical_tag_target_sha"] != historical["historical_artifact_sha"]:
        raise RecoveryContractError("Historical source/artifact/tag target identity is inconsistent")
    if not isinstance(historical.get("historical_tag"), str) or not historical["historical_tag"]:
        raise RecoveryContractError("historical_tag must be non-empty")
    for field in ("expected_stale_pages_identity", "expected_stale_hf_identity"):
        if not isinstance(historical.get(field), Mapping) or not historical[field]:
            raise RecoveryContractError(f"{field} must contain reviewed stale production evidence")
    if historical.get("legacy_identity_status") != "FAIL_CLOSED" or historical.get("legacy_plan_status") != "FAIL_CLOSED":
        raise RecoveryContractError("Historical failures must remain explicitly FAIL_CLOSED")
    contracts = plan.get("projection_contracts")
    if not isinstance(contracts, Mapping) or set(contracts) != {"pages_v1", "pricing_v2_hf"}:
        raise RecoveryContractError("Recovery projection contracts must separately define Pages V1 and Pricing V2/HF")
    for name, contract in contracts.items():
        if not isinstance(contract, Mapping):
            raise RecoveryContractError(f"{name} contract must be an object")
        _required(contract, PROJECTION_FIELDS, name)
    website = plan.get("website_contract")
    if not isinstance(website, Mapping):
        raise RecoveryContractError("website_contract must be an object")
    if website.get("mode") == "reuse":
        _required(website, WEBSITE_REUSE_FIELDS, "website_contract")
        _sha(website.get("website_sha"), "website_sha")
        _sha(website.get("website_parent_sha"), "website_parent_sha")
        for field in ("production_json_sha256", "production_csv_sha256", "pricing_manifest_sha256"):
            _digest(website.get(field), field)
    elif website.get("mode") != "new":
        raise RecoveryContractError("website_contract.mode must be reuse or new")


def recovery_tag_name(plan: Mapping[str, Any]) -> str:
    validate_recovery_plan(plan)
    date = str(plan["snapshot_generated_at"])[:10]
    readable = re.sub(r"[^a-z0-9]+", "-", str(plan["recovery_id"]).lower()).strip("-")[:48]
    collision = sha256_bytes((str(plan["recovery_id"]) + ":" + str(plan["canonical_sha256"])).encode("utf-8"))[:12]
    return f"dataset-recovery-{date}-{readable}-{collision}"


def is_recovery_artifact_path(path: str) -> bool:
    return path in RECOVERY_ARTIFACT_EXACT or path.startswith(RECOVERY_ARTIFACT_PREFIXES)


def assert_recovery_tag_available(plan: Mapping[str, Any], local_ref: str, remote_ref: str) -> str:
    tag = recovery_tag_name(plan)
    if tag == plan["historical_context"]["historical_tag"]:
        raise RecoveryContractError("Recovery must not reuse the historical tag")
    if local_ref or remote_ref:
        raise RecoveryContractError("RECOVERY TAG ALREADY EXISTS - REFUSING TO MOVE OR OVERWRITE")
    return tag


def validate_recovery_chain(
    plan: Mapping[str, Any],
    plan_bytes_s1: bytes,
    plan_bytes_s2: bytes,
    approved_digest: str,
    source_sha: str,
    artifact_sha: str,
    parent_of: Callable[[str], str],
    read_blob: Callable[[str, str], bytes],
    changed_files: Callable[[str, str], Iterable[str]],
    tag_object: Callable[[str], str],
    tag_target: Callable[[str], str],
) -> None:
    validate_recovery_plan(plan)
    _digest(approved_digest, "approved recovery plan digest")
    source_sha = _sha(source_sha, "Recovery S1")
    artifact_sha = _sha(artifact_sha, "Recovery S2")
    base_sha = plan["dataset_base_sha"]
    historical = plan["historical_context"]
    if source_sha in (historical["historical_source_sha"], historical["historical_artifact_sha"]) or artifact_sha in (historical["historical_source_sha"], historical["historical_artifact_sha"]):
        raise RecoveryContractError("Historical commits cannot become the new recovery S1 or S2")
    if plan_bytes_s1 != plan_bytes_s2 or sha256_bytes(plan_bytes_s1) != approved_digest:
        raise RecoveryContractError("Recovery Plan bytes or approved digest differ between S1 and S2")
    try:
        if json.loads(plan_bytes_s1.decode("utf-8")) != dict(plan):
            raise RecoveryContractError("Recovery Plan object differs from the committed approved bytes")
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RecoveryContractError("Recovery Plan bytes are not valid UTF-8 JSON") from None
    if parent_of(source_sha) != base_sha:
        raise RecoveryContractError("Recovery S1 parent must be C0")
    if parent_of(artifact_sha) != source_sha:
        raise RecoveryContractError("Recovery S2 parent must be S1")
    canonical = read_blob(base_sha, "data/canonical/models.json")
    if canonical != read_blob(source_sha, "data/canonical/models.json") or canonical != read_blob(artifact_sha, "data/canonical/models.json"):
        raise RecoveryContractError("Canonical bytes must be identical across C0, S1, and S2")
    if sha256_bytes(canonical) != plan["canonical_sha256"]:
        raise RecoveryContractError("Canonical digest differs from the approved recovery plan")
    plan_path = f"release-plans/{plan['recovery_id']}.json"
    if set(changed_files(base_sha, source_sha)) != {plan_path}:
        raise RecoveryContractError("Recovery S1 must be a plan-only commit")
    s2_files = set(changed_files(source_sha, artifact_sha))
    if not s2_files or any(not is_recovery_artifact_path(path) for path in s2_files):
        raise RecoveryContractError("Recovery S2 must modify only allowlisted generated/public artifacts")
    try:
        metadata = json.loads(read_blob(artifact_sha, "api/v1/meta.json"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RecoveryContractError("Recovery S2 metadata is invalid") from None
    if metadata.get("source_commit_sha") != source_sha:
        raise RecoveryContractError("Recovery S2 metadata source_commit_sha must equal S1")
    if metadata.get("generated_at") != plan["snapshot_generated_at"]:
        raise RecoveryContractError("Recovery must preserve the approved snapshot_generated_at")
    try:
        hf_metadata = json.loads(read_blob(artifact_sha, "huggingface/meta.json"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RecoveryContractError("Recovery S2 Hugging Face metadata is invalid") from None
    if hf_metadata.get("generated_at") != plan["snapshot_generated_at"]:
        raise RecoveryContractError("Recovery Hugging Face metadata must preserve snapshot_generated_at")
    historical_tag = historical["historical_tag"]
    if recovery_tag_name(plan) == historical_tag:
        raise RecoveryContractError("Recovery must not reuse the historical tag")
    if tag_object(historical_tag) != historical["historical_tag_object_sha"] or tag_target(historical_tag) != historical["historical_tag_target_sha"]:
        raise RecoveryContractError("Historical tag object or target changed")


def load_committed_recovery_plan(
    root: Path,
    recovery_id: str,
    digest: str,
    source_sha: str,
    artifact_sha: str,
    read_committed: Callable[[str, str], bytes],
) -> tuple[dict[str, Any], bytes, bytes]:
    if not PLAN_ID_RE.fullmatch(recovery_id or "") or not DIGEST_RE.fullmatch(digest or ""):
        raise RecoveryContractError("Exact approved recovery plan identity is required")
    path = f"release-plans/{recovery_id}.json"
    try:
        source_bytes = read_committed(source_sha, path)
        artifact_bytes = read_committed(artifact_sha, path)
        plan = json.loads(source_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise RecoveryContractError("Committed recovery plan is missing or invalid") from None
    validate_recovery_plan(plan, recovery_id)
    if source_bytes != artifact_bytes or sha256_bytes(source_bytes) != digest:
        raise RecoveryContractError("Committed recovery plan bytes or digest mismatch")
    return plan, source_bytes, artifact_bytes


class ReleaseFailure(RuntimeError):
    def __init__(self, classification: str, stage: str, message: str):
        super().__init__(message)
        self.classification = classification
        self.stage = stage


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")


def plan_digest(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=repo, text=True, encoding="utf-8", capture_output=True)
    if check and result.returncode:
        raise ReleaseFailure("CODE_FAILURE", "recovery_git", result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def ensure_snapshot(root: Path, generated_at: str) -> str:
    snapshot_date = generated_at[:10]
    target = root / "data/snapshots" / snapshot_date
    sources = {suffix: root / f"api/v1/prices.{suffix}" for suffix in ("json", "csv")}
    if target.exists():
        if any(not (target / f"prices.{suffix}").is_file() for suffix in sources):
            raise ReleaseFailure("DATA_MISMATCH", "recovery_artifacts_generated", "Incomplete recovery snapshot")
        if any((target / f"prices.{suffix}").read_bytes() != source.read_bytes() for suffix, source in sources.items()):
            raise ReleaseFailure("DATA_MISMATCH", "recovery_artifacts_generated", "Recovery snapshot bytes changed")
        return snapshot_date
    target.mkdir(parents=True)
    for suffix, source in sources.items():
        shutil.copyfile(source, target / f"prices.{suffix}")
    return snapshot_date


RECOVERY_STAGES = (
    "recovery_plan_verified", "recovery_source_committed", "recovery_artifacts_generated",
    "recovery_artifact_committed", "recovery_website_verified", "recovery_dataset_pushed",
    "recovery_pre_tag_verified", "recovery_tag_pushed", "recovery_validate_verified",
    "recovery_pages_preflight_verified", "recovery_pages_deployed", "recovery_pages_verified",
    "recovery_website_production_verified",
    "recovery_hf_dry_run_verified", "recovery_hf_publish_verified", "recovery_hf_production_verified",
)


@dataclass
class RecoveryStateStore:
    root: Path
    recovery_id: str

    @property
    def path(self) -> Path:
        return self.root / ".git" / "forward-recovery-state" / f"{self.recovery_id}.json"

    def load(self, digest: str) -> dict[str, Any]:
        if self.path.exists():
            state = read_json(self.path)
            if state.get("schema") != RECOVERY_STATE_SCHEMA:
                raise ReleaseFailure("DATA_MISMATCH", "recovery_plan_verified", "Recovery state schema changed")
            if state.get("recovery_id") != self.recovery_id or state.get("plan_digest") != digest:
                raise ReleaseFailure("DATA_MISMATCH", "recovery_plan_verified", "Recovery identity or digest changed")
            if any(stage not in RECOVERY_STAGES for stage in state.get("completed_stages", [])):
                raise ReleaseFailure("DATA_MISMATCH", "recovery_plan_verified", "Recovery state contains an unknown stage")
            return state
        return {
            "schema": RECOVERY_STATE_SCHEMA, "recovery_id": self.recovery_id,
            "plan_digest": digest, "completed_stages": [], "last_error": None,
        }

    def save(self, state: dict[str, Any]) -> None:
        write_json(self.path, state)


class RecoveryBackend:
    def verify_plan(self, plan: dict[str, Any], digest: str) -> None: raise NotImplementedError
    def commit_source(self, plan: dict[str, Any]) -> str: raise NotImplementedError
    def generate_artifacts(self, plan: dict[str, Any], source_sha: str) -> None: raise NotImplementedError
    def commit_artifact(self, plan: dict[str, Any], source_sha: str) -> str: raise NotImplementedError
    def verify_website_reuse(self, plan: dict[str, Any]) -> str: raise NotImplementedError
    def push_dataset(self, plan: dict[str, Any], artifact_sha: str) -> None: raise NotImplementedError
    def verify_pre_tag(self, plan: dict[str, Any], digest: str, source_sha: str, artifact_sha: str, website_sha: str) -> str: raise NotImplementedError
    def push_tag(self, plan: dict[str, Any], artifact_sha: str, tag: str) -> None: raise NotImplementedError
    def verify_ci(self, artifact_sha: str, website_sha: str) -> list[dict[str, Any]]: raise NotImplementedError
    def deploy_pages(self, state: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]: raise NotImplementedError
    def verify_website_production(self, plan: dict[str, Any]) -> None: raise NotImplementedError
    def publish_hf(self, state: dict[str, Any], plan: dict[str, Any], dry_run: bool) -> dict[str, Any]: raise NotImplementedError
    def verify_hf(self, plan: dict[str, Any]) -> None: raise NotImplementedError


def publish_recovery(
    plan: dict[str, Any], plan_path: Path, digest: str,
    store: RecoveryStateStore, backend: RecoveryBackend,
) -> dict[str, Any]:
    try:
        validate_recovery_plan(plan, store.recovery_id)
    except RecoveryContractError as error:
        raise ReleaseFailure("DATA_MISMATCH", "recovery_plan_verified", str(error)) from None
    if plan_digest(plan_path) != digest:
        raise ReleaseFailure("DATA_MISMATCH", "recovery_plan_verified", "Approved recovery plan digest changed")
    state = store.load(digest)

    def run(stage: str, action: Callable[[], Any], key: str | None = None) -> Any:
        if stage in state["completed_stages"]:
            return state.get(key) if key else None
        try:
            value = action()
        except Exception as error:
            state["last_error"] = {"stage": stage, "message": str(error)}
            store.save(state)
            raise
        if key:
            state[key] = value
        state["completed_stages"].append(stage)
        state["last_error"] = None
        store.save(state)
        return value

    run("recovery_plan_verified", lambda: backend.verify_plan(plan, digest))
    source_sha = run("recovery_source_committed", lambda: backend.commit_source(plan), "source_sha") or state["source_sha"]
    run("recovery_artifacts_generated", lambda: backend.generate_artifacts(plan, source_sha))
    artifact_sha = run("recovery_artifact_committed", lambda: backend.commit_artifact(plan, source_sha), "artifact_sha") or state["artifact_sha"]
    website_sha = run("recovery_website_verified", lambda: backend.verify_website_reuse(plan), "website_sha") or state["website_sha"]
    run("recovery_dataset_pushed", lambda: backend.push_dataset(plan, artifact_sha))
    tag = run("recovery_pre_tag_verified", lambda: backend.verify_pre_tag(plan, digest, source_sha, artifact_sha, website_sha), "release_tag") or state["release_tag"]
    run("recovery_tag_pushed", lambda: backend.push_tag(plan, artifact_sha, tag))
    runs = run("recovery_validate_verified", lambda: backend.verify_ci(artifact_sha, website_sha), "validate_runs") or state["validate_runs"]
    pages = run("recovery_pages_preflight_verified", lambda: backend.deploy_pages(state, plan), "pages_run") or state["pages_run"]
    run("recovery_pages_deployed", lambda: None if pages.get("production_deployed") else (_ for _ in ()).throw(ReleaseFailure("CI_FAILURE", "recovery_pages_deployed", "Recovery Pages deployment evidence is incomplete")))
    run("recovery_pages_verified", lambda: None if pages.get("production_parity_verified") else (_ for _ in ()).throw(ReleaseFailure("CI_FAILURE", "recovery_pages_verified", "Recovery Pages parity evidence is incomplete")))
    run("recovery_website_production_verified", lambda: backend.verify_website_production(plan))
    dry = run("recovery_hf_dry_run_verified", lambda: backend.publish_hf(state, plan, True), "hf_dry_run") or state["hf_dry_run"]
    published = run("recovery_hf_publish_verified", lambda: backend.publish_hf(state, plan, False), "hf_publish") or state["hf_publish"]
    run("recovery_hf_production_verified", lambda: backend.verify_hf(plan))
    state["result"] = {
        "status": "PRODUCTION VERIFIED", "source_sha": source_sha, "artifact_sha": artifact_sha,
        "website_sha": website_sha, "release_tag": tag, "validate_runs": runs,
        "pages_run": pages, "hf_dry_run": dry, "hf_publish": published,
    }
    store.save(state)
    return state["result"]


class RecoveryShellBackend(RecoveryBackend):
    def __init__(self, root: Path, website: Path, plan_path: Path, digest: str):
        self.root, self.website, self.plan_path, self.digest = root, website, plan_path, digest

    def _run(self, args: list[str], cwd: Path) -> str:
        result = subprocess.run(args, cwd=cwd, text=True, encoding="utf-8", capture_output=True)
        if result.returncode:
            raise ReleaseFailure("CODE_FAILURE", "recovery", result.stderr.strip() or result.stdout.strip())
        return result.stdout.strip()

    def _remote_main(self, repo: str) -> str:
        value = self._run(["gh", "api", f"repos/{repo}/git/ref/heads/main", "--jq", ".object.sha"], self.root)
        if not SHA_RE.fullmatch(value):
            raise ReleaseFailure("REMOTE_STATE_UNKNOWN", "recovery", "Remote main did not return an exact SHA")
        return value

    def _approved_website(self, plan: dict[str, Any], verify_public: bool) -> str:
        from scripts.check_release_gate import expected_website_export, verify_production
        contract = plan["website_contract"]
        website_sha = contract["website_sha"]
        if git(self.website, "rev-parse", "HEAD") != website_sha:
            raise ReleaseFailure("REMOTE_STATE_UNKNOWN", "recovery_website_verified", "Website checkout moved")
        parent = git(self.website, "rev-parse", website_sha + "^")
        expected = expected_website_export(self.website)
        try:
            validate_website_reuse_contract(contract, expected, website_sha, parent)
            if verify_public:
                verify_production(expected, approved_contract=contract)
        except Exception as error:
            raise ReleaseFailure("DATA_MISMATCH", "recovery_website_verified", str(error)) from None
        return website_sha

    def verify_plan(self, plan: dict[str, Any], digest: str) -> None:
        if digest != self.digest or plan_digest(self.plan_path) != digest:
            raise ReleaseFailure("DATA_MISMATCH", "recovery_plan_verified", "Recovery plan digest changed")
        if git(self.root, "rev-parse", "HEAD") != plan["dataset_base_sha"] or self._remote_main(DATASET_REPO) != plan["dataset_base_sha"]:
            raise ReleaseFailure("REMOTE_STATE_UNKNOWN", "recovery_plan_verified", "Dataset checkout moved")
        if git(self.root, "status", "--porcelain=v1", "--untracked-files=all"):
            raise ReleaseFailure("DATA_MISMATCH", "recovery_plan_verified", "Recovery checkout must be clean")
        self._approved_website(plan, True)

    def commit_source(self, plan: dict[str, Any]) -> str:
        tracked = self.root / "release-plans" / f"{plan['recovery_id']}.json"
        tracked.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.plan_path, tracked)
        self._run(["git", "add", "--", tracked.relative_to(self.root).as_posix()], self.root)
        self._run(["git", "commit", "-m", f"recovery: approve {plan['recovery_id']} plan"], self.root)
        return git(self.root, "rev-parse", "HEAD")

    def generate_artifacts(self, plan: dict[str, Any], source_sha: str) -> None:
        if git(self.root, "rev-parse", "HEAD") != source_sha:
            raise ReleaseFailure("DATA_MISMATCH", "recovery_artifacts_generated", "Recovery source revision changed")
        generated_at = plan["snapshot_generated_at"]
        env = {**os.environ, "SOURCE_COMMIT_SHA": source_sha}
        self._run([sys.executable, "scripts/build.py", "--generated-at", generated_at], self.root)
        ensure_snapshot(self.root, generated_at)
        self._run([sys.executable, "scripts/generate_pricing_v2_preview.py", "--website-dataset", str(self.website / "data/model-pricing.json")], self.root)
        self._run([sys.executable, "scripts/export_huggingface.py", "--website-repo", str(self.website), "--website-ref", plan["website_contract"]["website_sha"], "--generated-at", generated_at, "--write"], self.root)
        self._run([sys.executable, "scripts/export_huggingface_history.py", "--write"], self.root)
        self._run([sys.executable, "scripts/update_readme_prices.py"], self.root)
        self._run([sys.executable, "scripts/validate.py"], self.root)

    def commit_artifact(self, plan: dict[str, Any], source_sha: str) -> str:
        files = sorted(set(git(self.root, "diff", "HEAD", "--name-only").splitlines()) | set(git(self.root, "ls-files", "--others", "--exclude-standard").splitlines()))
        if not files or any(not is_recovery_artifact_path(path) for path in files):
            raise ReleaseFailure("DATA_MISMATCH", "recovery_artifact_committed", "Recovery artifact files are not allowlisted")
        self._run(["git", "add", "--", *files], self.root)
        self._run(["git", "commit", "-m", f"recovery: publish {plan['recovery_id']} artifacts"], self.root)
        return git(self.root, "rev-parse", "HEAD")

    def verify_website_reuse(self, plan: dict[str, Any]) -> str:
        return self._approved_website(plan, True)

    def push_dataset(self, plan: dict[str, Any], artifact_sha: str) -> None:
        self._run(["git", "push", "origin", f"{artifact_sha}:main"], self.root)

    def verify_pre_tag(self, plan: dict[str, Any], digest: str, source_sha: str, artifact_sha: str, website_sha: str) -> str:
        from scripts.check_release_gate import verify_recovery_local
        tag = recovery_tag_name(plan)
        verify_recovery_local({
            "source_sha": source_sha, "artifact_sha": artifact_sha, "website_sha": website_sha,
            "release_tag": tag, "recovery_id": plan["recovery_id"], "recovery_digest": digest,
        }, self.website)
        return assert_recovery_tag_available(
            plan, git(self.root, "show-ref", "--verify", f"refs/tags/{tag}", check=False),
            self._run(["git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"], self.root),
        )

    def push_tag(self, plan: dict[str, Any], artifact_sha: str, tag: str) -> None:
        try:
            assert_recovery_tag_available(plan, git(self.root, "show-ref", "--verify", f"refs/tags/{tag}", check=False), self._run(["git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"], self.root))
        except RecoveryContractError as error:
            raise ReleaseFailure("DATA_MISMATCH", "recovery_tag_pushed", str(error)) from None
        self._run(["git", "tag", "-a", tag, artifact_sha, "-m", f"AICostBudget forward recovery {plan['recovery_id']}"], self.root)
        self._run(["git", "push", "origin", f"refs/tags/{tag}"], self.root)

    def _wait_run_id(self, run_id: int, stage: str) -> dict[str, Any]:
        result = json.loads(self._run(["gh", "run", "view", str(run_id), "--json", "conclusion,url,jobs"], self.root))
        if result.get("conclusion") != "success":
            raise ReleaseFailure("CI_FAILURE", stage, f"Recovery workflow failed: {result.get('url')}")
        return result

    def _dispatch(self, workflow: str, state: dict[str, Any], plan: dict[str, Any], extra: list[str] | None = None) -> dict[str, Any]:
        suffix = "publish" if extra and "dry_run=false" in extra else "dry" if extra else "release"
        stage = "recovery_hf_publish_verified" if suffix == "publish" else "recovery_hf_dry_run_verified" if suffix == "dry" else "recovery_pages_preflight_verified"
        key = f"{workflow}:{suffix}"
        run_ids = state.setdefault("workflow_run_ids", {})
        if key in run_ids:
            return self._wait_run_id(int(run_ids[key]), stage)
        known = {
            int(run["databaseId"])
            for run in json.loads(self._run([
                "gh", "run", "list", "--repo", DATASET_REPO, "--workflow", workflow,
                "--commit", state["artifact_sha"], "--event", "workflow_dispatch",
                "--json", "databaseId,headSha", "--limit", "10",
            ], self.root))
        }
        fields = [
            "-f", "recovery_mode=true", "-f", f"recovery_source_sha={state['source_sha']}",
            "-f", f"recovery_artifact_sha={state['artifact_sha']}", "-f", f"recovery_website_sha={state['website_sha']}",
            "-f", f"recovery_id={plan['recovery_id']}", "-f", f"recovery_digest={state['plan_digest']}",
        ]
        self._run(["gh", "workflow", "run", workflow, "--repo", DATASET_REPO, "--ref", "main", *fields, *(extra or [])], self.root)
        for _ in range(20):
            runs = json.loads(self._run([
                "gh", "run", "list", "--repo", DATASET_REPO, "--workflow", workflow,
                "--commit", state["artifact_sha"], "--event", "workflow_dispatch",
                "--json", "databaseId,headSha", "--limit", "10",
            ], self.root))
            fresh = [run for run in runs if run.get("headSha") == state["artifact_sha"] and int(run["databaseId"]) not in known]
            if fresh:
                run_id = int(fresh[0]["databaseId"])
                run_ids[key] = run_id
                write_json(self.root / ".git" / "forward-recovery-state" / f"{state['recovery_id']}.json", state)
                return self._wait_run_id(run_id, stage)
            time.sleep(3)
        raise ReleaseFailure("CI_FAILURE", stage, f"Recovery dispatched {workflow} but its exact run could not be resolved")

    def verify_ci(self, artifact_sha: str, website_sha: str) -> list[dict[str, Any]]:
        return []

    def deploy_pages(self, state: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
        return self._dispatch("deploy-pages.yml", state, plan)

    def verify_website_production(self, plan: dict[str, Any]) -> None:
        self._approved_website(plan, True)

    def publish_hf(self, state: dict[str, Any], plan: dict[str, Any], dry_run: bool) -> dict[str, Any]:
        return self._dispatch("publish-huggingface.yml", state, plan, ["-f", f"dry_run={'true' if dry_run else 'false'}"])

    def verify_hf(self, plan: dict[str, Any]) -> None:
        self._run([sys.executable, "scripts/check_hf_production_parity.py"], self.root)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an explicitly approved forward-only recovery.")
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--website-root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-digest", required=True)
    args = parser.parse_args()
    root, website, path = args.dataset_root.resolve(), args.website_root.resolve(), args.plan.resolve()
    try:
        if not path.is_file() or plan_digest(path) != args.plan_digest:
            raise ReleaseFailure("DATA_MISMATCH", "recovery_plan_verified", "Exact approved recovery plan path/digest is required")
        plan = read_json(path)
        validate_recovery_plan(plan)
        store = RecoveryStateStore(root, plan["recovery_id"])
        result = publish_recovery(plan, path, args.plan_digest, store, RecoveryShellBackend(root, website, path, args.plan_digest))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (RecoveryContractError, ReleaseFailure) as error:
        print(f"RECOVERY_FAILED: {error}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
