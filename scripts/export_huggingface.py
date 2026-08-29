from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import subprocess
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
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
    "verification_status",
    "last_verified_at",
    "checked_at",
    "effective_from",
    "effective_until",
    "notes",
    "pricing_tier_count",
    "pricing_tiers_json",
    "time_pricing_json",
    "pricing_components_json",
)
PUBLIC_SCHEMA_VERSION = "1.4.0"
PUBLIC_VERIFICATION_STATUSES = {
    "verified",
    "partially_verified",
    "review_required",
    "unresolved",
    "legacy_unverified",
}
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
    "utm_medium=referral",
    "utm_campaign=pricing_dataset",
)
FORBIDDEN_UTM = (
    "utm_medium=dataset",
    "utm_campaign=ai_api_pricing",
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


def public_pricing_tiers(
    row: dict[str, Any],
    last_verified_at: str | None,
    checked_at: str | None,
) -> list[dict[str, Any]]:
    return [
        {
            "id": tier["id"],
            "pricing_id": tier["pricingId"],
            "label": tier["label"],
            "context_class": tier["contextClass"],
            "calculation_default": tier["calculationDefault"],
            "prompt_token_threshold": tier["promptTokenThreshold"],
            "comparison": tier["comparison"],
            "token_basis": tier["tokenBasis"],
            "cached_prompt_tokens_included": tier["cachedPromptTokensIncluded"],
            "whole_request_pricing": tier["wholeRequestPricing"],
            "processing_mode": tier["processingMode"],
            "input_price_per_1m_tokens": tier["inputPrice"],
            "cached_input_price_per_1m_tokens": (
                tier.get("cachedInputPrice") if is_number(tier.get("cachedInputPrice")) else None
            ),
            "output_price_per_1m_tokens": tier["outputPrice"],
            "currency": tier["currency"],
            "pricing_unit": "1M tokens",
            "official_source_url": row["officialSourceUrl"],
            "source_refs": list(tier["sourceRefs"]),
            "last_verified_at": last_verified_at,
            "checked_at": checked_at,
            "verification_status": tier["verificationStatus"],
        }
        for tier in row.get("pricingTiers", [])
    ]


def public_pricing_components(row: dict[str, Any]) -> list[dict[str, Any]]:
    source_url_by_ref = dict(zip(row.get("sourceRefs", []), row.get("sourceUrls", []), strict=True))
    public_components = []
    for component in sorted(
        row.get("pricingComponents", []),
        key=lambda item: (item["pricingId"], item["chargeId"]),
    ):
        amount = component.get("amount")
        if not isinstance(amount, str):
            raise ValueError(f"component amount must remain a decimal string for {row['provider']}/{row['id']}")
        try:
            if Decimal(amount) < 0:
                raise ValueError
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"invalid component amount for {row['provider']}/{row['id']}: {amount}") from exc
        status = component.get("verificationStatus")
        if status not in PUBLIC_VERIFICATION_STATUSES:
            raise ValueError(f"unsupported public component verification status: {status}")
        source_refs = sorted(component.get("sourceRefs", []))
        try:
            source_urls = [source_url_by_ref[source_ref] for source_ref in source_refs]
        except KeyError as exc:
            raise ValueError(
                f"unresolvable component source ref for {row['provider']}/{row['id']}: {exc.args[0]}"
            ) from exc
        condition = component["condition"]
        tier_selection = condition.get("tierSelection")
        public_components.append(
            {
                "pricing_id": component["pricingId"],
                "charge_id": component["chargeId"],
                "component": component["component"],
                "amount": amount,
                "unit": component["unit"],
                "currency": component["currency"],
                "modality": component["modality"],
                "condition": {
                    "processing_mode": condition["processingMode"],
                    "context_class": condition["contextClass"],
                    "prompt_token_threshold": condition.get("promptTokenThreshold"),
                    "tier_selection": None if tier_selection is None else {
                        "comparison": tier_selection["comparison"],
                        "token_basis": tier_selection["tokenBasis"],
                        "cached_prompt_tokens_included": tier_selection["cachedPromptTokensIncluded"],
                        "whole_request_pricing": tier_selection["wholeRequestPricing"],
                    },
                    "region_policy": condition["regionPolicy"],
                    "effective_from": condition.get("effectiveFrom"),
                    "effective_until": condition.get("effectiveUntil"),
                },
                "calculation_default": component["calculationDefault"],
                "source_refs": source_refs,
                "source_urls": source_urls,
                "verification_status": status,
            }
        )
    return public_components


