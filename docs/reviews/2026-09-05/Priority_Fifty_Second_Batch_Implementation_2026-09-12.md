# Batch52 — explicit main barriers and refreshed engineering evidence

Date:2026-09-12. Base HEAD:`00718749b6eb15926ae8cbfc58e02a9432488815`.
Changes are local worktree implementation, not a pushed PR or deployment.
Tracking: DR04 #77; engineering readiness for #42/#56/#59/#58/#52.

## Delivered capability

Discovery now has a closed, versioned curator-declared main barrier, connected
from preparation through native registration, independent review and publication
to the compact scientific material matrix. V2 supports an explicit nondeclaration
or a statement/rationale with a qualified category and exact selected-context
basis. The four categories distinguish evidence gaps, execution constraints,
scientific hypotheses and recorded policy reasons.

The [final contract](../../DISCOVERY_MAIN_BARRIERS.md) specifies shapes, limits,
references, migration and scientific boundaries. Main barriers do not infer
physical truth from a score, fill unknown values with zero, change frozen RPS,
or authorize ML training. Original v1 documents and registry capabilities remain
unchanged. New declaration edits need fresh package/review pins.

The UI remains English. Declaration, category and basis have no default.
Assessment/structure/cell edits clear the declaration; any edit clears the
prepared preview and rehearsal. Expanded public, curator and governance views
show the rationale and exact basis/context. Existing no-store, authorization,
deadline, session clearing and original-request recovery paths remain intact.

Full frontend regression also exposed an existing source-task unload-listener
race: a committed receipt could render before passive-effect cleanup removed
the old unconditional warning handler. The correction uses a mount-lifetime
listener that checks the current in-memory recovery reference when invoked.
The reference is set before a commit await and cleared synchronously on a
verified receipt; unknown operations remain protected without a false warning
after completion. A deterministic regression exercises the retained listener
directly, so effect-cleanup timing cannot hide the bug.

## Native persistence and compatibility

Migration`0070_discovery_main_barrier` adds a paired-version guard without editing
the original0069 migration or model. It checks declaration shape, category,
recorded reason membership, matching selected cell cores, and identical
representative/row declarations. Authenticated full current reconstruction
remains responsible for exact native observations and their provenance; the SQL
helper is not an independent scientific adjudicator.

The rehearsal independently executes the old0069 nonempty-history guard before
introducing v2. It then verifies empty and v1-populated0070/0069 roundtrips,
restoration of the original SQL function body, unchanged retained v1 JSON TEXT
and record hashes, no-op original-key replay, actual v2 nondeclaration and
evidence-gap packages, and refusal to downgrade while v2 history exists.

Barrier text validation is aligned across Python, PostgreSQL and TypeScript for
Unicode whitespace and code-point ordering, including astral Unicode. This
alignment is scoped to v2 declarations and does not redefine v1 text parsing.

## Evidence and reproducibility

| Check | Terminal result |
| --- | --- |
| Final new main-barrier API module, guarded native services | 52 passed;80.32s; one pre-existing FastAPI regex deprecation warning |
| Combined Discovery + engineering API regression, guarded native services | 538 passed;1,086.16s;20 existing deprecation warnings; owned cleanup completed |
| Full scripts suite | 1,671 passed,36 subtests;67.28s |
| Targeted frontend compatibility/UI/native-wire selection | 275 passed across6 files;29.18s |
| Source-task correction and deterministic listener regression | 73 passed;8.10s |
| Final full frontend suite after correction | 1,353 passed across40 files;130.00s |
| Final English/source checks and TypeScript | 38 source checks passed; `tsc --noEmit --incremental false` exit0 |
| Native full schema rehearsal | Passed;0070;92,291ms;637 source pins; owned cleanup verified |
| Final isolated Next.js production build after source-task correction | Exit0;35 static-generation items;Next.js15.5.21 |

The first full frontend run, concurrent with the isolated build, had1,350 passes
and two failures: an unchanged layout-preview test exceeded its5-second limit,
and the source-task test observed the stale listener after a verified receipt.
The latter was diagnosed and corrected in the implementation, not dismissed as
load or hidden by waiting for cleanup. No test deadline was widened or assertion
removed. Final whole-suite and build results are recorded after that correction.

