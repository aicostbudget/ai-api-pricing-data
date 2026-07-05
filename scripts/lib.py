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
PRICE_FIELDS = ("input", "output", "cached_input", "cache_write", "batch_input", "batch_output")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_providers() -> list[dict[str, Any]]:
    return read_json(CANONICAL / "providers.json")


def load_models() -> list[dict[str, Any]]:
    return read_json(CANONICAL / "models.json")


def build_dataset() -> dict[str, Any]:
    providers = sorted(load_providers(), key=lambda item: item["provider_id"])
    models = sorted(load_models(), key=lambda item: (item["provider_id"], item["model_id"]))
    source_urls = sorted({model["official_source_url"] for model in models})
    last_verified = max(model["last_verified_at"] for model in models) if models else None
    return {
        "dataset_name": "AICostBudget AI API Pricing Dataset",
        "dataset_version": "1.0.0",
        "description": "Open, machine-readable pricing data for LLM and AI APIs.",
        "generated_at": "1970-01-01T00:00:00Z",
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
                "batch_input": pricing["batch_input"],
                "batch_output": pricing["batch_output"],
                "official_source_url": model["official_source_url"],
                "accessed_at": model["accessed_at"],
                "last_verified_at": model["last_verified_at"],
                "effective_from": model["effective_from"],
                "notes": " ".join(model.get("notes", "").split()),
            }
        )
    return rows


def write_csv(path: Path, models: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = csv_rows(models)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def clean_generated() -> None:
    for path in [
        DATA / "prices.json",
        DATA / "prices.csv",
        DATA / "providers",
        DATA / "models",
        DATA / "history",
        DATA / "snapshots",
        API,
    ]:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

