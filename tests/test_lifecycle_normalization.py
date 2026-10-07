import unittest
from scripts.generate_pricing_v2_preview import status_parts


class LifecycleNormalizationTests(unittest.TestCase):
    def parts(self, public, website):
        return status_parts("fixture-provider", "arbitrary-model", public, website)

    def test_canonical_active_is_not_overridden_by_editorial_legacy(self):
        self.assertEqual(self.parts({"status": "active"}, {"status": "legacy"})["lifecycleStatus"], "active")

    def test_canonical_deprecated_is_not_promoted_by_editorial_latest(self):
        self.assertEqual(self.parts({"status": "deprecated"}, {"status": "latest"})["lifecycleStatus"], "deprecated")

    def test_canonical_retired_is_authoritative(self):
        self.assertEqual(self.parts({"status": "retired"}, {"status": "active"})["lifecycleStatus"], "retired")

    def test_public_preview_has_active_lifecycle_and_preview_stage(self):
        result = self.parts({"status": "preview"}, None)
        self.assertEqual((result["lifecycleStatus"], result["releaseStage"]), ("active", "preview"))

    def test_explicit_website_lifecycle_is_authoritative_without_canonical(self):
        self.assertEqual(self.parts(None, {"status": "latest", "lifecycleStatus": "retired"})["lifecycleStatus"], "retired")

    def test_editorial_legacy_alone_is_not_deprecation_evidence(self):
        self.assertEqual(self.parts(None, {"status": "legacy"})["lifecycleStatus"], "unknown")

    def test_retired_website_fact_remains_a_fact(self):
        result = self.parts(None, {"status": "retired"})
        self.assertEqual((result["lifecycleStatus"], result["releaseStage"]), ("retired", "legacy"))


if __name__ == "__main__":
    unittest.main()
