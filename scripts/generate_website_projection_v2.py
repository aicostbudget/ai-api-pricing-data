from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

try:
    from lib import ROOT
except ModuleNotFoundError:
    from scripts.lib import ROOT

PREVIEW = ROOT / "data" / "pricing-v2-preview"
ARTIFACT = PREVIEW / "generated" / "model-pricing.v2.json"
REPORT = PREVIEW / "phase4a-website-projection-report.json"
SAFE_PRICE_RECONCILIATION = PREVIEW / "phase4a-5-safe-price-record-reconciliation.json"
PROJECTION_ROW_RECONCILIATION = PREVIEW / "phase4a-5-projection-row-reconciliation.json"
UNSAFE_DIFFERENCE_AUDIT = PREVIEW / "phase4a-5-unsafe-difference-audit.json"
CONTEXT_WINDOW_AUDIT = PREVIEW / "phase4a-5-context-window-audit.json"
WEBSITE_DATASET = Path(r"D:\ai-cost-control-tool\aicostguard-english\data\model-pricing.json")

GENERATED_AT = "2026-07-07T00:00:00Z"
DEFAULT_EFFECTIVE_AT = "2026-07-07T00:00:00Z"
PROJECTION_SCHEMA_VERSION = "website-pricing-projection-v2.phase4a"
DEFAULT_SELECTION_RULE = [
    "current_effective_utc",
    "verified",
    "standard",
    "text",
    "default_context_class",
]
EXCLUDED_DEFAULT_INTERNAL_IDS = {"cohere/command-a-plus", "openai/gpt-5", "openai/o3"}
REVIEW_REQUIRED_INTERNAL_IDS = {"openai/gpt-4.1", "openai/gpt-4.1-mini", "openai/gpt-4.1-nano"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(payload, encoding="utf-8", newline="\n")
    try:
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def parse_effective_at(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_decimal(value: str | None) -> int | float | None:
    if value is None:
        return None
    decimal = Decimal(value)
    if decimal == decimal.to_integral_value():
        return int(decimal)
    return float(decimal)


def source_timestamp(source: dict[str, Any], field: str) -> str | None:
    value = source.get(field)
    return value if isinstance(value, str) and value else None


def latest_timestamp(values: list[str | None]) -> str | None:
    present = sorted(value for value in values if value)
    return present[-1] if present else None


def current_effective(price: dict[str, Any], effective_at: datetime) -> bool:
    day = effective_at.date()
    if price["effectiveFrom"] and day < datetime.fromisoformat(price["effectiveFrom"]).date():
        return False
    if price["effectiveUntil"] and day > datetime.fromisoformat(price["effectiveUntil"]).date():
        return False
    return True


def charge_amount(price: dict[str, Any] | None, component: str) -> int | float | None:
    if price is None:
        return None
    for charge in price["charges"]:
        if charge["component"] == component and charge["modality"] == "text" and charge["unit"] == "per_1m_tokens":
            return parse_decimal(charge["amount"])
    return None


def has_text_input_output(price: dict[str, Any]) -> bool:
    return charge_amount(price, "input") is not None and charge_amount(price, "output") is not None


def select_price(
    prices_by_model: dict[str, list[dict[str, Any]]],
    model_internal_id: str,
    effective_at: datetime,
    safe_price_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    candidates = [
        price
        for price in prices_by_model.get(model_internal_id, [])
        if price["processingMode"] == "standard"
        and price["contextClass"] == "short"
        and (price["verificationStatus"] == "verified" or price["pricingId"] in safe_price_by_id)
        and current_effective(price, effective_at)
        and has_text_input_output(price)
    ]
    candidates.sort(
        key=lambda price: (
            price["effectiveFrom"] or "0000-00-00",
            price["calculationDefault"],
            price["pricingId"],
        ),
        reverse=True,
    )
    return candidates[0] if candidates else None


def display_status(identity: dict[str, Any], model: dict[str, Any] | None) -> str:
    lifecycle = identity["lifecycleStatus"]
    release = identity["releaseStage"]
    if lifecycle == "retired":
        return "retired"
    if lifecycle == "deprecated":
        return "legacy"
    if release == "preview":
        return "preview"
    if release == "specialized":
        return "specialized"
    if model and model.get("availability") == "Limited availability":
        return "limited"
    return "latest"


def source_urls(source_refs: list[str], sources_by_id: dict[str, dict[str, Any]]) -> list[str]:
    return [sources_by_id[source_ref]["url"] for source_ref in source_refs if source_ref in sources_by_id]


def price_source_refs(identity: dict[str, Any], price: dict[str, Any] | None) -> list[str]:
    refs = list(identity.get("sourceRefs", []))
    if price is not None:
        refs.extend(price.get("sourceRefs", []))
    return sorted(set(refs))


def website_id_for(identity: dict[str, Any]) -> str:
    website_ids = identity.get("websiteIds") or []
    return website_ids[0] if website_ids else identity["canonicalOfficialId"]


def legacy_grok_history(website_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    grok = next((row for row in website_rows if row.get("id") == "grok-3"), None)
    if not grok:
        return None
    return {
        "inputPrice": grok.get("historicalInputPrice"),
        "cachedInputPrice": None,
        "outputPrice": grok.get("historicalOutputPrice"),
        "contextWindow": grok.get("historicalContextWindow"),
        "pricingBasis": grok.get("historicalPricingBasis"),
        "source": "read_only_website_legacy_metadata",
        "currentCalculationEligible": False,
    }


def projection_row(
    identity: dict[str, Any],
    model_by_id: dict[str, dict[str, Any]],
    prices_by_model: dict[str, list[dict[str, Any]]],
    sources_by_id: dict[str, dict[str, Any]],
    safe_price_by_id: dict[str, dict[str, Any]],
    effective_at: datetime,
    website_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    model = model_by_id.get(identity["internalId"])
    target_internal_id = (
        identity.get("billingModelInternalId")
        or identity.get("aliasTargetInternalId")
        or identity["internalId"]
    )
    selected_price = select_price(prices_by_model, target_internal_id, effective_at, safe_price_by_id)
    blocked_reasons: list[str] = []
    if identity["internalId"] in EXCLUDED_DEFAULT_INTERNAL_IDS:
        blocked_reasons.append("excluded_default_candidate")
    if identity["internalId"] in REVIEW_REQUIRED_INTERNAL_IDS or identity["verificationStatus"] == "review_required":
        blocked_reasons.append("review_required")
    if identity["identityType"] == "historical_reference" and not identity.get("billingModelInternalId"):
        blocked_reasons.append("historical_only")
    if identity["lifecycleStatus"] == "retired" and not identity.get("billingModelInternalId"):
        blocked_reasons.append("retired_non_billing")
    if selected_price is None:
        blocked_reasons.append("missing_verified_current_price")
    default_safe = not blocked_reasons
    refs = price_source_refs(identity, selected_price)
    urls = source_urls(refs, sources_by_id)
    verified_at = None
    if default_safe and selected_price:
        verified_at = safe_price_by_id.get(selected_price["pricingId"], {}).get("phase25VerifiedAt")
        if verified_at is None:
            verified_at = latest_timestamp(
                [source_timestamp(sources_by_id[ref], "verifiedAt") for ref in refs if ref in sources_by_id]
            )
    checked_at = latest_timestamp([source_timestamp(sources_by_id[ref], "checkedAt") for ref in refs if ref in sources_by_id])
    row = {
        "id": website_id_for(identity),
        "provider": identity["providerId"],
        "model": identity["displayName"],
        "inputPrice": charge_amount(selected_price, "input") if default_safe else None,
        "cachedInputPrice": charge_amount(selected_price, "cached_input") if default_safe else None,
        "outputPrice": charge_amount(selected_price, "output") if default_safe else None,
        "status": display_status(identity, model),
        "defaultSafe": default_safe,
        "verificationStatus": "verified" if default_safe else identity["verificationStatus"],
        "verifiedAt": verified_at,
        "checkedAt": checked_at,
        "officialSourceUrl": urls[0] if urls else None,
        "contextWindow": None,
        "contextWindowStatus": "unknown_not_guessed",
        "canonicalInternalId": identity["internalId"],
        "identityType": identity["identityType"],
        "lifecycleStatus": identity["lifecycleStatus"],
        "releaseStage": identity["releaseStage"],
        "availability": identity["availability"],
        "routingBehavior": identity["routingBehavior"],
        "routingDetails": identity["routingDetails"],
        "aliasTargetInternalId": identity.get("aliasTargetInternalId"),
        "redirectTargetInternalId": identity.get("redirectTargetInternalId"),
        "billingModelInternalId": identity.get("billingModelInternalId"),
        "replacementInternalId": identity.get("replacementInternalId"),
        "selectedPriceRecordId": selected_price["pricingId"] if selected_price and default_safe else None,
        "selectedBillingPriceRecordId": selected_price["pricingId"] if selected_price else None,
        "selectedPriceEffectiveFrom": selected_price["effectiveFrom"] if selected_price else None,
        "selectedPriceEffectiveUntil": selected_price["effectiveUntil"] if selected_price else None,
        "defaultPriceSelectionRule": DEFAULT_SELECTION_RULE,
        "blockedFromDefaultReasons": sorted(set(blocked_reasons)),
        "sourceRefs": refs,
        "sourceUrls": urls,
    }
    if identity["internalId"] == "xai/grok-3":
        row["historicalPrice"] = legacy_grok_history(website_rows)
        row["redirectedBilling"] = {
            "redirectTargetInternalId": identity.get("redirectTargetInternalId"),
            "billingModelInternalId": identity.get("billingModelInternalId"),
            "currentBillingPriceRecordId": selected_price["pricingId"] if selected_price else None,
            "historicalPriceCurrentCalculationEligible": False,
        }
    if identity["identityType"] == "alias":
        row["alias"] = {
            "targetInternalId": identity.get("aliasTargetInternalId"),
            "routingBehavior": identity["routingBehavior"],
            "routingDetails": identity["routingDetails"],
        }
    return row


def parity_report(artifact_rows: list[dict[str, Any]], website_rows: list[dict[str, Any]]) -> dict[str, Any]:
    artifact_by_id = {row["id"]: row for row in artifact_rows}
    details = []
    for old in sorted(website_rows, key=lambda row: row["id"]):
        new = artifact_by_id.get(old["id"])
        if new is None:
            classification = "missing_identity"
            reason = "Website model is not present in the Phase 4A projection."
            new_values = None
        else:
            old_values = (old.get("inputPrice"), old.get("cachedInputPrice"), old.get("outputPrice"))
            new_values_tuple = (new.get("inputPrice"), new.get("cachedInputPrice"), new.get("outputPrice"))
            if new["defaultSafe"] is False:
                classification = "unsafe_difference"
                reason = "Projection blocks this row from default calculations."
            elif old_values == new_values_tuple:
                classification = "exact_parity"
                reason = "Legacy Website values match current projection values."
            elif any(value is None for value in new_values_tuple):
                classification = "null_difference"
                reason = "Projection has no current calculation price."
            elif new.get("selectedPriceEffectiveFrom") or new.get("selectedPriceEffectiveUntil"):
                classification = "effective_date_difference"
                reason = "Projection uses effective-date selection."
            else:
                classification = "expected_difference"
                reason = "Projection uses canonical verified pricing."
            new_values = {
                "inputPrice": new.get("inputPrice"),
                "cachedInputPrice": new.get("cachedInputPrice"),
                "outputPrice": new.get("outputPrice"),
            }
        details.append(
            {
                "modelId": old["id"],
                "classification": classification,
                "reason": reason,
                "website": {
                    "inputPrice": old.get("inputPrice"),
                    "cachedInputPrice": old.get("cachedInputPrice"),
                    "outputPrice": old.get("outputPrice"),
                },
                "projection": new_values,
            }
        )
    counts: dict[str, int] = {}
    for item in details:
        counts[item["classification"]] = counts.get(item["classification"], 0) + 1
    return {
        "websiteModelCount": len(website_rows),
        "projectionModelCount": len(artifact_rows),
        "counts": dict(sorted(counts.items())),
        "details": details,
    }


def load_safe_price_rows() -> list[dict[str, Any]]:
    report = read_json(PREVIEW / "phase2-5-default-safe-report.json")
    return [
        row
        for row in report["productionDefaultCandidates"]
        if row["defaultSafe"] is True
    ]


def target_internal_id_for_projection(row: dict[str, Any]) -> str:
    return row.get("billingModelInternalId") or row.get("aliasTargetInternalId") or row["canonicalInternalId"]


def exposure_policy_for(row: dict[str, Any]) -> str:
    if row["defaultSafe"]:
        return "shadow_only"
    if "review_required" in row["blockedFromDefaultReasons"]:
        return "legacy_fallback"
    if row["lifecycleStatus"] == "retired":
        return "warning_only"
    if "excluded_default_candidate" in row["blockedFromDefaultReasons"]:
        return "excluded"
    return "identity_display_only"


def usage_rows_for(model_id: str, phase3_mapping: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in phase3_mapping if row["websiteModelId"] == model_id]


def usage_summary(model_id: str, phase3_mapping: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = usage_rows_for(model_id, phase3_mapping)
    summary = []
    for row in rows:
        consumer = row["websiteConsumer"]
        summary.append(
            {
                "consumer": consumer,
                "usageType": row["websiteConsumer"],
                "defaultPath": consumer.endswith("_default_model") or consumer.startswith("budget_planner_routing_model:"),
                "manualSelectable": "dropdown" in consumer or consumer == "pricing_comparison_model",
                "displayOnly": consumer == "pricing_comparison_model",
                "seoOnly": False,
            }
        )
    return summary


def build_strict_verification_rows(
    identities: list[dict[str, Any]],
    models: list[dict[str, Any]],
    prices_by_model: dict[str, list[dict[str, Any]]],
    sources_by_id: dict[str, dict[str, Any]],
    effective_at: datetime,
    website_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    model_by_id = {model["internalId"]: model for model in models}
    rows = [
        projection_row(identity, model_by_id, prices_by_model, sources_by_id, {}, effective_at, website_rows)
        for identity in identities
    ]
    rows.sort(key=lambda row: (row["provider"], row["id"], row["canonicalInternalId"]))
    return rows


def build_phase45_audits(artifact: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    identities = read_json(PREVIEW / "model-identity-registry.json")
    models = read_json(PREVIEW / "models.json")
    prices = read_json(PREVIEW / "prices.json")
    sources = read_json(PREVIEW / "sources.json")
    dispositions = read_json(PREVIEW / "candidate-disposition-map.json")
    phase3_mapping = read_json(PREVIEW / "phase3-integration-mapping.json")
    website_rows = read_json(WEBSITE_DATASET)
    safe_rows = load_safe_price_rows()
    safe_price_by_id = {row["pricingId"]: row for row in safe_rows}
    price_by_id = {row["pricingId"]: row for row in prices}
    prices_by_model: dict[str, list[dict[str, Any]]] = {}
    for price in prices:
        prices_by_model.setdefault(price["modelInternalId"], []).append(price)
    source_by_id = {source["sourceId"]: source for source in sources}
    projection_rows = artifact["models"]
    projection_by_internal_id = {row["canonicalInternalId"]: row for row in projection_rows}
    projection_by_selected_price = {}
    for row in projection_rows:
        for field in ("selectedPriceRecordId", "selectedBillingPriceRecordId"):
            pricing_id = row.get(field)
            if pricing_id:
                projection_by_selected_price.setdefault(pricing_id, []).append(row)
    safe_reconciliation_rows = []
    for safe in safe_rows:
        price = price_by_id[safe["pricingId"]]
        matched_rows = projection_by_selected_price.get(safe["pricingId"], [])
        canonical_row = projection_by_internal_id.get(safe["modelInternalId"])
        omitted = not matched_rows
        omission_reason = None
        if omitted:
            if canonical_row is None:
                omission_reason = "model_identity_not_projected"
            elif canonical_row.get("selectedBillingPriceRecordId") != safe["pricingId"]:
                omission_reason = "superseded_by_projection_selection_rule"
            else:
                omission_reason = "unclassified"
        safe_reconciliation_rows.append(
            {
                "pricingId": safe["pricingId"],
                "modelInternalId": safe["modelInternalId"],
                "processingMode": price["processingMode"],
                "contextClass": price["contextClass"],
                "promptTokenThreshold": price["promptTokenThreshold"],
                "effectiveFrom": price["effectiveFrom"],
                "effectiveUntil": price["effectiveUntil"],
                "projectionRowId": canonical_row["id"] if canonical_row else None,
                "projectionRowIds": [row["id"] for row in matched_rows],
                "selectedAsCurrentDefault": bool(matched_rows),
                "mergedWithOtherPriceRecord": False,
                "mergeReason": None,
                "omittedFromProjection": omitted,
                "omissionReason": omission_reason,
            }
        )
    safe_stats = {
        "safePriceRecordsInput": len(safe_rows),
        "mappedToProjection": sum(1 for row in safe_reconciliation_rows if row["selectedAsCurrentDefault"]),
        "mergedIntoSameIdentity": sum(1 for row in safe_reconciliation_rows if row["mergedWithOtherPriceRecord"]),
        "futureNonEffective": sum(1 for row in safe_reconciliation_rows if row["omissionReason"] == "future_non_effective"),
        "omitted": sum(1 for row in safe_reconciliation_rows if row["omittedFromProjection"]),
        "unexplained": sum(1 for row in safe_reconciliation_rows if row["omissionReason"] == "unclassified"),
    }
    safe_reconciliation = {
        "generatedAt": GENERATED_AT,
        "stats": safe_stats,
        "rows": safe_reconciliation_rows,
    }

    row_reconciliation_rows = []
    for row in projection_rows:
        identity_type = row["identityType"]
        if identity_type == "historical_reference" and row.get("redirectTargetInternalId"):
            classification = "redirecting_identity"
        elif identity_type in {"canonical_model", "alias", "historical_reference"}:
            classification = identity_type
        else:
            classification = "other"
        row_reconciliation_rows.append(
            {
                "projectionRowId": row["id"],
                "canonicalInternalId": row["canonicalInternalId"],
                "sourceIdentityType": identity_type,
                "classification": classification,
                "aliasTargetInternalId": row.get("aliasTargetInternalId"),
                "redirectTargetInternalId": row.get("redirectTargetInternalId"),
                "billingModelInternalId": row.get("billingModelInternalId"),
                "status": row["status"],
                "defaultSafe": row["defaultSafe"],
                "reason": "canonical model row" if classification == "canonical_model" else "alias or redirect identity retained for compatibility",
            }
        )
    row_counts = {
        key: sum(1 for row in row_reconciliation_rows if row["classification"] == key)
        for key in ("canonical_model", "alias", "historical_reference", "redirecting_identity", "other")
    }
    row_reconciliation = {
        "generatedAt": GENERATED_AT,
        "normalizedCanonicalIdentities": len(models),
        "projectionRows": len(projection_rows),
        "counts": row_counts,
        "formula": "35 canonical_model + 2 alias + 1 redirecting_identity = 38 projection rows",
        "rows": row_reconciliation_rows,
    }

    strict_rows = build_strict_verification_rows(
        identities,
        models,
        prices_by_model,
        source_by_id,
        parse_effective_at(artifact["effectiveAt"]),
        website_rows,
    )
    strict_parity = parity_report(strict_rows, website_rows)
    current_unsafe_details = [item for item in report["parity"]["details"] if item["classification"] == "unsafe_difference"]
    strict_unsafe_details = [item for item in strict_parity["details"] if item["classification"] == "unsafe_difference"]
    unsafe_rows = []
    current_unsafe_ids = {item["modelId"] for item in current_unsafe_details}
    artifact_by_id = {row["id"]: row for row in projection_rows}
    website_by_id = {row["id"]: row for row in website_rows}
    for detail in strict_unsafe_details:
        projected = artifact_by_id.get(detail["modelId"])
        old = website_by_id[detail["modelId"]]
        usages = usage_summary(detail["modelId"], phase3_mapping)
        resolved_by_fix = detail["modelId"] not in current_unsafe_ids
        if resolved_by_fix:
            severity = "informational"
            action = "safe_shadow_only"
            reason = "Phase 4A.5 maps the Phase 2.5/2.6 approved safe PriceRecord into the projection."
        elif projected and "review_required" in projected["blockedFromDefaultReasons"]:
            severity = "warning"
            action = "keep_legacy_temporarily"
            reason = "Review-required pricing remains unsafe for v2 defaults."
        elif projected and projected["lifecycleStatus"] == "retired":
            severity = "warning"
            action = "adapter_warning"
            reason = "Retired model is display-only or warning-only in v2."
        else:
            severity = "warning"
            action = "adapter_warning"
            reason = "Projection blocks this legacy Website price from v2 defaults."
        unsafe_rows.append(
            {
                "websiteModelId": detail["modelId"],
                "canonicalInternalId": projected["canonicalInternalId"] if projected else None,
                "websiteOldPrice": detail["website"],
                "projectionPrice": detail["projection"] if not resolved_by_fix else {
                    "inputPrice": projected["inputPrice"],
                    "cachedInputPrice": projected["cachedInputPrice"],
                    "outputPrice": projected["outputPrice"],
                },
                "websiteOldStatus": old.get("status"),
                "projectionStatus": projected["status"] if projected else None,
                "defaultSafe": projected["defaultSafe"] if projected else False,
                "verificationStatus": projected["verificationStatus"] if projected else "missing",
                "differenceReason": reason,
                "websiteConsumerUsage": usages,
                "calculatorExposure": any("calculator" in usage["consumer"] or "homepage_estimator" in usage["consumer"] for usage in usages),
                "defaultRecommendationExposure": any(usage["defaultPath"] for usage in usages),
                "severity": severity,
                "recommendedPhase4BAction": action,
                "resolvedByPhase4A5": resolved_by_fix,
            }
        )
    unsafe_summary = {
        severity: sum(1 for row in unsafe_rows if row["severity"] == severity)
        for severity in ("informational", "warning", "high", "blocker")
    }
    null_difference_rows = []
    for detail in report["parity"]["details"]:
        if detail["classification"] != "null_difference":
            continue
        projected = artifact_by_id[detail["modelId"]]
        old = website_by_id[detail["modelId"]]
        null_difference_rows.append(
            {
                "websiteModelId": detail["modelId"],
                "canonicalInternalId": projected["canonicalInternalId"],
                "whyProjectionNull": "cachedInputPrice is null because the canonical selected PriceRecord has no verified cached_input charge.",
                "websiteHasOldPrice": old.get("inputPrice") is not None or old.get("outputPrice") is not None,
                "oldPriceVerified": old.get("verificationStatus") == "verified",
                "shouldContinueLegacyTemporarily": False,
                "shouldWarning": projected["id"] == "grok-3",
                "shouldExclude": False,
            }
        )
    unsafe_audit = {
        "generatedAt": GENERATED_AT,
        "beforePhase4A5UnsafeDifferenceCount": len(strict_unsafe_details),
        "currentUnsafeDifferenceCount": len(current_unsafe_details),
        "severitySummary": unsafe_summary,
        "blockerUnsafeDifferences": [row for row in unsafe_rows if row["severity"] == "blocker"],
        "unsafeDifferenceRows": unsafe_rows,
        "nullDifferenceRows": null_difference_rows,
    }

    canonical_context_keys = {"contextWindow", "context_window", "contextWindowTokens", "context_window_tokens"}
    context_rows = []
    model_by_id = {model["internalId"]: model for model in models}
    identity_by_id = {identity["internalId"]: identity for identity in identities}
    for row in projection_rows:
        model = model_by_id.get(row["canonicalInternalId"], {})
        identity = identity_by_id.get(row["canonicalInternalId"], {})
        canonical_value = None
        for container in (model, identity):
            for key in canonical_context_keys:
                if key in container and container[key] is not None:
                    canonical_value = container[key]
        context_rows.append(
            {
                "modelInternalId": row["canonicalInternalId"],
                "canonicalContextWindow": canonical_value,
                "canonicalVerificationStatus": "verified" if canonical_value is not None else "not_present",
                "officialSourceAvailable": bool(row["sourceRefs"]),
                "projectedContextWindow": row["contextWindow"],
                "reason": "Canonical V2 has no verified context-window field for this identity; projection leaves null rather than copying Website editorial text.",
            }
        )
    context_audit = {
        "generatedAt": GENERATED_AT,
        "contextWindowRows": len(context_rows),
        "verifiedCanonicalContextWindowCount": sum(1 for row in context_rows if row["canonicalContextWindow"] is not None),
        "projectedNullCount": sum(1 for row in context_rows if row["projectedContextWindow"] is None),
        "rows": context_rows,
    }

    default_safe_review = []
    for row in projection_rows:
        if not row["defaultSafe"]:
            continue
        price_id = row["selectedPriceRecordId"]
        price = price_by_id[price_id]
        safe = safe_price_by_id.get(price_id)
        default_safe_review.append(
            {
                "projectionRowId": row["id"],
                "canonicalInternalId": row["canonicalInternalId"],
                "selectedPriceRecordId": price_id,
                "currentEffective": current_effective(price, parse_effective_at(artifact["effectiveAt"])),
                "verified": row["verificationStatus"] == "verified" and row["verifiedAt"] is not None,
                "completeEvidence": bool(safe is None or safe["afterEvidenceCompleteness"] == "complete"),
                "standardDefaultSemantics": price["processingMode"] == "standard" and price["contextClass"] == "short",
                "textCompatible": has_text_input_output(price),
                "noUnresolvedConflict": row["canonicalInternalId"] not in REVIEW_REQUIRED_INTERNAL_IDS,
                "noFutureOnlyPrice": current_effective(price, parse_effective_at(artifact["effectiveAt"])),
                "noHistoricalOnlyPrice": not (row["identityType"] == "historical_reference" and not row.get("billingModelInternalId")),
            }
        )
    unsafe_null_policy = [
        {
            "projectionRowId": row["id"],
            "canonicalInternalId": row["canonicalInternalId"],
            "defaultSafe": row["defaultSafe"],
            "hasNullPrice": row["inputPrice"] is None or row["outputPrice"] is None,
            "phase4BPolicy": exposure_policy_for(row),
        }
        for row in projection_rows
        if not row["defaultSafe"] or row["inputPrice"] is None or row["outputPrice"] is None
    ]
    consumer_exposure = [
        {
            "projectionRowId": row["id"],
            "canonicalInternalId": row["canonicalInternalId"],
            "defaultSafe": row["defaultSafe"],
            "policy": exposure_policy_for(row),
            "usages": usage_summary(row["id"], phase3_mapping),
        }
        for row in projection_rows
    ]

    readiness = {
        "safeToEnterPhase4B": (
            safe_stats["unexplained"] == 0
            and len(row_reconciliation_rows) == 38
            and len(unsafe_audit["blockerUnsafeDifferences"]) == 0
            and context_audit["projectedNullCount"] == context_audit["contextWindowRows"]
            and all(all(value is True for key, value in item.items() if key not in {"projectionRowId", "canonicalInternalId", "selectedPriceRecordId"}) for item in default_safe_review)
            and all(item["phase4BPolicy"] != "shadow_only" or item["defaultSafe"] for item in unsafe_null_policy)
        ),
        "defaultSafeReview": default_safe_review,
        "unsafeNullRowPolicies": unsafe_null_policy,
        "websiteConsumerExposure": consumer_exposure,
        "dispositionCounts": {
            key: sum(1 for item in dispositions if item["disposition"] == key)
            for key in sorted({item["disposition"] for item in dispositions})
        },
    }
    return {
        "safe_reconciliation": safe_reconciliation,
        "row_reconciliation": row_reconciliation,
        "unsafe_audit": unsafe_audit,
        "context_audit": context_audit,
        "phase45_readiness": readiness,
    }


def build_projection(effective_at_value: str = DEFAULT_EFFECTIVE_AT) -> tuple[dict[str, Any], dict[str, Any]]:
    schema_version = read_json(PREVIEW / "schema-version.json")
    identities = read_json(PREVIEW / "model-identity-registry.json")
    models = read_json(PREVIEW / "models.json")
    prices = read_json(PREVIEW / "prices.json")
    sources = read_json(PREVIEW / "sources.json")
    contract = read_json(PREVIEW / "phase3-website-projection-contract.json")
    phase35 = read_json(PREVIEW / "phase3-5-readiness.json")
    website_rows = read_json(WEBSITE_DATASET)
    safe_price_by_id = {row["pricingId"]: row for row in load_safe_price_rows()}
    effective_at = parse_effective_at(effective_at_value)
    model_by_id = {model["internalId"]: model for model in models}
    prices_by_model: dict[str, list[dict[str, Any]]] = {}
    for price in prices:
        prices_by_model.setdefault(price["modelInternalId"], []).append(price)
    sources_by_id = {source["sourceId"]: source for source in sources}
    rows = [
        projection_row(identity, model_by_id, prices_by_model, sources_by_id, safe_price_by_id, effective_at, website_rows)
        for identity in identities
    ]
    rows.sort(key=lambda row: (row["provider"], row["id"], row["canonicalInternalId"]))
    artifact = {
        "schemaVersion": PROJECTION_SCHEMA_VERSION,
        "generatedAt": GENERATED_AT,
        "generatedAtPolicy": "deterministic static timestamp for reviewable repo-local artifacts",
        "effectiveAt": effective_at.isoformat().replace("+00:00", "Z"),
        "effectiveTimezone": "UTC",
        "sourceDatasetVersion": schema_version["schemaVersion"],
        "sourceDatasetSchema": schema_version["schemaName"],
        "contractName": contract["contractName"],
        "requiredFields": contract["requiredFields"],
        "defaultSafePolicy": contract["defaultSafePolicy"],
        "noRuntimeNetworkDependency": True,
        "failureBehavior": {
            "atomicWrite": True,
            "overwritePreviousValidArtifactOnFailure": False,
            "nonZeroExitOnFailure": True,
            "partialJson": "not_written",
            "publicV1Mutation": "forbidden",
        },
        "models": rows,
    }
    report = {
        "generatedAt": GENERATED_AT,
        "phase": "Phase 4A Production-Ready Website Projection",
        "artifactPath": str(ARTIFACT.relative_to(ROOT)).replace("\\", "/"),
        "projectionModelCount": len(rows),
        "defaultSafeModelCount": sum(1 for row in rows if row["defaultSafe"]),
        "unsafeIdentityCount": sum(1 for row in rows if not row["defaultSafe"]),
        "nullPriceCount": sum(1 for row in rows if row["inputPrice"] is None or row["outputPrice"] is None),
        "phase35Readiness": phase35["implementationReadiness"],
        "runtimeNetworkDependency": "none",
        "parity": parity_report(rows, website_rows),
    }
    validate_projection(artifact, report)
    return artifact, report


def validate_projection(artifact: dict[str, Any], report: dict[str, Any]) -> None:
    required = set(artifact["requiredFields"])
    for row in artifact["models"]:
        missing = sorted(field for field in required if field not in row)
        if missing:
            raise ValueError(f"projection row {row.get('id')} missing required fields {missing}")
        if row["contextWindow"] is not None:
            raise ValueError(f"contextWindow must not be guessed: {row['id']}")
        if row["verificationStatus"] in {"review_required", "unconfirmed_price"} and row["verifiedAt"] is not None:
            raise ValueError(f"review/unconfirmed row must not have verifiedAt: {row['id']}")
        if row["defaultSafe"] is False and any(row[field] is not None for field in ("inputPrice", "cachedInputPrice", "outputPrice")):
            raise ValueError(f"unsafe row exposes calculation price: {row['id']}")
    by_internal_id = {row["canonicalInternalId"]: row for row in artifact["models"]}
    for internal_id in REVIEW_REQUIRED_INTERNAL_IDS | EXCLUDED_DEFAULT_INTERNAL_IDS:
        row = by_internal_id[internal_id]
        if row["defaultSafe"] or row["inputPrice"] is not None or row["outputPrice"] is not None:
            raise ValueError(f"unsafe default candidate exposed: {internal_id}")
    grok = by_internal_id["xai/grok-3"]
    if grok["status"] == "latest" or grok["lifecycleStatus"] != "retired":
        raise ValueError("grok-3 must project as retired")
    if grok["redirectedBilling"]["billingModelInternalId"] != "xai/grok-4.3":
        raise ValueError("grok-3 billing model mismatch")
    if grok["historicalPrice"]["currentCalculationEligible"] is not False:
        raise ValueError("grok-3 historical price must be isolated")
    if artifact["noRuntimeNetworkDependency"] is not True:
        raise ValueError("projection must not require runtime network dependency")
    if report["projectionModelCount"] != len(artifact["models"]):
        raise ValueError("projection report count mismatch")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the Phase 4A Website pricing projection.")
    parser.add_argument("--effective-at", default=DEFAULT_EFFECTIVE_AT)
    parser.add_argument("--artifact", type=Path, default=ARTIFACT)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()
    artifact, report = build_projection(args.effective_at)
    audits = build_phase45_audits(artifact, report)
    atomic_write_json(args.artifact, artifact)
    atomic_write_json(args.report, report)
    atomic_write_json(SAFE_PRICE_RECONCILIATION, audits["safe_reconciliation"])
    atomic_write_json(PROJECTION_ROW_RECONCILIATION, audits["row_reconciliation"])
    atomic_write_json(UNSAFE_DIFFERENCE_AUDIT, audits["unsafe_audit"])
    atomic_write_json(CONTEXT_WINDOW_AUDIT, audits["context_audit"])
    print(f"generated website projection: {args.artifact}")
    print(f"generated projection report: {args.report}")


if __name__ == "__main__":
    main()
