import copy
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from functools import partial

from scripts.daily_pricing_release import (
    WEBSITE_OUTPUTS,
    ReleaseFailure,
    SuiteResult,
    ValidationRun,
    classify_changes,
    command,
    ensure_local_main,
    follow_huggingface,
    follow_indexnow,
    follow_release,
    follow_website_live,
    isolated_workspaces,
    prepare_release,
    price_event_changes,
    publish_release,
    rehearse_release,
    run_suite,
    run_validation_pipeline,
    validate_release,
    website_business_changed,
)
from scripts.generate_price_change_events import snapshot_date, write_events
from scripts.lib import latest_snapshot_id_for_date, next_snapshot_id, parse_snapshot_id, snapshot_sort_key
from scripts.prepare_pages_artifact import _latest_snapshot


ROOT = Path(__file__).resolve().parents[1]

# Stand-in for scripts/build.py inside throwaway repositories: writes the snapshot it is told to.
FAKE_BUILD = """
import argparse, json, pathlib
parser = argparse.ArgumentParser()
parser.add_argument("--generated-at")
parser.add_argument("--snapshot-id")
args = parser.parse_args()
models = json.loads(pathlib.Path("data/canonical/models.json").read_text(encoding="utf-8"))
body = json.dumps({"generated_at": args.generated_at, "models": models}, sort_keys=True) + "\\n"
for target in (pathlib.Path("data/snapshots") / args.snapshot_id, pathlib.Path("api/v1")):
    target.mkdir(parents=True, exist_ok=True)
    (target / "prices.json").write_text(body, encoding="utf-8")
"""


def model(model_id="deepseek-flash", *, version="DeepSeek-V4.1-Flash", price=1):
    return {
        "provider_id": "deepseek",
        "model_id": model_id,
        "served_version": version,
        "status": "active",
        "pricing": {"input": price, "output": price * 2, "cached_input": price / 10},
    }


def canonical_json(rows):
    """The canonical file's one normalized serialization (scripts/format_canonical.py)."""
    return json.dumps(rows, indent=2, ensure_ascii=False) + "\n"


def run(repo, *args, env=None):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=env).stdout.strip()


def make_dataset_repo(base: Path, existing_snapshots=("2026-10-18",)) -> Path:
    repo = base / "dataset"
    (repo / "data/canonical").mkdir(parents=True)
    (repo / "scripts").mkdir()
    (repo / "scripts/build.py").write_text(FAKE_BUILD, encoding="utf-8")
    (repo / "data/canonical/models.json").write_text(canonical_json([model()]), encoding="utf-8")
    for snapshot in existing_snapshots:
        (repo / "data/snapshots" / snapshot).mkdir(parents=True)
        (repo / "data/snapshots" / snapshot / "prices.json").write_text(f'{{"snapshot": "{snapshot}"}}\n', encoding="utf-8")
    run(repo, "init", "-q", "-b", "main")
    run(repo, "config", "user.name", "test")
    run(repo, "config", "user.email", "test@example.com")
    run(repo, "add", "-A")
    run(repo, "commit", "-q", "-m", "base")
    return repo


def make_website_repo(base: Path) -> Path:
    repo = base / "website"
    (repo / "data").mkdir(parents=True)
    (repo / "data/model-pricing.json").write_text("[]", encoding="utf-8")
    run(repo, "init", "-q", "-b", "main")
    run(repo, "config", "user.name", "test")
    run(repo, "config", "user.email", "test@example.com")
    run(repo, "add", "-A")
    run(repo, "commit", "-q", "-m", "base")
    return repo


