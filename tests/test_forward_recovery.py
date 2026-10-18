import copy
import csv
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.check_release_gate import GateError, assert_local_release_identity, verify_production
from scripts.forward_recovery import (
    RecoveryBackend,
    RecoveryShellBackend,
    RecoveryStateStore,
    ReleaseFailure,
    plan_digest,
    publish_recovery,
    write_json,
    HISTORICAL_FIELDS,
    RECOVERY_PLAN_SCHEMA,
    RecoveryContractError,
    assert_recovery_tag_available,
    canonical_bytes,
    load_committed_recovery_plan,
    projection_contract,
    recovery_tag_name,
    sha256_bytes,
    validate_projection_contract,
    validate_recovery_chain,
    validate_recovery_plan,
    validate_website_reuse_contract,
    website_contract_from_export,
)


ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_SOURCE = "fff06c723507d648cd3b325659803e28a897f831"
HISTORICAL_ARTIFACT = "31696019569ebfd033ad085a49f62ba6eee0c109"
HISTORICAL_TAG = "dataset-2026-10-15-grok-voice-3-0"
HISTORICAL_TAG_OBJECT = "371eecdc1337b5f1ae0c3da2adb576e3e277232f"
C0, S1, S2, W0, W1 = (character * 40 for character in "12345")


def rows():
    return [
        {"provider_id": "xai", "model_id": "grok-voice-2.0", "input": 1},
        {"provider_id": "xai", "model_id": "grok-voice-3.0", "input": 2},
        {"provider_id": "openai", "model_id": "gpt-fixture", "input": 3},
    ]


def projection_fixture(values=None):
    values = copy.deepcopy(values if values is not None else rows())
    json_bytes = json.dumps({"records": values}, sort_keys=True).encode()
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=["provider_id", "model_id", "input"], lineterminator="\n")
    writer.writeheader()
    writer.writerows(values)
    csv_bytes = output.getvalue().encode()
    return values, json_bytes, csv_bytes, projection_contract(values, json_bytes, csv_bytes)


def website_export():
    return {
        "json": {"metadata": {"schema_version": "1.10.0"}, "records": rows()},
        "csv": "provider_id,model_id\nxai,grok-voice-2.0\nxai,grok-voice-3.0\n",
        "version": {"pricing_fingerprint": "approved-fingerprint", "schema_version": 3},
    }


def recovery_plan():
    _, _, _, contract = projection_fixture()
    return {
        "schema": RECOVERY_PLAN_SCHEMA,
        "recovery_id": "grok-voice-forward-recovery-2026-10-15",
        "dataset_base_sha": C0,
        "canonical_sha256": sha256_bytes(b"canonical\n"),
        "snapshot_generated_at": "2026-10-15T10:15:09Z",
        "recovery_created_at": "2026-10-16T12:00:00Z",
        "recovery_reason": "Recover already-existing canonical facts through a new forward-only identity.",
        "historical_context": {
            "historical_source_sha": HISTORICAL_SOURCE,
            "historical_artifact_sha": HISTORICAL_ARTIFACT,
            "historical_tag": HISTORICAL_TAG,
            "historical_tag_object_sha": HISTORICAL_TAG_OBJECT,
            "historical_tag_target_sha": HISTORICAL_ARTIFACT,
            "legacy_identity_status": "FAIL_CLOSED",
            "legacy_plan_status": "FAIL_CLOSED",
            "expected_stale_pages_identity": {"source_commit_sha": "19ee35964833714b7891453ad1cb55adcf86a56c", "model_count": 89},
            "expected_stale_hf_identity": {"record_count": 87},
        },
        "projection_contracts": {"pages_v1": copy.deepcopy(contract), "pricing_v2_hf": copy.deepcopy(contract)},
        "website_contract": website_contract_from_export(website_export(), W1, W0),
    }


