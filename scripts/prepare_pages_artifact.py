from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from lib import ROOT, SNAPSHOT_ID, latest_snapshot_id_for_date, snapshot_ids
except ModuleNotFoundError:
    from scripts.lib import ROOT, SNAPSHOT_ID, latest_snapshot_id_for_date, snapshot_ids

RELEASE_SHA = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_PUBLIC_PATHS = (
    "api/v1/prices.json", "api/v1/prices.csv", "api/v1/meta.json",
    "api/v1/providers", "api/v1/models",
)
FORBIDDEN_PUBLIC_PATHS = (
    ".git", ".github", "data", "schema", "scripts", "tests", "pyproject.toml",
)
# Hand-written static pages published beside the API (published path -> repository path).
STATIC_PAGES = {"index.html": "pages/index.html"}


def relative_manifest(path: Path) -> list[str]:
    return sorted(item.relative_to(path).as_posix() for item in path.rglob("*") if item.is_file())


def manifest_summary(path: Path) -> dict[str, Any]:
    files = [item for item in path.rglob("*") if item.is_file()]
    return {
        "output": str(path), "fileCount": len(files),
        "totalBytes": sum(item.stat().st_size for item in files),
        "topLevel": sorted({item.relative_to(path).parts[0] for item in files}),
        "files": relative_manifest(path),
    }


def ensure_safe_output_dir(output_dir: Path) -> Path:
    resolved = output_dir.resolve()
    root = ROOT.resolve()
    if resolved == root or resolved.anchor == str(resolved):
        raise ValueError("Refusing unsafe Pages artifact output")
    if root in resolved.parents and resolved.relative_to(root).parts[0] in ("api", *FORBIDDEN_PUBLIC_PATHS):
        raise ValueError("Refusing to overwrite repository inputs with Pages artifact output")
    return resolved


def _latest_snapshot(ids: list[str], date: str) -> str:
    """The public API must match the latest snapshot of its UTC date (YYYY-MM-DD or YYYY-MM-DD-N)."""
    latest = latest_snapshot_id_for_date(ids, date)
    if latest is None:
        raise FileNotFoundError(f"No snapshot exists for {date}")
    return latest


def _validate_files(files: dict[str, bytes], release_sha: str, snapshot_reader) -> None:
    if not RELEASE_SHA.fullmatch(release_sha):
        raise ValueError("Approved release SHA must be a full lowercase Git SHA")
    for required in REQUIRED_PUBLIC_PATHS:
        if required not in files and not any(path.startswith(required + "/") for path in files):
            raise FileNotFoundError(f"Required public path is missing: {required}")
    meta = json.loads(files["api/v1/meta.json"])
    if meta.get("source_commit_sha") != release_sha:
        raise ValueError("Public metadata must identify the approved release SHA")
    generated_at = meta.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at.endswith("Z"):
        raise ValueError("Public generated_at must be UTC")
    snapshot_date = datetime.fromisoformat(generated_at.replace("Z", "+00:00")).date().isoformat()
    for suffix in ("json", "csv"):
        if files[f"api/v1/prices.{suffix}"] != snapshot_reader(snapshot_date, suffix):
            raise ValueError(f"Public API and {snapshot_date} snapshot differ: prices.{suffix}")


def workspace_pages(source_root: Path, release_sha: str) -> tuple[dict[str, bytes], str]:
    source_root = source_root.resolve()
    api_root = source_root / "api"
    files = {
        path.relative_to(source_root).as_posix(): path.read_bytes()
        for path in api_root.rglob("*") if path.is_file()
    }
    _validate_files(
        files, release_sha,
        lambda date, suffix: (
            source_root / f"data/snapshots/{_latest_snapshot(snapshot_ids(source_root / 'data/snapshots'), date)}/prices.{suffix}"
        ).read_bytes(),
    )
    return files, release_sha


def _git_bytes(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True).stdout


def recovery_committed_pages(artifact_ref: str = "HEAD") -> tuple[dict[str, bytes], str, str]:
    """Read the exact two-revision artifact used only by forward recovery."""
    artifact_sha = _git_bytes("rev-parse", "--verify", f"{artifact_ref}^{{commit}}").decode().strip()
    files: dict[str, bytes] = {}
    for entry in _git_bytes("ls-tree", "-rz", artifact_sha, "--", "api").split(b"\0"):
        if not entry:
            continue
        header, name = entry.split(b"\t", 1)
        mode, kind, object_id = header.split()
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            raise ValueError("Recovery Pages API must contain only regular committed files")
        files[name.decode("utf-8")] = _git_bytes("cat-file", "blob", object_id.decode())
    source_sha = json.loads(files["api/v1/meta.json"]).get("source_commit_sha", "")
    if not RELEASE_SHA.fullmatch(source_sha) or source_sha == artifact_sha:
        raise ValueError("Recovery requires distinct valid source and artifact revisions")
    if subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", source_sha, artifact_sha]).returncode:
        raise ValueError("Recovery source revision is not an ancestor of its artifact revision")
    committed_ids = [
        name for name in _git_bytes("ls-tree", "--name-only", f"{artifact_sha}:data/snapshots").decode("utf-8").splitlines()
        if SNAPSHOT_ID.fullmatch(name)
    ]
    _validate_files(
        files, source_sha,
        lambda date, suffix: _git_bytes("show", f"{artifact_sha}:data/snapshots/{_latest_snapshot(committed_ids, date)}/prices.{suffix}"),
    )
    return files, source_sha, artifact_sha


def copy_public_pages(output_dir: Path, release_sha: str, source_root: Path = ROOT) -> dict[str, Any]:
    files, approved_sha = workspace_pages(source_root, release_sha)
    for published, source in STATIC_PAGES.items():
        if (source_root / source).is_file():
            files[published] = (source_root / source).read_bytes()
    output = ensure_safe_output_dir(output_dir)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    for path, content in files.items():
        target = output / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    if relative_manifest(output) != sorted(files):
        raise ValueError("Pages artifact manifest differs from the allowlisted API")
    if any((output / path).read_bytes() != content for path, content in files.items()):
        raise ValueError("Pages artifact differs from generated API bytes")
    if any((output / forbidden).exists() for forbidden in FORBIDDEN_PUBLIC_PATHS):
        raise ValueError("Forbidden repository internals entered the Pages artifact")
    return {**manifest_summary(output), "release_sha": approved_sha}


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare an allowlisted Pages API artifact.")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(copy_public_pages(args.output_dir, args.release_sha, args.source_root), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
