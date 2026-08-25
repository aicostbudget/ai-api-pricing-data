from __future__ import annotations

import argparse
import csv
import io
import json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TextIO

try:
    from lib import ROOT
except ModuleNotFoundError:
    from scripts.lib import ROOT


HF_DIR = ROOT / "huggingface"
HF_RAW_BASE_URL = (
    "https://huggingface.co/datasets/aicostbudget-ai/ai-api-pricing/resolve/main"
)
ARTIFACTS = ("prices.json", "prices.csv", "train.csv", "meta.json")
MISSING = object()


@dataclass(frozen=True)
class Drift:
    artifact: str
    field: str
    expected: Any
    actual: Any
    model_id: str | None = None
    semantic: bool = False


class DataDriftError(Exception):
    def __init__(self, drifts: list[Drift]):
        super().__init__("Hugging Face production data differs from the expected artifacts")
        self.drifts = drifts


class NetworkFailureError(Exception):
    pass


FetchBytes = Callable[[str, float], bytes]


def _display(value: Any) -> str:
    if value is MISSING:
        return "<missing>"
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _download(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "aicostbudget-hf-production-parity/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_production_snapshot(
    base_url: str,
    timeout: float,
    fetch_bytes: FetchBytes = _download,
    cache_bust: Callable[[], str] = lambda: uuid.uuid4().hex,
) -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    for artifact in ARTIFACTS:
        separator = "&" if "?" in base_url else "?"
        url = f"{base_url.rstrip('/')}/{artifact}{separator}download=true&cache_bust={cache_bust()}"
        try:
            snapshot[artifact] = fetch_bytes(url, timeout)
        except (OSError, TimeoutError, urllib.error.URLError, urllib.error.HTTPError) as error:
            raise NetworkFailureError(f"{artifact}: {type(error).__name__}: {error}") from error
    return snapshot


def _compare_value(
    expected: Any,
    actual: Any,
    *,
    artifact: str,
    field: str,
    model_id: str | None = None,
) -> list[Drift]:
    if isinstance(expected, dict) and isinstance(actual, dict):
        drifts: list[Drift] = []
        for key in sorted(set(expected) | set(actual)):
            child_field = f"{field}.{key}" if field else key
            if key not in expected:
                drifts.append(Drift(artifact, child_field, MISSING, actual[key], model_id))
            elif key not in actual:
                drifts.append(Drift(artifact, child_field, expected[key], MISSING, model_id))
            else:
                drifts.extend(
                    _compare_value(
                        expected[key],
                        actual[key],
                        artifact=artifact,
                        field=child_field,
                        model_id=model_id,
                    )
                )
        return drifts
    if isinstance(expected, list) and isinstance(actual, list):
        drifts = []
        if len(expected) != len(actual):
            drifts.append(Drift(artifact, f"{field}.length", len(expected), len(actual), model_id))
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            drifts.extend(
                _compare_value(
                    expected_item,
                    actual_item,
                    artifact=artifact,
                    field=f"{field}[{index}]",
                    model_id=model_id,
                )
            )
        return drifts
    if expected != actual or type(expected) is not type(actual):
        return [Drift(artifact, field, expected, actual, model_id)]
    return []


def _record_identity(record: dict[str, Any]) -> tuple[Any, Any]:
    return record.get("provider_id", MISSING), record.get("model_id", MISSING)


