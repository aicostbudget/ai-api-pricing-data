"""One-off backfill: scheduled_price_change events for future price records already in the snapshot history.

Until 2026-11-05 the generator had no event type for an announced future price, so schedules such as
Gemini 4 Argon's 2026-12-01 increase never reached the price monitor. For each consecutive pair of
tracked snapshots this emits the scheduled_price_change events that pair would have produced and adds
those whose dedupe_key is not yet in the event file. Existing events are never regenerated or removed
(merge_events would purge other events in the same model/snapshot scope).

    python scripts/backfill_scheduled_price_change_events.py [--since 2026-09-01] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.daily_pricing_release import snapshot_ids, snapshot_sort_key  # noqa: E402
from scripts.generate_price_change_events import (  # noqa: E402
    EVENTS_PATH,
    ensure_source_snapshots_tracked,
    load_events,
    load_snapshot,
    repo_relative,
    scheduled_events_for_pair,
    snapshot_date,
    validate_event,
    validate_unique_events,
    write_events,
)

SNAPSHOTS = ROOT / "data" / "snapshots"


def backfill(since: str) -> list[dict]:
    ids = [s for s in snapshot_ids(SNAPSHOTS) if (SNAPSHOTS / s / "prices.json").is_file()]
    ids.sort(key=snapshot_sort_key)
    found: dict[str, dict] = {}
    for before_id, after_id in zip(ids, ids[1:]):
        if after_id[:10] < since:
            continue
        before, after = SNAPSHOTS / before_id / "prices.json", SNAPSHOTS / after_id / "prices.json"
        before_models = {k: v for k, v in load_snapshot(before).items() if not v.get("hosted_model")}
        after_models = {k: v for k, v in load_snapshot(after).items() if not v.get("hosted_model")}
        for key in sorted(after_models):
            for event in scheduled_events_for_pair(
                before_models.get(key), after_models[key], repo_relative(before), repo_relative(after), snapshot_date(after)
            ):
                ensure_source_snapshots_tracked(before, after)
                found.setdefault(event["dedupe_key"], event)
    return list(found.values())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", default="2026-09-01", help="first snapshot date to scan")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    existing = load_events(EVENTS_PATH)
    known = {event["dedupe_key"] for event in existing}
    added = [event for event in backfill(args.since) if event["dedupe_key"] not in known]
    for event in added:
        validate_event(event)
        print(f"{event['detected_at']} {event['provider_id']}/{event['model_id']} -> {event['effective_from']} {json.dumps(event['new_prices'])}")
    if args.dry_run or not added:
        print(f"{len(added)} scheduled_price_change events to add")
        return
    merged = sorted(existing + added, key=lambda item: (item["provider_id"], item["model_id"], item["dedupe_key"]))
    validate_unique_events(merged)
    write_events(merged, EVENTS_PATH)
    print(f"added {len(added)} scheduled_price_change events; {len(merged)} total")


if __name__ == "__main__":
    main()
