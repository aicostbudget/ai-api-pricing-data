# Billing Unit vNext decision (2026-08-29)

## Decision

Keep the public V1 token columns unchanged. Continue to use
`input_price_per_1m_tokens`, `cached_input_price_per_1m_tokens`, and
`output_price_per_1m_tokens` only for token prices. Extend the internal V2
charge-unit vocabulary additively so later records can express
`per_1000_pages`, `per_minute`, `per_second`, `per_image`, and `per_request`.
A future public schema can expose these records through structured pricing
components while retaining the V1 scalar columns as nullable compatibility
fields.

## Gemini 3.6 and 3.7 consumption-option coverage

The public V1 scalar contract continues to describe the current Standard
token prices. Structured V2 PriceRecords cover Standard and Batch across the
2026 introductory and 2027 standard-price periods. Batch context-cache reads
are included as `cached_input` charges on the Batch PriceRecords; their values
are USD 0.0375 per 1M tokens through 2026-12-31 and USD 0.075 starting
2027-01-01. The canonical source field is `batch_cached_input`.

Flex and Priority are intentionally not covered in this hotfix. Although V2
can represent their processing modes and token charges, adding them would
expand the product's currently implemented Standard/Batch coverage and needs a
separate consumer/default-selection decision. Flex currently matches Batch
pricing. Priority is USD 1.35 input, USD 0.135 cached input, and USD 6.75 output
per 1M tokens through 2026-12-31, changing to USD 2.70, USD 0.27, and USD 13.50
on 2027-01-01. Cache-storage, grounding, and other separately billed features
also remain outside the current scalar contract.

The Dataset and pricing pages must therefore be described as Standard plus
Batch coverage, not complete coverage of every Google consumption option.

## Cohere Parse v5

Cohere documents `parse-v5.0` at USD 1.50 per 1,000 pages. The current
canonical V1 model schema requires `pricing.unit = "1M tokens"`, so Parse is
not added to the formal Dataset in this hotfix. No token price field is
populated for it. The official sources are:

- https://docs.cohere.com/changelog/parse
- https://docs.cohere.com/v2/docs/parse
- https://cohere.com/blog/parse

## Gemini Omni Flash

Google released `gemini-omni-1.1-flash` GA on 2026-08-27 and announced that
`gemini-omni-flash-preview` will be deprecated on 2026-09-30. Standard input
is USD 1.50 per 1M text/image/video/audio tokens; output is modality-dependent:
USD 9.00 per 1M text tokens and USD 17.50 per 1M video tokens, with video also
described as approximately USD 0.10 per second at 720p. A single V1
`output_price_per_1m_tokens` value cannot represent that safely, so neither
Omni identity is added to the ordinary token table in this hotfix. Lifecycle
and pricing evidence remain documented here until a structured multi-unit,
multi-modality public contract is adopted.

Official sources: https://ai.google.dev/gemini-api/docs/changelog,
https://ai.google.dev/gemini-api/docs/models/gemini-omni-flash, and
https://ai.google.dev/gemini-api/docs/pricing.
