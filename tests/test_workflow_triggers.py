import re
import unittest

from tests.test_ci_orchestration import WORKFLOWS, child_mapping_keys


def block(text, parent, key):
    """Lines of `key:` directly under the top-level `parent:` mapping."""
    lines = text.splitlines()
    start = next(index for index, line in enumerate(lines) if line == f"{parent}:")
    body = []
    inside = False
    for line in lines[start + 1:]:
        if line and not line.startswith(" "):
            break
        if re.match(rf"^  {re.escape(key)}:", line):
            inside = True
            continue
        if inside and re.match(r"^  [A-Za-z0-9_-]+:", line):
            break
        if inside:
            body.append(line)
    return body


class WorkflowTriggerHygieneTests(unittest.TestCase):
    """Every workflow: push only on named branches, explicit permissions, no pull_request_target.

    An archive branch once ran a stale push-triggered validate workflow on its own push.
    """

    def workflows(self):
        paths = sorted(WORKFLOWS.glob("*.yml"))
        self.assertTrue(paths)
        return [(path.name, path.read_text(encoding="utf-8")) for path in paths]

    def test_push_triggers_name_their_branches(self):
        for name, text in self.workflows():
            if "push" not in child_mapping_keys(text, "on"):
                continue
            with self.subTest(workflow=name):
                push = "\n".join(block(text, "on", "push"))
                self.assertRegex(push, re.compile(r"^    branches:", re.M), f"{name} runs on every branch push")
                self.assertNotIn("branches-ignore", push)

    def test_permissions_are_explicit(self):
        for name, text in self.workflows():
            with self.subTest(workflow=name):
                top_level = re.search(r"^permissions:", text, re.M)
                jobs = re.findall(r"^  ([A-Za-z0-9_-]+):\n", text.split("\njobs:\n", 1)[1], re.M)
                job_level = all(re.search(rf"^  {re.escape(job)}:\n(?:    .*\n|\n)*?    permissions:", text, re.M) for job in jobs)
                self.assertTrue(top_level or job_level, f"{name} would inherit the repository default token permissions")

    def test_no_pull_request_target(self):
        for name, text in self.workflows():
            with self.subTest(workflow=name):
                self.assertNotIn("pull_request_target", text)


if __name__ == "__main__":
    unittest.main()
