# Genuine final R7 scan, 2026-10-02

The explicit-HEAD redacted Gitleaks 8.30.1 scan at immutable final-source capture
commit `f4f3eba860bb7b4f4f00a2beb4829a167198707a` scanned 631 commits and
117.39 MB in 58.9 seconds. It reported **12 generic-api-key occurrences and two
exact fingerprints**: six participant and six attestation occurrences. The
discovery archive has no finding in this scan; no exception is added for it.
The report SHA-256 is
`9e8cd011bd6b9746bd263efd66298fd20f7d80de2de0e29c5737427b6fbc591f`.
This scan covers the exact branch ancestry, not unrelated local refs.

Root and an independent read-only reviewer checked all one-based inclusive
committed-byte spans and recursively decoded their JSON. Every terminal copy
is a `request_key` field ending in RFC 4122 UUIDv4 hex from unchanged test
producers. Categories are six `synthetic-participation-`, three
`synthetic-declaration-` and three `synthetic-withdraw-` occurrences. No raw
identifier is published. They are synthetic idempotency keys, not provider,
session or authentication credentials.

Their immutable stdlib `uuid4().hex` generators remain in
`api/tests/test_ml_pilot_registration.py:142` and
`api/tests/test_ml_pilot_attestations.py:56` and `:249`, with the same source bytes
as R6. All seven committed archives match genuine native outputs and manifest
sizes/hashes. All 4,123 pins match 635 committed inputs; five packaged resources
were verified separately. The root metadata-only receipt SHA-256 is
`fc423030e371745129198711bc95dbcb74266654d6f7ce3f79bfa52bcf95d59b`;
the independent receipt SHA-256 is
`7efb74fb70f8b8b40940f512c4c82ce1b6f40a58f327c4449b765630985707ae`.

Only the actual two reviewed findings enter the exact ignore and static
acceptance sets:

```text
f4f3eba860bb7b4f4f00a2beb4829a167198707a:frontend/tests/fixtures/ml-pilot-attestations-native.materials20261002r7.wire.json:generic-api-key:1
f4f3eba860bb7b4f4f00a2beb4829a167198707a:frontend/tests/fixtures/ml-pilot-participant-native.materials20261002r7.wire.json:generic-api-key:1
```

Prior exclusions and capture bytes remain unchanged. There is no path, rule
or directory wildcard. Merge ancestry must preserve the capture commit bound
by these fingerprints. Final-head scanning, exact-head CI, signed release and
public production acceptance are separate gates. This synthetic-fixture triage
does not confer scientific review, source permission or candidate promotion.
