# AICostBudget AI API Pricing Dataset

Open, machine-readable pricing data for LLM and AI APIs.

This repository publishes a versioned dataset and read-only static API for AI API pricing. It is designed for developers, SaaS builders, FinOps teams, researchers, technical writers, and AI systems that need source-linked pricing records instead of ad hoc scraped snippets.

This project is maintained as an independent public dataset by AICostBudget. See [aicostbudget.com](https://aicostbudget.com).

## Quick Start

Download the latest JSON:

```bash
curl -L https://aicostbudget.github.io/ai-api-pricing-data/api/v1/prices.json
```

Download the latest CSV:

```bash
curl -L https://aicostbudget.github.io/ai-api-pricing-data/api/v1/prices.csv
```

## JSON example

```json
{
  "provider_id": "openai",
  "model_id": "gpt-5",
  "pricing": {
    "currency": "USD",
    "unit": "1M tokens",
    "input": 1.25,
    "output": 10.0,
    "cached_input": 0.125,
    "cache_write": null,
    "batch_input": 0.625,
    "batch_output": 5.0
  },
  "official_source_url": "https://platform.openai.com/docs/pricing"
}
```

Unknown or unverified prices are represented as `null`, never `0`.

## CSV example

```csv
provider_id,model_id,display_name,currency,unit,input,output,official_source_url
openai,gpt-5,GPT-5,USD,1M tokens,1.25,10.0,https://platform.openai.com/docs/pricing
```

The real CSV includes all normalized fields.

## curl example

```bash
curl -L https://aicostbudget.github.io/ai-api-pricing-data/api/v1/models/openai/gpt-5.json
```

## Python example

```python
import urllib.request
import json

url = "https://aicostbudget.github.io/ai-api-pricing-data/api/v1/prices.json"
data = json.load(urllib.request.urlopen(url))
print(data["provider_count"], data["model_count"])
```

## JavaScript example

```js
const url = "https://aicostbudget.github.io/ai-api-pricing-data/api/v1/prices.json";
const data = await fetch(url).then((response) => response.json());
console.log(data.provider_count, data.model_count);
```

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

The weekly freshness workflow checks source URLs and stale `last_verified_at` values. It does not guess, infer, or overwrite prices automatically.

## API

The static API is published through GitHub Pages:

- `/api/v1/prices.json`
- `/api/v1/prices.csv`
- `/api/v1/meta.json`
- `/api/v1/providers/<provider>.json`
- `/api/v1/models/<provider>/<model>.json`

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

