"""Fail-closed manual candidate policy; never used by published-main CI."""
import json
import os
import re
try:
    from review_gate import GitHubReader, require_manual_dispatch
except ModuleNotFoundError:
    from scripts.review_gate import GitHubReader, require_manual_dispatch

DATASET_REPO = "aicostbudget/ai-api-pricing-data"
WEBSITE_REPO = "linqiang-max/aicostbudget"
DATASET_BRANCH = "refs/heads/codex/p1-s1-source-20261013"
WEBSITE_BRANCH = "codex/p1-w1-website-20261014"
ENVIRONMENT = "pricing-candidate-review"
APPROVED_BASE = "50177d7c4f06d70fa4f0c429ac045e0c0cccef95"

def check_candidate(context, get):
    if (context.get("GITHUB_EVENT_NAME"), context.get("GITHUB_REPOSITORY"), context.get("GITHUB_REF")) != ("workflow_dispatch", DATASET_REPO, DATASET_BRANCH):
        raise ValueError("Candidate validation requires manual dispatch on the fixed Dataset candidate branch")
    sha = context.get("WEBSITE_CANDIDATE_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Candidate must be an exact lowercase 40-character commit SHA")
    require_manual_dispatch(context, get, ENVIRONMENT, DATASET_BRANCH.removeprefix("refs/heads/"))
    main = get(f"/repos/{WEBSITE_REPO}/git/ref/heads/main", "website")["object"]["sha"]
    if main != APPROVED_BASE:
        raise ValueError("Published Website main moved: re-review and update the approved baseline explicitly")
    tip = get(f"/repos/{WEBSITE_REPO}/git/ref/heads/{WEBSITE_BRANCH}", "website")["object"]["sha"]
    if sha != tip or sha == main:
        raise ValueError("Candidate must equal the fixed reviewed candidate branch tip and differ from main")
    comparison = get(f"/repos/{WEBSITE_REPO}/compare/{main}...{sha}", "website")
    if comparison.get("status") != "ahead" or comparison.get("merge_base_commit", {}).get("sha") != main:
        raise ValueError("Candidate must descend from the approved published Website main")
    return sha

def main():
    print("Approved Website candidate: " + check_candidate(os.environ, GitHubReader(os.environ)))

if __name__ == "__main__":
    main()
