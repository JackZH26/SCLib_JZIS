# Materials upgrade capture scan, 2026-10-01

Gitleaks reported 13 `generic-api-key` findings in commit
`f54eac6f28c655bad338ae726c571e6b97ac4c0c`: one in the discovery archive and
six each in the participant and attestations archives. Every finding was checked
against the exact committed bytes, scanner columns and recursively decoded JSON
fields. All 13 are `request_key` values with UUIDv4 hex suffixes: one unprefixed,
six `synthetic-participation-`, three `synthetic-declaration-` and three
`synthetic-withdraw-` identifiers. No identifier values or raw scan payloads are
published here.

Their native producers create these request IDs with `uuid4().hex` in
`api/tests/test_discovery_main_barrier.py`,
`api/tests/test_ml_pilot_registration.py` (used by the participant producer) and
`api/tests/test_ml_pilot_attestations.py`. They are disposable-test idempotency
keys, not authentication, provider or session credentials. The archive bytes
match the [capture manifest](capture-manifest-materials-2026-10-01.json).

Only these three immutable commit/path/rule/line fingerprints are added to
`.gitleaksignore` and its static acceptance contract:

```text
f54eac6f28c655bad338ae726c571e6b97ac4c0c:frontend/tests/fixtures/discovery-main-barrier-native.materials20261001.wire.json:generic-api-key:1
f54eac6f28c655bad338ae726c571e6b97ac4c0c:frontend/tests/fixtures/ml-pilot-attestations-native.materials20261001.wire.json:generic-api-key:1
f54eac6f28c655bad338ae726c571e6b97ac4c0c:frontend/tests/fixtures/ml-pilot-participant-native.materials20261001.wire.json:generic-api-key:1
```

Existing exceptions and archive contents remain unchanged. No path, directory,
commit or rule-wide exclusion is added; future fixture revisions require their
own scan and review.

Validation passed: the static security workflow suite reported 14 passed and one
skipped; Ruff and `git diff --check` passed. A redacted Gitleaks scan of
`origin/main..HEAD` covered both release commits through `f54eac6` and reported
no leaks. All seven archive hashes and 4,064 current source pins remained
unchanged after adding the exact exceptions. This branch scan is distinct from
an all-history scan.
