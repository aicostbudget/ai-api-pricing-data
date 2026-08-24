"use strict";

const ISSUE_TITLE = "Freshness check needs review";
const MANAGED_MARKER = "<!-- aicostbudget:freshness-check-managed -->";

function isManagedOpenIssue(issue) {
  return Boolean(
    issue
      && !issue.pull_request
      && issue.state === "open"
      && issue.title === ISSUE_TITLE
      && typeof issue.body === "string"
      && issue.body.includes(MANAGED_MARKER)
  );
}

function buildManagedBody(reportBody) {
  const report = typeof reportBody === "string" && reportBody.trim()
    ? reportBody.trim()
    : "# Freshness Report\n\nThe workflow did not produce a readable report.";
  return `${MANAGED_MARKER}\n\n${report}\n`;
}

function planIssueLifecycle(freshnessFailed, issues) {
  const managedIssues = (Array.isArray(issues) ? issues : [])
    .filter(isManagedOpenIssue)
    .sort((left, right) => left.number - right.number);
  const canonicalIssue = managedIssues[0] || null;

  if (freshnessFailed) {
    return {
      action: canonicalIssue ? "update" : "create",
      canonicalIssueNumber: canonicalIssue ? canonicalIssue.number : null,
      closeIssueNumbers: managedIssues.slice(1).map((issue) => issue.number),
    };
  }

  return {
    action: "none",
    canonicalIssueNumber: null,
    closeIssueNumbers: managedIssues.map((issue) => issue.number),
  };
}

async function closeIssue(github, owner, repo, issueNumber) {
  await github.rest.issues.update({
    owner,
    repo,
    issue_number: issueNumber,
    state: "closed",
    state_reason: "completed",
  });
}

async function manageFreshnessIssue({ github, context, reportBody, freshnessFailed }) {
  const { owner, repo } = context.repo;
  const issues = await github.paginate(github.rest.issues.listForRepo, {
    owner,
    repo,
    state: "open",
    per_page: 100,
  });
  const plan = planIssueLifecycle(freshnessFailed, issues);

  if (plan.action === "create") {
    const response = await github.rest.issues.create({
      owner,
      repo,
      title: ISSUE_TITLE,
      body: buildManagedBody(reportBody),
    });
    plan.canonicalIssueNumber = response.data.number;
  } else if (plan.action === "update") {
    await github.rest.issues.update({
      owner,
      repo,
      issue_number: plan.canonicalIssueNumber,
      body: buildManagedBody(reportBody),
    });
  }

  for (const issueNumber of plan.closeIssueNumbers) {
    await closeIssue(github, owner, repo, issueNumber);
  }

  return plan;
}

module.exports = {
  ISSUE_TITLE,
  MANAGED_MARKER,
  buildManagedBody,
  isManagedOpenIssue,
  manageFreshnessIssue,
  planIssueLifecycle,
};
