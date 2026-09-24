# JZIS / SCLib integration implementation validation

Base: production revision `3770bcc249d182f37ab150f5688da6a9f8cb6ba0`.
Scope: root-mounted SCLib website, institutional/resources pages, retirement
configuration, account-link compatibility. No scientific schema or data changes.

## Local validation

- Frontend source contracts: 46 passed.
- Frontend components/protocols: 1,923 passed across 55 files.
- Production-mode public browser suite: 24 passed. The owned loopback server
  blocks external browser HTTP/WebSockets. It checks root assets, English copy,
  390px/1440px layouts, navigation, old URLs, encoded IDs, private headers and
  reverse-proxy Host handling. Its unavailable-stats state is intentional.
- Native disposable PostgreSQL/Redis: 39 auth/email/selected scientific capture
  tests passed, plus one native attestation capture test passed separately.
  Email delivery is mocked/suppressed; Google behavior uses the existing mocked
  provider contract. No production accounts or emails were created.
- Nginx renderer tests: 6 passed; release/security workflow acceptance also run.
- TypeScript and whitespace validation passed.
- Real public stats were loaded in the separate local preview: 75,202 indexed
  papers and 11,463 catalogued materials, with the coverage caveat displayed.
  These are a dated observation, not hardcoded page values.

## Native fixtures

The auth/config changes invalidate current-source pins even though no scientific
protocol changed. Six fresh captures were generated with the existing native
SQL/HTTP tests; no response was edited or resealed. Old fixtures and old hash
assertions are retained. The Discovery capture pins 304 source files; the other
five pin 619 files, including the new email test and Nginx preparation script.

| Capture (`frontend/tests/fixtures/`) | SHA-256 |
|---|---|
| `discovery-main-barrier-native.site20260924.wire.json` | `f84c4832ca8cd53870a7c0e8ee8f90374cee667c3d025af3261306eca9fbadbf` |
| `ml-use-rights-native.site20260924.wire.json` | `cbf1e3114cfa23c10d0e5c0ac66b02ced4a6de1d59697e0df5aa9c691f36ba22` |
| `ml-use-runs-native.site20260924.wire.json` | `3e3d8a3fee3fccd74e031c97e998d9d4ca997297a623a8531b046e7c58c19bc7` |
| `ml-pilot-participant-native.site20260924.wire.json` | `fbb299b2d7c06204b32928788d0e636345413562ebc55f979d2713dec7f8d89a` |
| `ml-pilot-evidence-native.site20260924.wire.json` | `a23a9dfab8a6fb83cb6cff6e567111d6745831ef4dd10856cb8ac9bb702e6c83` |
| `ml-pilot-attestations-native.site20260924.wire.json` | `fc37095590345f77cdbd52f0483ed59c7bb40fc3559845e4b7d38dd1d78864e5` |

These are synthetic identities, requests and research inputs, not real research
approval or source rights. A redacted directory scan identified 13 generic-key
matches in three new one-line captures, all `request_key` fields. Any scan
exceptions must use the exact committed file/rule/line fingerprints and preserve
the historical allowlist; no path-wide exclusion is justified.

## Host configuration rehearsal

The audited input Nginx file SHA-256 is
`30923c925c00926677139d1aeba4ac404711486f3a4d5897168789d90f547523`.
The renderer produced a separate candidate preserving the API blocks, TLS
settings and private presentation include. On VPS2, `nginx -t` succeeded using
an isolated wrapper under `/tmp/sclib-site-integration-20260924-review/`.
The live Nginx configuration was not changed or reloaded.

Correction after the Timeline incident: the wrapper isolated the configuration
file but did **not** isolate temporary paths. Its `nginx -t` changed the owners
of five production temporary directories to `nobody`, breaking buffered large
responses. Those owners have now been restored to the active `www-data` user.
The earlier syntax success must not be interpreted as a side-effect-free
rehearsal. See `docs/operations/INCIDENT_2026-09-24_NGINX_TEMP_OWNERSHIP.md`.

## Release status and limitations

This record does not assert full CI completion or production deployment.
The current production SLO check reports public API availability passing and AI
API availability failing (99.11505% from 113 requests, one error at observation).
Data freshness is deferred because ingestion is intentionally paused, not passed.

The first root cutover requires the coordinated runbook and an ASRP-free rollback
baseline. Automatic image-only deployment refuses the old edge configuration.
Keep the change off production until the normal gates and first-cutover
prerequisites are satisfied. No previous incident exception is reused.
