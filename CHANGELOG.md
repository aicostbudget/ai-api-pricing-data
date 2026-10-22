# Changelog

## Unreleased

- Added a dependency-free Python developer utility, synthetic attempt input, tests, and documentation for estimating first-attempt, retry, fallback, and cost-per-successful-task totals from verified default-safe Pricing V2 token rates.
- Unsupported or ambiguous billing conditions fail explicitly instead of being treated as zero cost.

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

