# AICostBudget AI API Pricing Dataset

Open, versioned, machine-readable pricing data for major LLM and AI APIs, linked to official provider sources.

[![Validate](https://github.com/aicostbudget/ai-api-pricing-data/actions/workflows/validate.yml/badge.svg)](https://github.com/aicostbudget/ai-api-pricing-data/actions/workflows/validate.yml)
[![Code license: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](LICENSE-CODE)
[![Data license: CC BY 4.0](https://img.shields.io/badge/data-CC%20BY%204.0-green.svg)](LICENSE-DATA)

[Explore Live Pricing Data](https://aicostbudget.com/en/ai-api-pricing-data?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset) |
[Calculate AI API Cost](https://aicostbudget.com/en/ai-api-cost-calculator?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset) |
[Download JSON](https://aicostbudget.github.io/ai-api-pricing-data/api/v1/prices.json) |
[Download CSV](https://aicostbudget.github.io/ai-api-pricing-data/api/v1/prices.csv)

This repository publishes a versioned dataset and read-only static API for AI API pricing. It is designed for developers, SaaS builders, FinOps teams, researchers, technical writers, and AI systems that need source-linked pricing records instead of ad hoc scraped snippets.

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

## Live Tools

### AI API Pricing Dataset

[Browse current provider and model pricing, methodology, downloads, and verification information.](https://aicostbudget.com/en/ai-api-pricing-data?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=live_dataset)

### AI API Cost Calculator

[Estimate input, output, and cached-token costs using the public pricing selector.](https://aicostbudget.com/en/ai-api-cost-calculator?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=cost_calculator)

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

## Common Use Cases

- Power an AI API cost calculator
- Compare model input and output pricing
- Build internal FinOps dashboards
- Track historical pricing changes
- Audit source-linked pricing records
- Export normalized pricing data to JSON or CSV
- Support technical research and cost reporting

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

## Supported Providers

- OpenAI
- Anthropic
- Google Gemini
- xAI
- DeepSeek
- Mistral AI
- Cohere

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

This dataset is informational and may lag provider pricing changes. Always verify final billing decisions with the provider's official pricing page, contract, and invoice. Provider names and trademarks belong to their respective owners. This project is not affiliated with, endorsed by, or sponsored by any listed provider.
