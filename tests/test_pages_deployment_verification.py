import io
import json
import unittest
from unittest.mock import patch

from scripts import verify_pages_deployment as verifier

from scripts.verify_pages_deployment import (
    META_URL,
    PRICES_URL,
    VerificationError,
    fetch_json,
    validate_public_payloads,
    verify_public_deployment,
)

EXPECTED_SHA = "a" * 40
OLD_SHA = "b" * 40


def valid_payloads(sha=EXPECTED_SHA):
    meta = {
        "dataset_version": "1.0.0",
        "generated_at": "2026-09-14T00:00:00Z",
        "model_count": 2,
        "provider_count": 1,
        "official_source_count": 2,
        "source_commit_sha": sha,
    }
    prices = {
        "dataset_version": "1.0.0",
        "generated_at": "2026-09-14T00:00:00Z",
        "model_count": 2,
        "provider_count": 1,
        "official_source_count": 2,
        "models": [{"model_id": "one"}, {"model_id": "two"}],
    }
    return meta, prices


class FakeResponse:
    def __init__(self, payload, status=200, raw=False):
        self.body = payload if raw else json.dumps(payload).encode()
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self):
        return self.status

    def read(self):
        return self.body


class PagesDeploymentVerificationTests(unittest.TestCase):
    def expected_files(self):
        meta, prices = valid_payloads()
        return {
            "api/v1/meta.json": json.dumps(meta).encode(),
            "api/v1/prices.json": json.dumps(prices).encode(),
            "api/v1/prices.csv": b"provider_id,model_id\nexample,one\nexample,two\n",
        }

    def verify_responses(self, responses):
        responses = iter(responses)
        verify_public_deployment(
            EXPECTED_SHA, attempts=1, opener=lambda *_args, **_kwargs: next(responses),
            output=io.StringIO(), expected_files=self.expected_files(),
        )

    def test_committed_json_and_csv_http_200_pass(self):
        files = self.expected_files()
        self.verify_responses([FakeResponse(files[path], raw=True) for path in files])

    def test_non_200_meta_or_prices_fail(self):
        meta, prices = valid_payloads()
        for responses in ([FakeResponse(meta, status=206)], [FakeResponse(meta), FakeResponse(prices, status=206)]):
            with self.subTest(responses=responses), self.assertRaisesRegex(VerificationError, "expected HTTP 200"):
                self.verify_responses(responses)

    def test_regenerated_metadata_with_same_source_sha_fails(self):
        meta, _ = valid_payloads()
        meta["generated_at"] = "2026-09-15T00:00:00Z"
        with self.assertRaisesRegex(VerificationError, "public bytes differ"):
            self.verify_responses([FakeResponse(meta)])

    def test_price_record_drift_with_same_counts_fails(self):
        files = self.expected_files()
        _, prices = valid_payloads()
        prices["models"][0]["model_id"] = "changed"
        with self.assertRaisesRegex(VerificationError, "public bytes differ"):
            self.verify_responses([FakeResponse(files["api/v1/meta.json"], raw=True), FakeResponse(prices)])

    def test_csv_bytes_and_http_status_are_checked(self):
        files = self.expected_files()
        for csv in (FakeResponse(b"changed", raw=True), FakeResponse(files["api/v1/prices.csv"], status=206, raw=True)):
            with self.subTest(csv=csv), self.assertRaises(VerificationError):
                self.verify_responses([FakeResponse(files["api/v1/meta.json"], raw=True), FakeResponse(files["api/v1/prices.json"], raw=True), csv])

    def test_cli_uses_source_sha_and_artifact_bytes_separately(self):
        artifact_sha = "c" * 40
        files = self.expected_files()
        with patch.object(verifier, "committed_pages", return_value=(files, EXPECTED_SHA, artifact_sha)) as committed, patch.object(verifier, "verify_public_deployment") as verify, patch("sys.argv", ["verifier", "--expected-source-sha", EXPECTED_SHA, "--artifact-sha", artifact_sha]), patch("sys.stdout", io.StringIO()):
            verifier.main()
        committed.assert_called_once_with(artifact_sha)
        verify.assert_called_once_with(EXPECTED_SHA, 8, 8, 3, expected_files=files)

    def test_cli_artifact_sha_as_expected_source_fails_before_http(self):
        artifact_sha = "c" * 40
        with patch.object(verifier, "committed_pages", return_value=(self.expected_files(), EXPECTED_SHA, artifact_sha)), patch.object(verifier, "verify_public_deployment") as verify, patch("sys.argv", ["verifier", "--expected-source-sha", artifact_sha, "--artifact-sha", artifact_sha]), patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit) as error:
            verifier.main()
        self.assertEqual(error.exception.code, 1)
        verify.assert_not_called()

    def test_valid_payloads_pass(self):
        meta, prices = valid_payloads()
        validate_public_payloads(meta, prices, EXPECTED_SHA)

    def test_meta_invalid_json_fails(self):
        with self.assertRaisesRegex(VerificationError, "invalid JSON"):
            fetch_json(META_URL, 1, lambda *_args, **_kwargs: FakeResponse(b"{", raw=True))

    def test_prices_invalid_json_fails(self):
        with self.assertRaisesRegex(VerificationError, "invalid JSON"):
            fetch_json(PRICES_URL, 1, lambda *_args, **_kwargs: FakeResponse(b"[", raw=True))

    def test_source_commit_mismatch_fails(self):
        meta, prices = valid_payloads(OLD_SHA)
        with self.assertRaisesRegex(VerificationError, "source commit mismatch"):
            validate_public_payloads(meta, prices, EXPECTED_SHA)

    def test_model_count_mismatch_fails(self):
        meta, prices = valid_payloads()
        meta["model_count"] = 3
        prices["model_count"] = 3
        with self.assertRaisesRegex(VerificationError, "model count mismatch"):
            validate_public_payloads(meta, prices, EXPECTED_SHA)

    def test_dataset_version_mismatch_fails(self):
        meta, prices = valid_payloads()
        prices["dataset_version"] = "2.0.0"
        with self.assertRaisesRegex(VerificationError, "dataset_version"):
            validate_public_payloads(meta, prices, EXPECTED_SHA)

    def test_missing_source_commit_fails(self):
        meta, prices = valid_payloads()
        del meta["source_commit_sha"]
        with self.assertRaisesRegex(VerificationError, "source_commit_sha"):
            validate_public_payloads(meta, prices, EXPECTED_SHA)

    def test_old_sha_is_retried_until_expected_sha_is_public(self):
        old_meta, prices = valid_payloads(OLD_SHA)
        current_meta, _ = valid_payloads(EXPECTED_SHA)
        responses = iter(
            [FakeResponse(old_meta), FakeResponse(old_meta), FakeResponse(current_meta), FakeResponse(prices)]
        )
        sleeps = []

        def opener(*_args, **_kwargs):
            return next(responses)

        verify_public_deployment(
            EXPECTED_SHA,
            attempts=3,
            interval=0.25,
            timeout=1,
            opener=opener,
            sleeper=sleeps.append,
            output=io.StringIO(),
        )
        self.assertEqual(sleeps, [0.25, 0.25])


if __name__ == "__main__":
    unittest.main()
