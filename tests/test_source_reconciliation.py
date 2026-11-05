import json
import tempfile
import copy
import unittest
from pathlib import Path

from scripts.generate_pricing_v2_preview import (
    reconcile_existing_sources,
    refresh_verified_record_sources,
    reverification_evidence_urls,
    source_id,
)


class SourceReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.openai_url = "https://developers.openai.com/api/docs/guides/fast-mode"
        self.anthropic_url = "https://platform.claude.com/docs/en/build-with-claude/prompt-caching"
        self.gemini_url = "https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash-tts"
        self.existing = [
            {
                "sourceId": source_id("openai", self.openai_url),
                "providerId": "openai",
                "url": self.openai_url,
                "sourceType": "official_pricing_page",
                "title": "OpenAI official source",
                "accessedAt": "2026-09-04T17:34:11Z",
                "checkedAt": "2026-09-04T17:34:11Z",
                "verifiedAt": "2026-08-25T15:02:22Z",
                "officialProviderDomain": "developers.openai.com",
                "supports": ["pricing"],
                "verificationStatus": "verified",
            },
            {
                "sourceId": source_id("anthropic", self.anthropic_url),
                "providerId": "anthropic",
                "url": self.anthropic_url,
                "sourceType": "official_model_docs",
                "title": "Anthropic Prompt Caching",
                "accessedAt": "2026-09-06T23:26:10Z",
                "checkedAt": "2026-09-06T23:26:10Z",
                "verifiedAt": "2026-09-06T23:26:10Z",
                "officialProviderDomain": "platform.claude.com",
                "supports": ["cache_eligibility", "cache_lifetime", "cache_mode", "models"],
                "verificationStatus": "verified",
            },
        ]
        self.derived = {
            self.openai_url: {
                **{key: value for key, value in self.existing[0].items() if key != "sourceId"},
                "accessedAt": "2026-09-23T00:00:00Z",
                "checkedAt": "2026-09-23T00:00:00Z",
            },
            self.anthropic_url: {
                **{key: value for key, value in self.existing[1].items() if key != "sourceId"},
                "sourceType": "official_pricing_page",
                "title": "Anthropic official source",
                "accessedAt": "2026-09-23T00:00:00Z",
                "checkedAt": "2026-09-23T00:00:00Z",
                "supports": ["pricing"],
            },
            self.gemini_url: {
                "providerId": "google-gemini",
                "url": self.gemini_url,
                "sourceType": "official_model_docs",
                "title": "Google official source",
                "accessedAt": "2026-09-24T14:27:54Z",
                "checkedAt": "2026-09-24T14:27:54Z",
                "verifiedAt": "2026-09-24T14:27:54Z",
                "officialProviderDomain": "ai.google.dev",
                "supports": ["pricing"],
                "verificationStatus": "verified",
            },
        }

    def test_existing_metadata_is_preserved_and_new_source_is_added(self):
        reconciled = reconcile_existing_sources(self.derived, self.existing)
        for existing in self.existing:
            self.assertEqual(
                reconciled[existing["url"]],
                {key: value for key, value in existing.items() if key != "sourceId"},
            )
        self.assertEqual(reconciled[self.gemini_url], self.derived[self.gemini_url])
        self.assertEqual(set(reconciled), {self.openai_url, self.anthropic_url, self.gemini_url})

    def test_reconciliation_is_deterministic(self):
        first = reconcile_existing_sources(self.derived, self.existing)
        next_registry = [
            {"sourceId": source_id(source["providerId"], url), **source}
            for url, source in sorted(first.items())
        ]
        second = reconcile_existing_sources(copy.deepcopy(self.derived), next_registry)
        self.assertEqual(second, first)

    def test_duplicate_url_and_identity_mismatch_fail(self):
        with self.assertRaisesRegex(ValueError, "duplicate URL"):
            reconcile_existing_sources({}, [self.existing[0], copy.deepcopy(self.existing[0])])
        invalid = copy.deepcopy(self.existing[0])
        invalid["sourceId"] = "source:openai:wrong"
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            reconcile_existing_sources({}, [invalid])

    def test_explicit_record_refresh_updates_only_its_source_timestamps(self):
        public_by_key = {
            ("openai", "gpt-test"): {
                "provider_id": "openai",
                "model_id": "gpt-test",
                "official_source_url": self.openai_url,
                "official_source_urls": [self.openai_url],
                "accessed_at": "2026-09-29T12:00:00Z",
                "last_verified_at": "2026-09-29T11:59:00Z",
            }
        }
        reconciled = reconcile_existing_sources(self.derived, self.existing)
        refreshed = refresh_verified_record_sources(
            reconciled,
            public_by_key,
            [("openai", "gpt-test")],
        )
        self.assertEqual(refreshed[self.openai_url]["accessedAt"], "2026-09-29T12:00:00Z")
        self.assertEqual(refreshed[self.openai_url]["checkedAt"], "2026-09-29T12:00:00Z")
        self.assertEqual(refreshed[self.openai_url]["verifiedAt"], "2026-09-29T11:59:00Z")
        self.assertEqual(refreshed[self.anthropic_url], reconciled[self.anthropic_url])

    def test_record_refresh_skips_listed_pages_that_were_not_fetched(self):
        blog = "https://openai.com/index/gpt-test/"
        public_by_key = {
            ("openai", "gpt-test"): {
                "provider_id": "openai",
                "model_id": "gpt-test",
                "official_source_url": self.openai_url,
                "official_source_urls": [self.openai_url, blog],
                "accessed_at": "2026-09-29T12:00:00Z",
                "last_verified_at": "2026-09-29T11:59:00Z",
            }
        }
        reconciled = reconcile_existing_sources(self.derived, self.existing)
        old_blog = {"providerId": "openai", "url": blog, "verifiedAt": "2026-09-01T00:00:00Z",
                    "accessedAt": "2026-09-01T00:00:00Z", "checkedAt": "2026-09-01T00:00:00Z"}
        reconciled[blog] = dict(old_blog)
        refreshed = refresh_verified_record_sources(
            reconciled, public_by_key, [("openai", "gpt-test")],
            {("openai", "gpt-test"): {self.openai_url}},
        )
        self.assertEqual(refreshed[self.openai_url]["verifiedAt"], "2026-09-29T11:59:00Z")
        self.assertEqual(refreshed[blog], old_blog)

    def test_reverification_evidence_urls_reads_same_day_captures_up_to_stamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "openai" / "gpt-test"
            folder.mkdir(parents=True)
            for stem, url in (("20260929T115000Z", "https://a.test/"), ("20260929T115900Z", "https://b.test/"),
                              ("20260929T120500Z", "https://late.test/"), ("20260928T110000Z", "https://old.test/")):
                (folder / f"{stem}.json").write_text(json.dumps({"pages": [{"url": url}]}), encoding="utf-8")
            found = reverification_evidence_urls(
                {("openai", "gpt-test"): {"last_verified_at": "2026-09-29T11:59:00Z"},
                 ("openai", "none"): {"last_verified_at": "2026-09-29T11:59:00Z"}},
                [("openai", "gpt-test"), ("openai", "none")], Path(tmp),
            )
        self.assertEqual(found, {("openai", "gpt-test"): {"https://a.test/", "https://b.test/"}})

    def test_explicit_record_refresh_rejects_unknown_record(self):
        with self.assertRaisesRegex(ValueError, "Unknown canonical source refresh record"):
            refresh_verified_record_sources({}, {}, [("openai", "missing")])


if __name__ == "__main__":
    unittest.main()
