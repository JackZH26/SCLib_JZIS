# Private scientific-program imports: pending records, not accepted science

Version: `scientific-pending-import/1.0.0`. Schema: additive
`0065_scientific_import`, after `0064_ml_feature_companion`.

This importer retains complete native input/output bytes and can create one
source-bound **pending** `phonon_min_frequency` observation. It never runs QE,
creates a material or Tc claim, approves science, admits an ML example, or
publishes an artifact. It is a limited implementation step for ML05 / #67, not
completion of the full scientific-property importer.

## Scientific admission boundary

The accepted file format is the existing, independently pinned
[`scientific-program-package/1.0.0`](SCIENTIFIC_PROGRAM_PREFLIGHT.md) QE matdyn
package, augmented by a separately pinned matching force-constant file and an
explicit existing material row. Both the original package and the augmented
context are retained. Repository scripts and uploaded filenames are data;
neither is executed or fetched by an API request.

| Observation | Implemented validation | What it does not establish |
|---|---|---|
| Formula | Exact supported composition parser; FC species/site fractions match both source formula and current material formula | Phase identity, isotope/mass overrides, sample identity or a unique structure |
| Coordinates | Actual FC header; explicit `ibrav=0` vectors or QE `ibrav=2` FCC convention; Cartesian tau converted to fractional sites; finite, nonsingular, right-handed cell and no periodic duplicate sites | Absence of vacuum, physical bulk dimensionality, expert geometry approval or symmetry determination |
| Force constants | Complete native block/address traversal, no duplicate/missing entries; actual SHA-256 and native raw text retained | Correctness or convergence of forces, upstream run identity, eigenfrequency recomputation |
| Frequencies | Complete native q-point/mode inventory, signed numbers, input/output q-point matching, logical filename matching, mode count `3 × nat` | Full-Brillouin-zone stability, a verified DFPT execution or superconductivity |
| Minimum frequency | Printed sampled minimum and byte/line locator; exact cm⁻¹-to-THz factor `0.0299792458`; signed raw zero retained | Zero uncertainty, a Tc estimate or proof that a small negative mode is physical |
| Conditions and method | Pressure/temperature/field/phase/treatment explicitly unknown; source-scoped state | Ambient pressure, 0 K, harmonic approximation or compatibility with another calculation |

Only unambiguous supported coordinates plus declared bulk context can produce
pending canonical rows. Unsupported `ibrav`, two-dimensional treatment,
long-range FC layouts requiring additional context, missing FC, composition
mismatch, malformed native content, wrong names/mode counts or stale material
bindings remain quarantined or rejected with explicit reasons. Full raw source
bytes are retained for attempts that reached the durable-start boundary.

The coordinate JSON's `bulk_3d_periodic` representation is **not** a bulk/no-vacuum
attestation. The state and structure independently record that geometry review
is absent. Such data cannot pass the existing reviewed coordinate-feature gates
by virtue of this importer alone.

The property uses `registry_version=rv2/1`, `component_key=bulk` and
`relation=exact` for the printed point, not for exact underlying physics.
`reported_uncertainty=null` and the printed precision basis remain explicit.
Pressure is `not_reported`/null; simulation temperature is null. Neither is zero.

## Canonical rows and retained provenance

An import that finishes as `success_pending` atomically creates:

1. An actual completed **extraction** run, describing this parser/import process.
   It is not a fabricated `calculation` or completed DFPT run. Upstream run,
   executable version, convergence and calculation resources remain unresolved.
2. A source-scoped material state and FC-derived coordinate structure for the
   explicitly pinned existing material.
3. A `Computed`-origin extraction event with both review and validity **pending**,
   and no decision artifact.
4. One phonon-minimum property, with raw quantity, native unit, conversion,
   precision, sampled scope and locator.
5. Source evidence edges, coordinate/report artifacts and actual input/output
   import manifests, all private and hash-verified against retained bytes.

New immutable SQL tables hold packages, attempts, complete BYTEA blobs, logical
file inventory and outcomes. Outcome snapshots preserve the exact five canonical
rows at import time and their independent digest. These are historical receipts;
later authorized scientific review is not inferred from the stored pending
snapshot. Raw bytes do not disappear if a request is cancelled after start.

All artifacts default to restricted access and unknown availability time. No
Paper/Work record, source-publication time or redistribution permission is
invented. Retaining a repository License file does not grant per-file rights.
Existing 0054 freezes and 0064 feature companions are unchanged; this importer
does not manufacture their review, source-time or training-admission inputs.

## Operator API

All routes require an authenticated **current curator** grant and the existing
research feature gate. Account/session revocation and grant revocation are
rechecked in every independent transaction. A feature flag or ordinary admin
role alone is not curator authorization. Responses are `private, no-store`.

