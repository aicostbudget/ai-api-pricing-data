# Price change events

Canonical price change events are stored in:

```text
data/price-change-events/events.jsonl
```

A price change event is different from a normal history verification row. History rows record source verification state for a model and may change when `last_verified_at`, `official_source_url`, or notes change. Price change events record verified scalar pricing semantics between two trusted snapshots and can also emit `component_price_update` when matching `pricing_id + charge_id` entries change amount while scalar prices remain unchanged. Component events preserve the component name, old and new decimal-string amounts, and condition. Component additions/removals are not treated as price launches because they may reflect coverage changes.

Baseline snapshots are not price changes. New snapshots, reordered files, source URL edits, status changes, or repeated verification dates must not create price change events when the prices are unchanged.

Date fields use separate meanings:

- `effective_from`: provider-announced effective date only. It stays `null` when the provider did not publish one.
- `detected_at`: the first snapshot date where the repository observed the change by comparing trusted snapshots.
- `verified_at`: the date the new price was checked against an official provider source.
- `date_basis`: one of `provider_announced`, `official_changelog`, `first_observed`, or `unknown`.

Preview events without writing:

```bash
python scripts\generate_price_change_events.py --before data\snapshots\2026-07-09\prices.json --after data\snapshots\2026-07-27\prices.json --dry-run
```

Generate the canonical JSONL projection:

```bash
python scripts\generate_price_change_events.py --before data\snapshots\2026-07-09\prices.json --after data\snapshots\2026-07-27\prices.json
```

The generator matches models by `provider_id + model_id`, compares only pricing semantics, writes stable sorted output, and merges by `dedupe_key`. The first version emits `price_update`, `cached_price_added`, and `cached_price_removed`; it does not emit `pricing_added` or `pricing_removed` because a model first appearing in a snapshot may be coverage expansion rather than an official pricing launch. The dedupe key is based on provider, model, old prices, new prices, unit, currency, and change type. It excludes `verified_at`, `announcement_url`, and notes so later metadata backfills update the same event instead of creating a duplicate.

Both source snapshots must already be tracked by Git before event generation. The generator fails closed rather than writing a canonical event that depends on an ignored, untracked, or local-only snapshot.

Manual backfills should edit the existing event with the same `dedupe_key`. Add `effective_from` only when an official provider announcement, official changelog, or pricing page explicitly gives the effective date. Add `announcement_url` only for an official URL; do not invent one.

Do not copy a fixed event count into documentation or product code. The validated records in `data/price-change-events/events.jsonl` are the authoritative current count.

Publication readiness is determined from the current event file: require at least 5 real price changes, at least 3 providers covered, an official source plus `detected_at` and `verified_at` for every event, explicit marking of unknown effective dates, and no inferred old prices. Passing these gates supports a recent verified price-changes feed; it does not by itself establish deep multi-year Pricing History coverage.