def chain_fixture(plan=None):
    plan = copy.deepcopy(plan or recovery_plan())
    plan_bytes = canonical_bytes(plan)
    blobs = {
        (C0, "data/canonical/models.json"): b"canonical\n",
        (S1, "data/canonical/models.json"): b"canonical\n",
        (S2, "data/canonical/models.json"): b"canonical\n",
        (S2, "api/v1/meta.json"): json.dumps({"source_commit_sha": S1, "generated_at": "2026-10-15T10:15:09Z"}).encode(),
        (S2, "huggingface/meta.json"): json.dumps({"generated_at": "2026-10-15T10:15:09Z"}).encode(),
    }
    parents = {S1: C0, S2: S1}
    changes = {(C0, S1): [f"release-plans/{plan['recovery_id']}.json"], (S1, S2): ["api/v1/meta.json", "api/v1/prices.json"]}
    tags = {HISTORICAL_TAG: (HISTORICAL_TAG_OBJECT, HISTORICAL_ARTIFACT)}
    arguments = (
        plan,
        plan_bytes,
        plan_bytes,
        sha256_bytes(plan_bytes),
        S1,
        S2,
        lambda revision: parents[revision],
        lambda revision, path: blobs[(revision, path)],
        lambda before, after: changes[(before, after)],
        lambda tag: tags[tag][0],
        lambda tag: tags[tag][1],
    )
    return plan, plan_bytes, blobs, parents, changes, tags, arguments


class RecoverySchemaIsolationTests(unittest.TestCase):
    def test_daily_and_recovery_modules_do_not_import_each_other(self):
        daily = (ROOT / "scripts/daily_pricing_release.py").read_text(encoding="utf-8")
        recovery = (ROOT / "scripts/forward_recovery.py").read_text(encoding="utf-8")
        self.assertNotIn("forward_recovery", daily)
        self.assertNotIn("daily_pricing_release", recovery)

    def test_non_recovery_plan_is_rejected_by_recovery_loader(self):
        payload = json.dumps({"schema": "ordinary", "release_id": "daily-fixture"}).encode()
        with self.assertRaisesRegex(RecoveryContractError, "schema"):
            load_committed_recovery_plan(ROOT, "daily-fixture", sha256_bytes(payload), S1, S2, lambda revision, path: payload)

    def test_every_top_level_and_historical_required_field_is_fail_closed(self):
        plan = recovery_plan()
        for field in list(plan):
            with self.subTest(field=field):
                broken = copy.deepcopy(plan)
                del broken[field]
                with self.assertRaises(RecoveryContractError):
                    validate_recovery_plan(broken)
        for field in HISTORICAL_FIELDS:
            with self.subTest(historical_field=field):
                broken = copy.deepcopy(plan)
                del broken["historical_context"][field]
                with self.assertRaises(RecoveryContractError):
                    validate_recovery_plan(broken)


