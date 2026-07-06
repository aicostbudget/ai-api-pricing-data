import json
import unittest
from datetime import datetime, time, timedelta

from scripts.validate_pricing_v2_preview import PREVIEW, validate_preview


class PricingV2PreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.counts = validate_preview()
        cls.identities = json.loads((PREVIEW / "model-identity-registry.json").read_text(encoding="utf-8"))
        cls.dispositions = json.loads((PREVIEW / "candidate-disposition-map.json").read_text(encoding="utf-8"))
        cls.models = json.loads((PREVIEW / "models.json").read_text(encoding="utf-8"))
        cls.prices = json.loads((PREVIEW / "prices.json").read_text(encoding="utf-8"))
        cls.report = json.loads((PREVIEW / "convergence-report.json").read_text(encoding="utf-8"))
        cls.phase2_conflict = json.loads(
            (PREVIEW / "phase2-conflict-resolution-report.json").read_text(encoding="utf-8")
        )
        cls.phase2_matrix = json.loads((PREVIEW / "phase2-evidence-matrix.json").read_text(encoding="utf-8"))
        cls.phase2_readiness = json.loads((PREVIEW / "phase2-cutover-readiness.json").read_text(encoding="utf-8"))
        cls.phase25_evidence = json.loads((PREVIEW / "phase2-5-evidence-completion.json").read_text(encoding="utf-8"))
        cls.phase25_default_safe = json.loads(
            (PREVIEW / "phase2-5-default-safe-report.json").read_text(encoding="utf-8")
        )
        cls.phase25_blockers = json.loads(
            (PREVIEW / "phase2-5-website-integration-blockers.json").read_text(encoding="utf-8")
        )
        cls.phase25_readiness = json.loads((PREVIEW / "phase2-5-cutover-readiness.json").read_text(encoding="utf-8"))
        cls.phase26_resolution = json.loads((PREVIEW / "phase2-6-p0-resolution.json").read_text(encoding="utf-8"))
        cls.phase26_closure = json.loads((PREVIEW / "phase2-6-default-safe-closure.json").read_text(encoding="utf-8"))
        cls.phase26_readiness = json.loads((PREVIEW / "phase2-6-cutover-readiness.json").read_text(encoding="utf-8"))
        cls.projection = json.loads((PREVIEW / "generated" / "model-pricing.website-preview.json").read_text(encoding="utf-8"))

    def identity(self, internal_id):
        return next(item for item in self.identities if item["internalId"] == internal_id)

    def disposition(self, candidate_id):
        return next(item for item in self.dispositions if item["candidateId"] == candidate_id)

    def model(self, internal_id):
        return next(item for item in self.models if item["internalId"] == internal_id)

    def projection_row(self, model_id):
        return next(item for item in self.projection if item["id"] == model_id)

    def test_report_counts_match_phase_1_baseline(self):
        self.assertEqual(self.report["candidateUnionCount"], 39)
        self.assertEqual(self.report["websiteOnlyCount"], 21)
        self.assertEqual(self.report["publicOnlyCount"], 7)
        self.assertEqual(self.report["commonCount"], 11)
        self.assertEqual(self.report["aliasCount"], 2)
        self.assertEqual(len(self.dispositions), 39)
        self.assertEqual(self.report["normalizedCanonicalIdentityCount"], len(self.models))
        self.assertEqual(self.report["candidateDispositionCounts"]["unresolved"], 3)

    def test_claude_sonnet_5_intro_is_not_canonical_model(self):
        intro = self.disposition("anthropic/claude-sonnet-5-intro")
        self.assertEqual(intro["disposition"], "merged_duplicate")
        self.assertEqual(intro["mergeTarget"], "anthropic/claude-sonnet-5")
        self.assertNotIn("anthropic/claude-sonnet-5-intro", {item["internalId"] for item in self.identities})
        self.assertNotIn("anthropic/claude-sonnet-5-intro", {item["internalId"] for item in self.models})
        sonnet = self.model("anthropic/claude-sonnet-5")
        self.assertIsNotNone(sonnet["defaultPriceRecordId"])
        default_price = next(item for item in self.prices if item["pricingId"] == sonnet["defaultPriceRecordId"])
        self.assertEqual(default_price["effectiveUntil"], "2026-08-31")
        future = next(
            item
            for item in self.prices
            if item["pricingId"] == "price:anthropic/claude-sonnet-5:standard:short:2026-09-01"
        )
        self.assertEqual(future["effectiveFrom"], "2026-09-01")

    def test_claude_sonnet_5_effective_date_boundary(self):
        records = [
            item
            for item in self.prices
            if item["modelInternalId"] == "anthropic/claude-sonnet-5"
            and item["processingMode"] == "standard"
        ]

        def active_at(moment):
            selected = []
            for record in records:
                start = record["effectiveFrom"]
                end = record["effectiveUntil"]
                if start and moment < datetime.combine(datetime.fromisoformat(start).date(), time.min):
                    continue
                if end and moment >= datetime.combine(datetime.fromisoformat(end).date() + timedelta(days=1), time.min):
                    continue
                selected.append(record["pricingId"])
            return selected

        self.assertEqual(
            active_at(datetime.fromisoformat("2026-08-31T23:59:59")),
            ["price:anthropic/claude-sonnet-5:standard:intro:2026-07-05"],
        )
        self.assertEqual(
            active_at(datetime.fromisoformat("2026-09-01T00:00:00")),
            ["price:anthropic/claude-sonnet-5:standard:short:2026-09-01"],
        )

    def test_deepseek_aliases_target_v4_flash(self):
        for internal_id in ("deepseek/deepseek-chat", "deepseek/deepseek-reasoner"):
            alias = self.identity(internal_id)
            self.assertEqual(alias["identityType"], "alias")
            self.assertEqual(alias["aliasTargetInternalId"], "deepseek/deepseek-v4-flash")
            row = self.projection_row(internal_id.split("/", 1)[1])
            self.assertEqual(row["inputPrice"], 0.14)
            self.assertEqual(row["cachedInputPrice"], 0.0028)
            self.assertEqual(row["outputPrice"], 0.28)

    def test_grok_3_retired_redirect_is_preserved(self):
        grok = self.identity("xai/grok-3")
        self.assertEqual(grok["identityType"], "historical_reference")
        self.assertEqual(grok["lifecycleStatus"], "retired")
        self.assertIsNone(grok["replacementInternalId"])
        self.assertEqual(grok["redirectTargetInternalId"], "xai/grok-4.3")
        self.assertEqual(grok["billingModelInternalId"], "xai/grok-4.3")
        row = self.projection_row("grok-3")
        self.assertEqual(row["inputPrice"], 1.25)
        self.assertEqual(row["outputPrice"], 2.5)

    def test_gpt_4_1_family_is_review_required_without_safe_defaults(self):
        for internal_id in ("openai/gpt-4.1", "openai/gpt-4.1-mini", "openai/gpt-4.1-nano"):
            identity = self.identity(internal_id)
            self.assertEqual(identity["verificationStatus"], "review_required")
            if internal_id in {item["internalId"] for item in self.models}:
                self.assertIsNone(self.model(internal_id)["defaultPriceRecordId"])
            row = self.projection_row(internal_id.split("/", 1)[1])
            self.assertIsNone(row["inputPrice"])
            self.assertIsNone(row["cachedInputPrice"])
            self.assertIsNone(row["outputPrice"])
            self.assertEqual(row["verificationStatus"], "review_required")

    def test_gemini_2_5_cached_input_difference_is_classified(self):
        expected = {
            item["internalId"]
            for item in self.report["websiteCompatibilityPreviewParity"]["expected_difference"]
        }
        self.assertIn("google-gemini/gemini-2.5-pro", expected)
        self.assertIn("google-gemini/gemini-2.5-flash", expected)
        self.assertEqual(self.projection_row("gemini-2.5-pro")["cachedInputPrice"], 0.125)
        self.assertEqual(self.projection_row("gemini-2.5-flash")["cachedInputPrice"], 0.03)

    def test_phase2_evidence_matrix_covers_every_price(self):
        self.assertEqual(len(self.phase2_matrix), len(self.prices))
        self.assertEqual(
            {row["pricingId"] for row in self.phase2_matrix},
            {price["pricingId"] for price in self.prices},
        )
        verified_rows = [row for row in self.phase2_matrix if row["verificationStatus"] == "verified"]
        self.assertTrue(verified_rows)
        self.assertTrue(all(row["evidenceCompleteness"] == "complete" for row in verified_rows))

    def test_phase2_cutover_remains_blocked_by_review_required_gpt_family(self):
        self.assertEqual(self.phase2_readiness["overall"], "blocked")
        self.assertFalse(self.phase2_readiness["safeToEnterWebsiteIntegrationPlanning"])
        self.assertEqual(
            self.phase2_conflict["unresolvedIdentitiesAfter"],
            ["openai/gpt-4.1", "openai/gpt-4.1-mini", "openai/gpt-4.1-nano"],
        )
        self.assertFalse(self.phase2_conflict["gpt4_1Family"]["safeDefaultCalculationPrice"])
        self.assertIsNone(self.phase2_conflict["grok3"]["replacementInternalId"])

    def test_phase2_5_default_safe_gate_counts(self):
        self.assertEqual(len(self.phase25_evidence), 49)
        self.assertEqual(self.phase25_default_safe["productionDefaultCandidateCount"], 28)
        self.assertEqual(self.phase25_default_safe["defaultSafeCount"], 28)
        self.assertEqual(self.phase25_default_safe["defaultUnsafeCount"], 21)
        self.assertEqual(self.phase25_default_safe["P0PartialBefore"], 15)
        self.assertEqual(self.phase25_default_safe["P0PartialAfter"], 0)
        self.assertEqual(self.phase25_default_safe["P1PartialCount"], 6)
        self.assertEqual(self.phase25_default_safe["P2PartialCount"], 0)
        self.assertEqual(self.phase25_default_safe["P3PartialCount"], 5)

    def test_phase2_5_gpt_and_grok_policies(self):
        evidence_by_model = {row["modelInternalId"]: row for row in self.phase25_evidence}
        for internal_id in ("openai/gpt-4.1", "openai/gpt-4.1-mini", "openai/gpt-4.1-nano"):
            matching_rows = [row for row in self.phase25_evidence if row["modelInternalId"] == internal_id]
            self.assertTrue(matching_rows)
            self.assertTrue(all(not row["defaultSafe"] for row in matching_rows))
            self.assertTrue(all(row["priorityClass"] == "P3" for row in matching_rows))
        self.assertTrue(evidence_by_model["xai/grok-4.3"]["defaultSafe"])
        grok_3_rows = [row for row in self.phase25_blockers if row["websiteModelId"] == "grok-3"]
        self.assertTrue(grok_3_rows)
        self.assertTrue(all(row["recommendedIntegrationAction"] == "integrate_with_warning" for row in grok_3_rows))

    def test_phase2_6_closes_p0_default_safe_gate(self):
        self.assertTrue(self.phase26_closure["closureGatePassed"])
        self.assertEqual(self.phase26_closure["defaultCandidatesBefore"], 31)
        self.assertEqual(self.phase26_closure["defaultCandidatesAfter"], 28)
        self.assertEqual(self.phase26_closure["safeBefore"], 26)
        self.assertEqual(self.phase26_closure["safeAfter"], 28)
        self.assertEqual(self.phase26_closure["unsafeBefore"], 5)
        self.assertEqual(self.phase26_closure["unsafeAfter"], 0)
        self.assertEqual(self.phase26_resolution["P0BlockersAfter"], [])
        self.assertEqual(
            self.phase26_closure["excludedCandidates"],
            ["cohere/command-a-plus", "openai/gpt-5", "openai/o3"],
        )
        self.assertEqual(
            self.phase26_closure["evidenceBasedUpgrades"],
            ["google-gemini/gemini-3.1-pro-preview", "google-gemini/gemini-3.5-flash"],
        )
        self.assertTrue(self.phase26_readiness["safeToEnterWebsiteIntegrationPlanning"])
        self.assertEqual(self.phase26_readiness["defaultPricingReadiness"], "ready")
        self.assertEqual(self.phase26_readiness["integrationMappingCount"], 162)

    def test_phase2_6_website_usage_counts_are_mapping_entries(self):
        self.assertTrue(self.phase25_readiness["safeToEnterWebsiteIntegrationPlanning"])
        self.assertEqual(self.phase25_readiness["defaultPricingReadiness"], "ready")
        counts = self.phase25_readiness["websiteIntegrationActionCounts"]
        self.assertEqual(sum(counts.values()), 162)
        self.assertEqual(counts["safe_to_integrate"], 139)
        self.assertEqual(counts["integrate_with_warning"], 8)
        self.assertEqual(counts.get("exclude_from_default", 0), 0)
        self.assertEqual(counts["keep_existing_temporarily"], 15)
        self.assertEqual(counts.get("blocked", 0), 0)


if __name__ == "__main__":
    unittest.main()
