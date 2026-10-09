"""Reference facts and pinned fixtures for the October freshness migration."""
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "3e75fa51bc1f7af01745345d03bc1a525e353158"

def assert_verified_timestamp(test, value, baseline):
    actual = datetime.fromisoformat(value.replace("Z", "+00:00"))
    test.assertGreaterEqual(actual, datetime.fromisoformat(baseline.replace("Z", "+00:00")))
    test.assertLessEqual(actual, datetime.now(timezone.utc))

def lifecycle_fixture(generator):
    # These transaction tools deliberately accept only their reviewed 250-price universe.
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASELINE, "--", "data/pricing-v2-preview"], cwd=ROOT).decode().splitlines()
    prefix = "data/pricing-v2-preview/"
    return {p[len(prefix):]: subprocess.check_output(["git", "show", BASELINE + ":" + p], cwd=ROOT) for p in paths}

def assert_grok46_contract(test, row):
    test.assertEqual((row["provider_id"], row["model_id"], row["status"], row["context_window_tokens"]), ("xai", "grok-4.6", "active", 500000))
    test.assertEqual(tuple(row["pricing"][k] for k in ("input", "cached_input", "output", "batch_input", "batch_output")), (2, .5, 6, None, None))
    expected = {("standard", "short"): ("2", "0.5", "6"), ("standard", "long"): ("4", "1", "12"), ("priority", "short"): ("4", "1", "12"), ("priority", "long"): ("8", "2", "24")}
    records = {(r["processing_mode"], r["context_class"]): r for r in row["price_records"]}
    test.assertEqual(set(records), set(expected))
    for key, values in expected.items():
        r = records[key]; charges = {c["component"]: c["amount"] for c in r["charges"]}
        test.assertEqual(tuple(charges[k] for k in ("input", "cached_input", "output")), values)
        test.assertEqual(r["prompt_token_threshold"], 200000)
        test.assertEqual(r["tier_selection"], {"comparison": "less_than" if key[1] == "short" else "greater_than_or_equal", "token_basis": "total_prompt_tokens", "cached_prompt_tokens_included": True, "whole_request_pricing": True})
        test.assertEqual(r["region_policy"]["price_adjustments"][0]["factor"], "1.1")
        test.assertEqual(r["calculation_default"], key == ("standard", "short"))
