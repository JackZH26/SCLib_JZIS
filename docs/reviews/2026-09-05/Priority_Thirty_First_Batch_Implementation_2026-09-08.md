# Thirty-first implementation batch — private pending scientific imports

Date: 2026-09-08. Parent: `be4119f`, branch `codex/sclib-research-v2`.
Primary issue: [ML05 / #67](https://github.com/JackZH26/SCLib_JZIS/issues/67).

## Delivered result

The actual-byte preflight now has a real private SQL/HTTP path. A curator can
preview a pinned QE package without database changes, retain a durable import
attempt and source bytes, and atomically create source-scoped pending state,
coordinates, extraction run, event and sampled phonon-minimum property.
Unsupported or incomplete packages retain negative/inconclusive outcomes.

This batch does not manufacture completed DFPT calculations, reviewed geometry,
physical conditions, actual calculation costs, source-time/rights permission,
scientific acceptance, ML features, public releases or a Tc label. The new parser
run describes extraction only. ML05 remains incomplete against its full issue
criteria; no issue closure, remote publication, production access or deployment
is claimed. The persistent goal remains active.

## Implementation and integration

- `0065_scientific_import` and `models/scientific_import_v1.py`: five additive
  immutable tables for packages, attempts, actual BYTEA blobs, file inventory
  and outcomes. Native role, lock, digest, actual artifact projection, source
  completeness, exact attempt chain and pending-result snapshot guards.
- `services/qe_force_constants_import.py`: bounded complete native FC parsing,
  actual species/sites and supported QE `ibrav=0/2` cells; byte/line locators,
  full matrix/address inventory and composition checks. Unsupported conventions
  do not produce coordinate-derived features.
- `services/scientific_import_input.py`: immutable byte capture, separately
  versioned installed-runtime preflight, transitive compiler-source pins and
  in-process prepared-result integrity. No database or imported executable path.
- `services/scientific_pending_import.py`: independent material-row pin, actual
  retained bytes and artifacts, source-scoped pending canonical rows, durable
  history, explicit failure/unknown states, idempotency and full preview rollback.
- `routers/scientific_program_imports.py` and main registration: private curator
  binding/import/inspection APIs, strict upload limits, default preview, separate
  authentication/start/worker/finish scopes, current grant/session rechecks,
  commit-before-success, bounded cancellation recovery and exact 409 conflicts.
- Account audit-retention inventory includes the new immutable actor references.
  Startup remains read-only; schema head changes only through explicit migration.
- Explicit fixed-source FC downloader and opt-in genuine-file disposable tests.
  Original batch30 files, CLI/report format and frozen 0054/0064 contracts remain
  unchanged.

The [operator/scientific contract](../../SCIENTIFIC_PENDING_IMPORTS.md) documents
request fields, bytes, boundaries, state transitions, limits and reproduction.
All new website-owned API labels and errors default to English.

## Independent review and corrections

Three parallel review/test tracks covered native schema, actual SQL import, and
HTTP orchestration. Concrete fixes were made before final verification:

1. An invalid native JSON-array loop in the terminal trigger prevented genuine
   positive imports. Real pending-row tests exposed it; no fixture or assertion
   was weakened to accept a failed import.
2. Shared logical source references duplicated large BYTEA values in a join.
   The writer now measures unique physical bytes before loading each blob once;
   a 19-logical-file regression observes six actual unique blob rows.
3. Compiler pins omitted transitive composition grammar/canonicalization sources.
   Those files now participate in request/compiler identity.
4. Source hashes used repository-relative paths unavailable in API-only images.
   The new runtime envelope pins actual installed API files, has scientific
   parity tests with the frozen CLI, and compiles in an independent API-only
   subprocess with no repository scripts.
5. Cancelled HTTP requests could accumulate shielded recovery jobs. Recovery
   now has independent bounded capacity held until each job actually finishes.
   Late parser completion cannot produce SQL.
6. Expected typed request/package/material-start conflicts now return 409 with
   whole-database/guard-epoch no-change tests; unrelated failures remain 503.

## Genuine reference-file evidence

Original package inputs remain the three batch30 capsules from QEF/q-e commit
`770a0b2d12928a67048e2f3da8d10d057e52179e`. The new sidecars are complete native
files from the matching reference directories:

- [AlAs FC source](https://github.com/QEF/q-e/blob/770a0b2d12928a67048e2f3da8d10d057e52179e/PHonon/examples/GRID_recover_example/reference/alas.444.fc),
  77,388 bytes, SHA-256
  `b683e6fa7b6182c25ed5a25ee61038f10841d5e4827b7c6396a33b6ca4cc2047`.
- [BN FC source](https://github.com/QEF/q-e/blob/770a0b2d12928a67048e2f3da8d10d057e52179e/PHonon/examples/example17/reference/bn881.fc),
  77,384 bytes, SHA-256
  `34945d97a3458ea6833df66485feb4ab09e6c9b65f022e99ff7387dae87e3bde`.

No corresponding Al example14 FC exists in the inspected reference inventory.
Another example's Al force constants were not substituted. Historical reference
files and a repository tag are not evidence of the executable version or a new
scientific execution. Whole FC validation is not eigenvalue recomputation.

| Package | Files retained including context | FC inventory | Terminal | Parser wall / CPU ms |
|---|---:|---|---|---:|
| Al `example14` | 7 | Missing matching source | `quarantined` | 19 / 19 |
| AlAs `GRID_recover_example` | 8 | 2 atoms, 4×4×4 grid, 2,304 entries | `success_pending` | 48 / 48 |
| BN `example17` | 7 | 2 atoms, 8×8×1 grid, 2,304 entries; unsupported `ibrav=4` | `quarantined` | 38 / 37 |

These are measured **parser-worker** costs in one disposable run, not native
calculation or end-to-end API costs. All calculation cost fields remain null.
AlAs coordinate SHA-256:
`3afa668279d90e9d877200f0fa7c2733b39723725d09e5744e59286716b921cf`.
Signed raw `-0.0000 cm⁻¹` is retained without labeling it physical instability.
BN's negative observations are retained but cannot bypass geometry/treatment
quarantine. The minimum is sampled, not a full-zone stability certificate.

Final compiler inventory digest:
`99b3d970a2689b225cb0be805bddeffd625f388297e1500920e7736017975d10`.

| Package | Final private SQL report SHA-256 |
|---|---|
| Al | `c0ea2623dd5f5bb0d607ca01a4d7cb9ad67818a7b675481032dcddb9121b6d91` |
| AlAs | `707bcdd0aa04eb9f1647326940e552f8dad4b350389e84551589f247cce1018a` |
| BN | `cde859990038c01557f921c6c798d9b510e9c76e9413bc9eef50a97daff648c4` |

SQL report hashes include the disposable material/request identity. They are
not expected to match across independently seeded databases. Within each actual
case, the committed receipt and every database row/guard epoch replay exactly;
preview restores the full pre-import database state. The tests also check that
Material, Tc claims and ML tables are unchanged.

Denominator: **3 genuine reference packages, 1 pending canonical observation,
2 quarantines, 0 scientifically accepted, 0 ML-admitted**. All three were tested
with actual source bytes, including the negative cases. The two successful
syntactic preflights from batch30 are not two scientifically validated imports.

Source captures, not committed third-party files:

- Original capsules: `/Users/jackzhou/Documents/YorkMsc/ML-SC/qe-matdyn-canaries-d6c843a22e8c4c35bde392b8937b65c9`.
- New complete FC captures: `/Users/jackzhou/Documents/YorkMsc/ML-SC/qe-force-constants-uq0y_w7o`.

Disposable SQL receipts were inspected during tests and removed with their own
test database; hashes above are audit facts, not claims of a production record.
Sources remain private. Per-file rights and source-time review are still absent.

## Verification

All new runtime modules were frozen before the final complete API run. Its
three skips are exactly the opt-in genuine-file tests, which were separately
executed with explicit actual pinned local paths and all passed.

| Completed suite | Actual result |
|---|---|
| Full API, owned disposable native PostgreSQL/Redis | 4,913 passed, 3 intentional skips, 20 existing warnings; 1,094.26 s |
| Genuine-byte opt-in native SQL canary | 3 passed, one existing warning; 2.47 s |
| Full scripts | 777 passed plus 36 subtests; 9.42 s |
| Full ingestion, inert PostgreSQL/Redis endpoints | 1,275 passed, 34 existing warnings; 8.41 s |
| Full frontend components | 507 passed across 27 files; 14.55 s |
| Frontend source/English checks | 35 passed; 0.70 s |
| TypeScript | `tsc --noEmit` passed, no diagnostics |

Combined executed suites: **7,510 ordinary tests plus 36 subtests**. There are
203 new ordinary API tests, 49 new script tests and three opt-in real-file cases
in this batch. Focused tests below are subsets, not added again to that total:

- Focused native FC parser: 49 passed.
- Focused native SQL schema: 48 passed.
- Focused actual pending SQL service: 35 passed.
- Focused private HTTP/operator: 71 passed.
- Final genuine-byte opt-in native canary: 3 passed, one existing warning,
  2.47 seconds, full preview and exact replay checks for every case.
- Complete scripts: 777 passed plus 36 subtests, 9.42 seconds. Includes 38
  pure/compiler/installed-layout tests, 9 fixed-FC fetch tests and 2 additional
  migration ordering tests.
- Full native migration rehearsal passed: all prior independent revision guards,
  empty 0065 downgrade/re-upgrade, actual durable start/pending finish, finish
  rollback without erasing start, exact replay and nonempty downgrade refusal.
- Changed-module Ruff import/undefined-name checks and diff whitespace checks
  passed. Focused counts are subsets, not additional unique full-suite tests.

API-only runtime verification copies the exact shipped source modules into an
isolated installation layout and compiles actual-format bytes in a new Python
process with no repository/scripts. This is not a Docker image build or a
deployed wheel validation. Offline wheel-build verification was not completed;
local `uv`/`hatchling` were not available on the checked command path/runtime.
No dependencies were installed to bypass that limitation.

## Issue acceptance and next priorities

| ML05 criterion group | Actual status after this batch |
|---|---|
| Original quantity, native unit, normalized minimum, locator and canonical parent references | Implemented for pending sampled phonon minima |
| Safe actual coordinates and composition/hash/format validation | Implemented for bounded native `ibrav=0/2`; incompatible inputs remain quarantined |
| Scientific method/state matching and compatible feature admission | Pending; unknown pressure, phase, treatment, geometry review and upstream run are not filled with assumptions |
| Three-to-five genuinely permitted reviewed input/output contexts | Three actual-format contexts exercised, but only one pending SQL-positive case and no per-file independent rights/scientific approval; criterion not complete |
| Twice-verified actual SQL imports including negative outcomes and costs | Implemented for this three-case pending/negative cohort; parser costs only, native costs unknown |
| Broader DOS/energy/EPC/stiffness protocol-aware import and confusion fixtures | Still unfinished; no field-count expansion or fabricated values |
| Public/ML-ready release and delivered implementation links | Not performed; existing independent review and remote delivery gates remain |

Next safe local work is the operator's evidence-review interaction and explicit
method/state binding, followed by another bounded core-property adapter with
actual permitted sources and the issue's dimensionality/unit negative fixtures.
This must not turn the current pending path into automatic scientific approval.
Production rollout, real source/rights adjudication, paid computations and remote
delivery remain separately authorized actions. No remote issue was closed here.
