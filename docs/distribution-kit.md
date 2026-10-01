# Dataset distribution kit (draft, 2026-10-01)

All copy here is a private draft. Recheck platform rules, counts, links, and release assets before a human posts. Use the clean canonical URL `https://aicostbudget.com/en/datasets/ai-api-pricing` for citation and DOI metadata; keep existing UTM links only for explicit referral CTAs.

## One-line description

Source-linked AI API pricing dataset with token, cache, batch, tiered, multimodal, and non-token records in JSON and CSV.

## Channel ranking

Ratings are qualitative estimates for this repository, not traffic measurements. Traffic, citation, backlinks, developer fit, AI relevance, dataset fit, and current-asset fit use H/M/L; maintenance and self-promotion risk use L/M/H (lower is better).

| Channel | Traffic | Citation | Backlinks | Developer fit | AI fit | Dataset fit | Asset fit | Maintenance | Promo risk | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Corrected GitHub Release | M | H | H | H | H | H | H | L | L | P0 |
| Hugging Face Dataset Card | H | M | H | H | H | H | H | M | L | P0 |
| GitHub Topics and citation UX | M | M | M | H | H | H | H | L | L | P0 |
| Zenodo DOI | L | H | H | M | M | H | M | L | L | P1 after corrected release |
| GitHub Discussion | M | L | M | H | H | M | H | L | M | P1 after release |
| Awesome-list outreach | M | L | H | H | H | M | M | M | M | P1, selective |
| Reddit | M | L | L | M | H | M | M | H | H | P2/DEFER |
| Hacker News | uncertain | L | M | H | H | M | M | M | H | DEFER |
| Kaggle mirror | uncertain | M | M | M | M | M | L | H | L | DEFER |
| Research catalogs / Papers with Code | L | M | M | L | M | L | L | M | M | SKIP for now |

Immediate 3–5 actions: repair the next GitHub Release contract, make citation/version guidance accurate, keep HF card discoverable through a deliberate manual card update, prepare Zenodo for the next validated release, and approach only a few matching lists. GitHub [topics are designed for discovery](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics); current topics include `ai-api-pricing`, `ai-cost`, `ai-finops`, `ai-pricing`, `llm-pricing`, provider names, `json-dataset`, and `csv-dataset`. Suggested additions for manual review: `dataset`, `api-pricing`, `cost-optimization`, and possibly `finops`; do not replace relevant existing topics.

