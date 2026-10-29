---
pretty_name: "LLM API Pricing Dataset: GPT, Claude, Gemini, Grok, DeepSeek, Qwen token prices"
license: cc-by-4.0
language:
  - en
size_categories:
  - n<1K
tags:
  - llm
  - pricing
  - llm-pricing
  - llm-api-pricing
  - api-pricing
  - ai-api-pricing
  - ai-model-pricing
  - token-pricing
  - token-cost
  - pricing-data
  - openai
  - anthropic
  - gemini
  - gpt
  - claude
  - grok
  - deepseek
  - qwen
  - mistral
  - cohere
  - finops
  - ai-finops
  - tabular
configs:
  - config_name: default
    data_files:
      - split: train
        path: train.csv
---

# LLM API Pricing Dataset

Prices per 1M tokens for about 100 LLM and AI API models from OpenAI, Anthropic, Google, xAI, DeepSeek, Mistral, Cohere, Moonshot AI, Alibaba Qwen, Meta, and other providers. These are examples, not an exhaustive provider list. Every row links to the official provider pricing page it was verified against and carries its own `last_verified_at` date. Prices are updated as providers change them.

| | |
| --- | --- |
| Rows | One row per public model (about 100) |
| Prices | Input, cached input, and output per 1M tokens in USD, plus non-token units such as pages, characters, and images |
| Beyond list prices | Cache, batch, long-context tiers, multimodal, and time-of-day pricing in `prices.json` / `prices.csv` |
| Evidence | Official source URL and verification date on every row; unknown prices stay empty, never zero |
| License | CC BY 4.0 |

