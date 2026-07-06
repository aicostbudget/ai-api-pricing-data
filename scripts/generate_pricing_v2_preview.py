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
    "cohere": ("cohere.com",),
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
                "calculationDefault": (provider_id, model_id) not in REVIEW_REQUIRED_IDS,
                "sourceDatasetIds": {
                    "publicDatasetIds": [public["model_id"]],
                    "websiteIds": [website["id"]] if website else [],
                },
            }
            add_price(model_internal_id, record)
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
            add_price(
                model_internal_id,
                {
                    "pricingId": pricing_id,
                    "modelInternalId": model_internal_id,
                    "processingMode": "standard",
                    "contextClass": "short",
                    "regionPolicy": "global",
                    "promptTokenThreshold": None,
                    "effectiveFrom": website.get("lastUpdated"),
                    "effectiveUntil": None,
                    "currency": "USD",
                    "charges": make_charges(pricing_id, website, "website"),
                    "sourceRefs": source_refs_for(provider_id, None, website, source_by_url),
                    "billingNote": website.get("priceNote", ""),
                    "verificationStatus": verification,
                    "calculationDefault": verification not in {"review_required", "unconfirmed_price"},
                    "sourceDatasetIds": {"publicDatasetIds": [], "websiteIds": [website["id"]]},
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
                "generated/model-pricing.website-preview.json",
                "generated/seed-pricing.preview.sql",
            ],
        },
    )
    write_json(PREVIEW / "convergence-report.json", report)
    write_json(PREVIEW / "phase2-evidence-matrix.json", phase2_evidence_matrix)
    write_json(PREVIEW / "phase2-conflict-resolution-report.json", phase2_conflict_report)
    write_json(PREVIEW / "phase2-cutover-readiness.json", phase2_cutover_readiness)
    write_json(GENERATED / "model-pricing.website-preview.json", website_projection)
    (GENERATED / "seed-pricing.preview.sql").parent.mkdir(parents=True, exist_ok=True)
    write_text_with_retry(GENERATED / "seed-pricing.preview.sql", "\n".join(sql_lines))

    print(f"generated pricing v2 preview: {PREVIEW}")


if __name__ == "__main__":
    main()
