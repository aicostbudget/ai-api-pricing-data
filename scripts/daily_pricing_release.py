"""Ordinary model and pricing release: validate (dry run), prepare (source + artifact commits), publish."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

try:
    from lib import next_snapshot_id, parse_snapshot_id, snapshot_ids, snapshot_sort_key
except ModuleNotFoundError:
    from scripts.lib import next_snapshot_id, parse_snapshot_id, snapshot_ids, snapshot_sort_key

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = "data/canonical/models.json"
SNAPSHOTS_PATH = "data/snapshots"
# Same four files the Website's own scheduled pricing sync may change.
WEBSITE_OUTPUTS = (
    "data/model-pricing.json",
    "data/pricing-v2-projection/model-pricing.v2.json",
    "data/pricing-v2-projection/price-change-events.v1.json",
    "data/pricing-v2-projection/pricing-meta.v1.json",
)
VOLATILE_WEBSITE_KEYS = {
    "generatedAt", "generated_at", "provenanceTimestamp", "provenance_timestamp", "timestamp",
}


class ReleaseFailure(RuntimeError):
    def __init__(self, classification: str, stage: str, message: str):
        super().__init__(message)
        self.classification = classification
        self.stage = stage


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=repo, text=True, encoding="utf-8", capture_output=True)
    if check and result.returncode:
        raise ReleaseFailure("CODE_FAILURE", "git", result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def command(args: list[str], cwd: Path, env: Mapping[str, str] | None = None, stage: str = "validate") -> str:
    # Child Python output is forced to UTF-8 and undecodable bytes are replaced, so a
    # failing step always reports its own error instead of crashing the reporter.
    result = subprocess.run(
        args, cwd=cwd, text=True, encoding="utf-8", errors="replace", capture_output=True,
        env={**(os.environ if env is None else env), "PYTHONIOENCODING": "utf-8"},
    )
    if result.returncode:
        message = (result.stderr or "").strip() or (result.stdout or "").strip() or f"{args[0]} exited with {result.returncode}"
        raise ReleaseFailure("VALIDATION_SCRIPT_FAILURE", stage, message)
    return (result.stdout or "").strip()


def require_checkout(root: Path, required: str) -> Path:
    root = root.resolve()
    if not (root / ".git").exists() or not (root / required).is_file():
        raise ReleaseFailure("DATA_MISMATCH", "validate", f"Invalid checkout: {root}")
    return root


def parse_generated_at(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ReleaseFailure("DATA_MISMATCH", "validate", "generated-at must be an explicit UTC timestamp")
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def row_identity(row: Mapping[str, Any]) -> str:
    provider = row.get("provider_id") or row.get("provider")
    model = row.get("model_id") or row.get("id")
    if not isinstance(provider, str) or not provider or not isinstance(model, str) or not model:
        raise ReleaseFailure("DATA_MISMATCH", "validate", "Canonical row lacks provider/model identity")
    return f"{provider}/{model}"


def classify_changes(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    old = {row_identity(row): row for row in before}
    new = {row_identity(row): row for row in after}
    changes: list[dict[str, Any]] = []
    lifecycle_fields = {"status", "release_stage", "lifecycle", "released_at"}
    pricing_fields = {"pricing", "price_records", "time_pricing"}
    for identity in sorted(set(old) | set(new)):
        if identity not in old:
            kind = "added"
        elif identity not in new:
            kind = "lifecycle"
        elif old[identity] == new[identity]:
            continue
        else:
            changed = {
                key for key in set(old[identity]) | set(new[identity])
                if old[identity].get(key) != new[identity].get(key)
            }
            if changed & pricing_fields:
                kind = "pricing"
            elif changed & lifecycle_fields:
                kind = "lifecycle"
            else:
                kind = "metadata"
        provider, model = identity.split("/", 1)
        changes.append({
            "provider_id": provider,
            "model_id": model,
            "change_type": kind,
            "price_change": kind == "pricing",
        })
    return changes


def price_event_changes(changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only true price deltas are eligible for the price-event generator."""
    return [change for change in changes if change["change_type"] == "pricing"]


