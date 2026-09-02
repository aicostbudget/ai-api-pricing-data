import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from scripts.check_hf_production_parity import (
    ARTIFACTS,
    DataDriftError,
    NetworkFailureError,
    check_with_retry,
)


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "hf-production-parity.yml"
CSV_FIELDS = (
    "provider_id",
    "provider",
    "model_id",
    "input_price_per_1m_tokens",
    "official_source_url",
    "verification_status",
    "last_verified_at",
    "checked_at",
)
FULL_CSV_FIELDS = (
    *CSV_FIELDS,
    "pricing_tiers_json",
    "time_pricing_json",
    "pricing_components_json",
)


def record(model_id, *, status="verified", verified="2026-08-01", checked="2026-08-01"):
    return {
        "provider_id": "openai",
        "provider": "OpenAI",
        "model_id": model_id,
        "input_price_per_1m_tokens": 1.25,
        "official_source_url": "https://example.com/pricing",
        "verification_status": status,
        "last_verified_at": verified,
        "checked_at": checked,
    }


def csv_bytes(records, fieldnames=CSV_FIELDS):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    return output.getvalue().encode()


def build_snapshot():
    records = [
        record("verified-model"),
        record(
            "review-model",
            status="review_required",
            verified=None,
            checked="2026-08-02",
        ),
    ]
    metadata = {"record_count": 2, "generated_at": "2026-08-03T00:00:00Z"}
    prices = {"metadata": metadata, "records": records}
    full_csv_records = [
        {
            **item,
            "pricing_tiers_json": "[]",
            "time_pricing_json": "null",
            "pricing_components_json": "[]",
        }
        for item in records
    ]
    return {
        "prices.json": (json.dumps(prices, indent=2) + "\n").encode(),
        "prices.csv": csv_bytes(full_csv_records, FULL_CSV_FIELDS),
        "train.csv": csv_bytes(records),
        "meta.json": (json.dumps(metadata, indent=2) + "\n").encode(),
    }


class HuggingFaceProductionParityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.expected_dir = Path(self.temp_dir.name)
        self.expected = build_snapshot()
        for name, content in self.expected.items():
            (self.expected_dir / name).write_bytes(content)

    def tearDown(self):
        self.temp_dir.cleanup()

    def fetcher(self, snapshot, failures=0):
        state = {"failures": failures, "urls": []}

        def fetch(url, _timeout):
            state["urls"].append(url)
            if state["failures"]:
                state["failures"] -= 1
                raise OSError("temporary connection error")
            artifact = Path(urlsplit(url).path).name
            return snapshot[artifact]

        return fetch, state

    def run_check(self, snapshot, *, attempts=1, failures=0):
        fetch, state = self.fetcher(snapshot, failures)
        output = io.StringIO()
        sleeps = []
        result = check_with_retry(
            expected_dir=self.expected_dir,
            base_url="https://example.test/resolve/main",
            attempts=attempts,
            retry_delay=0.25,
            timeout=1,
            fetch_bytes=fetch,
            sleep=sleeps.append,
            cache_bust=lambda: "unique",
            output=output,
        )
        return result, output.getvalue(), state, sleeps

    def mutated_json(self, artifact, mutate):
        snapshot = dict(self.expected)
        payload = json.loads(snapshot[artifact])
        mutate(payload)
        snapshot[artifact] = json.dumps(payload).encode()
        return snapshot

    def assert_data_drift(self, snapshot):
        with self.assertRaises(DataDriftError) as caught:
            self.run_check(snapshot)
        return caught.exception.drifts

    def test_exact_parity_passes(self):
        result, output, state, sleeps = self.run_check(self.expected)
        self.assertEqual(result, 2)
        self.assertIn("HF production parity OK", output)
        self.assertIn("semantic violations: 0", output)
        self.assertEqual(sleeps, [])
        self.assertTrue(all("cache_bust=unique" in url for url in state["urls"]))

    def test_missing_verification_status_fails(self):
        snapshot = self.mutated_json(
            "prices.json", lambda payload: payload["records"][0].pop("verification_status")
        )
        drifts = self.assert_data_drift(snapshot)
        self.assertTrue(any(d.field == "verification_status" for d in drifts))

    def test_checked_at_drift_fails(self):
        snapshot = self.mutated_json(
            "prices.json",
            lambda payload: payload["records"][1].__setitem__("checked_at", "2026-08-09"),
        )
        drifts = self.assert_data_drift(snapshot)
        self.assertTrue(any(d.model_id == "review-model" and d.field == "checked_at" for d in drifts))

    def test_checked_at_cannot_be_substituted_for_last_verified_at(self):
        snapshot = self.mutated_json(
            "prices.json",
            lambda payload: payload["records"][1].__setitem__("last_verified_at", "2026-08-02"),
        )
        drifts = self.assert_data_drift(snapshot)
        drift = next(d for d in drifts if d.model_id == "review-model" and d.field == "last_verified_at")
        self.assertTrue(drift.semantic)
        self.assertIsNone(drift.expected)

    def test_numeric_pricing_drift_fails(self):
        snapshot = self.mutated_json(
            "prices.json",
            lambda payload: payload["records"][0].__setitem__("input_price_per_1m_tokens", 9.99),
        )
        drifts = self.assert_data_drift(snapshot)
        self.assertTrue(any(d.field == "input_price_per_1m_tokens" for d in drifts))

    def test_official_source_url_drift_fails(self):
        snapshot = self.mutated_json(
            "prices.json",
            lambda payload: payload["records"][0].__setitem__("official_source_url", "https://wrong.test"),
        )
        drifts = self.assert_data_drift(snapshot)
        self.assertTrue(any(d.field == "official_source_url" for d in drifts))

    def test_csv_row_drift_fails_without_line_ending_sensitivity(self):
        snapshot = dict(self.expected)
        text = snapshot["prices.csv"].decode().replace("1.25", "7.50", 1)
        snapshot["prices.csv"] = text.replace("\n", "\r\n").encode()
        drifts = self.assert_data_drift(snapshot)
        self.assertTrue(any(d.artifact == "prices.csv" and d.field == "input_price_per_1m_tokens" for d in drifts))

    def test_viewer_csv_drift_is_checked_independently(self):
        snapshot = dict(self.expected)
        snapshot["train.csv"] = snapshot["train.csv"].replace(b"1.25", b"7.50", 1)
        drifts = self.assert_data_drift(snapshot)
        self.assertTrue(
            any(
                drift.artifact == "train.csv"
                and drift.field == "input_price_per_1m_tokens"
                for drift in drifts
            )
        )

    def test_meta_json_drift_fails(self):
        snapshot = self.mutated_json(
            "meta.json", lambda payload: payload.__setitem__("record_count", 999)
        )
        drifts = self.assert_data_drift(snapshot)
        self.assertTrue(any(d.artifact == "meta.json" and d.field == "record_count" for d in drifts))

    def test_transient_http_failure_retries_and_passes(self):
        result, output, _state, sleeps = self.run_check(self.expected, attempts=2, failures=1)
        self.assertEqual(result, 2)
        self.assertIn("attempt 1/2: NETWORK_FAILURE", output)
        self.assertEqual(sleeps, [0.25])

    def test_retries_exhausted_reports_network_failure(self):
        fetch, _state = self.fetcher(self.expected, failures=10)
        output = io.StringIO()
        with self.assertRaises(NetworkFailureError):
            check_with_retry(
                expected_dir=self.expected_dir,
                base_url="https://example.test/resolve/main",
                attempts=3,
                retry_delay=0,
                timeout=1,
                fetch_bytes=fetch,
                sleep=lambda _seconds: None,
                output=output,
            )
        self.assertIn("HF production check unavailable", output.getvalue())
        self.assertIn("NETWORK_FAILURE", output.getvalue())

    def test_workflow_is_scheduled_or_manual_only(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("name: Hugging Face Production Parity", workflow)
        self.assertNotIn("push:", workflow)
        self.assertIn("schedule:", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("pull_request", workflow)
        self.assertIn("python scripts/check_hf_production_parity.py", workflow)
        self.assertNotIn("website-source", workflow)


if __name__ == "__main__":
    unittest.main()
