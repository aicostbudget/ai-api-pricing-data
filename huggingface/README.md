---
pretty_name: AICostBudget AI API Pricing Dataset
license: cc-by-4.0
language:
  - en
tags:
  - tabular
  - ai-api-pricing
  - llm-pricing
  - ai-model-pricing
  - token-cost
  - ai-finops
  - pricing-data
  - open-data
  - csv
  - json
  - developer-tools
configs:
  - config_name: default
    data_files:
      - split: train
        path: train.csv
---

# AI API Pricing Dataset

This Hugging Face dataset is the machine-readable distribution of the public AI API pricing records published by AICostBudget. It is not a separately curated subset: `train.csv`, `prices.csv`, and `prices.json` are generated from the same Pricing V2 public projection used by the AICostBudget Dataset page and download APIs.

Prices change frequently. Verify production billing decisions against the provider pricing page, contract, billing dashboard, and invoice.

## Explore and download

- [AICostBudget AI API Pricing Dataset](https://aicostbudget.com/en/datasets/ai-api-pricing?utm_source=huggingface&utm_medium=dataset&utm_campaign=ai_api_pricing_dataset)
- [Download the public JSON dataset](https://aicostbudget.com/api/datasets/ai-api-pricing.json)
- [Download the public CSV dataset](https://aicostbudget.com/api/datasets/ai-api-pricing.csv)
- [AI API Cost Calculator](https://aicostbudget.com/en/ai-api-cost-calculator?utm_source=huggingface&utm_medium=dataset&utm_campaign=ai_api_pricing_dataset)
- [Model Pricing Comparison](https://aicostbudget.com/en/model-pricing-comparison?utm_source=huggingface&utm_medium=dataset&utm_campaign=ai_api_pricing_dataset)
- [AI Budget Planner](https://aicostbudget.com/en/ai-budget-planner?utm_source=huggingface&utm_medium=dataset&utm_campaign=ai_api_pricing_dataset)

## Published files

- `train.csv`: the CSV consumed by the Hugging Face Dataset Viewer
- `prices.csv`: the same normalized CSV download
- `prices.json`: metadata plus the complete public Website record set
- `meta.json`: generation time, verification date, and coverage counts for this export

`train.csv` and `prices.csv` are byte-for-byte identical. Unknown or unavailable prices are `null` in JSON and empty in CSV; they are never rewritten as zero.

## Distribution rule

The export is deterministic:

1. Start from the checked-in Pricing V2 Website projection.
2. Exclude compatibility aliases because they are not independent public pricing rows.
3. Exclude rows marked `excluded_default_candidate` by the verified pricing pipeline.
4. Preserve Website legacy fallback rows only when the public Pricing Table adapter still exposes them, including the warning that they are not default-safe verified prices.
5. Export exactly the resulting public Website key set; no provider, family, or status-specific allowlist is maintained for Hugging Face.

The canonical provider and pricing facts live in the [AICostBudget pricing data repository](https://github.com/aicostbudget/ai-api-pricing-data). Website-owned legacy display metadata is used only for explicitly marked fallback rows. The exporter does not fetch or guess prices.

## Fields

| Field | Meaning |
| --- | --- |
| `provider_id` | Stable provider identifier. |
| `provider` | Human-readable provider name. |
| `model_id` | Stable public model identifier. |
| `model` | Human-readable model name. |
| `input_price_per_1m_tokens` | Standard input-token price per 1M tokens. |
| `cached_input_price_per_1m_tokens` | Cached-input price per 1M tokens when available. |
| `output_price_per_1m_tokens` | Standard output-token price per 1M tokens. |
| `currency` | Pricing currency; current records use USD. |
| `pricing_unit` | Normalized unit; current records use 1M tokens. |
| `status` | Public lifecycle/status label from the Website projection or marked fallback. |
| `availability` | Public availability label. |
| `official_source_url` | Provider source used by the verified pricing pipeline. |
| `last_verified_at` | Record verification date; it is not refreshed merely because an artifact is rebuilt. |
| `effective_from` | Provider-stated effective date when available. |
| `effective_until` | End date when a selected price record has one. |
| `notes` | Source context, projection warning, or legacy fallback warning. |

## Load with pandas

```python
import pandas as pd

url = (
    "https://huggingface.co/datasets/"
    "aicostbudget-ai/ai-api-pricing/resolve/main/train.csv"
)

pricing = pd.read_csv(url)
print(pricing.head())
print(pricing["provider_id"].value_counts())
```

## Load with Hugging Face Datasets

```python
from datasets import load_dataset

pricing = load_dataset(
    "aicostbudget-ai/ai-api-pricing",
    split="train",
)

print(pricing)
print(pricing[0])
```

The `train` split is the current published pricing snapshot. It is not intended as model-training supervision data.

## Direct Hugging Face files

```text
https://huggingface.co/datasets/aicostbudget-ai/ai-api-pricing/resolve/main/train.csv
https://huggingface.co/datasets/aicostbudget-ai/ai-api-pricing/resolve/main/prices.csv
https://huggingface.co/datasets/aicostbudget-ai/ai-api-pricing/resolve/main/prices.json
https://huggingface.co/datasets/aicostbudget-ai/ai-api-pricing/resolve/main/meta.json
```

## Freshness semantics

- `generated_at` is the artifact generation timestamp copied from the checked-in pricing metadata.
- `last_verified_at` belongs to each record and means the price was checked against its source.
- Rebuilding this distribution does not rewrite record verification dates.
- Validation requires `generated_at >= max(last_verified_at)` and rejects future timestamps.

For current coverage and timestamps, inspect `meta.json`. The source repository also contains schema checks, price validation, history, snapshots, and freshness workflows.

## Methodology and contributions

- [Methodology](https://github.com/aicostbudget/ai-api-pricing-data/blob/main/METHODOLOGY.md)
- [Contributing](https://github.com/aicostbudget/ai-api-pricing-data/blob/main/CONTRIBUTING.md)
- [Data license](https://github.com/aicostbudget/ai-api-pricing-data/blob/main/LICENSE-DATA)
- [Code license](https://github.com/aicostbudget/ai-api-pricing-data/blob/main/LICENSE-CODE)

Prices are accepted from official provider pricing pages, documentation, APIs, or announcements. Third-party aggregators and search snippets are not final price evidence.

## Citation

```text
AICostBudget. AICostBudget AI API Pricing Dataset.
https://github.com/aicostbudget/ai-api-pricing-data
```

## Disclaimer

This dataset is informational and may lag provider changes. AICostBudget is independent and is not affiliated with or endorsed by the listed providers. Provider names and trademarks belong to their respective owners.
