from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from lib import ROOT
except ModuleNotFoundError:
    from scripts.lib import ROOT

PREVIEW = ROOT / "data" / "pricing-v2-preview"

IDENTITY_TYPES = {"canonical_model", "alias", "snapshot", "pinned_id", "historical_reference"}
DISPOSITIONS = {"canonical_identity", "alias", "pinned_id", "snapshot", "historical_reference", "merged_duplicate", "unresolved"}
LIFECYCLE_STATUSES = {"active", "deprecated", "retired", "unknown"}
RELEASE_STAGES = {"stable", "preview", "legacy", "specialized", "unknown"}
VERIFICATION_STATUSES = {"verified", "partially_verified", "unconfirmed_price", "stale", "review_required"}
OFFICIAL_ID_TYPES = {"canonical", "alias", "snapshot", "pinned", "legacy", "historical_reference"}
PROCESSING_MODES = {"standard", "batch", "flex", "priority", "fast"}
CONTEXT_CLASSES = {"short", "long"}
CHARGE_COMPONENTS = {
    "input",
    "cached_input",
    "cache_write_5m",
    "cache_write_1h",
    "cache_read",
    "output",
    "storage",
    "request",
    "tool_call",
    "grounding",
}
MODALITIES = {"text", "image", "audio", "video"}
UNITS = {"per_1m_tokens", "per_1k_calls", "per_hour", "per_image", "per_second"}
DECIMAL_STRING = re.compile(r"^(0|[1-9]\d*)(\.\d+)?$")


def fail(message: str) -> None:
    raise SystemExit(f"pricing v2 preview validation failed: {message}")


def read_json(path: Path) -> Any:
    if not path.exists():
        fail(f"missing {path.relative_to(ROOT)}")
    return json.loads(path.read_text(encoding="utf-8"))


