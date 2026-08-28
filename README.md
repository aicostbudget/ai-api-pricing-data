# AI API Pricing Dataset

An AI API and LLM pricing dataset for OpenAI, Anthropic Claude, Google Gemini, xAI, DeepSeek, Mistral AI, and Cohere, built for cost estimation, budget planning, and model price comparison.

Published as JSON, CSV, and a Hugging Face dataset, with machine-readable records linked to official provider pricing sources and regularly validated. Prices change frequently, so production budget decisions should always be checked against the relevant provider pricing pages.

[![Validate](https://github.com/aicostbudget/ai-api-pricing-data/actions/workflows/validate.yml/badge.svg)](https://github.com/aicostbudget/ai-api-pricing-data/actions/workflows/validate.yml)
[![Code license: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](LICENSE-CODE)
[![Data license: CC BY 4.0](https://img.shields.io/badge/data-CC%20BY%204.0-green.svg)](LICENSE-DATA)

## Interactive Tools

- [Calculate your API cost](https://aicostbudget.com/en/ai-api-cost-calculator?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=readme_calculator)
- [Compare AI model prices](https://aicostbudget.com/en/model-pricing-comparison?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=readme_comparison)
- [Track AI model price changes](https://aicostbudget.com/en/model-price-monitor?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=readme_price_monitor)
- [Browse the full pricing dataset](https://aicostbudget.com/en/datasets/ai-api-pricing?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=readme_dataset)

Downloads: [JSON](https://aicostbudget.github.io/ai-api-pricing-data/api/v1/prices.json) | [CSV](https://aicostbudget.github.io/ai-api-pricing-data/api/v1/prices.csv) | [Hugging Face](https://huggingface.co/datasets/aicostbudget-ai/ai-api-pricing)

### Distribution projections

The GitHub Pages `/api/v1` JSON and CSV publish the canonical V1 records in this repository (currently 32 models). The AICostBudget Website JSON/CSV and Hugging Face files publish the same 40-row Pricing V2 public Website projection, including structured tier and pricing-component metadata. Public export schema 1.3.0 adds `pricing_components` to JSON and appends `pricing_components_json` to CSV without changing existing fields or column order. Hugging Face must match the Website projection exactly by key set and exported fields; it is not expected to match the intentionally narrower GitHub Pages V1 key set.

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

## Use Cases

- Compare AI model prices
- Estimate monthly AI API cost
- Build LLM cost dashboards
- Plan SaaS AI feature budgets
- Track model pricing changes

## Explore Pricing by Provider

| Provider | Pricing page |
| --- | --- |
| OpenAI | [OpenAI API pricing](https://aicostbudget.com/en/providers/openai-api-pricing?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=openai) |
| Anthropic | [Anthropic API pricing](https://aicostbudget.com/en/providers/anthropic-api-pricing?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=anthropic) |
| Google Gemini | [Google Gemini API pricing](https://aicostbudget.com/en/providers/google-gemini-api-pricing?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=google_gemini) |
| xAI | [xAI API pricing](https://aicostbudget.com/en/providers/xai-api-pricing?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=xai) |
| DeepSeek | [DeepSeek API pricing](https://aicostbudget.com/en/providers/deepseek-api-pricing?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=deepseek) |
| Mistral AI | [Mistral AI API pricing](https://aicostbudget.com/en/providers/mistral-ai-api-pricing?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=mistral_ai) |
| Cohere | [Cohere API pricing](https://aicostbudget.com/en/providers/cohere-api-pricing?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=cohere) |

## Coverage

- OpenAI
- Anthropic Claude
- Google Gemini
- DeepSeek
- xAI Grok
- Mistral AI
- Cohere

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

Manual backfills should edit the existing event with the same `dedupe_key`. Add `effective_from` only when an official provider announcement, official changelog, or pricing page explicitly gives the effective date. Add `announcement_url` only for an official URL; do not invent one.

Current canonical event count is 2:

- Mistral AI `mistral-large`: `price_update`
- xAI `grok-4.3`: `cached_price_added`

The current data is not ready for a public Pricing History page. Suggested readiness gates are at least 5 real price changes, at least 3 providers covered, official source for every event, `detected_at` and `verified_at` for every event, explicit marking of unknown effective dates, and no inferred old prices.

## Methodology

Prices are accepted only from official provider pricing pages, official documentation, official APIs, or official announcements. Third-party calculators, SEO pages, Reddit posts, and competitor aggregators are not used as final price sources.

See [METHODOLOGY.md](METHODOLOGY.md).

## Citation

If you use this dataset for a benchmark, research, analysis, tooling, an article, or dataset aggregation, cite this repository using [CITATION.cff](CITATION.cff), or cite:

> AICostBudget. AICostBudget AI API Pricing Dataset. https://github.com/aicostbudget/ai-api-pricing-data

## Contributing

Contributions are welcome when they include official sources and preserve `null` for unknown values. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Code is licensed under MIT in [LICENSE-CODE](LICENSE-CODE). Data is licensed under Creative Commons Attribution 4.0 in [LICENSE-DATA](LICENSE-DATA).

## Disclaimer

AI API prices change frequently. Always verify official provider pricing pages before making production budget decisions.

This dataset is informational and may lag provider pricing changes. Provider names and trademarks belong to their respective owners. This project is not affiliated with, endorsed by, or sponsored by any listed provider.
