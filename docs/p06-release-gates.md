# Single-maintainer release gates (P0.7 replaces P0.6 multi-reviewer governance)

One human maintainer manually dispatches each release. Independent reviewers, Prevent self-review and independent approval history are **not prerequisites**. All pricing/access/lifecycle tests and immutable source identity checks remain required. Local contract verification is not real GitHub Actions or production verification.

## Minimum manual setup

In aicostbudget/ai-api-pricing-data → Settings → Environments:

| Environment (names retained) | Selected Branch, exactly one | Required reviewers |
|---|---|---|
| pricing-candidate-review | codex/issue26-dataset-candidate | not required; clear for a single dispatch step |
| github-pages | main | not required |
| hf-release-review | main | not required |

Choose Selected branches and tags, add the exact **Branch** above, and remove wildcard, extra branch and tag entries. A missing environment or missing/incorrect branch restriction still fails closed. Existing reviewer options are not read by the code; to avoid native Actions waiting for an additional confirmation, clear Required reviewers. Do not weaken the branch restrictions.

Settings → Secrets and variables → Actions: WEBSITE_REPO_TOKEN reads only the private linqiang-max/aicostbudget repository (Contents read); HF_TOKEN writes only the intended HF dataset. No new review PAT/secret is needed. GITHUB_TOKEN is generated per run with contents:read/actions:read; GitHub metadata-read permission verifies that the actor is a real User with repository maintain/admin role. Missing required token, denied API access, bot/read/write-only actor, source mismatch or unapproved branch fails closed. Rotate named provider tokens through their account and Actions secret settings without logging values.

The maintainer's workflow_dispatch itself is manual approval. The guard checks exact repo/branch, the real run SHA/event/actor and first attempt, and the actor's maintain/admin permission. A failed production attempt requires a new dispatch to avoid unintentionally replaying deployment/publish; there is no independent reviewer or approval-history dependency.

## Immutable release identity and tests

Historical Website regression code is pinned to real commit 52c0e6f3094feeaf6812e1564aef4818ecdd372c and exact adapter Git-blob SHA256. It is separate from accessAuthority.baseRevision/accessAuthorityRevision, factual evidence digest, Dataset source S1, Website W1 and Dataset artifact S2. Preserve those distinctions and all exact security assertions; do not manufacture future SHA or upgrade restricted/unresolved facts.

Candidate inputs require the exact fixed Website branch tip, descending from the explicitly approved Website main baseline. Ordinary Validate/Parity still consume actual Website main. Formal Pages/HF inputs are real artifact_sha=S2, source_sha=S1, website_sha=W1, an existing tag resolving to S2 and release_date. Dataset/Website main, dispatch SHA and tag must match; S1 must be a distinct ancestor of S2. Clean actual checkouts, canonical source bytes identical at S1/S2, committed API/snapshot bytes, formal 8-file bundle/checksums, schema1.10, 88 canonical /86 public records, full tests and Website/HF semantic parity are mandatory. Reject LOCAL_CANDIDATE, wrong IDs/refs/SHAs, missing authority/token or failed production parity.

## Smallest execution sequence (requires separate human authorization; nothing is executed by this document)

1. Complete the three branch-restricted environments and token scopes. Test real committed code before any push. Register new workflow inputs on default branch through a separately validated CI-only step if needed; do not mix a source-only price change into that bootstrap.
2. Create real Dataset source S1 on the candidate branch; regenerate with its actual SHA and frozen generation/effective time. Sync all four Website artifacts, create/test real W1, generate HF from committed W1 and commit Dataset artifact S2. No candidate bundle is a formal publication.
3. Manually dispatch the paired candidate checks. Then ordinary checks for S2 must pass against actual Website main. Do not pretend candidate success is a normal-main PASS or disable a failing test to avoid the dependency.
4. **Hostinger binding was confirmed by the maintainer in P0.7: main, Git automatic deployment enabled.** Website main push therefore deploys production. Do not recommend or perform that push as a test-only action. Before any future main push, explicitly approve the exact W1 Hostinger release and fallback, or turn automatic deployment off in hPanel and confirm that change. No Hostinger setting/deploy was changed by P0.7. Website cache workflow may also perform real purge and state-tag writes after readiness; it is not a Hostinger deployment approval gate.
5. After approved W1 deployment, verify actual production JSON/CSV, schema3 fingerprint and Saved/lifecycle behavior. Against that actual W1 main, complete ordinary Dataset S2 checks. Promote only the verified artifact commit to Dataset main. Main/master pushes run validation only: Pages preparation/configuration/upload and production deploy are manual-dispatch-only.
6. The same maintainer selects **Deploy Pages → Run workflow**, main, and the exact S1/W1/S2/tag/date. Complete full tests/formal preflight; only then production deploy runs, with source/run rechecks and post-deployment byte verification.
7. HF is a **separate** manual Run workflow. Default dry_run=true. Verify fixed bundle, full Website/HF semantic parity and actual production Website JSON/CSV/fingerprint. Read independent HF HEAD. After inspecting dry-run, start a new explicitly authorized dispatch with dry_run=false for real publish; retain exact four-file allowlist, fast-forward-only history and post-publication HF/Website parity.

If merging changes W1/S2 SHA, use and re-verify the actual main commit, not an old candidate label; do not squash away S1 ancestry. No fixed future identities are prefilled. Preserve the original 130 user files; use a separately clean release checkout rather than cleaning the current worktree. Any data/identity/access/lifecycle, branch or secret failure stops release.

Official actor permission API: https://docs.github.com/en/rest/collaborators/collaborators?apiVersion=2022-11-28#get-repository-permissions-for-a-user .
