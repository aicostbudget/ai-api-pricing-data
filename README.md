# AI API Pricing Dataset

An AI API and LLM pricing dataset for OpenAI, Anthropic Claude, Google Gemini, xAI, DeepSeek, Mistral AI, and Cohere, built for cost estimation, budget planning, and model price comparison.

Published as JSON, CSV, and a Hugging Face dataset, with machine-readable records linked to official provider pricing sources and regularly validated. Prices change frequently, so production budget decisions should always be checked against the relevant provider pricing pages.

[![Validate](https://github.com/aicostbudget/ai-api-pricing-data/actions/workflows/validate.yml/badge.svg)](https://github.com/aicostbudget/ai-api-pricing-data/actions/workflows/validate.yml)
[![Code license: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](LICENSE-CODE)
[![Data license: CC BY 4.0](https://img.shields.io/badge/data-CC%20BY%204.0-green.svg)](LICENSE-DATA)

## Dataset access

- **Canonical dataset page:** [AI API & LLM Pricing Dataset documentation](https://aicostbudget.com/en/datasets/ai-api-pricing?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=readme_dataset)
- **Machine-readable downloads:** [JSON](https://aicostbudget.github.io/ai-api-pricing-data/api/v1/prices.json) | [CSV](https://aicostbudget.github.io/ai-api-pricing-data/api/v1/prices.csv) | [metadata](https://aicostbudget.github.io/ai-api-pricing-data/api/v1/meta.json)
- **Hugging Face mirror:** [aicostbudget-ai/ai-api-pricing](https://huggingface.co/datasets/aicostbudget-ai/ai-api-pricing)
- **Schema and verification:** [model schema](schema/model.schema.json) | [pricing contract](docs/pricing-contract.md) | [methodology](METHODOLOGY.md)

## Interactive Tools

- [Calculate your API cost](https://aicostbudget.com/en/ai-api-cost-calculator?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=readme_calculator)
- [Compare AI model prices](https://aicostbudget.com/en/model-pricing-comparison?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=readme_comparison)
- [Track AI model price changes](https://aicostbudget.com/en/model-price-monitor?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=readme_price_monitor)

### Distribution projections

The GitHub Pages `/api/v1` JSON and CSV publish the canonical records in this repository. The AICostBudget Website JSON/CSV and Hugging Face files publish the Pricing V2 public Website projection, including structured tier and pricing-component metadata. Current public export schema **1.10.0** adds generic promotion/list-price conditions and aligns the access/binding extension with the Website ([contract](docs/public-export-contract-1.10.md)); historical releases retain their original schema version. Schema 1.8.0 preserves generic `usage_tier` conditions and adds transport selection, modality-aware components, mutually exclusive measurement alternatives, optional feature charges, and independent model-default metadata. Eligibility-scoped `conditional_usage_allowances` remain separate from standard paid tiers. Hugging Face must match the Website projection exactly by key set and exported fields; it is not expected to match the intentionally narrower GitHub Pages V1 key set.

The existing scalar input, cached-input, and output values remain the compatibility/default pricing view. `pricing_components` is the full conditional view: each entry combines a charge component, decimal-string amount, condition, provenance, verification status, and effective range. One model can have separate `cache_write_5m` and `cache_write_1h` entries, or cache-write entries for different processing modes and context classes, so cache write cannot be modeled permanently as one universal scalar.

## Dataset Trust & Freshness

- **Updated:** The latest dataset build timestamp (`generated_at`) and aggregate record verification timestamp (`last_verified_at`) are published in [machine-readable metadata](api/v1/meta.json) and the [static API](https://aicostbudget.github.io/ai-api-pricing-data/api/v1/meta.json).
- **Verified:** Each pricing record includes its own `accessed_at` and `last_verified_at` timestamps.
- **Sources:** Pricing records link to official provider pricing pages or documentation through `official_source_url`; see the [methodology](#methodology).
- **Validation:** Pushes and pull requests run [dataset and schema checks, Hugging Face export parity, and tests](.github/workflows/validate.yml); a [weekly freshness check](.github/workflows/freshness-check.yml) surfaces stale verification timestamps and source URL failures.

This repository publishes a versioned dataset and read-only static API for AI API pricing. It is designed for developers, SaaS builders, FinOps teams, researchers, technical writers, and AI systems that need maintained pricing records instead of ad hoc scraped snippets.

This project is maintained as an independent public dataset by AICostBudget.

## Why this dataset?

- Source-linked pricing records
- Unknown or unverified values remain `null`, never `0`
- Versioned JSON and CSV outputs
- Per-model history files
- Dated full snapshots
- Read-only static API
- Suitable for calculators, dashboards, cost analysis, and AI FinOps tooling

The weekly freshness workflow checks source URLs and stale `last_verified_at` values. It does not guess, infer, or overwrite prices automatically.

## Quick Start

### Latest JSON

```bash
curl -L https://aicostbudget.github.io/ai-api-pricing-data/api/v1/prices.json
```

### Latest CSV

```bash
curl -L https://aicostbudget.github.io/ai-api-pricing-data/api/v1/prices.csv
```

### Single model record

```bash
curl -L https://aicostbudget.github.io/ai-api-pricing-data/api/v1/models/openai/gpt-4.1.json
```

### Python

```python
import json
import urllib.request

url = "https://aicostbudget.github.io/ai-api-pricing-data/api/v1/models/openai/gpt-4.1.json"
with urllib.request.urlopen(url) as response:
    model = json.load(response)

print(model["provider_id"], model["model_id"], model["pricing"]["input"])
```

### JavaScript

```js
const url = "https://aicostbudget.github.io/ai-api-pricing-data/api/v1/models/openai/gpt-4.1.json";

async function main() {
  const response = await fetch(url);
  const model = await response.json();

  console.log(model.provider_id, model.model_id, model.pricing.input);
}

main();
```

## Developer utility: retry and fallback cost diagnostics

Run the repository's dependency-free Python example to estimate the cost of anonymized LLM task attempts while keeping first attempts, retries, and model fallbacks separate:

```bash
python examples/llm_cost_diagnostics.py examples/sample_llm_attempts.json
```

Expected output for the checked-in synthetic input and current checked-in Pricing V2 catalog:

```text
LLM cost diagnostics
Input provenance: synthetic_example_not_production_measurement
Pricing catalog: data/pricing-v2-preview/generated/model-pricing.v2.json
Tasks: 3
Successful tasks: 2
Attempts: 5
Billed attempts: 5
Not-billed attempts: 0
First-attempt estimated cost (USD): 0.287500
Retry estimated cost (USD): 0.150000
Fallback estimated cost (USD): 0.300000
Total estimated cost (USD): 0.737500
Cost per successful task (USD): 0.368750
```

The example input is synthetic and is not a production measurement, provider invoice, or claimed success-rate benchmark. Replace it with anonymized attempt records from your own system. Each record must identify its task and attempt, classify the attempt as `first_attempt`, `retry`, or `fallback`, state whether the task attempt succeeded, and provide normalized usage by pricing component. `usage.input` must contain only uncached input tokens; cached input belongs in `usage.cached_input` so the two counts do not overlap.

The utility deliberately has a narrow billing scope:

- It reads the checked-in Pricing V2 catalog and accepts only its verified, default-safe selected billing record.
- It supports standard, short-context, global text pricing in USD per one million tokens for `input`, `cached_input`, and `output` components.
- `billing_status` must be `billed`, `not_billed`, or `unknown`. An explicit `not_billed` attempt contributes zero; `unknown` stops the run instead of silently contributing zero.
- Missing models or rates, conditional tiers, alternative processing modes, non-token units, unsupported usage components, and ambiguous billing conditions stop the run with an error.
- Results are catalog-rate estimates for diagnostic comparison, not invoice reconciliation. Provider-specific taxes, contracts, credits, rounding, and unrecorded charges are outside this example's scope.

Use the interactive tools for scenario exploration:

- [Analyze retry cost](https://aicostbudget.com/en/llm-retry-cost-calculator?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=readme_retry_cost_calculator)
- [Compare model-switch cost](https://aicostbudget.com/en/model-switch-cost-calculator?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=readme_model_switch_cost_calculator)

## Use Cases

- Compare AI model prices
- Estimate monthly AI API cost
- Build LLM cost dashboards
- Plan SaaS AI feature budgets
- Track model pricing changes

## Explore Pricing by Provider

| Provider | Pricing page | Coverage |
| --- | --- | --- |
| OpenAI | [OpenAI API pricing](https://aicostbudget.com/en/providers/openai-api-pricing?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=openai) | GPT models, cached input, cache-write pricing, batch and alternative processing modes, and long-context tiers |
| Anthropic | [Anthropic API pricing](https://aicostbudget.com/en/providers/anthropic-api-pricing?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=anthropic) | Claude models, prompt caching, cache-write pricing, and batch pricing |
| Google Gemini | [Google Gemini API pricing](https://aicostbudget.com/en/providers/google-gemini-api-pricing?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=google_gemini) | Gemini models, multimodal pricing, TTS, batch pricing, and cached input |
| xAI | [xAI API pricing](https://aicostbudget.com/en/providers/xai-api-pricing?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=xai) | Grok models, long-context tiers, processing-mode pricing, and speech/transcription pricing |
| DeepSeek | [DeepSeek API pricing](https://aicostbudget.com/en/providers/deepseek-api-pricing?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=deepseek) | DeepSeek chat and reasoning models, including cached-input pricing where available |
| Mistral AI | [Mistral AI API pricing](https://aicostbudget.com/en/providers/mistral-ai-api-pricing?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=mistral_ai) | Mistral model pricing with structured source and verification metadata |
| Cohere | [Cohere API pricing](https://aicostbudget.com/en/providers/cohere-api-pricing?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=cohere) | Cohere model pricing and supported non-token services |

## Dataset Coverage

The dataset covers multiple AI providers and supports both token-based and non-token pricing structures.

Coverage includes:

- Standard input and output token pricing
- Cached input and cache-write pricing
- Batch and alternative processing modes
- Long-context, usage-tier, and conditional pricing
- Multimodal and non-token pricing
- TTS, speech, and transcription pricing
- Model lifecycle, provenance, and verification metadata
- Structured conditional pricing components

## Fields

The CSV output uses the following fields:

| Field | Meaning |
| --- | --- |
| `provider_id` | Stable provider identifier. |
| `model_id` | Stable model identifier within the provider. |
| `display_name` | Human-readable model name. |
| `model_family` | Model family or grouping when available. |
| `status` | Model availability or lifecycle status. |
| `currency` | Pricing currency. |
| `unit` | Pricing unit, such as per-token or per-million-token billing units. |
| `input` | Input token price for the listed unit. |
| `output` | Output token price for the listed unit. |
| `cached_input` | Cached input token price when available. |
| `cache_write` | Cache write price when available. |
| `batch_input` | Batch input token price when available. |
| `batch_output` | Batch output token price when available. |
| `official_source_url` | Provider page or document URL used for source checking. |
| `accessed_at` | Date when the source was accessed. |
| `last_verified_at` | Date when the record was last verified. |
| `effective_from` | Date when the listed pricing became effective, if known. |
| `notes` | Additional context or caveats for the record. |

## API Reference

The static API is published through GitHub Pages:

- `/api/v1/prices.json`
- `/api/v1/prices.csv`
- `/api/v1/meta.json`
- `/api/v1/providers/<provider>.json`
- `/api/v1/models/<provider>/<model>.json`

Unknown or unverified prices are represented as `null`, never `0`.

The CSV output includes normalized pricing fields for provider, model, pricing unit, source URL, verification dates, and notes.

## Historical Pricing

Per-model history files are stored under:

```text
data/history/<provider>/<model>.jsonl
```

Dated full snapshots are stored under:

```text
data/snapshots/<YYYY-MM-DD>/prices.json
data/snapshots/<YYYY-MM-DD>/prices.csv
```

### Price Change Events

Canonical price change events are stored in:

```text
data/price-change-events/events.jsonl
```

A price change event is different from a normal history verification row. History rows record source verification state for a model and may change when `last_verified_at`, `official_source_url`, or notes change. Price change events record verified scalar pricing semantics between two trusted snapshots and can also emit `component_price_update` when matching `pricing_id + charge_id` entries change amount while scalar prices remain unchanged. Component events preserve the component name, old and new decimal-string amounts, and condition. Component additions/removals are not treated as price launches because they may reflect coverage changes.

Baseline snapshots are not price changes. New snapshots, reordered files, source URL edits, status changes, or repeated verification dates must not create price change events when the prices are unchanged.

Date fields use separate meanings:

- `effective_from`: provider-announced effective date only. It stays `null` when the provider did not publish one.
- `detected_at`: the first snapshot date where the repository observed the change by comparing trusted snapshots.
- `verified_at`: the date the new price was checked against an official provider source.
- `date_basis`: one of `provider_announced`, `official_changelog`, `first_observed`, or `unknown`.

Preview events without writing:

```bash
python scripts\generate_price_change_events.py --before data\snapshots\2026-07-09\prices.json --after data\snapshots\2026-07-27\prices.json --dry-run
```

Generate the canonical JSONL projection:

```bash
python scripts\generate_price_change_events.py --before data\snapshots\2026-07-09\prices.json --after data\snapshots\2026-07-27\prices.json
```

The generator matches models by `provider_id + model_id`, compares only pricing semantics, writes stable sorted output, and merges by `dedupe_key`. The first version emits `price_update`, `cached_price_added`, and `cached_price_removed`; it does not emit `pricing_added` or `pricing_removed` because a model first appearing in a snapshot may be coverage expansion rather than an official pricing launch. The dedupe key is based on provider, model, old prices, new prices, unit, currency, and change type. It excludes `verified_at`, `announcement_url`, and notes so later metadata backfills update the same event instead of creating a duplicate.

Both source snapshots must already be tracked by Git before event generation. The generator fails closed rather than writing a canonical event that depends on an ignored, untracked, or local-only snapshot.

Manual backfills should edit the existing event with the same `dedupe_key`. Add `effective_from` only when an official provider announcement, official changelog, or pricing page explicitly gives the effective date. Add `announcement_url` only for an official URL; do not invent one.

Do not copy a fixed event count into documentation or product code. The validated records in `data/price-change-events/events.jsonl` are the authoritative current count.

Publication readiness is determined from the current event file: require at least 5 real price changes, at least 3 providers covered, an official source plus `detected_at` and `verified_at` for every event, explicit marking of unknown effective dates, and no inferred old prices. Passing these gates supports a recent verified price-changes feed; it does not by itself establish deep multi-year Pricing History coverage.

## Methodology

Prices are accepted only from official provider pricing pages, official documentation, official APIs, or official announcements. Third-party calculators, SEO pages, Reddit posts, and competitor aggregators are not used as final price sources.

See [METHODOLOGY.md](METHODOLOGY.md).

## Cite this dataset

For reproducible research, cite the frozen **v1.1.0** release:

> AICostBudget. *AICostBudget AI API Pricing Dataset*, v1.1.0 (snapshot 2026-09-30). [https://doi.org/10.5281/zenodo.23087250](https://doi.org/10.5281/zenodo.23087250).

- [GitHub Release v1.1.0](https://github.com/aicostbudget/ai-api-pricing-data/releases/tag/v1.1.0)
- Dataset commit: `6882e95a8cdf5fb39b75b47bcd9ba0bff63b13d8`
- Data license: [CC BY 4.0](LICENSE-DATA)

The DOI identifies this fixed release, not the latest data. [CITATION.cff](CITATION.cff) provides its machine-readable citation metadata. The [canonical live dataset](https://aicostbudget.com/en/datasets/ai-api-pricing) continues to update; for current operational use, cite that URL with your access date. The export's `generated_at` and `last_verified_at` timestamps are separate from the access date. See the [release process](docs/release-process.md) for projection and checksum rules.


## Contributing

Contributions are welcome when they include official sources and preserve `null` for unknown values. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Code is licensed under MIT in [LICENSE-CODE](LICENSE-CODE). Data is licensed under Creative Commons Attribution 4.0 in [LICENSE-DATA](LICENSE-DATA).

## Disclaimer

AI API prices change frequently. Always verify official provider pricing pages before making production budget decisions.

This dataset is informational and may lag provider pricing changes. Provider names and trademarks belong to their respective owners. This project is not affiliated with, endorsed by, or sponsored by any listed provider.
