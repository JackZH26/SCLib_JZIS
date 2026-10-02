# Materials condition-correction capture scan, 2026-10-02 R5

The redacted Gitleaks scan of explicit `HEAD` at immutable capture commit
`44872224e1a75ae36e9863ed756df0d7471d424e` scanned 626 commits and 113.68 MB in
56.4 seconds. It reported 13 `generic-api-key` occurrences across three exact
fingerprints. This scan covers the published-branch ancestry, not unrelated
local refs. No exception is added for another branch, path, directory or rule.

Root and a separate read-only reviewer inspected every exact 1-based inclusive
committed-byte span and recursively decoded its JSON. All spans are
`request_key` assignments ending in RFC 4122 UUIDv4 hex from unchanged test
producers. Categories are one unprefixed ID, six `synthetic-participation-`,
three `synthetic-declaration-` and three `synthetic-withdraw-` IDs. The findings
are one discovery occurrence, six participant occurrences and six attestation
occurrences. All decoded terminal copies are exactly `request_key` fields in
synthetic requests, lookups, controls or responses; no raw IDs are published.

Their generators are `uuid4().hex` in
`api/tests/test_discovery_main_barrier.py:436`,
`api/tests/test_ml_pilot_registration.py:142`, and
`api/tests/test_ml_pilot_attestations.py:56` and `:249`. These files retain their
original source bytes. The reviewed values are test idempotency keys, not
authentication, provider or session credentials. All seven committed R5
archives match the genuine native output and committed manifest; all 4,123
source-pin entries match the committed source. The independent metadata-only
review receipt SHA-256 is
`51ba8aec21ae0f8a08a99c3174ee6d36aea14a94b1bbd4f79f87fe16a07f3def`;
the redacted scanner report SHA-256 is
`56ff28193120ee3e73060010de35c08930612a01995827414b74d6e3f19893a4`.

Only these three reviewed immutable commit/path/rule/line fingerprints are
added to `.gitleaksignore` and the exact static acceptance set:

```text
44872224e1a75ae36e9863ed756df0d7471d424e:frontend/tests/fixtures/discovery-main-barrier-native.materials20261002r5.wire.json:generic-api-key:1
44872224e1a75ae36e9863ed756df0d7471d424e:frontend/tests/fixtures/ml-pilot-attestations-native.materials20261002r5.wire.json:generic-api-key:1
44872224e1a75ae36e9863ed756df0d7471d424e:frontend/tests/fixtures/ml-pilot-participant-native.materials20261002r5.wire.json:generic-api-key:1
```

All previous exclusions, capture bytes, source pins and literal assertions
remain unchanged. A future capture requires a fresh scan and exact independent
review. Merge ancestry must preserve this capture commit because the
fingerprints bind its immutable identity. Final-head scanning and formal CI
remain separate gates; these reviewed synthetic fixtures confer no scientific
acceptance, source permission or data-release authority.
