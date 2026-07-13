# API versioning and compatibility

The public API major version is part of the URL:
`https://api.jzis.org/sclib/v1`. Responses also include
`X-API-Version: 1`, and `/v1/version` reports the same value.

Within v1, SCLib may make additive changes: add optional request fields, add
response fields, add endpoints, or add enum values when clients are expected to
handle unknown values. Existing fields do not change meaning or type within the
major version. Removing or renaming fields, changing field types, or changing
endpoint semantics requires a new major URL such as `/v2`.

Deprecated v1 operations remain available for at least 180 days after public
notice. During that window they return the standard `Deprecation`, `Sunset`,
and `Link` headers pointing to migration guidance. Security fixes may require a
shorter window; such an exception must be documented in the security advisory.

Errors preserve FastAPI's legacy `detail` field and add stable `error_code` and
`request_id` fields. Every response returns the same request ID in the
`X-Request-ID` header. Clients should branch on `error_code`, log `request_id`,
and treat human-readable detail text as non-contractual.
