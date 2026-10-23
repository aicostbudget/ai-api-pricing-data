import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/hf-contract-republish.yml"


class HfContractRepublishWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_runs_only_for_main_pushes_that_touch_hugging_face_artifacts(self):
        self.assertIn("push:\n    branches: [main]\n    paths:\n      - \"huggingface/**\"", self.workflow)
        for trigger in ("pull_request", "schedule:", "workflow_dispatch:"):
            self.assertNotIn(trigger, self.workflow)

    def test_skips_ordinary_release_artifact_commits(self):
        # The release script dispatches Hugging Face itself after pushing these commits.
        self.assertIn("!startsWith(github.event.head_commit.message, 'data: publish pricing artifacts')", self.workflow)

    def test_dispatches_the_single_publisher_only_on_data_drift(self):
        self.assertIn("python scripts/check_hf_production_parity.py", self.workflow)
        self.assertIn("grep -q '^DATA_DRIFT$' parity.log", self.workflow)
        self.assertIn("if: steps.parity.outputs.drift == 'true'", self.workflow)
        self.assertIn("gh workflow run publish-huggingface.yml --ref main -f recovery_mode=false", self.workflow)
        self.assertNotIn("python scripts/publish_huggingface.py", self.workflow)

    def test_network_failure_does_not_republish(self):
        self.assertIn("Parity check failed without a data drift verdict; not republishing.", self.workflow)

    def test_permissions_are_read_plus_dispatch(self):
        self.assertIn("permissions:\n  contents: read\n  actions: write\n", self.workflow)
        self.assertNotIn("contents: write", self.workflow)


if __name__ == "__main__":
    unittest.main()