def _compare_prices_json(expected_bytes: bytes, actual_bytes: bytes) -> tuple[list[Drift], int]:
    artifact = "prices.json"
    try:
        expected = json.loads(expected_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"local {artifact} is invalid: {error}") from error
    try:
        actual = json.loads(actual_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return [Drift(artifact, "<document>", "valid JSON", f"invalid JSON: {error}")], 0

    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return _compare_value(expected, actual, artifact=artifact, field="<document>"), 0

    drifts: list[Drift] = []
    for key in sorted((set(expected) | set(actual)) - {"records"}):
        if key not in expected:
            drifts.append(Drift(artifact, key, MISSING, actual[key]))
        elif key not in actual:
            drifts.append(Drift(artifact, key, expected[key], MISSING))
        else:
            drifts.extend(_compare_value(expected[key], actual[key], artifact=artifact, field=key))

    expected_records = expected.get("records", MISSING)
    actual_records = actual.get("records", MISSING)
    if not isinstance(expected_records, list) or not isinstance(actual_records, list):
        drifts.extend(
            _compare_value(
                expected_records,
                actual_records,
                artifact=artifact,
                field="records",
            )
        )
        return drifts, 0

    def index_records(records: list[Any], side: str) -> tuple[dict[tuple[Any, Any], dict[str, Any]], list[Drift]]:
        indexed: dict[tuple[Any, Any], dict[str, Any]] = {}
        problems: list[Drift] = []
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                problems.append(Drift(artifact, f"records[{index}]", "object", record))
                continue
            identity = _record_identity(record)
            if identity in indexed:
                problems.append(
                    Drift(artifact, "record_identity", "unique provider_id/model_id", identity, str(identity[1]))
                )
            indexed[identity] = record
        return indexed, problems

    expected_by_key, expected_problems = index_records(expected_records, "expected")
    if expected_problems:
        raise ValueError(f"local {artifact} has invalid or duplicate record identities")
    actual_by_key, actual_problems = index_records(actual_records, "actual")
    drifts.extend(actual_problems)

    for identity in sorted(set(expected_by_key) | set(actual_by_key), key=lambda item: str(item)):
        model_id = None if identity[1] is MISSING else str(identity[1])
        if identity not in expected_by_key:
            drifts.append(Drift(artifact, "record", MISSING, actual_by_key[identity], model_id))
        elif identity not in actual_by_key:
            drifts.append(Drift(artifact, "record", expected_by_key[identity], MISSING, model_id))
        else:
            drifts.extend(
                _compare_value(
                    expected_by_key[identity],
                    actual_by_key[identity],
                    artifact=artifact,
                    field="",
                    model_id=model_id,
                )
            )

    semantic_drifts: list[Drift] = []
    for identity, expected_record in expected_by_key.items():
        actual_record = actual_by_key.get(identity)
        if actual_record is None:
            continue
        model_id = str(expected_record.get("model_id", identity[1]))
        status = expected_record.get("verification_status")
        fields = ["verification_status", "checked_at"]
        if status == "verified" and expected_record.get("last_verified_at") is not None:
            fields.append("last_verified_at")
        if status in {"review_required", "partially_verified"}:
            fields.append("last_verified_at")
        for field in fields:
            expected_value = expected_record.get(field, MISSING)
            actual_value = actual_record.get(field, MISSING)
            if expected_value != actual_value or type(expected_value) is not type(actual_value):
                semantic_drifts.append(
                    Drift(artifact, field, expected_value, actual_value, model_id, semantic=True)
                )

    existing = {(d.artifact, d.model_id, d.field, _display(d.expected), _display(d.actual)) for d in drifts}
    for drift in semantic_drifts:
        key = (drift.artifact, drift.model_id, drift.field, _display(drift.expected), _display(drift.actual))
        if key not in existing:
            drifts.append(drift)
            existing.add(key)
        else:
            index = next(
                i
                for i, current in enumerate(drifts)
                if (current.artifact, current.model_id, current.field, _display(current.expected), _display(current.actual)) == key
            )
            drifts[index] = drift
    return drifts, len(semantic_drifts)


def _read_csv(data: bytes, artifact: str, side: str) -> tuple[list[str], list[dict[str, str]]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        if side == "expected":
            raise ValueError(f"local {artifact} is not UTF-8: {error}") from error
        raise DataDriftError([Drift(artifact, "<document>", "valid UTF-8 CSV", str(error))]) from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    return list(reader.fieldnames or []), list(reader)


def _compare_csv(expected_bytes: bytes, actual_bytes: bytes, artifact: str) -> list[Drift]:
    expected_header, expected_rows = _read_csv(expected_bytes, artifact, "expected")
    actual_header, actual_rows = _read_csv(actual_bytes, artifact, "actual")
    drifts: list[Drift] = []
    if expected_header != actual_header:
        drifts.append(Drift(artifact, "header", expected_header, actual_header))
    if len(expected_rows) != len(actual_rows):
        drifts.append(Drift(artifact, "row_count", len(expected_rows), len(actual_rows)))

    identity_fields = ("provider_id", "model_id")
    if not all(field in expected_header and field in actual_header for field in identity_fields):
        return drifts

    def index(rows: list[dict[str, str]]) -> tuple[dict[tuple[str, str], dict[str, str]], list[Drift]]:
        indexed: dict[tuple[str, str], dict[str, str]] = {}
        problems: list[Drift] = []
        for row in rows:
            identity = (row.get("provider_id", ""), row.get("model_id", ""))
            if identity in indexed:
                problems.append(Drift(artifact, "row_identity", "unique", identity, identity[1]))
            indexed[identity] = row
        return indexed, problems

    expected_by_key, expected_problems = index(expected_rows)
    if expected_problems:
        raise ValueError(f"local {artifact} has duplicate row identities")
    actual_by_key, actual_problems = index(actual_rows)
    drifts.extend(actual_problems)
    for identity in sorted(set(expected_by_key) | set(actual_by_key)):
        model_id = identity[1]
        if identity not in expected_by_key:
            drifts.append(Drift(artifact, "row", MISSING, actual_by_key[identity], model_id))
        elif identity not in actual_by_key:
            drifts.append(Drift(artifact, "row", expected_by_key[identity], MISSING, model_id))
        else:
            expected_row = expected_by_key[identity]
            actual_row = actual_by_key[identity]
            for field in sorted(set(expected_row) | set(actual_row)):
                expected_value = expected_row.get(field, MISSING)
                actual_value = actual_row.get(field, MISSING)
                if expected_value != actual_value:
                    drifts.append(Drift(artifact, field, expected_value, actual_value, model_id))
    return drifts


def compare_snapshot(expected_dir: Path, production: dict[str, bytes]) -> tuple[list[Drift], int, int]:
    expected = {name: (expected_dir / name).read_bytes() for name in ARTIFACTS}
    drifts, semantic_count = _compare_prices_json(expected["prices.json"], production["prices.json"])
    for artifact in ("prices.csv", "train.csv"):
        drifts.extend(_compare_csv(expected[artifact], production[artifact], artifact))
    try:
        expected_meta = json.loads(expected["meta.json"].decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"local meta.json is invalid: {error}") from error
    try:
        actual_meta = json.loads(production["meta.json"].decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        drifts.append(Drift("meta.json", "<document>", "valid JSON", f"invalid JSON: {error}"))
    else:
        drifts.extend(_compare_value(expected_meta, actual_meta, artifact="meta.json", field=""))
    record_count = len(expected_meta) if not isinstance(expected_meta, dict) else 0
    expected_prices = json.loads(expected["prices.json"].decode("utf-8-sig"))
    if isinstance(expected_prices, dict) and isinstance(expected_prices.get("records"), list):
        record_count = len(expected_prices["records"])
    return drifts, semantic_count, record_count


def _print_drifts(drifts: list[Drift], output: TextIO, limit: int = 50) -> None:
    for drift in drifts[:limit]:
        print(f"artifact: {drift.artifact}", file=output)
        if drift.model_id is not None:
            print(f"model_id: {drift.model_id}", file=output)
        print(f"field: {drift.field or '<document>'}", file=output)
        print(f"expected: {_display(drift.expected)}", file=output)
        print(f"actual: {_display(drift.actual)}", file=output)
        print(file=output)
    if len(drifts) > limit:
        print(f"... {len(drifts) - limit} additional drift(s) omitted", file=output)


def check_with_retry(
    *,
    expected_dir: Path = HF_DIR,
    base_url: str = HF_RAW_BASE_URL,
    attempts: int = 3,
    retry_delay: float = 45,
    timeout: float = 20,
    fetch_bytes: FetchBytes = _download,
    sleep: Callable[[float], None] = time.sleep,
    cache_bust: Callable[[], str] = lambda: uuid.uuid4().hex,
    output: TextIO,
) -> int:
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    last_network_error: NetworkFailureError | None = None
    last_drifts: list[Drift] | None = None
    for attempt in range(1, attempts + 1):
        try:
            production = fetch_production_snapshot(
                base_url,
                timeout,
                fetch_bytes=fetch_bytes,
                cache_bust=cache_bust,
            )
            drifts, semantic_count, record_count = compare_snapshot(expected_dir, production)
        except NetworkFailureError as error:
            last_network_error = error
            last_drifts = None
            print(f"attempt {attempt}/{attempts}: NETWORK_FAILURE: {error}", file=output)
        except DataDriftError as error:
            last_drifts = error.drifts
            last_network_error = None
            print(f"attempt {attempt}/{attempts}: DATA_DRIFT", file=output)
            _print_drifts(last_drifts, output)
        else:
            if not drifts:
                print("HF production parity OK", file=output)
                print(f"records: {record_count}", file=output)
                for artifact in ARTIFACTS:
                    print(f"{artifact}: PASS", file=output)
                print(f"semantic violations: {semantic_count}", file=output)
                return record_count
            last_drifts = drifts
            last_network_error = None
            print(f"attempt {attempt}/{attempts}: DATA_DRIFT", file=output)
            _print_drifts(drifts, output)
        if attempt < attempts:
            print(f"retrying in {retry_delay:g} seconds", file=output)
            sleep(retry_delay)

    if last_network_error is not None:
        print("HF production check unavailable", file=output)
        print(f"NETWORK_FAILURE: {last_network_error}", file=output)
        raise last_network_error
    assert last_drifts is not None
    print("HF production drift detected", file=output)
    print("DATA_DRIFT", file=output)
    _print_drifts(last_drifts, output)
    raise DataDriftError(last_drifts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare approved GitHub Hugging Face artifacts with the live Hugging Face main branch."
    )
    parser.add_argument("--expected-dir", type=Path, default=HF_DIR)
    parser.add_argument("--base-url", default=HF_RAW_BASE_URL)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=45)
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args()
    import sys

    try:
        check_with_retry(
            expected_dir=args.expected_dir,
            base_url=args.base_url,
            attempts=args.attempts,
            retry_delay=args.retry_delay,
            timeout=args.timeout,
            output=sys.stdout,
        )
    except (DataDriftError, NetworkFailureError) as error:
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
