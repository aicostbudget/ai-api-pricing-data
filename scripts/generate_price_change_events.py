from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from lib import ROOT
except ModuleNotFoundError:
    from scripts.lib import ROOT

EVENTS_PATH = ROOT / "data" / "price-change-events" / "events.jsonl"
PRICE_EVENT_FIELDS = ("input", "cached_input", "output")
SCHEMA_VERSION = "1.0"
CHANGE_TYPES = {
    "price_update",
    "cached_price_added",
    "cached_price_removed",
    "component_price_update",
}
DATE_BASIS_VALUES = {
    "provider_announced",
    "official_changelog",
    "first_observed",
    "unknown",
}


def fail(message: str) -> None:
    raise ValueError(message)


def repo_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def parsed_date(value: str, field: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{field} must be YYYY-MM-DD: {value}") from exc


def snapshot_date(path: Path) -> str:
    date = path.parent.name
    parsed_date(date, "snapshot directory")
    return date


def parse_date(value: str | None, field: str) -> None:
    if value is None:
        return
    parsed_date(value, field)


def timestamp_to_date(value: str, field: str) -> str:
    if not value.endswith("Z"):
        fail(f"{field} must end with Z: {value}")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO timestamp: {value}") from exc


def decimal_price(value: Any, field: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(f"{field} must be a number or null")
    if isinstance(value, float) and not math.isfinite(value):
        fail(f"{field} must be finite")
    try:
        decimal = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a valid decimal") from exc
    if decimal < 0:
        fail(f"{field} must not be negative")
    return decimal.normalize()


def normalized_price(value: Any, field: str) -> int | float | None:
    decimal = decimal_price(value, field)
    if decimal is None:
        return None
    if decimal == decimal.to_integral():
        return int(decimal)
    return float(decimal)


def normalize_prices(pricing: dict[str, Any], label: str) -> dict[str, int | float | None]:
    return {
        field: normalized_price(pricing.get(field), f"{label}.{field}")
        for field in PRICE_EVENT_FIELDS
    }


def normalized_component_amount(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        fail(f"{field} must be a decimal string")
    try:
        decimal = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a decimal string") from exc
    if not decimal.is_finite() or decimal < 0:
        fail(f"{field} must be a finite non-negative decimal string")
    normalized = format(decimal.normalize(), "f")
    return "0" if normalized in {"-0", ""} else normalized


def component_price_changes(before_model: dict[str, Any], after_model: dict[str, Any], label: str) -> list[dict[str, Any]]:
    def indexed(model: dict[str, Any], side: str) -> dict[tuple[str, str], dict[str, Any]]:
        result = {}
        for component in model.get("pricing_components", []):
            key = (component.get("pricing_id"), component.get("charge_id"))
            if not all(key) or key in result:
                fail(f"{label} {side} pricing_components must have unique pricing_id + charge_id")
            result[key] = component
        return result

    before_components = indexed(before_model, "old")
    after_components = indexed(after_model, "new")
    changes = []
    for key in sorted(set(before_components) & set(after_components)):
        old_component = before_components[key]
        new_component = after_components[key]
        if old_component.get("component") != new_component.get("component"):
            fail(f"{label} component identity changed for {key[1]}")
        if old_component.get("condition") != new_component.get("condition"):
            fail(f"{label} component condition changed for {key[1]}; add explicit event semantics")
        old_amount = normalized_component_amount(old_component.get("amount"), f"{label} old {key[1]}.amount")
        new_amount = normalized_component_amount(new_component.get("amount"), f"{label} new {key[1]}.amount")
        if old_amount == new_amount:
            continue
        changes.append({
            "pricing_id": key[0],
            "charge_id": key[1],
            "component": new_component["component"],
            "old_amount": old_amount,
            "new_amount": new_amount,
            "condition": deepcopy(new_component["condition"]),
        })
    return changes


def load_snapshot(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    models = {}
    for model in data.get("models", []):
        key = (model.get("provider_id"), model.get("model_id"))
        if not all(key):
            fail(f"{repo_relative(path)} contains a model without provider_id/model_id")
        if key in models:
            fail(f"{repo_relative(path)} contains duplicate model {key[0]}/{key[1]}")
        models[key] = model
    return models


def expected_change_type(old_prices: dict[str, Any], new_prices: dict[str, Any], component_changes: list[dict[str, Any]] | None = None) -> str:
    input_changed = old_prices["input"] != new_prices["input"]
    output_changed = old_prices["output"] != new_prices["output"]
    cached_changed = old_prices["cached_input"] != new_prices["cached_input"]
    if input_changed or output_changed:
        return "price_update"
    if cached_changed and old_prices["cached_input"] is None and new_prices["cached_input"] is not None:
        return "cached_price_added"
    if cached_changed and old_prices["cached_input"] is not None and new_prices["cached_input"] is None:
        return "cached_price_removed"
    if component_changes:
        return "component_price_update"
    fail("old_prices and new_prices must differ")


def infer_change_type(old_prices: dict[str, Any], new_prices: dict[str, Any], component_changes: list[dict[str, Any]] | None = None) -> str:
    return expected_change_type(old_prices, new_prices, component_changes)


def canonical_dedupe_payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "provider_id": event["provider_id"],
        "model_id": event["model_id"],
        "change_type": event["change_type"],
        "old_prices": event["old_prices"],
        "new_prices": event["new_prices"],
        "unit": event["unit"],
        "currency": event["currency"],
    }
    if event.get("component_changes"):
        payload["component_changes"] = event["component_changes"]
    return payload


def build_dedupe_key(event: dict[str, Any]) -> str:
    payload = json.dumps(canonical_dedupe_payload(event), sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_event_id(event: dict[str, Any]) -> str:
    short_hash = event["dedupe_key"].split(":", 1)[1][:12]
    return f"{event['provider_id']}:{event['model_id']}:{event['change_type']}:{short_hash}"


def generate_events(before: Path, after: Path) -> list[dict[str, Any]]:
    before_models = load_snapshot(before)
    after_models = load_snapshot(after)
    detected_at = snapshot_date(after)
    before_rel = repo_relative(before)
    after_rel = repo_relative(after)
    events: list[dict[str, Any]] = []

    for key in sorted(set(before_models) & set(after_models)):
        before_model = before_models[key]
        after_model = after_models[key]
        before_pricing = before_model["pricing"]
        after_pricing = after_model["pricing"]
        old_prices = normalize_prices(before_pricing, f"{key[0]}/{key[1]} old")
        new_prices = normalize_prices(after_pricing, f"{key[0]}/{key[1]} new")
        component_changes = component_price_changes(before_model, after_model, f"{key[0]}/{key[1]}")
        unit = after_pricing.get("unit")
        currency = after_pricing.get("currency")
        if old_prices == new_prices and not component_changes:
            continue
        if before_pricing.get("unit") != unit:
            fail(f"{key[0]}/{key[1]} unit changed; add explicit event semantics before generating")
        if before_pricing.get("currency") != currency:
            fail(f"{key[0]}/{key[1]} currency changed; add explicit event semantics before generating")
        event = {
            "schema_version": SCHEMA_VERSION,
            "event_id": "",
            "provider_id": key[0],
            "model_id": key[1],
            "change_type": infer_change_type(old_prices, new_prices, component_changes),
            "old_prices": old_prices,
            "new_prices": new_prices,
            "unit": unit,
            "currency": currency,
            "effective_from": None,
            "detected_at": detected_at,
            "verified_at": timestamp_to_date(after_model["last_verified_at"], f"{key[0]}/{key[1]}.last_verified_at"),
            "date_basis": "first_observed",
            "official_source_url": after_model["official_source_url"],
            "announcement_url": None,
            "source_snapshot_before": before_rel,
            "source_snapshot_after": after_rel,
            "dedupe_key": "",
            "notes": "Effective date was not published by the provider in the source used for this event.",
        }
        if component_changes:
            event["component_changes"] = component_changes
        event["dedupe_key"] = build_dedupe_key(event)
        event["event_id"] = build_event_id(event)
        events.append(event)

    return sorted(events, key=lambda item: (item["provider_id"], item["model_id"], item["dedupe_key"]))


def load_events(path: Path = EVENTS_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            event = json.loads(line)
            validate_event(event, path, line_number)
            events.append(event)
    validate_unique_events(events)
    return events


def merge_event(existing: dict[str, Any], generated: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(generated)
    for field in ("event_id", "effective_from", "date_basis", "announcement_url", "notes", "verified_at", "official_source_url"):
        value = existing.get(field)
        if value not in (None, ""):
            merged[field] = value
    return merged


def merge_events(existing: list[dict[str, Any]], generated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {event["dedupe_key"]: event for event in existing}
    for event in generated:
        current = by_key.get(event["dedupe_key"])
        by_key[event["dedupe_key"]] = merge_event(current, event) if current else event
    merged = sorted(by_key.values(), key=lambda item: (item["provider_id"], item["model_id"], item["dedupe_key"]))
    validate_unique_events(merged)
    return merged


def write_events(events: list[dict[str, Any]], path: Path = EVENTS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(event, sort_keys=True, separators=(",", ":")) for event in events]
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    os.replace(tmp_path, path)


def validate_price_triple(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{field} must be an object")
    extra = set(value) - set(PRICE_EVENT_FIELDS)
    missing = set(PRICE_EVENT_FIELDS) - set(value)
    if extra or missing:
        fail(f"{field} must contain exactly {PRICE_EVENT_FIELDS}")
    return {key: normalized_price(value[key], f"{field}.{key}") for key in PRICE_EVENT_FIELDS}


def validate_component_changes(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or not value:
        fail("component_changes must be a non-empty array when present")
    normalized = []
    seen = set()
    required = {"pricing_id", "charge_id", "component", "old_amount", "new_amount", "condition"}
    for index, change in enumerate(value):
        if not isinstance(change, dict) or set(change) != required:
            fail(f"component_changes[{index}] must contain exactly {sorted(required)}")
        identity = (change["pricing_id"], change["charge_id"])
        if not all(isinstance(item, str) and item for item in identity) or identity in seen:
            fail("component_changes must have unique non-empty pricing_id + charge_id")
        seen.add(identity)
        if not isinstance(change["component"], str) or not change["component"]:
            fail(f"component_changes[{index}].component must be non-empty")
        old_amount = normalized_component_amount(change["old_amount"], f"component_changes[{index}].old_amount")
        new_amount = normalized_component_amount(change["new_amount"], f"component_changes[{index}].new_amount")
        if old_amount == new_amount:
            fail(f"component_changes[{index}] amounts must differ")
        if not isinstance(change["condition"], dict):
            fail(f"component_changes[{index}].condition must be an object")
        normalized.append({**change, "old_amount": old_amount, "new_amount": new_amount})
    return normalized


def valid_https_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def resolve_source_snapshot(raw_path: Any, field: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        fail(f"{field} must be a repository-relative path")
    source_path = Path(raw_path)
    if source_path.is_absolute():
        fail(f"{field} must be a repository-relative path")
    resolved = (ROOT / source_path).resolve()
    try:
        resolved.relative_to(ROOT)
    except ValueError:
        fail(f"{field} must stay within the repository")
    if not resolved.exists():
        fail(f"{field} does not exist: {raw_path}")
    return resolved


def validate_event(event: dict[str, Any], path: Path | None = None, line_number: int | None = None) -> None:
    location = f"{path}:{line_number}: " if path and line_number else ""
    try:
        if event.get("schema_version") != SCHEMA_VERSION:
            fail("schema_version must be 1.0")
        for field in ("event_id", "provider_id", "model_id", "dedupe_key"):
            if not event.get(field):
                fail(f"{field} must be non-empty")
        if event.get("change_type") not in CHANGE_TYPES:
            fail(f"unsupported change_type {event.get('change_type')}")
        old_prices = validate_price_triple(event.get("old_prices"), "old_prices")
        new_prices = validate_price_triple(event.get("new_prices"), "new_prices")
        component_changes = validate_component_changes(event.get("component_changes"))
        if old_prices == new_prices and not component_changes:
            fail("old_prices/new_prices or component_changes must differ")
        expected_type = expected_change_type(old_prices, new_prices, component_changes)
        if event.get("change_type") != expected_type:
            fail(f"change_type must be {expected_type} for this price delta")
        if event.get("currency") != "USD":
            fail("currency must be USD")
        if event.get("unit") != "1M tokens":
            fail("unit must be 1M tokens")
        for field in ("effective_from", "detected_at", "verified_at"):
            parse_date(event.get(field), field)
        if not event.get("detected_at"):
            fail("detected_at is required")
        if not event.get("verified_at"):
            fail("verified_at is required")
        if not valid_https_url(event.get("official_source_url")):
            fail("official_source_url must be an HTTPS URL")
        if event.get("announcement_url") is not None and not valid_https_url(event.get("announcement_url")):
            fail("announcement_url must be null or an HTTPS URL")
        if event.get("date_basis") not in DATE_BASIS_VALUES:
            fail(f"unsupported date_basis {event.get('date_basis')}")
        if event["date_basis"] in {"provider_announced", "official_changelog"} and not event.get("effective_from"):
            fail("announced date_basis requires effective_from")
        if event["date_basis"] == "first_observed" and event.get("effective_from") == event.get("detected_at"):
            fail("first_observed must not auto-copy detected_at into effective_from")
        detected = parsed_date(event["detected_at"], "detected_at")
        verified = parsed_date(event["verified_at"], "verified_at")
        if detected > verified:
            fail("detected_at must not be later than verified_at")
        before_path = resolve_source_snapshot(event.get("source_snapshot_before"), "source_snapshot_before")
        after_path = resolve_source_snapshot(event.get("source_snapshot_after"), "source_snapshot_after")
        if before_path == after_path:
            fail("source snapshots must be different files")
        before_date = snapshot_date(before_path)
        after_date = snapshot_date(after_path)
        if parsed_date(before_date, "source_snapshot_before date") >= parsed_date(after_date, "source_snapshot_after date"):
            fail("source_snapshot_before date must be earlier than source_snapshot_after date")
        expected_key = build_dedupe_key({**event, "old_prices": old_prices, "new_prices": new_prices, "component_changes": component_changes})
        if event["dedupe_key"] != expected_key:
            fail("dedupe_key does not match canonical price-change payload")
        if event["event_id"] != build_event_id({**event, "dedupe_key": expected_key}):
            fail("event_id does not match stable dedupe-derived identity")
    except ValueError as exc:
        raise ValueError(location + str(exc)) from exc


def validate_unique_events(events: list[dict[str, Any]]) -> None:
    seen_event_ids: set[str] = set()
    seen_dedupe_keys: set[str] = set()
    for event in events:
        event_id = event["event_id"]
        dedupe_key = event["dedupe_key"]
        if event_id in seen_event_ids:
            fail(f"duplicate event_id {event_id}")
        if dedupe_key in seen_dedupe_keys:
            fail(f"duplicate dedupe_key {dedupe_key}")
        seen_event_ids.add(event_id)
        seen_dedupe_keys.add(dedupe_key)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate canonical price change events from two snapshots.")
    parser.add_argument("--before", required=True, type=Path, help="Before snapshot prices.json path.")
    parser.add_argument("--after", required=True, type=Path, help="After snapshot prices.json path.")
    parser.add_argument("--output", type=Path, default=EVENTS_PATH, help="Output JSONL path.")
    parser.add_argument("--dry-run", action="store_true", help="Print generated events without writing.")
    args = parser.parse_args()

    generated = generate_events(args.before, args.after)
    if args.dry_run:
        for event in generated:
            print(json.dumps(event, sort_keys=True))
        return

    existing = load_events(args.output)
    merged = merge_events(existing, generated)
    write_events(merged, args.output)
    print(f"wrote {len(merged)} price change events to {repo_relative(args.output)}")


if __name__ == "__main__":
    main()
