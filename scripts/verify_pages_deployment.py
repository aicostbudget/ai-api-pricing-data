from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, TextIO

try:
    from prepare_pages_artifact import ROOT, workspace_pages
except ModuleNotFoundError:
    from scripts.prepare_pages_artifact import ROOT, workspace_pages

META_URL = "https://aicostbudget.github.io/ai-api-pricing-data/api/v1/meta.json"
PRICES_URL = "https://aicostbudget.github.io/ai-api-pricing-data/api/v1/prices.json"
PRICES_CSV_URL = "https://aicostbudget.github.io/ai-api-pricing-data/api/v1/prices.csv"
FULL_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
META_REQUIRED_FIELDS = (
    "dataset_version",
    "generated_at",
    "model_count",
    "provider_count",
    "official_source_count",
    "source_commit_sha",
)
PARITY_FIELDS = (
    "dataset_version",
    "generated_at",
    "model_count",
    "provider_count",
    "official_source_count",
)


class VerificationError(RuntimeError):
    pass


class FetchError(VerificationError):
    def __init__(self, url: str, status: str, detail: str) -> None:
        super().__init__(f"GET failed: endpoint={url} HTTP status={status} detail={detail}")
        self.status = status


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def projection_contract(meta: Any, prices: Any) -> dict[str, Any]:
    """Build an explicit V1 identity/content contract for repo or public payloads."""
    validate_public_payloads(meta, prices, meta.get("source_commit_sha", ""))
    identities: dict[str, str] = {}
    provider_ids: set[str] = set()
    model_ids: set[str] = set()
    for index, row in enumerate(prices["models"]):
        if not isinstance(row, dict):
            raise VerificationError(f"prices.models[{index}] must be an object")
        provider_id = row.get("provider_id")
        model_id = row.get("model_id")
        if not isinstance(provider_id, str) or not provider_id:
            raise VerificationError(f"prices.models[{index}].provider_id must be a non-empty string")
        if not isinstance(model_id, str) or not model_id:
            raise VerificationError(f"prices.models[{index}].model_id must be a non-empty string")
        identity = f"{provider_id}/{model_id}"
        if identity in identities:
            raise VerificationError(f"duplicate model identity: {identity}")
        provider_ids.add(provider_id)
        model_ids.add(model_id)
        identities[identity] = _canonical_digest(row)
    if meta["provider_count"] != len(provider_ids):
        raise VerificationError(
            f"provider count mismatch: meta={meta['provider_count']} actual provider IDs={len(provider_ids)}"
        )
    return {
        "generated_at": meta["generated_at"],
        "model_count": meta["model_count"],
        "provider_count": meta["provider_count"],
        "source_commit_sha": meta["source_commit_sha"],
        "provider_ids": sorted(provider_ids),
        "model_ids": sorted(model_ids),
        "row_count": len(identities),
        "row_digests": dict(sorted(identities.items())),
    }


def validate_projection_parity(
    expected_meta: Any,
    expected_prices: Any,
    actual_meta: Any,
    actual_prices: Any,
) -> None:
    expected = projection_contract(expected_meta, expected_prices)
    actual = projection_contract(actual_meta, actual_prices)
    for field in expected:
        if expected[field] != actual[field]:
            raise VerificationError(
                f"projection parity mismatch for {field}: "
                f"expected={expected[field]!r} actual={actual[field]!r}"
            )


def fetch_bytes(
    url: str,
    timeout: float,
    opener: Callable[..., Any] = urllib.request.urlopen,
    expected_bytes: bytes | None = None,
) -> tuple[bytes, int]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "ai-api-pricing-data-pages-verifier"},
    )
    try:
        with opener(request, timeout=timeout) as response:
            status = response.getcode()
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise FetchError(url, str(exc.code), str(exc.reason)) from exc
    except urllib.error.URLError as exc:
        raise FetchError(url, "unavailable", str(exc.reason)) from exc
    except TimeoutError as exc:
        raise FetchError(url, "timeout", str(exc)) from exc
    if status != 200:
        raise FetchError(url, str(status), "expected HTTP 200")
    if not body:
        raise FetchError(url, str(status), "empty response body")
    if expected_bytes is not None and body != expected_bytes:
        raise VerificationError(f"public bytes differ from committed API: endpoint={url}")
    return body, status


def fetch_json(
    url: str,
    timeout: float,
    opener: Callable[..., Any] = urllib.request.urlopen,
    expected_bytes: bytes | None = None,
) -> tuple[Any, int]:
    body, status = fetch_bytes(url, timeout, opener, expected_bytes)
    try:
        return json.loads(body), status
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(
            f"invalid JSON: endpoint={url} HTTP status={status} detail={exc}"
        ) from exc


