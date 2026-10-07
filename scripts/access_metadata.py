"""Access facts and binding decisions; independent of pricing and production eligibility."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

ACCESS_STATUSES = {"public", "existing_users_only", "invite_only", "restricted", "unknown"}
BINDING_STATUSES = {"approved", "unresolved"}
OFFICIAL_HOSTS = {
    "openai": ("openai.com",), "anthropic": ("anthropic.com", "claude.com"),
    "google-gemini": ("google.dev", "google.com"), "xai": ("x.ai",),
    "cohere": ("cohere.com",), "deepseek": ("deepseek.com",),
    "mistral-ai": ("mistral.ai",), "moonshot-ai": ("kimi.ai", "moonshot.ai", "moonshot.cn"),
    "aws": ("amazon.com", "amazonaws.com"), "azure": ("microsoft.com", "azure.com"),
    "google-cloud": ("google.com",),
}
ACCESS_FIELDS = ("access_status", "access_evidence", "access_checked_at", "binding_status", "binding_evidence")
V2_FIELDS = ("accessStatus", "accessEvidence", "accessCheckedAt", "accessAuthority", "bindingStatus", "bindingEvidence")


def official_hostname(provider: str, url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise ValueError("ACCESS_OFFICIAL_HOST: HTTPS official hostname required")
    if not any(host == allowed or host.endswith("." + allowed) for allowed in OFFICIAL_HOSTS.get(provider, ())):
        raise ValueError(f"ACCESS_OFFICIAL_HOST: {provider} {host}")
    return host


def checked_timestamp(value: Any, now: datetime | None = None) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", value):
        raise ValueError("ACCESS_CHECKED_AT: UTC timestamp ending Z required")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("ACCESS_CHECKED_AT: invalid timestamp") from exc
    if parsed > (now or datetime.now(timezone.utc)):
        raise ValueError("ACCESS_CHECKED_AT: future timestamp")
    return value


def canonical_facts(record: dict[str, Any] | None, camel: bool = False) -> dict[str, Any]:
    record = record or {}
    names = ("accessStatus", "accessEvidence", "accessCheckedAt", "bindingStatus", "bindingEvidence") if camel else ACCESS_FIELDS
    defaults = ("unknown", [], None, "unresolved", [])
    facts = {name: record.get(source, default) for name, source, default in zip(ACCESS_FIELDS, names, defaults)}
    if camel:
        for field in ("access_evidence", "binding_evidence"):
            facts[field] = [{({"claimType": "claim_type", "officialModelId": "official_model_id", "entitlementScopeMatches": "entitlement_scope_matches"}.get(k, k)): v
                             for k, v in claim.items()} for claim in facts[field]]
    return facts


def validate_facts(facts: dict[str, Any], provider: str, now: datetime | None = None) -> None:
    status = facts.get("access_status", "unknown")
    if status not in ACCESS_STATUSES:
        raise ValueError("ACCESS_ENUM: unsupported status")
    evidence = facts.get("access_evidence", [])
    if not isinstance(evidence, list):
        raise ValueError("ACCESS_EVIDENCE: array required")
    if status == "unknown" and evidence:
        raise ValueError("ACCESS_UNKNOWN: no verified access claim may be asserted")
    if status != "unknown":
        if not evidence:
            raise ValueError("ACCESS_EVIDENCE: known status requires evidence")
        checked_timestamp(facts.get("access_checked_at"), now)
    elif facts.get("access_checked_at") is not None:
        raise ValueError("ACCESS_UNKNOWN: successful claim date must be null")
    for claim in evidence:
        if not isinstance(claim, dict) or any(not isinstance(claim.get(k), str) or not claim[k].strip() for k in ("url", "title", "claim_type", "official_model_id", "scope")):
            raise ValueError("ACCESS_EVIDENCE: exact model and claim scope required")
        if claim["claim_type"] != "official_access_" + status:
            raise ValueError("ACCESS_CLAIM: status must match an access-specific claim")
        official_hostname(provider, claim["url"])
    binding = facts.get("binding_status", "unresolved")
    if binding not in BINDING_STATUSES:
        raise ValueError("BINDING_ENUM: unsupported status")
    binding_evidence = facts.get("binding_evidence", [])
    if not isinstance(binding_evidence, list) or binding == "approved" and not binding_evidence:
        raise ValueError("BINDING_EVIDENCE: approval requires independent evidence")
    for claim in binding_evidence:
        if not isinstance(claim, dict) or any(not isinstance(claim.get(k), str) or not claim[k].strip() for k in ("url", "title", "claim_type", "official_model_id", "reason")):
            raise ValueError("BINDING_EVIDENCE: exact identity and decision reason required")
        expected = "official_identity_binding" if binding == "approved" else "official_identity_unresolved"
        if claim["claim_type"] != expected:
            raise ValueError("BINDING_CLAIM: decision mismatch")
        official_hostname(provider, claim["url"])
        if "entitlement_scope_matches" in claim and (not isinstance(claim["entitlement_scope_matches"], bool) or binding != "approved"):
            raise ValueError("ACCESS_ALIAS: scope proof must be an explicit approved-binding boolean")


def resolve_authoritative_facts(public: dict[str, Any] | None, seed: dict[str, Any] | None, provider: str) -> tuple[dict[str, Any], str]:
    canonical = canonical_facts(public)
    website = canonical_facts(seed, camel=True)
    validate_facts(canonical, provider)
    if seed and any(k in seed for k in ("accessStatus", "accessEvidence", "accessCheckedAt", "bindingStatus", "bindingEvidence")):
        validate_facts(website, provider)
        if public is not None and canonical != website:
            raise ValueError("ACCESS_AUTHORITY_CONFLICT: canonical and Website access/binding facts differ")
    if public is not None:
        return canonical, "canonical"
    if seed and "accessStatus" in seed:
        revision = seed.get("accessAuthorityRevision")
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("ACCESS_SEED_REVISION: pinned Website base revision required")
        return website, "website_only_seed"
    return canonical_facts(None), "unknown"


def source_entries(facts: dict[str, Any]):
    for field, purpose in (("access_evidence", "access"), ("binding_evidence", "binding")):
        for claim in facts[field]:
            yield claim, purpose


def register_sources(source_urls: dict[str, dict[str, Any]], facts: dict[str, Any], provider: str) -> None:
    for claim, purpose in source_entries(facts):
        url = claim["url"]
        if url in source_urls:
            # Preserve pricing/release title, timestamps and source identity.
            source_urls[url]["supports"] = sorted(set(source_urls[url]["supports"]) | {purpose})
        else:
            source_urls[url] = {
                "providerId": provider, "url": url, "sourceType": "official_model_docs",
                "title": claim["title"], "officialProviderDomain": official_hostname(provider, url),
                "accessedAt": facts["access_checked_at"], "checkedAt": facts["access_checked_at"],
                "verifiedAt": facts["access_checked_at"], "supports": [purpose], "verificationStatus": "verified",
            }


def project_facts(facts: dict[str, Any], source_by_url: dict[str, str], kind: str, revision: str | None = None) -> dict[str, Any]:
    def evidence(field: str):
        return [{"sourceRef": source_by_url[c["url"]], "title": c["title"], "claimType": c["claim_type"],
                 "officialModelId": c["official_model_id"], **({"scope": c["scope"]} if "scope" in c else {"reason": c["reason"]}), **({"entitlementScopeMatches": c["entitlement_scope_matches"]} if "entitlement_scope_matches" in c else {})}
                for c in facts[field]]
    digest = hashlib.sha256(json.dumps(facts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "accessStatus": facts["access_status"], "accessEvidence": evidence("access_evidence"),
        "accessCheckedAt": facts["access_checked_at"],
        "accessAuthority": {"kind": kind, "baseRevision": revision, "factSha256": digest, "revisionScope": "base_revision_plus_fact_digest"},
        "bindingStatus": facts["binding_status"], "bindingEvidence": evidence("binding_evidence"),
    }


def resolve_projection_metadata(row: dict[str, Any], sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result = {k: row[k] for k in V2_FIELDS if k in row}
    for field in ("accessEvidence", "bindingEvidence"):
        result[field] = [{**e, "url": sources[e["sourceRef"]]["url"]} for e in row.get(field, [])]
    return result


def validate_projected_metadata(row: dict[str, Any], sources: dict[str, dict[str, Any]], prices: list[dict[str, Any]]) -> None:
    provider = row.get("providerId") or row.get("provider")
    def evidence(field: str):
        entries = []
        for claim in row.get(field, []):
            source = sources.get(claim["sourceRef"])
            purpose = "access" if field == "accessEvidence" else "binding"
            if not source or source["providerId"] != provider or purpose not in source["supports"]:
                raise ValueError("ACCESS_SOURCE_ROUNDTRIP: missing provider/claim source")
            if claim.get("url", source["url"]) != source["url"]:
                raise ValueError("ACCESS_SOURCE_ROUNDTRIP: evidence URL mismatch")
            entries.append({"url": source["url"], "title": claim["title"], "claim_type": claim["claimType"], "official_model_id": claim["officialModelId"],
                            **({"scope": claim["scope"]} if purpose == "access" else {"reason": claim["reason"]}), **({"entitlement_scope_matches": claim["entitlementScopeMatches"]} if "entitlementScopeMatches" in claim else {})})
        return entries
    facts = {"access_status": row.get("accessStatus", "unknown"), "access_checked_at": row.get("accessCheckedAt"),
             "access_evidence": evidence("accessEvidence"), "binding_status": row.get("bindingStatus", "unresolved"), "binding_evidence": evidence("bindingEvidence")}
    validate_facts(facts, provider)
    authority = row.get("accessAuthority")
    if authority is not None:
        digest = hashlib.sha256(json.dumps(facts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if authority.get("kind") not in {"canonical", "website_only_seed", "approved_alias", "unknown"} or authority.get("factSha256") != digest:
            raise ValueError("ACCESS_AUTHORITY: invalid authority or fact digest")
        if authority.get("revisionScope") != "base_revision_plus_fact_digest":
            raise ValueError("ACCESS_AUTHORITY: revision scope required")
        if authority["kind"] in {"canonical", "website_only_seed"} and not re.fullmatch(r"[0-9a-f]{40}", authority.get("baseRevision") or ""):
            raise ValueError("ACCESS_AUTHORITY: pinned base revision required")
    for price in prices:
        for ref in price["sourceRefs"]:
            source = sources[ref]
            if set(source["supports"]) <= {"access", "binding"}:
                raise ValueError("ACCESS_PRICE_PROVENANCE: access-only evidence in price sourceRefs")


def inherit_alias_access(identity: dict[str, Any], target: dict[str, Any], entitlement_scope_matches: bool) -> dict[str, Any]:
    if identity.get("bindingStatus") != "approved" or not entitlement_scope_matches:
        raise ValueError("ACCESS_ALIAS: approved binding and identical entitlement scope required")
    if identity.get("aliasTargetInternalId") != target.get("internalId"):
        raise ValueError("ACCESS_ALIAS: target binding mismatch")
    return {k: target[k] for k in ("accessStatus", "accessEvidence", "accessCheckedAt")}


def apply_approved_aliases(identities: list[dict[str, Any]], sources: dict[str, dict[str, Any]], canonical_ids: set[str]) -> None:
    """Only explicit identity/scope evidence can inherit; billing targets never confer access."""
    by_id = {row["internalId"]: row for row in identities}
    by_url = {source["url"]: ref for ref, source in sources.items()}
    for row in identities:
        if row["internalId"] in canonical_ids or row.get("identityType") != "alias" or row.get("accessStatus") != "unknown":
            continue
        target = by_id.get(row.get("aliasTargetInternalId"))
        if target is None or target.get("bindingStatus") != "approved" or target.get("accessStatus") == "unknown":
            continue
        proof = any(claim.get("entitlementScopeMatches") is True and claim.get("officialModelId") == target.get("canonicalOfficialId")
                    for claim in row.get("bindingEvidence", []))
        if not proof:
            continue
        inherited = inherit_alias_access(row, target, True)
        combined = {**row, **inherited}
        facts = canonical_facts(resolve_projection_metadata(combined, sources), camel=True)
        # sourceRef is projection provenance, not part of the authority fact digest.
        for field in ("access_evidence", "binding_evidence"):
            facts[field] = [{k:v for k,v in claim.items() if k != "sourceRef"} for claim in facts[field]]
        validate_facts(facts, row["providerId"])
        row.update(project_facts(facts, by_url, "approved_alias", (row.get("accessAuthority") or {}).get("baseRevision")))
