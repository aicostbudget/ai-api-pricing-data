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

