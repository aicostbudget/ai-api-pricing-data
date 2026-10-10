"""Read-only, fail-closed branch-restricted maintainer dispatch verification."""
import json
import re
from urllib.request import Request, urlopen
from urllib.parse import quote

DATASET_REPO = "aicostbudget/ai-api-pricing-data"
WEBSITE_REPO = "linqiang-max/aicostbudget"

class GateError(ValueError):
    pass

def exact_sha(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise GateError(label + " requires an exact lowercase committed SHA")
    return value

class GitHubReader:
    def __init__(self, environ): self.environ = environ
    def __call__(self, path, purpose):
        name = "WEBSITE_REPO_TOKEN" if purpose == "website" else "GITHUB_TOKEN"
        token = self.environ.get(name, "").strip()
        if not token: raise GateError("Missing " + name + ": manual release cannot be verified")
        request = Request("https://api.github.com" + path, headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
        try:
            with urlopen(request, timeout=20) as response: return json.load(response)
        except Exception:
            # Never log Authorization, token values, response headers or exception credentials.
            raise GateError("GitHub maintainer/source verification unavailable or denied") from None

def require_manual_dispatch(context, get, environment_name, branch):
    if (context.get("GITHUB_EVENT_NAME"), context.get("GITHUB_REPOSITORY"), context.get("GITHUB_REF")) != ("workflow_dispatch", DATASET_REPO, "refs/heads/" + branch):
        raise GateError("Manual dispatch is restricted to the approved repository and branch")
    run_id = context.get("GITHUB_RUN_ID", "")
    if not re.fullmatch(r"[0-9]+", run_id) or context.get("GITHUB_RUN_ATTEMPT") != "1":
        raise GateError("A fresh first-attempt dispatch is required; production retries need a new maintainer dispatch")
    sha = exact_sha(context.get("GITHUB_SHA"), "Current workflow source")
    actor = context.get("GITHUB_ACTOR", "")
    if not actor: raise GateError("Workflow actor is missing")
    prefix = "/repos/" + DATASET_REPO
    environment = get(prefix + "/environments/" + environment_name, "review")
    if environment.get("name") != environment_name or not isinstance(environment.get("id"), int):
        raise GateError("Expected real branch-restricted environment is missing")
    policy = environment.get("deployment_branch_policy") or {}
    if policy.get("custom_branch_policies") is not True or policy.get("protected_branches") is not False:
        raise GateError("Release environment requires the explicit branch-only policy")
    branches = get(prefix + "/environments/" + environment_name + "/deployment-branch-policies", "review")
    if branches.get("total_count") != 1 or [(b.get("name"), b.get("type", "branch")) for b in branches.get("branch_policies", [])] != [(branch, "branch")]:
        raise GateError("Release environment must authorize exactly the fixed branch, without wildcards/tags")
    run = get(prefix + "/actions/runs/" + run_id, "review")
    if (run.get("head_sha"), run.get("head_branch"), run.get("event"), run.get("run_attempt"), run.get("actor", {}).get("login", "").casefold(), run.get("actor", {}).get("type")) != (sha, branch, "workflow_dispatch", 1, actor.casefold(), "User"):
        raise GateError("Dispatch run does not match the current source SHA, actor and dispatch")
    # The user's single-maintainer policy: the authorized human dispatch IS approval.
    # Do not query approvals, require a second reviewer, or depend on prevent_self_review.
    if context.get("GITHUB_TRIGGERING_ACTOR", actor).casefold() != actor.casefold():
        raise GateError("Dispatch initiator does not match the recorded maintainer")
    permission = get(prefix + "/collaborators/" + quote(actor, safe="") + "/permission", "review")
    user = permission.get("user", {})
    if permission.get("permission") not in {"admin", "write"} or permission.get("role_name") not in {"admin", "maintain"} or user.get("login", "").casefold() != actor.casefold() or user.get("type") != "User":
        raise GateError("Only the human repository maintainer/admin may approve this manual dispatch")
    return sha
