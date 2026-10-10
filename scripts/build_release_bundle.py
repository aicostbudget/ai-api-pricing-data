"""Build a projection-qualified, reproducible local release candidate."""

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
import tempfile
from pathlib import Path
from datetime import date
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.export_huggingface import (  # noqa: E402
    PUBLIC_SCHEMA_VERSION,
    SUPPORTED_PUBLIC_SCHEMA_VERSIONS,
    artifact_contents,
    build_export,
    load_website_models,
    load_website_projection,
    preserve_generated_at_for_timestamp_only_change,
    public_conditional_usage_allowances,
    public_pricing_components,
)

CONTRACT_VERSION = "1.0.0"
V1_SOURCES = {
    "github-pages-v1-prices.json": "api/v1/prices.json",
    "github-pages-v1-prices.csv": "api/v1/prices.csv",
    "github-pages-v1-meta.json": "api/v1/meta.json",
}
V2_SOURCE = "data/pricing-v2-preview/generated/model-pricing.v2.json"
V2_SOURCES = {
    "pricing-v2-prices.json": V2_SOURCE,
    "pricing-v2-prices.csv": V2_SOURCE,
    "pricing-v2-meta.json": V2_SOURCE,
}
HF_MIRRORS = {
    "pricing-v2-prices.json": "huggingface/prices.json",
    "pricing-v2-prices.csv": "huggingface/prices.csv",
    "pricing-v2-meta.json": "huggingface/meta.json",
}


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True
    ).stdout


def commit(repo: Path, ref: str) -> str:
    value = git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError(f"invalid commit: {ref}")
    return value


def source(repo: Path, revision: str, path: str) -> bytes:
    if revision == "WORKTREE":
        return (repo / path).read_bytes()
    return git(repo, "show", f"{revision}:{path}")


def parsed(data: bytes) -> Any:
    return json.loads(data.decode("utf-8"))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def projection_stats(prices_json: bytes, prices_csv: bytes, meta_json: bytes, projection: str) -> dict[str, Any]:
    payload, meta = parsed(prices_json), parsed(meta_json)
    if projection == "github_pages_v1":
        records = payload["models"]
        count_key = "model_count"
    elif projection == "pricing_v2":
        records = payload["records"]
        if payload["metadata"] != meta or meta["schema_version"] not in SUPPORTED_PUBLIC_SCHEMA_VERSIONS:
            raise ValueError("Pricing V2 metadata or export schema mismatch")
        count_key = "record_count"
    else:
        raise ValueError("unknown projection")
    if not isinstance(records, list) or not records:
        raise ValueError(f"{projection}: empty or invalid records")
    rows = list(csv.DictReader(io.StringIO(prices_csv.decode("utf-8"), newline="")))
    keys = [(row["provider_id"], row["model_id"]) for row in records]
    csv_keys = [(row["provider_id"], row["model_id"]) for row in rows]
    if len(keys) != len(set(keys)) or len(csv_keys) != len(set(csv_keys)) or set(keys) != set(csv_keys):
        raise ValueError(f"{projection}: JSON/CSV logical records mismatch")
    providers = len({provider for provider, _ in keys})
    if len(records) != len(rows) or meta.get(count_key) != len(records) or meta.get("provider_count") != providers:
        raise ValueError(f"{projection}: record or provider count mismatch")
    if projection == "github_pages_v1" and (payload[count_key] != len(records) or payload["provider_count"] != providers):
        raise ValueError("GitHub Pages V1 payload count mismatch")
    return {"records": len(records), "providers": providers, "generated_at": meta["generated_at"], "last_verified_at": meta["last_verified_at"]}


def asset(filename: str, source_path: str, content: bytes) -> dict[str, Any]:
    return {
        "filename": filename,
        "source_path": source_path,
        "sha256": digest(content),
        "bytes": len(content),
        "media_type": "text/csv" if filename.endswith(".csv") else "application/json",
    }


