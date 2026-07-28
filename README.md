# AI API Pricing Dataset

This dataset provides AI API model pricing data for cost estimation, LLM budget planning, and model price comparison.

Maintained, curated, machine-readable pricing data for major LLM and AI APIs. Prices change frequently, so production budget decisions should always be checked against the relevant provider pricing pages.

[![Validate](https://github.com/aicostbudget/ai-api-pricing-data/actions/workflows/validate.yml/badge.svg)](https://github.com/aicostbudget/ai-api-pricing-data/actions/workflows/validate.yml)
[![Code license: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](LICENSE-CODE)
[![Data license: CC BY 4.0](https://img.shields.io/badge/data-CC%20BY%204.0-green.svg)](LICENSE-DATA)

[AI API Cost Calculator](https://aicostbudget.com/en/ai-api-cost-calculator?utm_source=huggingface&utm_medium=dataset&utm_campaign=ai_api_pricing) |
[Model Pricing Comparison](https://aicostbudget.com/en/model-pricing-comparison?utm_source=huggingface&utm_medium=dataset&utm_campaign=ai_api_pricing) |
[AI Budget Planner](https://aicostbudget.com/en/ai-budget-planner?utm_source=huggingface&utm_medium=dataset&utm_campaign=ai_api_pricing) |
[Download JSON](https://aicostbudget.github.io/ai-api-pricing-data/api/v1/prices.json) |
[Download CSV](https://aicostbudget.github.io/ai-api-pricing-data/api/v1/prices.csv)

This repository publishes a versioned dataset and read-only static API for AI API pricing. It is designed for developers, SaaS builders, FinOps teams, researchers, technical writers, and AI systems that need maintained pricing records instead of ad hoc scraped snippets.

This project is maintained as an independent public dataset by AICostBudget. See [aicostbudget.com](https://aicostbudget.com).

## Why this dataset?

- Source-linked pricing records
- Unknown or unverified values remain `null`, never `0`
- Versioned JSON and CSV outputs
- Per-model history files
- Dated full snapshots
- Read-only static API
- Suitable for calculators, dashboards, cost analysis, and AI FinOps tooling

The weekly freshness workflow checks source URLs and stale `last_verified_at` values. It does not guess, infer, or overwrite prices automatically.

## Website Tools

### AI API Cost Calculator

[Estimate token usage and monthly AI API costs.](https://aicostbudget.com/en/ai-api-cost-calculator?utm_source=huggingface&utm_medium=dataset&utm_campaign=ai_api_pricing)

### Model Pricing Comparison

[Compare model pricing across providers.](https://aicostbudget.com/en/model-pricing-comparison?utm_source=huggingface&utm_medium=dataset&utm_campaign=ai_api_pricing)

### AI Budget Planner

[Plan AI feature budgets for products and SaaS applications.](https://aicostbudget.com/en/ai-budget-planner?utm_source=huggingface&utm_medium=dataset&utm_campaign=ai_api_pricing)

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

## Data Freshness

Every model record includes:

- `official_source_url`
- `accessed_at`
- `last_verified_at`
- `effective_from`
- `notes`

Freshness checks are designed to surface stale source checks. Final billing decisions should still be verified against the provider's official pricing page, contract, and invoice.

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

A price change event is different from a normal history verification row. History rows record source verification state for a model and may change when `last_verified_at`, `official_source_url`, or notes change. Price change events record only verified pricing semantics: input price, cached input price, output price, unit, and currency changes between two trusted snapshots.

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

Use the citation metadata in [CITATION.cff](CITATION.cff), or cite:

> AICostBudget. AICostBudget AI API Pricing Dataset. https://github.com/aicostbudget/ai-api-pricing-data

## Contributing

Contributions are welcome when they include official sources and preserve `null` for unknown values. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Code is licensed under MIT in [LICENSE-CODE](LICENSE-CODE). Data is licensed under Creative Commons Attribution 4.0 in [LICENSE-DATA](LICENSE-DATA).

## Disclaimer

AI API prices change frequently. Always verify official provider pricing pages before making production budget decisions.

This dataset is informational and may lag provider pricing changes. Provider names and trademarks belong to their respective owners. This project is not affiliated with, endorsed by, or sponsored by any listed provider.
