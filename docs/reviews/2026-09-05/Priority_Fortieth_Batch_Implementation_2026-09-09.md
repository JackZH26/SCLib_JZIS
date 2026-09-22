# Fortieth implementation batch: source-scoped current material views

Date: 2026-09-09. Base commit: `baaab4ff63b656d9f816793de72b781f04373ad3`.
Issue advanced: [SC08 / #66](https://github.com/JackZH26/SCLib_JZIS/issues/66).
Related contracts: SC02 atomic property evidence, SC07 source/material read
gates, SC10 reported classifications, SC11 pending structures, RG02 source
occurrences, RG04 selected-input currentness, and 0068 historical answer receipts.
Schema head remains `0068_answer_evidence`.

## Gap resolved

The live SC08 acceptance criteria explicitly distinguish only-source from
mixed-source invalidation. Although aggregation could preserve values from an
unheld source, the old current material policy still hid the whole material.
That suppressed results that had not been invalidated by the other source.

The new conditional v2 policy builds a bounded, exact private record partition.
It admits current reported records only when at least one real source hold and
one exact active unheld record coexist and every material, parent and provenance
gate still passes. This does not establish independent experiments or scientific
truth. Existing v1 policy bytes and old release compiler behavior are unchanged.

See [the complete operator/data contract](../../MATERIAL_SOURCE_SCOPES.md).

## End-to-end implementation

1. `material_source_scope.py` defines the versioned public shape and immutable
   private partition. It rejects malformed, incomplete, over-budget or tampered
   input. All original indices/hashes/source memberships remain bound. Public
   scope counts contain no private source IDs or reviewer notes, and
   `independent_support_count` is explicitly null.
2. The material read adapter resolves current exact Paper/Work lifecycle state
   and bounded ancestry. A v2 parent passes only through a validated compatibility
   bridge preserving its actual revision. Existing global review flags and any
   record provenance quarantine remain restrictive. SQL-unrepresentable or
   overlong Paper IDs never enter SQL, but a separate legacy inventory preserves
   their original v1 invalid-metadata holds instead of silently downgrading them
   to unknown. SQL-compatible legacy whitespace IDs are queried exactly as
   stored for negative lifecycle state, but cannot become v2 eligible sources.
3. Scoped summaries ignore cached values from excluded sources. Atomic Tc
   selection prefers a resolved observation, then a calculation, retaining its
   own source/state/conditions. Separate property columns do not become a joint
   observation. Unknown-origin results remain evidence, not observed headlines.
4. Lists, detail, variants, bookmarks, same-result predicates, phase diagrams and
   hydride enrichment use the same scope. Original result indices/identities
   remain stable; Archive records receive per-record restrictions. Legacy
   bibliographic year/tier are not reused as current scoped facts. Source-count
   filters are evaluated after scoping, including stale undercount/zero cases.
   Sorting uses current projected fields before pagination, with nulls last,
   deterministic ID ties and a bounded top-page heap.
5. Timeline retains point IDs and changes governance-bound dataset/ETag state
   on source-only changes. The old scope-unaware projection returns to current
   raw extraction for a qualifying v2 material. Both cache modes therefore use
   the same eligible records; this is not a measured performance improvement.
6. Paper/Chunk/current-claim occurrences require exact eligible container
   membership. Missing raw Paper ID can use its verified container; conflicting
   IDs and forged public-only scope envelopes fail closed. Search, Ask, exact
   numerical lookup, post-generation currentness and current-history metadata
   all preserve the private binding. Historical receipt bytes remain unchanged.
   A scoped occurrence still requires its own trusted-context anomaly assessment;
   an eligible source cannot approve every other record in that paper.
7. Source and anomaly audits still report every original matching material/raw
   finding. They do not create a new whole-material review flag solely for a
   safely separated source/anomaly hold. Existing flags are never cleared;
   other critical rules still apply. Synthetic SQL verifies repeat execution,
   report-count semantics and transaction rollback.
8. English UI parsers validate the closed v2 schema and bounded counts, show the
   eligible/excluded scope even in compact notices, and reject scientific SEO
   promotion for v2. Source/occurrence DTOs remain v1 and cannot silently inherit
   the broader material parser.

## Verification

The final source-frozen checks are recorded below. Counts describe synthetic
engineering tests, not independent materials, production coverage, or scientific
validation.

| Check | Result |
| --- | --- |
| Guarded native API integration, 34 modules | 826 passed; 217.53 s; disposable cleanup completed |
| Pure script regression | 1,464 passed plus 36 subtests; 54.96 s |
| Frontend full component/unit suite, two workers | 867 passed across 32 files; 84.21 s |
| Frontend source checks | 35 passed; 2.605 s |
| TypeScript `tsc --noEmit` | Passed |
| Python changed-file Ruff `I,F`; `git diff --check` | Passed |

The final API run reported one existing FastAPI `regex` deprecation warning in
`routers/admin.py`; no test failed or errored. Frontend and script sources were
unchanged after their recorded successful full runs.

The source-consumer subset separately passed 336 tests across 14 modules, and
the initial ordering/surface subset passed 18 tests. These overlap the combined
run; their counts must not be added to it as distinct coverage. After the final
legacy-ID fixes, the four-module scope/audit/adapter selection passed 196 tests
in 25.11 s, with disposable cleanup completed.

Initial combined runs contained failures and are not counted as successful
runs. Intermediate 816- and 820-test combined runs passed but preceded the final
legacy-ID compatibility fixes; the final result above supersedes them.
Corrections included function-loop database fixtures with owned Material-row
cleanup, a rollback assertion against the actual JSONB default rather than an
assumed null, and a unique synthetic snapshot pin. The old mixed-source Timeline
assertion was updated to the intentional current-source behavior while checking
the retained raw rows and original point identities. A committed ordering
fixture initially leaked a valid scoped Material into a later global Timeline
test; its fixture now deletes only its own tracked Material IDs during cleanup.
Final cross-review also identified that filtering overlong Paper IDs out of SQL
must not remove v1's invalid-metadata hold. The split current/fallback inventories
are now tested against the unchanged v1 envelope at 500, 501 and 2,000 characters,
as well as mixed-source exclusion with a malformed sibling record.
Real legacy Paper rows containing leading spaces, trailing tabs or embedded
newlines also retain their negative ledger through retracted-to-published
transitions, both with and without another healthy source. A new fixture's
server-generated `updated_at` is explicitly refreshed after its record update
before comparing the pure legacy envelope; implicit asynchronous ORM loading
is not treated as a policy result.

The Discovery registry test previously exceeded its normal deadline by checking
all groups in one case. It now has one case per consecutive group transition,
caches stable control queries, and checks accessible column names in one header
scan. All field, row, score and transition assertions remain; no timeout was
raised. The additional parameterized cases explain the increased test count.

All database tests use owned disposable PostgreSQL/Redis through the guarded
runner, never inherited development/production database settings. No actual
provider calls, data backfill, source review approval or scheduled production
audit is used.

Reproduce the combined API selection from the repository root (the runner
creates and verifies its own private disposable services):

```bash
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server --suite api -- \
  tests/test_material_source_scope.py tests/test_material_source_scope_audit.py \
  tests/test_material_source_scope_surfaces.py tests/test_material_source_scope_ordering.py \
  tests/test_material_visibility.py tests/test_material_visibility_adapter.py \
  tests/test_material_visibility_surfaces.py tests/test_material_property_projection.py \
  tests/test_material_semantics_surfaces.py tests/test_anomaly_surfaces.py \
  tests/test_source_lifecycle_audit.py tests/test_hydride_visibility.py \
  tests/test_timeline_projection.py tests/test_timeline_projection_identity.py \
  tests/test_timeline_http_cache.py tests/test_bookmarks.py \
  tests/test_source_scope_occurrences.py tests/test_source_visibility.py \
  tests/test_source_lifecycle_status.py tests/test_retrieval_currentness.py \
  tests/test_retrieval_groups.py tests/test_scientific_query_http.py \
  tests/test_scientific_mixed_ask.py tests/test_scientific_lookup_preparation.py \
  tests/test_history_evidence.py tests/test_answer_evidence.py \
  tests/test_answer_history_http.py tests/test_ml_foundation.py \
  tests/test_scientific_search_routing.py tests/test_rag_search_lineage.py \
  tests/test_materials_phase1_contract.py tests/test_source_lifecycle_aggregation_sql.py \
  tests/test_background_job_handlers.py tests/test_research_publication_http.py \
  -q --tb=short --show-capture=no
```

## Scientific and delivery boundaries

The scope is current reported-record eligibility, not a reviewed result/state
association, independent replication count, superconductivity probability or
approved ML label. Unknown source state cannot contribute to v2. Bibliographic
reactivation cannot erase a durable negative lifecycle event. Existing material
holds are sticky; this change does not automatically repair historical blanket
review flags.

List ordering reflects current projected values, not RPS or a calibrated
research-priority ranking. The raw fallback is explicit until a later scope-aware Timeline
projection has its own evidence. Saved answers/0068 receipts, original archives
and frozen ML release dependencies are not rewritten or retroactively approved.

Live issue #66 remains OPEN. Exact-version positive scientific reinstatement,
agreed/measured propagation SLA, full downstream ML/RPS current acceptance and
production rollout remain separate unfinished gates. The overall goal remains
active; a green local suite does not close all repository issues. Branch push,
PR/CI delivery, merge and deployment are not implied by this report.

## Next dependency item

The next bounded P1 increment is ML06 / #70: a separately versioned,
negative-only label-currentness capture and compiler path. The current v3 review
companion starts from optional feature inputs; it cannot be represented as full
current-label coverage for the composition-only cohort. The next design must
root the inventory in every frozen dataset example, include Claim/QC/event and
exact source dependencies, preserve excluded nodes as leakage-group bridges,
and rebuild splits and train-only preprocessing after label holds. New positive
reviews must not backfill missing evidence into old frozen labels. Old v1/v2/v3
artifacts and compiler source pins remain unchanged. This paragraph is a scoped
development handoff, not a claim that the next implementation is complete.
