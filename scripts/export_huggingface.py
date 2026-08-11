from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from lib import ROOT
except ModuleNotFoundError:
    from scripts.lib import ROOT


PROJECTION_PATH = ROOT / "data" / "pricing-v2-preview" / "generated" / "model-pricing.v2.json"
META_PATH = ROOT / "api" / "v1" / "meta.json"
HF_DIR = ROOT / "huggingface"
DATASET_PAGE_URL = "https://aicostbudget.com/en/datasets/ai-api-pricing"
CSV_HEADERS = (
    "provider_id",
    "provider",
    "model_id",
    "model",
    "input_price_per_1m_tokens",
    "cached_input_price_per_1m_tokens",
    "output_price_per_1m_tokens",
    "currency",
    "pricing_unit",
    "status",
    "availability",
    "official_source_url",
    "last_verified_at",
    "effective_from",
    "effective_until",
    "notes",
)
NUMERIC_FIELDS = (
    "input_price_per_1m_tokens",
    "cached_input_price_per_1m_tokens",
    "output_price_per_1m_tokens",
)
PROVIDER_DISPLAY = {
    "anthropic": "Anthropic",
    "cohere": "Cohere",
    "deepseek": "DeepSeek",
    "google-gemini": "Google",
    "mistral-ai": "Mistral AI",
    "openai": "OpenAI",
    "xai": "xAI",
}
REQUIRED_UTM = (
    "utm_source=huggingface",
    "utm_medium=dataset",
    "utm_campaign=ai_api_pricing_dataset",
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def date_only(value: str | None) -> str | None:
    if not value:
        return None
    return value[:10] if "T" in value else value


def projection_warning(row: dict[str, Any]) -> str | None:
    if row["id"] == "grok-3":
        return (
            "V2 marks this as a retired historical identity that redirects to Grok 4.3 current billing; "
            "it is not an ordinary active recommendation model."
        )
    if row["defaultSafe"] is False:
        reasons = ", ".join(row.get("blockedFromDefaultReasons", [])) or row["verificationStatus"]
        return f"V2 marks this row as unsafe for default calculations: {reasons}."
    if row["identityType"] != "canonical_model":
        return f"V2 routing behavior: {row['routingBehavior']}."
    return None


def fallback_warning(row: dict[str, Any]) -> str:
    return (
        f"V2 has no default-safe current price for this row ({row['verificationStatus']}); "
        "displayed price is a legacy fallback and must not be treated as V2 verified pricing."
    )


def load_website_models(website_repo: Path, website_ref: str) -> list[dict[str, Any]]:
    result = subprocess.run(
        ["git", "-C", str(website_repo), "show", f"{website_ref}:data/model-pricing.json"],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    rows = json.loads(result.stdout)
    if not isinstance(rows, list):
        raise ValueError("Website data/model-pricing.json must be a JSON array")
    return rows


def expected_public_keys(projection: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (row["provider"], row["id"])
        for row in projection["models"]
        if row["publicExposure"] == "public"
    }


def build_public_records(
    projection: dict[str, Any],
    legacy_models: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    legacy_by_id = {row["id"]: row for row in legacy_models}
    records: list[dict[str, Any]] = []

    for row in projection["models"]:
        if row["publicExposure"] != "public":
            continue
        if "excluded_default_candidate" in row.get("blockedFromDefaultReasons", []):
            continue

        legacy = legacy_by_id.get(row["id"])
        has_current_price = is_number(row.get("inputPrice")) and is_number(row.get("outputPrice"))
        if has_current_price:
            warning = projection_warning(row)
            records.append(
                {
                    "provider_id": row["provider"],
                    "provider": PROVIDER_DISPLAY.get(row["provider"], row["provider"]),
                    "model_id": row["id"],
                    "model": row["model"],
                    "input_price_per_1m_tokens": row["inputPrice"],
                    "cached_input_price_per_1m_tokens": (
                        row.get("cachedInputPrice") if is_number(row.get("cachedInputPrice")) else None
                    ),
                    "output_price_per_1m_tokens": row["outputPrice"],
                    "currency": "USD",
                    "pricing_unit": "1M tokens",
                    "status": row["status"],
                    "availability": row["availability"],
                    "official_source_url": row["officialSourceUrl"],
                    "last_verified_at": date_only(
                        row.get("verifiedAt") or row.get("checkedAt") or projection["generatedAt"]
                    ),
                    "effective_from": row.get("selectedPriceEffectiveFrom"),
                    "effective_until": row.get("selectedPriceEffectiveUntil"),
                    "notes": warning if warning is not None else (legacy.get("priceNote", "") if legacy else ""),
                }
            )
            continue

        if legacy is None:
            continue
        records.append(
            {
                "provider_id": row["provider"],
                "provider": legacy["provider"],
                "model_id": legacy["id"],
                "model": legacy["model"],
                "input_price_per_1m_tokens": legacy.get("inputPrice"),
                "cached_input_price_per_1m_tokens": legacy.get("cachedInputPrice"),
                "output_price_per_1m_tokens": legacy.get("outputPrice"),
                "currency": "USD",
                "pricing_unit": "1M tokens",
                "status": legacy["status"],
                "availability": legacy["availability"],
                "official_source_url": legacy["officialPriceUrl"],
                "last_verified_at": legacy["lastUpdated"],
                "effective_from": row.get("selectedPriceEffectiveFrom"),
                "effective_until": row.get("selectedPriceEffectiveUntil"),
                "notes": fallback_warning(row),
            }
        )

    actual_keys = {(row["provider_id"], row["model_id"]) for row in records}
    expected_keys = expected_public_keys(projection)
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        extra = sorted(actual_keys - expected_keys)
        raise ValueError(f"public projection key mismatch; missing={missing}, extra={extra}")
    return records


def build_export(
    projection: dict[str, Any],
    metadata: dict[str, Any],
    legacy_models: list[dict[str, Any]],
) -> dict[str, Any]:
    records = build_public_records(projection, legacy_models)
    provider_count = len({row["provider_id"] for row in records})
    source_count = len({row["official_source_url"] for row in records if row["official_source_url"]})
    payload = {
        "metadata": {
            "name": metadata["dataset_name"],
            "version": metadata["dataset_version"],
            "page_url": DATASET_PAGE_URL,
            "last_updated": metadata["last_verified_at"],
            "generated_at": metadata["generated_at"],
            "provider_count": provider_count,
            "record_count": len(records),
            "official_source_count": source_count,
            "currency": "USD",
            "pricing_unit": "1M tokens",
            "statistics_scope": "public pricing records returned by the Pricing Table adapter with Pricing V2 enabled",
            "null_value_meaning": (
                "Not listed, not published, not applicable, or not currently available in the dataset; "
                "null is not zero."
            ),
        },
        "records": records,
    }
    validate_payload(payload, projection)
    return payload


def parse_date(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate_payload(
    payload: dict[str, Any],
    projection: dict[str, Any],
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(timezone.utc)
    records = payload["records"]
    metadata = payload["metadata"]
    keys = [(row["provider_id"], row["model_id"]) for row in records]
    if len(keys) != len(set(keys)):
        raise ValueError("Hugging Face export contains duplicate provider_id + model_id")
    if set(keys) != expected_public_keys(projection):
        raise ValueError("Hugging Face export key set differs from the public Website projection")
    if metadata["record_count"] != len(records):
        raise ValueError("Hugging Face metadata record_count mismatch")
    if metadata["provider_count"] != len({row["provider_id"] for row in records}):
        raise ValueError("Hugging Face metadata provider_count mismatch")

    for row in records:
        for field in NUMERIC_FIELDS:
            value = row[field]
            if value is not None and (not is_number(value) or value < 0):
                raise ValueError(f"invalid numeric price for {row['provider_id']}/{row['model_id']} {field}")
        if row["currency"] != "USD" or row["pricing_unit"] != "1M tokens":
            raise ValueError(f"invalid unit or currency for {row['provider_id']}/{row['model_id']}")
        verified = row.get("last_verified_at")
        if verified and parse_date(verified) > now:
            raise ValueError(f"future last_verified_at for {row['provider_id']}/{row['model_id']}")

    generated_at = parse_date(metadata["generated_at"])
    if generated_at > now:
        raise ValueError("Hugging Face generated_at is in the future")
    verified_values = [parse_date(row["last_verified_at"]) for row in records if row.get("last_verified_at")]
    if verified_values and generated_at < max(verified_values):
        raise ValueError("Hugging Face generated_at precedes max(last_verified_at)")


def csv_text(records: list[dict[str, Any]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_HEADERS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    return output.getvalue()


def artifact_contents(payload: dict[str, Any]) -> dict[str, str]:
    csv_payload = csv_text(payload["records"])
    return {
        "prices.json": json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        "prices.csv": csv_payload,
        "train.csv": csv_payload,
        "meta.json": json.dumps(payload["metadata"], indent=2, ensure_ascii=False) + "\n",
    }


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp_path.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temp_path, path)


def validate_huggingface_artifacts(output_dir: Path = HF_DIR) -> None:
    projection = read_json(PROJECTION_PATH)
    payload = read_json(output_dir / "prices.json")
    validate_payload(payload, projection)
    expected = artifact_contents(payload)
    for name, content in expected.items():
        path = output_dir / name
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            raise ValueError(f"Hugging Face artifact is inconsistent: {path.relative_to(ROOT)}")
    card = (output_dir / "README.md").read_text(encoding="utf-8")
    for marker in REQUIRED_UTM:
        if marker not in card:
            raise ValueError(f"Hugging Face Dataset Card missing {marker}")


def preserve_existing_generated_at_for_timestamp_only_change(
    payload: dict[str, Any],
    output_dir: Path,
) -> None:
    current_path = output_dir / "prices.json"
    if not current_path.exists():
        return
    current = read_json(current_path)
    current_metadata = dict(current.get("metadata", {}))
    expected_metadata = dict(payload["metadata"])
    current_generated_at = current_metadata.pop("generated_at", None)
    expected_metadata.pop("generated_at", None)
    if (
        current_generated_at
        and current.get("records") == payload["records"]
        and current_metadata == expected_metadata
    ):
        payload["metadata"]["generated_at"] = current_generated_at


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or check the Hugging Face public Website dataset export.")
    parser.add_argument("--website-repo", type=Path, required=True)
    parser.add_argument("--website-ref", default="HEAD")
    parser.add_argument("--output", type=Path, default=HF_DIR)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()

    projection = read_json(PROJECTION_PATH)
    metadata = read_json(META_PATH)
    legacy_models = load_website_models(args.website_repo.resolve(), args.website_ref)
    payload = build_export(projection, metadata, legacy_models)
    preserve_existing_generated_at_for_timestamp_only_change(payload, args.output)
    expected = artifact_contents(payload)

    if args.write:
        for name, content in expected.items():
            write_atomic(args.output / name, content)
        validate_huggingface_artifacts(args.output)
        print(f"wrote Hugging Face export: {len(payload['records'])} records")
        return

    changed = [name for name, content in expected.items() if not (args.output / name).exists() or (args.output / name).read_text(encoding="utf-8") != content]
    if changed:
        raise SystemExit(f"Hugging Face export is stale: {', '.join(changed)}")
    validate_huggingface_artifacts(args.output)
    print(f"Hugging Face export is in sync: {len(payload['records'])} records")


if __name__ == "__main__":
    main()
