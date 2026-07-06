from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

try:
    from lib import CANONICAL, ROOT
except ModuleNotFoundError:
    from scripts.lib import CANONICAL, ROOT

PREVIEW = ROOT / "data" / "pricing-v2-preview"
GENERATED = PREVIEW / "generated"
WEBSITE_DATASET = Path(r"D:\ai-cost-control-tool\aicostguard-english\data\model-pricing.json")

PROVIDER_SLUGS = {
    "OpenAI": "openai",
    "Anthropic": "anthropic",
    "Google": "google-gemini",
    "Google Gemini": "google-gemini",
    "xAI": "xai",
    "DeepSeek": "deepseek",
    "Mistral AI": "mistral-ai",
    "Cohere": "cohere",
}

PROVIDER_DISPLAY = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google-gemini": "Google",
    "xai": "xAI",
    "deepseek": "DeepSeek",
    "mistral-ai": "Mistral AI",
    "cohere": "Cohere",
}

OFFICIAL_DOMAINS = {
    "openai": ("platform.openai.com", "developers.openai.com"),
    "anthropic": ("docs.anthropic.com", "platform.claude.com"),
    "google-gemini": ("ai.google.dev",),
    "xai": ("docs.x.ai",),
    "deepseek": ("api-docs.deepseek.com",),
    "mistral-ai": ("mistral.ai",),
    "cohere": ("cohere.com", "docs.cohere.com"),
}

IDENTITY_COLLAPSE = {
    ("deepseek", "deepseek-chat"): {
        "identityType": "alias",
        "target": "deepseek/deepseek-v4-flash",
        "routingBehavior": "compatibility_alias_non_thinking_until_2026-07-24T15:59:00Z",
        "routingDetails": {
            "mode": "non_thinking",
            "effectiveUntil": "2026-07-24T15:59:00Z",
            "semantics": "Compatibility alias for non-thinking mode.",
        },
    },
    ("deepseek", "deepseek-reasoner"): {
        "identityType": "alias",
        "target": "deepseek/deepseek-v4-flash",
        "routingBehavior": "compatibility_alias_thinking_until_2026-07-24T15:59:00Z",
        "routingDetails": {
            "mode": "thinking",
            "effectiveUntil": "2026-07-24T15:59:00Z",
            "semantics": "Compatibility alias for thinking mode.",
        },
    },
    ("xai", "grok-3"): {
        "identityType": "historical_reference",
        "target": "xai/grok-4.3",
        "routingBehavior": "retired_redirects_to_grok-4.3_current_billing",
        "routingDetails": {
            "redirectTargetInternalId": "xai/grok-4.3",
            "billingModelInternalId": "xai/grok-4.3",
            "replacementInternalId": None,
            "semantics": "Retired slug is retained for history and redirects to Grok 4.3 for current billing.",
        },
    },
}

REVIEW_REQUIRED_IDS = {
    ("openai", "gpt-4.1"),
    ("openai", "gpt-4.1-mini"),
    ("openai", "gpt-4.1-nano"),
}

MERGED_DUPLICATES = {
    ("anthropic", "claude-sonnet-5-intro"): {
        "target": "anthropic/claude-sonnet-5",
        "reason": "Introductory pricing period is modeled as a PriceRecord on anthropic/claude-sonnet-5; no independent callable official model identity is confirmed in current sources.",
    },
}

PHASE25_OFFICIAL_COMPLETION = {
    "price:anthropic/claude-fable-5:standard:short:website-preview": "https://platform.claude.com/docs/en/about-claude/pricing",
    "price:anthropic/claude-mythos-5:standard:short:website-preview": "https://platform.claude.com/docs/en/about-claude/pricing",
    "price:anthropic/claude-opus-4.1:standard:short:website-preview": "https://platform.claude.com/docs/en/about-claude/pricing",
    "price:cohere/aya-expanse-32b:standard:short:current": "https://cohere.com/pricing",
    "price:cohere/command-r-plus-08-2024:standard:short:current": "https://cohere.com/pricing",
    "price:google-gemini/gemini-3-flash-preview:standard:short:website-preview": "https://ai.google.dev/gemini-api/docs/pricing",
    "price:google-gemini/gemini-3.1-flash-lite:standard:short:website-preview": "https://ai.google.dev/gemini-api/docs/pricing",
    "price:mistral-ai/mistral-large:standard:short:current": "https://mistral.ai/pricing/",
    "price:openai/chatgpt-chat-latest:standard:short:website-preview": "https://developers.openai.com/api/docs/pricing",
    "price:openai/gpt-5.3-codex:standard:short:website-preview": "https://developers.openai.com/api/docs/pricing",
    "price:openai/gpt-5.4:standard:short:website-preview": "https://developers.openai.com/api/docs/pricing",
    "price:openai/gpt-5.4-nano:standard:short:website-preview": "https://developers.openai.com/api/docs/pricing",
    "price:openai/gpt-5.4-pro:standard:short:website-preview": "https://developers.openai.com/api/docs/pricing",
    "price:openai/gpt-5.5-pro:standard:short:website-preview": "https://developers.openai.com/api/docs/pricing",
    "price:xai/grok-build-0.1:standard:short:website-preview": "https://docs.x.ai/developers/models",
}

PHASE26_OFFICIAL_COMPLETION = {
    "price:google-gemini/gemini-3.1-pro-preview:standard:short:website-preview": "https://ai.google.dev/gemini-api/docs/pricing",
    "price:google-gemini/gemini-3.5-flash:standard:short:website-preview": "https://ai.google.dev/gemini-api/docs/pricing",
}

PHASE26_EXCLUDED_DEFAULT_MODELS = {
    "cohere/command-a-plus": "official pricing page confirms token-based billing but does not expose a complete current Command A+ pay-as-you-go token price.",
    "openai/gpt-5": "current OpenAI API pricing page does not list gpt-5 current API pricing as a callable default model.",
    "openai/o3": "current OpenAI API pricing page lists o3-deep-research, not a current o3 default API price with cached-input semantics.",
}

PHASE26_BLOCKER_MODEL_IDS = {
    "cohere/command-a-plus",
    "google-gemini/gemini-3.1-pro-preview",
    "google-gemini/gemini-3.5-flash",
    "openai/gpt-5",
    "openai/o3",
}

