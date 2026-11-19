# Changelog

## Unreleased

- Added the `get_price_impact` tool to `ai-api-pricing-mcp` 0.2.0 (not yet published to npm): for one model and a monthly workload it prices each recorded price change before and after, separates changes in effect from announced ones, never assumes a price an event does not list, and gives a net total only when every change in effect could be priced and the changes connect. It refuses workloads priced from a non-standard tier and does not price time-of-day schedules.
- Added `data/archive-history/price-changes-2024-2026.v1.json`: 46 price changes from 2024 to 2026 across OpenAI, Anthropic, Google, DeepSeek, Mistral, Cohere and xAI, each with Wayback Machine captures of the official pricing page before and after the change, plus the announcement when one exists.

## dataset-2026-10 - 2026-11-01

- Published by the monthly release workflow for October 2026, from snapshot `2026-10-31-2` (130 models from 13 providers, last verified 2026-10-31). The Release notes list 32 price-change-log entries across 8 providers.
- The release tag points to Dataset commit `8039a9d9ecc72ff22478519af3ea0dd4f3f15fc4` and carries the same eight assets as `dataset-2026-10-10`: GitHub Pages V1 and Pricing V2 JSON, CSV and metadata files, `release-manifest.json`, and `SHA256SUMS.txt`.
- The tagged source includes the retry and fallback cost diagnostics utility added on 2026-10-11: a dependency-free Python developer utility, synthetic attempt input, tests, and documentation for estimating first-attempt, retry, fallback, and cost-per-successful-task totals from verified default-safe Pricing V2 token rates. Unsupported or ambiguous billing conditions fail explicitly instead of being treated as zero cost.

## mcp-server-v0.1.0 - 2026-10-21 (MCP server bundle, not a dataset release)

- Published the `ai-api-pricing-mcp` 0.1.0 MCPB bundle (`ai-api-pricing-mcp-0.1.0.mcpb`) for Claude Desktop. The Release contains the bundle only and is not a new dataset version; its notes state that the citable dataset release remains `v1.1.0`.

## dataset-2026-10-10 - 2026-10-10

- Published the 2026-10-09 snapshot from Dataset artifact commit `e720435ead3647b0d307c1a10cd8137ff7c8918f`, with authoritative source commit `a01b945461e0670689860e2a715733edc3c6b2f2` retained separately in release provenance.
- Published separate GitHub Pages V1 (88 models) and Pricing V2 / Hugging Face (86 records, export schema 1.10.0) projections.
- Published eight release assets: six projection JSON/CSV/metadata files, `release-manifest.json`, and `SHA256SUMS.txt`.
- GitHub Pages deployment and Hugging Face publication remained separate from the GitHub Release.

## 1.1.0 - 2026-10-02

- Published the first projection-qualified deterministic release bundle for the 2026-09-30 snapshot.
- The annotated `v1.1.0` tag object `94af3e5c5f537aceed388bd2fccaec3ba70bf328` points to Dataset commit `6882e95a8cdf5fb39b75b47bcd9ba0bff63b13d8`; the release also records Website source commit `52d79a701df4cc67e6c4a17b3ab52d50b8197576`.
- Separated GitHub Pages V1 and Pricing V2 assets and added a deterministic release manifest plus SHA-256 checksums.
- Published the fixed-release DOI `10.5281/zenodo.23087250` for this version.

## dataset-2026-09-30 - 2026-10-01 (superseded)

- Published a snapshot tag at commit `c0e1cd74a8aa86534f283037bd571f38a36039cd`.
- Retained as a historical release, but its uploaded `prices.json` and `prices.csv` are GitHub Pages V1 while `meta.json` is Pricing V2 metadata; it is not a validated V2 bundle.
- Superseded for reproducible citation by `v1.1.0`; the historical tag, assets, and hashes remain unchanged.

## 1.0.0 - 2026-07-05 snapshot (GitHub Release published 2026-07-16 Asia/Hong_Kong)

- Initial public dataset structure.
- Added canonical provider and model data for OpenAI, Anthropic, Google Gemini, xAI, DeepSeek, Mistral AI, and Cohere.
- Added JSON Schema files, reproducible Python build scripts, static API output, tests, and GitHub Actions workflows.
- The lightweight `v1.0.0` tag and GitHub Release target commit `64950c02988b38bd9fe133be1650a76e3f01a2e2`.

