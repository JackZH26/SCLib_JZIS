# September 15 immutable fixture scan review

Gitleaks scanned commit `a05fb46d83909107cdb221bbc5ac2c619edb4a49` after it existed.
The redacted report contains 51 generic-api-key matches across 11 immutable
single-line JSON fixture fingerprints. Every matched substring was checked
against the exact captured source columns: all are generated request_key values.
They are idempotency/recovery identifiers in disposable synthetic account tests,
not authentication credentials, source permissions or live bearer tokens.

Generators: `api/tests/test_discovery_main_barrier.py` uses uuid4().hex;
`api/tests/test_ml_pilot_attestations.py` prefixes synthetic-declaration and
synthetic-withdraw; `api/tests/test_ml_pilot_registration.py` prefixes
synthetic-pilot and synthetic-participation. Historical batch74/75/82 archives
and the new delivery20260915 archives retain their original bytes.

Only the 11 actual commit/path/rule/line fingerprints were added to
.gitleaksignore and its exact-set regression. Multiple matches on the same
immutable JSON line share a fingerprint. No rule-wide or path-wide exclusions
were added. The redacted original scan is retained privately as
`/private/tmp/sclib-delivery-20260915-cvlj6qk5/commit-scan.json`.
A clean follow-up scan must still complete before publication.
