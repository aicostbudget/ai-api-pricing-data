"""Prepare and resume the reviewed AICostBudget daily pricing release."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

try:
    from forward_recovery import (
        RECOVERY_PLAN_SCHEMA, RECOVERY_STATE_SCHEMA, RecoveryContractError,
        assert_recovery_tag_available, is_recovery_artifact_path, recovery_tag_name,
        validate_recovery_plan, validate_website_reuse_contract,
    )
except ModuleNotFoundError:
    from scripts.forward_recovery import (
        RECOVERY_PLAN_SCHEMA, RECOVERY_STATE_SCHEMA, RecoveryContractError,
        assert_recovery_tag_available, is_recovery_artifact_path, recovery_tag_name,
        validate_recovery_plan, validate_website_reuse_contract,
    )

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR_NAME = ".daily-pricing-release"
PLAN_SCHEMA = "aicostbudget-daily-pricing-release-plan-v1"
STATE_SCHEMA = "aicostbudget-daily-pricing-release-state-v3"
DATASET_REPO = "aicostbudget/ai-api-pricing-data"
WEBSITE_REPO = "linqiang-max/aicostbudget"
ALLOWED_WEBSITE_OUTPUTS = {
    "data/pricing-v2-projection/model-pricing.v2.json",
    "data/pricing-v2-projection/price-change-events.v1.json",
    "data/pricing-v2-projection/pricing-meta.v1.json",
}
SOURCE_PATHS = {"data/canonical/models.json"}
ARTIFACT_EXACT = {
    "api/v1/meta.json", "api/v1/prices.json", "api/v1/prices.csv",
    "data/prices.json", "data/prices.csv", "data/price-change-events/events.jsonl",
    "huggingface/prices.json", "huggingface/prices.csv", "huggingface/train.csv", "huggingface/meta.json",
}
ARTIFACT_PREFIXES = (
    "api/v1/models/", "api/v1/providers/", "data/models/", "data/providers/", "data/history/",
    "data/pricing-v2-preview/",
)
STAGES = (
    "plan_verified", "source_committed", "artifacts_generated", "artifact_committed",
    "website_committed", "website_pushed", "dataset_pushed", "pre_tag_verified", "tag_pushed",
    "validate_verified", "pages_release_preflight_verified", "pages_production_deployed",
    "pages_production_verified", "website_production_verified",
    "hf_dry_run_verified", "hf_publish_verified", "hf_production_verified",
)


class ReleaseFailure(RuntimeError):
    def __init__(self, classification: str, stage: str, message: str):
        super().__init__(message)
        self.classification = classification
        self.stage = stage


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalized_file_sha256(path: Path) -> str:
    raw=path.read_bytes()
    if b"\r" in raw:
        if b"\r" in raw.replace(b"\r\n",b""): raise ReleaseFailure("DATA_MISMATCH","prepare",f"Mixed or bare CR newlines: {path}")
        raw=raw.replace(b"\r\n",b"\n")
    return sha256_bytes(raw)


def row_identity(row: Mapping[str, Any]) -> str:
    provider = row.get("provider_id") or row.get("provider")
    model = row.get("model_id") or row.get("id")
    if not isinstance(provider, str) or not isinstance(model, str) or not provider or not model:
        raise ReleaseFailure("DATA_MISMATCH", "prepare", "Pricing row lacks provider/model identity")
    return f"{provider}/{model}"


def row_contract(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    digests: dict[str, str] = {}
    for row in rows:
        identity = row_identity(row)
        if identity in digests:
            raise ReleaseFailure("DATA_MISMATCH", "prepare", f"Duplicate pricing identity: {identity}")
        digests[identity] = sha256_bytes(canonical_bytes(row))
    return {"records": len(digests), "row_digests": dict(sorted(digests.items()))}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")


def plan_digest(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def release_tag_name(plan: Mapping[str, Any]) -> str:
    models = plan.get("models", [])
    if len(models) == 1:
        readable = re.sub(r"[^a-z0-9]+", "-", str(models[0].get("model_id", "")).lower()).strip("-")[:64]
        subject = readable or "model"
    else:
        subject = "pricing"
    return f"dataset-{plan['snapshot_date']}-{subject}-{plan['canonical_sha256'][:8]}"


def git(repo: Path, *args: str, check: bool = True) -> str:
    completed = subprocess.run(["git", *args], cwd=repo, text=True, encoding="utf-8", capture_output=True)
    if check and completed.returncode:
        raise ReleaseFailure("CODE_FAILURE", "git", completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout.strip()


def command(args: list[str], cwd: Path, env: Mapping[str, str] | None = None) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        capture_output=True,
        env=None if env is None else dict(env),
    )
    if completed.returncode:
        raise ReleaseFailure("VALIDATION_SCRIPT_FAILURE", "prepare", completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout.strip()


def github_remote_main(repo: str, cwd: Path) -> str:
    completed = subprocess.run(
        ["gh", "api", f"repos/{repo}/git/ref/heads/main", "--jq", ".object.sha"],
        cwd=cwd,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if completed.returncode:
        message = completed.stderr.strip() or completed.stdout.strip()
        classification = "AUTH_FAILURE" if any(term in message.lower() for term in ("auth", "login", "401", "403")) else "NETWORK_FAILURE"
        raise ReleaseFailure(classification, "prepare", "Cannot verify remote main: " + message)
    value = completed.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", value): raise ReleaseFailure("REMOTE_STATE_UNKNOWN", "prepare", "Remote main did not return an exact SHA")
    return value


def require_checkout(root: Path, required: str) -> Path:
    root = root.resolve()
    if not (root / ".git").exists() or not (root / required).is_file():
        raise ReleaseFailure("DATA_MISMATCH", "prepare", f"Invalid checkout: {root}")
    return root


def parse_generated_at(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ReleaseFailure("DATA_MISMATCH", "prepare", "generated-at must be an explicit UTC timestamp")
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def classify_changes(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    old = {row_identity(row): row for row in before}
    new = {row_identity(row): row for row in after}
    changes: list[dict[str, Any]] = []
    verification_fields = {"verified_at", "access_checked_at", "official_source_checked_at"}
    for identity in sorted(set(old) | set(new)):
        if identity not in old:
            kind = "added"
        elif identity not in new:
            kind = "removed"
        elif old[identity] == new[identity]:
            continue
        else:
            changed = {key for key in set(old[identity]) | set(new[identity]) if old[identity].get(key) != new[identity].get(key)}
            if changed <= verification_fields:
                kind = "verification_metadata"
            elif changed & {"pricing", "price_records"}:
                kind = "pricing"
            elif changed & {"status", "release_stage", "lifecycle", "released_at"}:
                kind = "lifecycle"
            else:
                kind = "metadata"
        provider, model = identity.split("/", 1)
        changes.append({
            "provider_id": provider,
            "model_id": model,
            "change_type": kind,
            "before_sha256": sha256_bytes(canonical_bytes(old[identity])) if identity in old else None,
            "after_sha256": sha256_bytes(canonical_bytes(new[identity])) if identity in new else None,
            "old_pricing": old.get(identity, {}).get("price_records", old.get(identity, {}).get("pricing")),
            "new_pricing": new.get(identity, {}).get("price_records", new.get(identity, {}).get("pricing")),
        })
    return changes


def latest_prior_snapshot(root: Path, snapshot_date: str) -> str:
    candidates = sorted(path.name for path in (root / "data/snapshots").iterdir() if path.is_dir() and path.name < snapshot_date and (path / "prices.json").is_file())
    if not candidates:
        raise ReleaseFailure("DATA_MISMATCH", "prepare", "No prior tracked snapshot is available")
    return candidates[-1]


def ensure_snapshot(root: Path, generated_at: str) -> str:
    snapshot_date = generated_at[:10]
    target = root / "data/snapshots" / snapshot_date
    api_json = root / "api/v1/prices.json"
    api_csv = root / "api/v1/prices.csv"
    if target.exists():
        if not (target / "prices.json").is_file() or not (target / "prices.csv").is_file():
            raise ReleaseFailure("DATA_MISMATCH", "prepare", f"Incomplete existing snapshot: {snapshot_date}")
        if (target / "prices.json").read_bytes() != api_json.read_bytes() or (target / "prices.csv").read_bytes() != api_csv.read_bytes():
            raise ReleaseFailure("DATA_MISMATCH", "prepare", f"Snapshot {snapshot_date} already exists with different bytes")
        return snapshot_date
    target.mkdir(parents=True)
    shutil.copyfile(api_json, target / "prices.json")
    shutil.copyfile(api_csv, target / "prices.csv")
    return snapshot_date


def run_prepare_generators(root: Path, website: Path, generated_at: str) -> tuple[str, list[dict[str, str]]]:
    py = sys.executable
    results: list[dict[str, str]] = []
    def run(label: str, args: list[str], cwd: Path = root) -> None:
        command(args, cwd)
        results.append({"name": label, "status": "PASS"})
    run("build-v1", [py, "scripts/build.py", "--generated-at", generated_at])
    snapshot_date = ensure_snapshot(root, generated_at)
    run("pricing-v2-generate", [py, "scripts/generate_pricing_v2_preview.py"])
    run("website-projection-generate", [py, "scripts/generate_website_projection_v2.py", "--effective-at", generated_at, "--generated-at", generated_at, "--website-dataset", str(website / "data/model-pricing.json"), "--existing-artifact-git-ref", "HEAD", "--preserve-existing-selections"])
    run("website-sync", ["node", "scripts/sync-pricing-artifacts.mjs", "--write", "--dataset", str(root), "--website", str(website)], website)
    run("hf-export", [py, "scripts/export_huggingface.py", "--website-repo", str(website), "--website-ref", "WORKTREE", "--generated-at", generated_at, "--write"])
    run("dataset-validation", [py, "scripts/validate.py"])
    run("pricing-v2-validation", [py, "scripts/validate_pricing_v2_preview.py"])
    run("website-sync-check", ["node", "scripts/sync-pricing-artifacts.mjs", "--check", "--dataset", str(root), "--website", str(website)], website)
    run("hf-parity", [py, "scripts/export_huggingface.py", "--website-repo", str(website), "--website-ref", "WORKTREE", "--generated-at", generated_at, "--check"])
    return snapshot_date, results


def build_plan(root: Path, website: Path, generated_at: str, snapshot_date: str, tests: list[dict[str, str]]) -> dict[str, Any]:
    dataset_base = git(root, "rev-parse", "HEAD")
    website_base = git(website, "rev-parse", "HEAD")
    before = json.loads(git(root, "show", f"{dataset_base}:data/canonical/models.json"))
    after = read_json(root / "data/canonical/models.json")
    changes = classify_changes(before, after)
    v1 = read_json(root / "api/v1/prices.json")["models"]
    v2 = read_json(root / "huggingface/prices.json")["records"]
    snapshot_before = latest_prior_snapshot(root, snapshot_date)
    canonical_digest = normalized_file_sha256(root / "data/canonical/models.json")
    release_id = f"pricing-{snapshot_date}-{canonical_digest[:12]}"
    dataset_diff = sorted(filter(None, git(root, "diff", "HEAD", "--name-only").splitlines()))
    dataset_untracked = sorted(filter(None, git(root, "ls-files", "--others", "--exclude-standard").splitlines()))
    website_diff = sorted(filter(None, git(website, "diff", "HEAD", "--name-only").splitlines()))
    website_untracked = sorted(filter(None, git(website, "ls-files", "--others", "--exclude-standard").splitlines()))
    dataset_allowed = lambda path: path in SOURCE_PATHS or path in ARTIFACT_EXACT or path.startswith(ARTIFACT_PREFIXES) or path.startswith("data/snapshots/")
    unrelated = [path for path in dataset_diff + dataset_untracked if not dataset_allowed(path)] + [path for path in website_diff + website_untracked if path not in ALLOWED_WEBSITE_OUTPUTS]
    source_files = sorted(SOURCE_PATHS | {f"data/snapshots/{snapshot_date}/prices.json", f"data/snapshots/{snapshot_date}/prices.csv"})
    return {
        "schema": PLAN_SCHEMA,
        "release_id": release_id,
        "generated_at": generated_at,
        "snapshot_date": snapshot_date,
        "snapshot_before": snapshot_before,
        "dataset_base_sha": dataset_base,
        "website_base_sha": website_base,
        "canonical_sha256": canonical_digest,
        "models": changes,
        "source_files": source_files,
        "workspace": {"dataset_files": sorted(set(dataset_diff + dataset_untracked)), "website_files": sorted(set(website_diff + website_untracked)), "unrelated_files": unrelated},
        "projection_contracts": {"v1": row_contract(v1), "v2": row_contract(v2)},
        "tests": tests,
    }


def prepare_release(root: Path, website: Path, generated_at: str | None = None, run_generators: Callable[[Path, Path, str], tuple[str, list[dict[str, str]]]] = run_prepare_generators, remote_reader: Callable[[str, Path], str] = github_remote_main) -> tuple[dict[str, Any], Path, str]:
    root = require_checkout(root, "data/canonical/models.json")
    website = require_checkout(website, "data/model-pricing.json")
    generated_at = parse_generated_at(generated_at)
    dataset_head=git(root,"rev-parse","HEAD");website_head=git(website,"rev-parse","HEAD")
    if remote_reader(DATASET_REPO,root)!=dataset_head or remote_reader(WEBSITE_REPO,website)!=website_head:
        raise ReleaseFailure("REMOTE_STATE_UNKNOWN","prepare","Dataset or Website main moved; refresh the safe worktree before Prepare")
    before=json.loads(git(root,"show",f"{dataset_head}:data/canonical/models.json"));after=read_json(root/"data/canonical/models.json")
    if not classify_changes(before,after): raise ReleaseFailure("DATA_MISMATCH","prepare","No canonical model change; publication is not required")
    snapshot_date, tests = run_generators(root, website, generated_at)
    plan = build_plan(root, website, generated_at, snapshot_date, tests)
    if not plan["models"]:
        raise ReleaseFailure("DATA_MISMATCH", "prepare", "No canonical model change; publication is not required")
    if plan["workspace"]["unrelated_files"]:
        raise ReleaseFailure("DATA_MISMATCH", "prepare", "Unrelated Website changes: " + ", ".join(plan["workspace"]["unrelated_files"]))
    state_dir = root / STATE_DIR_NAME
    plan_path = state_dir / "plans" / f"{plan['release_id']}.json"
    write_json(plan_path, plan)
    digest = plan_digest(plan_path)
    write_json(state_dir / "latest.json", {"release_id": plan["release_id"], "plan_path": str(plan_path), "plan_digest": digest})
    return plan, plan_path, digest


@dataclass
class ReleaseStateStore:
    root: Path
    release_id: str

    @property
    def path(self) -> Path:
        return self.root / STATE_DIR_NAME / "state" / f"{self.release_id}.json"

    def load(self, digest: str) -> dict[str, Any]:
        if self.path.exists():
            state = read_json(self.path)
            if state.get("schema") != STATE_SCHEMA:
                raise ReleaseFailure("DATA_MISMATCH", "plan_verified", "Release state schema changed; run Prepare again")
            if state.get("plan_digest") != digest:
                raise ReleaseFailure("DATA_MISMATCH", "plan_verified", "Approved plan digest changed; run Prepare again")
            return state
        return {"schema": STATE_SCHEMA, "release_id": self.release_id, "plan_digest": digest, "completed_stages": [], "last_error": None}

    def save(self, state: dict[str, Any]) -> None:
        write_json(self.path, state)


class Backend:
    """Side-effect boundary. Production uses ShellBackend; tests use a fake."""
    def verify_plan(self, plan: dict[str, Any], digest: str) -> None: raise NotImplementedError
    def commit_source(self, plan: dict[str, Any]) -> str: raise NotImplementedError
    def generate_artifacts(self, plan: dict[str, Any], source_sha: str) -> None: raise NotImplementedError
    def commit_artifact(self, plan: dict[str, Any], source_sha: str) -> str: raise NotImplementedError
    def commit_website(self, plan: dict[str, Any], source_sha: str) -> str: raise NotImplementedError
    def push_dataset(self, plan: dict[str, Any], artifact_sha: str) -> None: raise NotImplementedError
    def push_website(self, plan: dict[str, Any], website_sha: str) -> None: raise NotImplementedError
    def verify_pre_tag(self, plan: dict[str, Any], digest: str, source_sha: str, artifact_sha: str, website_sha: str) -> str: raise NotImplementedError
    def push_tag(self, plan: dict[str, Any], artifact_sha: str, tag: str) -> str: raise NotImplementedError
    def verify_ci(self, artifact_sha: str, website_sha: str) -> list[dict[str, Any]]: raise NotImplementedError
    def deploy_pages(self, state: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]: raise NotImplementedError
    def verify_website_production(self, website_sha: str) -> None: raise NotImplementedError
    def publish_hf(self, state: dict[str, Any], plan: dict[str, Any], dry_run: bool) -> dict[str, Any]: raise NotImplementedError
    def verify_hf(self) -> None: raise NotImplementedError


RECOVERY_STAGES = (
    "recovery_plan_verified",
    "recovery_source_committed",
    "recovery_artifacts_generated",
    "recovery_artifact_committed",
    "recovery_website_verified",
    "recovery_dataset_pushed",
    "recovery_pre_tag_verified",
    "recovery_tag_pushed",
    "recovery_validate_verified",
    "recovery_pages_preflight_verified",
    "recovery_pages_deployed",
    "recovery_pages_verified",
    "recovery_website_production_verified",
    "recovery_hf_dry_run_verified",
    "recovery_hf_publish_verified",
    "recovery_hf_production_verified",
)


@dataclass
class RecoveryStateStore:
    root: Path
    recovery_id: str

    @property
    def path(self) -> Path:
        return self.root / STATE_DIR_NAME / "recovery-state" / f"{self.recovery_id}.json"

    def load(self, digest: str) -> dict[str, Any]:
        if self.path.exists():
            state = read_json(self.path)
            if state.get("schema") != RECOVERY_STATE_SCHEMA:
                raise ReleaseFailure("DATA_MISMATCH", "recovery_plan_verified", "Recovery state schema changed; obtain a new human approval")
            if state.get("recovery_id") != self.recovery_id or state.get("plan_digest") != digest:
                raise ReleaseFailure("DATA_MISMATCH", "recovery_plan_verified", "Recovery identity or approved plan digest changed")
            if any(stage not in RECOVERY_STAGES for stage in state.get("completed_stages", [])):
                raise ReleaseFailure("DATA_MISMATCH", "recovery_plan_verified", "Recovery state contains an unknown stage")
            return state
        return {"schema": RECOVERY_STATE_SCHEMA, "recovery_id": self.recovery_id, "plan_digest": digest, "completed_stages": [], "last_error": None}

    def save(self, state: dict[str, Any]) -> None:
        write_json(self.path, state)


class RecoveryBackend:
    """Independent side-effect boundary; recovery never falls through to Daily Release."""
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


def publish_recovery(plan: dict[str, Any], plan_path: Path, digest: str, store: RecoveryStateStore, backend: RecoveryBackend) -> dict[str, Any]:
    try:
        validate_recovery_plan(plan, store.recovery_id)
    except RecoveryContractError as error:
        raise ReleaseFailure("DATA_MISMATCH", "recovery_plan_verified", str(error)) from None
    if plan.get("schema") != RECOVERY_PLAN_SCHEMA or plan_digest(plan_path) != digest:
        raise ReleaseFailure("DATA_MISMATCH", "recovery_plan_verified", "Approved recovery plan identity does not match")
    state = store.load(digest)

    def run(stage: str, operation: Callable[[], Any], field: str | None = None) -> Any:
        if stage in state["completed_stages"]:
            return state.get(field) if field else None
        state["active_stage"] = stage
        store.save(state)
        try:
            value = operation()
        except Exception as error:
            failure = error if isinstance(error, ReleaseFailure) else ReleaseFailure("CODE_FAILURE", stage, str(error))
            state["last_error"] = {"classification": failure.classification, "stage": stage, "message": str(failure)}
            store.save(state)
            raise failure
        if field:
            state[field] = value
        state["completed_stages"].append(stage)
        state.pop("active_stage", None)
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

    def require_pages(field: str, stage: str) -> None:
        if not isinstance(pages, dict) or pages.get(field) is not True:
            raise ReleaseFailure("CI_FAILURE", stage, f"Pages run lacks {field} evidence")

    run("recovery_pages_deployed", lambda: require_pages("production_deployed", "recovery_pages_deployed"))
    run("recovery_pages_verified", lambda: require_pages("production_parity_verified", "recovery_pages_verified"))
    run("recovery_website_production_verified", lambda: backend.verify_website_production(plan))
    hf_dry = run("recovery_hf_dry_run_verified", lambda: backend.publish_hf(state, plan, True), "hf_dry_run") or state["hf_dry_run"]
    hf_publish = run("recovery_hf_publish_verified", lambda: backend.publish_hf(state, plan, False), "hf_publish") or state["hf_publish"]
    run("recovery_hf_production_verified", lambda: backend.verify_hf(plan))
    state["result"] = {
        "status": "PRODUCTION VERIFIED",
        "source_sha": source_sha,
        "artifact_sha": artifact_sha,
        "website_sha": website_sha,
        "release_tag": tag,
        "validate_runs": runs,
        "pages_run": pages,
        "hf_dry_run": hf_dry,
        "hf_publish": hf_publish,
    }
    store.save(state)
    return state["result"]


def publish_release(plan: dict[str, Any], plan_path: Path, digest: str, store: ReleaseStateStore, backend: Backend) -> dict[str, Any]:
    if plan.get("schema") != PLAN_SCHEMA or plan.get("release_id") != store.release_id or plan_digest(plan_path) != digest:
        raise ReleaseFailure("DATA_MISMATCH", "plan_verified", "Approved release plan identity does not match")
    state = store.load(digest)
    def run(stage: str, operation: Callable[[], Any], field: str | None = None) -> Any:
        if stage in state["completed_stages"]:
            return state.get(field) if field else None
        state["active_stage"] = stage
        store.save(state)
        try:
            value = operation()
        except Exception as error:
            failure = error if isinstance(error, ReleaseFailure) else ReleaseFailure("CODE_FAILURE", stage, str(error))
            state["last_error"] = {"classification": failure.classification, "stage": stage, "message": str(failure)}
            store.save(state)
            raise failure
        if field:
            state[field] = value
        state["completed_stages"].append(stage)
        state.pop("active_stage", None)
        state["last_error"] = None
        store.save(state)
        return value
    run("plan_verified", lambda: backend.verify_plan(plan, digest))
    source_sha = run("source_committed", lambda: backend.commit_source(plan), "source_sha") or state["source_sha"]
    run("artifacts_generated", lambda: backend.generate_artifacts(plan, source_sha))
    artifact_sha = run("artifact_committed", lambda: backend.commit_artifact(plan, source_sha), "artifact_sha") or state["artifact_sha"]
    website_sha = run("website_committed", lambda: backend.commit_website(plan, source_sha), "website_sha") or state["website_sha"]
    run("website_pushed", lambda: backend.push_website(plan, website_sha))
    run("dataset_pushed", lambda: backend.push_dataset(plan, artifact_sha))
    tag = run("pre_tag_verified", lambda: backend.verify_pre_tag(plan, digest, source_sha, artifact_sha, website_sha), "release_tag") or state["release_tag"]
    run("tag_pushed", lambda: backend.push_tag(plan, artifact_sha, tag))
    runs = run("validate_verified", lambda: backend.verify_ci(artifact_sha, website_sha), "validate_runs") or state["validate_runs"]
    pages = run("pages_release_preflight_verified", lambda: backend.deploy_pages(state, plan), "pages_run") or state["pages_run"]
    def require_pages_evidence(field: str, stage: str) -> None:
        if not isinstance(pages, dict) or pages.get(field) is not True:
            raise ReleaseFailure("CI_FAILURE", stage, f"Pages run lacks {field} evidence")
    run("pages_production_deployed", lambda: require_pages_evidence("production_deployed", "pages_production_deployed"))
    run("pages_production_verified", lambda: require_pages_evidence("production_parity_verified", "pages_production_verified"))
    run("website_production_verified", lambda: backend.verify_website_production(website_sha))
    hf_dry = run("hf_dry_run_verified", lambda: backend.publish_hf(state, plan, True), "hf_dry_run") or state["hf_dry_run"]
    hf_publish = run("hf_publish_verified", lambda: backend.publish_hf(state, plan, False), "hf_publish") or state["hf_publish"]
    run("hf_production_verified", backend.verify_hf)
    state["result"] = {"status": "PRODUCTION VERIFIED", "source_sha": source_sha, "artifact_sha": artifact_sha, "website_sha": website_sha, "release_tag": tag, "validate_runs": runs, "pages_run": pages, "hf_dry_run": hf_dry, "hf_publish": hf_publish, "verification": {"validate": True, "pages_release_preflight": True, "pages_production_deployed": True, "pages_production_parity": True, "website_production": True, "hf_dry_run": True, "hf_publish": True, "hf_production": True}}
    store.save(state)
    return state["result"]


class ShellBackend(Backend):
    def __init__(self, root: Path, website: Path, plan_path: Path, digest: str):
        self.root, self.website, self.plan_path, self.digest = root.resolve(), website.resolve(), plan_path.resolve(), digest

    def _run(self, args: list[str], cwd: Path) -> str:
        completed = subprocess.run(args, cwd=cwd, text=True, encoding="utf-8", capture_output=True)
        if completed.returncode:
            text = completed.stderr.strip() or completed.stdout.strip()
            classification = "NETWORK_FAILURE" if any(term in text.lower() for term in ("network", "connection", "could not resolve", "timed out")) else "CODE_FAILURE"
            raise ReleaseFailure(classification, "publish", text)
        return completed.stdout.strip()

    def _remote_main(self, repo: str) -> str:
        return self._run(["gh", "api", f"repos/{repo}/git/ref/heads/main", "--jq", ".object.sha"], self.root)

    def verify_plan(self, plan: dict[str, Any], digest: str) -> None:
        if digest != self.digest or plan_digest(self.plan_path) != digest: raise ReleaseFailure("DATA_MISMATCH", "plan_verified", "Plan digest changed")
        if git(self.root, "rev-parse", "HEAD") != plan["dataset_base_sha"] or self._remote_main(DATASET_REPO) != plan["dataset_base_sha"]: raise ReleaseFailure("REMOTE_STATE_UNKNOWN", "plan_verified", "Dataset main moved after approval")
        if git(self.website, "rev-parse", "HEAD") != plan["website_base_sha"] or self._remote_main(WEBSITE_REPO) != plan["website_base_sha"]: raise ReleaseFailure("REMOTE_STATE_UNKNOWN", "plan_verified", "Website main moved after approval")
        if normalized_file_sha256(self.root / "data/canonical/models.json") != plan["canonical_sha256"]: raise ReleaseFailure("DATA_MISMATCH", "plan_verified", "Canonical changed after approval")

    def commit_source(self, plan: dict[str, Any]) -> str:
        current=git(self.root,"rev-parse","HEAD")
        if current!=plan["dataset_base_sha"]:
            if git(self.root,"rev-parse","HEAD^")==plan["dataset_base_sha"] and git(self.root,"log","-1","--format=%s")==f"data: prepare {plan['release_id']} source": return current
            raise ReleaseFailure("DATA_MISMATCH","source_committed","Dataset HEAD is not the approved baseline or resumable S1")
        tracked_plan = self.root / "release-plans" / f"{plan['release_id']}.json"
        write_json(tracked_plan, plan)
        files = [*plan["source_files"], tracked_plan.relative_to(self.root).as_posix()]
        self._run(["git", "add", "--", *files], self.root)
        self._run(["git", "commit", "-m", f"data: prepare {plan['release_id']} source"], self.root)
        return git(self.root, "rev-parse", "HEAD")

    def generate_artifacts(self, plan: dict[str, Any], source_sha: str) -> None:
        py = sys.executable; before = f"data/snapshots/{plan['snapshot_before']}/prices.json"; after = f"data/snapshots/{plan['snapshot_date']}/prices.json"
        groups: dict[str, list[str]] = {}
        for change in plan["models"]: groups.setdefault(change["provider_id"], []).append(change["model_id"])
        for provider, models in sorted(groups.items()):
            self._run([py, "scripts/generate_price_change_events.py", "--before", before, "--after", after, "--provider", provider, *sum((["--model", model] for model in sorted(models)), [])], self.root)
        self._run([py, "scripts/build.py", "--generated-at", plan["generated_at"]], self.root)
        self._run([py, "scripts/generate_pricing_v2_preview.py"], self.root)
        self._run([py, "scripts/generate_website_projection_v2.py", "--effective-at", plan["generated_at"], "--generated-at", plan["generated_at"], "--website-dataset", str(self.website / "data/model-pricing.json"), "--existing-artifact-git-ref", plan["dataset_base_sha"], "--preserve-existing-selections"], self.root)
        self._run(["node", "scripts/sync-pricing-artifacts.mjs", "--write", "--dataset", str(self.root), "--website", str(self.website)], self.website)
        self._run([py, "scripts/export_huggingface.py", "--website-repo", str(self.website), "--website-ref", "WORKTREE", "--generated-at", plan["generated_at"], "--write"], self.root)
        self._run([py, "scripts/validate.py"], self.root)

    def commit_artifact(self, plan: dict[str, Any], source_sha: str) -> str:
        current=git(self.root,"rev-parse","HEAD")
        if current!=source_sha:
            if git(self.root,"rev-parse","HEAD^")==source_sha and git(self.root,"log","-1","--format=%s")==f"data: publish {plan['release_id']} artifacts": return current
            raise ReleaseFailure("DATA_MISMATCH","artifact_committed","Dataset HEAD is not the approved S1 or resumable S2")
        files = sorted(list(filter(None, git(self.root, "diff", "HEAD", "--name-only").splitlines())) + list(filter(None, git(self.root, "ls-files", "--others", "--exclude-standard").splitlines())))
        bad = [path for path in files if path not in ARTIFACT_EXACT and not path.startswith(ARTIFACT_PREFIXES)]
        if bad: raise ReleaseFailure("DATA_MISMATCH", "artifact_committed", "Unexpected S2 files: " + ", ".join(bad))
        self._run(["git", "add", "--", *files], self.root)
        self._run(["git", "commit", "-m", f"data: publish {plan['release_id']} artifacts"], self.root)
        return git(self.root, "rev-parse", "HEAD")

    def commit_website(self, plan: dict[str, Any], source_sha: str) -> str:
        current=git(self.website,"rev-parse","HEAD")
        if current!=plan["website_base_sha"]:
            if git(self.website,"rev-parse","HEAD^")==plan["website_base_sha"] and git(self.website,"log","-1","--format=%s")==f"data: sync {plan['release_id']} pricing": return current
            raise ReleaseFailure("DATA_MISMATCH","website_committed","Website HEAD is not the approved baseline or resumable W1")
        files = sorted(filter(None, git(self.website, "diff", "HEAD", "--name-only").splitlines()))
        if set(files) - ALLOWED_WEBSITE_OUTPUTS: raise ReleaseFailure("DATA_MISMATCH", "website_committed", "Unexpected Website files")
        self._run(["git", "add", "--", *files], self.website)
        self._run(["git", "commit", "-m", f"data: sync {plan['release_id']} pricing"], self.website)
        return git(self.website, "rev-parse", "HEAD")

    def push_dataset(self, plan: dict[str, Any], artifact_sha: str) -> None:
        remote=self._remote_main(DATASET_REPO)
        if remote==artifact_sha:return
        if remote != plan["dataset_base_sha"]: raise ReleaseFailure("REMOTE_STATE_UNKNOWN", "dataset_pushed", "Dataset main moved")
        self._run(["git", "push", "origin", f"{artifact_sha}:main"], self.root)

    def push_website(self, plan: dict[str, Any], website_sha: str) -> None:
        remote=self._remote_main(WEBSITE_REPO)
        if remote==website_sha:return
        if remote != plan["website_base_sha"]: raise ReleaseFailure("REMOTE_STATE_UNKNOWN", "website_pushed", "Website main moved")
        self._run(["git", "push", "origin", f"{website_sha}:main"], self.website)

    def _assert_tag_available(self, tag: str, stage: str) -> None:
        local=git(self.root,"show-ref","--verify",f"refs/tags/{tag}",check=False)
        remote=self._run(["git","ls-remote","--tags","origin",f"refs/tags/{tag}",f"refs/tags/{tag}^{{}}"],self.root)
        if local or remote:
            raise ReleaseFailure("DATA_MISMATCH",stage,"RELEASE TAG ALREADY EXISTS — REFUSING TO MOVE OR OVERWRITE")

    def verify_pre_tag(self, plan: dict[str, Any], digest: str, source_sha: str, artifact_sha: str, website_sha: str) -> str:
        from scripts.check_release_gate import verify_local
        from scripts.review_gate import GateError, exact_sha
        try:
            source=exact_sha(source_sha,"Source SHA");artifact=exact_sha(artifact_sha,"Artifact SHA");website=exact_sha(website_sha,"Website SHA")
        except GateError as error:
            raise ReleaseFailure("DATA_MISMATCH","pre_tag_verified",str(error)) from None
        if source==artifact:
            raise ReleaseFailure("DATA_MISMATCH","pre_tag_verified","SOURCE AND ARTIFACT SHA MUST BE DISTINCT")
        try:
            dataset_main=exact_sha(self._remote_main(DATASET_REPO),"Dataset main SHA")
            website_main=exact_sha(self._remote_main(WEBSITE_REPO),"Website main SHA")
        except GateError as error:
            raise ReleaseFailure("REMOTE_STATE_UNKNOWN","pre_tag_verified",str(error)) from None
        if dataset_main!=artifact or website_main!=website:
            raise ReleaseFailure("REMOTE_STATE_UNKNOWN","pre_tag_verified","PUSHED MAIN SHA DOES NOT MATCH APPROVED S2/W1")
        tag=release_tag_name(plan)
        identity={"source_sha":source,"artifact_sha":artifact,"website_sha":website,"release_tag":tag,"release_plan_id":plan["release_id"],"release_plan_digest":digest}
        try:
            verify_local(identity,self.website,plan["snapshot_date"])
        except GateError as error:
            raise ReleaseFailure("DATA_MISMATCH","pre_tag_verified",str(error)) from None
        try:
            self._run(["node","scripts/test-dataset-pricing-components-parity.mjs",str(self.root/"huggingface")],self.website)
        except ReleaseFailure:
            raise ReleaseFailure("DATA_MISMATCH","pre_tag_verified","WEBSITE / DATASET PRICING V2 PARITY FAILED") from None
        self._assert_tag_available(tag,"pre_tag_verified")
        return tag

    def push_tag(self, plan: dict[str, Any], artifact_sha: str, tag: str) -> str:
        if tag!=release_tag_name(plan): raise ReleaseFailure("DATA_MISMATCH","tag_pushed","Release tag changed after pre-tag verification")
        self._assert_tag_available(tag,"tag_pushed")
        self._run(["git", "tag", "-a", tag, artifact_sha, "-m", f"AICostBudget pricing release {plan['release_id']}"], self.root)
        self._run(["git", "push", "origin", f"refs/tags/{tag}"], self.root)
        return tag

    def _wait_workflow(self, workflow: str, sha: str, timeout: int = 1800) -> dict[str, Any]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = self._run(["gh", "run", "list", "--repo", DATASET_REPO, "--workflow", workflow, "--commit", sha, "--json", "databaseId,status,conclusion,url,headSha", "--limit", "10"], self.root)
            runs = json.loads(raw)
            exact = [run for run in runs if run.get("headSha") == sha]
            failed = [run for run in exact if run.get("status") == "completed" and run.get("conclusion") != "success"]
            if failed: raise ReleaseFailure("CI_FAILURE", "validate_verified", f"{workflow} failed: {failed[0].get('url')}")
            passed = [run for run in exact if run.get("status") == "completed" and run.get("conclusion") == "success"]
            if passed: return passed[0]
            time.sleep(15)
        raise ReleaseFailure("CI_FAILURE", "validate_verified", f"Timed out waiting for {workflow} at {sha}")

    def _wait_run_id(self, run_id: int, stage: str, timeout: int = 1800) -> dict[str, Any]:
        deadline=time.time()+timeout
        while time.time()<deadline:
            run=json.loads(self._run(["gh","run","view",str(run_id),"--repo",DATASET_REPO,"--json","databaseId,status,conclusion,url,headSha,jobs"],self.root))
            if run.get("status")=="completed":
                if run.get("conclusion")!="success": raise ReleaseFailure("CI_FAILURE",stage,f"Workflow failed: {run.get('url')}")
                return run
            time.sleep(15)
        raise ReleaseFailure("CI_FAILURE",stage,f"Timed out waiting for workflow run {run_id}")

    def verify_ci(self, artifact_sha: str, website_sha: str) -> list[dict[str, Any]]:
        # Validate is push-triggered for the exact S2 SHA and checks the already-pushed Website main.
        # Pages later repeats the complete suite before deployment, so do not dispatch a duplicate parity run.
        return [self._wait_workflow("validate.yml", artifact_sha)]

    def _dispatch(self, workflow: str, state: dict[str, Any], plan: dict[str, Any], extra: list[str] | None = None) -> dict[str, Any]:
        suffix="publish" if extra and "dry_run=false" in extra else "dry" if extra else "release"
        stage="hf_publish_verified" if suffix=="publish" else "hf_dry_run_verified" if suffix=="dry" else "pages_release_preflight_verified"
        key=f"{workflow}:{suffix}";run_ids=state.setdefault("workflow_run_ids",{})
        if key in run_ids:return self._wait_run_id(int(run_ids[key]),stage)
        known={int(value) for value in run_ids.values()}
        existing=json.loads(self._run(["gh","run","list","--repo",DATASET_REPO,"--workflow",workflow,"--commit",state["artifact_sha"],"--event","workflow_dispatch","--json","databaseId,headSha","--limit","10"],self.root))
        recoverable=[run for run in existing if run.get("headSha")==state["artifact_sha"] and int(run["databaseId"]) not in known]
        if recoverable:
            run_id=int(recoverable[0]["databaseId"]);run_ids[key]=run_id;write_json(self.root/STATE_DIR_NAME/"state"/f"{state['release_id']}.json",state);return self._wait_run_id(run_id,stage)
        fields = ["-f", f"artifact_sha={state['artifact_sha']}", "-f", f"source_sha={state['source_sha']}", "-f", f"website_sha={state['website_sha']}", "-f", f"release_tag={state['release_tag']}", "-f", f"release_date={plan['snapshot_date']}", "-f", f"release_plan_id={plan['release_id']}", "-f", f"release_plan_digest={state['plan_digest']}"]
        self._run(["gh", "workflow", "run", workflow, "--repo", DATASET_REPO, "--ref", "main", *fields, *(extra or [])], self.root)
        for _ in range(20):
            runs=json.loads(self._run(["gh","run","list","--repo",DATASET_REPO,"--workflow",workflow,"--commit",state["artifact_sha"],"--event","workflow_dispatch","--json","databaseId,headSha","--limit","10"],self.root))
            fresh=[run for run in runs if run.get("headSha")==state["artifact_sha"] and int(run["databaseId"]) not in known]
            if fresh:
                run_id=int(fresh[0]["databaseId"]);run_ids[key]=run_id;write_json(self.root/STATE_DIR_NAME/"state"/f"{state['release_id']}.json",state);return self._wait_run_id(run_id,stage)
            time.sleep(3)
        raise ReleaseFailure("CI_FAILURE",stage,f"Dispatched {workflow} but could not resolve its exact run ID")

    def deploy_pages(self, state: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
        run = self._dispatch("deploy-pages.yml", state, plan)
        jobs = {job.get("name"): job for job in run.get("jobs", [])}
        preflight = jobs.get("release-preflight", {})
        deploy = jobs.get("deploy", {})
        steps = {step.get("name"): step for step in deploy.get("steps", [])}
        evidence = {
            **run,
            "release_preflight_verified": preflight.get("conclusion") == "success",
            "production_deployed": steps.get("Deploy approved Pages artifact", {}).get("conclusion") == "success",
            "production_parity_verified": steps.get("Verify public Pages deployment", {}).get("conclusion") == "success",
        }
        if not all(evidence[field] for field in ("release_preflight_verified", "production_deployed", "production_parity_verified")):
            raise ReleaseFailure("CI_FAILURE", "pages_release_preflight_verified", "Pages workflow succeeded without complete preflight/deploy/production parity evidence")
        return evidence

    def verify_website_production(self, website_sha: str) -> None:
        from scripts.check_release_gate import expected_website_export, verify_production
        expected = expected_website_export(self.website); deadline = time.time() + 900; last = None
        while time.time() < deadline:
            try: verify_production(expected); return
            except Exception as error: last = error; time.sleep(20)
        raise ReleaseFailure("CI_FAILURE", "website_production_verified", f"Hostinger production did not converge: {last}")

    def publish_hf(self, state: dict[str, Any], plan: dict[str, Any], dry_run: bool) -> dict[str, Any]: return self._dispatch("publish-huggingface.yml", state, plan, ["-f", f"dry_run={'true' if dry_run else 'false'}"])

    def verify_hf(self) -> None: self._run([sys.executable, "scripts/check_hf_production_parity.py"], self.root)


class RecoveryShellBackend(ShellBackend, RecoveryBackend):
    """Concrete forward-only backend. It accepts only a separately approved Recovery Plan."""

    def _approved_website(self, plan: dict[str, Any], verify_public: bool) -> str:
        try: from check_release_gate import expected_website_export, verify_production
        except ModuleNotFoundError: from scripts.check_release_gate import expected_website_export, verify_production
        contract = plan["website_contract"]
        website_sha = contract["website_sha"]
        if git(self.website, "rev-parse", "HEAD") != website_sha or self._remote_main(WEBSITE_REPO) != website_sha:
            raise ReleaseFailure("REMOTE_STATE_UNKNOWN", "recovery_website_verified", "Website main moved from approved W1")
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
            raise ReleaseFailure("DATA_MISMATCH", "recovery_plan_verified", "Recovery Plan digest changed")
        if git(self.root, "rev-parse", "HEAD") != plan["dataset_base_sha"] or self._remote_main(DATASET_REPO) != plan["dataset_base_sha"]:
            raise ReleaseFailure("REMOTE_STATE_UNKNOWN", "recovery_plan_verified", "Dataset main moved from approved C0")
        if normalized_file_sha256(self.root / "data/canonical/models.json") != plan["canonical_sha256"]:
            raise ReleaseFailure("DATA_MISMATCH", "recovery_plan_verified", "Canonical changed after Recovery Plan approval")
        if git(self.root, "status", "--porcelain=v1", "--untracked-files=all"):
            raise ReleaseFailure("DATA_MISMATCH", "recovery_plan_verified", "Recovery C0 checkout must be clean")
        self._approved_website(plan, True)

    def commit_source(self, plan: dict[str, Any]) -> str:
        current = git(self.root, "rev-parse", "HEAD")
        message = f"recovery: approve {plan['recovery_id']} plan"
        if current != plan["dataset_base_sha"]:
            if git(self.root, "rev-parse", "HEAD^") == plan["dataset_base_sha"] and git(self.root, "log", "-1", "--format=%s") == message:
                return current
            raise ReleaseFailure("DATA_MISMATCH", "recovery_source_committed", "Dataset HEAD is not approved C0 or resumable S1")
        tracked_plan = self.root / "release-plans" / f"{plan['recovery_id']}.json"
        tracked_plan.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.plan_path, tracked_plan)
        changed = sorted(filter(None, git(self.root, "status", "--porcelain=v1", "--untracked-files=all").splitlines()))
        expected = "?? " + tracked_plan.relative_to(self.root).as_posix()
        if changed != [expected]:
            raise ReleaseFailure("DATA_MISMATCH", "recovery_source_committed", "Recovery S1 must contain only the approved Plan")
        self._run(["git", "add", "--", tracked_plan.relative_to(self.root).as_posix()], self.root)
        self._run(["git", "commit", "-m", message], self.root)
        return git(self.root, "rev-parse", "HEAD")

    def generate_artifacts(self, plan: dict[str, Any], source_sha: str) -> None:
        if git(self.root, "rev-parse", "HEAD") != source_sha:
            raise ReleaseFailure("DATA_MISMATCH", "recovery_artifacts_generated", "Recovery artifact generation must start at S1")
        generated_at = plan["snapshot_generated_at"]
        py = sys.executable
        self._run([py, "scripts/build.py", "--generated-at", generated_at], self.root)
        ensure_snapshot(self.root, generated_at)
        self._run([py, "scripts/generate_pricing_v2_preview.py"], self.root)
        self._run([py, "scripts/export_huggingface.py", "--website-repo", str(self.website), "--website-ref", plan["website_contract"]["website_sha"], "--generated-at", generated_at, "--write"], self.root)
        self._run([py, "scripts/validate.py"], self.root)

    def commit_artifact(self, plan: dict[str, Any], source_sha: str) -> str:
        current = git(self.root, "rev-parse", "HEAD")
        message = f"recovery: publish {plan['recovery_id']} artifacts"
        if current != source_sha:
            if git(self.root, "rev-parse", "HEAD^") == source_sha and git(self.root, "log", "-1", "--format=%s") == message:
                return current
            raise ReleaseFailure("DATA_MISMATCH", "recovery_artifact_committed", "Dataset HEAD is not approved S1 or resumable S2")
        files = sorted(set(filter(None, git(self.root, "diff", "HEAD", "--name-only").splitlines())) | set(filter(None, git(self.root, "ls-files", "--others", "--exclude-standard").splitlines())))
        if not files or any(not is_recovery_artifact_path(path) for path in files):
            raise ReleaseFailure("DATA_MISMATCH", "recovery_artifact_committed", "Recovery S2 contains missing or non-artifact changes")
        self._run(["git", "add", "--", *files], self.root)
        self._run(["git", "commit", "-m", message], self.root)
        return git(self.root, "rev-parse", "HEAD")

    def verify_website_reuse(self, plan: dict[str, Any]) -> str:
        return self._approved_website(plan, True)

    def verify_pre_tag(self, plan: dict[str, Any], digest: str, source_sha: str, artifact_sha: str, website_sha: str) -> str:
        try:
            from check_release_gate import verify_local
            from review_gate import GateError
        except ModuleNotFoundError:
            from scripts.check_release_gate import verify_local
            from scripts.review_gate import GateError
        if self._remote_main(DATASET_REPO) != artifact_sha or self._remote_main(WEBSITE_REPO) != website_sha:
            raise ReleaseFailure("REMOTE_STATE_UNKNOWN", "recovery_pre_tag_verified", "Pushed main SHA does not match approved S2/W1")
        tag = recovery_tag_name(plan)
        identity = {"source_sha": source_sha, "artifact_sha": artifact_sha, "website_sha": website_sha, "release_tag": tag, "release_plan_id": plan["recovery_id"], "release_plan_digest": digest}
        try:
            verify_local(identity, self.website, plan["snapshot_generated_at"][:10])
        except GateError as error:
            raise ReleaseFailure("DATA_MISMATCH", "recovery_pre_tag_verified", str(error)) from None
        self._run(["node", "scripts/test-dataset-pricing-components-parity.mjs", str(self.root / "huggingface")], self.website)
        local = git(self.root, "show-ref", "--verify", f"refs/tags/{tag}", check=False)
        remote = self._run(["git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"], self.root)
        try:
            return assert_recovery_tag_available(plan, local, remote)
        except RecoveryContractError as error:
            raise ReleaseFailure("DATA_MISMATCH", "recovery_pre_tag_verified", str(error)) from None

    def push_tag(self, plan: dict[str, Any], artifact_sha: str, tag: str) -> None:
        if tag != recovery_tag_name(plan):
            raise ReleaseFailure("DATA_MISMATCH", "recovery_tag_pushed", "Recovery tag changed after pre-tag verification")
        local = git(self.root, "show-ref", "--verify", f"refs/tags/{tag}", check=False)
        remote = self._run(["git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"], self.root)
        try:
            assert_recovery_tag_available(plan, local, remote)
        except RecoveryContractError as error:
            raise ReleaseFailure("DATA_MISMATCH", "recovery_tag_pushed", str(error)) from None
        self._run(["git", "tag", "-a", tag, artifact_sha, "-m", f"AICostBudget forward recovery {plan['recovery_id']}"], self.root)
        self._run(["git", "push", "origin", f"refs/tags/{tag}"], self.root)

    def _dispatch(self, workflow: str, state: dict[str, Any], plan: dict[str, Any], extra: list[str] | None = None) -> dict[str, Any]:
        suffix = "publish" if extra and "dry_run=false" in extra else "dry" if extra else "release"
        stage = "recovery_hf_publish_verified" if suffix == "publish" else "recovery_hf_dry_run_verified" if suffix == "dry" else "recovery_pages_preflight_verified"
        key = f"{workflow}:{suffix}"
        run_ids = state.setdefault("workflow_run_ids", {})
        if key in run_ids:
            return self._wait_run_id(int(run_ids[key]), stage)
        known = {int(value) for value in run_ids.values()}
        existing = json.loads(self._run(["gh", "run", "list", "--repo", DATASET_REPO, "--workflow", workflow, "--commit", state["artifact_sha"], "--event", "workflow_dispatch", "--json", "databaseId,headSha", "--limit", "10"], self.root))
        recoverable = [run for run in existing if run.get("headSha") == state["artifact_sha"] and int(run["databaseId"]) not in known]
        if recoverable:
            run_id = int(recoverable[0]["databaseId"])
            run_ids[key] = run_id
            write_json(self.root / STATE_DIR_NAME / "recovery-state" / f"{state['recovery_id']}.json", state)
            return self._wait_run_id(run_id, stage)
        fields = ["-f", f"artifact_sha={state['artifact_sha']}", "-f", f"source_sha={state['source_sha']}", "-f", f"website_sha={state['website_sha']}", "-f", f"release_tag={state['release_tag']}", "-f", f"release_date={plan['snapshot_generated_at'][:10]}", "-f", f"release_plan_id={plan['recovery_id']}", "-f", f"release_plan_digest={state['plan_digest']}"]
        self._run(["gh", "workflow", "run", workflow, "--repo", DATASET_REPO, "--ref", "main", *fields, *(extra or [])], self.root)
        for _ in range(20):
            runs = json.loads(self._run(["gh", "run", "list", "--repo", DATASET_REPO, "--workflow", workflow, "--commit", state["artifact_sha"], "--event", "workflow_dispatch", "--json", "databaseId,headSha", "--limit", "10"], self.root))
            fresh = [run for run in runs if run.get("headSha") == state["artifact_sha"] and int(run["databaseId"]) not in known]
            if fresh:
                run_id = int(fresh[0]["databaseId"])
                run_ids[key] = run_id
                write_json(self.root / STATE_DIR_NAME / "recovery-state" / f"{state['recovery_id']}.json", state)
                return self._wait_run_id(run_id, stage)
            time.sleep(3)
        raise ReleaseFailure("CI_FAILURE", stage, f"Dispatched {workflow} but could not resolve its exact run ID")

    def verify_website_production(self, plan: dict[str, Any]) -> None:
        self._approved_website(plan, True)

    def publish_hf(self, state: dict[str, Any], plan: dict[str, Any], dry_run: bool) -> dict[str, Any]:
        return self._dispatch("publish-huggingface.yml", state, plan, ["-f", f"dry_run={'true' if dry_run else 'false'}"])

    def verify_hf(self, plan: dict[str, Any]) -> None:
        self._run([sys.executable, "scripts/check_hf_production_parity.py"], self.root)


def load_latest(root: Path) -> tuple[dict[str, Any], Path, str]:
    latest = read_json(root / STATE_DIR_NAME / "latest.json")
    path = Path(latest["plan_path"])
    if not path.is_absolute(): path = root / path
    digest = latest["plan_digest"]
    if plan_digest(path) != digest: raise ReleaseFailure("DATA_MISMATCH", "plan_verified", "Latest plan digest changed")
    return read_json(path), path, digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("prepare", "publish"):
        item = sub.add_parser(name); item.add_argument("--dataset-root", type=Path, default=ROOT); item.add_argument("--website-root", type=Path, required=True)
        if name == "prepare": item.add_argument("--generated-at")
    recovery = sub.add_parser("publish-recovery")
    recovery.add_argument("--dataset-root", type=Path, default=ROOT)
    recovery.add_argument("--website-root", type=Path, required=True)
    recovery.add_argument("--plan", type=Path, required=True)
    recovery.add_argument("--plan-digest", required=True)
    args = parser.parse_args()
    root, website = args.dataset_root.resolve(), args.website_root.resolve()
    try:
        if args.action == "prepare":
            plan, path, digest = prepare_release(root, website, args.generated_at)
            ready = not plan["workspace"]["unrelated_files"] and bool(plan["models"]) and all(test["status"] == "PASS" for test in plan["tests"])
            print(json.dumps({"release_id": plan["release_id"], "plan_digest": digest, "models": [f"{row['provider_id']}/{row['model_id']}:{row['change_type']}" for row in plan["models"]], "v1_records": plan["projection_contracts"]["v1"]["records"], "v2_records": plan["projection_contracts"]["v2"]["records"], "plan": str(path), "ready_for_approval": ready}, ensure_ascii=False, indent=2))
            print("READY FOR APPROVAL: " + ("YES" if ready else "NO"))
        elif args.action == "publish":
            plan, path, digest = load_latest(root); store = ReleaseStateStore(root, plan["release_id"]); backend = ShellBackend(root, website, path, digest)
            print(json.dumps(publish_release(plan, path, digest, store, backend), ensure_ascii=False, indent=2)); print("PRODUCTION VERIFIED")
        else:
            path = args.plan.resolve()
            digest = args.plan_digest
            if not re.fullmatch(r"[0-9a-f]{64}", digest) or not path.is_file() or plan_digest(path) != digest:
                raise ReleaseFailure("DATA_MISMATCH", "recovery_plan_verified", "Exact approved Recovery Plan path/digest is required")
            plan = read_json(path)
            try: validate_recovery_plan(plan)
            except RecoveryContractError as error: raise ReleaseFailure("DATA_MISMATCH", "recovery_plan_verified", str(error)) from None
            store = RecoveryStateStore(root, plan["recovery_id"])
            backend = RecoveryShellBackend(root, website, path, digest)
            print(json.dumps(publish_recovery(plan, path, digest, store, backend), ensure_ascii=False, indent=2)); print("PRODUCTION VERIFIED")
    except ReleaseFailure as error:
        print(f"{error.classification}: stage={error.stage}: {error}", file=sys.stderr)
        if args.action == "publish": print(f"Resume: .\\scripts\\daily-pricing-release.ps1 -Publish -DatasetPath \"{root}\" -WebsitePath \"{website}\"", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__": main()
