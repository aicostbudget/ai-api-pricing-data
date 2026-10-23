"""Write data/canonical/models.json in its one normalized form, or --check that it already is.

The canonical file is edited by hand and by agents; one fixed serialization (two-space indent,
UTF-8, original key order, trailing newline) keeps release diffs to the records that changed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "data/canonical/models.json"


def normalized_text(text: str) -> str:
    return json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n"


def is_normalized(path: Path = CANONICAL) -> bool:
    # Line endings are left to Git (a Windows checkout may use CRLF); the layout is what counts.
    raw = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    return raw == normalized_text(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 if the file is not normalized")
    parser.add_argument("path", nargs="?", type=Path, default=CANONICAL)
    args = parser.parse_args()
    if args.check:
        if not is_normalized(args.path):
            print(f"{args.path} is not normalized; run python scripts/format_canonical.py", file=sys.stderr)
            raise SystemExit(1)
        return
    raw = args.path.read_bytes().decode("utf-8")
    args.path.write_bytes(normalized_text(raw).encode("utf-8"))


if __name__ == "__main__":
    main()