def _normalized_business_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _normalized_business_value(item)
            for key, item in sorted(value.items())
            if key not in VOLATILE_WEBSITE_KEYS
        }
    if isinstance(value, list):
        return [_normalized_business_value(item) for item in value]
    return value


def website_business_changed(before: bytes | None, after: bytes | None) -> bool:
    if before is None or after is None:
        return before != after
    try:
        return _normalized_business_value(json.loads(before)) != _normalized_business_value(json.loads(after))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return before.replace(b"\r\n", b"\n") != after.replace(b"\r\n", b"\n")


def changed_paths(repo: Path) -> list[str]:
    tracked = git(repo, "diff", "HEAD", "--name-only").splitlines()
    untracked = git(repo, "ls-files", "--others", "--exclude-standard").splitlines()
    return sorted(set(filter(None, tracked + untracked)))


@contextmanager
def isolated_workspaces(root: Path, website: Path, dataset_ref: str, website_ref: str):
    with tempfile.TemporaryDirectory(prefix="daily-pricing-release-") as tmp:
        temporary = Path(tmp)
        dataset_candidate = temporary / "dataset"
        website_candidate = temporary / "website"
        command(["git", "clone", "--no-hardlinks", str(root), str(dataset_candidate)], temporary)
        command(["git", "checkout", "--detach", dataset_ref], dataset_candidate)
        command(["git", "clone", "--no-hardlinks", str(website), str(website_candidate)], temporary)
        command(["git", "checkout", "--detach", website_ref], website_candidate)
        yield dataset_candidate, website_candidate


def _head_bytes(repo: Path, path: str) -> bytes | None:
    result = subprocess.run(["git", "show", f"HEAD:{path}"], cwd=repo, capture_output=True)
    return result.stdout if result.returncode == 0 else None


@dataclass(frozen=True)
class ValidationRun:
    generated_files: list[str]
    website_business_change: bool


def build_source_snapshot(root: Path, generated_at: str) -> str:
    """Build once and write this release's snapshot under the next free id of its UTC date."""
    snapshot_id = next_snapshot_id(snapshot_ids(root / SNAPSHOTS_PATH), generated_at[:10])
    command([sys.executable, "scripts/build.py", "--generated-at", generated_at, "--snapshot-id", snapshot_id], root)
    return snapshot_id


def commit_source(root: Path, generated_at: str, snapshot_id: str) -> str:
    """Source commit: canonical change plus its tracked snapshot, dated at generated_at."""
    command(["git", "add", "--", SOURCE_PATH, f"{SNAPSHOTS_PATH}/{snapshot_id}"], root)
    dated = {**os.environ, "GIT_AUTHOR_DATE": generated_at, "GIT_COMMITTER_DATE": generated_at}
    command(["git", "commit", "-m", f"data: prepare pricing source {snapshot_id}"], root, dated)
    return git(root, "rev-parse", "HEAD")


def source_snapshot_id(root: Path, source_ref: str = "HEAD") -> str:
    """The single snapshot directory added by a source commit."""
    paths = git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", source_ref, "--", SNAPSHOTS_PATH).splitlines()
    ids = sorted({path.split("/")[2] for path in paths if path.count("/") >= 3})
    if len(ids) != 1:
        raise ReleaseFailure("DATA_MISMATCH", "validate", f"Source commit must add exactly one snapshot, found: {ids or 'none'}")
    parse_snapshot_id(ids[0])
    return ids[0]


def snapshot_pair(root: Path, snapshot_id: str) -> tuple[Path, Path]:
    snapshots = root / SNAPSHOTS_PATH
    earlier = [
        candidate for candidate in snapshot_ids(snapshots)
        if snapshot_sort_key(candidate) < snapshot_sort_key(snapshot_id) and (snapshots / candidate / "prices.json").is_file()
    ]
    if not earlier:
        raise ReleaseFailure("DATA_MISMATCH", "validate", "No prior tracked snapshot is available")
    return snapshots / earlier[-1] / "prices.json", snapshots / snapshot_id / "prices.json"


