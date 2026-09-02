import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def workflow_text(name):
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def child_mapping_keys(text, parent):
    lines = text.splitlines()
    parent_index = next(
        index for index, line in enumerate(lines) if line == f"{parent}:"
    )
    keys = set()
    for line in lines[parent_index + 1 :]:
        if line and not line.startswith(" "):
            break
        match = re.match(r"^  ([A-Za-z0-9_-]+):(?:\s|$)", line)
        if match:
            keys.add(match.group(1))
    return keys


class CiOrchestrationContractTests(unittest.TestCase):
    def test_validate_is_push_and_pull_request_local_ci(self):
        workflow = workflow_text("validate.yml")
        self.assertEqual(child_mapping_keys(workflow, "on"), {"push", "pull_request"})
        self.assertIn("python scripts/build.py", workflow)
        self.assertIn("python scripts/validate.py", workflow)
        self.assertIn("python -m unittest discover -s tests", workflow)
        self.assertNotIn("export_huggingface.py --website-repo", workflow)
        self.assertIn("github.event.pull_request.head.repo.full_name == github.repository", workflow)
        self.assertIn("github.actor != 'dependabot[bot]'", workflow)

    def test_website_parity_is_an_explicit_release_check(self):
        workflow = workflow_text("website-pricing-parity.yml")
        self.assertEqual(child_mapping_keys(workflow, "on"), {"workflow_dispatch"})
        self.assertIn("repository: linqiang-max/aicostbudget", workflow)
        self.assertIn("ref: main", workflow)
        self.assertIn("export_huggingface.py --website-repo", workflow)
        self.assertNotIn("continue-on-error", workflow)

    def test_hf_production_parity_does_not_run_on_dataset_push(self):
        workflow = workflow_text("hf-production-parity.yml")
        self.assertEqual(
            child_mapping_keys(workflow, "on"),
            {"schedule", "workflow_dispatch"},
        )
        self.assertIn("python scripts/check_hf_production_parity.py", workflow)
        self.assertNotIn("continue-on-error", workflow)

    def test_scheduled_hf_parity_retains_known_release_window_alert(self):
        workflow = workflow_text("hf-production-parity.yml")
        self.assertIn("schedule:", workflow)
        self.assertIn("python scripts/check_hf_production_parity.py", workflow)
        self.assertNotIn("--expected-dir", workflow)


    def test_hf_publish_remains_manual_and_enforces_post_publish_parity(self):
        workflow = workflow_text("publish-huggingface.yml")
        self.assertEqual(child_mapping_keys(workflow, "on"), {"workflow_dispatch"})
        publish_index = workflow.index("python scripts/publish_huggingface.py")
        parity_index = workflow.index("python scripts/check_hf_production_parity.py")
        success_index = workflow.index('echo "PUBLISH_SUCCESS"')
        self.assertLess(publish_index, parity_index)
        self.assertLess(parity_index, success_index)
        self.assertNotIn("continue-on-error", workflow)

    def test_freshness_permissions_and_triggers_remain_contained(self):
        workflow = workflow_text("freshness-check.yml")
        self.assertEqual(
            child_mapping_keys(workflow, "on"),
            {"schedule", "workflow_dispatch"},
        )
        self.assertEqual(
            child_mapping_keys(workflow, "permissions"),
            {"contents", "issues"},
        )
        self.assertIn("contents: read", workflow)
        self.assertIn("issues: write", workflow)

    def test_no_workflow_automatically_publishes_hugging_face(self):
        publisher = workflow_text("publish-huggingface.yml")
        for path in WORKFLOWS.glob("*.yml"):
            workflow = path.read_text(encoding="utf-8")
            if path.name == "publish-huggingface.yml":
                self.assertEqual(workflow, publisher)
                continue
            self.assertNotIn("python scripts/publish_huggingface.py", workflow)


if __name__ == "__main__":
    unittest.main()
