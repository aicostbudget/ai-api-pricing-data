from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Callable, TextIO

META_URL = "https://aicostbudget.github.io/ai-api-pricing-data/api/v1/meta.json"
PRICES_URL = "https://aicostbudget.github.io/ai-api-pricing-data/api/v1/prices.json"
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


def fetch_json(
    url: str,
    timeout: float,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> tuple[Any, int]:
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
    if not body:
        raise FetchError(url, str(status), "empty response body")
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
            meta, status = fetch_json(META_URL, timeout, opener)
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
                prices, prices_status = fetch_json(PRICES_URL, timeout, opener)
                validate_public_payloads(meta, prices, expected_sha)
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
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--attempts", type=int, default=8)
    parser.add_argument("--interval", type=float, default=8)
    parser.add_argument("--timeout", type=float, default=3)
    args = parser.parse_args()
    try:
        verify_public_deployment(args.expected_sha, args.attempts, args.interval, args.timeout)
    except (ValueError, VerificationError) as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
