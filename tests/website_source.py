import os
from pathlib import Path
from typing import Mapping


def resolve_website_source(
    root: Path,
    environ: Mapping[str, str] | None = None,
) -> Path:
    environment = os.environ if environ is None else environ
    candidates: list[Path] = []

    configured_root = environment.get("WEBSITE_SOURCE_ROOT")
    if configured_root:
        candidates.append(Path(configured_root).expanduser())

    candidates.extend(
        (
            root / "website-source",
            root.parent / "ai-cost-control-tool" / "aicostguard-english",
        )
    )

    for candidate in candidates:
        if candidate.is_dir():
            return candidate

    checked = "\n".join(f"- {candidate}" for candidate in candidates)
    raise FileNotFoundError(f"Website source not found. Tried:\n{checked}")


def release_source_candidates(root, environ=None):
    environment = os.environ if environ is None else environ
    configured = environment.get("WEBSITE_SOURCE_ROOT")
    if configured:
        return [Path(configured).expanduser()]
    return [root / "website-source", root.parent / "ai-cost-control-tool" / "aicostguard-english"]


def resolve_release_website_source(root: Path, environ=None) -> Path:
    """Require an actual checkout for local candidate integration, fail closed."""
    import json
    root = root.resolve()
    if not (root / "data/canonical/models.json").is_file() or not (root / "scripts/build_release_bundle.py").is_file():
        raise ValueError("Dataset repository root is invalid")
    candidates = release_source_candidates(root, environ)
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        required = ["package.json", "data/model-pricing.json", "data/pricing-v2-projection/model-pricing.v2.json"]
        if not (candidate / ".git").exists() or not all((candidate / p).is_file() for p in required):
            raise ValueError("Website checkout is not the required repository")
        if json.loads((candidate / "package.json").read_text(encoding="utf-8")).get("name") != "aicostbudget-english":
            raise ValueError("Website checkout package identity is invalid")
        return candidate.resolve()
    raise FileNotFoundError("Required Website checkout missing: " + ", ".join(str(p) for p in candidates))
