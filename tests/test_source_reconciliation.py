import copy
import unittest

from scripts.generate_pricing_v2_preview import reconcile_existing_sources, source_id


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


if __name__ == "__main__":
    unittest.main()
