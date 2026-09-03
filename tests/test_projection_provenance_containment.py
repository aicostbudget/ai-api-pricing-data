import itertools
import json
from pathlib import Path
import tempfile
import unittest

from scripts.generate_website_projection_v2 import (
    ARTIFACT,
    build_projection,
    select_official_source_url,
    source_evidence_role,
)


WEBSITE_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "website-model-pricing.json"
PROVENANCE_FIELDS = (
    "checkedAt",
    "verifiedAt",
    "checkedSourceRefs",
    "verifiedSourceRefs",
    "officialSourceUrl",
)


def source(source_id, url, source_type="official_pricing_page", *, timestamp="2026-08-29T00:00:00Z"):
    return {
        "sourceId": source_id,
        "url": url,
        "sourceType": source_type,
        "supports": ["pricing"],
        "verificationStatus": "verified",
        "verifiedAt": timestamp,
        "checkedAt": timestamp,
    }


class ProjectionProvenanceContainmentTests(unittest.TestCase):
    def test_existing_projection_preserves_all_provenance_and_generated_at(self):
        committed = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        generated, _ = build_projection(
            effective_at_value=committed["effectiveAt"],
            website_dataset=WEBSITE_FIXTURE,
            existing_artifact=ARTIFACT,
        )
        self.assertEqual(generated["generatedAt"], committed["generatedAt"])
        expected = {row["id"]: row for row in committed["models"]}
        for row in generated["models"]:
            for field in PROVENANCE_FIELDS:
                self.assertEqual(row[field], expected[row["id"]][field], (row["id"], field))

    def test_custom_existing_artifact_is_the_actual_preservation_input(self):
        existing = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        row = next(item for item in existing["models"] if item["id"] == "grok-4.5")
        row["verifiedAt"] = "2026-08-30T00:00:00Z"
        artifact_timestamps = [
            item[field]
            for item in existing["models"]
            for field in ("verifiedAt", "checkedAt")
            if isinstance(item.get(field), str) and item[field]
        ]
        existing["generatedAt"] = max([existing["generatedAt"], *artifact_timestamps])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing.json"
            path.write_text(json.dumps(existing), encoding="utf-8")
            generated, _ = build_projection(
                website_dataset=WEBSITE_FIXTURE,
                existing_artifact=path,
            )
        actual = next(item for item in generated["models"] if item["id"] == "grok-4.5")
        self.assertEqual(actual["verifiedAt"], "2026-08-30T00:00:00Z")
        self.assertEqual(generated["generatedAt"], existing["generatedAt"])

    def test_missing_baseline_is_deterministic_and_not_wall_clock_stamped(self):
        first, _ = build_projection(website_dataset=WEBSITE_FIXTURE, existing_artifact=None)
        second, _ = build_projection(website_dataset=WEBSITE_FIXTURE, existing_artifact=None)
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.json"
            third, _ = build_projection(website_dataset=WEBSITE_FIXTURE, existing_artifact=missing)
        self.assertEqual(first, second)
        self.assertEqual(first, third)
        timestamps = [
            row[field]
            for row in first["models"]
            for field in ("checkedAt", "verifiedAt")
            if row[field]
        ]
        self.assertEqual(first["generatedAt"], max(timestamps))

    def test_projection_website_sync_feedback_converges_after_one_pass(self):
        first, _ = build_projection(website_dataset=WEBSITE_FIXTURE, existing_artifact=None)
        synced_website = json.loads(WEBSITE_FIXTURE.read_text(encoding="utf-8"))
        projection_by_id = {row["id"]: row for row in first["models"]}
        for website_row in synced_website:
            projection_row = projection_by_id[website_row["id"]]
            website_row.update(
                {
                    "officialPriceUrl": projection_row["officialSourceUrl"],
                    "officialSourceUrl": projection_row["officialSourceUrl"],
                    "lastVerifiedAt": projection_row["verifiedAt"],
                    "lastCheckedAt": projection_row["checkedAt"],
                    "verificationStatus": projection_row["verificationStatus"],
                }
            )
            website_row.pop("pricingTiers", None)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_path = root / "first.json"
            website_path = root / "website.json"
            first_path.write_text(json.dumps(first), encoding="utf-8")
            website_path.write_text(json.dumps(synced_website), encoding="utf-8")
            second, _ = build_projection(
                website_dataset=website_path,
                existing_artifact=first_path,
            )

        self.assertEqual(first["generatedAt"], second["generatedAt"])
        self.assertEqual(first["models"], second["models"])

    def test_fresh_projection_contains_known_cross_provider_incidents(self):
        artifact, _ = build_projection(website_dataset=WEBSITE_FIXTURE, existing_artifact=None)
        rows = {row["id"]: row for row in artifact["models"]}
        self.assertEqual(
            rows["deepseek-chat"]["officialSourceUrl"],
            "https://api-docs.deepseek.com/quick_start/pricing",
        )
        self.assertEqual(
            rows["gemini-3.6-flash"]["officialSourceUrl"],
            "https://ai.google.dev/gemini-api/docs/pricing",
        )
        self.assertEqual(
            rows["gpt-5.6-luna"]["officialSourceUrl"],
            "https://developers.openai.com/api/docs/pricing",
        )


    def test_source_roles_express_evidence_purpose(self):
        self.assertEqual(source_evidence_role(source("pricing", "https://example.test/pricing")), "direct_pricing")
        self.assertEqual(
            source_evidence_role(source("model", "https://example.test/models/example", "official_model_docs")),
            "model_detail",
        )
        self.assertEqual(source_evidence_role(source("release", "https://example.test/changelog")), "release_note")
        self.assertEqual(source_evidence_role(source("news", "https://example.test/news/update")), "announcement")
        self.assertEqual(source_evidence_role(source("guide", "https://example.test/guides/batch")), "pricing_support")

    def test_source_priority_is_generic_and_input_order_independent(self):
        candidates = [
            source("news", "https://example.test/news/update"),
            source("release", "https://example.test/changelog"),
            source("guide", "https://example.test/guides/batch"),
            source("model", "https://example.test/models/example", "official_model_docs"),
            source("pricing", "https://example.test/pricing"),
        ]
        for permutation in itertools.islice(itertools.permutations(candidates), 5):
            sources = {item["sourceId"]: item for item in permutation}
            refs = [item["sourceId"] for item in reversed(permutation)]
            self.assertEqual(
                select_official_source_url(
                    refs,
                    sources,
                    existing_url=None,
                    price_source_refs=refs,
                    public_official_url=None,
                    website_official_url=None,
                ),
                "https://example.test/pricing",
            )

    def test_existing_legal_url_wins_over_fresh_ranking(self):
        sources = {
            "pricing": source("pricing", "https://example.test/pricing"),
            "news": source("news", "https://example.test/news/update"),
        }
        self.assertEqual(
            select_official_source_url(
                ["pricing", "news"],
                sources,
                existing_url="https://example.test/news/update",
                price_source_refs=["pricing", "news"],
                public_official_url=None,
                website_official_url=None,
            ),
            "https://example.test/news/update",
        )

    def test_semantically_ambiguous_sources_fail_instead_of_using_lexical_order(self):
        sources = {
            "a": source("a", "https://example.test/guides/alpha"),
            "z": source("z", "https://example.test/guides/zeta"),
        }
        with self.assertRaisesRegex(ValueError, "ambiguous official source candidates"):
            select_official_source_url(
                ["z", "a"],
                sources,
                existing_url=None,
                price_source_refs=["a", "z"],
                public_official_url=None,
                website_official_url=None,
            )


if __name__ == "__main__":
    unittest.main()
