# Declarative pricing contract

`price_records` is the canonical, lossless source for models that opt into the
new contract. Every price is explicit by processing mode, context class,
effective period, region scope, and charge. The V2 generator validates and
normalizes these records; it does not infer prices from provider, model, or
family names.

The existing top-level `pricing` object remains required as a deliberately
lossy V1 compatibility projection. For a model with `price_records`, validation
requires it to equal the current Standard short-context default plus the current
Batch short-context fields. It is not authoritative for modes, long-context
tiers, regional adjustments, or availability.

Region rules keep availability separate from price. `availability.rules` may
mark a selector unavailable, while `price_adjustments` may apply a positive,
source-backed decimal multiplier to a different selector. Contract selection
returns an explicit unavailable result when the requested mode, context,
endpoint geography, or data residency is unsupported. It never falls back to a
different mode, geography, or context tier.

Existing canonical formats (`pricing_tiers`, `time_pricing`,
`pricing_components`, and legacy token pricing) remain supported during staged
migration. Their generated production output is unchanged. A model should move
to `price_records` only after new-versus-legacy semantic parity is demonstrated.
