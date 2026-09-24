# Materials native capture secret-scan triage, 2026-09-24

Gitleaks scanning commit `128331840e8b8e3756262156df345e7e68f216a5` reported 13 generic-api-key matches in three newly retained native capture files. Every matched field is request_key. Decoding the retained JSON and embedded JSON responses verified every matched value against its exact synthetic request-key field: UUID hex identifiers, optionally prefixed synthetic-declaration-, synthetic-participation- or synthetic-withdraw-. These are disposable-test idempotency keys, not credentials. The unredacted report was inspected locally and not published.

The three affected capture producers are test_discovery_main_barrier.py, test_ml_pilot_attestations.py and test_ml_pilot_participant_wire.py. Unmodified archive hashes and all current source pins are recorded in capture-manifest-materials-2026-09-24.json. The fixture notices identify synthetic records. Older captures and their hash assertions remain unchanged.

Only the following immutable commit/file/rule/line fingerprints are added to .gitleaksignore and its existing acceptance test. No rule or path wildcard is excluded; no production authentication/security setting is changed. The matching payloads and scanner scope were checked before adding these entries.

- `128331840e8b8e3756262156df345e7e68f216a5:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260924r2.wire.json:generic-api-key:1`
- `128331840e8b8e3756262156df345e7e68f216a5:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260924r2.wire.json:generic-api-key:1`
- `128331840e8b8e3756262156df345e7e68f216a5:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260924r2.wire.json:generic-api-key:1`