def parse_date(value: str | None, field: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        fail(f"invalid {field}: {value}")


def validate_required_fields(items: list[dict[str, Any]], required: set[str], label: str) -> None:
    for item in items:
        missing = required - set(item)
        if missing:
            fail(f"{label} missing fields {sorted(missing)}: {item}")


def validate_preview() -> dict[str, Any]:
    identities = read_json(PREVIEW / "model-identity-registry.json")
    dispositions = read_json(PREVIEW / "candidate-disposition-map.json")
    models = read_json(PREVIEW / "models.json")
    prices = read_json(PREVIEW / "prices.json")
    sources = read_json(PREVIEW / "sources.json")
    report = read_json(PREVIEW / "convergence-report.json")
    phase2_conflict = read_json(PREVIEW / "phase2-conflict-resolution-report.json")
    phase2_matrix = read_json(PREVIEW / "phase2-evidence-matrix.json")
    phase2_readiness = read_json(PREVIEW / "phase2-cutover-readiness.json")
    projection = read_json(PREVIEW / "generated" / "model-pricing.website-preview.json")
    seed = PREVIEW / "generated" / "seed-pricing.preview.sql"
    if not seed.exists() or not seed.read_text(encoding="utf-8").strip():
        fail("missing generated/seed-pricing.preview.sql")

    validate_required_fields(
        identities,
        {
            "providerId",
            "internalId",
            "displayName",
            "canonicalOfficialId",
            "officialIds",
            "websiteIds",
            "publicDatasetIds",
            "identityType",
            "lifecycleStatus",
            "releaseStage",
            "availability",
            "routingBehavior",
            "routingDetails",
            "aliasTargetInternalId",
            "redirectTargetInternalId",
            "billingModelInternalId",
            "replacementInternalId",
            "deprecationDate",
            "retirementDate",
            "verificationStatus",
            "sourceRefs",
        },
        "identity",
    )
    validate_required_fields(
        dispositions,
        {
            "candidateId",
            "sourceSide",
            "provider",
            "finalInternalId",
            "disposition",
            "mergeTarget",
            "aliasTarget",
            "reason",
            "verificationStatus",
        },
        "candidate disposition",
    )
    validate_required_fields(
        models,
        {
            "providerId",
            "internalId",
            "displayName",
            "canonicalOfficialId",
            "officialIds",
            "lifecycleStatus",
            "releaseStage",
            "availability",
            "routingBehavior",
            "defaultPriceRecordId",
            "verificationStatus",
            "sourceRefs",
        },
        "model",
    )
    validate_required_fields(
        prices,
        {
            "pricingId",
            "modelInternalId",
            "processingMode",
            "contextClass",
            "regionPolicy",
            "promptTokenThreshold",
            "effectiveFrom",
            "effectiveUntil",
            "currency",
            "charges",
            "sourceRefs",
            "billingNote",
            "verificationStatus",
            "calculationDefault",
        },
        "price",
    )
    validate_required_fields(
        sources,
        {
            "sourceId",
            "providerId",
            "url",
            "sourceType",
            "title",
            "checkedAt",
            "verifiedAt",
            "officialProviderDomain",
            "supports",
            "verificationStatus",
        },
        "source",
    )
    validate_required_fields(
        phase2_matrix,
        {
            "pricingId",
            "modelInternalId",
            "verificationStatus",
            "sourceRefs",
            "officialProviderDomain",
            "sourceType",
            "verifiedAt",
            "priceComponents",
            "evidenceCompleteness",
        },
        "phase2 evidence row",
    )

    identity_ids = [item["internalId"] for item in identities]
    if len(identity_ids) != len(set(identity_ids)):
        fail("duplicate identity internalId")
    model_ids = [item["internalId"] for item in models]
    if len(model_ids) != len(set(model_ids)):
        fail("duplicate model internalId")
    pricing_ids = [item["pricingId"] for item in prices]
    if len(pricing_ids) != len(set(pricing_ids)):
        fail("duplicate pricingId")
    source_ids = [item["sourceId"] for item in sources]
    if len(source_ids) != len(set(source_ids)):
        fail("duplicate sourceId")
    disposition_ids = [item["candidateId"] for item in dispositions]
    if len(disposition_ids) != len(set(disposition_ids)):
        fail("duplicate candidate disposition")

    identity_set = set(identity_ids)
    model_set = set(model_ids)
    price_by_id = {item["pricingId"]: item for item in prices}
    source_by_id = {item["sourceId"]: item for item in sources}
    source_set = set(source_by_id)
    disposition_set = set(disposition_ids)

    if "anthropic/claude-sonnet-5-intro" in identity_set:
        fail("claude-sonnet-5-intro must not be modeled as an identity")
    if "anthropic/claude-sonnet-5-intro" in model_set:
        fail("claude-sonnet-5-intro must not be modeled as a canonical model")

    for identity in identities:
        if identity["identityType"] not in IDENTITY_TYPES:
            fail(f"invalid identityType for {identity['internalId']}")
        if identity["lifecycleStatus"] not in LIFECYCLE_STATUSES:
            fail(f"invalid lifecycleStatus for {identity['internalId']}")
        if identity["releaseStage"] not in RELEASE_STAGES:
            fail(f"invalid releaseStage for {identity['internalId']}")
        if identity["verificationStatus"] not in VERIFICATION_STATUSES:
            fail(f"invalid verificationStatus for {identity['internalId']}")
        for ref in identity["sourceRefs"]:
            if ref not in source_set:
                fail(f"identity {identity['internalId']} has orphan sourceRef {ref}")
        for official in identity["officialIds"]:
            if not official.get("id") or official.get("type") not in OFFICIAL_ID_TYPES:
                fail(f"invalid officialId for {identity['internalId']}")
        if identity["aliasTargetInternalId"] and identity["aliasTargetInternalId"] not in identity_set:
            fail(f"invalid alias target for {identity['internalId']}")
        if identity["replacementInternalId"] and identity["replacementInternalId"] not in identity_set:
            fail(f"invalid replacement target for {identity['internalId']}")
        if identity["redirectTargetInternalId"] and identity["redirectTargetInternalId"] not in identity_set:
            fail(f"invalid redirect target for {identity['internalId']}")
        if identity["billingModelInternalId"] and identity["billingModelInternalId"] not in identity_set:
            fail(f"invalid billing model for {identity['internalId']}")
        if identity["internalId"] == "xai/grok-3":
            if identity["replacementInternalId"] is not None:
                fail("grok-3 redirect must not be conflated with replacementInternalId")
            if identity["redirectTargetInternalId"] != "xai/grok-4.3":
                fail("grok-3 missing redirectTargetInternalId")
            if identity["billingModelInternalId"] != "xai/grok-4.3":
                fail("grok-3 missing billingModelInternalId")

    for disposition in dispositions:
        if disposition["disposition"] not in DISPOSITIONS:
            fail(f"invalid disposition for {disposition['candidateId']}")
        if disposition["verificationStatus"] not in VERIFICATION_STATUSES:
            fail(f"invalid disposition verificationStatus for {disposition['candidateId']}")
        if disposition["sourceSide"] not in {"public_only", "website_only", "common"}:
            fail(f"invalid sourceSide for {disposition['candidateId']}")
        if disposition["disposition"] == "merged_duplicate" and not disposition["mergeTarget"]:
            fail(f"merged_duplicate missing mergeTarget for {disposition['candidateId']}")
        if disposition["disposition"] == "alias" and not disposition["aliasTarget"]:
            fail(f"alias missing aliasTarget for {disposition['candidateId']}")
        if disposition["finalInternalId"] not in identity_set:
            fail(f"candidate disposition finalInternalId missing identity: {disposition['candidateId']}")
    intro_disposition = next(item for item in dispositions if item["candidateId"] == "anthropic/claude-sonnet-5-intro")
    if intro_disposition["disposition"] != "merged_duplicate" or intro_disposition["mergeTarget"] != "anthropic/claude-sonnet-5":
        fail("claude-sonnet-5-intro must be a merged_duplicate disposition targeting anthropic/claude-sonnet-5")

    for model in models:
        if model["internalId"] not in identity_set:
            fail(f"model without identity {model['internalId']}")
        if model["verificationStatus"] not in VERIFICATION_STATUSES:
            fail(f"invalid model verificationStatus {model['internalId']}")
        for official in model["officialIds"]:
            if not official.get("id") or official.get("type") not in OFFICIAL_ID_TYPES:
                fail(f"invalid model officialIds for {model['internalId']}")
        for ref in model["sourceRefs"]:
            if ref not in source_set:
                fail(f"model {model['internalId']} has orphan sourceRef {ref}")
        default_id = model["defaultPriceRecordId"]
        if default_id is not None:
            if default_id not in price_by_id:
                fail(f"model {model['internalId']} defaultPriceRecordId missing")
            if price_by_id[default_id]["modelInternalId"] != model["internalId"]:
                fail(f"model {model['internalId']} defaultPriceRecordId points to another model")

    for price in prices:
        if price["modelInternalId"] not in model_set:
            fail(f"orphan price {price['pricingId']}")
        if price["processingMode"] not in PROCESSING_MODES:
            fail(f"invalid processingMode {price['pricingId']}")
        if price["contextClass"] not in CONTEXT_CLASSES:
            fail(f"invalid contextClass {price['pricingId']}")
        if price["currency"] != "USD":
            fail(f"invalid currency {price['pricingId']}")
        if price["verificationStatus"] not in VERIFICATION_STATUSES:
            fail(f"invalid price verificationStatus {price['pricingId']}")
        effective_from = parse_date(price["effectiveFrom"], "effectiveFrom")
        effective_until = parse_date(price["effectiveUntil"], "effectiveUntil")
        if effective_from and effective_until and effective_from >= effective_until:
            fail(f"effectiveFrom must be before effectiveUntil for {price['pricingId']}")
        if not price["sourceRefs"]:
            fail(f"price {price['pricingId']} missing sourceRefs")
        for ref in price["sourceRefs"]:
            if ref not in source_set:
                fail(f"price {price['pricingId']} has orphan sourceRef {ref}")
        if price["verificationStatus"] == "verified":
            verified_sources = [source_by_id[ref] for ref in price["sourceRefs"] if source_by_id[ref]["verificationStatus"] == "verified"]
            if not verified_sources:
                fail(f"verified price {price['pricingId']} has no verified sourceRef")
            for source in verified_sources:
                if not source.get("checkedAt") or not source.get("verifiedAt"):
                    fail(f"verified price {price['pricingId']} uses source without checkedAt/verifiedAt")
                domain = source["officialProviderDomain"]
                if not domain or domain not in urlparse(source["url"]).netloc:
                    fail(f"verified price {price['pricingId']} uses source without official provider domain")
        for charge in price["charges"]:
            if charge.get("component") not in CHARGE_COMPONENTS:
                fail(f"invalid charge component in {price['pricingId']}")
            if charge.get("modality") not in MODALITIES:
                fail(f"invalid charge modality in {price['pricingId']}")
            if charge.get("unit") not in UNITS:
                fail(f"invalid charge unit in {price['pricingId']}")
            amount = charge.get("amount")
            if not isinstance(amount, str) or not DECIMAL_STRING.match(amount):
                fail(f"invalid decimal string in {price['pricingId']}: {amount}")

    for source in sources:
        if not str(source["url"]).startswith("https://"):
            fail(f"source URL must be https: {source['sourceId']}")
        if source["verificationStatus"] not in VERIFICATION_STATUSES:
            fail(f"invalid source verificationStatus {source['sourceId']}")
        if source["officialProviderDomain"] not in urlparse(source["url"]).netloc:
            fail(f"source officialProviderDomain does not match URL: {source['sourceId']}")
        if source["verificationStatus"] == "verified" and (not source["checkedAt"] or not source["verifiedAt"]):
            fail(f"verified source missing checkedAt/verifiedAt: {source['sourceId']}")
        if not source["supports"]:
            fail(f"source missing supports: {source['sourceId']}")

    matrix_price_ids = [row["pricingId"] for row in phase2_matrix]
    if len(matrix_price_ids) != len(set(matrix_price_ids)):
        fail("duplicate phase2 evidence pricingId")
    if set(matrix_price_ids) != set(pricing_ids):
        fail("phase2 evidence matrix must cover every price exactly once")
    for row in phase2_matrix:
        price = price_by_id[row["pricingId"]]
        if row["modelInternalId"] != price["modelInternalId"]:
            fail(f"phase2 evidence row model mismatch: {row['pricingId']}")
        if row["verificationStatus"] != price["verificationStatus"]:
            fail(f"phase2 evidence row verification mismatch: {row['pricingId']}")
        if row["sourceRefs"] != price["sourceRefs"]:
            fail(f"phase2 evidence row sourceRefs mismatch: {row['pricingId']}")
        if row["evidenceCompleteness"] not in {"complete", "partial", "insufficient"}:
            fail(f"invalid phase2 evidenceCompleteness: {row['pricingId']}")
        if price["verificationStatus"] == "verified" and row["evidenceCompleteness"] != "complete":
            fail(f"verified price lacks complete phase2 evidence: {row['pricingId']}")
        if len(row["priceComponents"]) != len(price["charges"]):
            fail(f"phase2 evidence row charge count mismatch: {row['pricingId']}")
        source_domains = sorted({source_by_id[ref]["officialProviderDomain"] for ref in price["sourceRefs"]})
        if row["officialProviderDomain"] != source_domains:
            fail(f"phase2 evidence row source domain mismatch: {row['pricingId']}")

    for row in projection:
        for field in ("id", "provider", "model", "inputPrice", "cachedInputPrice", "outputPrice", "status"):
            if field not in row:
                fail(f"website projection missing {field}")
        if row.get("defaultPriceRecordId") is None:
            if any(row.get(field) is not None for field in ("inputPrice", "cachedInputPrice", "outputPrice")):
                fail(f"projection guessed price without defaultPriceRecordId: {row['id']}")
        elif row["defaultPriceRecordId"] not in price_by_id:
            fail(f"projection points to missing defaultPriceRecordId: {row['id']}")

    if report["candidateUnionCount"] != len(dispositions):
        fail("candidateUnionCount does not match candidate disposition map")
    if report["normalizedCanonicalIdentityCount"] != len(models):
        fail("normalizedCanonicalIdentityCount does not match models")
    if report["duplicateIdentityCount"] != report["candidateUnionCount"] - report["normalizedCanonicalIdentityCount"]:
        fail("duplicateIdentityCount does not match candidateUnionCount - normalizedCanonicalIdentityCount")
    if report["candidateDispositionCounts"] != {
        key: sum(1 for item in dispositions if item["disposition"] == key)
        for key in sorted({item["disposition"] for item in dispositions})
    }:
        fail("candidateDispositionCounts mismatch")
    if report["counts"]["priceRecordCount"] != len(prices):
        fail("report priceRecordCount mismatch")
    if report["counts"]["chargeRecordCount"] != sum(len(item["charges"]) for item in prices):
        fail("report chargeRecordCount mismatch")
    if report["counts"]["sourceRecordCount"] != len(sources):
        fail("report sourceRecordCount mismatch")
    parity = report["websiteCompatibilityPreviewParity"]
    if len(projection) != 32:
        fail("website projection must contain 32 records")
    if len(parity["details"]) != len(projection):
        fail("website parity details must cover every projection row")
    for classification in ("exact_parity", "expected_difference", "unresolved_difference"):
        detail_count = sum(1 for item in parity["details"] if item["classification"] == classification)
        bucket = parity[classification]
        if classification == "exact_parity":
            if detail_count != len(bucket):
                fail("exact parity detail count mismatch")
        elif detail_count != len(bucket):
            fail(f"{classification} detail count mismatch")
    if phase2_conflict["unresolvedIdentitiesBefore"] != report["unresolvedIdentities"]:
        fail("phase2 unresolvedIdentitiesBefore mismatch")
    if phase2_conflict["unresolvedIdentitiesAfter"] != report["unresolvedIdentities"]:
        fail("phase2 unresolvedIdentitiesAfter mismatch")
    if phase2_conflict["gpt4_1Family"]["safeDefaultCalculationPrice"] is not False:
        fail("phase2 GPT-4.1 family must not be safe default")
    if phase2_conflict["grok3"]["replacementInternalId"] is not None:
        fail("phase2 Grok 3 must not infer replacement from redirect")
    if phase2_conflict["deepseekAliases"]["target"] != "deepseek/deepseek-v4-flash":
        fail("phase2 DeepSeek alias target mismatch")
    if phase2_readiness["overall"] != "blocked":
        fail("phase2 cutover readiness must remain blocked")
    readiness_counts = phase2_readiness["counts"]
    if readiness_counts["priceRecordCount"] != len(prices):
        fail("phase2 readiness price count mismatch")
    if readiness_counts["chargeRecordCount"] != sum(len(item["charges"]) for item in prices):
        fail("phase2 readiness charge count mismatch")
    if (
        readiness_counts["completeEvidencePriceRecordCount"]
        + readiness_counts["partialEvidencePriceRecordCount"]
        + readiness_counts["insufficientEvidencePriceRecordCount"]
        != len(prices)
    ):
        fail("phase2 readiness evidence counts mismatch")

    return {
        "candidate_count": len(dispositions),
        "identity_count": len(identities),
        "model_count": len(models),
        "price_count": len(prices),
        "charge_count": sum(len(item["charges"]) for item in prices),
        "source_count": len(sources),
    }


def main() -> None:
    counts = validate_preview()
    print(
        "pricing v2 preview validation ok "
        f"candidates={counts['candidate_count']} identities={counts['identity_count']} models={counts['model_count']} "
        f"prices={counts['price_count']} charges={counts['charge_count']} sources={counts['source_count']}"
    )


if __name__ == "__main__":
    main()
