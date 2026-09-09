from __future__ import annotations

"""Generic canonical price-record validation, normalization, and selection."""

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable


PROCESSING_MODES = {"standard", "batch", "flex", "priority", "fast"}
CONTEXT_CLASSES = {"short", "long"}
PRICING_STATUSES = {"current", "future", "historical"}
COMPARISONS = {
    "less_than",
    "less_than_or_equal",
    "greater_than",
    "greater_than_or_equal",
}
USAGE_TIER_MODES = {"graduated", "volume"}
USAGE_BILLING_PERIODS = {"calendar_month"}
USAGE_SCOPES = {"unknown", "billing_account", "project", "processor", "region", "provider_account"}
CHARGE_COMPONENTS = {
    "input",
    "cached_input",
    "cache_write",
    "cache_write_5m",
    "cache_write_1h",
    "cache_read",
    "output",
    "storage",
    "request",
    "tool_call",
    "grounding",
    "document_page",
}
MODALITIES = {"text", "image", "audio", "video", "document"}
UNITS = {
    "per_1m_tokens",
    "per_1k_calls",
    "per_1000_pages",
    "per_minute",
    "per_hour",
    "per_image",
    "per_second",
    "per_request",
}
AVAILABILITY_STATUSES = {"available", "unavailable"}
SELECTOR_KEYS = {"endpoint_geographies", "data_residencies"}


