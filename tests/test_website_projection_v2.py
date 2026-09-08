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
    build_pricing_components,
    build_phase45_audits,
    build_projection,
    parse_effective_at,
    project_pricing_component,
    project_cache_eligibility,
    project_cache_lifetime_modes,
    validate_projection,
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

    def test_cache_eligibility_projects_verified_model_evidence_without_defaults(self):
        openai = self.by_internal["openai/gpt-5.6-sol"]["cacheEligibility"]
        anthropic = self.by_internal["anthropic/claude-sonnet-5"]["cacheEligibility"]
        self.assertEqual(openai["minimumCacheablePrefixTokens"], 1024)
        self.assertEqual(anthropic["minimumCacheablePrefixTokens"], 1024)
        self.assertEqual(openai["verificationStatus"], "verified")
        self.assertEqual(
            openai["sourceUrls"],
            ["https://developers.openai.com/api/docs/guides/prompt-caching"],
        )
        self.assertNotIn("cacheEligibility", self.by_internal["openai/gpt-5.4-mini"])

    def test_cache_eligibility_rejects_invalid_minimum(self):
        source_id = "source:openai:prompt-caching-test"
        sources = {
            source_id: {
                "providerId": "openai",
                "verificationStatus": "verified",
                "url": "https://developers.openai.com/api/docs/guides/prompt-caching",
            }
        }
        base = {
            "internalId": "openai/test",
            "providerId": "openai",
            "cacheEligibility": {
                "minimumCacheablePrefixTokens": -1,
                "verificationStatus": "verified",
                "checkedAt": "2026-09-06T16:10:43Z",
                "verifiedAt": "2026-09-06T16:10:43Z",
                "sourceRefs": [source_id],
            },
        }
        with self.assertRaisesRegex(ValueError, "non-negative integer"):
            project_cache_eligibility(base, sources)
        base["cacheEligibility"]["minimumCacheablePrefixTokens"] = True
        with self.assertRaisesRegex(ValueError, "non-negative integer"):
            project_cache_eligibility(base, sources)

    def test_cache_lifetime_modes_project_verified_duration_renewal_and_absence(self):
        openai = self.by_internal["openai/gpt-5.6-sol"]["cacheLifetimeModes"]
        fable = self.by_internal["anthropic/claude-fable-5"]["cacheLifetimeModes"]
        haiku = self.by_internal["anthropic/claude-haiku-4.5"]["cacheLifetimeModes"]
        self.assertEqual([(mode["cacheWriteComponent"], mode["minimumLifetimeSeconds"]) for mode in openai], [("cache_write", 1800)])
        self.assertEqual({(mode["cacheWriteComponent"], mode["minimumLifetimeSeconds"]) for mode in fable}, {("cache_write_5m", 300), ("cache_write_1h", 3600)})
        self.assertEqual([(mode["cacheWriteComponent"], mode["minimumLifetimeSeconds"]) for mode in haiku], [("cache_write_5m", 300)])
        self.assertEqual(
            [(mode["activationBehavior"], mode["userSelectable"], mode["isDefault"]) for mode in openai],
            [("provider_automatic", False, True)],
        )
        self.assertEqual(
            {
                (mode["cacheWriteComponent"], mode["activationBehavior"], mode["userSelectable"], mode["isDefault"])
                for mode in fable
            },
            {("cache_write_5m", "request_configured", True, True), ("cache_write_1h", "request_configured", True, False)},
        )
        self.assertTrue(all(mode["renewalBehavior"] == "refresh_on_reuse" for mode in openai + fable + haiku))
        self.assertTrue(all(mode["sourceUrls"] and mode["sourceUrls"][0].startswith("https://") for mode in openai + fable + haiku))
        self.assertNotIn("cacheLifetimeModes", self.by_internal["openai/gpt-5.4-mini"])

    def test_cache_lifetime_modes_reject_invalid_duration_and_duplicate_mode(self):
        source_id = "source:anthropic:prompt-caching-test"
        sources = {source_id: {"providerId": "anthropic", "verificationStatus": "verified", "url": "https://platform.claude.com/docs/en/build-with-claude/prompt-caching"}}
        mode = {
            "activationBehavior": "request_configured",
            "isDefault": True,
            "userSelectable": True,
            "cacheWriteComponent": "cache_write_5m",
            "minimumLifetimeSeconds": 0,
            "renewalBehavior": "refresh_on_reuse",
            "verificationStatus": "verified",
            "checkedAt": "2026-09-06T16:57:50Z",
            "verifiedAt": "2026-09-06T16:57:50Z",
            "sourceRefs": [source_id],
        }
        model = {"internalId": "anthropic/test", "providerId": "anthropic", "cacheLifetimeModes": [mode]}
        with self.assertRaisesRegex(ValueError, "positive integer"):
            project_cache_lifetime_modes(model, sources)
        mode["minimumLifetimeSeconds"] = True
        with self.assertRaisesRegex(ValueError, "positive integer"):
            project_cache_lifetime_modes(model, sources)
        mode["minimumLifetimeSeconds"] = 300
        mode["activationBehavior"] = "unknown"
        with self.assertRaisesRegex(ValueError, "activation behavior"):
            project_cache_lifetime_modes(model, sources)
        mode["activationBehavior"] = "provider_automatic"
        with self.assertRaisesRegex(ValueError, "cannot be user-selectable"):
            project_cache_lifetime_modes(model, sources)
        mode["activationBehavior"] = "request_configured"
        mode["minimumLifetimeSeconds"] = 3600
        with self.assertRaisesRegex(ValueError, "does not match write component"):
            project_cache_lifetime_modes(model, sources)
        mode["minimumLifetimeSeconds"] = 300
        mode["isDefault"] = False
        with self.assertRaisesRegex(ValueError, "exactly one default"):
            project_cache_lifetime_modes(model, sources)
        mode["isDefault"] = True
        model["cacheLifetimeModes"] = [mode, dict(mode)]
        with self.assertRaisesRegex(ValueError, "invalid or duplicated"):
            project_cache_lifetime_modes(model, sources)
        model["cacheLifetimeModes"] = [dict(mode, sourceRefs=["source:missing"])]
        with self.assertRaisesRegex(ValueError, "known unique source refs"):
            project_cache_lifetime_modes(model, sources)
        model["cacheLifetimeModes"] = [mode]
        sources[source_id]["providerId"] = "openai"
        with self.assertRaisesRegex(ValueError, "source provider mismatch"):
            project_cache_lifetime_modes(model, sources)
    def test_projection_default_times_are_ordered_utc_instants(self):
        self.assertNotEqual(
            self.artifact["generatedAt"],
            self.artifact["effectiveAt"],
            "artifact generation time and pricing effective selection time are distinct semantics",
        )
        generated_at = datetime.fromisoformat(self.artifact["generatedAt"].replace("Z", "+00:00"))
        verified_at = datetime.fromisoformat("2026-08-08T18:00:00+00:00")
        self.assertGreaterEqual(generated_at, verified_at)
        self.assertGreaterEqual(self.artifact["effectiveAt"], "2026-07-24T00:00:00Z")

    def test_projection_generated_at_covers_every_checked_and_verified_timestamp(self):
        generated_at = datetime.fromisoformat(self.artifact["generatedAt"].replace("Z", "+00:00"))
        for row in self.rows:
            for field in ("checkedAt", "verifiedAt"):
                if row[field] is not None:
                    timestamp = parse_effective_at(row[field])
                    self.assertGreaterEqual(generated_at, timestamp, f"{row['id']} {field}")

    def test_projection_rejects_generated_at_before_checked_or_verified(self):
        for field in ("checkedAt", "verifiedAt"):
            artifact = json.loads(json.dumps(self.artifact))
            for item in artifact["models"]:
                item.pop("cacheEligibility", None)
                item.pop("cacheLifetimeModes", None)
            row = next(item for item in artifact["models"] if item[field] is not None)
            other_field = "verifiedAt" if field == "checkedAt" else "checkedAt"
            other_refs_field = "verifiedSourceRefs" if field == "checkedAt" else "checkedSourceRefs"
            for item in artifact["models"]:
                if item is not row:
                    item[field] = None
                    item["verifiedSourceRefs" if field == "verifiedAt" else "checkedSourceRefs"] = []
                item[other_field] = None
                item[other_refs_field] = []
            artifact["generatedAt"] = "2000-01-01T00:00:00Z"
            with self.assertRaisesRegex(ValueError, f"generatedAt precedes {field}"):
                validate_projection(artifact, self.report)

    def test_checked_and_verified_keep_distinct_source_associations(self):
        sources = {
            source["sourceId"]: source
            for source in json.loads((PREVIEW / "sources.json").read_text(encoding="utf-8"))
        }
        for row in self.rows:
            self.assertTrue(set(row["checkedSourceRefs"]) <= set(row["sourceRefs"]))
            self.assertTrue(set(row["verifiedSourceRefs"]) <= set(row["sourceRefs"]))
            for ref in row["checkedSourceRefs"]:
                self.assertIn(ref, sources)
            if row["verifiedAt"] is None:
                self.assertEqual(row["verifiedSourceRefs"], [])

        checked_after_verified = next(
            row for row in self.rows
            if row["checkedAt"] and row["verifiedAt"] and row["checkedAt"] > row["verifiedAt"]
        )
        self.assertNotEqual(checked_after_verified["checkedAt"], checked_after_verified["verifiedAt"])
        validate_projection(self.artifact, self.report)

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
        projected = {row["id"]: row for row in self.rows if row["contextWindow"] is not None}
        for model_id in ("grok-4.20-0309-reasoning", "grok-4.20-0309-non-reasoning", "grok-4.20-multi-agent-0309"):
            self.assertEqual(projected[model_id]["contextWindowTokens"], 1_000_000)
        self.assertEqual(projected["kimi-k3"]["contextWindowTokens"], 1_048_576)
        self.assertEqual(projected["kimi-k2.7-code"]["contextWindowTokens"], 262_144)
        self.assertEqual(projected["kimi-k2.6"]["contextWindowTokens"], 262_144)
        self.assertTrue(all(row["contextWindowStatus"] == "canonical_verified" for row in projected.values()))
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

    def test_grok_4_6_projection_and_lifecycle_are_exact(self):
        grok46 = self.by_internal["xai/grok-4.6"]
        self.assertEqual(grok46["status"], "latest")
        self.assertEqual(grok46["lifecycleStatus"], "active")
        self.assertIsNone(grok46["contextWindow"])
        self.assertEqual(grok46["contextWindowStatus"], "unknown_not_guessed")
        self.assertEqual(
            (grok46["inputPrice"], grok46["cachedInputPrice"], grok46["outputPrice"]),
            (2, 0.5, 6),
        )
        self.assertIsNone(grok46["batchInputPrice"])
        self.assertIsNone(grok46["batchOutputPrice"])
        self.assertIsNone(grok46["selectedBatchPriceRecordId"])
        self.assertEqual(len(grok46["pricingTiers"]), 2)
        self.assertNotIn("redirectedBilling", grok46)
        self.assertEqual(self.by_internal["xai/grok-4.5"]["lifecycleStatus"], "active")
        self.assertEqual(self.by_internal["xai/grok-build-0.1"]["status"], "active")

    def test_redirected_billing_is_owned_only_by_grok_3(self):
        owners = [
            row["canonicalInternalId"]
            for row in self.rows
            if "redirectedBilling" in row
        ]
        self.assertEqual(owners, ["xai/grok-3"])
        self.assertNotIn("redirectedBilling", self.by_internal["cohere/parse-v5.0"])

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
        self.assertEqual(
            self.report["defaultSafeModelCount"] + self.report["unsafeIdentityCount"],
            self.report["projectionModelCount"],
        )
        self.assertEqual(self.report["nullPriceCount"], self.report["unsafeIdentityCount"])
        self.assertEqual(self.report["parity"]["websiteModelCount"], 36)
        self.assertEqual(sum(self.report["parity"]["counts"].values()), 36)
        self.assertEqual(self.report["parity"]["counts"]["unsafe_difference"], 4)

    def test_gpt_5_6_rows_use_standard_short_defaults(self):
        expected = {
            "openai/gpt-5.6-sol": (4, 0.4, 20),
            "openai/gpt-5.6-terra": (2, 0.2, 12),
            "openai/gpt-5.6-luna": (0.2, 0.02, 1.2),
        }
        public_by_internal_id = {
            f"{row['provider_id']}/{row['model_id']}": row
            for row in json.loads((PREVIEW.parent / "prices.json").read_text(encoding="utf-8"))["models"]
        }
        for internal_id, prices in expected.items():
            row = self.by_internal[internal_id]
            self.assertTrue(row["defaultSafe"])
            self.assertEqual(row["selectedPriceRecordId"], f"price:{internal_id}:standard:short:current")
            self.assertEqual((row["inputPrice"], row["cachedInputPrice"], row["outputPrice"]), prices)
            self.assertEqual(
                row["verifiedAt"],
                public_by_internal_id[internal_id]["last_verified_at"],
                "website projection freshness must follow the current canonical model verification",
            )
            price = next(
                item
                for item in json.loads((PREVIEW / "prices.json").read_text(encoding="utf-8"))
                if item["pricingId"] == row["selectedPriceRecordId"]
            )
            components = {charge["component"] for charge in price["charges"]}
            self.assertIn("cache_write", components)
            self.assertNotIn("cache_write_5m", components)

    def test_pricing_component_projection_preserves_supported_cache_variants(self):
        record = {
            "pricingId": "price:test/model:standard:short:current",
            "processingMode": "standard",
            "contextClass": "short",
            "promptTokenThreshold": None,
            "tierSelection": None,
            "regionPolicy": "global",
            "currency": "USD",
            "effectiveFrom": None,
            "effectiveUntil": None,
            "calculationDefault": True,
            "sourceRefs": ["source:z", "source:a"],
            "verificationStatus": "verified",
        }
        for component in (
            "cached_input",
            "cache_read",
            "cache_write",
            "cache_write_5m",
            "cache_write_1h",
        ):
            charge = {
                "chargeId": f"{record['pricingId']}:{component}:text:per_1m_tokens",
                "component": component,
                "amount": "1.25",
                "unit": "per_1m_tokens",
                "modality": "text",
            }
            projected = project_pricing_component(record, charge)
            self.assertEqual(projected["component"], component)
            self.assertEqual(projected["amount"], "1.25")
            self.assertEqual(projected["condition"]["processingMode"], "standard")
            self.assertEqual(projected["sourceRefs"], ["source:a", "source:z"])

    def test_nine_verified_models_keep_every_structured_cache_write_condition(self):
        canonical_prices = json.loads((PREVIEW / "prices.json").read_text(encoding="utf-8"))
        canonical_by_charge_id = {
            charge["chargeId"]: (record, charge)
            for record in canonical_prices
            for charge in record["charges"]
        }
        expected_write_counts = {
            "openai/gpt-5.6-sol": 8,
            "openai/gpt-5.6-terra": 8,
            "openai/gpt-5.6-luna": 8,
            "anthropic/claude-fable-5": 2,
            "anthropic/claude-haiku-4.5": 1,
            "anthropic/claude-opus-4.8": 1,
            "anthropic/claude-opus-5": 2,
            "anthropic/claude-sonnet-4.6": 1,
            "anthropic/claude-sonnet-5": 2,
        }
        for internal_id, expected_count in expected_write_counts.items():
            components = self.by_internal[internal_id]["pricingComponents"]
            writes = [item for item in components if item["component"].startswith("cache_write")]
            self.assertEqual(len(writes), expected_count, internal_id)
            self.assertEqual(len({item["chargeId"] for item in writes}), expected_count, internal_id)
            self.assertTrue(all(item["verificationStatus"] == "verified" for item in writes))
            self.assertTrue(all(item["sourceRefs"] for item in writes))
            for item in writes:
                record, charge = canonical_by_charge_id[item["chargeId"]]
                self.assertEqual(item["amount"], charge["amount"])
                self.assertEqual(item["component"], charge["component"])
                self.assertEqual(item["unit"], charge["unit"])
                self.assertEqual(item["condition"]["processingMode"], record["processingMode"])
                self.assertEqual(item["condition"]["contextClass"], record["contextClass"])
                self.assertEqual(item["condition"]["promptTokenThreshold"], record["promptTokenThreshold"])
                self.assertEqual(item["condition"]["effectiveFrom"], record["effectiveFrom"])
                self.assertEqual(item["condition"]["effectiveUntil"], record["effectiveUntil"])
                self.assertEqual(item["sourceRefs"], sorted(record["sourceRefs"]))

        for internal_id in (
            "openai/gpt-5.6-sol",
            "openai/gpt-5.6-terra",
            "openai/gpt-5.6-luna",
        ):
            writes = [
                item for item in self.by_internal[internal_id]["pricingComponents"]
                if item["component"] == "cache_write"
            ]
            self.assertEqual(
                {(item["condition"]["processingMode"], item["condition"]["contextClass"]) for item in writes},
                {(mode, context) for mode in ("standard", "batch", "flex", "fast") for context in ("short", "long")},
            )

        for internal_id in (
            "anthropic/claude-fable-5",
            "anthropic/claude-opus-5",
            "anthropic/claude-sonnet-5",
        ):
            variants = {
                item["component"]
                for item in self.by_internal[internal_id]["pricingComponents"]
                if item["component"].startswith("cache_write")
            }
            self.assertEqual(variants, {"cache_write_5m", "cache_write_1h"})

    def test_pricing_components_do_not_parse_notes_or_invent_write_prices(self):
        record = {
            "billingNote": "Cache write is $99 per 1M tokens.",
            "pricingId": "price:test/notes-only:standard:short:current",
            "pricingStatus": "current",
            "processingMode": "standard",
            "contextClass": "short",
            "promptTokenThreshold": None,
            "regionPolicy": "global",
            "currency": "USD",
            "effectiveFrom": None,
            "effectiveUntil": None,
            "calculationDefault": True,
            "sourceRefs": ["source:test"],
            "verificationStatus": "verified",
            "charges": [{
                "chargeId": "price:test/notes-only:standard:short:current:input:text:per_1m_tokens",
                "component": "input",
                "amount": "1",
                "unit": "per_1m_tokens",
                "modality": "text",
            }],
        }
        components = build_pricing_components(
            [record], parse_effective_at("2026-08-22T14:45:21Z"), {}
        )
        self.assertEqual([item["component"] for item in components], ["input"])
        self.assertFalse(any(item["component"].startswith("cache_write") for item in components))

    def test_duplicate_component_in_one_condition_fails_instead_of_flattening(self):
        record = {
            "pricingId": "price:test/duplicate:standard:short:current",
            "pricingStatus": "current",
            "processingMode": "standard",
            "contextClass": "short",
            "promptTokenThreshold": None,
            "regionPolicy": "global",
            "currency": "USD",
            "effectiveFrom": None,
            "effectiveUntil": None,
            "calculationDefault": True,
            "sourceRefs": ["source:test"],
            "verificationStatus": "verified",
            "charges": [
                {
                    "chargeId": f"charge:{index}",
                    "component": "cache_write",
                    "amount": str(index),
                    "unit": "per_1m_tokens",
                    "modality": "text",
                }
                for index in (1, 2)
            ],
        }
        with self.assertRaisesRegex(ValueError, "duplicate component cache_write"):
            build_pricing_components([record], parse_effective_at("2026-08-22T14:45:21Z"), {})

    def test_optional_component_absence_and_generator_determinism(self):
        self.assertNotIn("pricingComponents", self.by_internal["openai/gpt-4.1"])
        second_artifact, _ = build_projection(website_dataset=WEBSITE_FIXTURE)
        self.assertEqual(self.artifact, second_artifact)

    def test_new_models_statuses_and_batch_prices_are_projected(self):
        expected = {
            "google-gemini/gemini-3.6-flash": (0.75, 0.075, 3.75, 0.375, 1.875),
            "google-gemini/gemini-3.7-flash": (0.75, 0.075, 3.75, 0.375, 1.875),
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
        self.assertEqual(
            safe["stats"]["mappedToProjection"] + safe["stats"]["mergedIntoSameIdentity"] + safe["stats"]["omitted"],
            safe["stats"]["safePriceRecordsInput"],
        )
        self.assertEqual(safe["stats"]["unexplained"], 0)
        self.assertEqual(sum(rows["counts"].values()), len(self.rows))
        self.assertEqual(rows["counts"]["alias"], 2)
        self.assertEqual(rows["counts"]["redirecting_identity"], 1)
        self.assertEqual(unsafe["beforePhase4A5UnsafeDifferenceCount"], 5)
        self.assertEqual(unsafe["currentUnsafeDifferenceCount"], 4)
        self.assertEqual(len(unsafe["blockerUnsafeDifferences"]), 0)
        self.assertEqual(context["contextWindowRows"], len(self.rows))
        self.assertEqual(
            context["verifiedCanonicalContextWindowCount"] + context["projectedNullCount"],
            context["contextWindowRows"],
        )
        self.assertEqual(context["projectedCanonicalMatchCount"], len(self.rows))


if __name__ == "__main__":
    unittest.main()