class RecoveryIdentityTests(unittest.TestCase):
    def test_full_new_chain_passes(self):
        *_, arguments = chain_fixture()
        validate_recovery_chain(*arguments)

    def test_backfill_to_old_artifact_fails(self):
        plan, plan_bytes, *_ = chain_fixture()
        with self.assertRaises(RecoveryContractError):
            validate_recovery_chain(plan, plan_bytes, plan_bytes, sha256_bytes(plan_bytes), HISTORICAL_SOURCE, HISTORICAL_ARTIFACT, lambda revision: C0, lambda revision, path: b"canonical\n", lambda before, after: [], lambda tag: HISTORICAL_TAG_OBJECT, lambda tag: HISTORICAL_ARTIFACT)

    def test_historical_source_cannot_be_new_s1(self):
        *_, arguments = chain_fixture()
        altered = list(arguments)
        altered[4] = HISTORICAL_SOURCE
        with self.assertRaises(RecoveryContractError):
            validate_recovery_chain(*altered)

    def test_s1_parent_must_equal_c0(self):
        *_, arguments = chain_fixture()
        altered = list(arguments)
        altered[6] = lambda revision: "9" * 40 if revision == S1 else S1
        with self.assertRaisesRegex(RecoveryContractError, "S1 parent"):
            validate_recovery_chain(*altered)

    def test_s2_parent_must_equal_s1(self):
        *_, arguments = chain_fixture()
        altered = list(arguments)
        altered[6] = lambda revision: C0
        with self.assertRaisesRegex(RecoveryContractError, "S2 parent"):
            validate_recovery_chain(*altered)

    def test_canonical_change_at_s1_or_s2_fails(self):
        for changed_revision in (S1, S2):
            with self.subTest(revision=changed_revision):
                *_, arguments = chain_fixture()
                original = arguments[7]
                altered = list(arguments)
                altered[7] = lambda revision, path, original=original: b"changed\n" if revision == changed_revision and path == "data/canonical/models.json" else original(revision, path)
                with self.assertRaisesRegex(RecoveryContractError, "Canonical bytes"):
                    validate_recovery_chain(*altered)

    def test_plan_bytes_and_digest_must_match(self):
        *_, arguments = chain_fixture()
        altered = list(arguments)
        altered[2] = b"different"
        with self.assertRaisesRegex(RecoveryContractError, "Plan bytes"):
            validate_recovery_chain(*altered)
        altered = list(arguments)
        altered[3] = "0" * 64
        with self.assertRaisesRegex(RecoveryContractError, "digest"):
            validate_recovery_chain(*altered)

    def test_s1_is_plan_only_and_s2_is_artifact_only(self):
        *_, arguments = chain_fixture()
        original = arguments[8]
        for pair, files in [((C0, S1), ["data/canonical/models.json"]), ((S1, S2), ["README.md"])]:
            with self.subTest(pair=pair):
                altered = list(arguments)
                altered[8] = lambda before, after, pair=pair, files=files: files if (before, after) == pair else original(before, after)
                with self.assertRaises(RecoveryContractError):
                    validate_recovery_chain(*altered)

    def test_s2_metadata_source_must_be_s1(self):
        *_, arguments = chain_fixture()
        original = arguments[7]
        altered = list(arguments)
        altered[7] = lambda revision, path: json.dumps({"source_commit_sha": HISTORICAL_SOURCE, "generated_at": "2026-10-15T10:15:09Z"}).encode() if (revision, path) == (S2, "api/v1/meta.json") else original(revision, path)
        with self.assertRaisesRegex(RecoveryContractError, "source_commit_sha"):
            validate_recovery_chain(*altered)

    def test_snapshot_fact_time_cannot_be_replaced_by_recovery_time(self):
        *_, arguments = chain_fixture()
        original = arguments[7]
        for path in ("api/v1/meta.json", "huggingface/meta.json"):
            with self.subTest(path=path):
                altered = list(arguments)
                payload = {"source_commit_sha": S1, "generated_at": "2026-10-16T12:00:00Z"}
                altered[7] = lambda revision, candidate, path=path, payload=payload: json.dumps(payload).encode() if (revision, candidate) == (S2, path) else original(revision, candidate)
                with self.assertRaisesRegex(RecoveryContractError, "snapshot_generated_at"):
                    validate_recovery_chain(*altered)

    def test_historical_tag_object_and_target_are_immutable(self):
        *_, arguments = chain_fixture()
        for index in (9, 10):
            altered = list(arguments)
            altered[index] = lambda tag: "9" * 40
            with self.assertRaisesRegex(RecoveryContractError, "Historical tag"):
                validate_recovery_chain(*altered)

    def test_new_tag_is_deterministic_distinct_and_must_be_absent(self):
        plan = recovery_plan()
        tag = recovery_tag_name(plan)
        self.assertTrue(tag.startswith("dataset-recovery-2026-10-15-"))
        self.assertNotEqual(tag, HISTORICAL_TAG)
        self.assertEqual(assert_recovery_tag_available(plan, "", ""), tag)
        for local, remote in [("exists", ""), ("", "exists")]:
            with self.assertRaisesRegex(RecoveryContractError, "ALREADY EXISTS"):
                assert_recovery_tag_available(plan, local, remote)


