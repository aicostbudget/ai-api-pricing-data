---
pretty_name: "LLM API Price History: GPT, Claude, Gemini, Grok, DeepSeek, Qwen price changes over time"
license: cc-by-4.0
language:
  - en
size_categories:
  - 1K<n<10K
tags:
  - llm
  - pricing
  - price-history
  - llm-pricing
  - llm-api-pricing
  - api-pricing
  - token-pricing
  - time-series
  - openai
  - anthropic
  - gemini
  - gpt
  - claude
  - grok
  - deepseek
  - qwen
  - mistral
  - finops
  - tabular
configs:
  - config_name: price_snapshots
    default: true
    data_files:
      - split: train
        path: price_snapshots.csv
  - config_name: price_changes
    data_files:
      - split: train
        path: price_changes.csv
---

# LLM API Price History

How LLM API prices change over time, starting 2026-07-05: dated price snapshots for every model in the [AICostBudget AI API Pricing Dataset](https://huggingface.co/datasets/aicostbudget-ai/ai-api-pricing), plus a log of verified provider price changes, new models, deprecations, and retirements. Providers include OpenAI, Anthropic, Google, xAI, DeepSeek, Mistral, Cohere, Moonshot AI, Alibaba Qwen, and Meta. These are examples, not an exhaustive provider list.

| Config | One row per | Use it for |
| --- | --- | --- |
| `price_snapshots` (default) | snapshot day × model | Price of a model on a given date; price trends; when a model entered the dataset |
| `price_changes` | verified change event | Price cuts and increases, new models, deprecations, retirements, successor models |

**Current prices** live in the main [AI API Pricing Dataset](https://huggingface.co/datasets/aicostbudget-ai/ai-api-pricing). To see what a price change means for your bill, compare two models in the [Model Switch Cost Calculator](https://aicostbudget.com/en/model-switch-cost-calculator?utm_source=huggingface&utm_medium=referral&utm_campaign=price_history_dataset&utm_content=card_intro) or follow changes on the [model price monitor](https://aicostbudget.com/en/model-price-monitor?utm_source=huggingface&utm_medium=referral&utm_campaign=price_history_dataset&utm_content=card_intro). Browse recent changes in the [LLM API Pricing Calculator](https://huggingface.co/spaces/aicostbudget-ai/llm-api-pricing-calculator) Space, part of the [LLM API Pricing & Cost collection](https://huggingface.co/collections/aicostbudget-ai/llm-api-pricing-and-cost-6ae3690fbe696553bf43f16a).

## Quick start

```python
from datasets import load_dataset

snapshots = load_dataset("aicostbudget-ai/llm-api-price-history", "price_snapshots", split="train").to_pandas()
changes = load_dataset("aicostbudget-ai/llm-api-price-history", "price_changes", split="train").to_pandas()

# Verified provider price changes
print(changes[changes["change_type"] == "price_update"][
    ["detected_at", "provider", "model_id", "old_input_price", "new_input_price", "old_output_price", "new_output_price"]
])

# Price path of one model across snapshot days
print(snapshots[snapshots["model_id"] == "gemini-3.6-flash"][
    ["snapshot_date", "input_price", "output_price", "change_vs_previous_snapshot"]
])
```

With pandas only:

```python
import pandas as pd

base = "https://huggingface.co/datasets/aicostbudget-ai/llm-api-price-history/resolve/main/"
snapshots = pd.read_csv(base + "price_snapshots.csv")
changes = pd.read_csv(base + "price_changes.csv")
```

## How to read price changes

Snapshots record what the dataset said on each day, so not every difference between two days is a provider price change. Every snapshot row is labeled:

| `change_vs_previous_snapshot` | Meaning |
| --- | --- |
| `first_seen` | First snapshot containing the model. This is when the model entered the dataset, not its launch date. |
| `unchanged` | Same scalar prices as the previous snapshot day. |
| `price_change` | Prices changed and a verified provider price-change event explains it; `price_change_event_id` links to the row in `price_changes`. |
| `dataset_revision` | Prices changed without a provider price-change event: a correction or re-audit of the dataset, not a provider price change. |

For price-change analysis, use `price_changes` or the `price_change` rows. Do not treat `dataset_revision` rows as market price movements.

Snapshots exist only on days the dataset was released, so there are gaps between snapshot days. When several releases happened on one day, the last one is used. History before 2026-07-05 is not included, and older prices are never back-filled from third-party sources.

## Files and fields

`price_snapshots.csv`

| Field | Meaning |
| --- | --- |
| `snapshot_date` | UTC day of the snapshot. |
| `snapshot_id` | Source snapshot in the [repository](https://github.com/aicostbudget/ai-api-pricing-data/tree/main/data/snapshots) (`YYYY-MM-DD` or `YYYY-MM-DD-N` for later same-day releases). |
| `provider_id`, `provider` | Provider identifier and display name. |
| `model_id`, `model` | Model identifier and display name. |
| `status` | Lifecycle status on that day: `active`, `preview`, `deprecated`, `retired`, or `unknown`. |
| `input_price`, `cached_input_price`, `output_price` | Standard prices per `unit`. |
| `batch_input_price`, `batch_output_price` | Batch prices per `unit` when published. |
| `cache_write_price` | Cache-write price per `unit` when published. |
| `currency`, `unit` | Currently USD; most rows use `1M tokens`, non-token APIs use their own unit. |
| `last_verified_at` | Date the record was last verified against its official source as of that snapshot. |
| `official_source_url` | Official provider page the price was verified against. |
| `change_vs_previous_snapshot` | See the table above. |
| `price_change_event_id` | Matching `price_changes.event_id` for `price_change` rows. |

`price_changes.csv`

| Field | Meaning |
| --- | --- |
| `event_id` | Stable event identifier. |
| `detected_at` | Day the change was first observed in the dataset. |
| `effective_from` | Provider-stated effective date when published. |
| `date_basis` | Whether the date is provider-stated or first observed. |
| `change_type` | `price_update`, `cached_price_added`, `cached_price_removed`, `component_price_update`, `temporal_price_schedule_update`, `model_added`, `lifecycle_update`, or `successor_transition`. |
| `old_*_price`, `new_*_price` | Input, cached-input, and output prices before and after the change; empty when not applicable. |
| `old_status`, `new_status` | Lifecycle status before and after, for lifecycle events. |
| `predecessor_model_id`, `successor_model_id` | Models linked by a successor transition. |
| `official_source_url`, `announcement_url` | Official pricing page and announcement, when available. |
| `verified_at` | Date the event was verified. |
| `notes` | Source context. |

Unknown or unpublished prices are empty; they are never rewritten as zero. Prices are scalar compatibility values; tiered, multimodal, and conditional pricing details are in the main dataset's `prices.json`.

## Source and method

Both files are generated deterministically from the committed snapshots and price-change events in the [AICostBudget pricing data repository](https://github.com/aicostbudget/ai-api-pricing-data) by `scripts/export_huggingface_history.py`. Prices are accepted only from official provider pricing pages, documentation, APIs, or announcements; see the [methodology](https://github.com/aicostbudget/ai-api-pricing-data/blob/main/METHODOLOGY.md).

## License and citation

Data is licensed under CC BY 4.0. Cite the dataset with your access date:

```text
AICostBudget. LLM API Price History. Hugging Face, https://huggingface.co/datasets/aicostbudget-ai/llm-api-price-history (accessed YYYY-MM-DD).
```

## Disclaimer

This dataset is informational. Prices can change, provider conditions vary, and verification may lag provider changes. Check official provider documentation before production billing decisions. AICostBudget is independent and is not affiliated with or endorsed by the listed providers. Provider names and trademarks belong to their respective owners.