def load_website_models(website_repo: Path, website_ref: str) -> list[dict[str, Any]]:
    if website_ref == "WORKTREE":
        rows = read_json(website_repo / "data" / "model-pricing.json")
        if not isinstance(rows, list):
            raise ValueError("Website data/model-pricing.json must be a JSON array")
        return rows
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


def load_website_projection(website_repo: Path, website_ref: str) -> dict[str, Any]:
    relative_path = "data/pricing-v2-projection/model-pricing.v2.json"
    if website_ref == "WORKTREE":
        projection = read_json(website_repo / relative_path)
    else:
        result = subprocess.run(
            ["git", "-C", str(website_repo), "show", f"{website_ref}:{relative_path}"],
            check=True,
            capture_output=True,
            encoding="utf-8",
        )
        projection = json.loads(result.stdout)
    if not isinstance(projection, dict) or not isinstance(projection.get("models"), list):
        raise ValueError("Website pricing projection must contain a models array")
    return projection


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
            last_verified_at = date_only(row.get("verifiedAt"))
            checked_at = date_only(row.get("checkedAt"))
            tiers = public_pricing_tiers(row, last_verified_at, checked_at)
            components = public_pricing_components(row)
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
                    "verification_status": row["verificationStatus"],
                    "last_verified_at": last_verified_at,
                    "checked_at": checked_at,
                    "effective_from": row.get("selectedPriceEffectiveFrom"),
                    "effective_until": row.get("selectedPriceEffectiveUntil"),
                    "notes": warning if warning is not None else (legacy.get("priceNote", "") if legacy else ""),
                    "pricing_tier_count": len(tiers),
                    "pricing_tiers": tiers,
                    "time_pricing": row.get("timePricing"),
                    "pricing_components": components,
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
                "official_source_url": row["officialSourceUrl"],
                "verification_status": row["verificationStatus"],
                "last_verified_at": date_only(row.get("verifiedAt")),
                "checked_at": date_only(row.get("checkedAt")),
                "effective_from": row.get("selectedPriceEffectiveFrom"),
                "effective_until": row.get("selectedPriceEffectiveUntil"),
                "notes": fallback_warning(row),
                "pricing_tier_count": 0,
                "pricing_tiers": [],
                "time_pricing": row.get("timePricing"),
                "pricing_components": public_pricing_components(row),
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
            "schema_version": PUBLIC_SCHEMA_VERSION,
            "page_url": DATASET_PAGE_URL,
            "last_updated": metadata["last_verified_at"],
            "last_verified_at": metadata["last_verified_at"],
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
            "features": {
                "pricing_components": "Full conditional pricing components; [] when none apply.",
                "pricing_components_json": "Compact CSV JSON serialization of pricing_components.",
                "time_pricing": "Structured request-time pricing schedule; null when no temporal pricing applies.",
                "time_pricing_json": "Compact CSV JSON serialization of time_pricing.",
            },
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

    projection_by_key = {(row["provider"], row["id"]): row for row in projection["models"]}
    for row in records:
        key = (row["provider_id"], row["model_id"])
        canonical = projection_by_key[key]
        expected_verified = date_only(canonical.get("verifiedAt"))
        expected_checked = date_only(canonical.get("checkedAt"))
        if row["official_source_url"] != canonical["officialSourceUrl"]:
            raise ValueError(f"official source mismatch for {key[0]}/{key[1]}")
        if row["verification_status"] != canonical["verificationStatus"]:
            raise ValueError(f"verification status mismatch for {key[0]}/{key[1]}")
        if row["last_verified_at"] != expected_verified:
            raise ValueError(f"verifiedAt mismatch for {key[0]}/{key[1]}")
        if row["checked_at"] != expected_checked:
            raise ValueError(f"checkedAt mismatch for {key[0]}/{key[1]}")
        if canonical.get("verifiedAt") is None and row["last_verified_at"] is not None:
            raise ValueError(f"checkedAt/generatedAt substituted for verifiedAt: {key[0]}/{key[1]}")
        for field in NUMERIC_FIELDS:
            value = row[field]
            if value is not None and (not is_number(value) or value < 0):
                raise ValueError(f"invalid numeric price for {row['provider_id']}/{row['model_id']} {field}")
        if row["currency"] != "USD" or row["pricing_unit"] != "1M tokens":
            raise ValueError(f"invalid unit or currency for {row['provider_id']}/{row['model_id']}")
        tiers = row.get("pricing_tiers", [])
        if row.get("pricing_tier_count") != len(tiers):
            raise ValueError(f"pricing tier count mismatch for {row['provider_id']}/{row['model_id']}")
        for tier in tiers:
            for field in NUMERIC_FIELDS:
                value = tier[field]
                if value is not None and (not is_number(value) or value < 0):
                    raise ValueError(f"invalid tier price for {row['provider_id']}/{row['model_id']} {field}")
            if tier["official_source_url"] != canonical["officialSourceUrl"]:
                raise ValueError(f"tier official source mismatch for {key[0]}/{key[1]}")
            if tier["last_verified_at"] != expected_verified:
                raise ValueError(f"tier verifiedAt mismatch for {key[0]}/{key[1]}")
            if tier["checked_at"] != expected_checked:
                raise ValueError(f"tier checkedAt mismatch for {key[0]}/{key[1]}")
        components = row.get("pricing_components", [])
        expected_components = public_pricing_components(canonical)
        if components != expected_components:
            raise ValueError(f"pricing component mismatch for {key[0]}/{key[1]}")
        if row.get("time_pricing") != canonical.get("timePricing"):
            raise ValueError(f"time pricing mismatch for {key[0]}/{key[1]}")
        verified = row.get("last_verified_at")
        if verified and parse_date(verified) > now:
            raise ValueError(f"future last_verified_at for {row['provider_id']}/{row['model_id']}")

    generated_at = parse_date(metadata["generated_at"])
    if generated_at > now:
        raise ValueError("Hugging Face generated_at is in the future")
    verified_values = [parse_date(row["last_verified_at"]) for row in records if row.get("last_verified_at")]
    if verified_values and generated_at < max(verified_values):
        raise ValueError("Hugging Face generated_at precedes max(last_verified_at)")
    checked_values = [parse_date(row["checked_at"]) for row in records if row.get("checked_at")]
    if checked_values and generated_at < max(checked_values):
        raise ValueError("Hugging Face generated_at precedes max(checked_at)")


def csv_text(records: list[dict[str, Any]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_HEADERS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(
        {
            **{key: value for key, value in record.items() if key not in {"pricing_tiers", "time_pricing", "pricing_components"}},
            "pricing_tiers_json": json.dumps(record["pricing_tiers"], separators=(",", ":"), ensure_ascii=False),
            "time_pricing_json": json.dumps(record["time_pricing"], separators=(",", ":"), ensure_ascii=False),
            "pricing_components_json": json.dumps(record["pricing_components"], separators=(",", ":"), ensure_ascii=False),
        }
        for record in records
    )
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
    for marker in FORBIDDEN_UTM:
        if marker in card:
            raise ValueError(f"Hugging Face Dataset Card contains legacy {marker}")


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

    canonical_projection = read_json(PROJECTION_PATH)
    projection = load_website_projection(args.website_repo.resolve(), args.website_ref)
    canonical_components = {
        (row["provider"], row["id"]): public_pricing_components(row)
        for row in canonical_projection["models"]
    }
    website_components = {
        (row["provider"], row["id"]): public_pricing_components(row)
        for row in projection["models"]
    }
    if website_components != canonical_components:
        raise ValueError("Website pricing components differ from the canonical Pricing V2 projection")
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
