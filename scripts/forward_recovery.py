"""Fail-closed contracts for a new forward-only recovery release identity."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


RECOVERY_PLAN_SCHEMA = "aicostbudget-forward-recovery-plan-v1"
RECOVERY_STATE_SCHEMA = "aicostbudget-forward-recovery-state-v1"
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
