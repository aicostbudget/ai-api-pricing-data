"""One-off backfill: model_added events for models that releases added without running the event generator.

Until 2026-10-29 the release pipeline ran generate_price_change_events.py only for price changes, so models
added by a release got no model_added event. For each consecutive pair of tracked snapshots this runs the
generator, limited to the models the later snapshot added, unless an event already exists for that model.

    python scripts/backfill_model_added_events.py [--since 2026-10-14] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.daily_pricing_release import snapshot_ids, snapshot_sort_key  # noqa: E402

SNAPSHOTS = ROOT / "data" / "snapshots"
EVENTS = ROOT / "data" / "price-change-events" / "events.jsonl"


def model_keys(prices_path: Path) -> set[tuple[str, str]]:
    data = json.loads(prices_path.read_text(encoding="utf-8"))
    rows = data["models"] if isinstance(data, dict) else data
    return {(row["provider_id"], row["model_id"]) for row in rows}


def existing_event_keys() -> set[tuple[str, str]]:
    keys = set()
    for line in EVENTS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            event = json.loads(line)
            keys.add((event["provider_id"], event["model_id"]))
    return keys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", default="2026-10-14", help="first snapshot date to backfill")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    ids = [s for s in snapshot_ids(SNAPSHOTS) if (SNAPSHOTS / s / "prices.json").is_file()]
    ids.sort(key=snapshot_sort_key)
    covered = existing_event_keys()
    for before, after in zip(ids, ids[1:]):
        if after[:10] < args.since:
            continue
        added = sorted(model_keys(SNAPSHOTS / after / "prices.json") - model_keys(SNAPSHOTS / before / "prices.json") - covered)
        if not added:
            continue
        print(f"{before} -> {after}: {', '.join(f'{p}/{m}' for p, m in added)}")
        for provider in sorted({p for p, _ in added}):
            command = [sys.executable, "scripts/generate_price_change_events.py",
                       "--before", str(SNAPSHOTS / before / "prices.json"), "--after", str(SNAPSHOTS / after / "prices.json"),
                       "--provider", provider]
            for p, m in added:
                if p == provider:
                    command += ["--model", m]
            if args.dry_run:
                command.append("--dry-run")
            subprocess.run(command, cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
