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
  - finops
  - openai
  - anthropic
  - gemini
configs:
  - config_name: default
    data_files:
      - split: train
        path: train.csv
---

# AI API Pricing Dataset

Source-linked AI API pricing data covering token, cache, batch, tiered, multimodal, and non-token pricing across multiple providers, including OpenAI, Anthropic, Google, xAI, DeepSeek, Mistral, and Cohere. These are examples, not an exhaustive provider list.

- [Live dataset and documentation](https://aicostbudget.com/en/datasets/ai-api-pricing)
- [Source repository](https://github.com/aicostbudget/ai-api-pricing-data)
- [Fixed v1.1.0 release (snapshot 2026-09-30)](https://github.com/aicostbudget/ai-api-pricing-data/releases/tag/v1.1.0)
- [Version DOI](https://doi.org/10.5281/zenodo.23087250)
- [Methodology](https://github.com/aicostbudget/ai-api-pricing-data/blob/main/METHODOLOGY.md)

This Hugging Face dataset is the machine-readable distribution of the public AI API pricing records published by AICostBudget. It is not a separately curated subset: `train.csv`, `prices.csv`, and `prices.json` are generated from the same Pricing V2 public projection used by the AICostBudget Dataset page and download APIs. The Hugging Face dataset mirrors that Pricing V2 public projection; GitHub Pages `/api/v1` is a separate compatibility projection and may have a different record count by design.

Prices change frequently. Verify production billing decisions against the provider pricing page, contract, billing dashboard, and invoice.

## Explore and download

Download `prices.json` or `prices.csv` from the [Hugging Face files](https://huggingface.co/datasets/aicostbudget-ai/ai-api-pricing/tree/main), or use the live dataset's [public JSON](https://aicostbudget.com/api/datasets/ai-api-pricing.json) and [public CSV](https://aicostbudget.com/api/datasets/ai-api-pricing.csv) downloads.

## Published files

- `train.csv`: a lightweight CSV projection consumed by the Hugging Face Dataset Viewer
- `prices.csv`: the complete normalized CSV download
- `prices.json`: metadata plus the complete public Website record set
- `meta.json`: generation time, verification date, and coverage counts for this export

`train.csv` intentionally omits the large serialized `pricing_tiers_json`, `time_pricing_json`, `pricing_components_json`, `conditional_usage_allowances_json`, and `model_selection_json` columns for Dataset Viewer usability. It preserves every exported model and all other CSV fields. Complete tier, time, component, conditional allowance, transport, alternative-measurement, optional-feature, and model-selection details remain available in `prices.csv` and `prices.json`. Schema 1.8.0 keeps eligibility-scoped short-term allowances separate from standard paid usage tiers.

Unknown or unavailable prices are `null` in JSON and empty in CSV; they are never rewritten as zero.

Access Policy V1 adds optional, independent access and identity-binding metadata. JSON exposes `access_status`, `access_checked_at`, official `access_evidence`, `binding_status`, and `binding_evidence`. CSV appends five columns after all existing columns: `access_status`, `access_checked_at`, `access_evidence_json`, `binding_status`, and `binding_evidence_json`. Consumers using named columns remain compatible; consumers assuming a fixed column count must accept these additions. Access verification timestamps are separate from price freshness. Access restrictions do not filter this factual pricing export. Older pinned exports without access metadata retain their original JSON and CSV contract when reproduced.


Hugging Face generates the Dataset Viewer and auto-converted Parquet from `train.csv` as convenience views. They are not an independent pricing source. Viewer and search indexing can lag behind the raw published artifacts, so use `prices.json`, `prices.csv`, and `meta.json` for the corresponding published version when displayed counts or dates differ.

The compact field guide below describes the public export. For structured pricing details, see the repository's [model schema](https://github.com/aicostbudget/ai-api-pricing-data/blob/main/schema/model.schema.json) and [pricing contract](https://github.com/aicostbudget/ai-api-pricing-data/blob/main/docs/pricing-contract.md).

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

The scalar input, cached-input, and output fields remain the compatibility/default pricing view. They are not deprecated. `pricing_components` represents conditions and units that one scalar cannot: context thresholds, batch and processing modes, cache writes, multimodal usage, tiered pricing, and non-token services. The [pricing contract](https://github.com/aicostbudget/ai-api-pricing-data/blob/main/docs/pricing-contract.md) defines the full structure.

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
- `last_verified_at` belongs to each record and means the price was verified against its source.
- `checked_at` records a source check that may not have reached verified status.
- `review_required` and `partially_verified` records keep `last_verified_at` empty; neither `checked_at` nor `generated_at` is substituted.
- Rebuilding this distribution does not rewrite record verification dates.
- Validation requires `generated_at >= max(last_verified_at)` and `generated_at >= max(checked_at)`, and rejects future timestamps.

For current coverage and timestamps, inspect `meta.json`. The source repository also contains schema checks, price validation, history, snapshots, and freshness workflows.

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
