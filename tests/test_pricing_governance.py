from __future__ import annotations

import json
import math
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / "data" / "pricing-v2-preview"
PROJECTION = PREVIEW / "generated" / "model-pricing.v2.json"
WEBSITE_FIXTURE = ROOT / "tests" / "fixtures" / "website-model-pricing.json"
PUBLIC_NUMERIC_FIELDS = (
    "input_price_per_1m_tokens",
    "cached_input_price_per_1m_tokens",
    "output_price_per_1m_tokens",
)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class PricingGovernanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.canonical = {
            f"{row['provider_id']}/{row['model_id']}": row
            for row in read_json(ROOT / "data" / "canonical" / "models.json")
        }
        cls.website = {row["id"]: row for row in read_json(WEBSITE_FIXTURE)}
        cls.identities = {
            row["internalId"]: row for row in read_json(PREVIEW / "model-identity-registry.json")
        }
        cls.dispositions = {
            row["candidateId"]: row for row in read_json(PREVIEW / "candidate-disposition-map.json")
        }
        cls.projection_payload = read_json(PROJECTION)
        cls.projection = {
            row["canonicalInternalId"]: row for row in cls.projection_payload["models"]
        }
        cls.hf_payload = read_json(ROOT / "huggingface" / "prices.json")
        cls.hf = {
            f"{row['provider_id']}/{row['model_id']}": row for row in cls.hf_payload["records"]
        }
        phase26 = read_json(PREVIEW / "phase2-6-p0-resolution.json")
        cls.excluded_decisions = {
            row["modelInternalId"]: row
            for row in phase26["perModelDecisions"]
            if row["finalAction"] == "exclude_from_default"
        }

    def test_all_candidates_and_projection_rows_have_governance(self):
        self.assertEqual(
            set(self.dispositions),
            set(self.identities),
            "ORPHAN_CANDIDATE: disposition coverage differs from normalized identities",
        )
        counts = Counter(row["governanceClass"] for row in self.projection.values())
        self.assertEqual(
            counts,
            Counter(
                {
                    "VERIFIED_CANONICAL": 31,
                    "VERIFIED_PROJECTION": 7,
                    "PROJECTED_IDENTITY": 2,
                    "HISTORICAL_REFERENCE": 2,
                    "EXCLUDED": 3,
                    "REVIEW_REQUIRED": 3,
                }
            ),
            "GOVERNANCE_CLASS_COUNT_MISMATCH: current 48-row normalized projection changed classification",
        )
        exposures = Counter(row["publicExposure"] for row in self.projection.values())
        self.assertEqual(
            exposures,
            Counter({"public": 43, "excluded": 3, "alias_only": 2}),
            "PUBLIC_EXPOSURE_COUNT_MISMATCH: expected 43 public, 3 excluded, and 2 alias-only rows",
        )
        for internal_id, row in self.projection.items():
            self.assertTrue(row["governanceReason"], f"MISSING_GOVERNANCE_REASON: {internal_id}")
            self.assertTrue(row["governanceSourceCandidateIds"], f"MISSING_GOVERNANCE_SOURCE: {internal_id}")

    def test_public_rows_are_traceable_and_match_hugging_face(self):
        expected_rows = [
            f"{row['provider']}/{row['id']}"
            for row in self.projection.values()
            if row["publicExposure"] == "public"
        ]
        expected = set(expected_rows)
        self.assertEqual(set(self.hf), expected, "ORPHAN_PUBLIC_ROW: HF/public projection identity sets differ")
        self.assertEqual(len(expected_rows), len(expected), "DUPLICATE_PUBLIC_IDENTITY: provider/model pair repeated")
        for internal_id, row in self.projection.items():
            if row["publicExposure"] != "public":
                continue
            self.assertNotEqual(row["pricingSourceType"], "none", f"PUBLIC_ROW_WITHOUT_PRICE_SOURCE: {internal_id}")
            self.assertTrue(row["sourceUrls"], f"PUBLIC_ROW_WITHOUT_SOURCE: {internal_id}")

    def test_every_canonical_row_has_explicit_disposition(self):
        for internal_id in sorted(self.canonical):
            disposition = self.dispositions.get(internal_id)
            self.assertIsNotNone(disposition, f"SILENT_CANONICAL_DISAPPEARANCE: {internal_id}")
            if disposition["disposition"] == "merged_duplicate":
                target = disposition["mergeTarget"]
                self.assertIn(target, self.projection, f"MERGE_TARGET_MISSING: {internal_id} -> {target}")
                self.assertEqual(self.projection[target]["publicExposure"], "public")
                continue
            row = self.projection.get(internal_id)
            self.assertIsNotNone(row, f"UNEXPLAINED_CANONICAL_EXCLUSION: {internal_id}")
            self.assertIn(
                row["governanceClass"],
                {"VERIFIED_CANONICAL", "EXCLUDED", "REVIEW_REQUIRED"},
                f"INVALID_CANONICAL_GOVERNANCE: {internal_id}",
            )

    def test_fallbacks_are_explicit_and_preserve_legacy_values(self):
        fallback_types = {"compatibility_fallback", "legacy_historical_fallback"}
        rows = [row for row in self.projection.values() if row["pricingSourceType"] in fallback_types]
        self.assertEqual(
            {row["canonicalInternalId"] for row in rows},
            {"anthropic/claude-sonnet-4", "openai/gpt-4.1", "openai/gpt-4.1-mini", "openai/gpt-4.1-nano"},
            "FALLBACK_SET_MISMATCH: expected the four audited legacy compatibility rows",
        )
        for row in rows:
            internal_id = row["canonicalInternalId"]
            legacy = self.website.get(row["id"])
            self.assertIsNotNone(legacy, f"FALLBACK_WITHOUT_LEGACY_ROW: {internal_id}")
            public = self.hf[f"{row['provider']}/{row['id']}"]
            self.assertEqual(public["input_price_per_1m_tokens"], legacy["inputPrice"])
            self.assertTrue(public["official_source_url"], f"FALLBACK_WITHOUT_SOURCE: {internal_id}")
            self.assertEqual(public["verification_status"], row["verificationStatus"])
            self.assertIsNone(public["last_verified_at"], f"FALLBACK_MUST_NOT_FABRICATE_VERIFICATION: {internal_id}")
            self.assertEqual(public["checked_at"], row["checkedAt"][:10])
            self.assertTrue(public["checked_at"], f"FALLBACK_WITHOUT_CHECK_TIMESTAMP: {internal_id}")
            self.assertEqual(public["cached_input_price_per_1m_tokens"], legacy.get("cachedInputPrice"))
            self.assertEqual(public["output_price_per_1m_tokens"], legacy["outputPrice"])
        self.assertIsNone(
            self.hf["openai/gpt-4.1"]["cached_input_price_per_1m_tokens"],
            "GPT_4_1_STALE_CACHE_PRICE_REINTRODUCED: cached input must remain null",
        )

    def test_aliases_and_exclusions_are_machine_governed(self):
        for internal_id, identity in self.identities.items():
            if identity["identityType"] != "alias":
                continue
            target = identity["aliasTargetInternalId"]
            self.assertIn(target, self.identities, f"ALIAS_TARGET_MISSING: {internal_id} -> {target}")
            visited = {internal_id}
            current = target
            while self.identities[current]["identityType"] == "alias":
                self.assertNotIn(current, visited, f"ALIAS_CYCLE: {internal_id} -> {current}")
                visited.add(current)
                current = self.identities[current]["aliasTargetInternalId"]
                self.assertIn(current, self.identities, f"ALIAS_TARGET_MISSING: {internal_id} -> {current}")
            self.assertNotIn(current, visited, f"ALIAS_CYCLE: {internal_id} -> {current}")
            self.assertEqual(self.projection[internal_id]["publicExposure"], "alias_only")
        excluded = {key for key, row in self.projection.items() if row["publicExposure"] == "excluded"}
        self.assertEqual(excluded, set(self.excluded_decisions), "EXCLUSION_DECISION_DRIFT: projection differs from Phase 2.6")
        for internal_id in excluded:
            self.assertTrue(self.projection[internal_id]["governanceDetails"], f"EXCLUSION_WITHOUT_REASON: {internal_id}")

    def test_verified_projection_requires_official_evidence(self):
        rows = [row for row in self.projection.values() if row["governanceClass"] == "VERIFIED_PROJECTION"]
        self.assertEqual(len(rows), 7, "VERIFIED_PROJECTION_COUNT_MISMATCH")
        for row in rows:
            internal_id = row["canonicalInternalId"]
            self.assertEqual(row["verificationStatus"], "verified", f"PROMOTION_WITHOUT_VERIFICATION: {internal_id}")
            self.assertTrue(row["selectedPriceRecordId"], f"PROMOTION_WITHOUT_PRICE_RECORD: {internal_id}")
            self.assertTrue(row["verifiedAt"], f"PROMOTION_WITHOUT_TIMESTAMP: {internal_id}")
            self.assertTrue(all(url.startswith("https://") for url in row["sourceUrls"]), f"PROMOTION_WITHOUT_OFFICIAL_SOURCE: {internal_id}")

    def test_p3_promotes_only_the_approved_seven(self):
        promoted = {
            "anthropic/claude-fable-5",
            "google-gemini/gemini-3.1-flash-lite",
            "google-gemini/gemini-3.5-flash",
            "openai/gpt-5.4",
            "openai/gpt-5.4-nano",
            "openai/gpt-5.4-pro",
            "openai/gpt-5.5-pro",
        }
        protected_projection = {
            "anthropic/claude-mythos-5",
            "anthropic/claude-opus-4.1",
            "google-gemini/gemini-3-flash-preview",
            "google-gemini/gemini-3.1-pro-preview",
            "openai/chatgpt-chat-latest",
            "openai/gpt-5.3-codex",
            "xai/grok-build-0.1",
        }
        self.assertTrue(promoted.issubset(self.canonical))
        self.assertEqual(
            {internal_id for internal_id in promoted if self.projection[internal_id]["governanceClass"] == "VERIFIED_CANONICAL"},
            promoted,
        )
        self.assertEqual(
            {
                internal_id
                for internal_id, row in self.projection.items()
                if row["governanceClass"] == "VERIFIED_PROJECTION"
            },
            protected_projection,
        )
        self.assertTrue(all(self.projection[internal_id]["publicExposure"] == "public" for internal_id in promoted))
        self.assertTrue(protected_projection.isdisjoint(self.canonical))

    def test_public_numeric_and_timestamp_semantics(self):
        now = datetime.now(timezone.utc)
        generated_at = parse_timestamp(self.hf_payload["metadata"]["generated_at"])
        verified = []
        for internal_id, row in self.hf.items():
            for field in PUBLIC_NUMERIC_FIELDS:
                value = row[field]
                self.assertTrue(value is None or (isinstance(value, (int, float)) and math.isfinite(value) and value >= 0), f"INVALID_NUMERIC_PRICE: {internal_id} {field}")
            if row["last_verified_at"]:
                timestamp = parse_timestamp(row["last_verified_at"])
