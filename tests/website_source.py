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
