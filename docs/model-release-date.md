# Model release date contract

`released_at` is an optional `YYYY-MM-DD` date for the first official public availability of the exact canonical model/version. Public preview counts when it precedes GA; a later GA date does not replace that first availability date. Unknown day, model-family-only announcements, and rolling aliases without stable version identity remain null or absent.

A non-null date requires `release_evidence` with the official provider URL, source title, and evidence type (`official_release_announcement`, `official_changelog`, or `official_model_docs`). The release URL is registered in the generated official sources catalog and is linked by `releaseSourceRef`; it need not be a price source in `official_source_urls`. This fact is model metadata and cannot create a price event or alter price verification. `accessed_at`, `last_verified_at`, `effective_from`, website `checkedAt`, and Dataset first-seen dates are never release-date substitutes.

