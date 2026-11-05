# Archived price changes, 2024–2026

`data/archive-history/price-changes-2024-2026.v1.json` lists price changes that happened before this dataset started tracking a provider, or before a model was added to it. Each change was rebuilt from Internet Archive (Wayback Machine) captures of the provider's own pricing page, plus the provider's announcement when one exists.

This file is separate from `data/price-change-events/events.jsonl`. Most models in it are no longer listed in the main dataset, and the evidence is archived pages rather than captures we made ourselves, so these records do not go through the release gates for live events.

## What each record proves

Every record links two archived captures of the same official pricing page:

- `before_snapshot`: the last capture that still shows the old price
- `after_snapshot`: the first capture that shows the new price

Each capture has a short `quote` copied from the archived page text. The test in `tests/test_archive_price_changes.py` checks that every before and after price in the record appears in those quotes, and that each archive link matches its capture time.

`observed_window` is therefore an upper bound on uncertainty: the change happened somewhere between those two captures.

## Dates

- `date_basis: provider_announced` — the provider stated the date, either in an announcement or on the pricing page itself (for example "starting October 1st, 2024 it will reduce to $1.25"). `effective_from` holds that date.
- `date_basis: snapshot_window` — no dated announcement was found. `effective_from` is `null`; use `observed_window`.

## Change kinds

| `change_kind` | Meaning |
|---|---|
| `price_cut`, `price_increase`, `price_change` | The same model row changed price (`price_change` when some fields went up and others down) |
| `cached_price_added` | A cached-input price appeared for an existing row; `before` is `null` |
| `alias_repoint` | An alias (such as `gpt-4o` or `deepseek-chat`) started pointing to a different snapshot with a different price |
| `promo_start`, `promo_end` | A temporary discount started or ended |
| `preview_to_ga_reprice` | A preview row was replaced by the stable model at a different price |

Audio input prices that sit in the same row as a text price (Gemini's "text / image / video" and "audio" cached rates) are kept, because they changed together with the text price.

## Where the candidates came from

Evidence is always official: archived captures of the provider's pricing page, and the provider's announcement or changelog when there is one.

To find candidates we also read third-party price lists: the LiteLLM price file (monthly versions from January 2024), Pydantic's `genai-prices` and Simon Willison's llm-prices. Those were used only as leads. A lead became a record only after two official captures showed the change. Leads that did not hold up were dropped, for example:

- Claude Sonnet 5 launched on 2026-07-01 at an introductory $2 / $10 per 1M tokens, with $3 / $15 scheduled from September 1. Between 2026-08-01 and 2026-08-12 Anthropic cancelled the increase and made $2 / $10 the standard price. The billed price never changed, so this is not a record.
- Several LiteLLM changes for Gemini (robotics, image, TTS, native audio and `-latest` aliases) were corrections to LiteLLM's own data, not price changes.

## Gemini Batch caching

From 2025-09-03 to 2025-09-07 Google's pricing page changed the Batch-tier context caching price for Gemini 2.5 Pro, 2.5 Flash, 2.5 Flash-Lite and 2.0 Flash from half the standard rate to the full standard rate. These are recorded as `price_increase` with tier `paid tier, Batch`. A month later (2025-10) the standard caching price itself was cut for the 2.5 models; those cuts are separate records.

## What is not included

- New models or new dated snapshots launched at a different price than an older one. Those are launches, not price changes.
- Changes we could not confirm from two readable captures.
- Rows that were removed from a page (for example Gemini 2.0 Flash-Lite caching). Removal is not a price change.
- Image, audio-only, embedding and per-request prices. All records are USD per 1M tokens of text (plus audio input where it shares a row, see above).

## Coverage by provider

OpenAI, Anthropic and Google were checked across the whole period. What was checked, and what is still open:

- OpenAI
  - January to May 2024 and August 2024 to February 2025: `openai.com/pricing` and `openai.com/api/pricing` are readable.
  - June and July 2024: no readable capture. The last readable capture before (2024-05-31) and the first after (2024-08-02) show the same prices for all 20 rows they share, so no change in those rows was missed.
  - February 2025 to February 2026: the detailed price table was rendered by JavaScript. On the 2026-02-10 capture of `developers.openai.com/api/docs/pricing`, every text model launched or listed in that period (GPT-4.1, GPT-5, GPT-5.1, GPT-5.2, o-series and others) still shows its launch price, except o3, whose cut is recorded. A change that was later reversed could still be missing.
  - February to November 2026: `developers.openai.com/api/docs/pricing` was checked capture by capture. From March 2026 only the flagship table is readable; older models in the "All models" table are rendered by JavaScript.
- Anthropic: the `anthropic.com/api` pricing cards and the documentation models and pricing pages were checked from March 2024 to November 2026. January and February 2024 have no readable official page.
- Google: `ai.google.dev/pricing` (2024 to February 2025) and `ai.google.dev/gemini-api/docs/pricing` (February 2025 to November 2026) were checked for every text model row.
- Mistral: pricing page captures after October 2025 are not readable.
- xAI: the API page shows no prices before April 2025, and the docs site is JavaScript only.
- DeepSeek, Mistral and xAI were only checked on their main pricing pages; third-party leads were not followed up for them.

## Fields

`dataset_model_id` is `provider_id/model_id` from `data/canonical/models.json` when the same model is still listed; otherwise `null`. The full structure is in `schema/archive-price-change.schema.json`.
