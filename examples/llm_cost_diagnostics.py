#!/usr/bin/env python3
"""Estimate retry and fallback costs from normalized, anonymized attempt logs."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "data" / "pricing-v2-preview" / "generated" / "model-pricing.v2.json"
DEFAULT_ATTEMPTS = ROOT / "examples" / "sample_llm_attempts.json"
MILLION = Decimal("1000000")
ATTEMPT_TYPES = ("first_attempt", "retry", "fallback")
USAGE_COMPONENTS = ("input", "cached_input", "output")
BILLING_STATUSES = ("billed", "not_billed", "unknown")


class DiagnosticError(ValueError):
    """Raised when input records are invalid."""


class UnsupportedBillingError(DiagnosticError):
    """Raised when a cost would require an unsupported billing assumption."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle, parse_float=Decimal)
    except (OSError, json.JSONDecodeError) as exc:
        raise DiagnosticError(f"cannot read JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DiagnosticError(f"{path} must contain a JSON object")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DiagnosticError(f"{field} must be a non-empty string")
    return value


def _count(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DiagnosticError(f"{field} must be a non-negative integer")
    return value


def _decimal(value: Any, field: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise UnsupportedBillingError(f"{field} is not a decimal amount") from exc
    if not amount.is_finite() or amount < 0:
        raise UnsupportedBillingError(f"{field} must be a finite non-negative amount")
    return amount


def _catalog_models(catalog: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    models = catalog.get("models")
    if not isinstance(models, list):
        raise UnsupportedBillingError("pricing catalog has no models array")

    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for position, model in enumerate(models):
        if not isinstance(model, dict):
            raise UnsupportedBillingError(f"pricing catalog model {position} is not an object")
        provider = model.get("provider")
        model_id = model.get("id")
        if not isinstance(provider, str) or not isinstance(model_id, str):
            continue
        key = (provider, model_id)
        if key in indexed:
            raise UnsupportedBillingError(f"pricing catalog contains duplicate model {provider}/{model_id}")
        indexed[key] = model
    return indexed


def _is_supported_condition(condition: Any) -> bool:
    if not isinstance(condition, dict):
        return False
    supported_keys = {
        "availabilityRules",
        "contextClass",
        "defaultAvailabilityStatus",
        "effectiveFrom",
        "effectiveUntil",
        "priceAdjustments",
        "processingMode",
        "promptTokenThreshold",
        "regionPolicy",
        "regionSelector",
        "tierSelection",
    }
    if set(condition) - supported_keys:
        return False
    if condition.get("processingMode") != "standard":
        return False
    if condition.get("contextClass") != "short":
        return False
    if condition.get("regionPolicy") != "global":
        return False
    if condition.get("promptTokenThreshold") is not None:
        return False
    if condition.get("tierSelection") is not None:
        return False
    if condition.get("effectiveUntil") is not None:
        return False
    if condition.get("availabilityRules", []) != []:
        return False
    if condition.get("priceAdjustments", []) != []:
        return False
    if condition.get("defaultAvailabilityStatus", "available") != "available":
        return False

    selector = condition.get("regionSelector")
    if selector is not None:
        if not isinstance(selector, dict):
            return False
        if selector.get("pricingGeography") != "global_base":
            return False
        if selector.get("endpointGeographies") != ["global"]:
            return False
        if selector.get("dataResidencies") != ["global"]:
            return False
    return True


def selected_rates(model: dict[str, Any], model_key: str) -> dict[str, Decimal]:
    if model.get("defaultSafe") is not True:
        raise UnsupportedBillingError(f"{model_key} is not default-safe in Pricing V2")
    if model.get("verificationStatus") != "verified":
        raise UnsupportedBillingError(f"{model_key} is not verified in Pricing V2")
    if model.get("billingModelInternalId") is not None:
        raise UnsupportedBillingError(f"{model_key} delegates billing to another model")

    pricing_id = model.get("selectedBillingPriceRecordId")
    if not isinstance(pricing_id, str) or not pricing_id:
        raise UnsupportedBillingError(f"{model_key} has no selected billing price record")
    if pricing_id != model.get("selectedPriceRecordId"):
        raise UnsupportedBillingError(f"{model_key} billing and display price records differ")

    price_records = model.get("priceRecords")
    if not isinstance(price_records, list):
        raise UnsupportedBillingError(f"{model_key} has no Pricing V2 price records")
    selected = [record for record in price_records if isinstance(record, dict) and record.get("pricingId") == pricing_id]
    if len(selected) != 1:
        raise UnsupportedBillingError(f"{model_key} does not have exactly one selected price record")
    record = selected[0]
    if record.get("calculationDefault") is not True:
        raise UnsupportedBillingError(f"{model_key} selected price is not the calculation default")
    if record.get("verificationStatus") != "verified":
        raise UnsupportedBillingError(f"{model_key} selected price is not verified")
    if record.get("processingMode") != "standard" or record.get("contextClass") != "short":
        raise UnsupportedBillingError(f"{model_key} selected price is not standard short-context pricing")
    if record.get("pricingStatus") not in (None, "current") or record.get("effectiveUntil") is not None:
        raise UnsupportedBillingError(f"{model_key} selected price is not an open-ended current price")

    components = model.get("pricingComponents")
    if not isinstance(components, list):
        raise UnsupportedBillingError(f"{model_key} has no Pricing V2 pricing components")

    rates: dict[str, Decimal] = {}
    for component in components:
        if not isinstance(component, dict) or component.get("pricingId") != pricing_id:
            continue
        name = component.get("component")
        if name not in USAGE_COMPONENTS:
            continue
        if name in rates:
            raise UnsupportedBillingError(f"{model_key} has duplicate {name} rates")
        if component.get("calculationDefault") is not True:
            raise UnsupportedBillingError(f"{model_key} {name} rate is not a calculation default")
        if component.get("verificationStatus") != "verified":
            raise UnsupportedBillingError(f"{model_key} {name} rate is not verified")
        if component.get("currency") != "USD":
            raise UnsupportedBillingError(f"{model_key} {name} rate is not in USD")
        if component.get("modality") != "text" or component.get("unit") != "per_1m_tokens":
            raise UnsupportedBillingError(f"{model_key} {name} rate is not text per_1m_tokens")
        if not _is_supported_condition(component.get("condition")):
            raise UnsupportedBillingError(f"{model_key} {name} rate has unsupported billing conditions")
        rates[name] = _decimal(component.get("amount"), f"{model_key} {name} rate")
    return rates


def _attempt_cost(
    attempt: dict[str, Any],
    models: dict[tuple[str, str], dict[str, Any]],
    label: str,
) -> Decimal:
    provider_id = _text(attempt.get("provider_id"), f"{label}.provider_id")
    model_id = _text(attempt.get("model_id"), f"{label}.model_id")
    billing_status = attempt.get("billing_status")
    if billing_status not in BILLING_STATUSES:
        raise DiagnosticError(f"{label}.billing_status must be one of {', '.join(BILLING_STATUSES)}")
    if billing_status == "unknown":
        raise UnsupportedBillingError(f"{label} has unknown billing status")

    usage = attempt.get("usage")
    if not isinstance(usage, dict):
        raise DiagnosticError(f"{label}.usage must be an object")
    unsupported = sorted(set(usage) - set(USAGE_COMPONENTS))
    if unsupported:
        raise UnsupportedBillingError(f"{label} has unsupported usage components: {', '.join(unsupported)}")
    if not usage:
        raise DiagnosticError(f"{label}.usage must contain at least one supported component")
    counts = {name: _count(value, f"{label}.usage.{name}") for name, value in usage.items()}

    if billing_status == "not_billed":
        return Decimal("0")

    model = models.get((provider_id, model_id))
    model_key = f"{provider_id}/{model_id}"
    if model is None:
        raise UnsupportedBillingError(f"{label} model {model_key} is missing from Pricing V2")
    rates = selected_rates(model, model_key)

    cost = Decimal("0")
    for component, count in counts.items():
        rate = rates.get(component)
        if rate is None:
            raise UnsupportedBillingError(f"{label} model {model_key} has no supported {component} rate")
        cost += Decimal(count) * rate / MILLION
    return cost


def summarize(attempt_document: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    provenance = _text(attempt_document.get("input_provenance"), "input_provenance")
    attempts = attempt_document.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        raise DiagnosticError("attempts must be a non-empty array")

    models = _catalog_models(catalog)
    category_counts = {name: 0 for name in ATTEMPT_TYPES}
    category_costs = {name: Decimal("0") for name in ATTEMPT_TYPES}
    task_attempts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    successful_tasks: set[str] = set()
    attempt_ids: set[str] = set()
    billed_attempts = 0
    not_billed_attempts = 0

    for position, attempt in enumerate(attempts):
        label = f"attempts[{position}]"
        if not isinstance(attempt, dict):
            raise DiagnosticError(f"{label} must be an object")
        task_id = _text(attempt.get("task_id"), f"{label}.task_id")
        attempt_id = _text(attempt.get("attempt_id"), f"{label}.attempt_id")
        if attempt_id in attempt_ids:
            raise DiagnosticError(f"duplicate attempt_id {attempt_id}")
        attempt_ids.add(attempt_id)

        attempt_type = attempt.get("attempt_type")
        if attempt_type not in ATTEMPT_TYPES:
            raise DiagnosticError(f"{label}.attempt_type must be one of {', '.join(ATTEMPT_TYPES)}")
        if not isinstance(attempt.get("success"), bool):
            raise DiagnosticError(f"{label}.success must be a boolean")

        previous = task_attempts[task_id]
        if not previous and attempt_type != "first_attempt":
            raise DiagnosticError(f"{label} is the first record for {task_id} but is not first_attempt")
        if previous and attempt_type == "first_attempt":
            raise DiagnosticError(f"{label} repeats first_attempt for {task_id}")
        if previous and previous[-1]["success"]:
            raise DiagnosticError(f"{label} appears after {task_id} already succeeded")
        if previous:
            current_model = (attempt.get("provider_id"), attempt.get("model_id"))
            previous_model = (previous[-1].get("provider_id"), previous[-1].get("model_id"))
            if attempt_type == "retry" and current_model != previous_model:
                raise DiagnosticError(f"{label} changes model but is classified as retry")
            if attempt_type == "fallback" and current_model == previous_model:
                raise DiagnosticError(f"{label} keeps the same model but is classified as fallback")

        cost = _attempt_cost(attempt, models, label)
        category_counts[attempt_type] += 1
        category_costs[attempt_type] += cost
        if attempt["billing_status"] == "billed":
            billed_attempts += 1
        else:
            not_billed_attempts += 1
        previous.append(attempt)
        if attempt["success"]:
            successful_tasks.add(task_id)

    total_cost = sum(category_costs.values(), Decimal("0"))
    successful_count = len(successful_tasks)
    return {
        "input_provenance": provenance,
        "task_count": len(task_attempts),
        "successful_task_count": successful_count,
        "attempt_count": len(attempts),
        "billed_attempt_count": billed_attempts,
        "not_billed_attempt_count": not_billed_attempts,
        "category_counts": category_counts,
        "category_costs": category_costs,
        "total_cost": total_cost,
        "cost_per_successful_task": total_cost / successful_count if successful_count else None,
    }


def _money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), "f")


def format_summary(summary: dict[str, Any], catalog_path: Path) -> str:
    per_success = summary["cost_per_successful_task"]
    per_success_text = _money(per_success) if per_success is not None else "N/A (no successful tasks)"
    try:
        display_catalog = catalog_path.resolve().relative_to(ROOT)
    except ValueError:
        display_catalog = catalog_path.resolve()
    lines = [
        "LLM cost diagnostics",
        f"Input provenance: {summary['input_provenance']}",
        f"Pricing catalog: {display_catalog.as_posix()}",
        f"Tasks: {summary['task_count']}",
        f"Successful tasks: {summary['successful_task_count']}",
        f"Attempts: {summary['attempt_count']}",
        f"Billed attempts: {summary['billed_attempt_count']}",
        f"Not-billed attempts: {summary['not_billed_attempt_count']}",
        f"First-attempt estimated cost (USD): {_money(summary['category_costs']['first_attempt'])}",
        f"Retry estimated cost (USD): {_money(summary['category_costs']['retry'])}",
        f"Fallback estimated cost (USD): {_money(summary['category_costs']['fallback'])}",
        f"Total estimated cost (USD): {_money(summary['total_cost'])}",
        f"Cost per successful task (USD): {per_success_text}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("attempts", nargs="?", type=Path, default=DEFAULT_ATTEMPTS)
    parser.add_argument("--pricing-catalog", type=Path, default=DEFAULT_CATALOG)
    args = parser.parse_args(argv)
    try:
        summary = summarize(load_json(args.attempts), load_json(args.pricing_catalog))
    except DiagnosticError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(format_summary(summary, args.pricing_catalog))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
