import json
from datetime import datetime
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.generate_website_projection_v2 import (
    ARTIFACT,
    DEFAULT_SELECTION_RULE,
    PREVIEW,
    REPORT,
    atomic_write_json,
    build_phase45_audits,
    build_projection,
)

# Mirrors the 35-row legacy Website parity input captured in the committed Phase 4A report.
WEBSITE_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "website-model-pricing.json"


class WebsiteProjectionV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifact, cls.report = build_projection(website_dataset=WEBSITE_FIXTURE)
        cls.audits = build_phase45_audits(cls.artifact, cls.report, website_dataset=WEBSITE_FIXTURE)
        cls.rows = cls.artifact["models"]
        cls.by_id = {row["id"]: row for row in cls.rows}
        cls.by_internal = {row["canonicalInternalId"]: row for row in cls.rows}

    def test_projection_default_times_are_ordered_utc_instants(self):
        self.assertEqual(self.artifact["generatedAt"], self.artifact["effectiveAt"])
        generated_at = datetime.fromisoformat(self.artifact["generatedAt"].replace("Z", "+00:00"))
        verified_at = datetime.fromisoformat("2026-08-08T18:00:00+00:00")
        self.assertGreaterEqual(generated_at, verified_at)
        self.assertGreaterEqual(self.artifact["effectiveAt"], "2026-07-24T00:00:00Z")

    def test_claude_opus_5_projection_is_default_safe_and_current_opus(self):
        opus5 = self.by_internal["anthropic/claude-opus-5"]
        opus48 = self.by_internal["anthropic/claude-opus-4.8"]
        self.assertTrue(opus5["defaultSafe"])
        self.assertEqual(opus5["selectedPriceRecordId"], "price:anthropic/claude-opus-5:standard:short:current")
        self.assertEqual(opus5["selectedPriceEffectiveFrom"], "2026-07-24")
        self.assertGreaterEqual(self.artifact["effectiveAt"], "2026-07-24T00:00:00Z")
        self.assertEqual((opus5["inputPrice"], opus5["cachedInputPrice"], opus5["outputPrice"]), (5, 0.5, 25))
        self.assertEqual((opus5["batchInputPrice"], opus5["batchOutputPrice"]), (2.5, 12.5))
        self.assertTrue(opus48["defaultSafe"])

        current_opus_rows = [
            row
            for row in self.rows
            if row["provider"] == "anthropic"
            and row["model"].startswith("Claude Opus")
            and row["lifecycleStatus"] == "active"
            and row["releaseStage"] == "stable"
            and row["defaultSafe"]
        ]
        selected = max(current_opus_rows, key=lambda row: tuple(int(part) for part in row["id"].removeprefix("claude-opus-").split(".")))
        self.assertEqual(selected["canonicalInternalId"], "anthropic/claude-opus-5")

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

    def test_claude_sonnet_5_permanent_standard_price_has_no_boundary_switch(self):
        august_artifact, _ = build_projection("2026-08-31T23:59:59Z", website_dataset=WEBSITE_FIXTURE)
        september_artifact, _ = build_projection("2026-09-01T00:00:00Z", website_dataset=WEBSITE_FIXTURE)
        for artifact in (august_artifact, september_artifact):
            sonnet = next(row for row in artifact["models"] if row["canonicalInternalId"] == "anthropic/claude-sonnet-5")
            self.assertEqual(sonnet["selectedPriceRecordId"], "price:anthropic/claude-sonnet-5:standard:short:current")
            self.assertEqual((sonnet["inputPrice"], sonnet["outputPrice"]), (2, 10))
            self.assertIsNone(sonnet["selectedPriceEffectiveUntil"])
            self.assertEqual(artifact["effectiveTimezone"], "UTC")

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
        self.assertEqual(self.report["projectionModelCount"], 45)
        self.assertEqual(self.report["defaultSafeModelCount"], 38)
        self.assertEqual(self.report["unsafeIdentityCount"], 7)
        self.assertEqual(self.report["nullPriceCount"], 7)
        self.assertEqual(self.report["parity"]["websiteModelCount"], 36)
        self.assertEqual(sum(self.report["parity"]["counts"].values()), 36)
        self.assertEqual(self.report["parity"]["counts"]["unsafe_difference"], 4)

    def test_gpt_5_6_rows_use_standard_short_defaults(self):
        expected = {
            "openai/gpt-5.6-sol": (4, 0.4, 20),
            "openai/gpt-5.6-terra": (2, 0.2, 12),
            "openai/gpt-5.6-luna": (0.2, 0.02, 1.2),
        }
        for internal_id, prices in expected.items():
            row = self.by_internal[internal_id]
            self.assertTrue(row["defaultSafe"])
            self.assertEqual(row["selectedPriceRecordId"], f"price:{internal_id}:standard:short:current")
            self.assertEqual((row["inputPrice"], row["cachedInputPrice"], row["outputPrice"]), prices)
            price = next(
                item
                for item in json.loads((PREVIEW / "prices.json").read_text(encoding="utf-8"))
                if item["pricingId"] == row["selectedPriceRecordId"]
            )
            components = {charge["component"] for charge in price["charges"]}
            self.assertIn("cache_write", components)
            self.assertNotIn("cache_write_5m", components)

    def test_new_models_statuses_and_batch_prices_are_projected(self):
        expected = {
            "google-gemini/gemini-3.6-flash": (1.5, 0.15, 7.5, 0.75, 3.75),
            "google-gemini/gemini-3.5-flash-lite": (0.3, 0.03, 2.5, 0.15, 1.25),
            "xai/grok-4.5": (2, 0.3, 6, None, None),
        }
        for internal_id, prices in expected.items():
            row = self.by_internal[internal_id]
            self.assertEqual(row["status"], "latest")
            self.assertEqual(row["verificationStatus"], "verified")
            self.assertTrue(row["defaultSafe"])
            self.assertEqual(
                (
                    row["inputPrice"],
                    row["cachedInputPrice"],
                    row["outputPrice"],
                    row["batchInputPrice"],
                    row["batchOutputPrice"],
                ),
                prices,
            )
        for internal_id in (
            "google-gemini/gemini-3.5-flash",
            "google-gemini/gemini-3.1-flash-lite",
            "xai/grok-4.3",
        ):
            self.assertEqual(self.by_internal[internal_id]["status"], "active")

    def test_artifact_paths_and_no_runtime_network_dependency(self):
        self.assertEqual(
            ARTIFACT.relative_to(PREVIEW.parent.parent).as_posix(),
            "data/pricing-v2-preview/generated/model-pricing.v2.json",
        )
        self.assertEqual(
            REPORT.relative_to(PREVIEW.parent.parent).as_posix(),
            "data/pricing-v2-preview/phase4a-website-projection-report.json",
        )
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
        self.assertEqual(safe["stats"]["safePriceRecordsInput"], 35)
        self.assertEqual(safe["stats"]["mappedToProjection"], 35)
        self.assertEqual(safe["stats"]["unexplained"], 0)
        self.assertEqual(rows["counts"]["canonical_model"], 42)
        self.assertEqual(rows["counts"]["alias"], 2)
        self.assertEqual(rows["counts"]["redirecting_identity"], 1)
        self.assertEqual(unsafe["beforePhase4A5UnsafeDifferenceCount"], 11)
        self.assertEqual(unsafe["currentUnsafeDifferenceCount"], 4)
        self.assertEqual(len(unsafe["blockerUnsafeDifferences"]), 0)
        self.assertEqual(context["contextWindowRows"], 45)
        self.assertEqual(context["verifiedCanonicalContextWindowCount"], 0)


if __name__ == "__main__":
    unittest.main()
