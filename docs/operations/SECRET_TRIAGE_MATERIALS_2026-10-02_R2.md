# Scientific reference capture scan, 2026-10-02 R2

Gitleaks reported 13 `generic-api-key` findings in immutable commit
`5b6e90305f6e783ec1127827b6f4bcc7c06f720f`: one discovery request ID and six
each in the participant and attestations archives. Independent review checked
the exact inclusive scanner byte spans, committed archive bytes and recursively
decoded JSON fields. All findings are `request_key` values ending in valid
UUIDv4 hex: one unprefixed, six `synthetic-participation-`, three
`synthetic-declaration-` and three `synthetic-withdraw-` IDs. Raw values and scan
payloads are not published here.

The unchanged native producers generate these idempotency IDs with
`uuid4().hex`: `api/tests/test_discovery_main_barrier.py:436`, the participant
producer's imported `api/tests/test_ml_pilot_registration.py:142`, and
`api/tests/test_ml_pilot_attestations.py:56` and `:249`. Repeated IDs remain under
`request_key` fields in synthetic request, lookup, response and control data.
These are not authentication, provider or session credentials. Committed bytes
match both the original native output and the exact hashes in the
[capture manifest](capture-manifest-materials-2026-10-02-r2.json).

Only three immutable commit/path/rule/line fingerprints are added to
`.gitleaksignore` and its exact static acceptance set:

```text
5b6e90305f6e783ec1127827b6f4bcc7c06f720f:frontend/tests/fixtures/discovery-main-barrier-native.materials20261002r2.wire.json:generic-api-key:1
5b6e90305f6e783ec1127827b6f4bcc7c06f720f:frontend/tests/fixtures/ml-pilot-attestations-native.materials20261002r2.wire.json:generic-api-key:1
5b6e90305f6e783ec1127827b6f4bcc7c06f720f:frontend/tests/fixtures/ml-pilot-participant-native.materials20261002r2.wire.json:generic-api-key:1
```

All earlier exceptions, archive bytes and source-pin assertions are retained.
No path, directory, entire commit or rule-wide exemption is added. Future
capture revisions require another scan and exact review. Merge ancestry must
be preserved because these fingerprints bind the original capture commit.
