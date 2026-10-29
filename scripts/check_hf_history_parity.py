"""Compare the committed price-history CSVs with the live Hugging Face price-history dataset.

Prints HISTORY_PARITY: PASS when every CSV is byte-identical (after CRLF folding), DATA_DRIFT
with the drifting files otherwise, and NETWORK_FAILURE when production cannot be read.
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import uuid
from pathlib import Path
from typing import Callable, TextIO

try:
    from check_hf_production_parity import FetchBytes, NetworkFailureError, _download
    from export_huggingface_history import HISTORY_HF_DIR
    from publish_huggingface import DEFAULT_HISTORY_REPO_ID, HISTORY_ARTIFACTS
except ModuleNotFoundError:
    from scripts.check_hf_production_parity import FetchBytes, NetworkFailureError, _download
    from scripts.export_huggingface_history import HISTORY_HF_DIR
    from scripts.publish_huggingface import DEFAULT_HISTORY_REPO_ID, HISTORY_ARTIFACTS


HISTORY_RAW_BASE_URL = f"https://huggingface.co/datasets/{DEFAULT_HISTORY_REPO_ID}/resolve/main"


class HistoryDriftError(Exception):
    def __init__(self, files: list[str]):
        super().__init__(f"Hugging Face price history differs: {', '.join(files)}")
        self.files = files


def _normalized(value: bytes) -> bytes:
    return value.replace(b"\r\n", b"\n")


def drifting_files(
    expected_dir: Path,
    base_url: str,
    timeout: float,
    fetch_bytes: FetchBytes = _download,
    cache_bust: Callable[[], str] = lambda: uuid.uuid4().hex,
) -> list[str]:
    drift = []
    for name in HISTORY_ARTIFACTS:
        url = f"{base_url.rstrip('/')}/{name}?download=true&cache_bust={cache_bust()}"
        try:
            actual = fetch_bytes(url, timeout)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                drift.append(name)
                continue
            raise NetworkFailureError(f"{name}: HTTPError: {error}") from error
        except (OSError, TimeoutError, urllib.error.URLError) as error:
            raise NetworkFailureError(f"{name}: {type(error).__name__}: {error}") from error
        if _normalized(actual) != _normalized((expected_dir / name).read_bytes()):
            drift.append(name)
    return drift


def check_with_retry(
    *,
    expected_dir: Path = HISTORY_HF_DIR,
    base_url: str = HISTORY_RAW_BASE_URL,
    attempts: int = 3,
    retry_delay: float = 45,
    timeout: float = 20,
    fetch_bytes: FetchBytes = _download,
    sleep: Callable[[float], None] = time.sleep,
    output: TextIO,
) -> None:
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    last_network_error: NetworkFailureError | None = None
    last_drift: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            last_drift = drifting_files(expected_dir, base_url, timeout, fetch_bytes)
            last_network_error = None
        except NetworkFailureError as error:
            last_network_error = error
            print(f"attempt {attempt}/{attempts}: NETWORK_FAILURE: {error}", file=output)
        else:
            if not last_drift:
                print("HISTORY_PARITY: PASS", file=output)
                for name in HISTORY_ARTIFACTS:
                    print(f"{name}: PASS", file=output)
                return
            print(f"attempt {attempt}/{attempts}: DATA_DRIFT", file=output)
            for name in last_drift:
                print(f"file: {name}", file=output)
        if attempt < attempts:
            print(f"retrying in {retry_delay:g} seconds", file=output)
            sleep(retry_delay)

    if last_network_error is not None:
        print(f"NETWORK_FAILURE: {last_network_error}", file=output)
        raise last_network_error
    print("DATA_DRIFT", file=output)
    for name in last_drift:
        print(f"file: {name}", file=output)
    raise HistoryDriftError(last_drift)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--expected-dir", type=Path, default=HISTORY_HF_DIR)
    parser.add_argument("--base-url", default=HISTORY_RAW_BASE_URL)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=45)
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args()
    try:
        check_with_retry(
            expected_dir=args.expected_dir,
            base_url=args.base_url,
            attempts=args.attempts,
            retry_delay=args.retry_delay,
            timeout=args.timeout,
            output=sys.stdout,
        )
    except (HistoryDriftError, NetworkFailureError) as error:
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