def validate_public_payloads(meta: Any, prices: Any, expected_sha: str) -> None:
    if not FULL_GIT_SHA.fullmatch(expected_sha):
        raise VerificationError("expected SHA must be 40 lowercase hexadecimal characters")
    if not isinstance(meta, dict):
        raise VerificationError("meta JSON must be an object")
    missing_meta = [field for field in META_REQUIRED_FIELDS if field not in meta]
    if missing_meta:
        raise VerificationError(f"meta JSON missing required fields: {', '.join(missing_meta)}")
    actual_sha = meta["source_commit_sha"]
    if not isinstance(actual_sha, str) or not FULL_GIT_SHA.fullmatch(actual_sha):
        raise VerificationError("meta.source_commit_sha must be a 40-character lowercase git SHA")
    if actual_sha != expected_sha:
        raise VerificationError(
            f"source commit mismatch: expected SHA={expected_sha} actual SHA={actual_sha}"
        )
    if not isinstance(prices, dict):
        raise VerificationError("prices JSON must be an object")
    missing_prices = [field for field in (*PARITY_FIELDS, "models") if field not in prices]
    if missing_prices:
        raise VerificationError(f"prices JSON missing required fields: {', '.join(missing_prices)}")
    for field in PARITY_FIELDS:
        if meta[field] != prices[field]:
            raise VerificationError(
                f"public payload parity mismatch for {field}: meta={meta[field]!r} prices={prices[field]!r}"
            )
    models = prices["models"]
    if not isinstance(models, list):
        raise VerificationError("prices.models must be an array")
    if isinstance(meta["model_count"], bool) or not isinstance(meta["model_count"], int):
        raise VerificationError("meta.model_count must be an integer")
    if meta["model_count"] != len(models):
        raise VerificationError(
            f"model count mismatch: meta={meta['model_count']} actual public models={len(models)}"
        )


def verify_public_deployment(
    expected_sha: str,
    attempts: int = 8,
    interval: float = 8,
    timeout: float = 3,
    opener: Callable[..., Any] = urllib.request.urlopen,
    sleeper: Callable[[float], None] = time.sleep,
    output: TextIO = sys.stdout,
    expected_files: dict[str, bytes] | None = None,
) -> None:
    if not FULL_GIT_SHA.fullmatch(expected_sha):
        raise VerificationError("expected SHA must be 40 lowercase hexadecimal characters")
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    last_actual = "unavailable"
    last_status = "unavailable"
    last_error = "deployment has not been checked"
    for attempt in range(1, attempts + 1):
        try:
            meta, status = fetch_json(
                META_URL, timeout, opener,
            )
            last_status = str(status)
            last_actual = meta.get("source_commit_sha", "missing") if isinstance(meta, dict) else "unavailable"
            if last_actual != expected_sha:
                last_error = "public meta has not propagated to the expected commit"
                print(
                    f"Pages verification retry: attempt={attempt}/{attempts} endpoint={META_URL} "
                    f"HTTP status={last_status} expected SHA={expected_sha} actual SHA={last_actual}",
                    file=output,
                )
            else:
                prices, prices_status = fetch_json(
                    PRICES_URL, timeout, opener,
                )
                validate_public_payloads(meta, prices, expected_sha)
                if expected_files is not None:
                    expected_meta = json.loads(expected_files["api/v1/meta.json"])
                    expected_prices = json.loads(expected_files["api/v1/prices.json"])
                    validate_projection_parity(expected_meta, expected_prices, meta, prices)
                    fetch_bytes(PRICES_CSV_URL, timeout, opener, expected_files["api/v1/prices.csv"])
                print(
                    f"Pages verification passed: attempt={attempt}/{attempts} "
                    f"meta HTTP status={status} prices HTTP status={prices_status} SHA={expected_sha}",
                    file=output,
                )
                return
        except (FetchError, VerificationError) as exc:
            last_error = str(exc)
            if isinstance(exc, FetchError):
                last_status = exc.status
            print(
                f"Pages verification retry: attempt={attempt}/{attempts} endpoint={META_URL} "
                f"HTTP status={last_status} expected SHA={expected_sha} actual SHA={last_actual} error={exc}",
                file=output,
            )
        if attempt < attempts:
            sleeper(interval)
    raise VerificationError(
        f"Pages verification failed after {attempts} attempts: endpoint={META_URL} "
        f"HTTP status={last_status} expected SHA={expected_sha} actual SHA={last_actual} "
        f"last error={last_error}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the deployed public GitHub Pages JSON.")
    parser.add_argument("--release-sha", required=True, help="Approved main revision that produced the public API")
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--attempts", type=int, default=8)
    parser.add_argument("--interval", type=float, default=8)
    parser.add_argument("--timeout", type=float, default=3)
    args = parser.parse_args()
    try:
        files, release_sha = workspace_pages(args.source_root, args.release_sha)
        print(f"Pages release revision: {release_sha}")
        verify_public_deployment(
            release_sha, args.attempts, args.interval, args.timeout, expected_files=files,
        )
    except (ValueError, VerificationError, OSError, subprocess.SubprocessError) as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
