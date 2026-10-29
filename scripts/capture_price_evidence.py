"""Archive what official pricing pages say, and what changed since the last check.

  python scripts/capture_price_evidence.py --model mistral-ai/voxtral-mini-tts-3-0 \
      --url https://docs.mistral.ai/models/voxtral-mini-tts-3-0 --url https://mistral.ai/news/voxtral-3 \
      --expect '$13'          (single quotes: PowerShell and bash expand "$13")

For each URL it stores the price-bearing passages of the page text (each with two lines of
context, because pages often split "$13" and "/M Chars" across elements), the fetch time and a
digest of the page text under reports/price-evidence/<provider>/<model>/<UTC time>.json, then
compares them with the previous capture of the same model: passages that appeared or disappeared
point at a price change, or at a stale search-index quote that the live page no longer shows.
--expect fails the run when a page does not contain a value the release is about to publish.
--script-tables also reads MDX tables that a docs site ships only in its script payload (Kimi's
Mintlify pricing pages), one line per row, because the page text itself has no prices there.
The capture is committed with the release (amended into the artifact commit after prepare).
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = "reports/price-evidence"
PRICE_LINE = re.compile(r"[$€£]\s?\d|\b(?:USD|EUR)\b|\bper\s+(?:minute|hour|second|request|image|page|1\s?[MK]|million|thousand)\b|/\s?(?:M|K|min|hr|1M)\b", re.I)
USER_AGENT = "Mozilla/5.0 (compatible; AICostBudget price evidence)"
MAX_PASSAGES = 60
MAX_PASSAGE_CHARS = 500
MDX_TABLE = re.compile(r"columns:\[(?P<columns>.*?)\],rows:\[(?P<rows>\[.*?\])\]\}", re.S)
MDX_TEXT = re.compile(r"(?:(\w+):)?`([^`]*)`")
MDX_SKIPPED_KEYS = {"href", "width", "tip", "className"}


def page_lines(markup: str) -> list[str]:
    text = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", markup)
    text = html.unescape(re.sub(r"(?s)<[^>]+>", "\n", text))
    return [line for line in (re.sub(r"\s+", " ", raw).strip() for raw in text.splitlines()) if line]


def script_table_lines(markup: str) -> list[str]:
    """Header and rows of each MDX table in the script payload, cells joined by ' | '."""
    lines: list[str] = []
    for table in MDX_TABLE.finditer(markup):
        rows = re.split(r"\],\s*\[", table["rows"][1:-1])
        for cells in [table["columns"], *rows]:
            line = " | ".join(text.strip() for key, text in MDX_TEXT.findall(cells) if key not in MDX_SKIPPED_KEYS)
            if line and line not in lines:
                lines.append(line)
    return lines


def price_passages(lines: list[str], context: int = 2) -> list[str]:
    passages: list[str] = []
    for index, line in enumerate(lines):
        if PRICE_LINE.search(line):
            passage = " ".join(lines[max(0, index - context): index + context + 1])[:MAX_PASSAGE_CHARS]
            if passage not in passages:
                passages.append(passage)
    return passages[:MAX_PASSAGES]


def fetch(url: str, timeout: float = 30) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read().decode("utf-8", "replace")


def capture(url: str, expect: list[str], fetcher=fetch, script_tables: bool = False) -> dict:
    status, markup = fetcher(url)
    lines = page_lines(markup) + (script_table_lines(markup) if script_tables else [])
    text = "\n".join(lines)
    return {
        "url": url,
        "http_status": status,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "passages": price_passages(lines),
        "missing_expected": [value for value in expect if value not in text],
    }


def previous_capture(model_dir: Path) -> dict | None:
    files = sorted(model_dir.glob("*.json"))
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None


def compare(previous: dict | None, current: dict) -> list[dict]:
    if not previous:
        return []
    before = {page["url"]: set(page["passages"]) for page in previous["pages"]}
    changes = []
    for page in current["pages"]:
        if page["url"] not in before:
            continue
        added = sorted(set(page["passages"]) - before[page["url"]])
        removed = sorted(before[page["url"]] - set(page["passages"]))
        if added or removed:
            changes.append({"url": page["url"], "added": added, "removed": removed})
    return changes


def run(model: str, urls: list[str], expect: list[str], root: Path = ROOT, fetcher=fetch, now=None, script_tables: bool = False) -> dict:
    provider, _, model_id = model.partition("/")
    if not provider or not model_id:
        raise SystemExit("--model must be provider/model")
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    model_dir = root / EVIDENCE_DIR / provider / model_id
    previous = previous_capture(model_dir)
    record = {"model": model, "captured_at": stamp, "expect": expect, "pages": [capture(url, expect, fetcher, script_tables) for url in urls]}
    if script_tables:
        record["script_tables"] = True
    record["changes_since_previous"] = compare(previous, record)
    record["previous_capture"] = previous["captured_at"] if previous else None
    model_dir.mkdir(parents=True, exist_ok=True)
    path = model_dir / f"{stamp}.json"
    sequence = 2
    while path.exists():
        path = model_dir / f"{stamp}-{sequence}.json"
        sequence += 1
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    record["path"] = str(path.relative_to(root)).replace("\\", "/")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", required=True, help="provider/model, as in canonical")
    parser.add_argument("--url", action="append", required=True, help="official page; repeat for several")
    parser.add_argument("--expect", action="append", default=[], help="text every page must contain, e.g. $13; repeatable")
    parser.add_argument("--script-tables", action="store_true", help="also read MDX tables from the script payload")
    args = parser.parse_args()
    record = run(args.model, args.url, args.expect, script_tables=args.script_tables)
    print(f"EVIDENCE: {record['path']}")
    for page in record["pages"]:
        print(f"- {page['url']} HTTP {page['http_status']}: {len(page['passages'])} price passages")
        for value in page["missing_expected"]:
            print(f"  MISSING EXPECTED: {value}")
    if record["previous_capture"]:
        print(f"CHANGES SINCE {record['previous_capture']}: {'NONE' if not record['changes_since_previous'] else ''}")
        for change in record["changes_since_previous"]:
            print(f"- {change['url']}")
            for passage in change["added"]:
                print(f"  + {passage}")
            for passage in change["removed"]:
                print(f"  - {passage}")
    if any(page["missing_expected"] or page["http_status"] != 200 for page in record["pages"]):
        raise SystemExit(1)


if __name__ == "__main__":
    sys.exit(main())