| Method and route | Purpose |
|---|---|
| `GET /v1/ml/scientific-program-imports/capabilities` | Read current curator/account/grant capability and the installed compiler pin |
| `GET /v1/ml/scientific-program-imports/outcome?request_key=...&expected_request_sha256=...` | Read only the current account's original actor/key/package receipt, including a durable unresolved start |
| `GET /v1/ml/scientific-program-imports/material-bindings/{material_id}` | Read the current full-material-row SHA-256 and formula without exposing the full row |
| `POST /v1/ml/scientific-program-imports` | Default rollback-only preview, or explicit durable pending import |
| `GET /v1/ml/scientific-program-imports/{attempt_id}` | Inspect a private durable attempt and its recorded outcome |

The JSON request has the following closed top-level fields. The additive
`expected_request_sha256` field is optional for old clients and is always used
by the [English import workbench](SCIENTIFIC_IMPORT_WORKBENCH.md). It binds the
preview's augmented package, including the installed compiler, and is checked
before any durable start. Omission retains the old API behavior.

```json
{
  "request_key": "operator-chosen-idempotency-key",
  "dry_run": true,
  "manifest": "REPLACE WITH ORIGINAL CLOSED PACKAGE OBJECT",
  "expected_manifest_sha256": "REPLACE WITH INDEPENDENT 64-HEX MANIFEST PIN",
  "expected_request_sha256": "REPLACE WITH EXACT AUGMENTED PACKAGE PIN FROM PREVIEW",
  "artifact_bytes_base64": {"ACTUAL_FILE_SHA256": "CANONICAL_BASE64_OF_COMPLETE_FILE"},
  "context": {
    "version": "scientific-import-context/1.0.0",
    "material_id": "EXISTING_MATERIAL_ID",
    "expected_material_row_sha256": "PIN FROM AUTHENTICATED BINDING READ",
    "force_constants": {
      "logical_name": "EXACT_FLFRC_BASENAME_FROM_NATIVE_INPUT",
      "sha256": "INDEPENDENT_64_HEX_FORCE_CONSTANT_PIN",
      "size_bytes": 12345
    }
  },
  "force_constants_bytes_base64": "CANONICAL_BASE64_OF_COMPLETE_FC_FILE"
}
```

This is a **non-executable shape example**: placeholders and `12345` are not
valid source observations. Supply actual objects, bytes, hashes and length.
If the FC file is unavailable, both FC fields must be null; the result is an
explicit missing-coordinate quarantine, not formula-derived coordinates.
Request bodies cannot set actor/grant IDs, approvals, pressure, costs or prepared
parser results. Website preview data is not an upstream execution attestation.

Obtain the material pin first, prepare a preview, inspect its reasons, and then
submit the **same actual source package** with `dry_run=false` if authorized.
The material ID is a string and may require ordinary URL path encoding.

## Transaction, retry and error semantics

`authenticate → durable start → pure worker → atomic pending rows + terminal`

Authentication closes its read transaction before upload. A successful start
commits the exact package, actual bytes and attempt **before** parsing. The worker
has no database session or transaction. Finish uses a new serializable transaction,
rechecks current identity/authority and bytes, validates material binding, and
commits science rows and terminal outcome together. Responses assert committed
status only after the outer transaction has committed.

For a committed import (`dry_run=false`, outer `committed=true`):

| Status | Interpretation and action |
|---|---|
| `success_pending` | Pending rows and receipt committed; no scientific acceptance or ML eligibility |
| `quarantined` | Captured source remains inspectable; reasons recorded; no new canonical science rows |
| `failed` | An independently committed technical failure receipt; no partial canonical science rows |
| `outcome_unknown` | Durable start has no terminal receipt; do not claim success or failure; inspect/retry with current authority |

Same actor/key and exact request **terminal replay** returns the stored outcome
with no SQL row or guard-epoch change. Repeating an HTTP request whose attempt is
still `outcome_unknown` resumes parsing/finish and may commit its first terminal
and pending rows. A different request under that key is a 409 conflict. A new
key can extend a failed/quarantined/unresolved package's exact predecessor chain;
an already successful package cannot acquire a second successful import. An old
attempt cannot finalize after a successor has become the head.

Preview rolls back the entire operation, including audit/guard state. A preview
can return `success_pending` with `committed=false`; it has not created those
rows. Newly proposed IDs are not persisted lookup targets; replay of an already
durable terminal may return its existing IDs. A preview failure creates no
attempt receipt. Malformed envelopes rejected before start likewise do not
create an audit claim that parsing began.