class ProjectionAndWebsiteContractTests(unittest.TestCase):
    def test_v1_and_v2_contracts_are_independent(self):
        plan = recovery_plan()
        plan["projection_contracts"]["pages_v1"]["record_count"] = 91
        plan["projection_contracts"]["pricing_v2_hf"]["record_count"] = 89
        validate_recovery_plan(plan)

    def test_model_provider_row_and_file_digest_drift_fail_closed(self):
        values, json_bytes, csv_bytes, contract = projection_fixture()
        mutations = []
        missing_voice_2 = [row for row in values if row["model_id"] != "grok-voice-2.0"]
        missing_voice_3 = [row for row in values if row["model_id"] != "grok-voice-3.0"]
        mutations.extend([missing_voice_2, missing_voice_3])
        mutations.append([{**row, "provider_id": "other" if index == 0 else row["provider_id"]} for index, row in enumerate(values)])
        mutations.append([{**row, "input": 999 if index == 0 else row["input"]} for index, row in enumerate(values)])
        for changed in mutations:
            with self.subTest(changed=changed):
                changed_rows, changed_json, changed_csv, _ = projection_fixture(changed)
                with self.assertRaises(RecoveryContractError):
                    validate_projection_contract(contract, changed_rows, changed_json, changed_csv, "fixture")
        with self.assertRaises(RecoveryContractError):
            validate_projection_contract(contract, values, json_bytes + b" ", csv_bytes, "fixture")
        with self.assertRaises(RecoveryContractError):
            validate_projection_contract(contract, values, json_bytes, csv_bytes + b"\n", "fixture")

    def test_json_csv_identity_mismatch_fails(self):
        values, json_bytes, _, _ = projection_fixture()
        bad_csv = b"provider_id,model_id,input\nxai,grok-voice-2.0,1\n"
        with self.assertRaisesRegex(RecoveryContractError, "JSON/CSV"):
            projection_contract(values, json_bytes, bad_csv)

    def test_website_reuse_remote_parent_and_production_evidence_are_exact(self):
        expected = website_export()
        contract = website_contract_from_export(expected, W1, W0)
        validate_website_reuse_contract(contract, expected, W1, W0)
        cases = [
            (expected, "9" * 40, W0),
            (expected, W1, "9" * 40),
            ({**expected, "json": {"changed": True}}, W1, W0),
            ({**expected, "csv": expected["csv"] + "xai,extra\n"}, W1, W0),
            ({**expected, "version": {**expected["version"], "pricing_fingerprint": "changed"}}, W1, W0),
        ]
        for candidate, remote, parent in cases:
            with self.subTest(remote=remote, parent=parent, candidate=candidate):
                with self.assertRaises(RecoveryContractError):
                    validate_website_reuse_contract(contract, candidate, remote, parent)

    def test_recovery_production_requires_approved_json_csv_and_manifest_digests(self):
        expected = website_export()
        contract = website_contract_from_export(expected, W1, W0)
        def fetch(url):
            if url.endswith(".json"):
                return 200, "application/json", json.dumps(expected["json"]).encode()
            if url.endswith(".csv"):
                return 200, "text/csv", expected["csv"].encode()
            return 200, "application/json", json.dumps(expected["version"]).encode()
        verify_production(expected, fetch, contract)
        def padded_csv(url):
            status, content_type, body = fetch(url)
            return (status, content_type, body + b"\n") if url.endswith(".csv") else (status, content_type, body)
        with self.assertRaisesRegex(GateError, "CSV digest"):
            verify_production(expected, padded_csv, contract)


class HistoricalFixtureTests(unittest.TestCase):
    def test_real_legacy_chain_still_fails_closed(self):
        identity = {"source_sha": HISTORICAL_SOURCE, "artifact_sha": HISTORICAL_ARTIFACT, "website_sha": "c" * 40}
        read = lambda revision, path: subprocess.check_output(["git", "show", f"{revision}:{path}"], cwd=ROOT)
        with self.assertRaisesRegex(GateError, "ALTERED AUTHORITATIVE SOURCE FACTS"):
            assert_local_release_identity(identity, read, lambda source, artifact: True)

    def test_real_historical_tag_object_and_target_match_fixture(self):
        tag_object = subprocess.check_output(["git", "rev-parse", f"refs/tags/{HISTORICAL_TAG}"], cwd=ROOT, text=True).strip()
        target = subprocess.check_output(["git", "rev-parse", f"refs/tags/{HISTORICAL_TAG}^{{commit}}"], cwd=ROOT, text=True).strip()
        self.assertEqual(tag_object, HISTORICAL_TAG_OBJECT)
        self.assertEqual(target, HISTORICAL_ARTIFACT)


class FakeRecoveryBackend(RecoveryBackend):
    def __init__(self, fail=None):
        self.fail = fail
        self.calls = []

    def hit(self, name, value=None):
        self.calls.append(name)
        if self.fail == name:
            raise ReleaseFailure("CI_FAILURE", name, "fixture failure")
        return value

    def verify_plan(self, plan, digest): self.hit("recovery_plan_verified")
    def commit_source(self, plan): return self.hit("recovery_source_committed", S1)
    def generate_artifacts(self, plan, source): self.hit("recovery_artifacts_generated")
    def commit_artifact(self, plan, source): return self.hit("recovery_artifact_committed", S2)
    def verify_website_reuse(self, plan): return self.hit("recovery_website_verified", W1)
    def push_dataset(self, plan, artifact): self.hit("recovery_dataset_pushed")
    def verify_pre_tag(self, plan, digest, source, artifact, website): return self.hit("recovery_pre_tag_verified", recovery_tag_name(plan))
    def push_tag(self, plan, artifact, tag): self.hit("recovery_tag_pushed")
    def verify_ci(self, artifact, website): return self.hit("recovery_validate_verified", [{"url": "ci"}])
    def deploy_pages(self, state, plan): return self.hit("recovery_pages_preflight_verified", {"production_deployed": True, "production_parity_verified": True})
    def verify_website_production(self, plan): self.hit("recovery_website_production_verified")
    def publish_hf(self, state, plan, dry_run): return self.hit("recovery_hf_dry_run_verified" if dry_run else "recovery_hf_publish_verified", {"url": "hf"})
    def verify_hf(self, plan): self.hit("recovery_hf_production_verified")


