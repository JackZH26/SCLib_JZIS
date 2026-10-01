# Materials recovery capture scan, 2026-10-02 R3

The initial redacted Gitleaks scan included all local Git refs and reported 26
`generic-api-key` occurrences across six fingerprints. Of these, 13 occurrences
and three fingerprints belong to the current R3 capture commit
`8b8b04fd048720f47917fc518e08b8089bf431be`: one in discovery, six in participant
and six in attestations. The other 13 belong to historical commit
`9291e394407501b8e7ea9b600823c9e2177eec64` on an unrelated local branch. Ancestry
inspection confirmed that commit is not an ancestor of the current HEAD. No
exception is added for it. The published-head scan uses `--log-opts=HEAD`;
all-local-refs scan counts must not be presented as current-branch findings.

Independent review checked every current R3 finding against its exact 1-based
inclusive scanner byte columns and recursively decoded JSON fields. Every span
is a `request_key` assignment whose value ends in valid RFC 4122 UUIDv4 hex.
The occurrence categories are one unprefixed ID, six
`synthetic-participation-`, three `synthetic-declaration-` and three
`synthetic-withdraw-` IDs. All decoded copies remain under `request_key` fields
in synthetic requests, controls, lookups and responses. No raw values or scan
payloads are published here.

The unchanged producers generate these test idempotency IDs with `uuid4().hex`:
`api/tests/test_discovery_main_barrier.py:436`, the participant producer's
imported `api/tests/test_ml_pilot_registration.py:142`, and
`api/tests/test_ml_pilot_attestations.py:56` and `:249`. These source files match
their original frozen upgrade bytes and the source pins in the genuine R3
captures. All seven committed R3 archives match the original native producer
output bytes and the exact hashes in the
[R3 manifest](capture-manifest-materials-2026-10-02-r3.json). The reviewed IDs are
not authentication, provider or session credentials. The private independent
review receipt SHA-256 is
`74964cbe8861d638f07cd4407e7a36707c7f0365a43a732d3604d5af9c46c15e`.

Only the three reviewed immutable commit/path/rule/line fingerprints are added
to `.gitleaksignore` and its exact static acceptance set:

```text
8b8b04fd048720f47917fc518e08b8089bf431be:frontend/tests/fixtures/discovery-main-barrier-native.materials20261002r3.wire.json:generic-api-key:1
8b8b04fd048720f47917fc518e08b8089bf431be:frontend/tests/fixtures/ml-pilot-attestations-native.materials20261002r3.wire.json:generic-api-key:1
8b8b04fd048720f47917fc518e08b8089bf431be:frontend/tests/fixtures/ml-pilot-participant-native.materials20261002r3.wire.json:generic-api-key:1
```

All earlier exceptions, archive bytes and source-pin assertions remain
unchanged. No path, directory, entire-commit or rule-wide exemption is added.
Future capture revisions require a fresh scan and exact review. Merge ancestry
must preserve the capture commit because the fingerprints bind its immutable
identity. The final published-head scan and CI results remain separate gates.
