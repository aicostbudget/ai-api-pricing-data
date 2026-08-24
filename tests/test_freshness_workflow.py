import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / ".github" / "scripts" / "freshness-issue-lifecycle.js"
WORKFLOW = ROOT / ".github" / "workflows" / "freshness-check.yml"
VALIDATE_WORKFLOW = ROOT / ".github" / "workflows" / "validate.yml"
DEPLOY_PAGES_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-pages.yml"
TITLE = "Freshness check needs review"
MARKER = "<!-- aicostbudget:freshness-check-managed -->"

OLD_ACTIONS = (
    "actions/checkout@v4",
    "actions/setup-python@v5",
    "actions/upload-artifact@v4",
    "actions/github-script@v7",
    "actions/configure-pages@v5",
    "actions/upload-pages-artifact@v3",
    "actions/deploy-pages@v4",
)

NODE_SCENARIO = r"""
const helper = require(process.argv[1]);
const input = JSON.parse(process.argv[2]);
const calls = [];
const github = {
  paginate: async (_method, params) => {
    calls.push({ op: "paginate", params });
    return input.issues;
  },
  rest: {
    issues: {
      listForRepo: function listForRepo() {},
      create: async (params) => {
        calls.push({ op: "create", params });
        return { data: { number: input.createdNumber || 999 } };
      },
      update: async (params) => {
        calls.push({ op: "update", params });
        return { data: {} };
      },
    },
  },
};
helper.manageFreshnessIssue({
  github,
  context: { repo: { owner: "owner", repo: "repo" } },
  reportBody: input.reportBody,
  freshnessFailed: input.freshnessFailed,
}).then((result) => {
  process.stdout.write(JSON.stringify({ result, calls }));
}).catch((error) => {
  console.error(error);
  process.exit(1);
});
"""


def issue(number, *, managed=True, state="open", title=TITLE, body=None):
    if body is None:
        body = f"{MARKER}\n\n# Freshness Report" if managed else "human-authored body"
    return {"number": number, "state": state, "title": title, "body": body}


class FreshnessWorkflowTests(unittest.TestCase):
    def run_scenario(
        self,
        *,
        freshness_failed,
        issues,
        report_body="# Freshness Report\n\nlatest",
    ):
        payload = json.dumps(
            {
                "freshnessFailed": freshness_failed,
                "issues": issues,
                "reportBody": report_body,
                "createdNumber": 42,
            }
        )
        completed = subprocess.run(
            ["node", "-e", NODE_SCENARIO, str(HELPER), payload],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def test_failure_without_managed_issue_creates_one(self):
        result = self.run_scenario(freshness_failed=True, issues=[])
        self.assertEqual(result["result"]["action"], "create")
        self.assertEqual(result["result"]["canonicalIssueNumber"], 42)
        creates = [call for call in result["calls"] if call["op"] == "create"]
        self.assertEqual(len(creates), 1)
        self.assertEqual(creates[0]["params"]["title"], TITLE)
        self.assertIn(MARKER, creates[0]["params"]["body"])

    def test_failure_with_managed_issue_updates_same_issue(self):
        result = self.run_scenario(freshness_failed=True, issues=[issue(11)])
        self.assertEqual(result["result"]["action"], "update")
        self.assertEqual(result["result"]["canonicalIssueNumber"], 11)
        self.assertFalse(any(call["op"] == "create" for call in result["calls"]))
        updates = [call for call in result["calls"] if call["op"] == "update"]
        self.assertEqual(updates[0]["params"]["issue_number"], 11)
        self.assertIn(MARKER, updates[0]["params"]["body"])

    def test_success_closes_existing_managed_issue_as_completed(self):
        result = self.run_scenario(freshness_failed=False, issues=[issue(11)])
        self.assertEqual(result["result"]["action"], "none")
        updates = [call for call in result["calls"] if call["op"] == "update"]
        self.assertEqual(updates[0]["params"]["issue_number"], 11)
        self.assertEqual(updates[0]["params"]["state"], "closed")
        self.assertEqual(updates[0]["params"]["state_reason"], "completed")

    def test_success_ignores_manual_issue_with_same_title(self):
        result = self.run_scenario(
            freshness_failed=False,
            issues=[issue(17, managed=False)],
        )
        self.assertEqual([call["op"] for call in result["calls"]], ["paginate"])

    def test_failure_keeps_lowest_managed_issue_and_closes_duplicates(self):
        result = self.run_scenario(
            freshness_failed=True,
            issues=[issue(12), issue(9), issue(15, managed=False)],
        )
        self.assertEqual(result["result"]["canonicalIssueNumber"], 9)
        self.assertEqual(result["result"]["closeIssueNumbers"], [12])
        updates = [
            call["params"] for call in result["calls"] if call["op"] == "update"
        ]
        self.assertEqual(updates[0]["issue_number"], 9)
        self.assertEqual(updates[1]["issue_number"], 12)
        self.assertEqual(updates[1]["state_reason"], "completed")

    def test_workflow_contract_is_preserved(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        helper = HELPER.read_text(encoding="utf-8")
        self.assertIn("contents: read", workflow)
        self.assertIn("issues: write", workflow)
        self.assertIn("actions/checkout@v5", workflow)
        self.assertIn("actions/setup-python@v6", workflow)
        self.assertIn("actions/upload-artifact@v6", workflow)
        self.assertIn("actions/github-script@v8", workflow)
        self.assertIn("continue-on-error: true", workflow)
        self.assertIn(
            "python scripts/validate.py --freshness-report --max-age-days 30 --check-urls",
            workflow,
        )
        self.assertIn("name: freshness-report", workflow)
        self.assertIn("path: freshness-report.md", workflow)
        self.assertIn("steps.freshness.outcome", workflow)
        self.assertIn("github.paginate", helper)
        self.assertIn(MARKER, helper)

    def test_all_workflows_use_node24_action_contract(self):
        workflows = {
            "freshness": WORKFLOW.read_text(encoding="utf-8"),
            "validate": VALIDATE_WORKFLOW.read_text(encoding="utf-8"),
            "deploy-pages": DEPLOY_PAGES_WORKFLOW.read_text(encoding="utf-8"),
        }
        production_workflows = "\n".join(workflows.values())

        for old_action in OLD_ACTIONS:
            self.assertNotIn(old_action, production_workflows)

        self.assertIn("actions/checkout@v5", workflows["freshness"])
        self.assertIn("actions/setup-python@v6", workflows["freshness"])
        self.assertIn("actions/upload-artifact@v6", workflows["freshness"])
        self.assertIn("actions/github-script@v8", workflows["freshness"])

        self.assertIn("actions/checkout@v5", workflows["validate"])
        self.assertIn("actions/setup-python@v6", workflows["validate"])

        self.assertIn("actions/checkout@v5", workflows["deploy-pages"])
        self.assertIn("actions/setup-python@v6", workflows["deploy-pages"])
        self.assertIn("actions/configure-pages@v6", workflows["deploy-pages"])
        self.assertIn("actions/upload-pages-artifact@v5", workflows["deploy-pages"])
        self.assertIn("actions/deploy-pages@v5", workflows["deploy-pages"])

if __name__ == "__main__":
    unittest.main()
