from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "data" / "canonical"
DATA = ROOT / "data"
API = ROOT / "api" / "v1"
PRICE_FIELDS = ("input", "output", "cached_input", "cache_write", "cache_write_1h", "batch_input", "batch_output")
HISTORY_COMPARE_FIELDS = (
    "provider_id",
    "model_id",
    "pricing",
    "pricing_periods",
    "time_pricing",
    "pricing_components",
    "official_source_url",
    "effective_from",
    "last_verified_at",
    "notes",
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_providers() -> list[dict[str, Any]]:
    return read_json(CANONICAL / "providers.json")


def load_models() -> list[dict[str, Any]]:
    return read_json(CANONICAL / "models.json")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def select_time_pricing_period(
    time_pricing: dict[str, Any], request_time: datetime
) -> dict[str, Any]:
    if request_time.tzinfo is None:
        raise ValueError("request_time must be timezone-aware")
    if time_pricing["timezone"] != "UTC":
        raise ValueError(f"unsupported time pricing timezone: {time_pricing['timezone']}")

    request_utc = request_time.astimezone(timezone.utc)
    weekday = request_utc.strftime("%A").lower()
    hhmm = request_utc.strftime("%H:%M")
    periods = time_pricing["periods"]
    for period in periods:
        if period["all_other_times"] or weekday not in period["active_weekdays"]:
            continue
        if any(window["start"] <= hhmm < window["end"] for window in period["time_windows"]):
            return period

    default_period_id = time_pricing["default_period_id"]
    return next(period for period in periods if period["id"] == default_period_id)


def build_dataset(generated_at: str | None = None) -> dict[str, Any]:
    providers = sorted(load_providers(), key=lambda item: item["provider_id"])
    models = sorted(load_models(), key=lambda item: (item["provider_id"], item["model_id"]))
    source_urls = sorted({model["official_source_url"] for model in models})
    last_verified = max(model["last_verified_at"] for model in models) if models else None
    generated_at = generated_at or utc_now()
    return {
        "dataset_name": "AICostBudget AI API Pricing Dataset",
        "dataset_version": "1.0.0",
        "description": "Open, machine-readable pricing data for LLM and AI APIs.",
        "generated_at": generated_at,
        "homepage": "https://aicostbudget.com",
        "licenses": {
            "code": "MIT",
            "data": "CC BY 4.0",
        },
        "provider_count": len(providers),
        "model_count": len(models),
        "official_source_count": len(source_urls),
        "last_verified_at": last_verified,
        "providers": providers,
        "models": models,
        "official_sources": source_urls,
    }


def csv_rows(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model in sorted(models, key=lambda item: (item["provider_id"], item["model_id"])):
        pricing = model["pricing"]
        components = model.get("pricing_components", [])
        primary_component = components[0] if len(components) == 1 else None
        rows.append(
            {
                "provider_id": model["provider_id"],
                "model_id": model["model_id"],
                "display_name": model["display_name"],
                "model_family": model["model_family"],
                "status": model["status"],
                "currency": pricing["currency"],
                "unit": pricing["unit"],
                "input": pricing["input"],
                "output": pricing["output"],
                "cached_input": pricing["cached_input"],
                "cache_write": pricing["cache_write"],
                "cache_write_1h": pricing.get("cache_write_1h"),
                "batch_input": pricing["batch_input"],
                "batch_output": pricing["batch_output"],
                "official_source_url": model["official_source_url"],
                "accessed_at": model["accessed_at"],
                "last_verified_at": model["last_verified_at"],
                "effective_from": model["effective_from"],
                "notes": " ".join(model.get("notes", "").split()),
                "unit_price": primary_component["amount"] if primary_component else None,
                "billing_unit": primary_component["unit"] if primary_component else None,
                "billing_quantity": 1000 if primary_component and primary_component["unit"] == "per_1000_pages" else None,
                "pricing_dimension": primary_component["component"] if primary_component else None,
                "pricing_components_json": json.dumps(components, separators=(",", ":")) if components else None,
            }
        )
    return rows


def write_csv(path: Path, models: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = csv_rows(models)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def clean_generated() -> None:
    for path in [
        DATA / "prices.json",
        DATA / "prices.csv",
        DATA / "providers",
        DATA / "models",
        API,
    ]:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def history_entry(model: dict[str, Any], recorded_at: str) -> dict[str, Any]:
    entry = {
        "recorded_at": recorded_at,
        "provider_id": model["provider_id"],
        "model_id": model["model_id"],
        "pricing": model["pricing"],
        "official_source_url": model["official_source_url"],
        "effective_from": model.get("effective_from"),
        "last_verified_at": model["last_verified_at"],
        "notes": model.get("notes", ""),
    }
    if "pricing_periods" in model:
        entry["pricing_periods"] = model["pricing_periods"]
    if "time_pricing" in model:
        entry["time_pricing"] = model["time_pricing"]
    if "pricing_components" in model:
        entry["pricing_components"] = model["pricing_components"]
    return entry


def comparable_history(entry: dict[str, Any]) -> dict[str, Any]:
    return {field: entry.get(field) for field in HISTORY_COMPARE_FIELDS}


def latest_history_entry(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    latest = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            latest = json.loads(line)
    return latest


def append_history_if_changed(path: Path, entry: dict[str, Any]) -> bool:
    previous = latest_history_entry(path)
    if previous is not None and comparable_history(previous) == comparable_history(entry):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
    return True
