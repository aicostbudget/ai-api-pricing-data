import io
import json
import unittest

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
