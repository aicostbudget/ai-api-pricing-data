import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import access_metadata as access
from scripts import generate_pricing_v2_preview as generator
from scripts.lib import ROOT


class AccessMetadataTests(unittest.TestCase):
    def fact(self, status="public", binding="approved"):
        return {
            "access_status": status,
            "access_evidence": [] if status == "unknown" else [{"url": "https://developers.openai.com/api/docs/models/fixture", "title": "Official fixture access", "claim_type": "official_access_" + status, "official_model_id": "fixture", "scope": "Exact endpoint, ordinary paid API tier"}],
            "access_checked_at": None if status == "unknown" else "2026-10-07T04:26:40Z",
            "binding_status": binding,
            "binding_evidence": [{"url": "https://developers.openai.com/api/docs/models/fixture", "title": "Official binding", "claim_type": "official_identity_binding" if binding == "approved" else "official_identity_unresolved", "official_model_id": "fixture", "reason": "Explicit independent identity review"}],
        }

    def test_all_enum_values_validate(self):
        for status in access.ACCESS_STATUSES:
            access.validate_facts(self.fact(status), "openai")
        facts = self.fact(); facts["access_status"] = "experimental_public"
        with self.assertRaisesRegex(ValueError, "ACCESS_ENUM"):
            access.validate_facts(facts, "openai")

    def test_known_requires_evidence(self):
        facts = self.fact(); facts["access_evidence"] = []
        with self.assertRaisesRegex(ValueError, "ACCESS_EVIDENCE"):
            access.validate_facts(facts, "openai")

    def test_known_requires_successful_date(self):
        facts = self.fact(); facts["access_checked_at"] = None
        with self.assertRaisesRegex(ValueError, "ACCESS_CHECKED_AT"):
            access.validate_facts(facts, "openai")

    def test_future_date_rejected(self):
        facts = self.fact(); facts["access_checked_at"] = "2099-01-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "future"):
            access.validate_facts(facts, "openai")

    def test_official_hostname_not_substring(self):
        for url in ["https://openai.com.evil.example/doc", "https://evil.example/openai.com", "https://developers.openai.com@evil.example/doc", "http://openai.com/doc"]:
            with self.assertRaises(ValueError): access.official_hostname("openai", url)
        self.assertEqual(access.official_hostname("openai", "https://developers.openai.com/doc"), "developers.openai.com")

    def test_provider_hostname_scope(self):
        with self.assertRaisesRegex(ValueError, "ACCESS_OFFICIAL_HOST"):
            access.validate_facts(self.fact(), "anthropic")

    def test_pricing_claim_cannot_supply_access(self):
        facts = self.fact(); facts["access_evidence"][0]["claim_type"] = "official_pricing"
        with self.assertRaisesRegex(ValueError, "ACCESS_CLAIM"):
            access.validate_facts(facts, "openai")

    def test_unknown_cannot_claim_public_or_checked_success(self):
        facts = self.fact("unknown"); facts["access_evidence"] = self.fact()["access_evidence"]
        with self.assertRaisesRegex(ValueError, "ACCESS_UNKNOWN"): access.validate_facts(facts, "openai")
        facts = self.fact("unknown"); facts["access_checked_at"] = "2026-10-07T04:26:40Z"
        with self.assertRaisesRegex(ValueError, "ACCESS_UNKNOWN"): access.validate_facts(facts, "openai")

    def seed(self, facts):
        names = dict(zip(access.ACCESS_FIELDS, ["accessStatus", "accessEvidence", "accessCheckedAt", "bindingStatus", "bindingEvidence"]))
        return {**{names[k]: v for k, v in facts.items()}, "accessAuthorityRevision": "a" * 40}

    def test_canonical_present_unknown_cannot_be_promoted(self):
        with self.assertRaisesRegex(ValueError, "ACCESS_AUTHORITY_CONFLICT"):
            access.resolve_authoritative_facts({}, self.seed(self.fact()), "openai")
        facts, authority = access.resolve_authoritative_facts({}, None, "openai")
        self.assertEqual((facts["access_status"], authority), ("unknown", "canonical"))

    def test_canonical_precedence_and_conflicting_seed_fail(self):
        facts = self.fact(); seed = self.seed(self.fact("restricted"))
        with self.assertRaisesRegex(ValueError, "ACCESS_AUTHORITY_CONFLICT"):
            access.resolve_authoritative_facts(facts, seed, "openai")
        self.assertEqual(access.resolve_authoritative_facts(facts, self.seed(facts), "openai"), (facts, "canonical"))

    def test_website_only_seed_requires_pinned_authority(self):
        seed = self.seed(self.fact())
        self.assertEqual(access.resolve_authoritative_facts(None, seed, "openai")[1], "website_only_seed")
        del seed["accessAuthorityRevision"]
        with self.assertRaisesRegex(ValueError, "ACCESS_SEED_REVISION"):
            access.resolve_authoritative_facts(None, seed, "openai")

    def test_binding_independent_of_access(self):
        facts = self.fact(binding="unresolved"); access.validate_facts(facts, "openai")
        self.assertEqual(facts["access_status"], "public")
        facts["binding_status"] = "approved"
        with self.assertRaisesRegex(ValueError, "BINDING_CLAIM"): access.validate_facts(facts, "openai")

    def test_alias_needs_binding_and_entitlement_scope(self):
        alias = {"bindingStatus": "approved", "aliasTargetInternalId": "openai/target"}
        target = {"internalId": "openai/target", "accessStatus": "public", "accessEvidence": [], "accessCheckedAt": None}
        self.assertEqual(access.inherit_alias_access(alias, target, True)["accessStatus"], "public")
        with self.assertRaisesRegex(ValueError, "ACCESS_ALIAS"): access.inherit_alias_access(alias, target, False)
        alias["bindingStatus"] = "unresolved"
        with self.assertRaisesRegex(ValueError, "ACCESS_ALIAS"): access.inherit_alias_access(alias, target, True)

    def test_roundtrip_and_price_provenance_isolation(self):
        facts = self.fact(); sources = {}; access.register_sources(sources, facts, "openai")
        url = facts["access_evidence"][0]["url"]; row = {"providerId": "openai", **access.project_facts(facts, {url: "source:fixture"}, "canonical", "a" * 40)}
        registry = {"source:fixture": sources[url]}
        access.validate_projected_metadata(row, registry, [])
        projection = access.resolve_projection_metadata(row, registry)
        self.assertEqual(projection["accessEvidence"][0]["url"], url)
        with self.assertRaisesRegex(ValueError, "ACCESS_PRICE_PROVENANCE"):
            access.validate_projected_metadata(row, registry, [{"sourceRefs": ["source:fixture"]}])
        projection["accessEvidence"][0]["url"] = "https://openai.com/wrong"
        with self.assertRaisesRegex(ValueError, "ROUNDTRIP"):
            access.validate_projected_metadata(projection, registry, [])

    def test_existing_source_pricing_timestamps_preserved(self):
        facts = self.fact(); url = facts["access_evidence"][0]["url"]
        source = {"supports": ["pricing"], "verifiedAt": "2020-01-01T00:00:00Z", "title": "Pricing title"}
        registry = {url: copy.deepcopy(source)}; access.register_sources(registry, facts, "openai")
        self.assertEqual({k:v for k,v in registry[url].items() if k != "supports"}, {k:v for k,v in source.items() if k != "supports"})

    def test_actual_special_model_claims(self):
        rows = {m["internalId"]:m for m in json.loads((ROOT / "data/pricing-v2-preview/model-identity-registry.json").read_text())}
        for mid in ["claude-mythos-5", "claude-mythos-5-1"]:
            row = rows["anthropic/" + mid]; self.assertEqual(row["accessStatus"], "restricted"); self.assertEqual(row["lifecycleStatus"], "active")
        for mid in ["gemini-2.5-flash", "gemini-2.5-pro"]:
            row = rows["google-gemini/" + mid]; self.assertEqual(row["accessStatus"], "existing_users_only"); self.assertIn("previously actively used this exact model", row["accessEvidence"][0]["scope"]); self.assertEqual(row["lifecycleStatus"], "active")
        self.assertEqual(rows["xai/grok-build-0.1"]["accessStatus"], "public")
        self.assertEqual(rows["google-gemini/gemini-3-flash-preview"]["accessStatus"], "public")
        self.assertEqual(rows["google-gemini/gemini-3-flash-preview"]["releaseStage"], "preview")

    def test_real_generator_conflict_mutation_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); preview = root / "preview"; canonical = root / "canonical"; preview.mkdir(); canonical.mkdir()
            identity = {"internalId":"openai/fixture", "providerId":"openai"}
            for name, rows in [("model-identity-registry.json",[identity]),("models.json",[identity]),("sources.json",[]),("prices.json",[])]:
                (preview/name).write_text(json.dumps(rows))
            (canonical/"models.json").write_text(json.dumps([{"provider_id":"openai","model_id":"fixture",**self.fact()}]))
            seed = {"provider":"OpenAI", "id":"fixture", **self.seed(self.fact("restricted"))}
            seedpath = root / "seed.json"; seedpath.write_text(json.dumps([seed]))
            before = {p.name:p.read_bytes() for p in preview.iterdir()}
            with patch.object(generator, "PREVIEW", preview), patch.object(generator, "CANONICAL", canonical):
                with self.assertRaisesRegex(ValueError, "ACCESS_AUTHORITY_CONFLICT"):
                    generator.update_access_metadata(seedpath)
            self.assertEqual(before, {p.name:p.read_bytes() for p in preview.iterdir()})

    def test_all_artifact_sources_roundtrip(self):
        preview = ROOT / "data/pricing-v2-preview"
        sources = {s["sourceId"]:s for s in json.loads((preview/"sources.json").read_text())}
        prices = json.loads((preview/"prices.json").read_text())
        for filename in ["model-identity-registry.json", "models.json"]:
            for row in json.loads((preview/filename).read_text()): access.validate_projected_metadata(row, sources, prices)

    def test_hf_and_api_access_propagation(self):
        projection = json.loads((ROOT / "data/pricing-v2-preview/generated/model-pricing.v2.json").read_text())
        rows = {(r["provider"],r["id"]):r for r in projection["models"]}
        for record in json.loads((ROOT / "huggingface/prices.json").read_text())["records"]:
            row = rows[(record["provider_id"],record["model_id"])]
            for public, projected in [("access_status","accessStatus"),("access_evidence","accessEvidence"),("access_checked_at","accessCheckedAt"),("binding_status","bindingStatus"),("binding_evidence","bindingEvidence")]:
                self.assertEqual(record[public],row[projected])
        registry = {r["internalId"]:r for r in json.loads((ROOT / "api/v1/meta.json").read_text())["modelAccess"]}
        for internal_id in ["anthropic/claude-mythos-5","google-gemini/gemini-3-flash-preview","google-gemini/gemini-3.1-pro-preview","openai/chatgpt-chat-latest","xai/grok-build-0.1"]:
            self.assertEqual(registry[internal_id]["accessAuthority"]["kind"],"website_only_seed")
            self.assertTrue(registry[internal_id]["accessEvidence"])


    def test_generator_alias_inheritance_requires_explicit_reviewed_scope(self):
        target_facts = self.fact(); alias_facts = self.fact("unknown")
        url = target_facts["access_evidence"][0]["url"]
        sources = {}; access.register_sources(sources, target_facts, "openai")
        registry = {"source:fixture": sources[url]}; by_url = {url:"source:fixture"}
        target = {"providerId":"openai", "internalId":"openai/fixture", "canonicalOfficialId":"fixture", "identityType":"canonical_model", **access.project_facts(target_facts,by_url,"canonical","a"*40)}
        alias = {"providerId":"openai", "internalId":"openai/alias", "canonicalOfficialId":"alias", "identityType":"alias", "aliasTargetInternalId":"openai/fixture", **access.project_facts(alias_facts,by_url,"website_only_seed","b"*40)}
        access.apply_approved_aliases([target,alias],registry,{"openai/fixture"})
        self.assertEqual(alias["accessStatus"],"unknown")
        alias["bindingEvidence"][0]["entitlementScopeMatches"] = True
        access.apply_approved_aliases([target,alias],registry,{"openai/fixture"})
        self.assertEqual(alias["accessStatus"],"public")
        self.assertEqual(alias["accessAuthority"]["kind"],"approved_alias")
        access.validate_projected_metadata(alias,registry,[])
        blocked = {**alias, "accessStatus":"unknown", "bindingStatus":"unresolved"}
        with self.assertRaisesRegex(ValueError,"ACCESS_ALIAS"):
            access.apply_approved_aliases([target,blocked],registry,{"openai/fixture"})



if __name__ == "__main__":
    unittest.main()
