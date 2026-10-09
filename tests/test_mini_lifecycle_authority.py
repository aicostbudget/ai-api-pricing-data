import json
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import generate_pricing_v2_preview as g
from scripts import lifecycle_authority as authority
from scripts.sql_seed import parse_seed, render_sql_seed


class MiniLifecycleAuthorityTests(unittest.TestCase):
    def record(self):
        return copy.deepcopy(g.read_json(authority.AUTHORITY_PATH)[0])

    def test_real_authority_drives_mini_lifecycle_without_promoting_review(self):
        authority = g.read_json(g.CANONICAL / "model-lifecycle-evidence.json")
        self.assertEqual(authority[0]["normalizedLifecycleStatus"], "active")
        public = next((row for row in g.read_json(g.CANONICAL / "models.json")
                       if (row["provider_id"], row["model_id"]) == ("openai", "gpt-4.1-mini")), None)
        self.assertIsNone(public)
        website = next(row for row in g.read_json(g.GENERATED / "model-pricing.website-preview.json")
                       if row["id"] == "gpt-4.1-mini")
        self.assertEqual(g.status_parts("openai", "gpt-4.1-mini", public, website), {
            "lifecycleStatus": "active", "releaseStage": "legacy",
            "availability": "Legacy", "verificationStatus": "review_required",
        })

    def test_closed_schema_and_single_target(self):
        self.assertEqual(authority.load_authority(), self.record())
        schema = g.read_json(authority.SCHEMA_PATH)
        schema["items"]["additionalProperties"] = True
        with self.assertRaisesRegex(ValueError, "LIFECYCLE_SCHEMA"):
            authority.validate_authority([self.record()], schema)

    def test_missing_authority_refuses_promotion(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(authority, "AUTHORITY_PATH", Path(directory) / "missing.json"):
            with self.assertRaisesRegex(ValueError, "LIFECYCLE_AUTHORITY"):
                g.status_parts("openai", "gpt-4.1-mini", None, {"status": "legacy"})

    def test_wrong_model_id(self):
        row = self.record(); row["modelId"] = "gpt-4.1"
        with self.assertRaises(ValueError): authority.validate_authority([row])

    def test_malformed_or_unsupported_schema_fails_closed(self):
        for schema in ([], {"items": []}, {**g.read_json(authority.SCHEMA_PATH), "unimplementedKeyword": True}):
            with self.subTest(schema=str(type(schema))), self.assertRaises(ValueError):
                authority.validate_authority([self.record()], schema)

    def test_wrong_provider(self):
        row = self.record(); row["providerId"] = "other"
        with self.assertRaises(ValueError): authority.validate_authority([row])

    def test_wrong_internal_id(self):
        row = self.record(); row["canonicalInternalId"] = "openai/gpt-4.1-nano"
        with self.assertRaises(ValueError): authority.validate_authority([row])

    def test_duplicate_or_conflicting_records(self):
        for rows in ([], [self.record(), self.record()], [self.record(), {**self.record(), "normalizedLifecycleStatus": "deprecated"}]):
            with self.subTest(rows=len(rows)), self.assertRaises(ValueError): authority.validate_authority(rows)

    def test_unapproved_sources(self):
        for url in ("http://developers.openai.com/api/docs/models/gpt-4.1-mini", "https://example.com/model", "https://developers.openai.com/api/docs/models/gpt-4.1-nano", "https://developers.openai.com.evil.example/model"):
            row = self.record(); row["officialModelUrl"] = url
            with self.subTest(url=url), self.assertRaises(ValueError): authority.validate_authority([row])

    def test_missing_official_source(self):
        for key in ("officialModelUrl", "officialDeprecationsUrl"):
            row = self.record(); row.pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError): authority.validate_authority([row])

    def test_dated_snapshot_cannot_impersonate_base_id(self):
        row = self.record(); row["modelId"] = "gpt-4.1-mini-2025-04-14"
        with self.assertRaises(ValueError): authority.validate_authority([row])

    def test_wrong_or_duplicate_documented_snapshot(self):
        for snapshots in ([], ["gpt-4.1-nano-2025-04-14"], ["gpt-4.1-mini-2025-04-14"] * 2):
            row = self.record(); row["documentedSnapshotIds"] = snapshots
            with self.subTest(snapshots=snapshots), self.assertRaises(ValueError): authority.validate_authority([row])

    def test_invalid_normalized_status(self):
        for status in ("verified", "public", "Default", "deprecated", None):
            row = self.record(); row["normalizedLifecycleStatus"] = status
            with self.subTest(status=status), self.assertRaises(ValueError): authority.validate_authority([row])

    def test_default_label_alone_does_not_establish_active(self):
        row = self.record(); row.pop("deprecationEvidenceResult")
        with self.assertRaises(ValueError): authority.validate_authority([row])
        row = self.record(); row["deprecationEvidenceResult"] = "listed"
        with self.assertRaises(ValueError): authority.validate_authority([row])

    def test_forbidden_price_access_and_eligibility_fields(self):
        for key in ("inputPrice", "outputPrice", "cachedInputPrice", "batchPrice", "priceRecord", "defaultSafe", "calculationDefault", "accessStatus", "bindingStatus", "accountEntitlement", "shutdownDate"):
            row = self.record(); row[key] = "unapproved"
            with self.subTest(key=key), self.assertRaises(ValueError): authority.validate_authority([row])

    def test_invalid_or_future_utc_observation(self):
        for value in ("2026-10-09", "2026-13-09T00:00:00Z", "2026-10-09T00:00:00+00:00", "2099-01-01T00:00:00Z"):
            row = self.record(); row["lifecycleCheckedAt"] = value
            with self.subTest(value=value), self.assertRaises(ValueError): authority.validate_authority([row])

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            authority.parsed(b'{"modelId":"gpt-4.1-mini","modelId":"gpt-4.1"}')

    def test_authority_is_not_applied_to_base_or_nano_default_label(self):
        for model, expected in (("gpt-4.1", "active"), ("gpt-4.1-nano", "deprecated")):
            row = g.status_parts("openai", model, {"status": "active"}, {"status": "latest", "availability": "Default"}, mini_authority=self.record())
            self.assertEqual((row["lifecycleStatus"], row["verificationStatus"]), (expected, "review_required"))


class TargetedMiniLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.authority = authority.load_authority()
        cls.baseline = g.frozen_preview(g.PREVIEW)
        for name, (container, field) in g.GPT41_JSON_TARGETS.items():
            document = json.loads(cls.baseline[name])
            g.exact_gpt41(document[container] if container else document, field, authority.MINI_ID)["lifecycleStatus"] = "deprecated"
            cls.baseline[name] = g.render_json(document).encode()
        cls.baseline[g.GPT41_SQL] = render_sql_seed(*[json.loads(cls.baseline[name]) for name in ("sources.json", "models.json", "prices.json")]).encode()
        cls.candidate = g.mini_candidates(cls.baseline, cls.authority)
        cls.context = g.mini_context()
        cls.head = g.lifecycle_git_head()
        cls.review = g.review_mini_candidate(cls.baseline, cls.candidate, cls.context, cls.head)

    def isolated(self, directory):
        preview = Path(directory) / "preview"
        for name, data in self.baseline.items():
            path = preview / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        return preview

    def changed(self, baseline, name, mutate):
        result = dict(baseline); document = json.loads(result[name]); mutate(document)
        result[name] = g.render_json(document).encode(); return result

    def test_only_four_outputs_and_one_lifecycle_field(self):
        self.assertEqual({n for n in self.baseline if self.baseline[n] != self.candidate[n]}, {*g.GPT41_JSON_TARGETS, g.GPT41_SQL})
        for name, (container, field) in g.GPT41_JSON_TARGETS.items():
            before, after = json.loads(self.baseline[name]), json.loads(self.candidate[name])
            row = g.exact_gpt41(after[container] if container else after, field, authority.MINI_ID)
            self.assertEqual(row["lifecycleStatus"], "active")
            self.assertEqual((row["verificationStatus"], row["releaseStage"], row["accessStatus"], row["bindingStatus"]), ("review_required", "legacy", "unknown", "unresolved"))
            row["lifecycleStatus"] = "deprecated"; self.assertEqual(after, before)

    def test_all_prices_charges_sources_and_freshness_bytes_unchanged(self):
        for name in self.baseline:
            if name not in {*g.GPT41_JSON_TARGETS, g.GPT41_SQL}: self.assertEqual(self.baseline[name], self.candidate[name], name)
        prices = json.loads(self.candidate["prices.json"])
        mini = [p for p in prices if p["modelInternalId"] == authority.MINI_ID]
        self.assertEqual(len(mini), 1); self.assertFalse(mini[0]["calculationDefault"])
        self.assertEqual(len(prices), 250); self.assertEqual(sum(len(p["charges"]) for p in prices), 751)
        self.assertEqual(len(json.loads(self.candidate["sources.json"])), 170)

    def test_safety_defaults_and_family_preserved(self):
        models = json.loads(self.candidate["models.json"]); rich = json.loads(self.candidate["generated/model-pricing.v2.json"])["models"]
        for mid, expected in (("gpt-4.1", "active"), ("gpt-4.1-mini", "active"), ("gpt-4.1-nano", "deprecated")):
            row = g.exact_gpt41(rich, "canonicalInternalId", "openai/" + mid)
            self.assertEqual(row["lifecycleStatus"], expected); self.assertFalse(row["defaultSafe"]); self.assertIsNone(row["selectedPriceRecordId"])
        self.assertIsNone(g.exact_gpt41(models, "internalId", authority.MINI_ID)["defaultPriceRecordId"])

    def test_missing_and_duplicate_target_refused(self):
        for duplicate in (False, True):
            def mutate(rows):
                row = g.exact_gpt41(rows, "internalId", authority.MINI_ID)
                rows.append(copy.deepcopy(row)) if duplicate else rows.remove(row)
            bad = self.changed(self.baseline, "models.json", mutate)
            with self.subTest(duplicate=duplicate), self.assertRaises(ValueError): g.mini_candidates(bad, self.authority)

    def test_explicit_safety_promotion_refused(self):
        bad = self.changed(self.baseline, "generated/model-pricing.v2.json", lambda d: g.exact_gpt41(d["models"], "canonicalInternalId", authority.MINI_ID).update(defaultSafe=True))
        with self.assertRaisesRegex(ValueError, "MINI_SAFETY"): g.mini_candidates(bad, self.authority)

    def test_non_target_model_field_refused(self):
        bad = self.changed(self.candidate, "models.json", lambda rows: rows[0].update(availability="promoted"))
        with self.assertRaises(ValueError): g.audit_mini_delta(self.baseline, bad)

    def test_target_non_lifecycle_field_refused(self):
        bad = self.changed(self.candidate, "models.json", lambda rows: g.exact_gpt41(rows, "internalId", authority.MINI_ID).update(verificationStatus="verified"))
        with self.assertRaises(ValueError): g.audit_mini_delta(self.baseline, bad)

    def test_source_price_and_generated_at_drift_refused(self):
        for name, mutate in (("sources.json", lambda rows: rows[0].update(checkedAt="2099-01-01T00:00:00Z")), ("prices.json", lambda rows: rows[0]["charges"][0].update(amount="999")), ("generated/model-pricing.v2.json", lambda d: d.update(generatedAt="2099-01-01T00:00:00Z"))):
            bad = self.changed(self.candidate, name, mutate)
            with self.subTest(name=name), self.assertRaises(ValueError): g.audit_mini_delta(self.baseline, bad)

    def test_sql_preserves_transactions_keys_order_and_every_other_insert(self):
        before, after = parse_seed(self.baseline[g.GPT41_SQL].decode()), parse_seed(self.candidate[g.GPT41_SQL].decode())
        self.assertEqual([(r.table, r.key) for r in before], [(r.table, r.key) for r in after])
        self.assertEqual(len(after), 514); self.assertTrue(all(r.in_transaction and r.upsert for r in after))
        for old, new in zip(before, after):
            if (old.table, old.key) != ("models", authority.MINI_ID): self.assertEqual(old.raw, new.raw)
        bad = dict(self.candidate); bad[g.GPT41_SQL] += b"-- unauthorized footer\n"
        with self.assertRaises(ValueError): g.audit_mini_delta(self.baseline, bad)

    def test_full_validator_accepts_temp_candidate(self):
        self.assertEqual(json.loads((self.review / "review.json").read_bytes())["validation"]["model_count"], 94)

    def test_tampered_temp_review_is_refused_before_any_write(self):
        with tempfile.TemporaryDirectory() as directory:
            preview = self.isolated(directory)
            with self.assertRaisesRegex(ValueError, "MINI_REVIEW"):
                g.persist_mini(preview, self.baseline, self.candidate, self.context, self.head, Path(directory) / "missing-review")
            self.assertEqual(g.frozen_preview(preview), self.baseline)

    def test_check_refuses_stale_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            preview = self.isolated(directory)
            with patch.object(g, "PREVIEW", preview), patch("builtins.print"), self.assertRaisesRegex(ValueError, "MINI_CHECK"):
                g.targeted_identity_lifecycle(authority.MINI_ID, False)
            self.assertEqual(g.frozen_preview(preview), self.baseline)

    def test_cli_write_then_check_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            preview = self.isolated(directory)
            with patch.object(g, "PREVIEW", preview), patch("builtins.print"):
                for mode in ("--write", "--write", "--check"):
                    with patch.object(g.sys, "argv", ["generator", "--targeted-identity-lifecycle", "--model-internal-id", authority.MINI_ID, mode]): g.main()
                    self.assertEqual(g.frozen_preview(preview), self.candidate)

    def test_single_target_allowlist_rejects_wildcards_other_models_and_multiple_ids(self):
        for target in (None, "openai/*", "openai/gpt-4.1", "openai/gpt-4.1-nano", authority.MINI_ID + ",openai/gpt-4.1"):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "MINI_TARGET"): g.targeted_identity_lifecycle(target, False)

    def test_conflicting_cli_modes_rejected(self):
        with patch.object(g.sys, "argv", ["generator", "--targeted-identity-lifecycle", "--targeted-gpt41-lifecycle", "--check"]), patch("sys.stderr"):
            with self.assertRaises(SystemExit) as raised: g.main()
        self.assertEqual(raised.exception.code, 2)

    def test_head_drift_refused(self):
        with patch.object(g, "lifecycle_git_head", return_value="changed"), self.assertRaisesRegex(ValueError, "MINI_CONCURRENT"):
            g.assert_mini_context(self.context, self.head)

    def test_external_input_drift_before_write_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            preview = self.isolated(directory); source = Path(directory) / "authority.json"; source.write_bytes(b"original")
            context = {source: b"original"}; source.write_bytes(b"concurrent")
            with self.assertRaisesRegex(ValueError, "MINI_CONCURRENT"): g.persist_mini(preview, self.baseline, self.candidate, context, self.head, self.review)
            self.assertEqual(g.frozen_preview(preview), self.baseline); self.assertEqual(source.read_bytes(), b"concurrent")

    def test_preview_input_drift_before_write_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            preview = self.isolated(directory); (preview / "sources.json").write_bytes(self.baseline["sources.json"] + b" ")
            current = g.frozen_preview(preview)
            with self.assertRaisesRegex(ValueError, "MINI_CONCURRENT"): g.persist_mini(preview, self.baseline, self.candidate, self.context, self.head, self.review)
            self.assertEqual(g.frozen_preview(preview), current)

    def test_partial_mid_write_failure_restores_every_attempted_file(self):
        count = 0; original = g.write_mini_artifact
        def fail_second(path, data):
            nonlocal count
            count += 1
            if count == 2:
                path.write_bytes(b"partial write"); raise OSError("injected partial write")
            original(path, data)
        with tempfile.TemporaryDirectory() as directory:
            preview = self.isolated(directory)
            with patch.object(g, "write_mini_artifact", side_effect=fail_second), self.assertRaisesRegex(OSError, "injected"):
                g.persist_mini(preview, self.baseline, self.candidate, self.context, self.head, self.review)
            self.assertEqual(g.frozen_preview(preview), self.baseline)

    def test_mid_write_input_drift_rolls_back_outputs_preserving_foreign_input(self):
        original = g.write_mini_artifact
        with tempfile.TemporaryDirectory() as directory:
            preview = self.isolated(directory); source = Path(directory) / "authority.json"; source.write_bytes(b"original")
            def mutate_input(path, data): original(path, data); source.write_bytes(b"concurrent")
            with patch.object(g, "write_mini_artifact", side_effect=mutate_input), self.assertRaisesRegex(ValueError, "MINI_CONCURRENT"):
                g.persist_mini(preview, self.baseline, self.candidate, {source: b"original"}, self.head, self.review)
            self.assertEqual(g.frozen_preview(preview), self.baseline); self.assertEqual(source.read_bytes(), b"concurrent")

    def test_old_base_mode_preserves_reconciled_mini_and_nano(self):
        self.assertEqual(g.gpt41_candidates(self.candidate, g.read_json(g.CANONICAL / "models.json")), self.candidate)


if __name__ == "__main__":
    unittest.main()
