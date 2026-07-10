from __future__ import annotations

import argparse
import json
import shutil
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
    return resolved


def copy_public_pages(output_dir: Path) -> dict[str, Any]:
    output = ensure_safe_output_dir(output_dir)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    for required in REQUIRED_PUBLIC_PATHS:
        source = ROOT / required
        if not source.exists():
            raise FileNotFoundError(f"Required public path is missing: {required}")

    for public_path in PUBLIC_PATHS:
        source = ROOT / public_path
        target = output / public_path
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    for forbidden in FORBIDDEN_PUBLIC_PATHS:
        if (output / forbidden).exists():
            raise ValueError(f"Forbidden path staged for Pages artifact: {forbidden}")

    return manifest_summary(output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare the allowlisted GitHub Pages artifact.")
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(copy_public_pages(args.output_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