On timeout/cancellation/ambiguous commit acknowledgement, bounded independent
recovery first inspects the actual database. It never overwrites an observed
terminal. If an authorized negative receipt cannot commit, the durable start
remains `outcome_unknown`. Late parsing cannot perform SQL. Recovery has its own
capacity bound; exhausting it does not fabricate a negative outcome. Reauthentication
and the original package permit recovery after the original grant is revoked,
provided the new operator has current curator authority. A new operator's HTTP
retry can append a successor attempt; it does not rewrite an older operator's
unresolved attempt history.

Exact typed key/package/material-start conflicts return 409. Missing authority
returns 401/403; schema/feature unavailability, SQL errors and unknown failures
return sanitized errors rather than SQL/source text. A material change observed
after a durable start is recorded as quarantine at finish.

## Resource limits and reproducibility

- Request: 24 MiB, identity-encoded JSON only; at most two concurrent requests.
- Original manifest: 64 KiB, at most 16 logical files, 4 MiB per original file,
  8 MiB combined package bound; exact complete inventory and canonical Base64.
- FC: 8 MiB; at most 120,000 physical lines, 64 atoms, 4,096 grid points and
  100,000 matrix entries. Bounds apply before large per-entry processing.
- Augmented source: at most 19 logical files; unique bytes at most
  `16 MiB + 128 KiB`. Shared logical references load each actual blob once.
- SQL: at most 64 retained blobs and 24 MiB per package, with native hash, kind,
  exact artifact-projection and append-only checks. Raw source blobs are reused
  across retries; attempt/outcome receipts remain append-only history.
- Worker: two slots held until actual worker completion; 15-second await timeout.
  Overall request timeout is 45 seconds, body timeout 10 seconds, SQL timeout
  10 seconds. Recovery has two independent slots and a 5-second deadline.
- Only observed parser-worker wall/CPU milliseconds are measured on successful
  compile. Native calculation CPU/wall/monetary costs remain null. These timings
  are not imported-computation cost estimates or whole-request latency.

Compiler inventory includes the actual installed parser, composition grammar,
normalization, canonicalization, writer and new schema sources. Capture and
compile pin the same inventory before and after processing. Stable `api/...`
labels work in repository, API-only container and installed-wheel layouts;
repository CLI scripts are not required at API runtime.

The frozen batch30 CLI and its reports are unchanged. The API's separately
versioned `scientific-import-native-preflight/1.0.0` envelope uses the same closed
validator/native parser and has parity tests for successful, malformed, wrong-name
and nonbulk inputs. In-process HMACs prevent forged prepared-result dictionaries;
they are not upstream scientific signatures and are not portable across processes.

## Reproduce the genuine-file canary safely

The explicit downloader only retrieves two fixed, content-pinned public QE
force-constant files. It never executes scripts or writes a database. Its
new owner-only directory is independent of the batch30 capsules.

```bash
api/.venv/bin/python scripts/fetch_qe_force_constant_canaries.py --parent /absolute/existing/private/directory
```

Run the three real-byte cases only through the disposable runner, substituting
the actual local paths returned by the two download workflows:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server --suite api -- \
  -p tests.scientific_reference_options \
  --scientific-reference-capsules /absolute/batch30/capsules \
  --scientific-force-constants /absolute/new/fc/capture \
  tests/test_scientific_import_reference_canaries.py -q -s --tb=short
```

Without explicit local paths these three tests skip and attempt no download.
The test harness cannot accept an existing PostgreSQL/Redis instance. Every case
checks full-state preview rollback, durable start/finish, retained source hashes,
unchanged material/Tc/ML data and exact no-write retry, including quarantine cases.

Results: **3 genuine packages, 1 pending canonical observation, 2 quarantines,
0 scientifically accepted and 0 ML-admitted**. AlAs has actual matching FC
coordinates/matrices; Al example14 lacks the corresponding FC; BN's `ibrav=4`
and explicit 2D context are outside current coordinate admission. These are
historical reference files, not newly executed or independently approved runs.

## Rollout and remaining work

The migration is additive and startup schema admission remains read-only.
Empty 0065 tables support a rehearsed downgrade; any retained source/attempt
history causes downgrade refusal. Account deletion respects immutable audit
identity. No production migration or rollout is implied by native test success.

Before scientific/ML use, finish reviewed state/run/geometry/source-time/rights
binding and the existing independent dataset/release gates. Expand other core
property adapters only with explicit units, dimensionality, reference/method
context and negative fixtures. A sampled phonon-frequency minimum is neither a
superconducting label nor a universal cross-family ranking feature. The
[private read-only evidence workbench](SCIENTIFIC_EVIDENCE_WORKBENCH.md) now
exposes exact pending results and their dependency metadata. Actual scientific
adjudication, a broader genuinely permitted canary cohort and remote
implementation delivery remain separate unfinished work.
