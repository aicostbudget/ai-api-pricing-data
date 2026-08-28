# Methodology

The goal of this dataset is to provide high-trust, machine-readable AI API pricing data.

## Source hierarchy

1. Official provider pricing page
2. Official provider documentation
3. Official provider API
4. Official provider announcement

No third-party source is used as a final price authority.

## Normalization

Prices are normalized to USD per 1M tokens when the official source provides token prices. The canonical fields are:

- `input`
- `output`
- `cached_input`
- `cache_write`
- `batch_input`
- `batch_output`

When a provider exposes multiple thresholds, the lowest standard public threshold may be stored in the numeric field and the threshold details are recorded in `notes`. When a value cannot be confirmed from the official source, it is `null`.

### Pricing V2 context tiers

Canonical models with explicit context-dependent prices use `pricing_tiers`. A tier is selected by its `prompt_token_threshold` and `threshold_comparison`, never by array order. `less_than` is an exclusive maximum and `greater_than_or_equal` is an inclusive minimum. `calculation_default` identifies the fallback tier when no non-default rule matches.

`threshold_token_basis: total_prompt_tokens` counts all prompt tokens. `cached_prompt_tokens_included: true` makes cached prompt tokens part of that total. `whole_request_pricing: true` means the selected tier prices every input, cached-input, and output token in the request; pricing is not applied only to tokens beyond the threshold.

The V2 `PriceRecord` projection preserves these facts in `contextClass`, `promptTokenThreshold`, and `tierSelection`. Current standard IDs follow `price:<provider>/<model>:standard:<context>:current`.

### Pricing V2 components

The Website and Hugging Face public export schema 1.3.0 publishes `pricing_components` as the detailed conditional pricing representation. Each component combines `component`, a decimal-string `amount`, `unit`, `currency`, `modality`, calculation conditions, provenance, verification status, and an effective range. The corresponding final CSV column, `pricing_components_json`, is a compact deterministic serialization of the same array.

Scalar input, cached-input, and output fields remain the compatibility/default pricing view. Components do not replace them. A model can expose both `cache_write_5m` and `cache_write_1h`, or distinct `cache_write` charges by processing mode and context class. The public structure is therefore component-oriented rather than cache-specific and can also represent storage, request, tool-call, and grounding charges.

Components are ordered by `pricing_id` and then `charge_id`. Canonical source IDs remain in `source_refs`, and `source_urls` provides the corresponding resolvable official URLs. An absent component set is represented consistently as `[]` in JSON and as the JSON text `[]` in CSV.

## Dates

- `accessed_at` records when the source was accessed.
- `last_verified_at` records when the value was last checked against the official source.
- `effective_from` records a provider-stated effective date when available.

## Reproducibility

The canonical data lives in:

```text
data/canonical/providers.json
data/canonical/models.json
```

Generated outputs are created with:

```bash
python scripts/build.py
```

Validation checks schema presence, duplicate IDs, timestamp format, official source URLs, negative prices, JSON/CSV consistency, API parseability, and reproducibility.
