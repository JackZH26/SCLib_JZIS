# Native site-integration fixture scan

The exact commit c6b8d125a7d110a22cf8d1b349bd3d5f25e7bf38 was scanned
with Gitleaks. Thirteen findings across three one-line JSON captures all match
`request_key` fields. These are idempotency/recovery identifiers emitted by the
owned disposable native test services, not API keys or account credentials.
The unchanged capture tests generated them from synthetic test inputs.

The six new archives and their source fingerprints were checked before copying;
existing historical archives were retained byte-for-byte. See
[implementation validation](2026-09-24-site-integration.md) for their hashes.
Only these exact commit/path/rule/line fingerprints are accepted. No global,
path-wide or rule-wide exclusion is added.

```text
c6b8d125a7d110a22cf8d1b349bd3d5f25e7bf38:frontend/tests/fixtures/discovery-main-barrier-native.site20260924.wire.json:generic-api-key:1
c6b8d125a7d110a22cf8d1b349bd3d5f25e7bf38:frontend/tests/fixtures/ml-pilot-attestations-native.site20260924.wire.json:generic-api-key:1
c6b8d125a7d110a22cf8d1b349bd3d5f25e7bf38:frontend/tests/fixtures/ml-pilot-participant-native.site20260924.wire.json:generic-api-key:1
```
