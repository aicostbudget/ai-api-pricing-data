"""Write the GitHub Release notes for one month of the dataset.

Reads the month's entries from data/price-change-events/events.jsonl and the current
api/v1 metadata, and prints Markdown (or writes it with --output). `--check` exits 3 when
the month has no events, so the monthly workflow can skip an empty release.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.update_readme_prices import PROVIDERS, usd as readme_usd  # noqa: E402

PROVIDER_NAMES = {**dict(PROVIDERS), "aws": "AWS", "azure": "Azure", "google-cloud": "Google Cloud"}
EVENTS = "data/price-change-events/events.jsonl"
PRICES = "api/v1/prices.json"
SITE = "https://aicostbudget.com/en"
UTM = "utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=release_{month}"
PRICE_TYPES = {
    "price_update", "component_price_update", "cached_price_added", "cached_price_removed",
    "temporal_price_schedule_update",
}
LIFECYCLE_TYPES = {"lifecycle_update", "successor_transition"}
SCALARS = (("input", "input"), ("cached_input", "cached input"), ("output", "output"))
NO_EVENTS = 3


def usd(value) -> str:
    return "none" if value is None else readme_usd(value)


def month_label(month: str) -> str:
    return date.fromisoformat(f"{month}-01").strftime("%B %Y")


def load_events(root: Path, month: str) -> list[dict]:
    lines = (root / EVENTS).read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines if line.strip()]
    selected = [event for event in events if event["detected_at"][:7] == month]
    return sorted(selected, key=lambda event: (event["detected_at"], event["provider_id"], event["model_id"], event["change_type"]))


def names(dataset: dict) -> dict[tuple[str, str], str]:
    return {(model["provider_id"], model["model_id"]): model["display_name"] for model in dataset["models"]}


def provider_link(provider_id: str, month: str) -> str:
    name = PROVIDER_NAMES.get(provider_id, provider_id)
    return f"[{name}]({SITE}/providers/{provider_id}-api-pricing?{UTM.format(month=month)})"


def model_name(event: dict, display: dict) -> str:
    return display.get((event["provider_id"], event["model_id"]), event["model_id"])


def source(event: dict) -> str:
    url = event.get("official_source_url")
    return f"[official]({url})" if url else "–"


def scalar_changes(event: dict) -> list[str]:
    old, new = event.get("old_prices") or {}, event.get("new_prices") or {}
    return [f"{label} {usd(old.get(key))} → {usd(new.get(key))}" for key, label in SCALARS if old.get(key) != new.get(key)]


def describe_price(event: dict) -> str:
    kind = event["change_type"]
    if kind == "temporal_price_schedule_update":
        periods = (event.get("new_time_pricing") or {}).get("periods") or []
        return "time-of-day pricing: " + "; ".join(
            f"{period['id']} input {usd(period['pricing'].get('input'))} / output {usd(period['pricing'].get('output'))}"
            for period in periods
        )
    changes = scalar_changes(event)
    for change in event.get("component_changes") or []:
        label = change["component"].replace("_", " ")
        if not any(text.startswith(label) for text in changes):
            changes.append(f"{label} {usd(change.get('old_amount'))} → {usd(change.get('new_amount'))}")
    return "; ".join(changes) or kind.replace("_", " ")


def describe_lifecycle(event: dict, display: dict) -> str:
    if event["change_type"] == "successor_transition":
        predecessor = event.get("predecessor_model_id")
        return f"replaces {display.get((event['provider_id'], predecessor), predecessor)}" if predecessor else "successor model"
    lifecycle = event.get("new_lifecycle") or {}
    old, new = event.get("old_status"), event.get("new_status")
    parts = [f"{old} → {new}" if old and old != new else str(new)]
    for key, label in (("deprecation_date", "deprecated"), ("retirement_date", "retires")):
        if lifecycle.get(key):
            parts.append(f"{label} {lifecycle[key]}")
    replacement = lifecycle.get("replacement_model_id")
    if replacement:
        parts.append(f"replacement {display.get((event['provider_id'], replacement), replacement)}")
    return ", ".join(parts)


def table(header: str, rows: list[str]) -> list[str]:
    columns = header.count("|") - 1
    return [header, "|" + " --- |" * columns, *rows, ""]


def render(month: str, events: list[dict], dataset: dict, snapshot: str) -> str:
    display = names(dataset)
    label = month_label(month)
    providers = Counter(event["provider_id"] for event in events)
    price = [event for event in events if event["change_type"] in PRICE_TYPES]
    added = [event for event in events if event["change_type"] == "model_added"]
    lifecycle = [event for event in events if event["change_type"] in LIFECYCLE_TYPES]
    lines = [
        f"## AI API prices in {label}",
        "",
        f"{len(events)} changes across {len(providers)} providers, taken from the dataset's price-change log. "
        "Prices are USD list prices per 1M tokens unless the model's record says otherwise; every row links the provider's own page.",
        "",
    ]
    if price:
        lines += ["### Price changes", ""] + table(
            "| Date | Provider | Model | Change | Source |",
            [f"| {e['detected_at']} | {provider_link(e['provider_id'], month)} | {model_name(e, display)} | {describe_price(e)} | {source(e)} |" for e in price],
        )
    if added:
        lines += ["### New models", ""] + table(
            "| Date | Provider | Model | Input / output | Source |",
            [
                f"| {e['detected_at']} | {provider_link(e['provider_id'], month)} | {model_name(e, display)} | "
                f"{usd((e.get('new_prices') or {}).get('input'))} / {usd((e.get('new_prices') or {}).get('output'))} | {source(e)} |"
                for e in added
            ],
        )
    if lifecycle:
        lines += ["### Deprecations and replacements", ""] + table(
            "| Date | Provider | Model | What changed | Source |",
            [f"| {e['detected_at']} | {provider_link(e['provider_id'], month)} | {model_name(e, display)} | {describe_lifecycle(e, display)} | {source(e)} |" for e in lifecycle],
        )
    utm = UTM.format(month=month)
    lines += [
        f"Compare current prices: [model price comparison]({SITE}/model-pricing-comparison?{utm}) · "
        f"[price change monitor]({SITE}/model-price-monitor?{utm}) · [cost calculator]({SITE}/ai-api-cost-calculator?{utm})",
        "",
        "## This release",
        "",
        f"- Snapshot `{snapshot}`: {dataset['model_count']} models from {dataset['provider_count']} providers, last verified {dataset['last_verified_at'][:10]}.",
        "- Assets: GitHub Pages V1 and Pricing V2 (Hugging Face) JSON, CSV and metadata, plus `release-manifest.json` and `SHA256SUMS.txt`. "
        "The manifest records the exact Dataset and Website commits.",
        "- Zenodo archives this release under its own DOI version. For live data use the [static API](https://aicostbudget.github.io/ai-api-pricing-data/api/v1/prices.json).",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true", help=f"exit {NO_EVENTS} when the month has no events")
    args = parser.parse_args()
    month_label(args.month)
    events = load_events(args.root, args.month)
    if not events:
        print(f"No price-change events in {args.month}", file=sys.stderr)
        sys.exit(NO_EVENTS if args.check else 0)
    if args.check:
        return
    dataset = json.loads((args.root / PRICES).read_text(encoding="utf-8"))
    notes = render(args.month, events, dataset, args.snapshot)
    if args.output:
        args.output.write_text(notes, encoding="utf-8", newline="\n")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(notes)


if __name__ == "__main__":
    main()
