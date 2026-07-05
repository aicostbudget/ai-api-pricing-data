from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

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


def validate_models() -> None:
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
        parse_ts(model["accessed_at"])
        parse_ts(model["last_verified_at"])
        pricing = model["pricing"]
        if pricing["currency"] != "USD":
            fail(f"unsupported currency for {item[0]}/{item[1]}")
        if pricing["unit"] != "1M tokens":
            fail(f"unsupported unit for {item[0]}/{item[1]}")
        for field in PRICE_FIELDS:
            value = pricing[field]
            if value is not None and value < 0:
                fail(f"negative price for {item[0]}/{item[1]} {field}")


def validate_outputs() -> None:
    expected = build_dataset()
    actual = json.loads((DATA / "prices.json").read_text(encoding="utf-8"))
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


def validate_schema_files() -> None:
    for name in ("model.schema.json", "provider.schema.json", "dataset.schema.json"):
        schema = json.loads((ROOT / "schema" / name).read_text(encoding="utf-8"))
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            fail(f"schema {name} missing draft marker")


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
    if args.freshness_report:
        raise SystemExit(freshness_report(args.max_age_days, args.check_urls))
    validate_outputs()
    print("validation ok")


if __name__ == "__main__":
    main()

