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
    from lib import ROOT
except ModuleNotFoundError:
    from scripts.lib import ROOT

PUBLIC_PATHS = ("api",)
REQUIRED_PUBLIC_PATHS = (
    "api/v1/prices.json",
    "api/v1/prices.csv",
    "api/v1/meta.json",
    "api/v1/providers",
    "api/v1/models",
)
FORBIDDEN_PUBLIC_PATHS = (
    ".git",
    ".github",
    "data",
    "schema",
    "scripts",
    "tests",
    "pyproject.toml",
)


def relative_manifest(path: Path) -> list[str]:
    return sorted(
        item.relative_to(path).as_posix()
        for item in path.rglob("*")
        if item.is_file()
    )


def manifest_summary(path: Path) -> dict[str, Any]:
    files = [item for item in path.rglob("*") if item.is_file()]
    top_level = sorted({item.relative_to(path).parts[0] for item in files})
    return {
        "output": str(path),
        "fileCount": len(files),
        "totalBytes": sum(item.stat().st_size for item in files),
        "topLevel": top_level,
        "files": relative_manifest(path),
    }


def ensure_safe_output_dir(output_dir: Path) -> Path:
    resolved = output_dir.resolve()
    root = ROOT.resolve()
    if resolved == root:
        raise ValueError("Refusing to use repository root as Pages artifact output")
    if resolved.anchor == str(resolved):
        raise ValueError("Refusing to use filesystem root as Pages artifact output")
    if root in resolved.parents and resolved.relative_to(root).parts[0] in (*PUBLIC_PATHS, *FORBIDDEN_PUBLIC_PATHS):
        raise ValueError("Refusing to overwrite repository inputs with Pages artifact output")
    return resolved


def git_bytes(*args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], check=True, capture_output=True
    ).stdout


def committed_pages(artifact_ref: str = "HEAD") -> tuple[dict[str, bytes], str, str]:
    """Read exact committed API bytes and validate their separate source provenance."""
    artifact_sha = git_bytes("rev-parse", "--verify", f"{artifact_ref}^{{commit}}").decode().strip()
    files = {}
    for entry in git_bytes("ls-tree", "-rz", artifact_sha, "--", "api").split(b"\0"):
        if not entry:
            continue
        header, name = entry.split(b"\t", 1)
        mode, kind, object_id = header.split()
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            raise ValueError("Pages API must contain only regular committed files")
        path = name.decode("utf-8")
        files[path] = git_bytes("cat-file", "blob", object_id.decode())
    for required in REQUIRED_PUBLIC_PATHS:
        if required not in files and not any(path.startswith(required + "/") for path in files):
            raise FileNotFoundError(f"Required committed public path is missing: {required}")
    meta = json.loads(files["api/v1/meta.json"])
    source_sha = meta.get("source_commit_sha")
    if not isinstance(source_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("Committed API source_commit_sha must be a full lowercase Git SHA")
    if source_sha == artifact_sha:
        raise ValueError("Dataset Source SHA must precede the Artifact SHA")
    if git_bytes("rev-parse", "--verify", f"{source_sha}^{{commit}}").decode().strip() != source_sha:
        raise ValueError("Dataset Source SHA must identify a commit")
    ancestry = subprocess.run(
        ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", source_sha, artifact_sha],
        capture_output=True,
    )
    if ancestry.returncode != 0:
        raise ValueError("Dataset Source SHA is not an ancestor of the Artifact SHA")
    generated_at = meta["generated_at"]
    if not isinstance(generated_at, str) or not generated_at.endswith("Z"):
        raise ValueError("Committed API generated_at must be UTC")
    snapshot_date = datetime.fromisoformat(generated_at.replace("Z", "+00:00")).date().isoformat()
    for suffix in ("json", "csv"):
        snapshot = git_bytes("show", f"{artifact_sha}:data/snapshots/{snapshot_date}/prices.{suffix}")
        if files[f"api/v1/prices.{suffix}"] != snapshot:
            raise ValueError(f"Committed API and {snapshot_date} snapshot differ: prices.{suffix}")
    return files, source_sha, artifact_sha


def copy_public_pages(output_dir: Path, artifact_ref: str = "HEAD") -> dict[str, Any]:
    files, source_sha, artifact_sha = committed_pages(artifact_ref)
    output = ensure_safe_output_dir(output_dir)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    for path, content in files.items():
        target = output / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    if relative_manifest(output) != sorted(files) or any(
        (output / path).read_bytes() != content for path, content in files.items()
    ):
        raise ValueError("Pages artifact differs from committed API bytes")

    for forbidden in FORBIDDEN_PUBLIC_PATHS:
        if (output / forbidden).exists():
            raise ValueError(f"Forbidden path staged for Pages artifact: {forbidden}")

    return {**manifest_summary(output), "source_sha": source_sha, "artifact_sha": artifact_sha}


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare the allowlisted GitHub Pages artifact.")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--artifact-sha", default="HEAD", help="Committed Dataset artifact revision")
    parser.add_argument("--github-output", type=Path, help="GitHub Actions step output file")
    args = parser.parse_args()
    summary = copy_public_pages(args.output_dir, args.artifact_sha)
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(f"source_sha={summary['source_sha']}\nartifact_sha={summary['artifact_sha']}\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
