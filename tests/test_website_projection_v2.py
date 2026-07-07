import json
import unittest
from unittest.mock import patch

from scripts.generate_website_projection_v2 import (
    ARTIFACT,
    DEFAULT_SELECTION_RULE,
    REPORT,
    atomic_write_json,
    build_phase45_audits,
    build_projection,
)


class WebsiteProjectionV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifact, cls.report = build_projection()
        cls.audits = build_phase45_audits(cls.artifact, cls.report)
        cls.rows = cls.artifact["models"]
        cls.by_id = {row["id"]: row for row in cls.rows}
        cls.by_internal = {row["canonicalInternalId"]: row for row in cls.rows}

    def test_required_contract_fields_are_present(self):
        required = set(self.artifact["requiredFields"])
        self.assertEqual(
            required,
            {
                "id",
                "provider",
                "model",
                "inputPrice",
                "cachedInputPrice",
                "outputPrice",
                "status",
                "defaultSafe",
                "verificationStatus",
                "verifiedAt",
                "officialSourceUrl",
                "contextWindow",
            },
        )
        for row in self.rows:
            self.assertTrue(required <= set(row))
            self.assertEqual(row["defaultPriceSelectionRule"], DEFAULT_SELECTION_RULE)

    def test_context_window_and_verified_at_semantics(self):
        self.assertTrue(all(row["contextWindow"] is None for row in self.rows))
        for row in self.rows:
            if row["verificationStatus"] in {"review_required", "unconfirmed_price"}:
                self.assertIsNone(row["verifiedAt"])
            if row["defaultSafe"]:
                self.assertIsNotNone(row["verifiedAt"])

    def test_default_safe_rows_are_the_only_rows_with_calculation_prices(self):
        for row in self.rows:
            prices = (row["inputPrice"], row["cachedInputPrice"], row["outputPrice"])
            if row["defaultSafe"]:
                self.assertIsNotNone(row["inputPrice"])
                self.assertIsNotNone(row["outputPrice"])
            else:
                self.assertEqual(prices, (None, None, None))

    def test_claude_sonnet_5_effective_date_boundaries_are_utc(self):
        intro_artifact, _ = build_projection("2026-08-31T23:59:59Z")
        standard_artifact, _ = build_projection("2026-09-01T00:00:00Z")
        intro = next(row for row in intro_artifact["models"] if row["canonicalInternalId"] == "anthropic/claude-sonnet-5")
        standard = next(row for row in standard_artifact["models"] if row["canonicalInternalId"] == "anthropic/claude-sonnet-5")
        self.assertEqual(intro["selectedPriceRecordId"], "price:anthropic/claude-sonnet-5:standard:intro:2026-07-05")
        self.assertEqual(intro["inputPrice"], 2)
        self.assertEqual(intro["outputPrice"], 10)
        self.assertEqual(standard["selectedPriceRecordId"], "price:anthropic/claude-sonnet-5:standard:short:2026-09-01")
        self.assertEqual(standard["inputPrice"], 3)
        self.assertEqual(standard["outputPrice"], 15)
        self.assertEqual(intro_artifact["effectiveTimezone"], "UTC")
        self.assertEqual(standard_artifact["effectiveTimezone"], "UTC")

    def test_grok_3_redirected_billing_and_historical_isolation(self):
        grok = self.by_internal["xai/grok-3"]
        self.assertEqual(grok["status"], "retired")
        self.assertEqual(grok["identityType"], "historical_reference")
        self.assertEqual(grok["redirectTargetInternalId"], "xai/grok-4.3")
        self.assertEqual(grok["billingModelInternalId"], "xai/grok-4.3")
        self.assertEqual(grok["selectedBillingPriceRecordId"], "price:xai/grok-4.3:standard:short:current")
        self.assertEqual(grok["inputPrice"], 1.25)
        self.assertEqual(grok["outputPrice"], 2.5)
        self.assertFalse(grok["historicalPrice"]["currentCalculationEligible"])
        self.assertEqual(grok["historicalPrice"]["inputPrice"], 3)
        self.assertEqual(grok["historicalPrice"]["outputPrice"], 15)

    def test_gpt_4_1_family_and_excluded_defaults_are_null(self):
        for internal_id in ("openai/gpt-4.1", "openai/gpt-4.1-mini", "openai/gpt-4.1-nano"):
            row = self.by_internal[internal_id]
            self.assertEqual(row["verificationStatus"], "review_required")
            self.assertFalse(row["defaultSafe"])
            self.assertIsNone(row["inputPrice"])
            self.assertIsNone(row["outputPrice"])
        for internal_id in ("cohere/command-a-plus", "openai/gpt-5", "openai/o3"):
            row = self.by_internal[internal_id]
            self.assertFalse(row["defaultSafe"])
            self.assertIn("excluded_default_candidate", row["blockedFromDefaultReasons"])
            self.assertIsNone(row["inputPrice"])
            self.assertIsNone(row["outputPrice"])

    def test_alias_behavior_is_preserved(self):
        chat = self.by_internal["deepseek/deepseek-chat"]
        reasoner = self.by_internal["deepseek/deepseek-reasoner"]
        self.assertEqual(chat["alias"]["targetInternalId"], "deepseek/deepseek-v4-flash")
        self.assertEqual(chat["alias"]["routingDetails"]["mode"], "non_thinking")
        self.assertEqual(reasoner["alias"]["targetInternalId"], "deepseek/deepseek-v4-flash")
        self.assertEqual(reasoner["alias"]["routingDetails"]["mode"], "thinking")
        self.assertTrue(chat["defaultSafe"])
        self.assertTrue(reasoner["defaultSafe"])

    def test_report_counts_and_parity_buckets(self):
        self.assertEqual(self.report["projectionModelCount"], len(self.rows))
        self.assertEqual(self.report["projectionModelCount"], 38)
        self.assertEqual(self.report["defaultSafeModelCount"], 31)
        self.assertEqual(self.report["unsafeIdentityCount"], 7)
        self.assertEqual(self.report["nullPriceCount"], 7)
        self.assertEqual(self.report["parity"]["websiteModelCount"], 32)
        self.assertEqual(sum(self.report["parity"]["counts"].values()), 32)
        self.assertEqual(self.report["parity"]["counts"]["unsafe_difference"], 4)

    def test_artifact_paths_and_no_runtime_network_dependency(self):
        self.assertEqual(str(ARTIFACT).endswith(r"data\pricing-v2-preview\generated\model-pricing.v2.json"), True)
        self.assertEqual(str(REPORT).endswith(r"data\pricing-v2-preview\phase4a-website-projection-report.json"), True)
        self.assertTrue(self.artifact["noRuntimeNetworkDependency"])

    def test_atomic_write_replaces_complete_json(self):
        with patch("pathlib.Path.mkdir"), patch("pathlib.Path.write_text") as write_text, patch("os.replace") as replace:
            path = ARTIFACT.with_name("projection.json")
            atomic_write_json(path, {"ok": True})
            write_text.assert_called_once()
            replace.assert_called_once_with(path.with_name("projection.json.tmp"), path)
            self.assertIn('"ok": true', write_text.call_args.args[0])

    def test_phase45_reconciliations_are_complete(self):
        safe = self.audits["safe_reconciliation"]
        rows = self.audits["row_reconciliation"]
        unsafe = self.audits["unsafe_audit"]
        context = self.audits["context_audit"]
        self.assertEqual(safe["stats"]["safePriceRecordsInput"], 28)
        self.assertEqual(safe["stats"]["mappedToProjection"], 28)
        self.assertEqual(safe["stats"]["unexplained"], 0)
        self.assertEqual(rows["counts"]["canonical_model"], 35)
        self.assertEqual(rows["counts"]["alias"], 2)
        self.assertEqual(rows["counts"]["redirecting_identity"], 1)
        self.assertEqual(unsafe["beforePhase4A5UnsafeDifferenceCount"], 16)
        self.assertEqual(unsafe["currentUnsafeDifferenceCount"], 4)
        self.assertEqual(len(unsafe["blockerUnsafeDifferences"]), 0)
        self.assertEqual(context["contextWindowRows"], 38)
        self.assertEqual(context["verifiedCanonicalContextWindowCount"], 0)


if __name__ == "__main__":
    unittest.main()