**Estimate your own bill:** compare two models with your token counts and success rates in the [Model Switch Cost Calculator](https://aicostbudget.com/en/model-switch-cost-calculator?utm_source=huggingface&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=card_intro), or see the [cheapest LLM APIs right now](https://aicostbudget.com/en/cheapest-llm-api?utm_source=huggingface&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=card_intro).

- [Live dataset and documentation](https://aicostbudget.com/en/datasets/ai-api-pricing)
- [Source repository](https://github.com/aicostbudget/ai-api-pricing-data)
- [Fixed v1.1.0 release (snapshot 2026-09-30)](https://github.com/aicostbudget/ai-api-pricing-data/releases/tag/v1.1.0)
- [Version DOI](https://doi.org/10.5281/zenodo.23087250)
- [Methodology](https://github.com/aicostbudget/ai-api-pricing-data/blob/main/METHODOLOGY.md)
- [Price history: dated snapshots and verified price changes](https://huggingface.co/datasets/aicostbudget-ai/llm-api-price-history)
- [LLM API Pricing Calculator Space](https://huggingface.co/spaces/aicostbudget-ai/llm-api-pricing-calculator) and the [LLM API Pricing & Cost collection](https://huggingface.co/collections/aicostbudget-ai/llm-api-pricing-and-cost-6ae3690fbe696553bf43f16a)

Prices change frequently. Verify production billing decisions against the provider pricing page, contract, billing dashboard, and invoice.

## Quick start

```python
import pandas as pd

url = (
    "https://huggingface.co/datasets/"
    "aicostbudget-ai/ai-api-pricing/resolve/main/train.csv"
)

pricing = pd.read_csv(url)

# Ten cheapest token-priced models by output price
token_rows = pricing.dropna(subset=["output_price_per_1m_tokens"])
print(
    token_rows.sort_values("output_price_per_1m_tokens")[
        ["provider", "model", "input_price_per_1m_tokens", "output_price_per_1m_tokens"]
    ].head(10)
)
```

With Hugging Face Datasets:

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

## Use it from code or an AI assistant

- **JavaScript / TypeScript:** `npm install ai-api-pricing` looks up prices, lists models, and estimates or compares workload costs. Every returned price includes its official source URL and verification date. ([npm package](https://www.npmjs.com/package/ai-api-pricing))
- **AI assistants (MCP):** `npx -y ai-api-pricing-mcp` runs a read-only MCP server with tools for model prices, filtered model lists, monthly cost estimates, comparisons, and recent price changes. It is listed in the official MCP Registry as `io.github.aicostbudget/ai-api-pricing-mcp` and on [Glama](https://glama.ai/mcp/servers/aicostbudget/ai-api-pricing-data). ([npm package](https://www.npmjs.com/package/ai-api-pricing-mcp))

Both packages read the GitHub Pages `/api/v1` compatibility projection described in the technical notes below. Source code: [packages/](https://github.com/aicostbudget/ai-api-pricing-data/tree/main/packages).

## Compare pricing with your workload

The [Model Switch Cost Calculator](https://aicostbudget.com/en/model-switch-cost-calculator?utm_source=huggingface&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=card_workload) compares API costs for two models based on your input and output tokens, monthly request volume, and assumed success rates. It estimates monthly spending, cost per successful task, and the break-even success rate for a model switch.

The results depend on your inputs and assumptions. The tool does not benchmark model quality, measure actual success rates, automate routing, or guarantee savings.

To measure success rates on your own models, use the open [LLM cost-per-task benchmark](https://github.com/aicostbudget/llm-cost-per-task-benchmark): 16 tasks with code-only validators, run with your own API keys and priced from this dataset.

## Published files

- `train.csv`: a lightweight CSV projection consumed by the Hugging Face Dataset Viewer
- `prices.csv`: the complete normalized CSV download
- `prices.json`: metadata plus the complete public Website record set
- `meta.json`: generation time, verification date, and coverage counts for this export

Download them from the [Hugging Face files](https://huggingface.co/datasets/aicostbudget-ai/ai-api-pricing/tree/main), or use the live dataset's [public JSON](https://aicostbudget.com/api/datasets/ai-api-pricing.json) and [public CSV](https://aicostbudget.com/api/datasets/ai-api-pricing.csv) downloads.

```text
https://huggingface.co/datasets/aicostbudget-ai/ai-api-pricing/resolve/main/train.csv
https://huggingface.co/datasets/aicostbudget-ai/ai-api-pricing/resolve/main/prices.csv
https://huggingface.co/datasets/aicostbudget-ai/ai-api-pricing/resolve/main/prices.json
https://huggingface.co/datasets/aicostbudget-ai/ai-api-pricing/resolve/main/meta.json
```

`train.csv` lists the most-searched providers first and intentionally omits the large serialized `pricing_tiers_json`, `time_pricing_json`, `pricing_components_json`, `conditional_usage_allowances_json`, `model_selection_json`, `access_evidence_json`, and `binding_evidence_json` columns for Dataset Viewer usability. It preserves every exported model and all other CSV fields. Complete tier, time, component, conditional allowance, transport, alternative-measurement, optional-feature, model-selection, and access-evidence details remain available in `prices.csv` and `prices.json`. Schema 1.8.0 keeps eligibility-scoped short-term allowances separate from standard paid usage tiers.

Unknown or unavailable prices are `null` in JSON and empty in CSV; they are never rewritten as zero.

Hugging Face generates the Dataset Viewer and auto-converted Parquet from `train.csv` as convenience views. They are not an independent pricing source. Viewer and search indexing can lag behind the raw published artifacts, so use `prices.json`, `prices.csv`, and `meta.json` for the corresponding published version when displayed counts or dates differ.

## Fields

| Field | Meaning |
| --- | --- |
| `provider_id` | Stable provider identifier. |
| `provider` | Human-readable provider name. |
| `model_id` | Stable public model identifier. |
| `model` | Human-readable model name. |
| `input_price_per_1m_tokens` | Standard input-token price per 1M tokens. |
| `cached_input_price_per_1m_tokens` | Compatibility/default cached-input or read-like scalar when available; provider cache semantics can differ. |
| `output_price_per_1m_tokens` | Standard output-token price per 1M tokens. |
| `currency` | Pricing currency; current records use USD. |
| `pricing_unit` | Normalized unit; current records use 1M tokens. |
| `status` | Public lifecycle/status label from the Website projection or marked fallback. |
| `availability` | Public availability label. |
| `official_source_url` | Provider source used by the verified pricing pipeline. |
| `verification_status` | Canonical record status such as `verified`, `review_required`, or `partially_verified`. |
| `last_verified_at` | Record verification date; it is not refreshed merely because an artifact is rebuilt. |
| `checked_at` | Date the source was checked, kept separate from verification. |
| `effective_from` | Provider-stated effective date when available. |
| `effective_until` | End date when a selected price record has one. |
| `notes` | Source context, projection warning, or legacy fallback warning. |
| `pricing_tier_count` | Number of structured context-dependent pricing tiers. |
| `pricing_tiers` | JSON-only structured tier records, including thresholds and source references. |
| `pricing_tiers_json` | CSV-only lossless JSON serialization of `pricing_tiers`; `[]` when no tiers apply. |
| `pricing_components` | JSON-only full conditional pricing representation: component, decimal-string amount, conditions, effective range, source IDs and URLs, and verification status; `[]` when none apply. |
| `pricing_components_json` | Final CSV column containing the same `pricing_components` array as compact deterministic JSON; `[]` when none apply. |

The scalar input, cached-input, and output fields remain the compatibility/default pricing view. They are not deprecated. `pricing_components` represents conditions and units that one scalar cannot: context thresholds, batch and processing modes, cache writes, multimodal usage, tiered pricing, and non-token services. The [pricing contract](https://github.com/aicostbudget/ai-api-pricing-data/blob/main/docs/pricing-contract.md) defines the full structure. For structured pricing details, see the repository's [model schema](https://github.com/aicostbudget/ai-api-pricing-data/blob/main/schema/model.schema.json).

Access Policy V1 adds optional, independent access and identity-binding metadata. JSON exposes `access_status`, `access_checked_at`, official `access_evidence`, `binding_status`, and `binding_evidence`. CSV appends five columns after all existing columns: `access_status`, `access_checked_at`, `access_evidence_json`, `binding_status`, and `binding_evidence_json`. Consumers using named columns remain compatible; consumers assuming a fixed column count must accept these additions. Access verification timestamps are separate from price freshness. Access restrictions do not filter this factual pricing export. Older pinned exports without access metadata retain their original JSON and CSV contract when reproduced.

## Freshness semantics

- `generated_at` is the artifact generation timestamp copied from the checked-in pricing metadata.
- `last_verified_at` belongs to each record and means the price was verified against its source.
- `checked_at` records a source check that may not have reached verified status.
- `review_required` and `partially_verified` records keep `last_verified_at` empty; neither `checked_at` nor `generated_at` is substituted.
- Rebuilding this distribution does not rewrite record verification dates.
- Validation requires `generated_at >= max(last_verified_at)` and `generated_at >= max(checked_at)`, and rejects future timestamps.

For current coverage and timestamps, inspect `meta.json`. The source repository also contains schema checks, price validation, history, snapshots, and freshness workflows.

## Technical notes: how this export is built

This Hugging Face dataset is the machine-readable distribution of the public AI API pricing records published by AICostBudget. It is not a separately curated subset: `train.csv`, `prices.csv`, and `prices.json` are generated from the same Pricing V2 public projection used by the AICostBudget Dataset page and download APIs. The Hugging Face dataset mirrors that Pricing V2 public projection; GitHub Pages `/api/v1` is a separate compatibility projection and may have a different record count by design.

The export is deterministic:

1. Start from the checked-in Pricing V2 Website projection.
2. Exclude compatibility aliases because they are not independent public pricing rows.
3. Exclude rows marked `excluded_default_candidate` by the verified pricing pipeline.
4. Preserve Website legacy fallback rows only when the public Pricing Table adapter still exposes them, including the warning that they are not default-safe verified prices.
5. Export exactly the resulting public Website key set; no provider, family, or status-specific allowlist is maintained for Hugging Face.

The canonical provider and pricing facts live in the [AICostBudget pricing data repository](https://github.com/aicostbudget/ai-api-pricing-data). Website-owned legacy display metadata is used only for explicitly marked fallback rows. The exporter does not fetch or guess prices.

## Methodology and contributions

- [Methodology](https://github.com/aicostbudget/ai-api-pricing-data/blob/main/METHODOLOGY.md)
- [Contributing](https://github.com/aicostbudget/ai-api-pricing-data/blob/main/CONTRIBUTING.md)
- [Data license](https://github.com/aicostbudget/ai-api-pricing-data/blob/main/LICENSE-DATA)
- [Code license](https://github.com/aicostbudget/ai-api-pricing-data/blob/main/LICENSE-CODE)

Dataset data is licensed under CC BY 4.0; repository code is licensed under MIT. The front matter license applies to the dataset data.

Prices are accepted from official provider pricing pages, documentation, APIs, or announcements. Third-party aggregators and search snippets are not final price evidence.

## Citation

For reproducible analysis, cite the frozen v1.1.0 release and its version DOI (snapshot 2026-09-30). The live dataset and Hugging Face `main` can change after that snapshot; for latest operational use, cite the live dataset with your access date instead. This is a version DOI, not a claim that it identifies the latest dataset.

```text
AICostBudget. AICostBudget AI API Pricing Dataset, v1.1.0, snapshot 2026-09-30.
Version DOI: 10.5281/zenodo.23087250
DOI: https://doi.org/10.5281/zenodo.23087250
GitHub Release: https://github.com/aicostbudget/ai-api-pricing-data/releases/tag/v1.1.0
Canonical live dataset: https://aicostbudget.com/en/datasets/ai-api-pricing
```

```bibtex
@misc{aicostbudget_2026_v110,
  author = {{AICostBudget}},
  title = {AICostBudget AI API Pricing Dataset},
  year = {2026},
  version = {1.1.0},
  doi = {10.5281/zenodo.23087250},
  url = {https://doi.org/10.5281/zenodo.23087250},
  note = {Snapshot 2026-09-30}
}
```

For the changing dataset, record the access date and inspect `meta.json` for export generation and aggregate verification timestamps. Record-level verification remains in each row's `last_verified_at`; do not replace it with the access date or `generated_at`.

## Disclaimer

This dataset is informational. Prices can change, provider conditions vary, and verification timestamps may lag provider changes. Check official provider documentation before production billing decisions. AICostBudget is independent and is not affiliated with or endorsed by the listed providers. Provider names and trademarks belong to their respective owners.

If this dataset saves you time, consider liking it on Hugging Face so you can find future pricing updates more easily.
