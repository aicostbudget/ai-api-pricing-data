import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DeprecatedWebsiteStatusTests(unittest.TestCase):
    def test_canonical_deprecation_overrides_legacy_editorial_status(self):
        canonical = json.loads((ROOT / "data/canonical/models.json").read_text(encoding="utf-8"))
        preview = json.loads((ROOT / "data/pricing-v2-preview/generated/model-pricing.website-preview.json").read_text(encoding="utf-8"))
        deprecated_ids = {row["model_id"] for row in canonical if row["status"] == "deprecated"}
        matched = [row for row in preview if row["id"] in deprecated_ids]
        self.assertTrue(matched)
        for row in matched:
            self.assertEqual(row["status"], "deprecated", row["id"])

    def test_rich_projection_preserves_deprecated_display_status(self):
        projection = json.loads((ROOT / "data/pricing-v2-preview/generated/model-pricing.v2.json").read_text(encoding="utf-8"))
        canonical = json.loads((ROOT / "data/canonical/models.json").read_text(encoding="utf-8"))
        deprecated = {row["provider_id"] + "/" + row["model_id"] for row in canonical if row["status"] == "deprecated"}
        rows = [row for row in projection["models"] if row["canonicalInternalId"] in deprecated]
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row["status"], "deprecated", row["id"])
            self.assertFalse(row["defaultSafe"], row["id"])
