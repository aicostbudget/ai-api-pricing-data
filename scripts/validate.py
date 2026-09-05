from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import date, datetime, timezone
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
try:
    from lib import API, DATA, PRICE_FIELDS, ROOT, build_dataset, csv_rows, load_models, load_providers
except ModuleNotFoundError:
    from scripts.lib import API, DATA, PRICE_FIELDS, ROOT, build_dataset, csv_rows, load_models, load_providers
try:
    from pricing_contract import PricingContractError, validate_model_price_records
except ModuleNotFoundError:
    from scripts.pricing_contract import PricingContractError, validate_model_price_records

MODEL_SCHEMA = json.loads((ROOT / "schema" / "model.schema.json").read_text(encoding="utf-8"))
PRICING_PROPERTIES = MODEL_SCHEMA["properties"]["pricing"]["properties"]
PRICING_COMPONENT_SCHEMA = MODEL_SCHEMA["$defs"]["pricingComponent"]
LEGACY_TOKEN_PRICE_FIELDS = tuple(
    field for field in PRICING_PROPERTIES if field not in {"currency", "unit"}
)


def fail(message: str) -> None:
    raise SystemExit(f"validation failed: {message}")


def parse_ts(value: str) -> datetime:
    if not value.endswith("Z"):
        fail(f"timestamp must end with Z: {value}")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail(f"invalid timestamp: {value}")