class RecoveryStateTests(unittest.TestCase):
    def fixture(self, tmp):
        plan = recovery_plan()
        path = Path(tmp) / "plan.json"
        write_json(path, plan)
        return plan, path, plan_digest(path), RecoveryStateStore(Path(tmp), plan["recovery_id"])

    def test_old_or_daily_state_schema_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan, path, digest, store = self.fixture(tmp)
            write_json(store.path, {"schema": "aicostbudget-daily-pricing-release-state-v3", "recovery_id": plan["recovery_id"], "plan_digest": digest, "completed_stages": []})
            with self.assertRaisesRegex(ReleaseFailure, "state schema"):
                publish_recovery(plan, path, digest, store, FakeRecoveryBackend())

    def test_recovery_runs_all_separate_stages_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan, path, digest, store = self.fixture(tmp)
            backend = FakeRecoveryBackend()
            result = publish_recovery(plan, path, digest, store, backend)
            self.assertEqual(result["status"], "PRODUCTION VERIFIED")
            self.assertEqual(len(backend.calls), 14)

    def test_resume_never_repeats_commit_tag_deploy_or_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan, path, digest, store = self.fixture(tmp)
            first = FakeRecoveryBackend("recovery_hf_production_verified")
            with self.assertRaises(ReleaseFailure):
                publish_recovery(plan, path, digest, store, first)
            second = FakeRecoveryBackend()
            publish_recovery(plan, path, digest, store, second)
            self.assertEqual(second.calls, ["recovery_hf_production_verified"])
            for stage in ("recovery_source_committed", "recovery_artifact_committed", "recovery_tag_pushed", "recovery_pages_preflight_verified", "recovery_hf_publish_verified"):
                self.assertNotIn(stage, second.calls)


class RecoveryShellBackendTests(unittest.TestCase):
    def backend(self, tmp):
        plan = recovery_plan()
        path = Path(tmp) / "plan.json"
        website = Path(tmp) / "website"
        website.mkdir()
        write_json(path, plan)
        return plan, RecoveryShellBackend(Path(tmp), website, path, plan_digest(path))

    def test_recovery_generator_preserves_snapshot_fact_time_and_reuses_w1(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan, backend = self.backend(tmp)
            calls = []
            with patch("scripts.forward_recovery.git", return_value=S1), patch("scripts.forward_recovery.ensure_snapshot") as snapshot, patch.object(backend, "_run", side_effect=lambda args, cwd: calls.append(args) or ""):
                backend.generate_artifacts(plan, S1)
            snapshot.assert_called_once_with(backend.root, plan["snapshot_generated_at"])
            flattened = "\n".join(" ".join(call) for call in calls)
            self.assertIn("--generated-at " + plan["snapshot_generated_at"], flattened)
            self.assertIn("--website-ref " + W1, flattened)
            self.assertNotIn(plan["recovery_created_at"], flattened)

    def test_recovery_dispatch_uses_same_exact_identity_inputs_and_recovery_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan, backend = self.backend(tmp)
            state = {"schema": "fixture", "recovery_id": plan["recovery_id"], "plan_digest": "a" * 64, "source_sha": S1, "artifact_sha": S2, "website_sha": W1, "release_tag": recovery_tag_name(plan), "workflow_run_ids": {"deploy-pages.yml:release": 7}}
            with patch.object(backend, "_wait_run_id", return_value={"conclusion": "success"}) as wait:
                backend._dispatch("deploy-pages.yml", state, plan)
            wait.assert_called_once_with(7, "recovery_pages_preflight_verified")

    def test_recovery_existing_tag_is_never_accepted_or_moved(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan, backend = self.backend(tmp)
            with patch("scripts.forward_recovery.git", return_value="existing"), patch.object(backend, "_run", return_value=""):
                with self.assertRaisesRegex(ReleaseFailure, "ALREADY EXISTS"):
                    backend.push_tag(plan, S2, recovery_tag_name(plan))

    def test_recovery_cli_has_no_prepare_or_plan_backfill_path(self):
        source = (ROOT / "scripts/forward_recovery.py").read_text(encoding="utf-8")
        self.assertIn('ArgumentParser(description="Run an explicitly approved forward-only recovery.")', source)
        self.assertNotIn('"prepare-recovery"', source)
        self.assertNotIn('"--force"', source)


if __name__ == "__main__":
    unittest.main()
