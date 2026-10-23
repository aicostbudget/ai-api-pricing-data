# Public downloadable pricing contract 1.11.0

Website JSON/full CSV and HF downloadable JSON/prices.csv share logical
records keyed by provider_id+model_id and the same pricing, tier, component,
access/binding and provenance meanings. HF train.csv is a reduced Viewer
projection; it must preserve the keyset and scalar meanings but intentionally
omits large serialized fields. Metadata may add HF features and
last_verified_at aliases; notes may use an empty string versus null. These
format-specific differences are not pricing parity exceptions.

Schema 1.11.0 additively extends `pricing_components[].unit` with
`per_1m_characters`. This unit means the published amount is charged per
1,000,000 input text characters, with `billing_quantity` equal to 1,000,000.
It is not a token or time unit and must not be converted into tokens or
minutes. The V1 token-price scalar columns remain null for character-priced
records. Consumers that reject unknown unit enum values must opt into 1.11.0.

Schema 1.10.0 introduced the generic optional
`pricing_components[].condition.promotion` contract. Historical 1.8, 1.9 and
1.10 releases remain pinned to their original version and bytes; release
reconstruction selects the version from the committed mirror and never
relabels history.

All other field meanings, format mappings, date distinctions, compatibility
rules, lifecycle safety policy, and narrowly enumerated historical mappings
remain as documented by the 1.10.0 contract.
