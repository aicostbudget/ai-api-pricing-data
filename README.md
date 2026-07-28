# AI API Pricing Dataset

**Source-linked, machine-readable AI API pricing for cost calculators, model comparison, budget planning, and AI FinOps.**

`7 providers` | `21 normalized model records` | `10 official sources` | `JSON + CSV` | `per-model history`

[![Validate](https://github.com/aicostbudget/ai-api-pricing-data/actions/workflows/validate.yml/badge.svg)](https://github.com/aicostbudget/ai-api-pricing-data/actions/workflows/validate.yml)
[![Code license: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](LICENSE-CODE)
[![Data license: CC BY 4.0](https://img.shields.io/badge/data-CC%20BY%204.0-green.svg)](LICENSE-DATA)

[Try the AI API Cost Calculator](https://aicostbudget.com/en/ai-api-cost-calculator?utm_source=github&utm_medium=referral&utm_campaign=ai_api_pricing&utm_content=header_cost_calculator)

[Browse the Pricing Dataset](https://aicostbudget.com/en/ai-api-pricing-data?utm_source=github&utm_medium=referral&utm_campaign=ai_api_pricing&utm_content=header_dataset_page) |
[Compare Model Pricing](https://aicostbudget.com/en/model-pricing-comparison?utm_source=github&utm_medium=referral&utm_campaign=ai_api_pricing&utm_content=header_model_comparison) |
[Plan an AI Budget](https://aicostbudget.com/en/ai-budget-planner?utm_source=github&utm_medium=referral&utm_campaign=ai_api_pricing&utm_content=header_budget_planner)

[View JSON API](https://aicostbudget.github.io/ai-api-pricing-data/api/v1/prices.json) |
[Download CSV](https://aicostbudget.github.io/ai-api-pricing-data/api/v1/prices.csv)

Use this dataset when you need maintained pricing records instead of ad hoc scraped snippets. Every record includes an official source and verification metadata, and unknown or insufficiently verified prices remain `null`, never `0`.

- Official-source-linked pricing records
- Standard, cached, and batch pricing where available
- Per-model history and dated snapshots
- Read-only static API for calculators, dashboards, and AI FinOps tools

This project is maintained as an independent public dataset by [AICostBudget](https://aicostbudget.com/en/ai-api-pricing-data?utm_source=github&utm_medium=referral&utm_campaign=ai_api_pricing&utm_content=maintainer_dataset_page).

Prices change frequently, so production budget decisions should always be checked against the relevant provider pricing pages. The weekly freshness workflow checks source URLs and stale `last_verified_at` values; it does not guess, infer, or overwrite prices automatically.

## Website Tools

### AI API Cost Calculator

[Estimate token usage and monthly AI API costs.](https://aicostbudget.com/en/ai-api-cost-calculator?utm_source=github&utm_medium=referral&utm_campaign=ai_api_pricing&utm_content=website_tools_cost_calculator)

### Model Pricing Comparison

[Compare model pricing across providers.](https://aicostbudget.com/en/model-pricing-comparison?utm_source=github&utm_medium=referral&utm_campaign=ai_api_pricing&utm_content=website_tools_model_comparison)

### AI Budget Planner

[Plan AI feature budgets for products and SaaS applications.](https://aicostbudget.com/en/ai-budget-planner?utm_source=github&utm_medium=referral&utm_campaign=ai_api_pricing&utm_content=website_tools_budget_planner)

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