PHASE26_EXTRA_SOURCE_URLS = {
    ("cohere", "https://docs.cohere.com/docs/models"): {
        "sourceType": "official_model_page",
        "title": "Cohere official model documentation",
        "supports": ["models"],
        "verificationStatus": "verified",
    },
    ("cohere", "https://docs.cohere.com/docs/how-does-cohere-pricing-work"): {
        "sourceType": "official_pricing_page",
        "title": "Cohere official pricing methodology",
        "supports": ["pricing"],
        "verificationStatus": "verified",
    },
    ("openai", "https://developers.openai.com/api/docs/pricing"): {
        "sourceType": "official_pricing_page",
        "title": "OpenAI official API pricing",
        "supports": ["pricing"],
        "verificationStatus": "verified",
    },
    ("openai", "https://developers.openai.com/api/docs/models"): {
        "sourceType": "official_model_page",
        "title": "OpenAI official API models",
        "supports": ["models"],
        "verificationStatus": "verified",
    },
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_with_retry(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def write_text_with_retry(path: Path, value: str) -> None:
    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == value:
                return
        except PermissionError:
            pass
    for attempt in range(10):
        try:
            path.write_text(value, encoding="utf-8")
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.1)


def evidence_completeness(price: dict[str, Any], source_by_id: dict[str, dict[str, Any]]) -> str:
    sources = [source_by_id.get(ref) for ref in price.get("sourceRefs", [])]
    if not sources or any(source is None for source in sources):
        return "insufficient"
    if price["verificationStatus"] == "verified":
        if any(
            source["verificationStatus"] == "verified"
            and source.get("checkedAt")
            and source.get("verifiedAt")
            and source.get("officialProviderDomain")
            and source["officialProviderDomain"] in source["url"]
            for source in sources
        ):
            return "complete"
        return "insufficient"
    if any(source.get("officialProviderDomain") for source in sources):
        return "partial"
    return "insufficient"


def build_phase2_evidence_matrix(
    prices: list[dict[str, Any]], sources: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    source_by_id = {source["sourceId"]: source for source in sources}
    matrix = []
    for price in prices:
        resolved_sources = [source_by_id[ref] for ref in price["sourceRefs"] if ref in source_by_id]
        matrix.append(
            {
                "pricingId": price["pricingId"],
                "modelInternalId": price["modelInternalId"],
                "verificationStatus": price["verificationStatus"],
                "sourceRefs": price["sourceRefs"],
                "officialProviderDomain": sorted(
                    {source["officialProviderDomain"] for source in resolved_sources}
                ),
                "sourceType": sorted({source["sourceType"] for source in resolved_sources}),
                "verifiedAt": sorted({source["verifiedAt"] for source in resolved_sources if source.get("verifiedAt")}),
                "priceComponents": [
                    {
                        "chargeId": charge["chargeId"],
                        "component": charge["component"],
                        "modality": charge["modality"],
                        "unit": charge["unit"],
                        "amount": charge["amount"],
                    }
                    for charge in price["charges"]
                ],
                "evidenceCompleteness": evidence_completeness(price, source_by_id),
            }
        )
    return matrix


def build_phase2_conflict_report(
    report: dict[str, Any], identities: list[dict[str, Any]], matrix: list[dict[str, Any]]
) -> dict[str, Any]:
    gpt_family = ["openai/gpt-4.1", "openai/gpt-4.1-mini", "openai/gpt-4.1-nano"]
    identity_by_id = {identity["internalId"]: identity for identity in identities}
    insufficient_verified = [
        row["pricingId"]
        for row in matrix
        if row["verificationStatus"] == "verified" and row["evidenceCompleteness"] != "complete"
    ]
    return {
        "generatedAt": report["generatedAt"],
        "scope": "phase2_official_verification_preview_only",
        "unresolvedIdentitiesBefore": report["unresolvedIdentities"],
        "unresolvedIdentitiesAfter": [
            internal_id
            for internal_id in gpt_family
            if identity_by_id[internal_id]["verificationStatus"] == "review_required"
        ],
        "pricingConflictsBefore": report["pricingConflicts"],
        "pricingConflictsAfter": [
            {"internalId": internal_id, "resolution": "remain_review_required"}
            for internal_id in gpt_family
            if identity_by_id[internal_id]["verificationStatus"] == "review_required"
        ],
        "verificationUpgrades": [],
        "verificationDowngrades": [],
        "provenanceConflictsAfter": insufficient_verified,
        "gpt4_1Family": {
            "finalStatus": "review_required",
            "safeDefaultCalculationPrice": False,
            "reason": "Official OpenAI pricing/model pages did not provide complete current price evidence for the whole GPT-4.1 family during Phase 2 review; Public V1 and Website values are not accepted as final proof.",
            "officialEvidence": [
                "https://developers.openai.com/api/docs/pricing",
                "https://developers.openai.com/api/docs/models",
                "https://developers.openai.com/api/docs/deprecations",
            ],
        },
        "grok3": {
            "identityType": "historical_reference",
            "lifecycleStatus": "retired",
            "routingBehavior": "redirect",
            "redirectTargetInternalId": "xai/grok-4.3",
            "replacementInternalId": None,
            "billingModelInternalId": "xai/grok-4.3",
            "phase2Resolution": "Retain redirect metadata and keep replacement null; do not infer replacement from redirect.",
            "officialEvidence": ["https://docs.x.ai/developers/migration/may-15-retirement"],
        },
        "deepseekAliases": {
            "finalStatus": "verified",
            "target": "deepseek/deepseek-v4-flash",
            "effectiveUntil": "2026-07-24T15:59:00Z",
            "semanticPreservation": "routingDetails.mode preserves non_thinking for deepseek-chat and thinking for deepseek-reasoner.",
            "officialEvidence": ["https://api-docs.deepseek.com/quick_start/pricing"],
        },
        "claudeSonnet5": {
            "finalStatus": "verified",
            "identityHandling": "single canonical identity anthropic/claude-sonnet-5; introductory and standard prices are separate PriceRecords.",
            "introductoryEffectiveUntil": "2026-08-31",
            "standardEffectiveFrom": "2026-09-01",
            "officialEvidence": ["https://platform.claude.com/docs/en/about-claude/pricing"],
        },
        "expectedDifferences": report["websiteCompatibilityPreviewParity"]["expected_difference"],
        "unresolvedDifferences": [
            {"internalId": internal_id, "resolution": "remain_review_required"} for internal_id in gpt_family
        ],
    }


def build_phase2_cutover_readiness(
    report: dict[str, Any], conflict_report: dict[str, Any], matrix: list[dict[str, Any]]
) -> dict[str, Any]:
    partial_or_insufficient = [
        row["pricingId"] for row in matrix if row["evidenceCompleteness"] != "complete"
    ]
    unresolved = conflict_report["unresolvedIdentitiesAfter"]
    ready = not unresolved and not partial_or_insufficient
    return {
        "generatedAt": report["generatedAt"],
        "overall": "blocked" if not ready else "ready",
        "productionMigration": "not_allowed_in_phase2",
        "phase2SafeToCommitPreview": True,
        "safeToEnterWebsiteIntegrationPlanning": False,
        "gates": {
            "identity": "conditional" if unresolved else "ready",
            "pricing": "blocked" if unresolved else "conditional",
            "provenance": "conditional" if partial_or_insufficient else "ready",
            "websiteCompatibility": "blocked" if unresolved else "conditional",
            "supabaseProjection": "conditional",
            "regression": "pending_runtime_validation",
        },
        "blockers": [
            "GPT-4.1 family remains review_required without safe default calculation prices.",
            "Some PriceRecords remain partial evidence because their sources are official but not independently verified in Phase 2.",
        ],
        "counts": {
            "candidateUnionCount": report["candidateUnionCount"],
            "normalizedCanonicalIdentityCount": report["normalizedCanonicalIdentityCount"],
            "priceRecordCount": report["counts"]["priceRecordCount"],
            "chargeRecordCount": report["counts"]["chargeRecordCount"],
            "sourceRecordCount": report["counts"]["sourceRecordCount"],
            "completeEvidencePriceRecordCount": sum(
                1 for row in matrix if row["evidenceCompleteness"] == "complete"
            ),
            "partialEvidencePriceRecordCount": sum(
                1 for row in matrix if row["evidenceCompleteness"] == "partial"
            ),
            "insufficientEvidencePriceRecordCount": sum(
                1 for row in matrix if row["evidenceCompleteness"] == "insufficient"
            ),
        },
    }


def parse_effective_date(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


def is_current_effective(price: dict[str, Any], today: date) -> bool:
    effective_from = parse_effective_date(price["effectiveFrom"])
    effective_until = parse_effective_date(price["effectiveUntil"])
    return (effective_from is None or effective_from <= today) and (
        effective_until is None or effective_until >= today
    )


def price_amounts(price: dict[str, Any]) -> dict[str, str | None]:
    charges = {charge["component"]: charge["amount"] for charge in price["charges"]}
    return {
        "input": charges.get("input"),
        "cached_input": charges.get("cached_input"),
        "output": charges.get("output"),
    }


def text_modality_present(price: dict[str, Any]) -> bool:
    return any(charge["modality"] == "text" for charge in price["charges"])


def provider_from_internal_id(internal_id_value: str) -> str:
    return internal_id_value.split("/", 1)[0]


def build_website_usage_map(website_models: list[dict[str, Any]]) -> list[dict[str, str]]:
    website_ids = [item["id"] for item in website_models]
    usage_rows: list[dict[str, str]] = []

    def add(website_model_id: str, usage_type: str, source: str) -> None:
        usage_rows.append(
            {
                "websiteModelId": website_model_id,
                "usageType": usage_type,
                "source": source,
            }
        )

    all_model_consumers = [
        ("calculator_dropdown_model", "src/components/cost-calculator.tsx"),
        ("pricing_comparison_model", "src/components/pricing-table.tsx"),
        ("token_calculator_dropdown_model", "src/components/token-calculator.tsx"),
        ("prompt_cost_optimizer_dropdown_model", "src/components/prompt-cost-optimizer.tsx"),
    ]
    for website_model_id in website_ids:
        for usage_type, source in all_model_consumers:
            add(website_model_id, usage_type, source)

    for website_model_id in website_ids[:12]:
        add(website_model_id, "homepage_estimator_dropdown_model", "src/components/home-api-cost-estimator.tsx")

    for website_model_id, usage_type, source in [
        ("gpt-5.4-mini", "calculator_default_model", "src/components/cost-calculator.tsx"),
        ("gpt-5.4-mini", "homepage_estimator_default_model", "src/components/home-api-cost-estimator.tsx"),
        ("gpt-5.4-mini", "token_calculator_default_model", "src/components/token-calculator.tsx"),
        ("gpt-5.4-mini", "prompt_cost_optimizer_default_model", "src/components/prompt-cost-optimizer.tsx"),
    ]:
        add(website_model_id, usage_type, source)

    budget_routes = [
        ("gpt-5.4-mini", "support.routeA"),
        ("gemini-3.1-flash-lite", "support.routeB"),
        ("claude-haiku-4.5", "support.routeC"),
        ("gemini-3.5-flash", "summary.routeA"),
        ("gpt-5.4-mini", "summary.routeB"),
        ("claude-sonnet-5", "summary.routeC"),
        ("gpt-5.4-mini", "agent.routeA"),
        ("gpt-5.5", "agent.routeB"),
        ("claude-opus-4.8", "agent.routeC"),
        ("gpt-5.4-nano", "scenario.budget.45"),
        ("deepseek-v4-flash", "scenario.budget.35"),
        ("gemini-3.1-flash-lite", "scenario.budget.20"),
        ("gpt-5.4-mini", "scenario.balanced.45"),
        ("gemini-3.5-flash", "scenario.balanced.35"),
        ("claude-haiku-4.5", "scenario.balanced.20"),
        ("claude-opus-4.8", "scenario.premium.35"),
        ("gpt-5.5", "scenario.premium.35"),
        ("grok-4.3", "scenario.premium.30"),
    ]
    for website_model_id, route in budget_routes:
        add(website_model_id, f"budget_planner_routing_model:{route}", "src/lib/budget-planner.ts")

    return sorted(usage_rows, key=lambda item: (item["websiteModelId"], item["usageType"], item["source"]))


def build_phase25_artifacts(
    prices: list[dict[str, Any]],
    models: list[dict[str, Any]],
    identities: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    phase2_matrix: list[dict[str, Any]],
    report: dict[str, Any],
    website_models: list[dict[str, Any]],
    website_projection: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    today = date.today()
    price_by_id = {price["pricingId"]: price for price in prices}
    model_by_id = {model["internalId"]: model for model in models}
    identity_by_id = {identity["internalId"]: identity for identity in identities}
    matrix_by_id = {row["pricingId"]: row for row in phase2_matrix}
    source_by_id = {source["sourceId"]: source for source in sources}
    pricing_conflict_ids = {item["internalId"] for item in report["pricingConflicts"]}
    default_price_ids = {
        model["defaultPriceRecordId"] for model in models if model["defaultPriceRecordId"] is not None
    }
    default_price_ids.update(
        row["defaultPriceRecordId"] for row in website_projection if row["defaultPriceRecordId"] is not None
    )

    def default_safe_blockers(
        price: dict[str, Any],
        criticality: str,
        verification_status: str,
        evidence_completeness_value: str,
    ) -> list[str]:
        model = model_by_id[price["modelInternalId"]]
        identity = identity_by_id[price["modelInternalId"]]
        blockers: list[str] = []
        if not is_current_effective(price, today):
            blockers.append("not_current_effective")
        if model["lifecycleStatus"] == "retired" or identity["lifecycleStatus"] == "retired":
            blockers.append("lifecycle_retired")
        if verification_status != "verified":
            blockers.append("verification_not_verified")
        if evidence_completeness_value != "complete":
            blockers.append("evidence_not_complete")
        if not price["sourceRefs"]:
            blockers.append("missing_source_refs")
        for ref in price["sourceRefs"]:
            source = source_by_id.get(ref)
            if source is None:
                blockers.append("orphan_source_ref")
            elif not source.get("officialProviderDomain"):
                blockers.append("missing_official_provider_domain")
            elif source["verificationStatus"] == "verified" and not source.get("verifiedAt"):
                blockers.append("missing_verified_at")
        if price["processingMode"] != "standard":
            blockers.append("not_standard_processing_mode")
        if not text_modality_present(price):
            blockers.append("missing_text_modality")
        if verification_status == "review_required":
            blockers.append("review_required")
        if criticality in {"historical", "review_only"}:
            blockers.append(f"criticality_{criticality}")
        if criticality != "production_default_candidate":
            blockers.append("not_production_default_candidate")
        if identity["identityType"] == "historical_reference" and identity["routingBehavior"] == "redirect":
            blockers.append("redirect_only_pricing")
        if price["modelInternalId"] in pricing_conflict_ids:
            blockers.append("unresolved_pricing_conflict")
        if not price["charges"]:
            blockers.append("missing_charge_components")
        return sorted(set(blockers))

    def classify_criticality(price: dict[str, Any]) -> str:
        model = model_by_id[price["modelInternalId"]]
        identity = identity_by_id[price["modelInternalId"]]
        effective_from = parse_effective_date(price["effectiveFrom"])
        effective_until = parse_effective_date(price["effectiveUntil"])
        if price["verificationStatus"] == "review_required":
            return "review_only"
        if identity["identityType"] == "historical_reference" and identity["routingBehavior"] == "redirect":
            return "retired_redirect"
        if model["lifecycleStatus"] == "retired":
            return "historical"
        if effective_from and effective_from > today:
            return "future_effective"
        if effective_until and effective_until < today:
            return "historical"
        if price["pricingId"] in default_price_ids and price["processingMode"] == "standard":
            return "production_default_candidate"
        if price["processingMode"] != "standard":
            return "non_default_tier"
        if model["lifecycleStatus"] == "active":
            return "production_secondary"
        return "historical"

    evidence_completion = []
    for price in prices:
        criticality = classify_criticality(price)
        evidence = matrix_by_id[price["pricingId"]]
        phase25_source = PHASE25_OFFICIAL_COMPLETION.get(price["pricingId"]) or PHASE26_OFFICIAL_COMPLETION.get(price["pricingId"])
        after_evidence = "complete" if phase25_source else evidence["evidenceCompleteness"]
        after_verification_status = "verified" if phase25_source else price["verificationStatus"]
        blockers = default_safe_blockers(price, criticality, after_verification_status, after_evidence)
        default_safe = not blockers
        if evidence["evidenceCompleteness"] == "partial":
            if criticality == "production_default_candidate":
                priority = "P0"
            elif criticality in {"production_secondary", "non_default_tier"}:
                priority = "P1"
            elif criticality == "future_effective":
                priority = "P2"
            else:
                priority = "P3"
        else:
            priority = "not_partial"
        if phase25_source:
            verification_decision = "official_verified_in_phase2_5"
        elif priority.startswith("P") and evidence["evidenceCompleteness"] == "partial":
            verification_decision = "retain_partial"
        else:
            verification_decision = "unchanged"
        evidence_completion.append(
            {
                "pricingId": price["pricingId"],
                "modelInternalId": price["modelInternalId"],
                "provider": provider_from_internal_id(price["modelInternalId"]),
                "businessCriticality": criticality,
                "priorityClass": priority,
                "beforeEvidenceCompleteness": evidence["evidenceCompleteness"],
                "afterEvidenceCompleteness": after_evidence,
                "beforeVerificationStatus": price["verificationStatus"],
                "afterVerificationStatus": after_verification_status,
                "sourceRefs": price["sourceRefs"],
                "officialEvidence": [phase25_source] if phase25_source else [],
                "phase25VerifiedAt": f"{today.isoformat()}T00:00:00Z" if phase25_source else None,
                "verificationDecision": verification_decision,
                "defaultSafe": default_safe,
                "currentEffective": is_current_effective(price, today),
                "currentPrices": price_amounts(price),
                "blocker": blockers,
                "reason": "Default-safe gate passed." if default_safe else "Default-safe gate blocked by: " + ", ".join(blockers),
            }
        )

    p0_partial_before = sum(
        1 for item in evidence_completion if item["priorityClass"] == "P0" and item["beforeEvidenceCompleteness"] == "partial"
    )
    p0_partial_after = sum(
        1 for item in evidence_completion if item["priorityClass"] == "P0" and item["afterEvidenceCompleteness"] == "partial"
    )
    p1_partial = sum(1 for item in evidence_completion if item["priorityClass"] == "P1")
    p2_partial = sum(1 for item in evidence_completion if item["priorityClass"] == "P2")
    p3_partial = sum(1 for item in evidence_completion if item["priorityClass"] == "P3")
    production_default_candidates = [
        item for item in evidence_completion if item["businessCriticality"] == "production_default_candidate"
    ]
    default_safe_report = {
        "generatedAt": f"{today.isoformat()}T00:00:00Z",
        "totalPriceRecords": len(prices),
        "productionDefaultCandidateCount": len(production_default_candidates),
        "defaultSafeCount": sum(1 for item in evidence_completion if item["defaultSafe"]),
        "defaultUnsafeCount": sum(1 for item in evidence_completion if not item["defaultSafe"]),
        "productionDefaultSafeCount": sum(1 for item in production_default_candidates if item["defaultSafe"]),
        "productionDefaultUnsafeCount": sum(1 for item in production_default_candidates if not item["defaultSafe"]),
        "P0PartialBefore": p0_partial_before,
        "P0PartialAfter": p0_partial_after,
        "P1PartialCount": p1_partial,
        "P2PartialCount": p2_partial,
        "P3PartialCount": p3_partial,
        "blockers": sorted(
            {
                blocker
                for item in evidence_completion
                for blocker in item["blocker"]
                if item["businessCriticality"] == "production_default_candidate"
            }
        ),
        "productionDefaultCandidates": production_default_candidates,
    }

    projection_by_website_id = {row["id"]: row for row in website_projection}
    website_by_id = {row["id"]: row for row in website_models}
    website_usage_map = build_website_usage_map(website_models)
    evidence_by_price_id = {item["pricingId"]: item for item in evidence_completion}
    blocker_rows = []
    for usage in website_usage_map:
        website_model_id = usage["websiteModelId"]
        website = website_by_id[website_model_id]
        provider_id = website_provider_id(website)
        canonical_internal_id = internal_id(provider_id, website_model_id)
        projection = projection_by_website_id.get(website_model_id, {})
        selected_price_record_id = projection.get("defaultPriceRecordId")
        price_evidence = evidence_by_price_id.get(selected_price_record_id) if selected_price_record_id else None
        default_safe = bool(price_evidence and price_evidence["defaultSafe"])
        evidence_completeness_value = (
            price_evidence["afterEvidenceCompleteness"] if price_evidence else "insufficient"
        )
        blockers = [] if default_safe else ["selected_price_not_default_safe"]
        if selected_price_record_id is None:
            blockers.append("missing_selected_price_record")
        if website.get("status") == "retired" or website_model_id == "grok-3":
            blockers.append("retired_or_redirected_website_model")
        if website.get("verificationStatus") == "review_required":
            blockers.append("website_model_review_required")

        usage_type = usage["usageType"]
        if default_safe and "retired_or_redirected_website_model" not in blockers:
            action = "safe_to_integrate"
        elif "retired_or_redirected_website_model" in blockers and selected_price_record_id:
            action = "integrate_with_warning"
        elif "default" in usage_type or "routing" in usage_type:
            action = "exclude_from_default"
        elif "review_required" in blockers or "missing_selected_price_record" in blockers:
            action = "keep_existing_temporarily"
        elif evidence_completeness_value == "partial":
            action = "integrate_with_warning"
        else:
            action = "blocked"

        blocker_rows.append(
            {
                "websiteModelId": website_model_id,
                "usageType": usage_type,
                "source": usage["source"],
                "canonicalInternalId": canonical_internal_id,
                "selectedPriceRecordId": selected_price_record_id,
                "defaultSafe": default_safe,
                "evidenceCompleteness": evidence_completeness_value,
                "blocker": sorted(set(blockers)),
                "recommendedIntegrationAction": action,
            }
        )

    blocker_action_counts = {
        action: sum(1 for item in blocker_rows if item["recommendedIntegrationAction"] == action)
        for action in [
            "safe_to_integrate",
            "integrate_with_warning",
            "exclude_from_default",
            "keep_existing_temporarily",
            "blocked",
        ]
    }
    p0_blockers = [item for item in production_default_candidates if not item["defaultSafe"]]
    phase25_readiness = {
        "generatedAt": f"{today.isoformat()}T00:00:00Z",
        "identityReadiness": "conditional",
        "defaultPricingReadiness": "blocked" if p0_blockers else "ready",
        "secondaryPricingReadiness": "conditional" if p1_partial else "ready",
        "provenanceReadiness": "blocked" if p0_partial_after else "conditional",
        "websiteCompatibilityReadiness": "blocked" if any(
            item["recommendedIntegrationAction"] == "exclude_from_default" for item in blocker_rows
        ) else "conditional",
        "supabaseProjectionReadiness": "conditional",
        "regressionReadiness": "pending_runtime_validation",
        "safeToEnterWebsiteIntegrationPlanning": not p0_blockers,
        "blockers": [
            "P0 partial evidence PriceRecords must not enter default calculators.",
            "GPT-4.1 family remains review_required and must keep defaultSafe=false.",
            "Claude Sonnet 5 future standard PriceRecord is not present in the 47-record preview; effective-date switch remains blocked for cutover.",
        ],
        "websiteIntegrationActionCounts": blocker_action_counts,
    }
    return evidence_completion, default_safe_report, blocker_rows, phase25_readiness


def build_phase26_artifacts(
    models: list[dict[str, Any]],
    prices: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    phase25_evidence: list[dict[str, Any]],
    phase25_default_safe: dict[str, Any],
    phase25_website_blockers: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    generated_at = "2026-07-07T00:00:00Z"
    source_by_url = {source["url"]: source["sourceId"] for source in sources}
    source_by_id = {source["sourceId"]: source for source in sources}
    model_by_id = {model["internalId"]: model for model in models}
    price_by_model = defaultdict(list)
    for price in prices:
        price_by_model[price["modelInternalId"]].append(price)

    phase25_by_model = {row["modelInternalId"]: row for row in phase25_evidence}
    p0_before = [
        "cohere/command-a-plus",
        "google-gemini/gemini-3.1-pro-preview",
        "google-gemini/gemini-3.5-flash",
        "openai/gpt-5",
        "openai/o3",
    ]
    p0_after = [
        model_id
        for model_id in p0_before
        if model_id in PHASE26_EXCLUDED_DEFAULT_MODELS
        and model_by_id.get(model_id, {}).get("defaultPriceRecordId") is not None
    ]
    verified_upgrade_models = [
        "google-gemini/gemini-3.1-pro-preview",
        "google-gemini/gemini-3.5-flash",
    ]
    excluded_models = sorted(PHASE26_EXCLUDED_DEFAULT_MODELS)

    def source_ref(url: str) -> str:
        return source_by_url[url]

    def pricing_refs(*urls: str) -> list[str]:
        return [source_ref(url) for url in urls]

    def source_verified_at(refs: list[str]) -> str | None:
        values = [source_by_id[ref].get("verifiedAt") for ref in refs if source_by_id.get(ref)]
        return max([value for value in values if value], default=None)

    decisions = []
    decision_specs = [
        {
            "modelInternalId": "cohere/command-a-plus",
            "officialModelExistence": "verified",
            "officialModelId": "command-a-plus-05-2026",
            "currentAvailability": "Live",
            "lifecycleStatus": "active",
            "currentEffectivePricingFound": False,
            "pricingSourceRefs": pricing_refs(
                "https://cohere.com/pricing",
                "https://docs.cohere.com/docs/how-does-cohere-pricing-work",
            ),
            "modelSourceRefs": pricing_refs("https://docs.cohere.com/docs/models"),
            "evidenceCompleteness": "partial",
            "defaultSafeDecision": False,
            "blockerReason": PHASE26_EXCLUDED_DEFAULT_MODELS["cohere/command-a-plus"],
            "finalAction": "exclude_from_default",
        },
        {
            "modelInternalId": "google-gemini/gemini-3.1-pro-preview",
            "officialModelExistence": "verified",
            "officialModelId": "gemini-3.1-pro-preview",
            "currentAvailability": "Preview",
            "lifecycleStatus": "active",
            "currentEffectivePricingFound": True,
            "pricingSourceRefs": pricing_refs("https://ai.google.dev/gemini-api/docs/pricing"),
            "modelSourceRefs": pricing_refs("https://ai.google.dev/gemini-api/docs/pricing"),
            "evidenceCompleteness": "complete",
            "defaultSafeDecision": True,
            "blockerReason": None,
            "finalAction": "verified_default_safe",
            "structuredPricing": {
                "standard_short": "prompts <= 200k tokens",
                "standard_long": "prompts > 200k tokens",
            },
        },
        {
            "modelInternalId": "google-gemini/gemini-3.5-flash",
            "officialModelExistence": "verified",
            "officialModelId": "gemini-3.5-flash",
            "currentAvailability": "Standard",
            "lifecycleStatus": "active",
            "currentEffectivePricingFound": True,
            "pricingSourceRefs": pricing_refs("https://ai.google.dev/gemini-api/docs/pricing"),
            "modelSourceRefs": pricing_refs("https://ai.google.dev/gemini-api/docs/pricing"),
            "evidenceCompleteness": "complete",
            "defaultSafeDecision": True,
            "blockerReason": None,
            "finalAction": "verified_default_safe",
        },
        {
            "modelInternalId": "openai/gpt-5",
            "officialModelExistence": "not_confirmed_current_api_pricing_identity",
            "officialModelId": "gpt-5",
            "currentAvailability": "not_confirmed_for_default_api_pricing",
            "lifecycleStatus": "active",
            "currentEffectivePricingFound": False,
            "pricingSourceRefs": pricing_refs("https://developers.openai.com/api/docs/pricing"),
            "modelSourceRefs": pricing_refs("https://developers.openai.com/api/docs/models"),
            "evidenceCompleteness": "partial",
            "defaultSafeDecision": False,
            "blockerReason": PHASE26_EXCLUDED_DEFAULT_MODELS["openai/gpt-5"],
            "finalAction": "exclude_from_default",
        },
        {
            "modelInternalId": "openai/o3",
            "officialModelExistence": "not_confirmed_current_default_api_pricing_identity",
            "officialModelId": "o3",
            "currentAvailability": "not_confirmed_for_default_api_pricing",
            "lifecycleStatus": "active",
            "currentEffectivePricingFound": False,
            "pricingSourceRefs": pricing_refs("https://developers.openai.com/api/docs/pricing"),
            "modelSourceRefs": pricing_refs("https://developers.openai.com/api/docs/models"),
            "evidenceCompleteness": "partial",
            "defaultSafeDecision": False,
            "blockerReason": PHASE26_EXCLUDED_DEFAULT_MODELS["openai/o3"],
            "finalAction": "exclude_from_default",
        },
    ]
    for spec in decision_specs:
        refs = sorted(set(spec["pricingSourceRefs"] + spec["modelSourceRefs"]))
        phase25_row = phase25_by_model.get(spec["modelInternalId"], {})
        decisions.append(
            {
                **spec,
                "verifiedAt": source_verified_at(refs) or generated_at,
                "phase25DefaultSafe": phase25_row.get("defaultSafe"),
                "priceRecordIds": [price["pricingId"] for price in price_by_model[spec["modelInternalId"]]],
            }
        )

    production_default_candidates = [
        row for row in phase25_evidence if row["businessCriticality"] == "production_default_candidate"
    ]
    production_default_safe = [row for row in production_default_candidates if row["defaultSafe"]]
    production_default_unsafe = [row for row in production_default_candidates if not row["defaultSafe"]]
    website_usage_impact = []
    for model_internal_id in p0_before:
        website_model_id = model_internal_id.split("/", 1)[1]
        rows = [row for row in phase25_website_blockers if row["websiteModelId"] == website_model_id]
        usage_counts: dict[str, int] = {}
        for row in rows:
            usage_counts[row["usageType"]] = usage_counts.get(row["usageType"], 0) + 1
        website_usage_impact.append(
            {
                "modelInternalId": model_internal_id,
                "websiteModelId": website_model_id,
                "usageMappingCount": len(rows),
                "usageTypes": dict(sorted(usage_counts.items())),
                "integrationImpact": (
                    "verified default-safe; safe_to_integrate for mapped usages"
                    if model_internal_id in verified_upgrade_models
                    else "excluded from default candidates; no direct Website usage mapping currently found"
                    if not rows
                    else "excluded from default candidates; mapped usages must keep existing temporarily"
                ),
            }
        )

    resolution = {
        "generatedAt": generated_at,
        "P0BlockersBefore": p0_before,
        "P0BlockersAfter": p0_after,
        "perModelDecisions": decisions,
        "verificationUpgrades": verified_upgrade_models,
        "exclusionsFromDefault": excluded_models,
        "reviewRequiredRemaining": [
            price["pricingId"] for price in prices if price["verificationStatus"] == "review_required"
        ],
        "productionDefaultCandidateCount": len(production_default_candidates),
        "productionDefaultSafeCount": len(production_default_safe),
        "productionDefaultUnsafeCount": len(production_default_unsafe),
        "remainingBlockers": production_default_unsafe,
        "integrationMappingCount": len(phase25_website_blockers),
        "websiteUsageImpact": website_usage_impact,
    }
    closure = {
        "generatedAt": generated_at,
        "defaultCandidatesBefore": 31,
        "defaultCandidatesAfter": len(production_default_candidates),
        "safeBefore": 26,
        "safeAfter": len(production_default_safe),
        "unsafeBefore": 5,
        "unsafeAfter": len(production_default_unsafe),
        "excludedCandidates": excluded_models,
        "evidenceBasedUpgrades": verified_upgrade_models,
        "closureGatePassed": len(production_default_unsafe) == 0,
    }
    cutover = {
        "generatedAt": generated_at,
        "identityReadiness": "conditional",
        "defaultPricingReadiness": "ready" if closure["closureGatePassed"] else "blocked",
        "provenanceReadiness": "conditional",
        "websiteCompatibilityReadiness": "conditional" if closure["closureGatePassed"] else "blocked",
        "supabaseReadiness": "conditional",
        "regressionReadiness": "conditional",
        "safeToEnterWebsiteIntegrationPlanning": closure["closureGatePassed"],
        "integrationMappingCount": len(phase25_website_blockers),
        "remainingBlockers": production_default_unsafe,
    }
    return resolution, closure, cutover


def build_phase3_artifacts(
    phase25_website_blockers: list[dict[str, Any]],
    phase26_resolution: dict[str, Any],
    phase26_closure: dict[str, Any],
    phase26_readiness: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    generated_at = "2026-07-07T00:00:00Z"
    consumer_map = {
        "generatedAt": generated_at,
        "websiteRepo": r"D:\ai-cost-control-tool\aicostguard-english",
        "readOnlyStatus": "observed_dirty_do_not_modify",
        "consumerCount": 13,
        "consumers": [
            {
                "consumerId": "pricing_data_module",
                "filePath": "src/lib/pricing.ts",
                "usageType": "central_pricing_utility",
                "currentDataSource": "data/model-pricing.json",
                "currentFieldsUsed": ["id", "provider", "model", "status", "availability", "inputPrice", "cachedInputPrice", "outputPrice", "contextWindow", "pricingBasis", "priceNote", "bestFor", "lastUpdated", "officialPriceUrl"],
                "currentDefaultModelLogic": "exports raw array order and helper labels; no default filtering",
                "currentFallbackLogic": "callers generally fallback to models[0]",
                "nullHandling": "cachedInputPrice optional; inputPrice/outputPrice typed required",
                "statusHandling": "display-only status union; no defaultSafe semantics",
                "cachedPriceHandling": "modelPriceSummary displays cached price when numeric; calculateCost ignores cached input",
                "integrationRisk": "high",
            },
            {
                "consumerId": "api_cost_calculator",
                "filePath": "src/components/cost-calculator.tsx",
                "usageType": "interactive_default_calculation",
                "currentDataSource": "@/lib/pricing.models",
                "currentFieldsUsed": ["id", "provider", "model", "status", "inputPrice", "outputPrice", "pricingBasis", "priceNote", "lastUpdated", "officialPriceUrl"],
                "currentDefaultModelLogic": "hardcoded gpt-5.4-mini; dropdown maps all models",
                "currentFallbackLogic": "selected model fallback to models[0]",
                "nullHandling": "does not support null input/output prices",
                "statusHandling": "status is shown but not enforced",
                "cachedPriceHandling": "cached price displayed in summary only; cost uses input/output",
                "integrationRisk": "high",
            },
            {
                "consumerId": "homepage_estimator",
                "filePath": "src/components/home-api-cost-estimator.tsx",
                "usageType": "homepage_default_calculation",
                "currentDataSource": "@/lib/pricing.models",
                "currentFieldsUsed": ["id", "provider", "model", "inputPrice", "outputPrice"],
                "currentDefaultModelLogic": "hardcoded gpt-5.4-mini; dropdown uses models.slice(0, 12)",
                "currentFallbackLogic": "fallback to first model if hardcoded ID missing",
                "nullHandling": "does not support null input/output prices",
                "statusHandling": "not surfaced in calculator body",
                "cachedPriceHandling": "not used",
                "integrationRisk": "high",
            },
            {
                "consumerId": "budget_planner_core",
                "filePath": "src/lib/budget-planner.ts",
                "usageType": "model_routing_cost_engine",
                "currentDataSource": "./pricing.models",
                "currentFieldsUsed": ["id", "inputPrice", "cachedInputPrice", "outputPrice"],
                "currentDefaultModelLogic": "preset and scenario route IDs are hardcoded",
                "currentFallbackLogic": "invalid routes fallback to support preset or models[0]",
                "nullHandling": "cachedInputPrice falls back to inputPrice; input/output required",
                "statusHandling": "none",
                "cachedPriceHandling": "cache hit rate blends inputPrice and cachedInputPrice",
                "integrationRisk": "high",
            },
            {
                "consumerId": "advanced_budget_planner",
                "filePath": "src/components/advanced-budget-planner.tsx",
                "usageType": "interactive_routing_ui",
                "currentDataSource": "@/lib/pricing.models plus src/lib/budget-planner.ts",
                "currentFieldsUsed": ["id", "provider", "model", "inputPrice", "cachedInputPrice", "outputPrice"],
                "currentDefaultModelLogic": "initial state from budget-planner support preset; route selects show all models",
                "currentFallbackLogic": "budget-planner sanitization",
                "nullHandling": "inherits budget-planner behavior",
                "statusHandling": "not enforced in route selects",
                "cachedPriceHandling": "inherits cache hit cost blending",
                "integrationRisk": "high",
            },
            {
                "consumerId": "pricing_table",
                "filePath": "src/components/pricing-table.tsx",
                "usageType": "comparison_table_display",
                "currentDataSource": "@/lib/pricing.models",
                "currentFieldsUsed": ["provider", "model", "status", "availability", "inputPrice", "cachedInputPrice", "outputPrice", "contextWindow", "officialPriceUrl", "bestFor", "pricingBasis", "priceNote", "lastUpdated"],
                "currentDefaultModelLogic": "all models rendered",
                "currentFallbackLogic": "none",
                "nullHandling": "cached price optional; input/output assumed present",
                "statusHandling": "CSS class and display only",
                "cachedPriceHandling": "display only",
                "integrationRisk": "medium",
            },
            {
                "consumerId": "model_pricing_comparison_page",
                "filePath": "src/app/[locale]/model-pricing-comparison/page.tsx",
                "usageType": "seo_page_wrapper",
                "currentDataSource": "PricingTable component",
                "currentFieldsUsed": ["derived through PricingTable"],
                "currentDefaultModelLogic": "none",
                "currentFallbackLogic": "none",
                "nullHandling": "inherits PricingTable",
                "statusHandling": "inherits PricingTable",
                "cachedPriceHandling": "inherits PricingTable",
                "integrationRisk": "medium",
            },
            {
                "consumerId": "homepage_price_highlights",
                "filePath": "src/app/[locale]/page.tsx",
                "usageType": "homepage_pricing_display",
                "currentDataSource": "@/lib/pricing.models",
                "currentFieldsUsed": ["provider", "model", "inputPrice", "outputPrice"],
                "currentDefaultModelLogic": "models.slice(0, 4)",
                "currentFallbackLogic": "none",
                "nullHandling": "input/output assumed present",
                "statusHandling": "not shown",
                "cachedPriceHandling": "not shown",
                "integrationRisk": "medium",
            },
            {
                "consumerId": "token_calculator",
                "filePath": "src/components/token-calculator.tsx",
                "usageType": "input_only_cost_estimator",
                "currentDataSource": "@/lib/pricing.models",
                "currentFieldsUsed": ["id", "provider", "model", "status", "inputPrice", "cachedInputPrice", "pricingBasis", "priceNote", "lastUpdated", "officialPriceUrl"],
                "currentDefaultModelLogic": "hardcoded gpt-5.4-mini; dropdown maps all models",
                "currentFallbackLogic": "fallback to models[0]",
                "nullHandling": "inputPrice assumed present",
                "statusHandling": "display only",
                "cachedPriceHandling": "display only; input cost uses inputPrice",
                "integrationRisk": "medium",
            },
            {
                "consumerId": "prompt_cost_optimizer",
                "filePath": "src/components/prompt-cost-optimizer.tsx",
                "usageType": "prompt_input_cost_estimator",
                "currentDataSource": "@/lib/pricing.models",
                "currentFieldsUsed": ["id", "provider", "model", "status", "inputPrice", "cachedInputPrice", "outputPrice", "pricingBasis", "lastUpdated", "officialPriceUrl"],
                "currentDefaultModelLogic": "hardcoded gpt-5.4-mini; dropdown maps all models",
                "currentFallbackLogic": "fallback to models[0]",
                "nullHandling": "input/output assumed present",
                "statusHandling": "display only",
                "cachedPriceHandling": "display only",
                "integrationRisk": "medium",
            },
            {
                "consumerId": "batch_token_calculator",
                "filePath": "src/components/batch-calculator.tsx",
                "usageType": "batch_input_cost_estimator",
                "currentDataSource": "@/lib/pricing.models",
                "currentFieldsUsed": ["id", "inputPrice"],
                "currentDefaultModelLogic": "hardcoded gpt-5.4-mini only",
                "currentFallbackLogic": "fallback to models[0]",
                "nullHandling": "inputPrice assumed present",
                "statusHandling": "none",
                "cachedPriceHandling": "not used",
                "integrationRisk": "medium",
            },
            {
                "consumerId": "supabase_model_prices_seed",
                "filePath": "supabase/seed.sql",
                "usageType": "database_seed_projection",
                "currentDataSource": "manually maintained SQL values",
                "currentFieldsUsed": ["id", "provider", "model", "model_status", "availability", "input_price", "cached_input_price", "output_price", "context_window", "pricing_basis", "pricing_note", "best_for", "price_last_updated", "official_price_url"],
                "currentDefaultModelLogic": "none",
                "currentFallbackLogic": "SQL on conflict update",
                "nullHandling": "cached_input_price nullable; input/output non-null",
                "statusHandling": "stored as model_status text",
                "cachedPriceHandling": "stored nullable",
                "integrationRisk": "high",
            },
            {
                "consumerId": "sitemap_and_seo_shell",
                "filePath": "src/app/sitemap.ts; src/lib/seo-content.ts; src/lib/blog-posts.ts",
                "usageType": "indirect_seo_reference",
                "currentDataSource": "static routes and editorial copy, no direct model-pricing JSON import",
                "currentFieldsUsed": ["links to comparison/calculator pages", "editorial pricing disclaimers"],
                "currentDefaultModelLogic": "none",
                "currentFallbackLogic": "none",
                "nullHandling": "not applicable",
                "statusHandling": "not applicable",
                "cachedPriceHandling": "editorial mentions only",
                "integrationRisk": "low",
            },
        ],
    }

    ownership_map = {
        "generatedAt": generated_at,
        "canonicalPricingFactsOwnedByDataset": [
            "provider identity",
            "model identity",
            "official IDs",
            "lifecycle",
            "pricing",
            "cached pricing",
            "effective dates",
            "aliases",
            "redirects",
            "verification",
            "official sources",
            "defaultSafe eligibility",
        ],
        "websiteEditorialMetadataOwnedByWebsite": [
            "bestFor",
            "marketing copy",
            "SEO description",
            "FAQ",
            "comparison commentary",
            "internal links",
            "page-specific editorial text",
            "pricing disclaimers",
        ],
        "doNotMigrateIntoCanonicalDataset": [
            "bestFor",
            "blog copy",
            "localized page metadata",
            "CTA text",
            "commercial plan copy",
        ],
        "projectionBoundary": "Canonical V2 emits facts and safe calculation metadata; Website owns presentation and editorial enrichment.",
    }

    projection_contract = {
        "generatedAt": generated_at,
        "recommendedMode": "repo_local_generated_projection",
        "contractName": "website-pricing-projection-v1",
        "requiredFields": ["id", "provider", "model", "inputPrice", "cachedInputPrice", "outputPrice", "status", "defaultSafe", "verificationStatus", "officialSourceUrl"],
        "optionalFields": ["contextWindow", "verifiedAt", "effectiveFrom", "effectiveUntil", "canonicalInternalId", "selectedPriceRecordId", "routingBehavior", "redirectedBilling", "warning"],
        "doNotRequireWebsiteToUnderstandFullV2Schema": True,
        "integrationModes": [
            {"mode": "runtime_fetch_public_api", "recommendation": "do_not_use", "reason": "adds request-time external dependency, latency, stale/failure ambiguity, and rollback complexity"},
            {"mode": "build_time_fetch", "recommendation": "acceptable_with_pin", "reason": "better latency than runtime fetch but build reproducibility depends on external availability"},
            {"mode": "repo_local_generated_projection", "recommendation": "recommended", "reason": "deterministic, reviewable, rollback-friendly, and no production runtime dependency on GitHub Pages"},
            {"mode": "ci_synchronized_artifact", "recommendation": "later_stage", "reason": "good automation after projection contract and rollback policy are approved"},
        ],
        "defaultSafePolicy": {
            "unsafe": "exclude from default calculations and show warning only where explicitly allowed",
            "review_required": "display only with warning; no default or recommendation placement",
            "null_price": "do not calculate; show unavailable/review message",
            "retired": "display as historical only",
            "redirect_billing": "show original slug as retired/redirected and calculate against billingModelInternalId only with explicit label",
            "future_effective": "select by effective dates, never by array order",
            "alias": "resolve alias target while preserving alias mode notes",
        },
        "specialPolicies": {
            "claude-sonnet-5": "Use effective-date selection: intro through 2026-08-31, standard from 2026-09-01.",
            "xai/grok-3": "Do not display as active; if current cost is offered, label redirected billing to xai/grok-4.3.",
            "gpt-4.1_family": "review_required and defaultSafe=false; may remain SEO/historical display with warning.",
            "cohere/command-a-plus": "excluded from default until official token pricing is complete.",
            "openai/gpt-5": "excluded from default until current API pricing is officially confirmed.",
            "openai/o3": "excluded from default until current API pricing is officially confirmed.",
        },
    }

    integration_mapping = []
    for row in phase25_website_blockers:
        action = row["recommendedIntegrationAction"]
        risk = "low" if action == "safe_to_integrate" else "medium" if action in {"integrate_with_warning", "keep_existing_temporarily"} else "high"
        integration_mapping.append(
            {
                "websiteConsumer": row["usageType"],
                "websiteModelId": row["websiteModelId"],
                "canonicalInternalId": row["canonicalInternalId"],
                "selectedPriceRecord": row["selectedPriceRecordId"],
                "defaultSafe": row["defaultSafe"],
                "action": action,
                "migrationRisk": risk,
                "blocker": row["blocker"],
            }
        )

    action_counts: dict[str, int] = {}
    for row in integration_mapping:
        action_counts[row["action"]] = action_counts.get(row["action"], 0) + 1

    integration_plan = {
        "generatedAt": generated_at,
        "recommendedSequence": [
            {"stage": 0, "name": "Website P0 Hotfix separate commit", "goal": "clean existing Website data/model-pricing.json change before implementation"},
            {"stage": 1, "name": "Add generated projection artifact", "goal": "commit repo-local Website-compatible projection without changing consumers"},
            {"stage": 2, "name": "Add adapter behind feature flag", "goal": "support old and projected shapes with default off"},
            {"stage": 3, "name": "Shadow parity", "goal": "compare current Website pricing to canonical projection without changing user results"},
            {"stage": 4, "name": "Low-risk consumer pilot", "goal": "migrate PricingTable or homepage highlights first"},
            {"stage": 5, "name": "Calculator migration", "goal": "enforce defaultSafe for API Cost Calculator and homepage estimator"},
            {"stage": 6, "name": "Budget Planner migration", "goal": "migrate route presets and cache blending with safe defaults only"},
            {"stage": 7, "name": "SEO / Comparison migration", "goal": "migrate display pages while preserving editorial metadata"},
            {"stage": 8, "name": "Supabase projection", "goal": "generate seed/sync artifact from Canonical V2"},
            {"stage": 9, "name": "Legacy dataset retirement", "goal": "remove manual dual maintenance only after shadow parity and rollback are proven"},
        ],
        "shadowMode": {
            "enabledBeforeUserVisibleMigration": True,
            "resultBuckets": ["exact_parity", "expected_difference", "unsafe_difference", "null_difference"],
            "userVisibleResultChange": "none during shadow mode",
        },
        "featureFlag": {
            "recommended": True,
            "name": "PRICING_V2_ENABLED",
            "default": "off",
            "rollout": ["local", "staging", "limited production", "full production"],
        },
        "runtimePublicApiDependency": "not_allowed",
    }

    rollback_plan = {
        "generatedAt": generated_at,
        "strategy": "single feature flag or single commit rollback to current Website data/model-pricing.json path",
        "requirements": [
            "keep legacy data/model-pricing.json until parity and production confidence are proven",
            "do not migrate all consumers in one commit",
            "adapter must preserve old shape while flag is off",
            "projection artifact changes must be reviewable in git",
            "Supabase sync must remain separate from Website runtime migration",
        ],
        "rollbackSteps": [
            "turn PRICING_V2_ENABLED off",
            "redeploy Website using legacy dataset path",
            "if needed revert only the projection/adapter commit",
            "leave canonical dataset artifacts intact for investigation",
        ],
    }

    testing_plan = {
        "generatedAt": generated_at,
        "requiredTests": [
            "projection contract tests",
            "V1/V2 parity tests",
            "defaultSafe enforcement",
            "null price tests",
            "review_required tests",
            "retired model tests",
            "redirect billing tests",
            "effective date boundary tests",
            "alias routing tests",
            "Calculator snapshot tests",
            "Budget Planner parity tests",
            "SEO page data tests",
            "Supabase seed projection tests",
        ],
    }

    readiness = {
        "generatedAt": generated_at,
        "datasetRepoCleanAtStart": True,
        "websiteRepoClean": False,
        "websiteExistingDirtyStatus": ["M data/model-pricing.json"],
        "websiteP0HotfixSeparateCommit": False,
        "projectionContractApproved": False,
        "rollbackPlanApproved": False,
        "shadowModeDesigned": True,
        "defaultSafeEnforcementDesigned": True,
        "noProductionRuntimeDependencyOnGitHubPages": True,
        "implementationReadiness": "blocked",
        "planningReadiness": "complete",
        "blockers": [
            "Website repo has pre-existing uncommitted data/model-pricing.json change.",
            "Website P0 Hotfix must be committed separately before implementation.",
            "Projection contract, rollback plan, and shadow mode need approval before implementation.",
        ],
        "phase26Closure": {
            "productionDefaultCandidateCount": phase26_closure["defaultCandidatesAfter"],
            "productionDefaultSafeCount": phase26_closure["safeAfter"],
            "productionDefaultUnsafeCount": phase26_closure["unsafeAfter"],
            "safeToEnterWebsiteIntegrationPlanning": phase26_readiness["safeToEnterWebsiteIntegrationPlanning"],
        },
        "integrationMappingCount": len(integration_mapping),
        "integrationActionCounts": dict(sorted(action_counts.items())),
    }

    return (
        consumer_map,
        ownership_map,
        projection_contract,
        integration_mapping,
        integration_plan,
        rollback_plan,
        testing_plan,
        readiness,
    )


def decimal_string(value: Any) -> str | None:
    if value is None:
        return None
    return format(Decimal(str(value)).normalize(), "f")


def number_or_none(value: str | None) -> float | int | None:
    if value is None:
        return None
    decimal = Decimal(value)
    if decimal == decimal.to_integral_value():
        return int(decimal)
    return float(decimal)


def internal_id(provider_id: str, model_id: str) -> str:
    return f"{provider_id}/{model_id}"


def source_id(provider_id: str, url: str) -> str:
    token = (
        url.replace("https://", "")
        .replace("http://", "")
        .replace("/", "-")
        .replace("#", "-")
        .replace(".", "-")
        .strip("-")
    )
    return f"source:{provider_id}:{token[:80]}"


def official_domain(provider_id: str, url: str) -> str | None:
    for domain in OFFICIAL_DOMAINS.get(provider_id, ()):
        if domain in url:
            return domain
    return None


def source_type(url: str) -> str:
    if "migration" in url or "deprecation" in url or "retirement" in url:
        return "official_deprecation_or_redirect"
    if "models" in url:
        return "official_model_docs"
    return "official_pricing_page"


def website_provider_id(record: dict[str, Any]) -> str:
    return PROVIDER_SLUGS.get(record["provider"], record["provider"].lower().replace(" ", "-"))


def status_parts(provider_id: str, model_id: str, public: dict[str, Any] | None, website: dict[str, Any] | None) -> dict[str, Any]:
    website_status = (website or {}).get("status")
    public_status = (public or {}).get("status")
    if (provider_id, model_id) in REVIEW_REQUIRED_IDS:
        return {
            "lifecycleStatus": "deprecated",
            "releaseStage": "legacy",
            "availability": (website or {}).get("availability", "Legacy"),
            "verificationStatus": "review_required",
        }
    if provider_id == "xai" and model_id == "grok-3":
        return {
            "lifecycleStatus": "retired",
            "releaseStage": "legacy",
            "availability": (website or {}).get("availability", "Retired"),
            "verificationStatus": "verified",
        }
    if website_status == "retired":
        lifecycle = "retired"
    elif website_status in {"legacy", "deprecated"} or public_status in {"deprecated", "retired"}:
        lifecycle = "deprecated"
    else:
        lifecycle = "active"

    if website_status == "preview" or public_status == "preview":
        release_stage = "preview"
    elif website_status in {"legacy", "deprecated", "retired"}:
        release_stage = "legacy"
    elif website_status == "specialized":
        release_stage = "specialized"
    else:
        release_stage = "stable"

    verification = "verified" if public and website else "partially_verified"
    return {
        "lifecycleStatus": lifecycle,
        "releaseStage": release_stage,
        "availability": (website or {}).get("availability", public_status or "unknown"),
        "verificationStatus": verification,
    }


def official_ids(provider_id: str, model_id: str, public: dict[str, Any] | None, website: dict[str, Any] | None) -> list[dict[str, str]]:
    kind = "canonical"
    if (provider_id, model_id) in IDENTITY_COLLAPSE:
        kind = IDENTITY_COLLAPSE[(provider_id, model_id)]["identityType"].replace("_id", "")
    values: list[dict[str, str]] = []
    if public:
        values.append({"id": model_id, "type": kind, "source": "public_dataset"})
    if website:
        values.append({"id": model_id, "type": kind, "source": "website_dataset"})
    seen: set[tuple[str, str, str]] = set()
    deduped = []
    for item in values:
        key = (item["id"], item["type"], item["source"])
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def source_refs_for(provider_id: str, public: dict[str, Any] | None, website: dict[str, Any] | None, source_by_url: dict[str, str]) -> list[str]:
    refs = []
    for url in ((public or {}).get("official_source_url"), (website or {}).get("officialPriceUrl")):
        if url:
            refs.append(source_by_url[url])
    return sorted(set(refs))


def make_charges(prefix: str, values: dict[str, Any], source: str) -> list[dict[str, Any]]:
    mapping = [
        ("input", values.get("input")),
        ("cached_input", values.get("cached_input")),
        ("cache_write_5m", values.get("cache_write")),
        ("output", values.get("output")),
    ]
    if source == "website":
        mapping = [
            ("input", values.get("inputPrice")),
            ("cached_input", values.get("cachedInputPrice")),
            ("output", values.get("outputPrice")),
        ]
    charges = []
    for component, value in mapping:
        amount = decimal_string(value)
        if amount is not None:
            charges.append(
                {
                    "chargeId": f"{prefix}:{component}:text:per_1m_tokens",
                    "component": component,
                    "modality": "text",
                    "unit": "per_1m_tokens",
                    "amount": amount,
                }
            )
    return charges


def price_lookup(record: dict[str, Any]) -> dict[str, str | None]:
    values = {charge["component"]: charge["amount"] for charge in record["charges"]}
    return {
        "input": values.get("input"),
        "cached_input": values.get("cached_input"),
        "output": values.get("output"),
    }


def source_side(public: dict[str, Any] | None, website: dict[str, Any] | None) -> str:
    if public and website:
        return "common"
    if public:
        return "public_only"
    return "website_only"


def main() -> None:
    public_models = read_json(CANONICAL / "models.json")
    website_models = read_json(WEBSITE_DATASET)
    public_by_key = {(item["provider_id"], item["model_id"]): item for item in public_models}
    website_by_key = {(website_provider_id(item), item["id"]): item for item in website_models}
    candidate_keys = sorted(set(public_by_key) | set(website_by_key))

    source_urls: dict[str, dict[str, Any]] = {}
    for key, item in public_by_key.items():
        source_urls[item["official_source_url"]] = {
            "providerId": key[0],
            "url": item["official_source_url"],
            "sourceType": source_type(item["official_source_url"]),
            "title": f"{PROVIDER_DISPLAY.get(key[0], key[0])} official source",
            "accessedAt": item.get("accessed_at"),
            "checkedAt": item.get("accessed_at"),
            "verifiedAt": item.get("last_verified_at"),
            "officialProviderDomain": official_domain(key[0], item["official_source_url"]),
            "supports": ["pricing"],
            "verificationStatus": "verified",
        }
    for key, item in website_by_key.items():
        url = item.get("officialPriceUrl")
        if not url:
            continue
        checked_at = item.get("lastVerifiedAt") or item.get("lastUpdated")
        supports = ["pricing"]
        if item.get("redirectTarget") or item.get("billingModelId"):
            supports.extend(["redirect", "billing"])
        if item.get("retirementDate"):
            supports.append("retirement")
        source_urls.setdefault(
            url,
            {
                "providerId": key[0],
                "url": url,
                "sourceType": source_type(url),
                "title": f"{PROVIDER_DISPLAY.get(key[0], key[0])} official source",
                "accessedAt": checked_at,
                "checkedAt": checked_at,
                "verifiedAt": item.get("lastVerifiedAt"),
                "officialProviderDomain": official_domain(key[0], url),
                "supports": sorted(set(supports)),
                "verificationStatus": item.get("verificationStatus", "partially_verified"),
            },
        )

    for (provider_id, url), meta in PHASE26_EXTRA_SOURCE_URLS.items():
        checked_at = "2026-07-07T00:00:00Z"
        source_urls[url] = {
            "providerId": provider_id,
            "url": url,
            "sourceType": meta["sourceType"],
            "title": meta["title"],
            "accessedAt": checked_at,
            "checkedAt": checked_at,
            "verifiedAt": checked_at,
            "officialProviderDomain": official_domain(provider_id, url),
            "supports": meta["supports"],
            "verificationStatus": meta["verificationStatus"],
        }

    source_by_url = {url: source_id(meta["providerId"], url) for url, meta in source_urls.items()}
    sources = [
        {"sourceId": source_by_url[url], **meta}
        for url, meta in sorted(source_urls.items(), key=lambda item: source_by_url[item[0]])
    ]

    identities = []
    canonical_keys = []
    for provider_id, model_id in candidate_keys:
        if (provider_id, model_id) in MERGED_DUPLICATES:
            continue
        public = public_by_key.get((provider_id, model_id))
        website = website_by_key.get((provider_id, model_id))
        collapse = IDENTITY_COLLAPSE.get((provider_id, model_id))
        parts = status_parts(provider_id, model_id, public, website)
        identity_type = collapse["identityType"] if collapse else "canonical_model"
        target = collapse["target"] if collapse else None
        if identity_type == "canonical_model":
            canonical_keys.append((provider_id, model_id))
        identities.append(
            {
                "providerId": provider_id,
                "internalId": internal_id(provider_id, model_id),
                "displayName": (public or {}).get("display_name") or (website or {}).get("model") or model_id,
                "canonicalOfficialId": target.split("/", 1)[1] if target else model_id,
                "officialIds": official_ids(provider_id, model_id, public, website),
                "websiteIds": [model_id] if website else [],
                "publicDatasetIds": [model_id] if public else [],
                "identityType": identity_type,
                "lifecycleStatus": parts["lifecycleStatus"],
                "releaseStage": parts["releaseStage"],
                "availability": parts["availability"],
                "routingBehavior": (collapse or {}).get("routingBehavior", "direct"),
                "routingDetails": (collapse or {}).get("routingDetails", {}),
                "aliasTargetInternalId": target if identity_type in {"alias", "pinned_id"} else None,
                "redirectTargetInternalId": (collapse or {}).get("routingDetails", {}).get("redirectTargetInternalId"),
                "billingModelInternalId": (collapse or {}).get("routingDetails", {}).get("billingModelInternalId"),
                "replacementInternalId": (
                    internal_id(provider_id, website["replacementModelId"])
                    if website and website.get("replacementModelId") and not (provider_id == "xai" and model_id == "grok-3")
                    else None
                ),
                "deprecationDate": None,
                "retirementDate": (website or {}).get("retirementDate"),
                "verificationStatus": parts["verificationStatus"],
                "sourceRefs": source_refs_for(provider_id, public, website, source_by_url),
            }
        )

    candidate_dispositions = []
    for provider_id, model_id in candidate_keys:
        public = public_by_key.get((provider_id, model_id))
        website = website_by_key.get((provider_id, model_id))
        candidate_internal_id = internal_id(provider_id, model_id)
        collapse = IDENTITY_COLLAPSE.get((provider_id, model_id))
        merged = MERGED_DUPLICATES.get((provider_id, model_id))
        parts = status_parts(provider_id, model_id, public, website)
        disposition = "canonical_identity"
        final_internal_id = candidate_internal_id
        merge_target = None
        alias_target = None
        reason = "Candidate is retained as a canonical model identity."
        verification_status = parts["verificationStatus"]
        if (provider_id, model_id) in REVIEW_REQUIRED_IDS:
            disposition = "unresolved"
            reason = "Identity retained, but current price/lifecycle facts require review before safe default calculation."
            verification_status = "review_required"
        if merged:
            disposition = "merged_duplicate"
            final_internal_id = merged["target"]
            merge_target = merged["target"]
            verification_status = "partially_verified"
            reason = merged["reason"]
        elif collapse and collapse["identityType"] == "alias":
            disposition = "alias"
            final_internal_id = collapse["target"]
            alias_target = collapse["target"]
            reason = collapse["routingDetails"]["semantics"]
        elif collapse and collapse["identityType"] == "historical_reference":
            disposition = "historical_reference"
            final_internal_id = candidate_internal_id
            reason = collapse["routingDetails"]["semantics"]
        candidate_dispositions.append(
            {
                "candidateId": candidate_internal_id,
                "sourceSide": source_side(public, website),
                "provider": provider_id,
                "finalInternalId": final_internal_id,
                "disposition": disposition,
                "mergeTarget": merge_target,
                "aliasTarget": alias_target,
                "reason": reason,
                "verificationStatus": verification_status,
            }
        )

    prices: list[dict[str, Any]] = []
    price_by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def add_price(model_internal_id: str, record: dict[str, Any]) -> None:
        prices.append(record)
        price_by_model[model_internal_id].append(record)

    for provider_id, model_id in canonical_keys:
        public = public_by_key.get((provider_id, model_id))
        website = website_by_key.get((provider_id, model_id))
        if provider_id == "anthropic" and model_id == "claude-sonnet-5":
            public = public_by_key.get(("anthropic", "claude-sonnet-5-intro"))
        verification = status_parts(provider_id, model_id, public, website)["verificationStatus"]
        model_internal_id = internal_id(provider_id, model_id)

        if public:
            pricing = public["pricing"]
            pricing_id = f"price:{model_internal_id}:standard:short:current"
            if provider_id == "anthropic" and model_id == "claude-sonnet-5":
                pricing_id = f"price:{model_internal_id}:standard:intro:2026-07-05"
            excluded_from_default = model_internal_id in PHASE26_EXCLUDED_DEFAULT_MODELS
            record = {
                "pricingId": pricing_id,
                "modelInternalId": model_internal_id,
                "processingMode": "standard",
                "contextClass": "short",
                "regionPolicy": "global",
                "promptTokenThreshold": None,
                "effectiveFrom": public.get("effective_from"),
                "effectiveUntil": "2026-08-31" if provider_id == "anthropic" and model_id == "claude-sonnet-5" else None,
                "currency": "USD",
                "charges": make_charges(pricing_id, pricing, "public"),
                "sourceRefs": source_refs_for(provider_id, public, website, source_by_url),
                "billingNote": public.get("notes", ""),
                "verificationStatus": "review_required" if (provider_id, model_id) in REVIEW_REQUIRED_IDS else verification,
                "calculationDefault": (provider_id, model_id) not in REVIEW_REQUIRED_IDS and not excluded_from_default,
                "sourceDatasetIds": {
                    "publicDatasetIds": [public["model_id"]],
                    "websiteIds": [website["id"]] if website else [],
                },
            }
            add_price(model_internal_id, record)
            if provider_id == "anthropic" and model_id == "claude-sonnet-5":
                future_id = f"price:{model_internal_id}:standard:short:2026-09-01"
                add_price(
                    model_internal_id,
                    {
                        **record,
                        "pricingId": future_id,
                        "effectiveFrom": "2026-09-01",
                        "effectiveUntil": None,
                        "charges": make_charges(
                            future_id,
                            {
                                "input": "3",
                                "cached_input": "0.3",
                                "cache_write": "3.75",
                                "output": "15",
                            },
                            "public",
                        ),
                        "billingNote": "Future standard pricing for Claude Sonnet 5 starts 2026-09-01 per Anthropic official pricing.",
                        "calculationDefault": False,
                        "sourceDatasetIds": {
                            "publicDatasetIds": ["claude-sonnet-5"],
                            "websiteIds": [website["id"]] if website else [],
                        },
                    },
                )
            if pricing.get("batch_input") is not None or pricing.get("batch_output") is not None:
                batch_id = f"price:{model_internal_id}:batch:short:current"
                add_price(
                    model_internal_id,
                    {
                        **record,
                        "pricingId": batch_id,
                        "processingMode": "batch",
                        "charges": make_charges(
                            batch_id,
                            {
                                "input": pricing.get("batch_input"),
                                "output": pricing.get("batch_output"),
                                "cached_input": None,
                                "cache_write": None,
                            },
                            "public",
                        ),
                        "billingNote": f"Batch projection derived from explicit Public V1 batch fields for {model_internal_id}.",
                        "calculationDefault": False,
                    },
                )
        elif website:
            pricing_id = f"price:{model_internal_id}:standard:short:website-preview"
            verification = "review_required" if (provider_id, model_id) in REVIEW_REQUIRED_IDS else website.get("verificationStatus", "partially_verified")
            if pricing_id in PHASE26_OFFICIAL_COMPLETION:
                verification = "verified"
            excluded_from_default = model_internal_id in PHASE26_EXCLUDED_DEFAULT_MODELS
            prompt_threshold = 200000 if model_internal_id == "google-gemini/gemini-3.1-pro-preview" else None
            record = {
                "pricingId": pricing_id,
                "modelInternalId": model_internal_id,
                "processingMode": "standard",
                "contextClass": "short",
                "regionPolicy": "global",
                "promptTokenThreshold": prompt_threshold,
                "effectiveFrom": website.get("lastUpdated"),
                "effectiveUntil": None,
                "currency": "USD",
                "charges": make_charges(pricing_id, website, "website"),
                "sourceRefs": source_refs_for(provider_id, None, website, source_by_url),
                "billingNote": website.get("priceNote", ""),
                "verificationStatus": verification,
                "calculationDefault": verification not in {"review_required", "unconfirmed_price"} and not excluded_from_default,
                "sourceDatasetIds": {"publicDatasetIds": [], "websiteIds": [website["id"]]},
            }
            add_price(model_internal_id, record)
            if model_internal_id == "google-gemini/gemini-3.1-pro-preview":
                long_id = f"price:{model_internal_id}:standard:long:website-preview"
                add_price(
                    model_internal_id,
                    {
                        **record,
                        "pricingId": long_id,
                        "contextClass": "long",
                        "promptTokenThreshold": 200000,
                        "charges": make_charges(
                            long_id,
                            {"input": "4", "cached_input": "0.4", "output": "18"},
                            "public",
                        ),
                        "billingNote": "Structured Gemini 3.1 Pro Preview standard pricing for prompts > 200k tokens.",
                        "calculationDefault": False,
                    },
                )

    models = []
    for provider_id, model_id in sorted(canonical_keys):
        public = public_by_key.get((provider_id, model_id))
        website = website_by_key.get((provider_id, model_id))
        if provider_id == "anthropic" and model_id == "claude-sonnet-5":
            public = public_by_key.get(("anthropic", "claude-sonnet-5-intro"))
        parts = status_parts(provider_id, model_id, public, website)
        model_internal_id = internal_id(provider_id, model_id)
        default_price = next(
            (
                item
                for item in price_by_model.get(model_internal_id, [])
                if item["processingMode"] == "standard" and item["calculationDefault"]
            ),
            None,
        )
        models.append(
            {
                "providerId": provider_id,
                "internalId": model_internal_id,
                "displayName": (website or {}).get("model") or (public or {}).get("display_name") or model_id,
                "canonicalOfficialId": model_id,
                "officialIds": official_ids(provider_id, model_id, public, website),
                "lifecycleStatus": parts["lifecycleStatus"],
                "releaseStage": parts["releaseStage"],
                "availability": parts["availability"],
                "routingBehavior": "direct",
                "defaultPriceRecordId": default_price["pricingId"] if default_price else None,
                "verificationStatus": parts["verificationStatus"],
                "sourceRefs": source_refs_for(provider_id, public, website, source_by_url),
            }
        )

    exact_parity: list[str] = []
    expected_difference: list[dict[str, str]] = []
    unresolved_difference: list[dict[str, str]] = []
    parity_details: list[dict[str, Any]] = []
    model_by_id = {item["internalId"]: item for item in models}
    price_by_id = {item["pricingId"]: item for item in prices}

    def default_price_for_candidate(provider_id: str, model_id: str) -> dict[str, Any] | None:
        collapse = IDENTITY_COLLAPSE.get((provider_id, model_id))
        model_internal_id = collapse["target"] if collapse else internal_id(provider_id, model_id)
        model = model_by_id.get(model_internal_id)
        if not model or not model["defaultPriceRecordId"]:
            return None
        return price_by_id[model["defaultPriceRecordId"]]

    website_projection = []
    for website in website_models:
        provider_id = website_provider_id(website)
        model_id = website["id"]
        candidate_id = internal_id(provider_id, model_id)
        price = default_price_for_candidate(provider_id, model_id)
        values = price_lookup(price) if price else {"input": None, "cached_input": None, "output": None}
        projected = {
            "id": model_id,
            "provider": website["provider"],
            "model": website["model"],
            "inputPrice": number_or_none(values["input"]),
            "cachedInputPrice": number_or_none(values["cached_input"]),
            "outputPrice": number_or_none(values["output"]),
            "status": website["status"],
            "verificationStatus": "review_required" if not price else price["verificationStatus"],
            "defaultPriceRecordId": price["pricingId"] if price else None,
            "defaultPriceSelectionRule": ["current_effective", "verified", "standard", "text", "default_context_class"],
        }
        website_projection.append(projected)
        old_values = {
            "inputPrice": website.get("inputPrice"),
            "cachedInputPrice": website.get("cachedInputPrice"),
            "outputPrice": website.get("outputPrice"),
        }
        new_values = {
            "inputPrice": projected["inputPrice"],
            "cachedInputPrice": projected["cachedInputPrice"],
            "outputPrice": projected["outputPrice"],
        }
        comparable = (
            new_values["inputPrice"] == old_values["inputPrice"]
            and new_values["cachedInputPrice"] == old_values["cachedInputPrice"]
            and new_values["outputPrice"] == old_values["outputPrice"]
        )
        if comparable:
            exact_parity.append(candidate_id)
            classification = "exact_parity"
            reason = "Website values match the selected V2 default calculation price."
        elif not price or projected["verificationStatus"] in {"review_required", "unconfirmed_price"}:
            reason = "no safe default calculation price"
            unresolved_difference.append({"internalId": candidate_id, "reason": reason})
            classification = "unresolved_difference"
        else:
            reason = "canonical V2 projection has richer condition/source metadata"
            expected_difference.append({"internalId": candidate_id, "reason": reason})
            classification = "expected_difference"
        parity_details.append(
            {
                "modelId": model_id,
                "internalId": candidate_id,
                "oldWebsiteValue": old_values,
                "v2PreviewValue": new_values,
                "classification": classification,
                "reason": reason,
            }
        )

    sql_lines = [
        "-- AICostBudget Pricing V2 preview seed.",
        "-- Generated from data/pricing-v2-preview/*.json; not a production Supabase seed.",
        "begin;",
        "create table if not exists pricing_v2_preview_sources (source_id text primary key, payload jsonb not null);",
        "create table if not exists pricing_v2_preview_models (internal_id text primary key, payload jsonb not null);",
        "create table if not exists pricing_v2_preview_prices (pricing_id text primary key, model_internal_id text not null, payload jsonb not null);",
    ]
    for source in sources:
        sql_lines.append(
            "insert into pricing_v2_preview_sources (source_id, payload) values "
            + f"('{source['sourceId']}', '{json.dumps(source, sort_keys=True).replace("'", "''")}'::jsonb) "
            + "on conflict (source_id) do update set payload = excluded.payload;"
        )
    for model in models:
        sql_lines.append(
            "insert into pricing_v2_preview_models (internal_id, payload) values "
            + f"('{model['internalId']}', '{json.dumps(model, sort_keys=True).replace("'", "''")}'::jsonb) "
            + "on conflict (internal_id) do update set payload = excluded.payload;"
        )
    for price in prices:
        sql_lines.append(
            "insert into pricing_v2_preview_prices (pricing_id, model_internal_id, payload) values "
            + f"('{price['pricingId']}', '{price['modelInternalId']}', '{json.dumps(price, sort_keys=True).replace("'", "''")}'::jsonb) "
            + "on conflict (pricing_id) do update set model_internal_id = excluded.model_internal_id, payload = excluded.payload;"
        )
    sql_lines.extend(["commit;", ""])

    identity_type_counts = defaultdict(int)
    disposition_counts = defaultdict(int)
    unresolved = []
    for identity in identities:
        identity_type_counts[identity["identityType"]] += 1
        if identity["verificationStatus"] in {"review_required", "unconfirmed_price"}:
            unresolved.append(identity["internalId"])
    for disposition in candidate_dispositions:
        disposition_counts[disposition["disposition"]] += 1

    report = {
        "generatedAt": f"{date.today().isoformat()}T00:00:00Z",
        "candidateUnionCount": len(candidate_keys),
        "normalizedCanonicalIdentityCount": len(canonical_keys),
        "aliasCount": identity_type_counts["alias"],
        "duplicateIdentityCount": len(candidate_keys) - len(canonical_keys),
        "statisticsSource": {
            "candidateUnionCount": "len(candidate-disposition-map.json)",
            "normalizedCanonicalIdentityCount": "len(models.json)",
            "aliasCount": "count(model-identity-registry.json where identityType == 'alias')",
            "duplicateIdentityCount": "candidateUnionCount - normalizedCanonicalIdentityCount; includes alias, historical_reference, and merged_duplicate candidate dispositions, so it is not mutually exclusive with aliasCount.",
            "unresolvedIdentityCount": "count(candidate-disposition-map.json where disposition == 'unresolved'); unresolved identities remain normalized canonical identities.",
        },
        "candidateDispositionCounts": dict(sorted(disposition_counts.items())),
        "websiteOnlyCount": len(set(website_by_key) - set(public_by_key)),
        "publicOnlyCount": len(set(public_by_key) - set(website_by_key)),
        "commonCount": len(set(public_by_key) & set(website_by_key)),
        "pricingConflicts": unresolved_difference,
        "lifecycleConflicts": [
            {"internalId": "xai/grok-3", "resolution": "retired identity retained; redirects to xai/grok-4.3 current billing"}
        ],
        "sourceConflicts": [],
        "verificationConflicts": [
            {"internalId": item, "resolution": "review_required; no safe default calculation price"}
            for item in sorted(unresolved)
        ],
        "unresolvedIdentities": sorted(unresolved),
        "specialCases": {
            "grok-3": "Retained as historical_reference for the retired slug, marked retired, redirectTargetInternalId and billingModelInternalId point to xai/grok-4.3, replacementInternalId remains null because redirect is not treated as replacement evidence.",
            "gpt-4.1_family": "gpt-4.1, gpt-4.1-mini, and gpt-4.1-nano are review_required; prices are retained where present but not selected as safe defaults.",
            "claude-sonnet-5_intro_pricing": "claude-sonnet-5-intro is not modeled as an identity; it is a merged_duplicate candidate and an introductory PriceRecord on anthropic/claude-sonnet-5.",
            "deepseek_aliases": "deepseek-chat and deepseek-reasoner are alias identities targeting deepseek-v4-flash with mode-specific routing notes.",
            "gemini-2.5_cached_pricing": "Public V1 cached_input values are preserved; Website projection differences are classified instead of silently overwriting Website data.",
        },
        "websiteCompatibilityPreviewParity": {
            "exact_parity": sorted(exact_parity),
            "expected_difference": expected_difference,
            "unresolved_difference": unresolved_difference,
            "details": parity_details,
        },
        "counts": {
            "modelRecordCount": len(models),
            "priceRecordCount": len(prices),
            "chargeRecordCount": sum(len(item["charges"]) for item in prices),
            "sourceRecordCount": len(sources),
        },
    }
    phase2_evidence_matrix = build_phase2_evidence_matrix(prices, sources)
    phase2_conflict_report = build_phase2_conflict_report(report, identities, phase2_evidence_matrix)
    phase2_cutover_readiness = build_phase2_cutover_readiness(
        report, phase2_conflict_report, phase2_evidence_matrix
    )
    (
        phase25_evidence_completion,
        phase25_default_safe_report,
        phase25_website_blockers,
        phase25_cutover_readiness,
    ) = build_phase25_artifacts(
        prices,
        models,
        identities,
        sources,
        phase2_evidence_matrix,
        report,
        website_models,
        website_projection,
    )
    (
        phase26_p0_resolution,
        phase26_default_safe_closure,
        phase26_cutover_readiness,
    ) = build_phase26_artifacts(
        models,
        prices,
        sources,
        phase25_evidence_completion,
        phase25_default_safe_report,
        phase25_website_blockers,
    )
    (
        phase3_website_consumer_map,
        phase3_data_ownership_map,
        phase3_website_projection_contract,
        phase3_integration_mapping,
        phase3_integration_plan,
        phase3_rollback_plan,
        phase3_testing_plan,
        phase3_readiness,
    ) = build_phase3_artifacts(
        phase25_website_blockers,
        phase26_p0_resolution,
        phase26_default_safe_closure,
        phase26_cutover_readiness,
    )

    write_json(PREVIEW / "model-identity-registry.json", identities)
    write_json(PREVIEW / "candidate-disposition-map.json", candidate_dispositions)
    write_json(PREVIEW / "models.json", models)
    write_json(PREVIEW / "prices.json", prices)
    write_json(PREVIEW / "sources.json", sources)
    write_json(
        PREVIEW / "schema-version.json",
        {
            "schemaName": "AICostBudget Pricing V2 Preview",
            "schemaVersion": "2.0.0-preview.1",
            "schemaPath": "schema/pricing-v2-preview.schema.json",
            "productionStatus": "preview_only",
            "publicV1Compatibility": "no_public_v1_outputs_are_overwritten",
            "previewFiles": [
                "candidate-disposition-map.json",
                "model-identity-registry.json",
                "models.json",
                "prices.json",
                "sources.json",
                "convergence-report.json",
                "phase2-conflict-resolution-report.json",
                "phase2-evidence-matrix.json",
                "phase2-cutover-readiness.json",
                "phase2-5-evidence-completion.json",
                "phase2-5-default-safe-report.json",
                "phase2-5-website-integration-blockers.json",
                "phase2-5-cutover-readiness.json",
                "phase2-6-p0-resolution.json",
                "phase2-6-default-safe-closure.json",
                "phase2-6-cutover-readiness.json",
                "phase3-website-consumer-map.json",
                "phase3-data-ownership-map.json",
                "phase3-website-projection-contract.json",
                "phase3-integration-mapping.json",
                "phase3-integration-plan.json",
                "phase3-rollback-plan.json",
                "phase3-testing-plan.json",
                "phase3-readiness.json",
                "generated/model-pricing.website-preview.json",
                "generated/seed-pricing.preview.sql",
            ],
        },
    )
    write_json(PREVIEW / "convergence-report.json", report)
    write_json(PREVIEW / "phase2-evidence-matrix.json", phase2_evidence_matrix)
    write_json(PREVIEW / "phase2-conflict-resolution-report.json", phase2_conflict_report)
    write_json(PREVIEW / "phase2-cutover-readiness.json", phase2_cutover_readiness)
    write_json(PREVIEW / "phase2-5-evidence-completion.json", phase25_evidence_completion)
    write_json(PREVIEW / "phase2-5-default-safe-report.json", phase25_default_safe_report)
    write_json(PREVIEW / "phase2-5-website-integration-blockers.json", phase25_website_blockers)
    write_json(PREVIEW / "phase2-5-cutover-readiness.json", phase25_cutover_readiness)
    write_json(PREVIEW / "phase2-6-p0-resolution.json", phase26_p0_resolution)
    write_json(PREVIEW / "phase2-6-default-safe-closure.json", phase26_default_safe_closure)
    write_json(PREVIEW / "phase2-6-cutover-readiness.json", phase26_cutover_readiness)
    write_json(PREVIEW / "phase3-website-consumer-map.json", phase3_website_consumer_map)
    write_json(PREVIEW / "phase3-data-ownership-map.json", phase3_data_ownership_map)
    write_json(PREVIEW / "phase3-website-projection-contract.json", phase3_website_projection_contract)
    write_json(PREVIEW / "phase3-integration-mapping.json", phase3_integration_mapping)
    write_json(PREVIEW / "phase3-integration-plan.json", phase3_integration_plan)
    write_json(PREVIEW / "phase3-rollback-plan.json", phase3_rollback_plan)
    write_json(PREVIEW / "phase3-testing-plan.json", phase3_testing_plan)
    write_json(PREVIEW / "phase3-readiness.json", phase3_readiness)
    write_json(GENERATED / "model-pricing.website-preview.json", website_projection)
    (GENERATED / "seed-pricing.preview.sql").parent.mkdir(parents=True, exist_ok=True)
    write_text_with_retry(GENERATED / "seed-pricing.preview.sql", "\n".join(sql_lines))

    print(f"generated pricing v2 preview: {PREVIEW}")


if __name__ == "__main__":
    main()
