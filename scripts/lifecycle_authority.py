"""Closed, offline lifecycle evidence contract; never an access or price verifier."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_PATH = ROOT / "data/canonical/model-lifecycle-evidence.json"
SCHEMA_PATH = ROOT / "schema/model-lifecycle-evidence.schema.json"
MINI_ID = "openai/gpt-4.1-mini"
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("LIFECYCLE_AUTHORITY: duplicate JSON key " + key)
        result[key] = value
    return result


def parsed(data: bytes) -> Any:
    try:
        return json.loads(data, object_pairs_hook=_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("LIFECYCLE_AUTHORITY: invalid JSON") from exc


def _schema_check(rule: dict[str, Any], value: Any, location: str = "authority") -> None:
    """Evaluate the deliberately small JSON Schema vocabulary used by this contract.

    No third-party runtime dependency is needed by the existing stdlib-only CI.
    Unsupported keywords fail closed rather than silently weakening validation.
    """
    allowed = {"$schema", "$id", "title", "description", "type", "const", "properties",
               "required", "additionalProperties", "items", "minItems", "maxItems",
               "uniqueItems", "pattern", "format"}
    if not isinstance(rule, dict) or set(rule) - allowed:
        raise ValueError("LIFECYCLE_SCHEMA: unsupported or malformed schema")
    kind = rule.get("type")
    if kind not in {"array", "object", "string"}:
        raise ValueError("LIFECYCLE_SCHEMA: unsupported type")
    valid = {"array": isinstance(value, list), "object": isinstance(value, dict),
             "string": isinstance(value, str)}[kind]
    if not valid or ("const" in rule and value != rule["const"]):
        raise ValueError("LIFECYCLE_AUTHORITY: type or reviewed value mismatch at " + location)
    if kind == "array":
        if not rule.get("minItems", 0) <= len(value) <= rule.get("maxItems", len(value)):
            raise ValueError("LIFECYCLE_AUTHORITY: exact record/snapshot count required")
        if rule.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            raise ValueError("LIFECYCLE_AUTHORITY: duplicate entries")
        for item in value:
            _schema_check(rule["items"], item, location + "[]")
    elif kind == "object":
        properties = rule.get("properties", {})
        required = rule.get("required", [])
        if not isinstance(properties, dict) or not isinstance(required, list):
            raise ValueError("LIFECYCLE_SCHEMA: malformed object contract")
        if set(required) - set(value) or (rule.get("additionalProperties") is False and set(value) - set(properties)):
            raise ValueError("LIFECYCLE_AUTHORITY: missing or forbidden fields")
        for key, item in value.items():
            if key in properties:
                _schema_check(properties[key], item, location + "." + key)
    else:
        if "pattern" in rule and not re.search(rule["pattern"], value):
            raise ValueError("LIFECYCLE_AUTHORITY: invalid timestamp/string at " + location)
        if "format" in rule:
            if rule["format"] != "date-time" or not UTC_TIMESTAMP.fullmatch(value):
                raise ValueError("LIFECYCLE_AUTHORITY: UTC timestamp required")
            try:
                checked = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("LIFECYCLE_AUTHORITY: invalid UTC timestamp") from exc
            if checked > datetime.now(timezone.utc):
                raise ValueError("LIFECYCLE_AUTHORITY: future observation")


def validate_authority(records: Any, schema: dict[str, Any] | None = None) -> dict[str, Any]:
    if schema is None:
        schema = parsed(SCHEMA_PATH.read_bytes())
    fields = {"providerId", "modelId", "canonicalInternalId", "officialModelUrl",
              "officialDeprecationsUrl", "observedModelLabel", "documentedSnapshotIds",
              "deprecationEvidenceResult", "normalizedLifecycleStatus", "lifecycleCheckedAt", "evidenceScope"}
    if not isinstance(schema, dict) or not isinstance(schema.get("items"), dict):
        raise ValueError("LIFECYCLE_SCHEMA: object schema and items required")
    item = schema["items"]
    if (schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema"
            or schema.get("type") != "array" or schema.get("minItems") != 1 or schema.get("maxItems") != 1
            or item.get("additionalProperties") is not False
            or set(item.get("required", [])) != fields or set(item.get("properties", {})) != fields):
        raise ValueError("LIFECYCLE_SCHEMA: closed single-mini contract required")
    _schema_check(schema, records)
    record = records[0]
    # Semantic checks remain strict even if a source schema is accidentally widened.
    expected = {"providerId": "openai", "modelId": "gpt-4.1-mini", "canonicalInternalId": MINI_ID,
                "officialModelUrl": "https://developers.openai.com/api/docs/models/gpt-4.1-mini",
                "officialDeprecationsUrl": "https://developers.openai.com/api/docs/deprecations",
                "observedModelLabel": "Default", "documentedSnapshotIds": ["gpt-4.1-mini-2025-04-14"],
                "deprecationEvidenceResult": "not_listed", "normalizedLifecycleStatus": "active"}
    if any(record[key] != value for key, value in expected.items()):
        raise ValueError("LIFECYCLE_AUTHORITY: unapproved identity, source or normalization")
    return record


def load_authority() -> dict[str, Any]:
    try:
        return validate_authority(parsed(AUTHORITY_PATH.read_bytes()))
    except OSError as exc:
        raise ValueError("LIFECYCLE_AUTHORITY: missing authority/schema input") from exc


def validate_unresolved_conflict(model: dict[str, Any]) -> None:
    try:
        from access_metadata import official_hostname, checked_timestamp
    except ModuleNotFoundError:
        from scripts.access_metadata import official_hostname, checked_timestamp
    conflict = model.get("lifecycle_conflict")
    required = {"resolution", "observed_at", "sources", "previous_assertion", "authority_analysis"}
    if not isinstance(conflict, dict) or set(conflict) != required or conflict["resolution"] != "unresolved":
        raise ValueError("LIFECYCLE_CONFLICT: explicit unresolved evidence required")
    checked_timestamp(conflict["observed_at"])
    sources = conflict["sources"]
    if not isinstance(sources, list) or len(sources) < 2 or len({s.get("shutdown_date") for s in sources}) < 2:
        raise ValueError("LIFECYCLE_CONFLICT: conflicting dated official sources required")
    for source in sources:
        official_hostname(model["provider_id"], source["url"])
        datetime.fromisoformat(source["shutdown_date"])
    if model["status"] != "unknown" or model.get("lifecycle") or model.get("price_records") or any(model["pricing"].get(k) is not None for k in ("unit", "input", "output", "cached_input")):
        raise ValueError("LIFECYCLE_CONFLICT: cannot assert certain lifecycle or unsupported prices")
