import copy
import json
import unittest
from datetime import datetime, time, timedelta
from unittest.mock import patch

from scripts.lib import CANONICAL
from scripts import validate_pricing_v2_preview as pricing_validator
from scripts.validate_pricing_v2_preview import PREVIEW, validate_preview


class PricingV2PreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.counts = validate_preview()
        cls.identities = json.loads((PREVIEW / "model-identity-registry.json").read_text(encoding="utf-8"))
        cls.dispositions = json.loads((PREVIEW / "candidate-disposition-map.json").read_text(encoding="utf-8"))
        cls.models = json.loads((PREVIEW / "models.json").read_text(encoding="utf-8"))
        cls.prices = json.loads((PREVIEW / "prices.json").read_text(encoding="utf-8"))
        cls.sources = json.loads((PREVIEW / "sources.json").read_text(encoding="utf-8"))
        cls.canonical_models = json.loads((CANONICAL / "models.json").read_text(encoding="utf-8"))
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
        cls.phase3_consumer_map = json.loads((PREVIEW / "phase3-website-consumer-map.json").read_text(encoding="utf-8"))
        cls.phase3_projection_contract = json.loads((PREVIEW / "phase3-website-projection-contract.json").read_text(encoding="utf-8"))
        cls.phase3_mapping = json.loads((PREVIEW / "phase3-integration-mapping.json").read_text(encoding="utf-8"))
        cls.phase3_readiness = json.loads((PREVIEW / "phase3-readiness.json").read_text(encoding="utf-8"))
        cls.phase35_approval = json.loads((PREVIEW / "phase3-5-approval-report.json").read_text(encoding="utf-8"))
        cls.phase35_scope = json.loads((PREVIEW / "phase3-5-implementation-scope.json").read_text(encoding="utf-8"))
        cls.phase35_readiness = json.loads((PREVIEW / "phase3-5-readiness.json").read_text(encoding="utf-8"))
        cls.projection = json.loads((PREVIEW / "generated" / "model-pricing.website-preview.json").read_text(encoding="utf-8"))

    def identity(self, internal_id):
        return next(item for item in self.identities if item["internalId"] == internal_id)

    def disposition(self, candidate_id):
        return next(item for item in self.dispositions if item["candidateId"] == candidate_id)

    def model(self, internal_id):
        return next(item for item in self.models if item["internalId"] == internal_id)

    def projection_row(self, model_id):
        return next(item for item in self.projection if item["id"] == model_id)

    def price(self, pricing_id):
        return next(item for item in self.prices if item["pricingId"] == pricing_id)

    def test_grok_4_3_canonical_short_and_long_tiers_are_complete(self):
        model = next(
            item
            for item in self.canonical_models
            if item["provider_id"] == "xai" and item["model_id"] == "grok-4.3"
        )
        tiers = {tier["id"]: tier for tier in model["pricing_tiers"]}
        self.assertEqual(set(tiers), {"short", "long"})
        self.assertEqual(
            {
                key: tiers["short"][key]
                for key in ("input", "cached_input", "output")
            },
            {"input": 1.25, "cached_input": 0.2, "output": 2.5},
        )
        self.assertEqual(
            {
                key: tiers["long"][key]
                for key in ("input", "cached_input", "output")
            },
            {"input": 2.5, "cached_input": 0.4, "output": 5.0},
        )
        self.assertEqual(tiers["short"]["prompt_token_threshold"], 200000)
        self.assertEqual(tiers["short"]["threshold_comparison"], "less_than")
        self.assertTrue(tiers["short"]["calculation_default"])
        self.assertEqual(tiers["long"]["prompt_token_threshold"], 200000)
        self.assertEqual(tiers["long"]["threshold_comparison"], "greater_than_or_equal")
        self.assertFalse(tiers["long"]["calculation_default"])
        for tier in tiers.values():
            self.assertEqual(tier["pricing_status"], "current")
            self.assertEqual(tier["processing_mode"], "standard")
            self.assertEqual(tier["threshold_token_basis"], "total_prompt_tokens")
            self.assertTrue(tier["cached_prompt_tokens_included"])
            self.assertTrue(tier["whole_request_pricing"])
            self.assertEqual(tier["currency"], "USD")
            self.assertEqual(tier["unit"], "1M tokens")
        self.assertEqual(model["accessed_at"], "2026-08-15T12:25:26Z")
        self.assertEqual(model["last_verified_at"], "2026-08-15T12:25:26Z")
        self.assertEqual(
            set(model["official_source_urls"]),
            {
                "https://docs.x.ai/developers/pricing",
                "https://docs.x.ai/developers/advanced-api-usage/prompt-caching/usage-and-pricing",
                "https://docs.x.ai/developers/rest-api-reference/inference/models",
                "https://docs.x.ai/developers/models/grok-4.3",
            },
        )

    def test_grok_4_3_generated_v2_tiers_and_boundaries(self):
        records = [
            price
            for price in self.prices
            if price["modelInternalId"] == "xai/grok-4.3"
            and price["processingMode"] == "standard"
            and price.get("pricingStatus") == "current"
        ]
        self.assertEqual(
            {record["pricingId"] for record in records},
            {
                "price:xai/grok-4.3:standard:short:current",
                "price:xai/grok-4.3:standard:long:current",
            },
        )
        by_context = {record["contextClass"]: record for record in records}
        source_by_id = {source["sourceId"]: source for source in self.sources}
        expected_source_urls = {
            "https://docs.x.ai/developers/pricing",
            "https://docs.x.ai/developers/advanced-api-usage/prompt-caching/usage-and-pricing",
            "https://docs.x.ai/developers/rest-api-reference/inference/models",
            "https://docs.x.ai/developers/models/grok-4.3",
        }
        self.assertEqual(by_context["short"]["promptTokenThreshold"], 200000)
        self.assertEqual(by_context["short"]["tierSelection"]["comparison"], "less_than")
        self.assertEqual(by_context["long"]["promptTokenThreshold"], 200000)
        self.assertEqual(
            by_context["long"]["tierSelection"]["comparison"],
            "greater_than_or_equal",
        )
        for record in by_context.values():
            self.assertEqual(record["tierSelection"]["tokenBasis"], "total_prompt_tokens")
            self.assertTrue(record["tierSelection"]["cachedPromptTokensIncluded"])
            self.assertTrue(record["tierSelection"]["wholeRequestPricing"])
            self.assertEqual(
                {charge["component"] for charge in record["charges"]},
                {"input", "cached_input", "output"},
            )
            self.assertEqual(
                {source_by_id[ref]["url"] for ref in record["sourceRefs"]},
                expected_source_urls,
            )
            self.assertEqual(
                record["sourceDatasetIds"],
                {"publicDatasetIds": ["grok-4.3"], "websiteIds": []},
            )
            for ref in record["sourceRefs"]:
                self.assertEqual(source_by_id[ref]["checkedAt"], "2026-08-15T12:25:26Z")
                self.assertEqual(source_by_id[ref]["verifiedAt"], "2026-08-15T12:25:26Z")

        def selected(prompt_tokens):
            return sorted(
                context
                for context, record in by_context.items()
                if (
                    record["tierSelection"]["comparison"] == "less_than"
                    and prompt_tokens < record["promptTokenThreshold"]
                )
                or (
                    record["tierSelection"]["comparison"] == "greater_than_or_equal"
                    and prompt_tokens >= record["promptTokenThreshold"]
                )
            )

        self.assertEqual(selected(199999), ["short"])
        self.assertEqual(selected(200000), ["long"])
        self.assertEqual(selected(200001), ["long"])
        self.assertEqual(
            self.model("xai/grok-4.3")["defaultPriceRecordId"],
            "price:xai/grok-4.3:standard:short:current",
        )

    def test_grok_4_6_canonical_and_v2_tiers_are_complete(self):
        canonical = [
            item for item in self.canonical_models
            if item["provider_id"] == "xai" and item["model_id"] == "grok-4.6"
        ]
        self.assertEqual(len(canonical), 1)
        model = canonical[0]
        self.assertEqual(model["context_window_tokens"], 500000)
        self.assertEqual(
            {key: model["pricing"][key] for key in ("input", "cached_input", "output")},
            {"input": 2.0, "cached_input": 0.5, "output": 6.0},
        )
        self.assertIsNone(model["pricing"]["batch_input"])
        self.assertIsNone(model["pricing"]["batch_output"])
        tiers = {tier["id"]: tier for tier in model["pricing_tiers"]}
        self.assertEqual(
            {key: tiers["long"][key] for key in ("input", "cached_input", "output")},
            {"input": 4.0, "cached_input": 1.0, "output": 12.0},
        )
        self.assertEqual(tiers["short"]["threshold_comparison"], "less_than")
        self.assertEqual(tiers["long"]["threshold_comparison"], "greater_than_or_equal")
        for tier in tiers.values():
            self.assertEqual(tier["prompt_token_threshold"], 200000)
            self.assertEqual(tier["threshold_token_basis"], "total_prompt_tokens")
            self.assertTrue(tier["cached_prompt_tokens_included"])
            self.assertTrue(tier["whole_request_pricing"])

        records = [
            price for price in self.prices
            if price["modelInternalId"] == "xai/grok-4.6"
        ]
        self.assertEqual(len(records), 2)
        self.assertFalse(any(record["processingMode"] == "batch" for record in records))
        by_context = {record["contextClass"]: record for record in records}
        self.assertEqual(
            {charge["component"]: charge["amount"] for charge in by_context["short"]["charges"]},
            {"input": "2", "cached_input": "0.5", "output": "6"},
        )
        self.assertEqual(
            {charge["component"]: charge["amount"] for charge in by_context["long"]["charges"]},
            {"input": "4", "cached_input": "1", "output": "12"},
        )
        projected_model = self.model("xai/grok-4.6")
        self.assertEqual(projected_model["lifecycleStatus"], "active")

    def test_openai_gpt56_terra_and_luna_tiers_and_boundaries(self):
        source_by_id = {source["sourceId"]: source for source in self.sources}
        expected_base = {
            "openai/gpt-5.6-terra": {"input": 2, "cached_input": 0.2, "cache_write": 2.5, "output": 12},
            "openai/gpt-5.6-luna": {"input": 0.2, "cached_input": 0.02, "cache_write": 0.25, "output": 1.2},
        }
        expected_model_sources = {
            "openai/gpt-5.6-terra": "https://developers.openai.com/api/docs/models/gpt-5.6-terra",
            "openai/gpt-5.6-luna": "https://developers.openai.com/api/docs/models/gpt-5.6-luna",
        }

        for model_internal_id, base_prices in expected_base.items():
            records = [price for price in self.prices if price["modelInternalId"] == model_internal_id]
            self.assertEqual(len(records), 8)
            self.assertEqual(
                {(record["processingMode"], record["contextClass"]) for record in records},
                {(mode, context) for mode in ("standard", "batch", "flex", "fast") for context in ("short", "long")},
            )

            for record in records:
                context_class = record["contextClass"]
                self.assertEqual(record["pricingStatus"], "current")
                self.assertEqual(record["promptTokenThreshold"], 272000)
                self.assertEqual(
                    record["tierSelection"]["comparison"],
                    "less_than_or_equal" if context_class == "short" else "greater_than",
                )
                self.assertEqual(record["tierSelection"]["tokenBasis"], "total_prompt_tokens")
                self.assertTrue(record["tierSelection"]["cachedPromptTokensIncluded"])
                self.assertTrue(record["tierSelection"]["wholeRequestPricing"])
                source_urls = {source_by_id[ref]["url"] for ref in record["sourceRefs"]}
                self.assertIn("https://developers.openai.com/api/docs/pricing", source_urls)
                self.assertIn(expected_model_sources[model_internal_id], source_urls)
                for ref in record["sourceRefs"]:
                    if source_by_id[ref]["url"] == expected_model_sources[model_internal_id]:
                        self.assertEqual(source_by_id[ref]["checkedAt"], "2026-08-25T15:02:22Z")
                        self.assertEqual(source_by_id[ref]["verifiedAt"], "2026-08-25T15:02:22Z")

            def selected(prompt_tokens):
                return sorted(
                    record["contextClass"]
                    for record in records
                    if record["processingMode"] == "standard"
                    and (
                        record["tierSelection"]["comparison"] == "less_than_or_equal"
                        and prompt_tokens <= record["promptTokenThreshold"]
                        or record["tierSelection"]["comparison"] == "greater_than"
                        and prompt_tokens > record["promptTokenThreshold"]
                    )
                )

            self.assertEqual(selected(271999), ["short"])
            self.assertEqual(selected(272000), ["short"])
            self.assertEqual(selected(272001), ["long"])

            standard_short = next(
                record for record in records
                if record["processingMode"] == "standard" and record["contextClass"] == "short"
            )
            self.assertEqual(
                {charge["component"]: float(charge["amount"]) for charge in standard_short["charges"]},
                base_prices,
            )

    def test_grok_4_3_validator_rejects_invalid_tier_mutations(self):
        original_read_json = pricing_validator.read_json

        def long_record(prices):
            return next(
                price
                for price in prices
                if price["pricingId"] == "price:xai/grok-4.3:standard:long:current"
            )

        def missing_threshold(prices):
            long_record(prices)["promptTokenThreshold"] = None

        def exclusive_long_boundary(prices):
            long_record(prices)["tierSelection"]["comparison"] = "greater_than"

        def missing_output(prices):
            record = long_record(prices)
            record["charges"] = [
                charge for charge in record["charges"] if charge["component"] != "output"
            ]

        def duplicate_current_tier(prices):
            duplicate = copy.deepcopy(long_record(prices))
            duplicate["pricingId"] = "price:xai/grok-4.3:standard:long:duplicate"
            prices.append(duplicate)

        def missing_source(prices):
            long_record(prices)["sourceRefs"] = []

        cases = [
            (missing_threshold, "long-context price missing promptTokenThreshold"),
            (exclusive_long_boundary, "threshold inclusivity mismatch"),
            (missing_output, "charges mismatch"),
            (duplicate_current_tier, "duplicate current pricing tier"),
            (missing_source, "missing sourceRefs"),
        ]

        for mutate, message in cases:
            with self.subTest(message=message):
                def fake_read_json(path):
                    value = original_read_json(path)
                    if path.name == "prices.json":
                        value = copy.deepcopy(value)
                        mutate(value)
                    return value

                with patch.object(pricing_validator, "read_json", side_effect=fake_read_json):
                    with self.assertRaisesRegex(SystemExit, message):
                        pricing_validator.validate_preview()

        def fake_early_generated_at(path):
            value = original_read_json(path)
            if path.name == "convergence-report.json":
                value = copy.deepcopy(value)
                value["generatedAt"] = "2026-08-15T00:00:00Z"
            return value

        with patch.object(pricing_validator, "read_json", side_effect=fake_early_generated_at):
            with self.assertRaisesRegex(SystemExit, "generatedAt precedes"):
                pricing_validator.validate_preview()

    def test_claude_opus_5_v2_identity_model_and_prices_are_present(self):
        identity = self.identity("anthropic/claude-opus-5")
        model = self.model("anthropic/claude-opus-5")
        self.assertEqual(identity["displayName"], "Claude Opus 5")
        self.assertEqual(identity["lifecycleStatus"], "active")
        self.assertEqual(identity["releaseStage"], "stable")
        self.assertEqual(identity["availability"], "Standard")
        self.assertIn("claude-opus-5", identity["publicDatasetIds"])
        self.assertEqual(model["defaultPriceRecordId"], "price:anthropic/claude-opus-5:standard:short:current")

        standard = self.price("price:anthropic/claude-opus-5:standard:short:current")
        batch = self.price("price:anthropic/claude-opus-5:batch:short:current")
        charges = {charge["component"]: charge["amount"] for charge in standard["charges"]}
        self.assertEqual(standard["effectiveFrom"], "2026-07-24")
        self.assertEqual(charges["input"], "5")
        self.assertEqual(charges["cached_input"], "0.5")
        self.assertEqual(charges["cache_write_5m"], "6.25")
        self.assertEqual(charges["cache_write_1h"], "10")
        self.assertEqual(charges["output"], "25")
        batch_charges = {charge["component"]: charge["amount"] for charge in batch["charges"]}
        self.assertEqual(batch["processingMode"], "batch")
        self.assertEqual(batch_charges, {"input": "2.5", "output": "12.5"})

    def test_claude_opus_4_8_is_retained_after_opus_5(self):
        identity = self.identity("anthropic/claude-opus-4.8")
        model = self.model("anthropic/claude-opus-4.8")
        self.assertEqual(identity["displayName"], "Claude Opus 4.8")
        self.assertEqual(identity["lifecycleStatus"], "active")
        self.assertEqual(identity["releaseStage"], "stable")
        self.assertEqual(model["defaultPriceRecordId"], "price:anthropic/claude-opus-4.8:standard:short:current")

    def test_report_counts_match_phase_1_baseline(self):
        self.assertEqual(self.report["candidateUnionCount"], len(self.dispositions))
        self.assertEqual(self.report["websiteOnlyCount"], 13)
        self.assertEqual(self.report["publicOnlyCount"], 10)
        self.assertEqual(self.report["commonCount"], 27)
        self.assertEqual(self.report["aliasCount"], 2)
        self.assertEqual(self.report["normalizedCanonicalIdentityCount"], len(self.models))
        self.assertEqual(self.report["candidateDispositionCounts"]["unresolved"], 3)
        candidate_ids = {row["candidateId"] for row in self.dispositions}
        self.assertTrue(
            {
                "openai/gpt-5.6-sol",
                "openai/gpt-5.6-terra",
                "openai/gpt-5.6-luna",
            }
            <= candidate_ids
        )

    def test_2026_08_09_coverage_gap_models_are_verified(self):
        for internal_id in (
            "google-gemini/gemini-3.6-flash",
            "google-gemini/gemini-3.5-flash-lite",
            "xai/grok-4.5",
        ):
            identity = self.identity(internal_id)
            self.assertEqual(identity["verificationStatus"], "verified")
            self.assertEqual(identity["lifecycleStatus"], "active")
            self.assertIsNotNone(self.model(internal_id)["defaultPriceRecordId"])

    def test_claude_sonnet_5_is_permanent_standard_canonical_model(self):
        disposition = self.disposition("anthropic/claude-sonnet-5")
        self.assertNotEqual(disposition["disposition"], "merged_duplicate")
        sonnet = self.model("anthropic/claude-sonnet-5")
        self.assertEqual(sonnet["defaultPriceRecordId"], "price:anthropic/claude-sonnet-5:standard:short:current")
        default_price = next(item for item in self.prices if item["pricingId"] == sonnet["defaultPriceRecordId"])
        self.assertIsNone(default_price["effectiveUntil"])
        charges = {charge["component"]: charge["amount"] for charge in default_price["charges"]}
        self.assertEqual(charges["input"], "2")
        self.assertEqual(charges["output"], "10")
        self.assertNotIn("2026-08-31", default_price["billingNote"])
        self.assertFalse(any("2026-09-01" in item["pricingId"] for item in self.prices))

    def test_deepseek_aliases_target_v4_flash(self):
        for internal_id in ("deepseek/deepseek-chat", "deepseek/deepseek-reasoner"):
            alias = self.identity(internal_id)
            self.assertEqual(alias["identityType"], "alias")
            self.assertEqual(alias["aliasTargetInternalId"], "deepseek/deepseek-v4-flash")
            row = self.projection_row(internal_id.split("/", 1)[1])
            self.assertEqual(row["inputPrice"], 0.44)
            self.assertEqual(row["cachedInputPrice"], 0.014)
            self.assertEqual(row["outputPrice"], 1.32)

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
        self.assertEqual(len(self.phase25_evidence), self.phase25_default_safe["totalPriceRecords"])
        self.assertEqual(self.phase25_default_safe["productionDefaultCandidateCount"], 39)
        self.assertEqual(self.phase25_default_safe["defaultSafeCount"], 39)
        self.assertEqual(self.phase25_default_safe["defaultUnsafeCount"], 63)
        self.assertEqual(self.phase25_default_safe["P0PartialBefore"], 4)
        self.assertEqual(self.phase25_default_safe["P0PartialAfter"], 0)
        self.assertEqual(self.phase25_default_safe["P1PartialCount"], 7)
        self.assertEqual(self.phase25_default_safe["P2PartialCount"], 0)
        self.assertEqual(self.phase25_default_safe["P3PartialCount"], 5)

    def test_phase2_5_gpt_and_grok_policies(self):
        evidence_by_model = {row["modelInternalId"]: row for row in self.phase25_evidence}
        for internal_id in ("openai/gpt-4.1", "openai/gpt-4.1-mini", "openai/gpt-4.1-nano"):
            matching_rows = [row for row in self.phase25_evidence if row["modelInternalId"] == internal_id]
            self.assertTrue(matching_rows)
            self.assertTrue(all(not row["defaultSafe"] for row in matching_rows))
            self.assertTrue(all(row["priorityClass"] == "P3" for row in matching_rows))
        self.assertTrue(next(row for row in self.phase25_evidence if row["pricingId"] == "price:xai/grok-4.3:standard:short:current")["defaultSafe"])
        grok_3_rows = [row for row in self.phase25_blockers if row["websiteModelId"] == "grok-3"]
        self.assertTrue(grok_3_rows)
        self.assertTrue(all(row["recommendedIntegrationAction"] == "integrate_with_warning" for row in grok_3_rows))

    def test_phase2_6_closes_p0_default_safe_gate(self):
        self.assertTrue(self.phase26_closure["closureGatePassed"])
        self.assertEqual(self.phase26_closure["defaultCandidatesBefore"], 39)
        self.assertEqual(self.phase26_closure["defaultCandidatesAfter"], 39)
        self.assertEqual(self.phase26_closure["safeBefore"], 34)
        self.assertEqual(self.phase26_closure["safeAfter"], 39)
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
        self.assertEqual(self.phase26_readiness["integrationMappingCount"], len(self.phase25_blockers))

    def test_phase2_6_website_usage_counts_are_mapping_entries(self):
        self.assertTrue(self.phase25_readiness["safeToEnterWebsiteIntegrationPlanning"])
        self.assertEqual(self.phase25_readiness["defaultPricingReadiness"], "ready")
        counts = self.phase25_readiness["websiteIntegrationActionCounts"]
        self.assertEqual(sum(counts.values()), len(self.phase25_blockers))
        self.assertEqual(counts["safe_to_integrate"], 173)
        self.assertEqual(counts["integrate_with_warning"], 8)
        self.assertEqual(counts.get("exclude_from_default", 0), 0)
        self.assertEqual(counts["keep_existing_temporarily"], 13)
        self.assertEqual(counts.get("blocked", 0), 0)

    def test_phase3_planning_artifacts_cover_website_consumers(self):
        self.assertEqual(self.phase3_consumer_map["consumerCount"], 13)
        consumer_ids = {row["consumerId"] for row in self.phase3_consumer_map["consumers"]}
        self.assertIn("api_cost_calculator", consumer_ids)
        self.assertIn("budget_planner_core", consumer_ids)
        self.assertIn("supabase_model_prices_seed", consumer_ids)
        self.assertEqual(self.phase3_projection_contract["recommendedMode"], "repo_local_generated_projection")
        self.assertIn("defaultSafe", self.phase3_projection_contract["requiredFields"])
        self.assertIn("verifiedAt", self.phase3_projection_contract["requiredFields"])
        self.assertIn("contextWindow", self.phase3_projection_contract["requiredFields"])

    def test_phase3_mapping_and_readiness(self):
        self.assertEqual(len(self.phase3_mapping), len(self.phase25_blockers))
        action_counts = {}
        for row in self.phase3_mapping:
            action_counts[row["action"]] = action_counts.get(row["action"], 0) + 1
        self.assertEqual(action_counts["safe_to_integrate"], 173)
        self.assertEqual(action_counts["integrate_with_warning"], 8)
        self.assertEqual(action_counts["keep_existing_temporarily"], 13)
        self.assertEqual(self.phase3_readiness["implementationReadiness"], "blocked")
        self.assertEqual(self.phase3_readiness["planningReadiness"], "complete")
        self.assertFalse(self.phase3_readiness["websiteRepoClean"])

    def test_phase35_approval_gate_is_ready(self):
        self.assertEqual(self.phase35_approval["implementationReadiness"], "ready")
        self.assertTrue(self.phase35_approval["safeToEnterPhase4Implementation"])
        self.assertTrue(self.phase35_readiness["safeToCommitPhase35"])
        self.assertTrue(self.phase35_readiness["safeToEnterPhase4Implementation"])
        self.assertTrue(all(self.phase35_readiness["conditionsSatisfied"].values()))
        approvals = {row["name"]: row["status"] for row in self.phase35_approval["approvals"]}
        self.assertEqual(approvals["Projection Contract Approval"], "approved")
        self.assertEqual(approvals["DefaultSafe Enforcement Approval"], "approved")
        self.assertEqual(approvals["Rollback Approval"], "approved")
        self.assertEqual(approvals["Testing Plan Approval"], "approved")

    def test_phase35_mapping_reviews_are_complete(self):
        temporary = self.phase35_approval["temporaryMappingReview"]
        warnings = self.phase35_approval["warningMappingReview"]
        action_counts = self.phase35_approval["phase3PlanningInputs"]["actionCounts"]
        self.assertEqual(len(temporary), action_counts["keep_existing_temporarily"])
        self.assertEqual(len(warnings), action_counts["integrate_with_warning"])
        for row in temporary:
            self.assertTrue(row["reason"])
            self.assertTrue(row["owner"])
            self.assertTrue(row["exitCondition"])
            self.assertTrue(row["migrationDestination"])
            self.assertTrue(row["risk"])
        self.assertEqual(self.phase35_scope["featureFlag"]["name"], "PRICING_V2_ENABLED")
        self.assertEqual(self.phase35_scope["featureFlag"]["default"], "off")
        self.assertIn("runtime GitHub Pages fetch", self.phase35_scope["outOfScope"])


if __name__ == "__main__":
    unittest.main()
