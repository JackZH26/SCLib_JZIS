# Forty-sixth implementation batch — exact RPS descriptor preparation

Date: 2026-09-09. Branch: `codex/sclib-research-v2`.
Baseline: `d2028af5452b08288842f154fdf696cb93e7d9c3` (forty-fifth batch).
Issue: [ML07 #68](https://github.com/JackZH26/SCLib_JZIS/issues/68).
Operator contract: [RPS distribution preparation](../../RPS_DISTRIBUTION_PREPARATION.md).

## Outcome

Added a private curator API that prepares the existing controlled RPS descriptors
and atomically registers an independently pinned release/public bundle against
explicit existing source roots. It closes the practical prerequisite before the
batch44 rights workbench: a curator no longer needs to insert each descriptor
directly in SQL. The durable package UUID is usable by that existing workbench.
There is no new browser source-selection interface in this batch.

The change adds a service, a bounded router and two new native test modules;
`api/main.py` only mounts the router. Existing database schema, source/frozen
contracts, full inventory validator, registration, rights, publisher separation,
RPS scoring, offline verifier and public admission are unchanged. No frontend,
dependency, hosting, migration or production configuration change is included.

No real source was imported, no rights or scientific decision was made, no
provider/DFT job or ML fit was run, and no remote push, PR, deployment or issue
closure occurred. Synthetic test actors are not real approvals.

## Exact preparation and historical identity

The closed selection document must explicitly cover every evidence artifact and
every material/state identity. Actual source-capture and frozen-result roots
retain their old origin checks; formula matching cannot infer a phase or sample.
The service captures mutable inputs before SQL awaits, reads source rows itself
and verifies the actual complete source/capsule bytes. Every capsule dependency
remains in the subsequent rights inventory.

Non-evidence descriptors contain the canonical complete RPS artifact, including
its own embedded hash. Their actual-byte hash therefore uses that whole object,
not just the embedded hash. Generated artifacts are restricted, have the old
schema/kind mapping, and receive no URI or artifact license.

Independent review found a genuine PostgreSQL representation problem: a nested
JSONB object can normalize numbers such as `-0.0`. The service now retains the
exact canonical JSON text in `metadata.rps_artifact_json` and reconstructs its
bytes from the sealed inventory projection. It checks canonical-byte equality,
full SHA-256 and original artifact/root identity. A real PostgreSQL signed-zero
regression exercises commit and historical recovery, not just an in-memory hash.

New preview inserts the actual descriptors/package/dependencies and exercises
deferred SQL completeness, then rolls back all rows and guard epochs. It returns
no durable package UUID. The stable intent substitutes the complete generated
descriptor byte plan for generated database-row projections while retaining
all exact source projections, independent request pins, authenticated actor/grant
and key. The durable inventory still contains the full generated projections,
including real IDs/timestamps; the binding hash includes those real IDs.

Commit validates the full inventory through the unchanged registrar and checks
the preview intent before outer commit. Exact actor/key POST replay resolves
retained history before descriptor creation or live-source fetching. It cannot
change to a replacement grant or changed request. GET recovery can use a current
replacement grant of the same original account, returning the historical grant
without falsely reauthorizing that old operation.

GET does not parse a new source package, read current source eligibility or write
anything. A missing receipt is not proof of rollback. The outer HTTP envelope
reports durable success only after actual commit or exact durable replay; the
service-level `committed` remains false. All scientific, training and current
publication authority flags remain false.

## Authenticated bounded HTTP behavior

The new route uses existing session/CSRF/research grants and ordered serializable
fences. Curator admission precedes body reading; account/session/grant are
checked again after upload under the actual write transaction. A review finding
also moved the historical-query shape check after curator admission. Raw query
bytes are still bounded before framework parsing to control unauthenticated
allocation; that resource limit is intentionally not a grant oracle.

Limits are 48 MiB streamed wire, 32 MiB shared decoded source/capsule bytes,
8 KiB response and 1,024 raw query bytes, with existing smaller per-file and
canonical bounds. The existing two-slot process gate and request/SQL timeouts
are reused. Response serialization and its tighter size limit run before outer
commit. Cancellation, stale identity, serialization failure and transaction
failure cannot leave success-shaped partial registrations. A lost successful
acknowledgement is recovered through an independent GET in a fresh session.

These limits are not corpus-sized performance evidence or fleet-wide memory
guarantees. No browser retry state machine or new upload UI is claimed.

## Verification

Final checks passed against the frozen product/test files. Subsequent changes
only finalize these documentation records.

| Check | Result |
| --- | --- |
| Guarded native API, exact 16-module selection below | **626 passed**, 1 existing warning, **1,099.14 seconds** (18:19), exit 0 |
| New service and HTTP cases, included in that total | **31 + 59 = 90 passed**; not an additional total |
| Ruff import/undefined-name checks (`I,F`), all five touched/new Python files | Passed |
| Git whitespace check | Passed |
| Independent service/router and operator-contract review | Completed; numeric-byte preservation and query-authentication findings corrected |

The warning is the existing `regex` deprecation in `routers/admin.py:83`, not a
new preparation warning. The native runner explicitly confirmed removal of only
its owned services and temporary test data. Existing development services and
the normal frontend build directory were untouched.

Earlier focused checkpoints overlap this final run: the HTTP suite passed 59
cases; the service checkpoint passed 30 before an extra synthetic native-import
fixture was corrected and passed separately. The final combined run verifies
all 31 service cases together. Those fixture corrections preserve the existing
permitted capsule-root and column-length constraints rather than weakening them.

The exact selected modules are reproduced below. All database and Redis targets
belong to the disposable native runner; no inherited development or production
target is used.

```bash
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server --suite api -- \
  tests/test_research_distribution_preparation.py \
  tests/test_research_distribution_preparation_http.py \
  tests/test_research_distribution_workflow.py \
  tests/test_research_distribution_contract.py \
  tests/test_research_distribution_schema.py \
  tests/test_research_distribution_operators.py \
  tests/test_research_distribution_rights.py \
  tests/test_research_distribution_rights_http.py \
  tests/test_research_distribution_rights_wire.py \
  tests/test_rps_distribution_http.py tests/test_rps_catalog_delivery.py \
  tests/test_research_publication.py tests/test_research_publication_http.py \
  tests/test_research_publication_schema.py tests/test_research_publication_limits.py \
  tests/test_scientific_result_public_gates.py -q --tb=short --show-capture=no
```

The new tests start with actual synthetic source rows/bytes and no preseeded RPS
descriptors. They cover both source kinds, complete SQL-state equality for
preview/replay/recovery, wrong or substituted roots and identities, stale source
pins, explicit rollback and deferred failure, actual signed-zero persistence,
and a complete preparation → per-dependency rights → independent review → third
publisher → current public admission → revocation chain. An actual pending
native import is frozen through its permitted snapshot membership; attempting
to misclassify its `extraction`/`Computed` origin as `calculation` is rejected by
the unchanged frozen-result validator, with a spy confirming that exact check.

HTTP checks include fresh post-upload role/session/account changes, actor/key/pin
recovery, no epoch advancement on replay, full outer transaction behavior,
bounded/closed query and body input, shared decoded budget, response limits and
real client cancellation after descriptor work. The positive HTTP fixture is
captured from actual disposable SQL/HTTP responses; it is synthetic and is not
a deployed or reviewed research release.

Frontend and scripts regressions/builds were not rerun because their code is
unchanged. No whole-API, actual Linux release-image or production test is claimed.

## Issue status and next implementation

A fresh read-only GitHub check confirmed ML07 #68 and DR04 #77 remain OPEN.
This practical preparation increment is not itself a new literal acceptance
condition for ML07. Its actual dependency contracts, recursive disclosure and
visibility matrix, offline bundle behavior and linked delivery evidence must
be assessed against that issue. General ML-use authorization and new scientific
pilot approval must not be invented as additional requirements for closing a
purely engineering access-control item.

The next concrete software gap is DR04: the current real release is assessment-
row based and has no frozen reviewed material-level representative selection;
the broad scientific matrix still imports synthetic demo rows. Implement a
separately versioned, exactly pinned read projection without rewriting the old
release/scorer/verifier contract. It must retain the chosen assessment/state/
action and alternates, source-linked typed scientific values, explicit
supported/populated/planned capabilities, and distinct missingness/review states.
No highest-score fallback or mixed-state material row is acceptable.

Read-only inspection identified three constraints for that next increment:

- An existing RPS evidence binding proves its source, not applicability to the
  selected material/state. A typed cell needs an independent exact identity and
  state check; contextual, opposing and template evidence cannot be promoted
  merely because it is in the same capsule.
- Eight native numeric properties are registered for storage, but the present
  exact scientific adjudication profiles cover sampled phonon minima. A
  negative-only hold gate is not positive scientific acceptance. The preview's
  DOS and stiffness labels/units also differ from the native registry; copying
  its column adapter would silently discard normalization semantics.
- Existing RPS disclosure rights bind the old public bundle, not a new companion
  containing scientific values or representative-selection rationale. The new
  companion needs its own exact reviewed disclosure binding before public
  delivery. Configuration pins or JSON approval flags cannot supply it.

The first real pilot still needs its genuine scientific/source review. Display
and export must state **“Policy-based research priority; empirical calibration
pending”** and restrict comparison to the frozen campaign/budget/policy/release.
DR04 does not require pretending that AL01's independent empirical evaluation
has already succeeded. The overall goal remains active.