class PricingContractError(ValueError):
    """Raised when a declarative pricing contract is invalid or ambiguous."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PricingContractError(message)


def _decimal(value: Any, label: str) -> Decimal:
    _require(not isinstance(value, bool), f"{label} must be a decimal value")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise PricingContractError(f"{label} must be a decimal value") from exc
    _require(parsed.is_finite(), f"{label} must be finite")
    return parsed


def _decimal_string(value: Any, label: str) -> str:
    parsed = _decimal(value, label)
    rendered = format(parsed, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _json_number(value: Any, label: str) -> int | float:
    parsed = _decimal(value, label)
    return int(parsed) if parsed == parsed.to_integral_value() else float(parsed)


def _parse_date(value: Any, label: str) -> date | None:
    if value is None:
        return None
    _require(isinstance(value, str), f"{label} must be an ISO date")
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise PricingContractError(f"{label} must be an ISO date") from exc


def _validate_timestamp(value: Any, label: str) -> None:
    _require(isinstance(value, str) and value.endswith("Z"), f"{label} is required")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PricingContractError(f"{label} must be an ISO timestamp") from exc


def _validate_slug_list(value: Any, label: str) -> None:
    _require(isinstance(value, list) and value, f"{label} must be a non-empty list")
    _require(len(value) == len(set(value)), f"{label} contains duplicates")
    _require(
        all(isinstance(item, str) and item and item == item.lower() for item in value),
        f"{label} must contain lowercase identifiers",
    )


def _validate_string_list(value: Any, label: str) -> None:
    _require(isinstance(value, list) and value, f"{label} must be a non-empty list")
    _require(len(value) == len(set(value)), f"{label} contains duplicates")
    _require(all(isinstance(item, str) and item for item in value), f"{label} contains an invalid value")


def _validate_selector(selector: Any, label: str, *, allow_empty: bool = False) -> None:
    _require(isinstance(selector, dict), f"{label} must be an object")
    _require(not (set(selector) - SELECTOR_KEYS), f"{label} has unsupported keys")
    _require(allow_empty or bool(selector), f"{label} must not be empty")
    for key, values in selector.items():
        _validate_slug_list(values, f"{label}.{key}")


def _selectors_intersect(left: dict[str, Any], right: dict[str, Any]) -> bool:
    for key in SELECTOR_KEYS:
        if key in left and key in right and not (set(left[key]) & set(right[key])):
            return False
    return True


def _periods_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_start = _parse_date(left.get("effective_from"), "effective_from") or date.min
    left_end = _parse_date(left.get("effective_until"), "effective_until") or date.max
    right_start = _parse_date(right.get("effective_from"), "effective_from") or date.min
    right_end = _parse_date(right.get("effective_until"), "effective_until") or date.max
    return left_start <= right_end and right_start <= left_end


def _matches_selector(selector: dict[str, Any], endpoint_geography: str, data_residency: str) -> bool:
    return (
        endpoint_geography in selector.get("endpoint_geographies", [endpoint_geography])
        and data_residency in selector.get("data_residencies", [data_residency])
    )


def _validate_region_policy(policy: Any, record_id: str) -> None:
    label = f"price record {record_id} region_policy"
    _require(isinstance(policy, dict), f"{label} must be an object")
    required = {"pricing_geography", "endpoint_geographies", "data_residencies", "availability", "price_adjustments"}
    _require(required <= set(policy), f"{label} is missing required fields")
    _require(set(policy) == required, f"{label} has unsupported fields")
    _require(
        policy["pricing_geography"] in {"global_base", "region_specific"},
        f"{label}.pricing_geography is invalid",
    )
    _validate_slug_list(policy["endpoint_geographies"], f"{label}.endpoint_geographies")
    _validate_slug_list(policy["data_residencies"], f"{label}.data_residencies")

    availability = policy["availability"]
    _require(isinstance(availability, dict), f"{label}.availability must be an object")
    _require(set(availability) == {"default", "rules"}, f"{label}.availability has unsupported fields")
    _require(availability.get("default") in AVAILABILITY_STATUSES, f"{label}.availability.default is invalid")
    rules = availability.get("rules", [])
    _require(isinstance(rules, list), f"{label}.availability.rules must be a list")
    rule_ids: set[str] = set()
    rule_selectors: list[tuple[dict[str, Any], str]] = []
    for rule in rules:
        _require(isinstance(rule, dict), f"{label} availability rule must be an object")
        _require(
            set(rule) == {"id", "selector", "status", "reason", "source_refs"},
            f"{label} availability rule has unsupported fields",
        )
        rule_id = rule.get("id")
        _require(isinstance(rule_id, str) and rule_id, f"{label} availability rule id is invalid")
        _require(rule_id not in rule_ids, f"duplicate availability rule id {rule_id}")
        rule_ids.add(rule_id)
        _validate_selector(rule.get("selector"), f"availability rule {rule_id} selector")
        _require(
            set(rule["selector"].get("endpoint_geographies", [])) <= set(policy["endpoint_geographies"])
            and set(rule["selector"].get("data_residencies", [])) <= set(policy["data_residencies"]),
            f"availability rule {rule_id} selector is outside the region policy",
        )
        status = rule.get("status")
        _require(status in AVAILABILITY_STATUSES, f"availability rule {rule_id} status is invalid")
        _require(isinstance(rule.get("reason"), str) and rule["reason"], f"availability rule {rule_id} needs a reason")
        refs = rule.get("source_refs")
        _validate_string_list(refs, f"availability rule {rule_id} source_refs")
        _require(
            not any(
                previous_status != status and _selectors_intersect(rule["selector"], previous_selector)
                for previous_selector, previous_status in rule_selectors
            ),
            f"contradictory availability rules overlap in {record_id}",
        )
        rule_selectors.append((rule["selector"], status))

    adjustments = policy["price_adjustments"]
    _require(isinstance(adjustments, list), f"{label}.price_adjustments must be a list")
    adjustment_ids: set[str] = set()
    adjustment_selectors: list[dict[str, Any]] = []
    for adjustment in adjustments:
        _require(isinstance(adjustment, dict), f"{label} price adjustment must be an object")
        _require(
            set(adjustment) == {"id", "selector", "operation", "factor", "source_refs"},
            f"{label} price adjustment has unsupported fields",
        )
        adjustment_id = adjustment.get("id")
        _require(isinstance(adjustment_id, str) and adjustment_id, f"{label} price adjustment id is invalid")
        _require(adjustment_id not in adjustment_ids, f"duplicate price adjustment id {adjustment_id}")
        adjustment_ids.add(adjustment_id)
        _validate_selector(adjustment.get("selector"), f"price adjustment {adjustment_id} selector")
        _require(
            set(adjustment["selector"].get("endpoint_geographies", [])) <= set(policy["endpoint_geographies"])
            and set(adjustment["selector"].get("data_residencies", [])) <= set(policy["data_residencies"]),
            f"price adjustment {adjustment_id} selector is outside the region policy",
        )
        _require(adjustment.get("operation") == "multiply", f"price adjustment {adjustment_id} operation is invalid")
        _require(_decimal(adjustment.get("factor"), f"price adjustment {adjustment_id} factor") > 0, f"price adjustment {adjustment_id} factor must be > 0")
        _validate_string_list(adjustment.get("source_refs"), f"price adjustment {adjustment_id} source_refs")
        _require(
            not any(_selectors_intersect(adjustment["selector"], previous) for previous in adjustment_selectors),
            f"overlapping price adjustment selectors in {record_id}",
        )
        adjustment_selectors.append(adjustment["selector"])


def validate_canonical_price_records(records: Any, *, production: bool = True) -> None:
    """Validate generic canonical price records without knowing provider or model names."""

    _require(isinstance(records, list) and records, "price_records must be a non-empty list")
    record_ids: set[str] = set()
    charge_ids: set[str] = set()
    required_record_fields = {
        "id",
        "processing_mode",
        "context_class",
        "pricing_status",
        "calculation_default",
        "prompt_token_threshold",
        "effective_from",
        "effective_until",
        "currency",
        "charges",
        "region_policy",
        "source_refs",
        "verification_status",
        "checked_at",
        "verified_at",
        "billing_note",
    }
    allowed_record_fields = required_record_fields | {"tier_selection", "usage_tier"}
    for record in records:
        _require(isinstance(record, dict), "price record must be an object")
        _require(required_record_fields <= set(record), "price record is missing required fields")
        _require(not (set(record) - allowed_record_fields), "price record has unsupported fields")
        record_id = record.get("id")
        _require(isinstance(record_id, str) and record_id, "price record id is invalid")
        _require(record_id not in record_ids, f"duplicate pricing id {record_id}")
        record_ids.add(record_id)
        _require(record.get("processing_mode") in PROCESSING_MODES, f"price record {record_id} processing_mode is invalid")
        _require(record.get("context_class") in CONTEXT_CLASSES, f"price record {record_id} context_class is invalid")
        _require(record.get("pricing_status") in PRICING_STATUSES, f"price record {record_id} pricing_status is invalid")
        _require(isinstance(record.get("calculation_default"), bool), f"price record {record_id} calculation_default is invalid")
        _require(record.get("currency") == "USD", f"price record {record_id} currency is invalid")
        _parse_date(record.get("effective_from"), f"price record {record_id} effective_from")
        _parse_date(record.get("effective_until"), f"price record {record_id} effective_until")
        start = _parse_date(record.get("effective_from"), f"price record {record_id} effective_from")
        end = _parse_date(record.get("effective_until"), f"price record {record_id} effective_until")
        _require(start is None or end is None or start <= end, f"price record {record_id} effective period is invalid")

        threshold = record.get("prompt_token_threshold")
        _require(threshold is None or (isinstance(threshold, int) and not isinstance(threshold, bool) and threshold >= 0), f"price record {record_id} prompt_token_threshold is invalid")
        tier = record.get("tier_selection")
        if tier is not None:
            _require(isinstance(tier, dict), f"price record {record_id} tier_selection must be an object")
            _require(
                set(tier) == {"comparison", "token_basis", "cached_prompt_tokens_included", "whole_request_pricing"},
                f"price record {record_id} tier_selection has unsupported fields",
            )
            _require(threshold is not None, f"price record {record_id} tier_selection requires a threshold")
            _require(tier.get("comparison") in COMPARISONS, f"price record {record_id} comparison is invalid")
            _require(tier.get("token_basis") == "total_prompt_tokens", f"price record {record_id} token_basis is invalid")
            _require(tier.get("cached_prompt_tokens_included") is True, f"price record {record_id} must include cached prompt tokens")
            _require(tier.get("whole_request_pricing") is True, f"price record {record_id} must use whole-request pricing")
        else:
            _require(threshold is None, f"price record {record_id} threshold requires tier_selection")

        usage_tier = record.get("usage_tier")
        if usage_tier is not None:
            _require(isinstance(usage_tier, dict), f"price record {record_id} usage_tier must be an object")
            _require(
                set(usage_tier) == {"metric", "tier_start", "tier_end", "billing_period", "tier_mode", "usage_scope", "free_allowance"},
                f"price record {record_id} usage_tier has unsupported fields",
            )
            _require(usage_tier.get("metric") in CHARGE_COMPONENTS, f"price record {record_id} usage metric is invalid")
            start = usage_tier.get("tier_start")
            end = usage_tier.get("tier_end")
            _require(isinstance(start, int) and not isinstance(start, bool) and start >= 0, f"price record {record_id} tier_start is invalid")
            _require(end is None or (isinstance(end, int) and not isinstance(end, bool) and end > start), f"price record {record_id} tier_end is invalid")
            _require(usage_tier.get("billing_period") in USAGE_BILLING_PERIODS, f"price record {record_id} billing_period is invalid")
            _require(usage_tier.get("tier_mode") in USAGE_TIER_MODES, f"price record {record_id} tier_mode is invalid")
            _require(usage_tier.get("usage_scope") in USAGE_SCOPES, f"price record {record_id} usage_scope is invalid")
            free_allowance = usage_tier.get("free_allowance")
            _require(isinstance(free_allowance, int) and not isinstance(free_allowance, bool) and free_allowance >= 0, f"price record {record_id} free_allowance is invalid")
            _require(record.get("tier_selection") is None, f"price record {record_id} cannot combine token and usage tiers")
            _require(record.get("calculation_default") is False, f"price record {record_id} usage tiers cannot be scalar defaults")

        charges = record.get("charges")
        _require(isinstance(charges, list) and charges, f"price record {record_id} charges must be non-empty")
        for charge in charges:
            _require(isinstance(charge, dict), f"price record {record_id} charge must be an object")
            _require(
                set(charge) == {"id", "component", "modality", "unit", "amount"},
                f"price record {record_id} charge has unsupported fields",
            )
            charge_id = charge.get("id")
            _require(isinstance(charge_id, str) and charge_id, f"price record {record_id} charge id is invalid")
            _require(charge_id not in charge_ids, f"duplicate charge id {charge_id}")
            charge_ids.add(charge_id)
            _require(charge.get("component") in CHARGE_COMPONENTS, f"charge {charge_id} component is invalid")
            _require(charge.get("modality") in MODALITIES, f"charge {charge_id} modality is invalid")
            _require(charge.get("unit") in UNITS, f"charge {charge_id} unit is invalid")
            _require(_decimal(charge.get("amount"), f"charge {charge_id} amount") >= 0, f"charge {charge_id} amount must be >= 0")

        if usage_tier is not None:
            _require(len(charges) == 1, f"price record {record_id} usage tier requires exactly one charge")
            _require(charges[0]["component"] == usage_tier["metric"], f"price record {record_id} usage metric must match its charge")

        _validate_region_policy(record.get("region_policy"), record_id)
        refs = record.get("source_refs")
        _validate_string_list(refs, f"price record {record_id} source_refs")
        _require(record.get("verification_status") in {"verified", "partially_verified", "unconfirmed_price", "stale", "review_required"}, f"price record {record_id} verification_status is invalid")
        if production:
            _require(record["verification_status"] == "verified", f"production price record {record_id} must be verified")
        for field in ("checked_at", "verified_at"):
            _validate_timestamp(record.get(field), f"price record {record_id} {field}")
        _require(isinstance(record.get("billing_note"), str), f"price record {record_id} billing_note is required")

    usage_records = [record for record in records if record.get("usage_tier") is not None]
    defaults = [record for record in records if record["calculation_default"]]
    if usage_records:
        _require(len(usage_records) == len(records), "usage-tier records cannot coexist with scalar-default price records")
        _require(not defaults, "usage-tier price_records cannot define a scalar calculation default")
        common_fields = ("metric", "billing_period", "tier_mode", "usage_scope", "free_allowance")
        first_usage = usage_records[0]["usage_tier"]
        _require(
            all(record["usage_tier"][field] == first_usage[field] for record in usage_records for field in common_fields),
            "usage-tier records must share one contract",
        )
        ordered = sorted(usage_records, key=lambda record: record["usage_tier"]["tier_start"])
        _require(ordered[0]["usage_tier"]["tier_start"] == 0, "usage tiers must start at zero")
        for left, right in zip(ordered, ordered[1:]):
            _require(left["usage_tier"]["tier_end"] == right["usage_tier"]["tier_start"], "usage tiers contain a gap or overlap")
        _require(ordered[-1]["usage_tier"]["tier_end"] is None, "final usage tier must be unbounded")
        if first_usage["free_allowance"]:
            free = ordered[0]
            _require(free["usage_tier"]["tier_end"] == first_usage["free_allowance"], "free allowance must equal the first tier boundary")
            _require(_decimal(free["charges"][0]["amount"], "free tier amount") == 0, "free allowance tier must have a zero rate")
    else:
        _require(len(defaults) == 1, "price_records require exactly one calculation_default record")

    for index, left in enumerate(records):
        for right in records[index + 1 :]:
            if (
                left["processing_mode"] == right["processing_mode"]
                and left["context_class"] == right["context_class"]
                and left["pricing_status"] == right["pricing_status"]
                and _periods_overlap(left, right)
            ):
                left_region = left["region_policy"]
                right_region = right["region_policy"]
                if _selectors_intersect(
                    {
                        "endpoint_geographies": left_region["endpoint_geographies"],
                        "data_residencies": left_region["data_residencies"],
                    },
                    {
                        "endpoint_geographies": right_region["endpoint_geographies"],
                        "data_residencies": right_region["data_residencies"],
                    },
                ):
                    if left.get("usage_tier") is None or right.get("usage_tier") is None:
                        raise PricingContractError(f"overlapping active price records {left['id']} and {right['id']}")

    by_mode: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if record.get("tier_selection") and record["pricing_status"] == "current":
            by_mode.setdefault(record["processing_mode"], []).append(record)
    complementary = {
        ("less_than", "greater_than_or_equal"),
        ("less_than_or_equal", "greater_than"),
    }
    for mode, mode_records in by_mode.items():
        contexts = {record["context_class"]: record for record in mode_records}
        _require(set(contexts) == CONTEXT_CLASSES and len(mode_records) == 2, f"{mode} tier selection requires exactly short and long records")
        short = contexts["short"]
        long = contexts["long"]
        _require(short["prompt_token_threshold"] == long["prompt_token_threshold"], f"{mode} tier thresholds do not match")
        comparisons = (short["tier_selection"]["comparison"], long["tier_selection"]["comparison"])
        _require(comparisons in complementary, f"{mode} tier comparisons contain a gap or overlap")


def project_v1_compatibility(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Project explicit records into the intentionally lossy V1 compatibility shape."""

    validate_canonical_price_records(records, production=False)
    if records and all(record.get("usage_tier") is not None for record in records):
        return {
            "currency": records[0]["currency"],
            "unit": None,
            "input": None,
            "output": None,
            "cached_input": None,
            "cache_write": None,
            "cache_write_1h": None,
            "batch_input": None,
            "batch_cached_input": None,
            "batch_output": None,
        }

    standard = next(
        (
            record
            for record in records
            if record["processing_mode"] == "standard"
            and record["context_class"] == "short"
            and record["pricing_status"] == "current"
            and record["calculation_default"]
        ),
        None,
    )
    _require(standard is not None, "V1 projection requires the current Standard short calculation default")
    batch = next(
        (
            record
            for record in records
            if record["processing_mode"] == "batch"
            and record["context_class"] == "short"
            and record["pricing_status"] == "current"
        ),
        None,
    )

    def amounts(record: dict[str, Any] | None) -> dict[str, Any]:
        if record is None:
            return {}
        return {charge["component"]: charge["amount"] for charge in record["charges"]}

    standard_amounts = amounts(standard)
    batch_amounts = amounts(batch)
    cache_write = standard_amounts.get("cache_write", standard_amounts.get("cache_write_5m"))
    return {
        "currency": standard["currency"],
        "unit": "1M tokens" if all(charge["unit"] == "per_1m_tokens" for charge in standard["charges"]) else None,
        "input": _json_number(standard_amounts["input"], "V1 input") if "input" in standard_amounts else None,
        "output": _json_number(standard_amounts["output"], "V1 output") if "output" in standard_amounts else None,
        "cached_input": _json_number(standard_amounts["cached_input"], "V1 cached_input") if "cached_input" in standard_amounts else None,
        "cache_write": _json_number(cache_write, "V1 cache_write") if cache_write is not None else None,
        "cache_write_1h": _json_number(standard_amounts["cache_write_1h"], "V1 cache_write_1h") if "cache_write_1h" in standard_amounts else None,
        "batch_input": _json_number(batch_amounts["input"], "V1 batch_input") if "input" in batch_amounts else None,
        "batch_cached_input": _json_number(batch_amounts["cached_input"], "V1 batch_cached_input") if "cached_input" in batch_amounts else None,
        "batch_output": _json_number(batch_amounts["output"], "V1 batch_output") if "output" in batch_amounts else None,
    }