def validate_pricing_contract(model: dict, item: tuple[str, str]) -> None:
    pricing = model["pricing"]
    if pricing["currency"] != "USD":
        fail(f"unsupported currency for {item[0]}/{item[1]}")
    for field in PRICE_FIELDS:
        value = pricing[field]
        if value is not None and value < 0:
            fail(f"negative price for {item[0]}/{item[1]} {field}")

    if pricing["unit"] == "1M tokens":
        return
    if pricing["unit"] is not None:
        fail(f"unsupported unit for {item[0]}/{item[1]}")

    populated_token_fields = [
        field for field in LEGACY_TOKEN_PRICE_FIELDS if pricing.get(field) is not None
    ]
    if populated_token_fields:
        fail(
            f"non-token pricing must leave token fields null for {item[0]}/{item[1]}: "
            f"{', '.join(populated_token_fields)}"
        )

    components = model.get("pricing_components")
    if not isinstance(components, list) or not components:
        fail(f"non-token pricing requires pricing_components for {item[0]}/{item[1]}")

    required = set(PRICING_COMPONENT_SCHEMA["required"])
    allowed = set(PRICING_COMPONENT_SCHEMA["properties"])
    for index, component in enumerate(components):
        label = f"{item[0]}/{item[1]} pricing component {index}"
        if not isinstance(component, dict):
            fail(f"invalid {label}")
        missing = required - set(component)
        if missing:
            fail(f"{label} missing fields: {', '.join(sorted(missing))}")
        if PRICING_COMPONENT_SCHEMA.get("additionalProperties") is False:
            extra = set(component) - allowed
            if extra:
                fail(f"{label} has unsupported fields: {', '.join(sorted(extra))}")
        if not isinstance(component["id"], str) or not component["id"]:
            fail(f"invalid {label} id")
        for field in ("component", "modality", "unit", "processing_mode", "pricing_status"):
            if component[field] not in PRICING_COMPONENT_SCHEMA["properties"][field]["enum"]:
                fail(f"invalid {label} {field}")
        amount = component["amount"]
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount <= 0:
            fail(f"invalid positive amount for {label}")
        if component["currency"] != PRICING_COMPONENT_SCHEMA["properties"]["currency"]["const"]:
            fail(f"invalid {label} currency")
        if not isinstance(component["calculation_default"], bool):
            fail(f"invalid {label} calculation_default")
        for field in ("effective_from", "effective_until"):
            value = component[field]
            if value is not None:
                if not isinstance(value, str):
                    fail(f"invalid {label} {field}")
                try:
                    date.fromisoformat(value)
                except ValueError:
                    fail(f"invalid {label} {field}")


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
        validate_pricing_contract(model, item)

        source_urls = model.get("official_source_urls", [model["official_source_url"]])
        if model["official_source_url"] not in source_urls:
            fail(f"primary official source missing from official_source_urls for {item[0]}/{item[1]}")
        if len(source_urls) != len(set(source_urls)) or any(
            not str(url).startswith("https://") for url in source_urls
        ):
            fail(f"invalid official_source_urls for {item[0]}/{item[1]}")

        try:
            validate_model_price_records(model)
        except PricingContractError as exc:
            fail(f"invalid declarative pricing contract for {item[0]}/{item[1]}: {exc}")

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

        time_pricing = model.get("time_pricing")
        if time_pricing:
            if tiers:
                fail(f"time pricing must not be represented as pricing_tiers for {item[0]}/{item[1]}")
            if time_pricing["timezone"] != "UTC":
                fail(f"unsupported time pricing timezone for {item[0]}/{item[1]}")
            parse_ts(time_pricing["rate_effective_from"])
            if time_pricing["schedule_effective_from"] is not None:
                parse_ts(time_pricing["schedule_effective_from"])
            parse_ts(time_pricing["schedule_accessed_at"])
            parse_ts(time_pricing["schedule_verified_at"])
            if time_pricing["schedule_source_url"] not in source_urls:
                fail(f"time pricing schedule source missing from official_source_urls for {item[0]}/{item[1]}")
            periods = time_pricing["periods"]
            period_ids = [period["id"] for period in periods]
            if len(period_ids) != len(set(period_ids)):
                fail(f"duplicate time pricing period id for {item[0]}/{item[1]}")
            defaults = [period for period in periods if period["is_default"]]
            if len(defaults) != 1 or defaults[0]["id"] != time_pricing["default_period_id"]:
                fail(f"time pricing requires exactly one matching default period for {item[0]}/{item[1]}")
            if not defaults[0]["all_other_times"]:
                fail(f"time pricing default period must cover all other times for {item[0]}/{item[1]}")
            for period in periods:
                period_pricing = period["pricing"]
                if period_pricing["currency"] != pricing["currency"] or period_pricing["unit"] != pricing["unit"]:
                    fail(f"time pricing currency/unit mismatch for {item[0]}/{item[1]} period {period['id']}")
                for field in ("input", "cached_input", "output"):
                    value = period_pricing[field]
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                        fail(f"invalid time price for {item[0]}/{item[1]} period {period['id']} {field}")
                for window in period["time_windows"]:
                    if window["start"] >= window["end"]:
                        fail(f"invalid time window for {item[0]}/{item[1]} period {period['id']}")

            if item in {("deepseek", "deepseek-v4-flash"), ("deepseek", "deepseek-v4-pro")}:
                periods_by_id = {period["id"]: period for period in periods}
                if set(periods_by_id) != {"peak", "off_peak"}:
                    fail(f"{item[0]}/{item[1]} must have peak and off_peak periods")
                peak = periods_by_id["peak"]
                off_peak = periods_by_id["off_peak"]
                weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday"]
                if peak["active_weekdays"] != weekdays or len(peak["time_windows"]) < 2:
                    fail(f"{item[0]}/{item[1]} peak schedule mismatch")
                if off_peak["active_weekdays"] or off_peak["time_windows"] or not off_peak["all_other_times"]:
                    fail(f"{item[0]}/{item[1]} off_peak fallback mismatch")
                for field in ("input", "cached_input", "output"):
                    if peak["pricing"][field] != 2 * off_peak["pricing"][field]:
                        fail(f"{item[0]}/{item[1]} peak must equal 2x off_peak for {field}")
                v1_prices = {field: pricing[field] for field in ("input", "cached_input", "output")}
                peak_prices = {field: peak["pricing"][field] for field in v1_prices}
                if v1_prices != peak_prices:
                    fail(f"{item[0]}/{item[1]} V1 pricing must match Peak")

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
    required = {
        ("mistral-ai", "mistral-large", "price_update", "2026-07-27"): {
            "old_prices": {"input": 2, "cached_input": None, "output": 6},
            "new_prices": {"input": 0.5, "cached_input": 0.05, "output": 1.5},
        },
        ("openai", "gpt-5.6-sol", "price_update", "2026-08-22"): {
            "old_prices": {"input": 5, "cached_input": 0.5, "output": 30},
            "new_prices": {"input": 4, "cached_input": 0.4, "output": 20},
        },
        ("xai", "grok-4.3", "cached_price_added", "2026-07-27"): {
            "old_prices": {"input": 1.25, "cached_input": None, "output": 2.5},
            "new_prices": {"input": 1.25, "cached_input": 0.2, "output": 2.5},
        },
    }
    by_identity: dict[tuple[str, str, str, str], dict] = {}
    for event in events:
        identity = (
            event["provider_id"],
            event["model_id"],
            event["change_type"],
            event["detected_at"],
        )
        if identity in by_identity:
            fail(f"duplicate price change event identity: {identity}")
        by_identity[identity] = event
    for identity, expected_prices in required.items():
        event = by_identity.get(identity)
        if event is None:
            fail(f"missing required price change event: {identity}")
        for field in ("old_prices", "new_prices"):
            if event[field] != expected_prices[field]:
                fail(f"required price change event {identity} has unexpected {field}: {event[field]}")


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