def run_validation_pipeline(root: Path, website: Path, generated_at: str, changes: list[dict[str, Any]]) -> ValidationRun:
    """Generate every artifact from the source commit checked out at root (HEAD)."""
    python = sys.executable
    source_sha = git(root, "rev-parse", "HEAD")
    snapshot_id = source_snapshot_id(root)
    env = {**os.environ, "SOURCE_COMMIT_SHA": source_sha}
    website_before = {path: _head_bytes(website, path) for path in WEBSITE_OUTPUTS}
    command([python, "scripts/build.py", "--generated-at", generated_at, "--snapshot-id", snapshot_id], root, env)
    if git(root, "status", "--porcelain=v1", "--", f"{SNAPSHOTS_PATH}/{snapshot_id}"):
        raise ReleaseFailure("DATA_MISMATCH", "validate", f"Rebuilt snapshot {snapshot_id} differs from the source commit")
    if price_event_changes(changes):
        before_snapshot, after_snapshot = snapshot_pair(root, snapshot_id)
        command([
            python, "scripts/generate_price_change_events.py",
            "--before", str(before_snapshot), "--after", str(after_snapshot),
        ], root, env)
    command([python, "scripts/generate_pricing_v2_preview.py"], root, env)
    command([
        python, "scripts/generate_website_projection_v2.py", "--effective-at", generated_at,
        "--generated-at", generated_at, "--website-dataset", str(website / "data/model-pricing.json"),
        "--existing-artifact-git-ref", "HEAD", "--preserve-existing-selections",
    ], root, env)
    command(["node", "scripts/sync-pricing-artifacts.mjs", "--write", "--dataset", str(root), "--website", str(website)], website, env)
    command([
        python, "scripts/export_huggingface.py", "--website-repo", str(website), "--website-ref", "WORKTREE",
        "--generated-at", generated_at, "--write",
    ], root, env)
    command([python, "scripts/validate.py"], root, env)
    command([python, "scripts/validate_pricing_v2_preview.py"], root, env)
    command(["node", "scripts/sync-pricing-artifacts.mjs", "--check", "--dataset", str(root), "--website", str(website)], website, env)
    command([
        python, "scripts/export_huggingface.py", "--website-repo", str(website), "--website-ref", "WORKTREE",
        "--generated-at", generated_at, "--check",
    ], root, env)
    website_changed = any(
        website_business_changed(website_before[path], (website / path).read_bytes() if (website / path).is_file() else None)
        for path in WEBSITE_OUTPUTS
    )
    return ValidationRun(changed_paths(root), website_changed)


def working_tree_changes(root: Path) -> list[dict[str, Any]]:
    dirty = changed_paths(root)
    if dirty != [SOURCE_PATH]:
        raise ReleaseFailure("DATA_MISMATCH", "validate", f"Only {SOURCE_PATH} may be modified before a release, found: {dirty or 'no change'}")
    changes = classify_changes(json.loads(git(root, "show", f"HEAD:{SOURCE_PATH}")), read_json(root / SOURCE_PATH))
    if not changes:
        raise ReleaseFailure("DATA_MISMATCH", "validate", "No canonical model change")
    return changes


def candidate_source(dataset_candidate: Path, canonical: bytes, generated_at: str) -> str:
    (dataset_candidate / SOURCE_PATH).write_bytes(canonical)
    command(["git", "config", "user.name", "daily-pricing-release"], dataset_candidate)
    command(["git", "config", "user.email", "daily-pricing-release@localhost"], dataset_candidate)
    snapshot_id = build_source_snapshot(dataset_candidate, generated_at)
    commit_source(dataset_candidate, generated_at, snapshot_id)
    return snapshot_id


