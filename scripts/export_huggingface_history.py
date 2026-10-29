"""Build the Hugging Face price-history dataset from committed snapshots and events.

price_snapshots.csv: one row per (snapshot day, provider, model), taken from the last
snapshot of each day. Each row says whether its scalar prices changed since the
previous snapshot day and, when they did, whether a verified price-change event explains
the change. Unexplained changes are dataset revisions (corrections, re-audits),
not provider price changes.

price_changes.csv: the verified price-change events, flattened.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
from pathlib import Path
from typing import Any

try:
    from lib import ROOT, latest_snapshot_id_for_date, parse_snapshot_id, snapshot_ids
except ModuleNotFoundError:
    from scripts.lib import ROOT, latest_snapshot_id_for_date, parse_snapshot_id, snapshot_ids


SNAPSHOTS_DIR = ROOT / "data" / "snapshots"
EVENTS_PATH = ROOT / "data" / "price-change-events" / "events.jsonl"
HISTORY_HF_DIR = ROOT / "huggingface-history"
SCALAR_PRICES = (
    ("input", "input_price"),
    ("cached_input", "cached_input_price"),
    ("output", "output_price"),
    ("batch_input", "batch_input_price"),
    ("batch_output", "batch_output_price"),
    ("cache_write", "cache_write_price"),
)
# Event types whose old/new prices describe a provider-side change of the scalar prices.
PRICE_EVENT_TYPES = frozenset(
    {"price_update", "cached_price_added", "cached_price_removed", "temporal_price_schedule_update"}
)
SNAPSHOT_HEADERS = (
    "snapshot_date",
    "snapshot_id",
    "provider_id",
    "provider",
    "model_id",
    "model",
    "status",
    *(column for _, column in SCALAR_PRICES),
    "currency",
    "unit",
    "last_verified_at",
    "official_source_url",
    "change_vs_previous_snapshot",
    "price_change_event_id",
)
CHANGE_HEADERS = (
    "event_id",
    "detected_at",
    "effective_from",
    "date_basis",
    "provider_id",
    "provider",
    "model_id",
    "change_type",
    "old_input_price",
    "new_input_price",
    "old_cached_input_price",
    "new_cached_input_price",
    "old_output_price",
    "new_output_price",
    "currency",
    "unit",
    "old_status",
    "new_status",
    "predecessor_model_id",
    "successor_model_id",
    "official_source_url",
    "announcement_url",
    "verified_at",
    "notes",
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_events(path: Path = EVENTS_PATH) -> list[dict[str, Any]]:
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return sorted(events, key=lambda event: (event["detected_at"], event["provider_id"], event["model_id"], event["event_id"]))


def latest_snapshot_per_day(snapshots_dir: Path = SNAPSHOTS_DIR) -> list[str]:
    ids = snapshot_ids(snapshots_dir)
    days = sorted({parse_snapshot_id(snapshot_id)[0] for snapshot_id in ids})
    return [latest_snapshot_id_for_date(ids, day) for day in days]


def provider_names(snapshot: dict[str, Any]) -> dict[str, str]:
    return {provider["provider_id"]: provider["display_name"] for provider in snapshot.get("providers", [])}


def scalar_prices(model: dict[str, Any]) -> dict[str, Any]:
    pricing = model.get("pricing") or {}
    return {column: pricing.get(field) for field, column in SCALAR_PRICES}


def build_snapshot_rows(
    snapshots_dir: Path = SNAPSHOTS_DIR,
    events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    events = read_events() if events is None else events
    price_events = {
        (event["detected_at"], event["provider_id"], event["model_id"]): event["event_id"]
        for event in events
        if event["change_type"] in PRICE_EVENT_TYPES
    }
    rows: list[dict[str, Any]] = []
    previous: dict[tuple[str, str], dict[str, Any]] = {}
    for snapshot_id in latest_snapshot_per_day(snapshots_dir):
        snapshot = read_json(snapshots_dir / snapshot_id / "prices.json")
        day = parse_snapshot_id(snapshot_id)[0]
        names = provider_names(snapshot)
        current: dict[tuple[str, str], dict[str, Any]] = {}
        for model in sorted(snapshot["models"], key=lambda item: (item["provider_id"], item["model_id"])):
            key = (model["provider_id"], model["model_id"])
            prices = scalar_prices(model)
            current[key] = prices
            event_id = ""
            if key not in previous:
                change = "first_seen"
            elif previous[key] == prices:
                change = "unchanged"
            else:
                event_id = price_events.get((day, *key), "")
                change = "price_change" if event_id else "dataset_revision"
            pricing = model.get("pricing") or {}
            rows.append(
                {
                    "snapshot_date": day,
                    "snapshot_id": snapshot_id,
                    "provider_id": model["provider_id"],
                    "provider": names.get(model["provider_id"], model["provider_id"]),
                    "model_id": model["model_id"],
                    "model": model.get("display_name") or model["model_id"],
                    "status": model.get("status"),
                    **prices,
                    "currency": pricing.get("currency"),
                    "unit": pricing.get("unit"),
                    "last_verified_at": (model.get("last_verified_at") or "")[:10] or None,
                    "official_source_url": model.get("official_source_url"),
                    "change_vs_previous_snapshot": change,
                    "price_change_event_id": event_id or None,
                }
            )
        previous = current
    return rows


def build_change_rows(events: list[dict[str, Any]] | None = None, snapshots_dir: Path = SNAPSHOTS_DIR) -> list[dict[str, Any]]:
    events = read_events() if events is None else events
    latest = latest_snapshot_per_day(snapshots_dir)[-1]
    names = provider_names(read_json(snapshots_dir / latest / "prices.json"))
    rows = []
    for event in events:
        old = event.get("old_prices") or {}
        new = event.get("new_prices") or {}
        rows.append(
            {
                "event_id": event["event_id"],
                "detected_at": event["detected_at"],
                "effective_from": event.get("effective_from"),
                "date_basis": event.get("date_basis"),
                "provider_id": event["provider_id"],
                "provider": names.get(event["provider_id"], event["provider_id"]),
                "model_id": event["model_id"],
                "change_type": event["change_type"],
                "old_input_price": old.get("input"),
                "new_input_price": new.get("input"),
                "old_cached_input_price": old.get("cached_input"),
                "new_cached_input_price": new.get("cached_input"),
                "old_output_price": old.get("output"),
                "new_output_price": new.get("output"),
                "currency": event.get("currency"),
                "unit": event.get("unit"),
                "old_status": event.get("old_status"),
                "new_status": event.get("new_status"),
                "predecessor_model_id": event.get("predecessor_model_id"),
                "successor_model_id": event.get("successor_model_id"),
                "official_source_url": event.get("official_source_url"),
                "announcement_url": event.get("announcement_url"),
                "verified_at": event.get("verified_at"),
                "notes": event.get("notes"),
            }
        )
    return rows


def csv_text(rows: list[dict[str, Any]], headers: tuple[str, ...]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field) for field in headers})
    return output.getvalue()


def artifact_contents(snapshots_dir: Path = SNAPSHOTS_DIR, events_path: Path = EVENTS_PATH) -> dict[str, str]:
    events = read_events(events_path)
    return {
        "price_snapshots.csv": csv_text(build_snapshot_rows(snapshots_dir, events), SNAPSHOT_HEADERS),
        "price_changes.csv": csv_text(build_change_rows(events, snapshots_dir), CHANGE_HEADERS),
    }


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp_path.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temp_path, path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="write the CSVs; otherwise check they are current")
    args = parser.parse_args()
    expected = artifact_contents()
    stale = [
        name
        for name, content in expected.items()
        if not (HISTORY_HF_DIR / name).is_file() or (HISTORY_HF_DIR / name).read_text(encoding="utf-8") != content
    ]
    if args.write:
        for name in stale:
            write_atomic(HISTORY_HF_DIR / name, expected[name])
        print(f"wrote {', '.join(stale) or 'nothing (already current)'}")
    elif stale:
        raise SystemExit(f"stale price-history artifacts: {', '.join(stale)}")
    else:
        print("price-history artifacts are current")


if __name__ == "__main__":
    main()