The final build used the owned source copy
`/tmp/sclib-main-barrier-build.tQmnYN/frontend`, copy-on-write installed
dependencies, the existing offline font fixture, `/sclib` base path and inert
loopback API origins. All137 relevant app/component/library/configuration and
dependency-manifest input files matched the final worktree. It did not overwrite
the regular `.next` or start/stop an existing development service. Build success
is not authenticated live-browser QA or a deployed performance measurement.

The latest API capture comes from the actual guarded SQL-to-HTTP test
`test_barrier_edit_needs_new_preview_package_and_independent_review_then_source_hold`.
It contains original response strings for selection access/context/preparation,
operator access/governance inspection and public reconstruction, plus255 actual
source hashes. The frontend verifies the original payload and selection byte
hashes, rather than passing Python floating quantities through JavaScript
reserialization. Its checked-in synthetic wire file SHA-256 is
`1873c02e3d9305ec4c3d048706193447aa4c12b156afa7a003d83796c91f9f7a`.
Batch54 preserves those exact historical bytes as
`frontend/tests/fixtures/discovery-main-barrier-native.batch52.wire.json` and
recaptures the current compatibility fixture against the 0071 implementation.
The 255 hashes above describe batch52, not the later source tree.

Additional frontend adversarial fixtures are explicitly re-sealed synthetic
adapters, not actual backend responses. Historical v1 wire/provenance assets
are byte-unchanged. Their tests verify immutable provenance and asset hashes
without pretending the historical source pins describe today's implementation
or requiring deep Git history in shallow CI. Current compatibility is supported
by the new native capture and current v1 regressions, not by relabeling old data.

The complete native schema receipt is archived as
[DR04_Main_Barrier_Schema_2026-09-12-01.json](measurements/DR04_Main_Barrier_Schema_2026-09-12-01.json).
Its full-file SHA-256 is
`1360aaf2fd0c2dcc4adefab5369b32a2bc4f3ac18b7b7bb67eba9fbb58bbf18a`;
closed schema/body and all637 source pins were independently verified after
publication. The receipt records actual dirty-worktree input hashes, not a
fictional new commit. Its established v1 table/outcome vocabulary is unchanged;
new0070 assertions are in the pinned executed harness rather than invented
new report counters.

Reproduce the final new API module from the repository root:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite api -- \
  -q tests/test_discovery_main_barrier.py --tb=short
```

For full migration evidence, use the same runner with`--suite migrations` and
`--report` naming a new file in an existing owned nonsymlink directory. Do not
reuse this run's services/capability or overwrite previous receipts.

The combined API regression selection uses the same native runner and these
files (not the whole API suite):

```text
test_discovery_main_barrier.py
test_discovery_scientific_projection.py
test_discovery_projection_governance.py
test_discovery_projection_http.py
test_discovery_selection_preparation.py
test_discovery_operator_history.py
test_discovery_scientific_http.py
test_disposable_environment.py
test_schema_lifecycle.py
test_discovery_feed_validation.py
test_discovery_cache.py
test_background_job_schema.py
test_background_jobs.py
test_background_job_recovery.py
test_background_job_processes.py
test_background_projection_recovery.py
test_background_job_handlers.py
test_background_jobs_http.py
test_stats_consistency.py
test_timeline_projection.py
```

The combined run includes the original44 main-barrier cases. The final52-case
module was separately rerun after adding Unicode parity and richer capture
checks. These overlapping test counts must not be added as unique coverage.
The20 combined-run warnings are one existing FastAPI regex deprecation and19
Alembic `path_separator` deprecations, not failed assertions. The engineering
subset includes real two-process/SIGKILL background-cycle recovery, not only
mocked concurrency.

## Engineering readiness and what remains

The [current engineering readiness audit](Engineering_Delivery_Readiness_2026-09-12.md)
adds a complete six-criterion EN01 mapping and identifies the existing DR03,
EN03, EN02 and EN04 implementations. This batch refreshes relevant local
evidence instead of recreating their existing frameworks. No matching remote
branch or PR was found in fresh read-only checks. No issue is closed by these
local results.

Remaining gates include authorized remote delivery and exact-revision Linux
Test/final-image evidence, real independently reviewed pilot data, source/ML-use
authorization, real scientific baseline comparison and AL01 fixed-budget
evaluation. DR04 cannot close solely because synthetic data renders correctly.
No real scientific approval, real training, provider calculation, production
migration/backfill/deployment or authenticated live-browser/device QA is claimed.
