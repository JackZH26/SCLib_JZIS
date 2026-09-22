# Forty-seventh implementation batch — exact scientific Discovery backend

Date: 2026-09-09. Branch: `codex/sclib-research-v2`.
Baseline: `f322d836f78495327cfb30680315b6f910ef710b` (forty-sixth batch).
Issue: [DR04 #77](https://github.com/JackZH26/SCLib_JZIS/issues/77).
Contract: [Scientific Discovery projections](../../DISCOVERY_SCIENTIFIC_PROJECTIONS.md).

## Outcome

Added a separately versioned backend companion linking unchanged RPS releases to
actual source-linked native scientific observations. One explicit representative
assessment/state/action is retained per actual material, together with every
alternative. The server does not choose by maximum score or silently collapse
pressures, structures or components. This is the backend prerequisite for the
reviewed browser matrix, not a completed browser integration or real pilot.

The increment adds an observation adapter, representative compiler, append-only
governance, private operator HTTP and opt-in public HTTP. Migration
`0069_discovery_projection` creates only three new tables and their guards; the
application model and account-retention inventory include them. The existing
explicit deployment migration/admission sequence remains.

Original RPS scoring, source/frozen contracts, bundle formats and offline
verifier files are unchanged. No old property registry or scientific-review
profile is expanded. There is no frontend, dependency, hosting or provider
change. All new website/API text is English.

No production database was contacted by tests. No real source import,
scientific/rights approval, DFT/provider job, ML fitting, public enablement,
remote push, PR, deployment or issue closure occurred. Synthetic test accounts
are not real independent human review.

## Scientific and governance boundaries

The eight existing native registry keys retain exact units and
exact/interval/inequality/unreported relations. Zero and legitimate negative
values remain; unknowns are not imputed as zero and distinct components are not
averaged. Geometry and competing-order groups remain planned. Capability counts
describe observations in the exact projection, not production-wide population.

Every observation retains its event revision, exact state/structure/run, typed
source relation/locator, origin and full current review pins. An independently
captured 0067 subject is bridged to the sealed 0054 closure instead of comparing
incompatible hash formats. Currently only the exact sampled-phonon-minimum
proposition has a positive scientific review profile. Event approval, extraction
fidelity, a hash match or old publication permission cannot accept another
scientific field. Registry units do not certify normalization or convergence.

Not-computed, not-applicable and conflicted cells are explicit review-required
declarations with pinned direct selected-context source/producer evidence.
Association alone does not establish the declaration for a property. All matching
native results stay visible, including unreported and inconvenient observations.
The calibration-pending disclaimer and same-campaign/budget/policy/release
comparison scope remain. Negative-control role is not measured-negative evidence.
Empirical policy validation is separate in AL01 #78.

Canonical selection, payload and full-bundle text are retained without JSONB
float rewriting. Registration binds exact base and full scientific-status pins;
commit requires the preview payload hash. A different reviewer approves both
representative selection and disclosure under a new scope, with every sealed
dependency's exact rights target. A third publisher acts on that exact review.
Publication needs at least one currently accepted scientific cell, not a blanket
material or ML approval. The original distribution must independently remain
published and permitted. Protective rejection/withdrawal and retained audit
identity remain available when positive scientific eligibility is lost.

Private HTTP checks explicit roles before upload and under the final serializable
write fence, bounds query/body/chunks/JSON/response and serializes before outer
commit. Preview and exact replay preserve all rows and epochs. Lost acknowledgement
is recovered using the original actor/key/request hash, not a replacement key.
Public reads require explicit new UUID/payload and old RPS release/bundle pins,
two fresh bounded read-only admissions and full semantic payload reconstruction.
They expose no private pending IDs and use no-store/nosniff, with no 304, latest,
highest-score or demo-data fallback. Defaults remain disabled.

## Independent findings corrected

- Different RPS descriptor aliases could produce two rows for one actual SQL
  Material. Ambiguous canonical-material duplication is now rejected.
- Declaration evidence originally needed only sealed membership. It now requires
  direct selected-context sources/producers and their actual artifacts.
- Native review-state guards now require closed shapes, unreviewed null metadata,
  correct fidelity flags, exact current decisions and false blanket authority.
  Application rebuild additionally rejects resealed scalar JSON forgeries.
- A PL/pgSQL local variable collided with a column on the first actual positive
  native publication. Renaming it fixed the executable path without weakening gates.
- Actual HTTP inspection exposed SQLAlchemy `quoted_name` key subclasses in
  `dict(row)`. The new service uses literal DTO keys; strict serialization remains.

## Verification

Final checks passed. The 18 product/integration/test source hashes captured
before and after the final five-module API run are identical. Subsequent edits
only finalize documentation. No whole-API or frontend-build claim is made.

| Check | Result |
| --- | --- |
| Final guarded native API, five new modules below | **239 passed**, 1 existing warning, **473.68 seconds**, exit 0 |
| Native compatibility checkpoint, seven existing modules below | **259 passed**, 20 existing warnings, **340.92 seconds**, exit 0 |
| Final full native Alembic migration rehearsal including 0069 | Passed, exit 0; owned cleanup confirmed |
| Final scripts regression suite | **130 passed**, **11.471 seconds** |
| Ruff import/undefined-name checks on all 18 touched/new Python files | Passed |
| Git whitespace check and independent review | Passed; concrete findings above corrected |

The 239 new tests comprise 35 observation-adapter, 77 representative-projection,
37 governance, 59 private-HTTP and 31 public-HTTP cases. Earlier focused runs
overlap these totals and are not additional tests. The compatibility checkpoint
preceded the final narrow native blanket-authority guard; the final new suite
and migration rehearsal both use that final guarded model. The final warning
is the existing FastAPI `regex` deprecation in `routers/admin.py:83`; the older
schema checks also emit 19 existing Alembic path-separator warnings.

Exact reproduction commands use only the disposable runner's owned services:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server --suite api -- \
  tests/test_discovery_scientific_cells.py \
  tests/test_discovery_scientific_projection.py \
  tests/test_discovery_projection_governance.py \
  tests/test_discovery_projection_http.py \
  tests/test_discovery_scientific_http.py -q --tb=short --show-capture=no

api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server --suite api -- \
  tests/test_schema_lifecycle.py tests/test_research_audit_retention.py \
  tests/test_scientific_adjudication_schema.py \
  tests/test_scientific_adjudication_contract.py \
  tests/test_scientific_result_public_gates.py \
  tests/test_rps_distribution_http.py tests/test_research_distribution_schema.py \
  -q --tb=short --show-capture=no

api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server --suite migrations

api/.venv/bin/python -m unittest discover -s scripts/tests -q
```

Actual HTTP tests cover preview/commit/inspection, current roles and sessions
during upload, all-state equality on replay, new-grant historical recovery,
response serialization before commit, deferred rollback, lost acknowledgement,
strict body/query/resource bounds and cancellation. Public tests cover two fresh
read-only snapshots, all independent configuration pins, actual role/source/
review changes between reads, withdrawal, no private-ID enumeration, no 304 and
no-store errors including method rejection. Committed synthetic fixtures are
held afterward using only their exact owned Material IDs; immutable history is
not deleted and no unrelated fixture or external database is touched.

The final model, service and migration SHA-256 values are respectively
`122c291d3fec7d0b6d0340fa99549021de4db2d9f916673f11058553386257f3`,
`607b42a6c2693ebf311a939b890766f1d06387417ed5bf6855c1b82a2cf88b1c` and
`eefa3f54ad888433445ad99e310bbd386be8f089fb6fb26aba914656353037c0`.

The migration rehearsal upgrades the actual old schema and preserves earlier
historical guards. Old empty round trips exclude only genuinely absent new
tables, after asserting those tables empty; nonempty history snapshots remain
complete. The new empty round trip removes/reinstalls only 0069 objects and
checks previous-head rejection. Actual committed register/review/protective-
withdrawal history then proves no-op replay and fail-closed populated downgrade.

Native fixtures use actual synthetic source bytes, frozen inventory, scientific
decisions, rights and operator transactions in capability-owned PostgreSQL.
They do not establish a reviewed 60-event pilot, production throughput, corpus
scale, actual Linux release-image equivalence or deployment approval. Existing
development services and normal frontend build output are untouched.

## Issue status and next implementation

A fresh read-only issue-list query confirms DR04 #77 and the linked remaining
review backlog are OPEN. This backend increment alone does not meet DR04's real
reviewed data and browser-matrix acceptance. No remote delivery is inferred from
synthetic engineering tests.

Next, connect an explicit approved companion to the English one-row-per-material
matrix, preserving the isolated development-only demo preview. Render exact observations and alternatives
in expandable details, distinguish recorded/accepted values, show supported /
populated / planned capabilities and retain the calibration disclaimer. Then
address the explicitly declared main-barrier gap: current rows retain constraint
codes, not a distinct reviewed `main_barrier`; the UI must not infer one from a
lowest dimension or the first reason. Add representative-selection/review interaction and verify a real independently
reviewed, authorized pilot when available. AL01/ML09 empirical results must not
be fabricated from these fixtures.