def build_contents(dataset_ref: str, website_repo: Path, website_ref: str, snapshot: str, release_version: str | None = None, release_date: str | None = None) -> dict[str, bytes]:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", snapshot):
        raise ValueError("snapshot must be YYYY-MM-DD")
    if (release_version is None) != (release_date is None):
        raise ValueError("release version and date must be provided together")
    if release_date is not None:
        date.fromisoformat(release_date)
        if not release_version or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", release_version):
            raise ValueError("invalid release version")
    local_candidate = dataset_ref == "WORKTREE" or website_ref == "WORKTREE"
    if local_candidate and (dataset_ref != "WORKTREE" or website_ref != "WORKTREE" or release_version is not None):
        raise ValueError("local candidate requires two WORKTREE inputs and cannot claim a published release")
    dataset_sha = "WORKTREE" if local_candidate else commit(ROOT, dataset_ref)
    website_repo = website_repo.resolve(strict=True)
    website_sha = "WORKTREE" if local_candidate else commit(website_repo, website_ref)
    v1 = {name: source(ROOT, dataset_sha, path) for name, path in V1_SOURCES.items()}
    for suffix in ("json", "csv"):
        if v1[f"github-pages-v1-prices.{suffix}"] != source(ROOT, dataset_sha, f"data/snapshots/{snapshot}/prices.{suffix}"):
            raise ValueError(f"V1 API and {snapshot} snapshot differ: prices.{suffix}")
    v1_stats = projection_stats(v1["github-pages-v1-prices.json"], v1["github-pages-v1-prices.csv"], v1["github-pages-v1-meta.json"], "github_pages_v1")

    canonical = parsed(source(ROOT, dataset_sha, V2_SOURCE))
    website = load_website_projection(website_repo, website_sha)
    for extractor in (public_pricing_components, public_conditional_usage_allowances):
        canonical_values = {(row["provider"], row["id"]): extractor(row) for row in canonical["models"]}
        website_values = {(row["provider"], row["id"]): extractor(row) for row in website["models"]}
        if canonical_values != website_values:
            raise ValueError("Website and Dataset Pricing V2 projections differ")
    metadata = parsed(v1["github-pages-v1-meta.json"])
    pinned_mirror = parsed(source(ROOT, dataset_sha, HF_MIRRORS["pricing-v2-prices.json"]))
    export_schema = PUBLIC_SCHEMA_VERSION if local_candidate else pinned_mirror["metadata"]["schema_version"]
    payload = build_export(website, metadata, load_website_models(website_repo, website_sha), schema_version=export_schema)
    preserve_generated_at_for_timestamp_only_change(
        payload, parsed(source(ROOT, dataset_sha, HF_MIRRORS["pricing-v2-prices.json"]))
    )
    generated = artifact_contents(payload)
    v2 = {name: generated[name.removeprefix("pricing-v2-")].encode("utf-8") for name in V2_SOURCES}
    for name, mirror in HF_MIRRORS.items():
        if v2[name] != source(ROOT, dataset_sha, mirror):
            raise ValueError(f"Website export and HF mirror differ: {name}")
    v2_stats = projection_stats(v2["pricing-v2-prices.json"], v2["pricing-v2-prices.csv"], v2["pricing-v2-meta.json"], "pricing_v2")

    manifest = {
        "release_contract_version": CONTRACT_VERSION,
        "status": "release" if release_version is not None else "candidate",
        "release_version": release_version,
        "release_date": release_date,
        "git_commit": None if local_candidate else dataset_sha,
        "snapshot_date": snapshot,
        "snapshot_path": f"data/snapshots/{snapshot}/",
        "dataset_schema": {"source_path": "schema/dataset.schema.json", "sha256": digest(source(ROOT, dataset_sha, "schema/dataset.schema.json"))},
        "website_source": {"git_commit": None if local_candidate else website_sha, "projection_path": "data/pricing-v2-projection/model-pricing.v2.json", "legacy_models_path": "data/model-pricing.json"},
        "projections": {
            "github_pages_v1": {"role": "GitHub Pages V1 API and tracked snapshot", "schema": "schema/dataset.schema.json", **v1_stats, "assets": [asset(name, path, v1[name]) for name, path in V1_SOURCES.items()]},
            "pricing_v2": {"role": "Website public Pricing V2 export; HF is parity target", "export_schema": export_schema, **v2_stats, "assets": [asset(name, path, v2[name]) for name, path in V2_SOURCES.items()]},
        },
    }
    if local_candidate:
        manifest["source_scope"] = "LOCAL_CANDIDATE"
        manifest["base_commits"] = {"dataset": commit(ROOT, "HEAD"), "website": commit(website_repo, "HEAD")}
    files = {**v1, **v2}
    files["release-manifest.json"] = (json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    files["SHA256SUMS.txt"] = "".join(f"{digest(files[name])}  {name}\n" for name in sorted(files)).encode("ascii")
    return files


def verify_contents(files: dict[str, bytes]) -> dict[str, Any]:
    manifest = parsed(files["release-manifest.json"])
    if manifest.get("source_scope") == "LOCAL_CANDIDATE":
        if manifest["status"] != "candidate" or manifest.get("git_commit") is not None or manifest["website_source"].get("git_commit") is not None:
            raise ValueError("local candidate cannot assert published source commits")
        if set(manifest["base_commits"]) != {"dataset", "website"} or not all(re.fullmatch(r"[0-9a-f]{40}", value) for value in manifest["base_commits"].values()):
            raise ValueError("local candidate base commit is invalid")
    if manifest["status"] == "candidate":
        if manifest["release_version"] is not None or manifest["release_date"] is not None:
            raise ValueError("candidate manifest state mismatch")
    elif manifest["status"] == "release":
        if not manifest["release_version"] or not manifest["release_date"]:
            raise ValueError("release manifest state mismatch")
        date.fromisoformat(manifest["release_date"])
    else:
        raise ValueError("unknown release manifest status")
    if set(files) != {*V1_SOURCES, *V2_SOURCES, "release-manifest.json", "SHA256SUMS.txt"}:
        raise ValueError("release asset set mismatch")
    for projection, sources in (("github_pages_v1", V1_SOURCES), ("pricing_v2", V2_SOURCES)):
        section = manifest["projections"][projection]
        actual = section["assets"]
        expected = [asset(name, path, files[name]) for name, path in sources.items()]
        if actual != expected:
            raise ValueError(f"{projection}: hash, length, source_path or media_type mismatch")
        prefix = "github-pages-v1" if projection == "github_pages_v1" else "pricing-v2"
        stats = projection_stats(files[f"{prefix}-prices.json"], files[f"{prefix}-prices.csv"], files[f"{prefix}-meta.json"], projection)
        if any(section[key] != value for key, value in stats.items()):
            raise ValueError(f"{projection}: manifest statistics mismatch")
    expected_sums = "".join(f"{digest(files[name])}  {name}\n" for name in sorted(files) if name != "SHA256SUMS.txt").encode("ascii")
    if files["SHA256SUMS.txt"] != expected_sums:
        raise ValueError("SHA256SUMS mismatch")
    return manifest


def write_bundle(files: dict[str, bytes], output: Path) -> None:
    output = output.resolve()
    if output == ROOT or ROOT in output.parents and (len(output.relative_to(ROOT).parts) < 2 or output.relative_to(ROOT).parts[0] != "dist"):
        raise ValueError("output inside repository must be under dist/")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".release-bundle-", dir=output.parent) as staging:
        staged = Path(staging)
        for name, content in files.items():
            (staged / name).write_bytes(content)
        verify_contents({path.name: path.read_bytes() for path in staged.iterdir()})
        os.replace(staged, output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--dataset-ref", required=True, help="Exact Dataset tag/commit, or WORKTREE for an explicitly local candidate")
    parser.add_argument("--website-repo", required=True, type=Path, help="Existing offline Website checkout")
    parser.add_argument("--website-ref", required=True, help="Exact Website commit, or WORKTREE for an explicitly local candidate")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "release-candidate")
    parser.add_argument("--release-version", help="Explicit version for a tag-derived final bundle")
    parser.add_argument("--release-date", help="Explicit YYYY-MM-DD date for a tag-derived final bundle")
    args = parser.parse_args()
    files = build_contents(args.dataset_ref, args.website_repo, args.website_ref, args.snapshot, args.release_version, args.release_date)
    verify_contents(files)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    write_bundle(files, output)
    print(f"built {output.resolve()}: {len(files)} files")


if __name__ == "__main__":
    main()