def validate_model_price_records(model: dict[str, Any]) -> None:
    records = model.get("price_records")
    allowances = model.get("conditional_usage_allowances", [])
    if allowances:
        _require(isinstance(allowances, list), "conditional_usage_allowances must be an array")
        allowance_ids: set[str] = set()
        official_urls = set(model.get("official_source_urls") or [model.get("official_source_url")])
        for allowance in allowances:
            required = {"id", "offer_type", "eligibility", "metric", "allowance", "billing_period", "usage_scope", "duration", "region_selector", "source_refs", "verification_status", "checked_at", "verified_at", "note"}
            _require(isinstance(allowance, dict) and set(allowance) == required, "conditional usage allowance has unsupported fields")
            allowance_id = allowance.get("id")
            _require(isinstance(allowance_id, str) and allowance_id and allowance_id not in allowance_ids, "conditional usage allowance id is invalid or duplicate")
            allowance_ids.add(allowance_id)
            _require(allowance.get("offer_type") == "short_term_trial", f"conditional usage allowance {allowance_id} offer_type is invalid")
            eligibility = allowance.get("eligibility")
            _require(isinstance(eligibility, dict) and set(eligibility) == {"customer_status", "account_plan"}, f"conditional usage allowance {allowance_id} eligibility is invalid")
            _require(eligibility.get("customer_status") in {"new_customer", "existing_customer", "any_customer"}, f"conditional usage allowance {allowance_id} customer_status is invalid")
            _require(eligibility.get("account_plan") in {"free", "paid", "any"}, f"conditional usage allowance {allowance_id} account_plan is invalid")
            _require(allowance.get("metric") in CHARGE_COMPONENTS, f"conditional usage allowance {allowance_id} metric is invalid")
            _require(isinstance(allowance.get("allowance"), int) and not isinstance(allowance.get("allowance"), bool) and allowance["allowance"] > 0, f"conditional usage allowance {allowance_id} quantity is invalid")
            _require(allowance.get("billing_period") in USAGE_BILLING_PERIODS, f"conditional usage allowance {allowance_id} billing_period is invalid")
            _require(allowance.get("usage_scope") in USAGE_SCOPES, f"conditional usage allowance {allowance_id} usage_scope is invalid")
            duration = allowance.get("duration")
            _require(isinstance(duration, dict) and set(duration) == {"value", "unit", "starts_on"}, f"conditional usage allowance {allowance_id} duration is invalid")
            _require(isinstance(duration.get("value"), int) and not isinstance(duration.get("value"), bool) and duration["value"] > 0, f"conditional usage allowance {allowance_id} duration value is invalid")
            _require(duration.get("unit") == "month" and duration.get("starts_on") == "offer_activation", f"conditional usage allowance {allowance_id} duration semantics are invalid")
            _validate_selector(allowance.get("region_selector"), f"conditional usage allowance {allowance_id} region_selector")
            refs = allowance.get("source_refs")
            _validate_string_list(refs, f"conditional usage allowance {allowance_id} source_refs")
            _require(set(refs) <= official_urls, f"conditional usage allowance {allowance_id} source_refs absent from official_source_urls")
            _require(allowance.get("verification_status") == "verified", f"conditional usage allowance {allowance_id} must be verified")
            _validate_timestamp(allowance.get("checked_at"), f"conditional usage allowance {allowance_id} checked_at")
            _validate_timestamp(allowance.get("verified_at"), f"conditional usage allowance {allowance_id} verified_at")
            _require(isinstance(allowance.get("note"), str) and allowance["note"], f"conditional usage allowance {allowance_id} note is required")
    if records is None:
        return
    legacy_structures = {
        field for field in ("pricing_tiers", "pricing_periods", "time_pricing", "pricing_components")
        if model.get(field) is not None
    }
    _require(
        not legacy_structures,
        "price_records cannot coexist with legacy structured pricing fields: "
        + ", ".join(sorted(legacy_structures)),
    )
    validate_canonical_price_records(records, production=True)
    official_urls = set(model.get("official_source_urls") or [model.get("official_source_url")])
    used_refs: set[str] = set()
    for record in records:
        used_refs.update(record["source_refs"])
        for rule in record["region_policy"]["availability"].get("rules", []):
            used_refs.update(rule["source_refs"])
        for adjustment in record["region_policy"]["price_adjustments"]:
            used_refs.update(adjustment["source_refs"])
    _require(used_refs <= official_urls, "price_records contain source_refs absent from official_source_urls")
    projected = project_v1_compatibility(records)
    actual = dict(model["pricing"])
    if "batch_cached_input" not in actual:
        projected.pop("batch_cached_input", None)
    _require(actual == projected, "pricing must equal the lossy V1 projection of price_records")


