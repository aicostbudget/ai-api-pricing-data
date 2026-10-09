import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import generate_pricing_v2_preview as g
from tests.freshness_assertions import lifecycle_fixture
from scripts.sql_seed import parse_seed, render_sql_seed, reconcile_astra_ultrafast


class TargetedGpt41LifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.canonical = g.read_json(g.CANONICAL / "models.json")
        cls.baseline = lifecycle_fixture(g)
        # Reconstruct the reviewed pre-repair lifecycle from actual persisted records.
        for name, (container, field) in g.GPT41_JSON_TARGETS.items():
            document = json.loads(cls.baseline[name])
            g.exact_gpt41(document[container] if container else document, field)["lifecycleStatus"] = "deprecated"
            cls.baseline[name] = g.render_json(document).encode()
        cls.baseline[g.GPT41_SQL] = render_sql_seed(*[
            json.loads(cls.baseline[name]) for name in ("sources.json", "models.json", "prices.json")
        ]).encode()
        cls.candidate = g.gpt41_candidates(cls.baseline, cls.canonical)

    def altered(self, baseline, name, mutate):
        result = dict(baseline)
        document = json.loads(result[name])
        mutate(document)
        result[name] = g.render_json(document).encode()
        return result

    def isolated(self, directory, baseline):
        preview = Path(directory) / "preview"
        for name, data in baseline.items():
            path = preview / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return preview

    def test_only_target_lifecycle_changes_and_all_other_payloads_are_preserved(self):
        self.assertEqual(set(self.baseline), set(self.candidate))
        changed = {name for name in self.baseline if self.baseline[name] != self.candidate[name]}
        self.assertEqual(changed, {*g.GPT41_JSON_TARGETS, g.GPT41_SQL})
        for name, (container, field) in g.GPT41_JSON_TARGETS.items():
            before, after = json.loads(self.baseline[name]), json.loads(self.candidate[name])
            target = g.exact_gpt41(after[container] if container else after, field)
            self.assertEqual(target["lifecycleStatus"], "active")
            target["lifecycleStatus"] = "deprecated"
            self.assertEqual(before, after)
        for name in ("sources.json", "prices.json", "generated/model-pricing.website-preview.json"):
            self.assertEqual(self.baseline[name], self.candidate[name])
        models = json.loads(self.candidate["models.json"])
        self.assertEqual(len(models), 94)
        for model in ("openai/gpt-4.1-mini", "openai/gpt-4.1-nano"):
            self.assertEqual(g.exact_gpt41(models, "internalId", model),
                             g.exact_gpt41(json.loads(self.baseline["models.json"]), "internalId", model))
        self.assertEqual(g.exact_gpt41(models, "internalId", "openai/gpt-4.1-nano")["lifecycleStatus"], "deprecated")

    def test_access_binding_and_default_safety_remain_blocked(self):
        row = g.exact_gpt41(json.loads(self.candidate["generated/model-pricing.v2.json"])["models"], "canonicalInternalId")
        self.assertEqual((row["accessStatus"], row["bindingStatus"], row["verificationStatus"]),
                         ("unknown", "unresolved", "review_required"))
        self.assertIs(row["defaultSafe"], False)
        self.assertIsNone(row["selectedPriceRecordId"])
        self.assertEqual(row["releaseStage"], "legacy")

    def test_repeated_generation_is_byte_identical(self):
        self.assertEqual(self.candidate, g.gpt41_candidates(self.candidate, self.canonical))

    def test_missing_target_fails_closed(self):
        bad = self.altered(self.baseline, "models.json", lambda rows: rows.remove(g.exact_gpt41(rows, "internalId")))
        with self.assertRaisesRegex(ValueError, "GPT41_IDENTITY"):
            g.gpt41_candidates(bad, self.canonical)

    def test_duplicate_target_fails_closed(self):
        bad = self.altered(self.baseline, "model-identity-registry.json", lambda rows: rows.append(copy.deepcopy(g.exact_gpt41(rows, "internalId"))))
        with self.assertRaisesRegex(ValueError, "GPT41_IDENTITY"):
            g.gpt41_candidates(bad, self.canonical)

    def test_different_target_structure_fails_closed(self):
        bad = self.altered(self.baseline, "models.json", lambda rows: g.exact_gpt41(rows, "internalId").pop("bindingStatus"))
        with self.assertRaisesRegex(ValueError, "GPT41_SAFETY"):
            g.gpt41_candidates(bad, self.canonical)

    def test_eligibility_promotion_fails_closed(self):
        bad = self.altered(self.baseline, "generated/model-pricing.v2.json", lambda doc: g.exact_gpt41(doc["models"], "canonicalInternalId").update(defaultSafe=True))
        with self.assertRaisesRegex(ValueError, "GPT41_SAFETY"):
            g.gpt41_candidates(bad, self.canonical)

    def test_non_target_model_drift_is_rejected(self):
        bad = self.altered(self.candidate, "models.json", lambda rows: rows[0].update(lifecycleStatus="retired"))
        with self.assertRaisesRegex(ValueError, "GPT41_DIFF"):
            g.audit_gpt41_delta(self.baseline, bad, "active")

    def test_source_drift_is_rejected(self):
        bad = self.altered(self.candidate, "sources.json", lambda rows: rows[0].update(checkedAt="2099-01-01T00:00:00Z"))
        with self.assertRaisesRegex(ValueError, "GPT41_DIFF"):
            g.audit_gpt41_delta(self.baseline, bad, "active")

    def test_price_drift_is_rejected(self):
        bad = self.altered(self.candidate, "prices.json", lambda rows: rows[0]["charges"][0].update(amount="999"))
        with self.assertRaisesRegex(ValueError, "GPT41_DIFF"):
            g.audit_gpt41_delta(self.baseline, bad, "active")

    def test_cli_check_is_read_only_when_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            preview = self.isolated(directory, self.baseline)
            with patch.object(g, "PREVIEW", preview), patch.object(g.sys, "argv", ["generator", "--targeted-gpt41-lifecycle", "--check"]):
                with self.assertRaisesRegex(ValueError, "GPT41_CHECK"):
                    g.main()
            self.assertEqual(g.frozen_preview(preview), self.baseline)

    def test_cli_check_is_read_only_when_in_sync(self):
        with tempfile.TemporaryDirectory() as directory:
            preview = self.isolated(directory, self.candidate)
            with patch.object(g, "PREVIEW", preview), patch.object(g.sys, "argv", ["generator", "--targeted-gpt41-lifecycle", "--check"]), patch("builtins.print"):
                g.main()
            self.assertEqual(g.frozen_preview(preview), self.candidate)

    def test_gate_failure_leaves_all_files_untouched(self):
        bad = self.altered(self.candidate, "models.json", lambda rows: rows[0].update(availability="promoted"))
        with tempfile.TemporaryDirectory() as directory:
            preview = self.isolated(directory, self.baseline)
            with self.assertRaisesRegex(ValueError, "GPT41_DIFF"):
                g.persist_gpt41(preview, self.baseline, bad)
            self.assertEqual(g.frozen_preview(preview), self.baseline)

    def test_mid_write_exception_rolls_back_completed_replacements(self):
        replace = g.os.replace
        calls = 0
        def fail_second(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected replacement failure")
            return replace(source, destination)
        with tempfile.TemporaryDirectory() as directory:
            preview = self.isolated(directory, self.baseline)
            with patch.object(g.os, "replace", side_effect=fail_second):
                with self.assertRaisesRegex(OSError, "injected"):
                    g.persist_gpt41(preview, self.baseline, self.candidate)
            self.assertEqual(g.frozen_preview(preview), self.baseline)
            self.assertEqual(list(Path(directory).iterdir()), [preview])

    def test_cli_write_is_idempotent_and_preserves_all_other_files(self):
        with tempfile.TemporaryDirectory() as directory:
            preview = self.isolated(directory, self.baseline)
            with patch.object(g, "PREVIEW", preview), patch.object(g.sys, "argv", ["generator", "--targeted-gpt41-lifecycle", "--write"]), patch("builtins.print"):
                g.main()
                self.assertEqual(g.frozen_preview(preview), self.candidate)
                g.main()
                self.assertEqual(g.frozen_preview(preview), self.candidate)

    def test_sql_preserves_every_key_non_target_insert_and_transaction(self):
        before, after = parse_seed(self.baseline[g.GPT41_SQL].decode()), parse_seed(self.candidate[g.GPT41_SQL].decode())
        self.assertEqual([(r.table, r.key) for r in before], [(r.table, r.key) for r in after])
        self.assertEqual(len(after), 170 + 94 + 250)
        self.assertTrue(all(r.in_transaction and r.upsert for r in after))
        for old, new in zip(before, after):
            if (old.table, old.key) != ("models", g.GPT41_TARGET):
                self.assertEqual(old.raw, new.raw)
        sources, models, prices = [json.loads(self.candidate[name]) for name in ("sources.json", "models.json", "prices.json")]
        sql = self.candidate[g.GPT41_SQL].decode()
        self.assertEqual(sql, render_sql_seed(sources, models, prices))
        self.assertEqual(sql, reconcile_astra_ultrafast(sql, sources, prices))

    def test_sql_baseline_non_target_drift_fails_before_generation(self):
        bad = dict(self.baseline)
        sources = json.loads(bad["sources.json"])
        sources[0]["title"] = "drift"
        bad[g.GPT41_SQL] = render_sql_seed(sources, json.loads(bad["models.json"]), json.loads(bad["prices.json"])).encode()
        with self.assertRaisesRegex(ValueError, "GPT41_SQL"):
            g.gpt41_candidates(bad, self.canonical)

    def test_concurrent_input_drift_fails_before_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            preview = self.isolated(directory, self.baseline)
            original = preview / "sources.json"
            original.write_bytes(original.read_bytes() + b" ")
            current = g.frozen_preview(preview)
            with self.assertRaisesRegex(ValueError, "GPT41_CONCURRENT"):
                g.persist_gpt41(preview, self.baseline, self.candidate)
            self.assertEqual(g.frozen_preview(preview), current)


if __name__ == "__main__":
    unittest.main()