def validate_release(
    root: Path,
    website: Path,
    generated_at: str | None = None,
    runner: Callable[[Path, Path, str, list[dict[str, Any]]], ValidationRun] = run_validation_pipeline,
    workspace_factory: Callable[..., Any] = isolated_workspaces,
    source_factory: Callable[[Path, bytes, str], str] = candidate_source,
) -> dict[str, Any]:
    """Dry run of prepare in throwaway clones; nothing in root or website changes."""
    root = require_checkout(root, SOURCE_PATH)
    website = require_checkout(website, "data/model-pricing.json")
    changes = working_tree_changes(root)
    generated_at = parse_generated_at(generated_at)
    website_sha = git(website, "rev-parse", "HEAD")
    with workspace_factory(root, website, "HEAD", website_sha) as (dataset_candidate, website_candidate):
        snapshot_id = source_factory(dataset_candidate, (root / SOURCE_PATH).read_bytes(), generated_at)
        result = runner(dataset_candidate, website_candidate, generated_at, changes)
    return {
        "changed_models": [f"{row['provider_id']}/{row['model_id']}" for row in changes],
        "changes": changes,
        "price_change": any(row["price_change"] for row in changes),
        "snapshot_id": snapshot_id,
        "generated_files": result.generated_files,
        "website_business_change": result.website_business_change,
        "validation": "PASS",
        "ready_for_human_approval": True,
    }


def prepare_release(
    root: Path,
    website: Path,
    generated_at: str | None = None,
    runner: Callable[[Path, Path, str, list[dict[str, Any]]], ValidationRun] = run_validation_pipeline,
    workspace_factory: Callable[..., Any] = isolated_workspaces,
) -> dict[str, Any]:
    """Create two local commits: canonical + snapshot, then the generated artifacts. Never pushes."""
    root = require_checkout(root, SOURCE_PATH)
    website = require_checkout(website, "data/model-pricing.json")
    changes = working_tree_changes(root)
    generated_at = parse_generated_at(generated_at)
    snapshot_id = build_source_snapshot(root, generated_at)
    source_sha = commit_source(root, generated_at, snapshot_id)
    command(["git", "checkout", "--", "."], root)
    command(["git", "clean", "-fdq", "--", "api", "data"], root)
    website_sha = git(website, "rev-parse", "HEAD")
    with workspace_factory(root, website, source_sha, website_sha) as (_dataset_candidate, website_candidate):
        result = runner(root, website_candidate, generated_at, changes)
    git(root, "add", "--", *result.generated_files)
    git(root, "commit", "-m", f"data: publish pricing artifacts {snapshot_id}")
    return {
        "changed_models": [f"{row['provider_id']}/{row['model_id']}" for row in changes],
        "changes": changes,
        "price_change": any(row["price_change"] for row in changes),
        "snapshot_id": snapshot_id,
        "source_sha": source_sha,
        "artifact_sha": git(root, "rev-parse", "HEAD"),
        "generated_files": result.generated_files,
        "website_business_change": result.website_business_change,
        "status": "PREPARED",
    }


def _push_main(repo: Path, sha: str) -> None:
    command(["git", "push", "origin", f"{sha}:main"], repo, stage="publish")


def _dispatch_huggingface(repo: Path) -> None:
    command([
        "gh", "workflow", "run", "publish-huggingface.yml", "--ref", "main",
        "-f", "recovery_mode=false",
    ], repo, stage="publish")


def _normalized_bytes(value: bytes | None) -> bytes | None:
    return None if value is None else value.replace(b"\r\n", b"\n")


def verify_artifact_commit(root: Path, release_sha: str, dataset_candidate: Path, generated_files: list[str]) -> None:
    """The reviewed artifact commit must contain exactly what the source commit regenerates."""
    for path in generated_files:
        shown = subprocess.run(["git", "show", f"{release_sha}:{path}"], cwd=root, capture_output=True)
        committed = shown.stdout if shown.returncode == 0 else None
        regenerated = (dataset_candidate / path).read_bytes() if (dataset_candidate / path).is_file() else None
        if _normalized_bytes(committed) != _normalized_bytes(regenerated):
            raise ReleaseFailure("DATA_MISMATCH", "publish", f"Artifact commit differs from regenerated output: {path}")