def fake_runner(dataset, _website, generated_at, _changes):
    """Deterministic stand-in for the generation pipeline: one artifact derived from the source commit."""
    snapshot = run(dataset, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD", "--", "data/snapshots")
    (dataset / "api/v1").mkdir(parents=True, exist_ok=True)
    (dataset / "api/v1/meta.json").write_text(json.dumps({"generated_at": generated_at, "snapshot": snapshot}) + "\n", encoding="utf-8")
    (dataset / "api/v1/prices.json").write_bytes((dataset / snapshot.splitlines()[0]).read_bytes())
    paths = sorted(filter(None, run(dataset, "status", "--porcelain=v1", "--untracked-files=all").replace("?? ", "").replace(" M ", "").splitlines()))
    return ValidationRun([path.strip() for path in paths], False)


class SnapshotIdTests(unittest.TestCase):
    def test_first_release_of_a_day_keeps_the_plain_date(self):
        self.assertEqual(next_snapshot_id(["2026-10-18"], "2026-10-21"), "2026-10-21")

    def test_later_same_day_releases_add_a_sequence(self):
        self.assertEqual(next_snapshot_id(["2026-10-18", "2026-10-21"], "2026-10-21"), "2026-10-21-2")
        self.assertEqual(next_snapshot_id(["2026-10-21", "2026-10-21-2"], "2026-10-21"), "2026-10-21-3")
        self.assertEqual(latest_snapshot_id_for_date(["2026-10-21", "2026-10-21-10", "2026-10-21-2"], "2026-10-21"), "2026-10-21-10")

    def test_order_is_date_then_sequence(self):
        ids = ["2026-10-21-2", "2026-10-22", "2026-10-21", "2026-10-21-10"]
        self.assertEqual(sorted(ids, key=snapshot_sort_key), ["2026-10-21", "2026-10-21-2", "2026-10-21-10", "2026-10-22"])

    def test_invalid_ids_are_rejected(self):
        for invalid in ("2026-10-21-1", "2026-10-21-01", "2026-10-21-x", "2026-13-01", "latest", "2026-10-21-0"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_snapshot_id(invalid)

    def test_event_detected_date_is_the_date_part_and_same_day_order_is_valid(self):
        self.assertEqual(snapshot_date(Path("data/snapshots/2026-10-21-2/prices.json")), "2026-10-21")
        self.assertLess(snapshot_sort_key("2026-10-21"), snapshot_sort_key("2026-10-21-2"))

    def test_pages_check_uses_the_latest_snapshot_of_the_api_date(self):
        self.assertEqual(_latest_snapshot(["2026-10-18", "2026-10-21", "2026-10-21-2"], "2026-10-21"), "2026-10-21-2")
        with self.assertRaises(FileNotFoundError):
            _latest_snapshot(["2026-10-18"], "2026-10-21")


class ChangeClassificationTests(unittest.TestCase):
    def test_metadata_only_version_update_has_no_price_event(self):
        changes = classify_changes([model()], [model(version="DeepSeek-V4.1-Flash-1017")])
        self.assertEqual(changes[0]["change_type"], "metadata")
        self.assertFalse(changes[0]["price_change"])
        self.assertEqual(price_event_changes(changes), [])

    def test_real_price_change_is_pricing_and_event_eligible(self):
        changes = classify_changes([model(price=1)], [model(price=2)])
        self.assertEqual(changes[0]["change_type"], "pricing")
        self.assertTrue(changes[0]["price_change"])
        self.assertEqual(price_event_changes(changes), changes)

    def test_new_model_is_added(self):
        changes = classify_changes([], [model("new-model")])
        self.assertEqual(changes[0]["change_type"], "added")
        self.assertFalse(changes[0]["price_change"])


class CommandReportingTests(unittest.TestCase):
    def test_failing_step_reports_its_own_error_even_with_undecodable_output(self):
        script = "import sys; sys.stdout.buffer.write(b'\\xb2\\xe2\\xca\\xd4'); sys.stderr.write('real failure'); sys.exit(3)"
        with self.assertRaises(ReleaseFailure) as raised:
            command([sys.executable, "-c", script], ROOT)
        self.assertEqual(str(raised.exception), "real failure")

    def test_failing_step_without_output_still_names_the_step(self):
        with self.assertRaises(ReleaseFailure) as raised:
            command([sys.executable, "-c", "import sys; sys.exit(2)"], ROOT, stage="publish")
        self.assertIn("exited with 2", str(raised.exception))
        self.assertEqual(raised.exception.stage, "publish")


class TwoCommitReleaseTests(unittest.TestCase):
    def prepare(self, base: Path, existing=("2026-10-18",), generated_at="2026-10-21T16:35:00Z", price=2):
        dataset = make_dataset_repo(base, existing)
        website = make_website_repo(base)
        (dataset / "data/canonical/models.json").write_text(canonical_json([model(price=price)]), encoding="utf-8")
        report = prepare_release(dataset, website, generated_at, fake_runner, isolated_workspaces)
        return dataset, website, report

    def test_prepare_makes_a_dated_source_commit_then_an_artifact_commit_without_pushing(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset, website, report = self.prepare(Path(tmp))
            source, artifact = report["source_sha"], report["artifact_sha"]
            self.assertEqual(run(dataset, "rev-parse", "HEAD"), artifact)
            self.assertEqual(run(dataset, "rev-parse", "HEAD^"), source)
            self.assertEqual(
                sorted(run(dataset, "diff-tree", "--no-commit-id", "--name-only", "-r", source).splitlines()),
                ["data/canonical/models.json", "data/snapshots/2026-10-21/prices.json"],
            )
            self.assertIn(run(dataset, "show", "-s", "--format=%cI", source), {"2026-10-21T16:35:00Z", "2026-10-21T16:35:00+00:00"})
            artifact_paths = run(dataset, "diff-tree", "--no-commit-id", "--name-only", "-r", artifact).splitlines()
            self.assertNotIn("data/canonical/models.json", artifact_paths)
            self.assertIn("api/v1/prices.json", artifact_paths)
            self.assertEqual(run(dataset, "status", "--porcelain"), "")
            self.assertEqual(report["snapshot_id"], "2026-10-21")
            self.assertEqual(report["status"], "PREPARED")
            self.assertEqual(run(website, "log", "--oneline").count("\n"), 0, "prepare never commits to the website")

    def test_second_release_on_the_same_utc_day_gets_a_new_snapshot_and_keeps_the_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset, _website, report = self.prepare(Path(tmp), existing=("2026-10-18", "2026-10-21"), generated_at="2026-10-21T17:20:00Z")
            self.assertEqual(report["snapshot_id"], "2026-10-21-2")
            self.assertEqual((dataset / "data/snapshots/2026-10-21/prices.json").read_text(encoding="utf-8"), '{"snapshot": "2026-10-21"}\n')
            self.assertEqual(run(dataset, "diff", "HEAD~2", "HEAD", "--name-only", "--", "data/snapshots/2026-10-21"), "")
            self.assertTrue((dataset / "data/snapshots/2026-10-21-2/prices.json").is_file())

    def test_prepare_refuses_anything_but_a_canonical_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = make_dataset_repo(Path(tmp))
            website = make_website_repo(Path(tmp))
            with self.assertRaisesRegex(ReleaseFailure, "Only data/canonical/models.json"):
                prepare_release(dataset, website, "2026-10-21T16:35:00Z", fake_runner, isolated_workspaces)
            (dataset / "data/canonical/models.json").write_text(canonical_json([model(price=2)]), encoding="utf-8")
            (dataset / "stray.txt").write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(ReleaseFailure, "Only data/canonical/models.json"):
                prepare_release(dataset, website, "2026-10-21T16:35:00Z", fake_runner, isolated_workspaces)

    def test_pending_price_evidence_is_allowed_and_left_out_of_the_artifact_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = make_dataset_repo(Path(tmp))
            website = make_website_repo(Path(tmp))
            (dataset / "data/canonical/models.json").write_text(canonical_json([model(price=2)]), encoding="utf-8")
            evidence = dataset / "reports/price-evidence/deepseek/deepseek-flash/20261021T160000Z.json"
            evidence.parent.mkdir(parents=True)
            evidence.write_text('{"pages": []}\n', encoding="utf-8")

            report = prepare_release(dataset, website, "2026-10-21T16:35:00Z", fake_runner, isolated_workspaces)

            committed = run(dataset, "diff-tree", "--no-commit-id", "--name-only", "-r", report["artifact_sha"]).splitlines()
            self.assertNotIn("reports/price-evidence/deepseek/deepseek-flash/20261021T160000Z.json", committed)
            self.assertTrue(evidence.is_file(), "evidence stays for the reviewer to amend in")
            self.assertEqual(run(dataset, "status", "--porcelain"), "?? reports/")

    def test_release_refuses_a_canonical_file_that_is_not_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = make_dataset_repo(Path(tmp))
            website = make_website_repo(Path(tmp))
            (dataset / "data/canonical/models.json").write_text(json.dumps([model(price=2)]), encoding="utf-8")
            with self.assertRaisesRegex(ReleaseFailure, "format_canonical.py"):
                validate_release(dataset, website, "2026-10-21T16:35:00Z", fake_runner, isolated_workspaces)

    def test_validate_is_a_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = make_dataset_repo(Path(tmp))
            website = make_website_repo(Path(tmp))
            (dataset / "data/canonical/models.json").write_text(canonical_json([model(price=2)]), encoding="utf-8")
            head = run(dataset, "rev-parse", "HEAD")
            report = validate_release(dataset, website, "2026-10-21T16:35:00Z", fake_runner, isolated_workspaces)
            self.assertEqual(report["snapshot_id"], "2026-10-21")
            self.assertTrue(report["price_change"])
            self.assertEqual(run(dataset, "rev-parse", "HEAD"), head)
            self.assertEqual(run(dataset, "status", "--porcelain"), "M data/canonical/models.json")
            self.assertFalse((dataset / "data/snapshots/2026-10-21").exists())

    def test_publish_regenerates_from_the_source_commit_then_pushes_dataset_and_dispatches_hf(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset, website, report = self.prepare(Path(tmp))
            calls = []
            result = publish_release(
                dataset, website, fake_runner, isolated_workspaces,
                lambda repo, sha: calls.append(("dataset", sha)),
                lambda repo, sha: calls.append(("website", sha)),
                lambda repo: calls.append(("hf",)),
            )
            self.assertEqual(calls, [("dataset", report["artifact_sha"]), ("hf",)])
            self.assertEqual(result["source_sha"], report["source_sha"])
            self.assertEqual(result["snapshot_id"], "2026-10-21")
            self.assertEqual(result["website_business_change"], "NO")
            self.assertEqual(result["next_step"], "NONE")

    def test_publish_refuses_an_artifact_commit_that_differs_from_regeneration(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset, website, _report = self.prepare(Path(tmp))
            (dataset / "api/v1/prices.json").write_text('{"tampered": true}\n', encoding="utf-8")
            run(dataset, "commit", "-q", "--amend", "-a", "--no-edit")
            push = Mock()
            with self.assertRaisesRegex(ReleaseFailure, "Artifact commit differs from regenerated output: api/v1/prices.json"):
                publish_release(dataset, website, fake_runner, isolated_workspaces, push, push, push)
            push.assert_not_called()

    def test_publish_refuses_canonical_changes_in_the_artifact_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset, website, _report = self.prepare(Path(tmp))
            (dataset / "data/canonical/models.json").write_text(canonical_json([model(price=3)]), encoding="utf-8")
            run(dataset, "commit", "-q", "--amend", "-a", "--no-edit")
            with self.assertRaisesRegex(ReleaseFailure, "must not change canonical data"):
                publish_release(dataset, website, fake_runner, isolated_workspaces, Mock(), Mock(), Mock())


class StabilityAndFlowTests(unittest.TestCase):
    def test_event_jsonl_is_lf_only_and_byte_stable(self):
        events = [{"event_id": "b", "value": 2}, {"event_id": "a", "value": 1}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            write_events(events, path)
            first = path.read_bytes()
            write_events(copy.deepcopy(events), path)
            second = path.read_bytes()
        self.assertEqual(first, second)
        self.assertNotIn(b"\r\n", first)
        self.assertTrue(first.endswith(b"\n"))

    def test_timestamp_and_newline_only_website_change_is_not_business_change(self):
        before = b'{"generatedAt":"old","records":[{"id":"x"}]}\r\n'
        after = b'{"generatedAt":"new","records":[{"id":"x"}]}\n'
        self.assertFalse(website_business_changed(before, after))
        self.assertTrue(website_business_changed(before, b'{"records":[{"id":"y"}]}\n'))

    def test_publish_business_change_creates_and_pushes_one_website_commit_before_dataset_and_hf(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset, website, report = TwoCommitReleaseTests().prepare(Path(tmp))
            remote_calls = []

            def business_runner(*args):
                return ValidationRun(fake_runner(*args).generated_files, True)

            def fake_sync(args, cwd, env=None, stage="validate"):
                if args[:2] == ["node", "scripts/sync-pricing-artifacts.mjs"]:
                    for path in WEBSITE_OUTPUTS:
                        (website / path).parent.mkdir(parents=True, exist_ok=True)
                        (website / path).write_text("{}\n", encoding="utf-8")
                    return ""
                return command(args, cwd, env, stage)

            with patch("scripts.daily_pricing_release.command", side_effect=fake_sync):
                result = publish_release(
                    dataset, website, business_runner, isolated_workspaces,
                    lambda repo, sha: remote_calls.append(("dataset", sha)),
                    lambda repo, sha: remote_calls.append(("website", sha)),
                    lambda repo: remote_calls.append(("hf",)),
                )
            website_head = run(website, "rev-parse", "HEAD")
            self.assertEqual(run(website, "rev-list", "--count", "HEAD"), "2")
            self.assertEqual(remote_calls, [("website", website_head), ("dataset", report["artifact_sha"]), ("hf",)])
            self.assertEqual(result["website_business_change"], "YES")
            self.assertIn(f"npm.cmd run indexnow:pricing -- --commit {website_head}", result["next_step"])
            self.assertIn("--send once approved", result["next_step"])

    def test_ordinary_source_has_no_resumable_state_machine_or_recovery_runtime(self):
        source = (ROOT / "scripts/daily_pricing_release.py").read_text(encoding="utf-8")
        forbidden = (
            "ReleaseStateStore", "STAGES", "pre_tag_verified", "hf_dry_run_verified",
            "release_plan_id", "release_plan_digest", ".daily-pricing-release", "forward_recovery",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, source)

    def test_recovery_runtime_belongs_only_to_forward_recovery(self):
        daily = (ROOT / "scripts/daily_pricing_release.py").read_text(encoding="utf-8")
        recovery = (ROOT / "scripts/forward_recovery.py").read_text(encoding="utf-8")
        for symbol in ("RecoveryStateStore", "RecoveryBackend", "RecoveryShellBackend", "publish_recovery"):
            self.assertNotIn(symbol, daily)
            self.assertIn(symbol, recovery)
        self.assertNotIn("daily_pricing_release", recovery)

    def test_powershell_uses_module_mode_and_only_validate_prepare_publish(self):
        source = (ROOT / "scripts/daily-pricing-release.ps1").read_text(encoding="utf-8")
        self.assertIn("python -m scripts.daily_pricing_release", source)
        self.assertNotIn("python scripts/daily_pricing_release.py", source)
        for token in ("$Validate", "$Prepare", "$Publish", "$Rehearse"):
            self.assertIn(token, source)
        for token in ("-Resume", "-Plan", "-Digest", "-Recovery"):
            self.assertNotIn(token, source)


class RehearsalTests(unittest.TestCase):
    def prepared(self, base: Path):
        dataset, website, report = TwoCommitReleaseTests().prepare(base)
        (website / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
        run(website, "add", ".gitignore")
        run(website, "commit", "-q", "-m", "ignore dependencies")
        dependencies = website / "node_modules"
        (dependencies / "pkg").mkdir(parents=True)
        (dependencies / "pkg/index.js").write_text("keep\n", encoding="utf-8")
        return dataset, website, report, dependencies

    def test_rehearsal_publishes_into_clones_and_tests_the_synced_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset, website, report, dependencies = self.prepared(Path(tmp))
            heads = (run(dataset, "rev-parse", "HEAD"), run(website, "rev-parse", "HEAD"))
            seen = {}

            def suites(dataset_clone, website_clone):
                seen["clones"] = (dataset_clone, website_clone)
                seen["dataset_head"] = run(dataset_clone, "rev-parse", "HEAD")
                seen["shared"] = (website_clone / "node_modules/pkg/index.js").read_text(encoding="utf-8")
                return [SuiteResult("website test:all", True, "ok"), SuiteResult("dataset unittest", True, "ok")]

            result = rehearse_release(dataset, website, partial(publish_release, runner=fake_runner), suites)
            self.assertEqual(result["status"], "REHEARSAL PASS")
            self.assertEqual(result["push_order"], ["dataset", "hf"])
            self.assertEqual(result["release_sha"], report["artifact_sha"])
            self.assertEqual(seen["dataset_head"], report["artifact_sha"])
            self.assertEqual(seen["shared"], "keep\n")
            self.assertNotIn(dataset, seen["clones"])
            self.assertEqual((run(dataset, "rev-parse", "HEAD"), run(website, "rev-parse", "HEAD")), heads)
            self.assertEqual(run(website, "status", "--porcelain"), "")
            self.assertFalse(seen["clones"][1].exists(), "throwaway clones are removed")
            self.assertEqual((dependencies / "pkg/index.js").read_text(encoding="utf-8"), "keep\n")

    def test_suite_keeps_the_full_log_and_reports_the_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = "import sys\nfor i in range(40): print(f'line {i}')\nsys.exit(1)"
            result = run_suite("website test:all", [sys.executable, "-c", script], Path(tmp), {}, Path(tmp) / "logs")
            self.assertFalse(result.passed)
            self.assertEqual(len(result.output_tail.splitlines()), 25)
            self.assertTrue(result.output_tail.endswith("line 39"))
            log = Path(result.log_path)
            self.assertEqual(log.name, "website-test-all.log")
            self.assertEqual(len(log.read_text(encoding="utf-8").splitlines()), 40)

    def test_failing_suite_fails_the_rehearsal_and_keeps_the_real_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset, website, _report, dependencies = self.prepared(Path(tmp))
            result = rehearse_release(
                dataset, website, partial(publish_release, runner=fake_runner),
                lambda *_: [SuiteResult("website test:all", False, "1 unexpected failure")],
            )
            self.assertEqual(result["status"], "REHEARSAL FAIL")
            self.assertEqual(result["suites"][0]["output_tail"], "1 unexpected failure")
            self.assertEqual((dependencies / "pkg/index.js").read_text(encoding="utf-8"), "keep\n")

    def test_clone_of_a_feature_branch_gets_a_local_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            website = make_website_repo(base)
            main_sha = run(website, "rev-parse", "HEAD")
            run(website, "switch", "-q", "-c", "feature")
            (website / "data/model-pricing.json").write_text("[1]", encoding="utf-8")
            run(website, "commit", "-q", "-am", "feature")
            direct = base / "direct"
            run(base, "clone", "-q", str(website), str(direct))
            ensure_local_main(direct)
            self.assertEqual(run(direct, "rev-parse", "main"), main_sha)
            # A clone of such a clone has no origin/main; main comes from the source's origin/main.
            run(direct, "branch", "-D", "main")
            nested = base / "nested"
            run(base, "clone", "-q", str(direct), str(nested))
            ensure_local_main(nested)
            self.assertEqual(run(nested, "rev-parse", "main"), main_sha)

    def test_rehearsal_refuses_a_dirty_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset, website, _report, _dependencies = self.prepared(Path(tmp))
            (website / "stray.txt").write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(ReleaseFailure, "Website checkout must be clean"):
                rehearse_release(dataset, website, partial(publish_release, runner=fake_runner), Mock())

    def test_rehearsal_rejects_a_publish_that_pushes_the_dataset_before_the_website(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset, website, report, _dependencies = self.prepared(Path(tmp))

            def wrong_order(_dataset, _website, dataset_push, website_push, hf_dispatch):
                dataset_push(_dataset, "sha")
                website_push(_website, "sha")
                hf_dispatch(_dataset)
                return {"release_sha": report["artifact_sha"], "source_sha": report["source_sha"],
                        "snapshot_id": report["snapshot_id"], "website_business_change": "YES"}

            with self.assertRaisesRegex(ReleaseFailure, "Publish order"):
                rehearse_release(dataset, website, wrong_order, run_tests=False)


class PipelineOrderTests(unittest.TestCase):
    def test_api_meta_is_rewritten_after_the_identity_registry_is_regenerated(self):
        # build.py reads model-identity-registry.json, which the Pricing V2 generator updates
        # afterwards; without the rewrite new models reach modelAccess one release late.
        with tempfile.TemporaryDirectory() as tmp:
            dataset, website, report = TwoCommitReleaseTests().prepare(Path(tmp))
            run(dataset, "checkout", "-q", "--detach", report["source_sha"])
            steps = []

            def record(args, cwd, env=None, stage="validate"):
                steps.append(" ".join(Path(part).name if part.endswith(".py") or part.endswith(".mjs") else part for part in args[1:3]))
                return ""

            with patch("scripts.daily_pricing_release.command", side_effect=record):
                run_validation_pipeline(dataset, website, "2026-10-21T16:35:00Z", [{"change_type": "added"}])
            generator = steps.index("generate_pricing_v2_preview.py")
            meta = next(index for index, step in enumerate(steps) if step == "build.py --generated-at" and index > generator)
            sync = steps.index("sync-pricing-artifacts.mjs --write")
            self.assertLess(generator, meta)
            self.assertLess(meta, sync)


class FollowTests(unittest.TestCase):
    RELEASE = "a" * 40
    WEBSITE = "b" * 40

    def report(self, business="YES"):
        return {"release_sha": self.RELEASE, "source_sha": "c" * 40, "snapshot_id": "2026-10-23",
                "website_sha": self.WEBSITE, "website_business_change": business, "status": "PUBLISH STARTED"}

    def test_website_live_reads_the_verify_live_verdict(self):
        calls = []

        def run(args, cwd):
            calls.append(args)
            return 0, f'{{"target":"{self.WEBSITE}","live":"{self.WEBSITE}","state":"live"}}'

        result = follow_website_live(ROOT, self.WEBSITE, run)
        self.assertEqual(result, {"passed": True, "state": "live", "live_commit": self.WEBSITE})
        self.assertEqual(calls[0], ["node", "scripts/verify-live-deploy.mjs", "--commit", self.WEBSITE, "--wait", "900"])

    def test_huggingface_waits_for_the_release_run_and_requires_parity(self):
        listed = json.dumps([{"databaseId": 7, "headSha": "f" * 40}, {"databaseId": 9, "headSha": self.RELEASE}])
        outputs = iter([(0, "[]"), (0, listed), (0, ""), (0, "HF_PUSHED: 469ac60\nBUSINESS_PARITY: PASS\n")])
        sleeps = []
        result = follow_huggingface(ROOT, self.RELEASE, lambda args, cwd: next(outputs), sleeps.append)
        self.assertEqual(result, {"passed": True, "run_id": 9, "parity": "PASS", "hf_commit": "469ac60"})
        self.assertEqual(sleeps, [10], "polls until the dispatched run appears")

    def test_huggingface_without_a_run_or_parity_fails(self):
        missing = follow_huggingface(ROOT, self.RELEASE, lambda args, cwd: (0, "[]"), lambda _s: None, attempts=2)
        self.assertFalse(missing["passed"])
        listed = json.dumps([{"databaseId": 9, "headSha": self.RELEASE}])
        outputs = iter([(0, listed), (1, "failed"), (0, "DATA_DRIFT")])
        failed = follow_huggingface(ROOT, self.RELEASE, lambda args, cwd: next(outputs), lambda _s: None)
        self.assertEqual((failed["passed"], failed["parity"]), (False, "FAIL"))

    def test_indexnow_is_only_a_dry_run(self):
        calls = []
        payload = '{\n  "urlList": [\n    "https://aicostbudget.com/en/models",\n    "https://aicostbudget.com/en/providers/mistral-ai-api-pricing"\n  ]\n}\nDry run: 2 URLs.'

        def run(args, cwd):
            calls.append(args)
            return 0, payload

        result = follow_indexnow(ROOT, self.WEBSITE, run)
        self.assertNotIn("--send", calls[0])
        self.assertIn("--wait-live", calls[0])
        self.assertEqual(result["dry_run_urls"], ["https://aicostbudget.com/en/models", "https://aicostbudget.com/en/providers/mistral-ai-api-pricing"])
        self.assertTrue(result["send"].endswith(f"--commit {self.WEBSITE} --send"))

    def test_follow_orders_steps_and_reports_status(self):
        order = []
        ok = lambda name: (lambda *_: order.append(name) or {"passed": True})
        result = follow_release(ROOT, ROOT, self.report(), ok("website"), ok("hf"), ok("indexnow"))
        self.assertEqual(order, ["website", "hf", "indexnow"])
        self.assertEqual(result["status"], "PUBLISHED AND VERIFIED")

        order.clear()
        no_site = follow_release(ROOT, ROOT, self.report("NO"), ok("website"), ok("hf"), ok("indexnow"))
        self.assertEqual(order, ["hf"])
        self.assertEqual(no_site["status"], "PUBLISHED AND VERIFIED")

        down = follow_release(ROOT, ROOT, self.report(), lambda *_: {"passed": False}, ok("hf"), ok("indexnow"))
        self.assertNotIn("indexnow", down["follow"], "no IndexNow before the Website is live")
        self.assertEqual(down["status"], "PUBLISHED, FOLLOW-UP NEEDS ATTENTION")


if __name__ == "__main__":
    unittest.main()