def _camel_selector(selector: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if "endpoint_geographies" in selector:
        result["endpointGeographies"] = list(selector["endpoint_geographies"])
    if "data_residencies" in selector:
        result["dataResidencies"] = list(selector["data_residencies"])
    return result


def normalize_canonical_price_records(
    model_internal_id: str,
    records: list[dict[str, Any]],
    source_ref_resolver: Callable[[str], str] | dict[str, str],
) -> list[dict[str, Any]]:
    """Normalize canonical snake_case records to the lossless Pricing V2 shape."""

    validate_canonical_price_records(records, production=False)

    def resolve(ref: str) -> str:
        return source_ref_resolver(ref) if callable(source_ref_resolver) else source_ref_resolver[ref]

    normalized: list[dict[str, Any]] = []
    for record in records:
        policy = record["region_policy"]
        item: dict[str, Any] = {
            "pricingId": record["id"],
            "modelInternalId": model_internal_id,
            "processingMode": record["processing_mode"],
            "pricingStatus": record["pricing_status"],
            "contextClass": record["context_class"],
            "regionPolicy": "global" if policy["pricing_geography"] == "global_base" else "region_specific",
            "regionSelector": {
                "pricingGeography": policy["pricing_geography"],
                "endpointGeographies": list(policy["endpoint_geographies"]),
                "dataResidencies": list(policy["data_residencies"]),
            },
            "availabilityRules": [
                {
                    "availabilityRuleId": rule["id"],
                    "selector": _camel_selector(rule["selector"]),
                    "availabilityStatus": rule["status"],
                    "reason": rule["reason"],
                    "sourceRefs": sorted(resolve(ref) for ref in rule["source_refs"]),
                }
                for rule in policy["availability"].get("rules", [])
            ],
            "defaultAvailabilityStatus": policy["availability"]["default"],
            "priceAdjustments": [
                {
                    "priceAdjustmentId": adjustment["id"],
                    "selector": _camel_selector(adjustment["selector"]),
                    "operation": adjustment["operation"],
                    "factor": _decimal_string(adjustment["factor"], f"price adjustment {adjustment['id']} factor"),
                    "sourceRefs": sorted(resolve(ref) for ref in adjustment["source_refs"]),
                }
                for adjustment in policy["price_adjustments"]
            ],
            "promptTokenThreshold": record.get("prompt_token_threshold"),
            "effectiveFrom": record.get("effective_from"),
            "effectiveUntil": record.get("effective_until"),
            "currency": record["currency"],
            "charges": [
                {
                    "chargeId": charge["id"],
                    "component": charge["component"],
                    "modality": charge["modality"],
                    "unit": charge["unit"],
                    "amount": _decimal_string(charge["amount"], f"charge {charge['id']} amount"),
                }
                for charge in record["charges"]
            ],
            "sourceRefs": sorted(resolve(ref) for ref in record["source_refs"]),
            "billingNote": record["billing_note"],
            "verificationStatus": record["verification_status"],
            "checkedAt": record["checked_at"],
            "verifiedAt": record["verified_at"],
            "calculationDefault": record["calculation_default"],
        }
        if record.get("tier_selection") is not None:
            tier = record["tier_selection"]
            item["tierSelection"] = {
                "comparison": tier["comparison"],
                "tokenBasis": tier["token_basis"],
                "cachedPromptTokensIncluded": tier["cached_prompt_tokens_included"],
                "wholeRequestPricing": tier["whole_request_pricing"],
            }
        if record.get("usage_tier") is not None:
            tier = record["usage_tier"]
            item["usageTier"] = {
                "metric": tier["metric"],
                "tierStart": tier["tier_start"],
                "tierEnd": tier["tier_end"],
                "billingPeriod": tier["billing_period"],
                "tierMode": tier["tier_mode"],
                "usageScope": tier["usage_scope"],
                "freeAllowance": tier["free_allowance"],
            }
        normalized.append(item)
    return normalized


def normalize_conditional_usage_allowances(
    allowances: list[dict[str, Any]],
    source_ref_resolver: Callable[[str], str] | dict[str, str],
) -> list[dict[str, Any]]:
    """Normalize generic conditional allowances without mixing them into paid tiers."""

    def resolve(ref: str) -> str:
        return source_ref_resolver(ref) if callable(source_ref_resolver) else source_ref_resolver[ref]

    return [
        {
            "allowanceId": allowance["id"],
            "offerType": allowance["offer_type"],
            "eligibility": {
                "customerStatus": allowance["eligibility"]["customer_status"],
                "accountPlan": allowance["eligibility"]["account_plan"],
            },
            "metric": allowance["metric"],
            "allowance": allowance["allowance"],
            "billingPeriod": allowance["billing_period"],
            "usageScope": allowance["usage_scope"],
            "duration": {
                "value": allowance["duration"]["value"],
                "unit": allowance["duration"]["unit"],
                "startsOn": allowance["duration"]["starts_on"],
            },
            "regionSelector": _camel_selector(allowance["region_selector"]),
            "sourceRefs": sorted(resolve(ref) for ref in allowance["source_refs"]),
            "verificationStatus": allowance["verification_status"],
            "checkedAt": allowance["checked_at"],
            "verifiedAt": allowance["verified_at"],
            "note": allowance["note"],
        }
        for allowance in allowances
    ]


def calculate_graduated_usage_cost(
    records: list[dict[str, Any]],
    usage_quantity: int,
    *,
    endpoint_geography: str | None = None,
    data_residency: str | None = None,
) -> Decimal:
    """Calculate a canonical graduated usage-tier contract without provider-specific logic."""

    validate_canonical_price_records(records, production=False)
    _require(
        isinstance(usage_quantity, int) and not isinstance(usage_quantity, bool) and usage_quantity >= 0,
        "usage_quantity must be a non-negative integer",
    )
    _require(
        all(record["usage_tier"]["tier_mode"] == "graduated" for record in records),
        "usage cost calculation currently requires graduated tiers",
    )
    total = Decimal("0")
    for record in sorted(records, key=lambda item: item["usage_tier"]["tier_start"]):
        tier = record["usage_tier"]
        billable = max(
            0,
            min(usage_quantity, tier["tier_end"] if tier["tier_end"] is not None else usage_quantity)
            - tier["tier_start"],
        )
        if billable:
            rate = _decimal(record["charges"][0]["amount"], f"price record {record['id']} amount")
            if endpoint_geography is not None:
                _require(
                    endpoint_geography in record["region_policy"]["endpoint_geographies"],
                    f"endpoint_geography {endpoint_geography} is outside price record {record['id']}",
                )
                residency = data_residency or record["region_policy"]["data_residencies"][0]
                _require(
                    residency in record["region_policy"]["data_residencies"],
                    f"data_residency {residency} is outside price record {record['id']}",
                )
                matches = [
                    adjustment
                    for adjustment in record["region_policy"]["price_adjustments"]
                    if _matches_selector(adjustment["selector"], endpoint_geography, residency)
                ]
                _require(len(matches) <= 1, f"multiple price adjustments match price record {record['id']}")
                if matches:
                    rate *= _decimal(matches[0]["factor"], f"price adjustment {matches[0]['id']} factor")
            quantity = Decimal("1000") if record["charges"][0]["unit"] == "per_1000_pages" else Decimal("1")
            total += Decimal(billable) * rate / quantity
    return total


def calculate_usage_cost_with_allowance(
    records: list[dict[str, Any]],
    usage_quantity: int,
    *,
    allowance: dict[str, Any] | None = None,
    eligible: bool = False,
    endpoint_geography: str | None = None,
    data_residency: str | None = None,
) -> Decimal:
    """Apply an explicitly eligible conditional allowance before paid graduated tiers."""

    billable_usage = usage_quantity
    if allowance is not None and eligible:
        _require(
            allowance["metric"] == records[0]["usage_tier"]["metric"],
            "conditional allowance metric must match usage tiers",
        )
        if endpoint_geography is not None:
            selector = allowance["region_selector"]
            residency = data_residency or records[0]["region_policy"]["data_residencies"][0]
            _require(
                _matches_selector(selector, endpoint_geography, residency),
                "conditional allowance does not cover the requested region",
            )
        billable_usage = max(0, usage_quantity - allowance["allowance"])
    return calculate_graduated_usage_cost(
        records,
        billable_usage,
        endpoint_geography=endpoint_geography,
        data_residency=data_residency,
    )


def validate_normalized_region_contract(
    record: dict[str, Any],
    *,
    known_source_refs: set[str] | None = None,
) -> None:
    """Validate the structured region portion of a normalized V2 record."""

    if record.get("regionSelector") is None:
        return
    record_id = record.get("pricingId", "(unknown)")
    required = {
        "defaultAvailabilityStatus",
        "availabilityRules",
        "priceAdjustments",
        "checkedAt",
        "verifiedAt",
    }
    _require(required <= set(record), f"V2 price record {record_id} has an incomplete region contract")
    region = record["regionSelector"]
    _require(isinstance(region, dict), f"V2 price record {record_id} regionSelector must be an object")
    _require(isinstance(record["availabilityRules"], list), f"V2 price record {record_id} availabilityRules must be a list")
    _require(isinstance(record["priceAdjustments"], list), f"V2 price record {record_id} priceAdjustments must be a list")
    for rule in record["availabilityRules"]:
        _require(isinstance(rule, dict), f"V2 price record {record_id} availability rule must be an object")
        _require(isinstance(rule.get("selector"), dict), f"V2 price record {record_id} availability selector must be an object")
    for adjustment in record["priceAdjustments"]:
        _require(isinstance(adjustment, dict), f"V2 price record {record_id} price adjustment must be an object")
        _require(isinstance(adjustment.get("selector"), dict), f"V2 price record {record_id} adjustment selector must be an object")
    policy = {
        "pricing_geography": region.get("pricingGeography"),
        "endpoint_geographies": region.get("endpointGeographies"),
        "data_residencies": region.get("dataResidencies"),
        "availability": {
            "default": record["defaultAvailabilityStatus"],
            "rules": [
                {
                    "id": rule.get("availabilityRuleId"),
                    "selector": {
                        **(
                            {"endpoint_geographies": rule.get("selector", {}).get("endpointGeographies")}
                            if "endpointGeographies" in rule.get("selector", {})
                            else {}
                        ),
                        **(
                            {"data_residencies": rule.get("selector", {}).get("dataResidencies")}
                            if "dataResidencies" in rule.get("selector", {})
                            else {}
                        ),
                    },
                    "status": rule.get("availabilityStatus"),
                    "reason": rule.get("reason"),
                    "source_refs": rule.get("sourceRefs"),
                }
                for rule in record["availabilityRules"]
            ],
        },
        "price_adjustments": [
            {
                "id": adjustment.get("priceAdjustmentId"),
                "selector": {
                    **(
                        {"endpoint_geographies": adjustment.get("selector", {}).get("endpointGeographies")}
                        if "endpointGeographies" in adjustment.get("selector", {})
                        else {}
                    ),
                    **(
                        {"data_residencies": adjustment.get("selector", {}).get("dataResidencies")}
                        if "dataResidencies" in adjustment.get("selector", {})
                        else {}
                    ),
                },
                "operation": adjustment.get("operation"),
                "factor": adjustment.get("factor"),
                "source_refs": adjustment.get("sourceRefs"),
            }
            for adjustment in record["priceAdjustments"]
        ],
    }
    _validate_region_policy(policy, record_id)
    _validate_timestamp(record["checkedAt"], f"V2 price record {record_id} checkedAt")
    _validate_timestamp(record["verifiedAt"], f"V2 price record {record_id} verifiedAt")
    if known_source_refs is not None:
        nested_refs = {
            ref
            for rule in record["availabilityRules"]
            for ref in rule["sourceRefs"]
        } | {
            ref
            for adjustment in record["priceAdjustments"]
            for ref in adjustment["sourceRefs"]
        }
        _require(nested_refs <= known_source_refs, f"V2 price record {record_id} has orphan region sourceRefs")


def _comparison_matches(value: int, comparison: str, threshold: int) -> bool:
    return {
        "less_than": value < threshold,
        "less_than_or_equal": value <= threshold,
        "greater_than": value > threshold,
        "greater_than_or_equal": value >= threshold,
    }[comparison]


def _v2_selector_matches(selector: dict[str, Any], endpoint_geography: str, data_residency: str) -> bool:
    return (
        endpoint_geography in selector.get("endpointGeographies", [endpoint_geography])
        and data_residency in selector.get("dataResidencies", [data_residency])
    )


def select_price_record(
    records: Iterable[dict[str, Any]],
    *,
    processing_mode: str,
    prompt_tokens: int,
    endpoint_geography: str = "global",
    data_residency: str = "global",
    at: str | date | None = None,
) -> dict[str, Any]:
    """Select and execute one explicit contract; unavailable requests never fall back."""

    _require(processing_mode in PROCESSING_MODES, "requested processing_mode is invalid")
    _require(isinstance(prompt_tokens, int) and not isinstance(prompt_tokens, bool) and prompt_tokens >= 0, "prompt_tokens must be a non-negative integer")
    target_date = date.today() if at is None else (at if isinstance(at, date) else _parse_date(at, "at"))
    assert target_date is not None
    candidates: list[dict[str, Any]] = []
    for record in records:
        if record.get("processingMode") != processing_mode or record.get("pricingStatus", "current") != "current":
            continue
        start = _parse_date(record.get("effectiveFrom"), "effectiveFrom") or date.min
        end = _parse_date(record.get("effectiveUntil"), "effectiveUntil") or date.max
        if not (start <= target_date <= end):
            continue
        tier = record.get("tierSelection")
        if tier is not None and not _comparison_matches(prompt_tokens, tier["comparison"], record["promptTokenThreshold"]):
            continue
        region = record.get("regionSelector", {})
        if not _v2_selector_matches(region, endpoint_geography, data_residency):
            continue
        candidates.append(record)

    if not candidates:
        return {
            "selectionStatus": "unavailable",
            "reason": "No explicit price record matches the requested contract.",
            "requestedProcessingMode": processing_mode,
            "endpointGeography": endpoint_geography,
            "dataResidency": data_residency,
        }
    _require(len(candidates) == 1, "ambiguous price record selection")
    selected = deepcopy(candidates[0])

    matching_rules = [
        rule
        for rule in selected.get("availabilityRules", [])
        if _v2_selector_matches(rule["selector"], endpoint_geography, data_residency)
    ]
    statuses = {rule["availabilityStatus"] for rule in matching_rules}
    _require(len(statuses) <= 1, "contradictory availability rules matched the request")
    status = next(iter(statuses), selected.get("defaultAvailabilityStatus", "available"))
    if status == "unavailable":
        return {
            "selectionStatus": "unavailable",
            "pricingId": selected["pricingId"],
            "reason": "; ".join(rule["reason"] for rule in matching_rules),
            "sourceRefs": sorted({ref for rule in matching_rules for ref in rule["sourceRefs"]}),
            "requestedProcessingMode": processing_mode,
            "endpointGeography": endpoint_geography,
            "dataResidency": data_residency,
        }

    adjustments = [
        adjustment
        for adjustment in selected.get("priceAdjustments", [])
        if _v2_selector_matches(adjustment["selector"], endpoint_geography, data_residency)
    ]
    _require(len(adjustments) <= 1, "multiple price adjustments matched the request")
    if adjustments:
        adjustment = adjustments[0]
        factor = _decimal(adjustment["factor"], "selected price adjustment factor")
        for charge in selected["charges"]:
            charge["amount"] = _decimal_string(
                _decimal(charge["amount"], f"charge {charge['chargeId']} amount") * factor,
                f"adjusted charge {charge['chargeId']} amount",
            )
        selected["appliedPriceAdjustmentIds"] = [adjustment["priceAdjustmentId"]]
    else:
        selected["appliedPriceAdjustmentIds"] = []
    selected["selectionStatus"] = "available"
    return selected
