import unittest
import json
from unittest.mock import patch
from scripts import generate_pricing_v2_preview as generator
from scripts import generate_website_projection_v2 as projection
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

    def test_real_gpt41_canonical_active_keeps_review_gate(self):
        canonical = json.loads((generator.CANONICAL / "models.json").read_text(encoding="utf-8"))
        website = json.loads((generator.GENERATED / "model-pricing.website-preview.json").read_text(encoding="utf-8"))
        public = next(row for row in canonical if (row["provider_id"], row["model_id"]) == ("openai", "gpt-4.1"))
        editorial = next(row for row in website if row["id"] == "gpt-4.1")
        self.assertEqual(public["status"], "active")
        self.assertEqual(status_parts("openai", "gpt-4.1", public, editorial), {
            "lifecycleStatus": "active", "releaseStage": "legacy",
            "availability": "Legacy", "verificationStatus": "review_required",
        })

    def test_real_mini_preserves_independent_review_lifecycle(self):
        self.assertEqual(status_parts("openai", "gpt-4.1-mini", None, {"status": "legacy"}), {
            "lifecycleStatus": "active", "releaseStage": "legacy",
            "availability": "Legacy", "verificationStatus": "review_required",
        })

    def test_real_nano_is_not_promoted_by_editorial_latest(self):
        result = status_parts("openai", "gpt-4.1-nano", {"status": "deprecated"}, {"status": "latest"})
        self.assertEqual((result["lifecycleStatus"], result["verificationStatus"]), ("deprecated", "review_required"))

    def test_other_review_required_ids_keep_existing_semantics(self):
        for provider, model in generator.REVIEW_REQUIRED_IDS - {("openai", "gpt-4.1"), ("openai", "gpt-4.1-mini")}:
            with self.subTest(model=model):
                result = status_parts(provider, model, {"status": "active"}, {"status": "latest"})
                self.assertEqual((result["lifecycleStatus"], result["releaseStage"], result["verificationStatus"]),
                                 ("deprecated", "legacy", "review_required"))

    def test_real_gpt41_canonical_deprecated_beats_editorial_latest(self):
        result = status_parts("openai", "gpt-4.1", {"status": "deprecated"}, {"status": "latest"})
        self.assertEqual((result["lifecycleStatus"], result["verificationStatus"]), ("deprecated", "review_required"))

    def test_real_gpt41_canonical_retired_is_preserved(self):
        self.assertEqual(status_parts("openai", "gpt-4.1", {"status": "retired"}, {"status": "active"})["lifecycleStatus"], "retired")

    def test_real_gpt41_without_canonical_cannot_infer_active(self):
        for public in (None, {}, {"status": "unknown"}):
            with self.subTest(public=public):
                result = status_parts("openai", "gpt-4.1", public, {"status": "latest", "lifecycleStatus": "active"})
                self.assertEqual((result["lifecycleStatus"], result["verificationStatus"]), ("unknown", "review_required"))

    def test_real_gpt41_generated_candidate_preserves_calculation_and_access_gates(self):
        canonical = generator.read_json(generator.CANONICAL / "models.json")
        public = next(row for row in canonical if (row["provider_id"], row["model_id"]) == ("openai", "gpt-4.1"))
        editorial = next(row for row in generator.read_json(projection.COMPATIBILITY_PREVIEW) if row["id"] == "gpt-4.1")
        parts = status_parts("openai", "gpt-4.1", public, editorial)
        outputs = {}
        for filename in ("models.json", "model-identity-registry.json"):
            outputs[filename] = generator.read_json(generator.PREVIEW / filename)
            target = next(row for row in outputs[filename] if row["internalId"] == "openai/gpt-4.1")
            target.update(parts)
            self.assertEqual((target["accessStatus"], target["bindingStatus"], target["availability"]),
                             ("unknown", "unresolved", "Legacy"))
        prices = generator.read_json(generator.PREVIEW / "prices.json")
        self.assertFalse(any(row["calculationDefault"] for row in prices if row["modelInternalId"] == "openai/gpt-4.1"))
        read_json = projection.read_json
        def candidate_json(path):
            if path.parent == generator.PREVIEW and path.name in outputs:
                return outputs[path.name]
            return read_json(path)
        baseline = read_json(projection.ARTIFACT)
        with patch.object(projection, "read_json", side_effect=candidate_json):
            artifact, _ = projection.build_projection(
                baseline["effectiveAt"],
                website_dataset=generator.GENERATED / "model-pricing.website-preview.json",
                generated_at_value=baseline["generatedAt"],
                existing_projection_data=baseline,
            )
        candidate = next(row for row in artifact["models"] if row["id"] == "gpt-4.1")
        self.assertEqual(candidate["lifecycleStatus"], "active")
        self.assertIs(candidate["defaultSafe"], False)
        self.assertEqual(candidate["verificationStatus"], "review_required")
        self.assertIsNone(candidate["selectedPriceRecordId"])


if __name__ == "__main__":
    unittest.main()
