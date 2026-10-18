import copy
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.daily_pricing_release import (
    WEBSITE_OUTPUTS,
    ValidationRun,
    classify_changes,
    price_event_changes,
    publish_release,
    validate_release,
    website_business_changed,
)
from scripts.generate_price_change_events import write_events


ROOT = Path(__file__).resolve().parents[1]


def model(model_id="deepseek-flash", *, version="DeepSeek-V4.1-Flash", price=1):
    return {
        "provider_id": "deepseek",
        "model_id": model_id,
        "served_version": version,
        "status": "active",
        "pricing": {"input": price, "output": price * 2, "cached_input": price / 10},
    }


class ChangeClassificationTests(unittest.TestCase):
    def test_metadata_only_version_update_has_no_price_event(self):
        before = [model()]
        after = [model(version="DeepSeek-V4.1-Flash-1017")]
        changes = classify_changes(before, after)
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

    def test_validate_runs_generation_and_validation_pipeline_once_without_remote_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dataset"
            website = Path(tmp) / "website"
            (root / ".git").mkdir(parents=True)
            (root / "data/canonical").mkdir(parents=True)
            (website / ".git").mkdir(parents=True)
            (website / "data").mkdir(parents=True)
            (root / "data/canonical/models.json").write_text(json.dumps([model(version="DeepSeek-V4.1-Flash-1017")]), encoding="utf-8")
            (website / "data/model-pricing.json").write_text("[]", encoding="utf-8")
            canonical_before = (root / "data/canonical/models.json").read_bytes()
            website_before = (website / "data/model-pricing.json").read_bytes()

            @contextmanager
            def workspaces(_root, _website, dataset_ref, website_ref):
                self.assertEqual(dataset_ref, "HEAD")
                self.assertEqual(website_ref, "b" * 40)
                candidate_root = Path(tmp) / "candidate-dataset"
                candidate_website = Path(tmp) / "candidate-website"
                (candidate_root / "data/canonical").mkdir(parents=True)
                (candidate_website / "data").mkdir(parents=True)
                yield candidate_root, candidate_website

            def run_candidate(candidate_root, candidate_website, _generated_at, _changes):
                self.assertNotEqual(candidate_root, root)
                self.assertNotEqual(candidate_website, website)
                self.assertEqual((candidate_root / "data/canonical/models.json").read_bytes(), canonical_before)
                (candidate_root / "generated.json").write_text("generated", encoding="utf-8")
                (candidate_website / "data/generated.json").write_text("generated", encoding="utf-8")
                return ValidationRun(["api/v1/prices.json"], False)

            runner = Mock(side_effect=run_candidate)

            def fake_git(repo, *args, **kwargs):
                if args[0] == "show":
                    return json.dumps([model()])
                if repo == website and args == ("rev-parse", "HEAD"):
                    return "b" * 40
                raise AssertionError(args)

            with patch("scripts.daily_pricing_release.git", side_effect=fake_git):
                report = validate_release(
                    root, website, "2026-10-18T00:00:00Z", runner, workspaces,
                )
            runner.assert_called_once()
            self.assertEqual((root / "data/canonical/models.json").read_bytes(), canonical_before)
            self.assertEqual((website / "data/model-pricing.json").read_bytes(), website_before)
            self.assertFalse((root / "generated.json").exists())
            self.assertFalse((website / "data/generated.json").exists())
            self.assertEqual(report["changes"][0]["change_type"], "metadata")
            self.assertFalse(report["price_change"])
            self.assertTrue(report["ready_for_human_approval"])


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

    def test_publish_generates_from_exact_clean_head_then_pushes_dataset_and_dispatches_hf_once(self):
        root = Path("dataset")
        website = Path("website")
        release_sha = "a" * 40
        website_sha = "b" * 40
        calls = []

        @contextmanager
        def workspaces(_root, _website, dataset_ref, website_ref):
            self.assertEqual((dataset_ref, website_ref), (release_sha, website_sha))
            yield Path("candidate-dataset"), Path("candidate-website")

        def fake_git(repo, *args, **kwargs):
            if args[0] == "status":
                return ""
            if args == ("rev-parse", "HEAD"):
                return release_sha if repo == root else website_sha
            if args[:3] == ("show", "-s", "--format=%cI"):
                return "2026-10-18T00:00:00+00:00"
            if args == ("show", f"{release_sha}^:data/canonical/models.json"):
                return json.dumps([model()])
            if args == ("show", f"{release_sha}:data/canonical/models.json"):
                return json.dumps([model(version="DeepSeek-V4.1-Flash-1017")])
            raise AssertionError((repo, args))

        runner = Mock(return_value=ValidationRun(["api/v1/prices.json"], False))
        dataset_push = Mock(side_effect=lambda repo, sha: calls.append(("dataset", repo, sha)))
        website_push = Mock(side_effect=lambda repo, sha: calls.append(("website", repo, sha)))
        hf_dispatch = Mock(side_effect=lambda repo: calls.append(("hf", repo)))
        with patch("scripts.daily_pricing_release.require_checkout", side_effect=lambda path, _required: path), patch(
            "scripts.daily_pricing_release.git", side_effect=fake_git
        ):
            result = publish_release(
                root, website, runner, workspaces, dataset_push, website_push, hf_dispatch,
            )
        runner.assert_called_once_with(
            Path("candidate-dataset"), Path("candidate-website"),
            "2026-10-18T00:00:00Z", result_changes := runner.call_args.args[3],
        )
        self.assertEqual(result_changes[0]["change_type"], "metadata")
        dataset_push.assert_called_once_with(root, release_sha)
        website_push.assert_not_called()
        hf_dispatch.assert_called_once_with(root)
        self.assertEqual(calls, [("dataset", root, release_sha), ("hf", root)])
        self.assertEqual(result["release_sha"], "a" * 40)
        self.assertEqual(result["website_business_change"], "NO")

    def test_publish_business_change_creates_and_pushes_at_most_one_website_commit(self):
        root = Path("dataset")
        website = Path("website")
        release_sha = "a" * 40
        old_website_sha = "b" * 40
        new_website_sha = "c" * 40
        git_calls = []
        remote_calls = []

        @contextmanager
        def workspaces(*_args):
            yield Path("candidate-dataset"), Path("candidate-website")

        def fake_git(repo, *args, **kwargs):
            git_calls.append((repo, args))
            if args[0] == "status":
                return ""
            if args == ("rev-parse", "HEAD"):
                if repo == root:
                    return release_sha
                return new_website_sha if any(call[1][0] == "commit" for call in git_calls) else old_website_sha
            if args[:3] == ("show", "-s", "--format=%cI"):
                return "2026-10-18T00:00:00+00:00"
            if args == ("show", f"{release_sha}^:data/canonical/models.json"):
                return json.dumps([model()])
            if args == ("show", f"{release_sha}:data/canonical/models.json"):
                return json.dumps([model(version="DeepSeek-V4.1-Flash-1017")])
            if args[0] in {"add", "commit"}:
                return ""
            raise AssertionError((repo, args))

        with patch("scripts.daily_pricing_release.require_checkout", side_effect=lambda path, _required: path), patch(
            "scripts.daily_pricing_release.git", side_effect=fake_git
        ), patch("scripts.daily_pricing_release.command") as run, patch(
            "scripts.daily_pricing_release.changed_paths", return_value=list(WEBSITE_OUTPUTS)
        ):
            result = publish_release(
                root,
                website,
                Mock(return_value=ValidationRun(["api/v1/prices.json"], True)),
                workspaces,
                lambda repo, sha: remote_calls.append(("dataset", repo, sha)),
                lambda repo, sha: remote_calls.append(("website", repo, sha)),
                lambda repo: remote_calls.append(("hf", repo)),
            )
        self.assertEqual(sum(args[0] == "commit" for repo, args in git_calls if repo == website), 1)
        run.assert_called_once()
        self.assertEqual(
            remote_calls,
            [
                ("website", website, new_website_sha),
                ("dataset", root, release_sha),
                ("hf", root),
            ],
        )
        self.assertEqual(result["website_business_change"], "YES")

    def test_ordinary_source_has_no_legacy_state_machine_or_recovery_runtime(self):
        source = (ROOT / "scripts/daily_pricing_release.py").read_text(encoding="utf-8")
        forbidden = (
            "ReleaseStateStore", "STAGES", "source_committed", "artifact_committed",
            "pre_tag_verified", "hf_dry_run_verified", "release_plan_id",
            "release_plan_digest", ".daily-pricing-release", "forward_recovery",
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

    def test_powershell_uses_module_mode_and_only_validate_publish(self):
        source = (ROOT / "scripts/daily-pricing-release.ps1").read_text(encoding="utf-8")
        self.assertIn("python -m scripts.daily_pricing_release", source)
        self.assertNotIn("python scripts/daily_pricing_release.py", source)
        for token in ("-Prepare", "-Resume", "-Plan", "-Digest", "-Recovery"):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
