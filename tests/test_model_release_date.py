import copy
import json
import re
import unittest
from pathlib import Path

from scripts.generate_pricing_v2_preview import source_refs_for
from scripts.validate import validate_release_metadata

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "data" / "canonical" / "models.json"
PREVIEW = ROOT / "data" / "pricing-v2-preview"
PROJECTION = PREVIEW / "generated" / "model-pricing.v2.json"


class ModelReleaseDateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.canonical = json.loads(CANONICAL.read_text(encoding="utf-8"))
        cls.identities = json.loads((PREVIEW / "model-identity-registry.json").read_text(encoding="utf-8"))
        cls.models = json.loads((PREVIEW / "models.json").read_text(encoding="utf-8"))
        cls.prices = json.loads((PREVIEW / "prices.json").read_text(encoding="utf-8"))
        cls.projection = json.loads(PROJECTION.read_text(encoding="utf-8"))["models"]
        cls.by_model = {(r["provider_id"], r["model_id"]): r for r in cls.canonical}
        cls.by_identity = {r["internalId"]: r for r in cls.identities}
        cls.by_projection = {r["canonicalInternalId"]: r for r in cls.projection}

    def test_valid_date_passes(self):
        validate_release_metadata(self.by_model[("openai", "gpt-6.1-sol")], ("openai", "gpt-6.1-sol"))

    def test_invalid_format_and_day_fail(self):
        row = copy.deepcopy(self.by_model[("openai", "gpt-6.1-sol")])
        for invalid in ("2026-9-29", "2026-09", "2026-02-30", "2026-09-29T00:00:00Z"):
            with self.subTest(invalid=invalid), self.assertRaises(SystemExit):
                row["released_at"] = invalid
                validate_release_metadata(row, ("openai", "gpt-6.1-sol"))

    def test_null_and_missing_pass(self):
        row = {"accessed_at": "2026-10-03T00:00:00Z", "last_verified_at": "2026-10-03T00:00:00Z"}
        validate_release_metadata(row, ("test", "missing"))
        row["released_at"] = None
        validate_release_metadata(row, ("test", "null"))

    def test_checked_at_and_last_verified_never_infer_release(self):
        row = {"checked_at": "2026-10-03T00:00:00Z", "last_verified_at": "2026-10-03T00:00:00Z"}
        validate_release_metadata(row, ("test", "undated"))
        self.assertNotIn("released_at", row)

    def test_generation_roundtrip(self):
        for row in self.canonical:
            internal = f"{row['provider_id']}/{row['model_id']}"
            if internal not in self.by_identity:
                continue
            identity = self.by_identity[internal]
            if identity["identityType"] == "canonical_model":
                self.assertEqual(identity.get("releasedAt"), row.get("released_at"), internal)

    def test_website_projection_keeps_date_and_source(self):
        for row in self.canonical:
            internal = f"{row['provider_id']}/{row['model_id']}"
            projected = self.by_projection.get(internal)
            if projected is None:
                continue
            self.assertEqual(projected.get("releasedAt"), row.get("released_at"), internal)
            if row.get("release_evidence"):
                self.assertEqual(projected["releaseSourceUrl"], row["release_evidence"]["url"])

    def test_price_records_have_no_release_fields(self):
        for price in self.prices:
            self.assertNotIn("releasedAt", price)
            self.assertNotIn("releaseSourceRef", price)
            self.assertNotIn("released_at", price)

    def test_new_release_source_is_not_price_ref(self):
        row = self.by_model[("cohere", "aya-expanse-32b")]
        release_url = row["release_evidence"]["url"]
        refs = {url: url for url in [row["official_source_url"], release_url]}
        self.assertNotIn(release_url, source_refs_for("cohere", row, None, refs))
        self.assertIn(release_url, source_refs_for("cohere", row, None, refs, include_release=True))

    def test_alias_only_does_not_get_independent_release_date(self):
        for identity in self.identities:
            if identity["identityType"] != "canonical_model" and not identity["publicDatasetIds"]:
                self.assertIsNone(identity.get("releasedAt"), identity["internalId"])

    def test_canonical_id_mapping_is_stable(self):
        for row in self.canonical:
            if not row.get("released_at"):
                continue
            internal = f"{row['provider_id']}/{row['model_id']}"
            self.assertEqual(self.by_identity[internal]["canonicalOfficialId"], row["model_id"])
            self.assertRegex(row["released_at"], r"^\d{4}-\d{2}-\d{2}$")


if __name__ == "__main__":
    unittest.main()
