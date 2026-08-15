from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

try:
    from generate_price_change_events import EVENTS_PATH, load_events
except ModuleNotFoundError:
    from scripts.generate_price_change_events import EVENTS_PATH, load_events
try:
    from export_huggingface import validate_huggingface_artifacts
except ModuleNotFoundError:
    from scripts.export_huggingface import validate_huggingface_artifacts
from lib import API, DATA, PRICE_FIELDS, ROOT, build_dataset, csv_rows, load_models, load_providers


def fail(message: str) -> None:
    raise SystemExit(f"validation failed: {message}")


def parse_ts(value: str) -> datetime:
    if not value.endswith("Z"):
        fail(f"timestamp must end with Z: {value}")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail(f"invalid timestamp: {value}")


def validate_models(now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    providers = load_providers()
    models = load_models()
    provider_ids = [provider["provider_id"] for provider in providers]
    if len(provider_ids) != len(set(provider_ids)):
        fail("duplicate provider_id")
    provider_set = set(provider_ids)
    seen_models: set[tuple[str, str]] = set()
    for provider in providers:
        for field in ("provider_id", "display_name", "website_url", "pricing_url", "docs_url", "notes"):
            if not provider.get(field):
                fail(f"provider {provider.get('provider_id')} missing {field}")
    for model in models:
        item = (model["provider_id"], model["model_id"])
        if item in seen_models:
            fail(f"duplicate model id {item[0]}/{item[1]}")
        seen_models.add(item)
        if model["provider_id"] not in provider_set:
            fail(f"model uses unknown provider {model['provider_id']}")
        if not str(model.get("official_source_url", "")).startswith("https://"):
            fail(f"missing official source URL for {item[0]}/{item[1]}")
        accessed_at = parse_ts(model["accessed_at"])
        last_verified_at = parse_ts(model["last_verified_at"])
        if accessed_at > now:
            fail(f"future accessed_at for {item[0]}/{item[1]}: {model['accessed_at']}")
        if last_verified_at > now:
            fail(f"future last_verified_at for {item[0]}/{item[1]}: {model['last_verified_at']}")
        pricing = model["pricing"]
        if pricing["currency"] != "USD":
            fail(f"unsupported currency for {item[0]}/{item[1]}")
        if pricing["unit"] != "1M tokens":
            fail(f"unsupported unit for {item[0]}/{item[1]}")
        for field in PRICE_FIELDS:
            value = pricing[field]
            if value is not None and value < 0:
                fail(f"negative price for {item[0]}/{item[1]} {field}")

        source_urls = model.get("official_source_urls", [model["official_source_url"]])
        if model["official_source_url"] not in source_urls:
            fail(f"primary official source missing from official_source_urls for {item[0]}/{item[1]}")
        if len(source_urls) != len(set(source_urls)) or any(
            not str(url).startswith("https://") for url in source_urls
        ):
            fail(f"invalid official_source_urls for {item[0]}/{item[1]}")

        tiers = model.get("pricing_tiers", [])
        if tiers:
            tier_keys = [
                (tier["processing_mode"], tier["id"], tier["pricing_status"])
                for tier in tiers
            ]
            if len(tier_keys) != len(set(tier_keys)):
                fail(f"duplicate pricing tier for {item[0]}/{item[1]}")
            defaults = [tier for tier in tiers if tier["calculation_default"]]
            if len(defaults) != 1:
                fail(f"tiered model must have exactly one calculation default for {item[0]}/{item[1]}")
            for tier in tiers:
                threshold = tier["prompt_token_threshold"]
                if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 0:
                    fail(f"invalid prompt token threshold for {item[0]}/{item[1]} tier {tier['id']}")
                if tier["threshold_token_basis"] != "total_prompt_tokens":
                    fail(f"invalid threshold token basis for {item[0]}/{item[1]} tier {tier['id']}")
                if tier["cached_prompt_tokens_included"] is not True:
                    fail(f"cached prompt token semantics missing for {item[0]}/{item[1]} tier {tier['id']}")
                if tier["whole_request_pricing"] is not True:
                    fail(f"whole-request pricing semantics missing for {item[0]}/{item[1]} tier {tier['id']}")
                if tier["currency"] != pricing["currency"] or tier["unit"] != pricing["unit"]:
                    fail(f"tier currency/unit mismatch for {item[0]}/{item[1]} tier {tier['id']}")
                for field in ("input", "cached_input", "output"):
                    value = tier[field]
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                        fail(f"invalid tier price for {item[0]}/{item[1]} tier {tier['id']} {field}")

        if item == ("xai", "grok-4.3"):
            tiers_by_id = {tier["id"]: tier for tier in tiers}
            if set(tiers_by_id) != {"short", "long"}:
                fail("xai/grok-4.3 must have exactly short and long canonical pricing tiers")
            short = tiers_by_id["short"]
            long = tiers_by_id["long"]
            if short["prompt_token_threshold"] != 200000 or short["threshold_comparison"] != "less_than":
                fail("xai/grok-4.3 short tier must apply below 200000 prompt tokens")
            if long["prompt_token_threshold"] != 200000 or long["threshold_comparison"] != "greater_than_or_equal":
                fail("xai/grok-4.3 long tier must apply at or above 200000 prompt tokens")
            if not short["calculation_default"] or long["calculation_default"]:
                fail("xai/grok-4.3 short tier must be the only calculation default")
            expected_prices = {
                "short": {"input": 1.25, "cached_input": 0.2, "output": 2.5},
                "long": {"input": 2.5, "cached_input": 0.4, "output": 5.0},
            }
            for tier_id, expected in expected_prices.items():
                actual = {field: tiers_by_id[tier_id][field] for field in expected}
                if actual != expected:
                    fail(f"xai/grok-4.3 {tier_id} tier price mismatch")
            short_projection = {field: short[field] for field in ("input", "cached_input", "output")}
            v1_projection = {field: pricing[field] for field in ("input", "cached_input", "output")}
            if short_projection != v1_projection:
                fail("xai/grok-4.3 V1 pricing must match its canonical short tier")


def validate_outputs() -> None:
    actual = json.loads((DATA / "prices.json").read_text(encoding="utf-8"))
    generated_at = parse_ts(actual["generated_at"])
    latest_verified_at = max(parse_ts(model["last_verified_at"]) for model in load_models())
    if generated_at < latest_verified_at:
        fail(
            f"data/prices.json generated_at {actual['generated_at']} precedes "
            f"latest last_verified_at {latest_verified_at.isoformat().replace('+00:00', 'Z')}"
        )
    expected = build_dataset(actual["generated_at"])
    if actual != expected:
        fail("data/prices.json is not reproducible from canonical data; run scripts/build.py")

    with (DATA / "prices.csv").open(encoding="utf-8", newline="") as handle:
        actual_rows = list(csv.DictReader(handle))
    expected_rows = csv_rows(load_models())
    normalized = [{key: "" if value is None else str(value) for key, value in row.items()} for row in expected_rows]
    if actual_rows != normalized:
        fail("data/prices.csv is inconsistent with canonical model data")

    for required in [
        API / "prices.json",
        API / "prices.csv",
        API / "meta.json",
    ]:
        if not required.exists():
            fail(f"missing API output {required}")
    json.loads((API / "prices.json").read_text(encoding="utf-8"))
    json.loads((API / "meta.json").read_text(encoding="utf-8"))
    try:
        validate_huggingface_artifacts()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        fail(str(exc))


def validate_schema_files() -> None:
    for name in ("model.schema.json", "provider.schema.json", "dataset.schema.json", "price-change-event.schema.json", "pricing-v2-preview.schema.json"):
        schema = json.loads((ROOT / "schema" / name).read_text(encoding="utf-8"))
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            fail(f"schema {name} missing draft marker")


def validate_price_change_events() -> None:
    if not EVENTS_PATH.exists():
        fail(f"missing price change events file {EVENTS_PATH.relative_to(ROOT)}")
    events = load_events(EVENTS_PATH)
    if len(events) != 2:
        fail(f"expected 2 verified price change events, found {len(events)}")
    expected = {
        ("mistral-ai", "mistral-large", "price_update"),
        ("xai", "grok-4.3", "cached_price_added"),
    }
    actual = {(event["provider_id"], event["model_id"], event["change_type"]) for event in events}
    if actual != expected:
        fail(f"unexpected price change event set: {sorted(actual)}")


def freshness_report(days: int, check_urls: bool) -> int:
    now = datetime.now(timezone.utc)
    stale: list[str] = []
    unreachable: list[str] = []
    for model in load_models():
        verified = parse_ts(model["last_verified_at"])
        age = (now - verified).days
        if age > days:
            stale.append(f"{model['provider_id']}/{model['model_id']} last_verified_at is {age} days old")
        if check_urls:
            try:
                request = Request(model["official_source_url"], headers={"User-Agent": "AICostBudget freshness-check/1.0"})
                with urlopen(request, timeout=20) as response:
                    if response.status >= 400:
                        unreachable.append(f"{model['official_source_url']} returned {response.status}")
            except Exception as exc:
                unreachable.append(f"{model['official_source_url']} failed: {exc}")
    report_path = ROOT / "freshness-report.md"
    lines = ["# Freshness Report", ""]
    lines.append(f"Threshold: {days} days")
    lines.append("")
    lines.append("## Stale records")
    lines.extend(f"- {item}" for item in stale) if stale else lines.append("- None")
    lines.append("")
    lines.append("## URL checks")
    lines.extend(f"- {item}" for item in unreachable) if unreachable else lines.append("- None")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if stale or unreachable else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the dataset.")
    parser.add_argument("--freshness-report", action="store_true")
    parser.add_argument("--max-age-days", type=int, default=30)
    parser.add_argument("--check-urls", action="store_true")
    args = parser.parse_args()
    validate_schema_files()
    validate_models()
    validate_price_change_events()
    if args.freshness_report:
        raise SystemExit(freshness_report(args.max_age_days, args.check_urls))
    validate_outputs()
    print("validation ok")


if __name__ == "__main__":
    main()