def publish_release(
    root: Path,
    website: Path,
    runner: Callable[[Path, Path, str, list[dict[str, Any]]], ValidationRun] = run_validation_pipeline,
    workspace_factory: Callable[..., Any] = isolated_workspaces,
    dataset_push: Callable[[Path, str], None] = _push_main,
    website_push: Callable[[Path, str], None] = _push_main,
    hf_dispatch: Callable[[Path], None] = _dispatch_huggingface,
    artifact_check: Callable[[Path, str, Path, list[str]], None] = verify_artifact_commit,
) -> dict[str, str]:
    root = require_checkout(root, SOURCE_PATH)
    website = require_checkout(website, "data/model-pricing.json")
    if git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ReleaseFailure("DATA_MISMATCH", "publish", "Publish requires the prepared release commits to be clean")
    if git(website, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ReleaseFailure("DATA_MISMATCH", "publish", "Website checkout must be clean before publish")
    release_sha = git(root, "rev-parse", "HEAD")
    source_sha = git(root, "rev-parse", f"{release_sha}^")
    website_sha = git(website, "rev-parse", "HEAD")
    if git(root, "diff", "--name-only", source_sha, release_sha, "--", SOURCE_PATH):
        raise ReleaseFailure("DATA_MISMATCH", "publish", "The artifact commit must not change canonical data")
    snapshot_id = source_snapshot_id(root, source_sha)
    source_paths = set(git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", source_sha).splitlines())
    if any(path != SOURCE_PATH and not path.startswith(f"{SNAPSHOTS_PATH}/{snapshot_id}/") for path in source_paths):
        raise ReleaseFailure("DATA_MISMATCH", "publish", "The source commit may change only canonical data and its snapshot")
    generated_at = parse_generated_at(git(root, "show", "-s", "--format=%cI", source_sha))
    before = json.loads(git(root, "show", f"{source_sha}^:{SOURCE_PATH}"))
    after = json.loads(git(root, "show", f"{source_sha}:{SOURCE_PATH}"))
    changes = classify_changes(before, after)
    if not changes:
        raise ReleaseFailure("DATA_MISMATCH", "publish", "The source commit has no canonical model change")

    with workspace_factory(root, website, source_sha, website_sha) as (dataset_candidate, website_candidate):
        result = runner(dataset_candidate, website_candidate, generated_at, changes)
        artifact_check(root, release_sha, dataset_candidate, result.generated_files)
        if result.website_business_change:
            command([
                "node", "scripts/sync-pricing-artifacts.mjs", "--write",
                "--dataset", str(dataset_candidate), "--website", str(website),
            ], website, stage="publish")
            website_changes = changed_paths(website)
            unexpected = sorted(set(website_changes) - set(WEBSITE_OUTPUTS))
            if unexpected:
                raise ReleaseFailure(
                    "DATA_MISMATCH", "publish",
                    "Website sync changed non-allowlisted paths: " + ", ".join(unexpected),
                )
            if not website_changes:
                raise ReleaseFailure("DATA_MISMATCH", "publish", "Website business change produced no sync diff")
            git(website, "add", "--", *WEBSITE_OUTPUTS)
            git(website, "commit", "-m", f"data: sync pricing for {release_sha[:7]}")
            website_sha = git(website, "rev-parse", "HEAD")
            website_push(website, website_sha)

    # Hugging Face export validates against the published Website, so it is dispatched last.
    dataset_push(root, release_sha)
    hf_dispatch(root)
    return {
        "release_sha": release_sha,
        "source_sha": source_sha,
        "snapshot_id": snapshot_id,
        "website_sha": website_sha,
        "website_business_change": "YES" if result.website_business_change else "NO",
        "status": "PUBLISH STARTED",
        "next_step": indexnow_next_step(website_sha) if result.website_business_change else "NONE",
    }


@dataclass(frozen=True)
class SuiteResult:
    name: str
    passed: bool
    output_tail: str


def run_suite(name: str, args: list[str], cwd: Path, env: Mapping[str, str]) -> SuiteResult:
    result = subprocess.run(
        args, cwd=cwd, text=True, encoding="utf-8", errors="replace", capture_output=True,
        env={**os.environ, **env, "PYTHONIOENCODING": "utf-8"},
    )
    lines = ((result.stdout or "") + "\n" + (result.stderr or "")).strip().splitlines()
    return SuiteResult(name, result.returncode == 0, "\n".join(lines[-25:]))


def run_cross_repo_suites(dataset: Path, website: Path) -> list[SuiteResult]:
    """Both complete suites against the synced pair, as the repositories will look after publish."""
    npm = "npm.cmd" if os.name == "nt" else "npm"
    return [
        run_suite("website test:all", [npm, "run", "test:all"], website, {
            "DATASET_ROOT": str(dataset), "DATASET_HF_DIR": str(dataset / "huggingface"),
        }),
        run_suite("dataset unittest", [sys.executable, "-m", "unittest", "discover", "-s", "tests"], dataset, {
            "WEBSITE_SOURCE_ROOT": str(website),
        }),
    ]


def link_directory(link: Path, target: Path) -> None:
    """Share the Website dependencies with a throwaway clone instead of reinstalling them."""
    if os.name == "nt":
        command(["cmd", "/c", "mklink", "/J", str(link), str(target)], link.parent, stage="rehearse")
    else:
        link.symlink_to(target, target_is_directory=True)


def unlink_directory(link: Path) -> None:
    # shutil.rmtree in Python 3.11 follows Windows junctions and would delete the real
    # dependencies, so the link itself is removed before the clone is cleaned up.
    if os.name == "nt":
        os.rmdir(link)
    else:
        link.unlink()


def ensure_local_main(clone: Path) -> None:
    """Some Website tests diff against the local main branch, which a clone of a feature branch
    lacks: take it from the source's main, else from the source's origin/main."""
    if git(clone, "rev-parse", "--verify", "--quiet", "refs/heads/main", check=False):
        return
    if git(clone, "rev-parse", "--verify", "--quiet", "refs/remotes/origin/main", check=False):
        command(["git", "branch", "main", "origin/main"], clone, stage="rehearse")
        return
    git(clone, "fetch", "--quiet", "origin", "refs/remotes/origin/main:refs/heads/main", check=False)


def rehearse_release(
    root: Path,
    website: Path,
    publish: Callable[..., dict[str, str]] = publish_release,
    suites: Callable[[Path, Path], list[SuiteResult]] = run_cross_repo_suites,
    run_tests: bool = True,
) -> dict[str, Any]:
    """Publish the prepared commits into throwaway clones with recorded pushes, then run both
    suites on the synced pair. Nothing is pushed and neither checkout changes."""
    root = require_checkout(root, SOURCE_PATH)
    website = require_checkout(website, "data/model-pricing.json")
    for repo, label in ((root, "Dataset"), (website, "Website")):
        if git(repo, "status", "--porcelain=v1", "--untracked-files=all"):
            raise ReleaseFailure("DATA_MISMATCH", "rehearse", f"{label} checkout must be clean: the rehearsal publishes its HEAD")
    dependencies = website / "node_modules"
    if run_tests and not dependencies.is_dir():
        raise ReleaseFailure("DATA_MISMATCH", "rehearse", f"Website dependencies are missing: run npm ci in {website}")
    with tempfile.TemporaryDirectory(prefix="daily-pricing-rehearsal-", ignore_cleanup_errors=True) as tmp:
        temporary = Path(tmp)
        dataset_clone, website_clone = temporary / "dataset", temporary / "website"
        for source, clone in ((root, dataset_clone), (website, website_clone)):
            command(["git", "clone", "--quiet", "--no-hardlinks", str(source), str(clone)], temporary, stage="rehearse")
            command(["git", "checkout", "--quiet", "--detach", git(source, "rev-parse", "HEAD")], clone, stage="rehearse")
        for key in ("user.name", "user.email"):
            command(["git", "config", key, git(website, "config", key, check=False) or "daily-pricing-rehearsal"], website_clone, stage="rehearse")
        ensure_local_main(website_clone)
        calls: list[str] = []
        report = publish(
            dataset_clone, website_clone,
            dataset_push=lambda _repo, _sha: calls.append("dataset"),
            website_push=lambda _repo, _sha: calls.append("website"),
            hf_dispatch=lambda _repo: calls.append("hf"),
        )
        expected = (["website"] if report["website_business_change"] == "YES" else []) + ["dataset", "hf"]
        if calls != expected:
            raise ReleaseFailure("CODE_FAILURE", "rehearse", f"Publish order was {calls}, expected {expected}")
        results: list[SuiteResult] = []
        if run_tests:
            link = website_clone / "node_modules"
            link_directory(link, dependencies)
            try:
                results = suites(dataset_clone, website_clone)
            finally:
                unlink_directory(link)
    return {
        "release_sha": report["release_sha"],
        "source_sha": report["source_sha"],
        "snapshot_id": report["snapshot_id"],
        "website_business_change": report["website_business_change"],
        "push_order": calls,
        "suites": [{"name": result.name, "passed": result.passed, "output_tail": result.output_tail} for result in results],
        "status": "REHEARSAL PASS" if all(result.passed for result in results) else "REHEARSAL FAIL",
    }


def _run_capture(args: list[str], cwd: Path) -> tuple[int, str]:
    result = subprocess.run(
        args, cwd=cwd, text=True, encoding="utf-8", errors="replace", capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    return result.returncode, ((result.stdout or "") + (result.stderr or "")).strip()


def follow_website_live(website: Path, website_sha: str, run: Callable[[list[str], Path], tuple[int, str]] = _run_capture) -> dict[str, Any]:
    """Wait for Hostinger to serve the pushed commit (read from the live bundle's release id)."""
    code, output = run(["node", "scripts/verify-live-deploy.mjs", "--commit", website_sha, "--wait", "900"], website)
    state = next((json.loads(line) for line in output.splitlines() if line.startswith("{")), {})
    return {"passed": code == 0, "state": state.get("state", "unknown"), "live_commit": state.get("live")}


def follow_huggingface(
    root: Path,
    release_sha: str,
    run: Callable[[list[str], Path], tuple[int, str]] = _run_capture,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = 12,
) -> dict[str, Any]:
    """Wait for the dispatched Hugging Face publish run; its last step is the production parity check."""
    run_id = None
    for _ in range(attempts):
        code, output = run([
            "gh", "run", "list", "--workflow", "publish-huggingface.yml", "--branch", "main",
            "--event", "workflow_dispatch", "--limit", "10", "--json", "databaseId,headSha",
        ], root)
        if code == 0:
            run_id = next((item["databaseId"] for item in json.loads(output or "[]") if item["headSha"] == release_sha), None)
        if run_id:
            break
        sleep(10)
    if not run_id:
        return {"passed": False, "run_id": None, "parity": "unknown", "reason": "no Hugging Face publish run for the release commit"}
    code, _ = run(["gh", "run", "watch", str(run_id), "--exit-status", "--interval", "15"], root)
    _, log = run(["gh", "run", "view", str(run_id), "--log"], root)
    parity = "PASS" if "BUSINESS_PARITY: PASS" in log else "FAIL"
    pushed = next((line.split("HF_PUSHED: ", 1)[1].strip() for line in log.splitlines() if "HF_PUSHED: " in line), None)
    return {"passed": code == 0 and parity == "PASS", "run_id": run_id, "parity": parity, "hf_commit": pushed}


def follow_indexnow(website: Path, website_sha: str, run: Callable[[list[str], Path], tuple[int, str]] = _run_capture) -> dict[str, Any]:
    """IndexNow dry run only: submitting to an external service needs a person's approval."""
    npm = "npm.cmd" if os.name == "nt" else "npm"
    code, output = run([npm, "run", "indexnow:pricing", "--", "--commit", website_sha, "--wait-live", "600"], website)
    urls = [line.strip().strip('",') for line in output.splitlines() if line.strip().startswith('"https://')]
    return {"passed": code == 0, "dry_run_urls": urls, "send": f"{npm} run indexnow:pricing -- --commit {website_sha} --send"}


def follow_release(
    root: Path,
    website: Path,
    report: Mapping[str, str],
    website_live: Callable[[Path, str], dict[str, Any]] = follow_website_live,
    huggingface: Callable[[Path, str], dict[str, Any]] = follow_huggingface,
    indexnow: Callable[[Path, str], dict[str, Any]] = follow_indexnow,
) -> dict[str, Any]:
    """After publish: Website live, Hugging Face published with parity, IndexNow dry run."""
    steps: dict[str, Any] = {}
    business = report["website_business_change"] == "YES"
    if business:
        steps["website_live"] = website_live(website, report["website_sha"])
    steps["huggingface"] = huggingface(root, report["release_sha"])
    if business and steps["website_live"]["passed"]:
        steps["indexnow"] = indexnow(website, report["website_sha"])
    passed = all(step["passed"] for step in steps.values()) and (not business or "indexnow" in steps)
    return {**report, "follow": steps, "status": "PUBLISHED AND VERIFIED" if passed else "PUBLISHED, FOLLOW-UP NEEDS ATTENTION"}


def indexnow_next_step(website_sha: str) -> str:
    """Pages only change after Hostinger deploys, so IndexNow is a separate, confirmed step."""
    return (
        f"After the Website deploy is live, in the Website checkout: npm.cmd run indexnow:pricing -- "
        f"--commit {website_sha} --wait-live 600 (dry run), then rerun with --send once approved"
    )


def print_report(report: Mapping[str, Any]) -> None:
    print("CHANGED MODELS: " + ", ".join(report["changed_models"]))
    print("CHANGE TYPE: " + ", ".join(row["change_type"] for row in report["changes"]))
    print("PRICE CHANGE: " + ("YES" if report["price_change"] else "NO"))
    print("SNAPSHOT: " + report["snapshot_id"])
    print("GENERATED FILES: " + (", ".join(report["generated_files"]) or "NONE"))
    print("WEBSITE BUSINESS CHANGE: " + ("YES" if report["website_business_change"] else "NO"))
    if "source_sha" in report:
        print("SOURCE COMMIT: " + report["source_sha"])
        print("ARTIFACT COMMIT: " + report["artifact_sha"])
        print("STATUS: " + report["status"] + " (review, run tests and approval gates, then publish)")
    else:
        print("VALIDATION: " + report["validation"])
        print("READY FOR HUMAN APPROVAL: " + ("YES" if report["ready_for_human_approval"] else "NO"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("validate", "prepare"):
        sub = subparsers.add_parser(action)
        sub.add_argument("--dataset-root", type=Path, default=ROOT)
        sub.add_argument("--website-root", type=Path, required=True)
        sub.add_argument("--generated-at")
    publish = subparsers.add_parser("publish")
    publish.add_argument("--dataset-root", type=Path, default=ROOT)
    publish.add_argument("--website-root", type=Path, required=True)
    publish.add_argument("--follow", action="store_true", help="wait for the Website deploy and Hugging Face publish, then run the IndexNow dry run")
    rehearse = subparsers.add_parser("rehearse")
    rehearse.add_argument("--dataset-root", type=Path, default=ROOT)
    rehearse.add_argument("--website-root", type=Path, required=True)
    rehearse.add_argument("--skip-tests", action="store_true", help="only rehearse the publish steps")
    args = parser.parse_args()
    try:
        if args.action == "validate":
            print_report(validate_release(args.dataset_root, args.website_root, args.generated_at))
        elif args.action == "prepare":
            print_report(prepare_release(args.dataset_root, args.website_root, args.generated_at))
        elif args.action == "rehearse":
            report = rehearse_release(args.dataset_root, args.website_root, run_tests=not args.skip_tests)
            print(json.dumps(report, indent=2))
            if report["status"] != "REHEARSAL PASS":
                raise SystemExit(1)
        else:
            report = publish_release(args.dataset_root, args.website_root)
            print(json.dumps(report, indent=2), flush=True)
            if args.follow:
                followed = follow_release(args.dataset_root.resolve(), args.website_root.resolve(), report)
                print(json.dumps(followed, indent=2))
                if followed["status"] != "PUBLISHED AND VERIFIED":
                    raise SystemExit(1)
    except ReleaseFailure as error:
        print(f"{error.classification}: stage={error.stage}: {error}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
