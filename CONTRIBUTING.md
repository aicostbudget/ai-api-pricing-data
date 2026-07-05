# Contributing

Thank you for helping improve the AICostBudget AI API Pricing Dataset.

## Source rules

Accepted final sources:

- Official provider pricing pages
- Official provider documentation
- Official provider APIs
- Official provider announcements

Not accepted as final sources:

- Third-party pricing calculators
- SEO blog posts
- Reddit or social posts
- Competitor comparison pages
- Unattributed screenshots

## Data rules

- Do not guess prices.
- Use `null` for unknown or unverified values.
- Do not use `0` unless an official source explicitly says the price is zero.
- Keep `official_source_url`, `accessed_at`, and `last_verified_at` current.
- Add a clear `notes` value when a provider has thresholds, modality-specific prices, regional pricing, cache rules, or temporary pricing.

## Development

```bash
python scripts/build.py
python scripts/validate.py
python -m pytest
```

Generated files should come from canonical files in `data/canonical/`.

