"""Update the mechanical approval fixtures for a prepared release, for review before amending.

Run in the Dataset checkout after prepare (HEAD = artifact commit, HEAD^ = source commit). For every
model the source commit changes it records the approved canonical and projection digests in
tests/fixtures/official-pricing-repair-scope.json, and for every added model it adds the stand-in
Website row to tests/fixtures/website-model-pricing.json. It does not write price-change event
approvals or model-specific assertions; those need a person and are listed at the end.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

try:
    from daily_pricing_release import SOURCE_PATH, classify_changes
except ModuleNotFoundError:
    from scripts.daily_pricing_release import SOURCE_PATH, classify_changes

ROOT = Path(__file__).resolve().parents[1]
SCOPE_PATH = "tests/fixtures/official-pricing-repair-scope.json"
WEBSITE_FIXTURE_PATH = "tests/fixtures/website-model-pricing.json"
PROJECTION_PATH = "data/pricing-v2-preview/generated/model-pricing.v2.json"


def digest(row: Any) -> str:
    """Same digest as tests/test_official_pricing_closure.py."""
    return hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _git_json(root: Path, ref: str, path: str) -> Any:
    shown = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=root, capture_output=True, check=True)
    return json.loads(shown.stdout)


def _read(root: Path, path: str) -> Any:
    return json.loads((root / path).read_text(encoding="utf-8"))


def _write(root: Path, path: str, value: Any) -> None:
    (root / path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def website_fixture_row(model: dict[str, Any]) -> dict[str, Any]:
    pricing = model.get("pricing") or {}
    return {
        "id": model["model_id"],
        "status": model["status"],
        "inputPrice": pricing.get("input"),
        "cachedInputPrice": pricing.get("cached_input"),
        "outputPrice": pricing.get("output"),
        "officialPriceUrl": model.get("official_source_url"),
    }


def update_approvals(root: Path = ROOT) -> dict[str, Any]:
    before = _git_json(root, "HEAD^^", SOURCE_PATH)
    after = _git_json(root, "HEAD^", SOURCE_PATH)
    changes = classify_changes(before, after)
    if not changes:
        raise SystemExit("HEAD^ is not a release source commit with a canonical change; run this after prepare")
    canonical = {f"{row['provider_id']}/{row['model_id']}": row for row in after}
    projection = {row["canonicalInternalId"]: row for row in _read(root, PROJECTION_PATH)["models"] if row.get("canonicalInternalId")}

    scope = _read(root, SCOPE_PATH)
    website_rows = _read(root, WEBSITE_FIXTURE_PATH)
    website_ids = {row["id"] for row in website_rows}
    updated, added_website, manual = [], [], []
    for change in changes:
        identity = f"{change['provider_id']}/{change['model_id']}"
        if identity not in canonical:
            manual.append(f"{identity}: removed from canonical; approve the removal by hand")
            continue
        scope["canonical"][identity] = digest(canonical[identity])
        if identity in projection:
            scope["projection"][identity] = digest(projection[identity])
        else:
            manual.append(f"{identity}: no Pricing V2 projection row; check whether one is expected")
        updated.append(identity)
        if change["change_type"] == "added" and change["model_id"] not in website_ids:
            website_rows.append(website_fixture_row(canonical[identity]))
            added_website.append(change["model_id"])
        if change["change_type"] == "pricing":
            manual.append(f"{identity}: price change; add its price-change event approval to {SCOPE_PATH} and tests/test_official_pricing_closure.py")
    _write(root, SCOPE_PATH, scope)
    _write(root, WEBSITE_FIXTURE_PATH, website_rows)
    manual.append("model-specific assertions (for example provider onboarding tests) and Website test pins; the rehearsal reports any that fail")
    return {"approved": updated, "website_fixture_added": added_website, "manual": manual}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=ROOT)
    args = parser.parse_args()
    result = update_approvals(args.dataset_root.resolve())
    print("APPROVED DIGESTS: " + (", ".join(result["approved"]) or "NONE"))
    print("WEBSITE FIXTURE ROWS ADDED: " + (", ".join(result["website_fixture_added"]) or "NONE"))
    print("STILL MANUAL:")
    for item in result["manual"]:
        print(f"- {item}")
    print("NEXT: review git diff, run the tests, git commit --amend into the artifact commit, then rehearse")


if __name__ == "__main__":
    main()