[HF metadata](https://huggingface.co/docs/hub/datasets-cards) supports discovery through license, language, pretty name, tags, and task fields. The local `huggingface/README.md` already has pretty name, license, language, tags, config, clean citation text, and GitHub/methodology links. The [publish allowlist](../scripts/publish_huggingface.py) contains only four data artifacts; changing the local card does not publish it. A maintainer should compare the live card with this local mirror and update the HF card separately only if source repository or canonical citation links are missing. The Dataset Viewer can lag raw files.

Zenodo is **GO after a corrected release**, because [GitHub integration archives releases and mints a version DOI](https://docs.github.com/en/repositories/archiving-a-github-repository/referencing-and-citing-content); the concept DOI then identifies the version family. Enable the repository before the next release, verify its metadata and archive, then backfill DOI links in a later commit. [Zenodo accepts CFF alone](https://help.zenodo.org/docs/github/describe-software/zenodo-json/), so no `.zenodo.json` is needed now.

Kaggle is **DEFER**. It offers [versioned datasets](https://www.kaggle.com/docs/datasets), but a mirror adds a separate update/parity obligation. The existing GitHub/HF channels cover direct downloads and a tabular viewer; public search did not establish a clear incremental audience for this pricing dataset. Papers with Code is **SKIP** unless a research paper or benchmark use case emerges; its directory is centered on ML datasets and tasks.

## Next GitHub Release description (draft)

Title: `AICostBudget AI API Pricing Dataset — RELEASE_VERSION`

> Fixed pricing dataset baseline at snapshot `SNAPSHOT_DATE`, Git commit `FULL_SHA`. This release replaces the mixed-projection asset contract of `dataset-2026-09-30`; it does not alter the historical release.
>
> GitHub Pages V1 contains `V1_COUNT` canonical repository records across `V1_PROVIDERS` providers. Website/HF Pricing V2 contains `V2_COUNT` public records across `V2_PROVIDERS` providers, with export schema `EXPORT_SCHEMA`. The projections have different scopes; counts are not required to match. Dataset JSON Schema: `SCHEMA_PATH` at `SCHEMA_SHA256`.
>
> Generated: `GENERATED_AT`. Aggregate last verified: `LAST_VERIFIED_AT`. Download the projection-qualified JSON, CSV, and metadata assets, `release-manifest.json`, and `SHA256SUMS.txt`. The tracked snapshot is `SNAPSHOT_PATH`. Verify each asset SHA-256 and manifest count before use.
>
> For citation, use this release URL, exact commit, snapshot date, [methodology](https://github.com/aicostbudget/ai-api-pricing-data/blob/main/METHODOLOGY.md), and CC BY 4.0 data license. Code is MIT. Prices may lag provider changes and may be conditional, regional, or account-specific.

Fill placeholders only after the [release gate](release-process.md) passes. Describe concrete changes from the previous correct baseline; do not invent a model launch list.

## GitHub Discussion draft

Title: `A fixed, projection-labeled release baseline for the AI API pricing dataset`

Body:

> We have prepared a release with separate GitHub Pages V1 and Website/HF Pricing V2 assets, a manifest that names the tag commit and tracked snapshot, and SHA-256 checksums. The two projections intentionally contain different public record sets.
>
> The previous `dataset-2026-09-30` bundle mixed V1 price files with V2 metadata. The successor release documents and validates each projection separately. For a reproducible comparison, use the release tag and snapshot rather than the changing main-branch downloads.
>
> Release: `RELEASE_URL`. Manifest: `MANIFEST_URL`. Methodology: `METHODOLOGY_URL`. What additional manifest field would make this easier to cite or integrate?

Post only after release. Existing [Discussion #24](https://github.com/aicostbudget/ai-api-pricing-data/discussions/24) asks how to model conditional prices; this draft asks about release reproducibility instead.

## Hacker News editorial brief

**HN = DEFER** for this release cleanup. [Show HN](https://news.ycombinator.com/showhn.html) is for something people can try; routine version upgrades usually do not qualify. A regular link submission could be considered only if there is a substantive technical write-up, and [HN asks authors to write their own text rather than post generated copy](https://news.ycombinator.com/newsguidelines.html). These are internal title prompts for a human editor, not submission-ready text:

1. `A versioned dataset of AI API pricing with separate V1 and V2 projections` (recommended if a substantive write-up exists)
2. `How we made conditional AI API pricing records reproducible`
3. `Source-linked AI API pricing data with fixed snapshots and checksums`

Editorial angle: explain the mixed-asset failure, the corrected manifest, and how a developer reproduces a cited price. Link the primary technical source; do not repost a prior HN submission or use a marketing CTA.

## Reddit assessment and drafts

Current rule evidence: [r/LLMDevs Rule 5 update](https://www.reddit.com/r/LLMDevs/comments/1mvuw5x/community_rule_update_clarifying_our/) allows free open-source projects but prohibits commercial promotion and disguised advertising. Because this dataset is tied to AICostBudget, ask moderators before posting if the account or linked page could be read as commercial. Draft only for that community:

- Subreddit: r/LLMDevs; recommendation: conditional, moderator check first.
- Title: `A source-linked pricing dataset with explicit cache, batch, and non-token rates`
- Body: `I maintain AICostBudget's open AI API pricing dataset. We store provider source URLs and verification timestamps alongside token and conditional pricing, including cache writes, batch modes, and non-token units. The fixed release and data schema are at RELEASE_URL. Which pricing conditions are hardest to represent in your cost tooling?`
- Disclosure: `I maintain AICostBudget and the linked dataset.`
- Risk: commercial association and self-promotion; do not hide it or post if moderators object.

[r/MachineLearning hosts a self-promotion thread](https://www.reddit.com/r/MachineLearning/comments/1w4xaes/d_selfpromotion_thread/), so use that thread only if the dataset has a concrete research use, rather than opening a standalone promotional post. [r/LocalLLaMA enforces self-promotion activity limits](https://www.reddit.com/r/LocalLLaMA/comments/1wh657b/removed/) and mainly serves local-model discussion; this provider API pricing release is a poor fit. r/OpenAI and r/ClaudeAI are provider-specific; r/ArtificialInteligence rules were not reliably retrievable in this audit. Do not prepare cross-posts for them. Recheck live rules before any human posting.

## Awesome-list outreach shortlist

Snapshot of public GitHub repository API on 2026-10-01; stars and last push are volatile and must be refreshed. No outreach was sent. Contribution text is from each repository README/guide where available.

| Repository | Stars | Last push UTC | Contribution rule observed | Fit / decision |
| --- | ---: | --- | --- | --- |
| [QuesmaOrg/awesome-ai-tokenomics](https://github.com/QuesmaOrg/awesome-ai-tokenomics) | 191 | 2026-10-01 | [Guide](https://github.com/QuesmaOrg/awesome-ai-tokenomics/blob/main/CONTRIBUTING.md): factual one-line entry, primary source, verified date, PR | Strong pricing-data fit; shortlist |
| [InftyAI/Awesome-LLMOps](https://github.com/InftyAI/Awesome-LLMOps) | 264 | 2026-09-30 | README welcomes a relevant project through an issue | LLMOps cost input; shortlist |
| [gregoire-costory/awesome-agentic-finops](https://github.com/gregoire-costory/awesome-agentic-finops) | 30 | 2026-08-13 | No explicit submission rule confirmed; inspect maintainer preference first | FinOps audience; shortlist |
| [pmady/llmops](https://github.com/pmady/llmops) | 20 | 2026-07-05 | [CONTRIBUTING.md](https://github.com/pmady/llmops/blob/main/CONTRIBUTING.md) exists; follow its entry format | Possible secondary target |
| [KennethanCeyer/awesome-llmops](https://github.com/KennethanCeyer/awesome-llmops) | 56 | 2025-03-17 | README asks that additions be relevant to LLMOps | Older activity; hold |
| [ravsau/awesome-ai-cost-optimization](https://github.com/ravsau/awesome-ai-cost-optimization) | 1 | 2026-09-16 | No explicit rule confirmed | Topical but tiny audience; hold |
| [argilla-io/awesome-llm-datasets](https://github.com/argilla-io/awesome-llm-datasets) | 26 | 2023-05-02 | No current contribution rule confirmed | Training-data focus and stale; skip |

Approach only the first three initially, after a corrected release exists. Propose the GitHub source and clean canonical dataset URL, explain the fixed snapshot and official-source provenance, and follow each maintainer's rules. Do not create PRs or issues as part of this local task.
