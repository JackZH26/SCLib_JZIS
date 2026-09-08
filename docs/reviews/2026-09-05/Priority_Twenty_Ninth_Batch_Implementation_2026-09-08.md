# Twenty-ninth implementation batch — scientific-feature provenance and fixed-cohort ML

Date: 2026-09-08. Branch: `codex/sclib-research-v2`.
Baseline: `bb7e5f4` (twenty-eighth batch).
Priority: [ML06 / #70](https://github.com/JackZH26/SCLib_JZIS/issues/70), with
the limited-property and coordinate dependency in
[ML05 / #67](https://github.com/JackZH26/SCLib_JZIS/issues/67).
Specification: [Restricted scientific datasets v2](../../ML_SCIENTIFIC_DATASETS_V2.md).

## Outcome

The exact composition baseline can now be compared with seven explicitly
defined computed normal-state properties and two real-coordinate descriptors,
using separately source-bound physical/structure inputs and one fixed base
split. A real SQL candidate inventory can pass through unchanged 0054 freezing,
new 0064 companion capture, offline v2 compilation and independent complete
recomputation. This is an executable private canary, not an unused table or an
unsupported expansion of the v1 feature-budget enum.

The new cohort design retains independently valid composition labels when an
optional input fails. Enhanced comparisons use identical sample subsets and
assignments, not a comparison between a large easy baseline and a small
selectively complete physics cohort. Missingness and no-go partitions are
reported honestly; the compiler does not resplit or select a favorable seed.

No real expert review, external source permission or scientific acceptance was
created. No production migration, deployment, data backfill, public release,
model training, paid computation, push, PR or remote issue closure was performed.
Existing public Discovery/RPS behavior and English defaults are unchanged.
#67, #70 and the overall goal remain open for their full acceptance gates.

## Delivered

1. Additive 0064 input-scoped append-only feature-source bindings with real
   release/input/revision/capture/Work/review foreign keys and frozen-row checks.
   The 0045 registry, 0052 claim-source tables, 0054 capsule, v1 task/compiler and
   existing source-bound formula features remain byte-for-byte unchanged.
2. Exact private feature-source review documents pinning both sides of
   applicability, the result/run/structure context, own source version and
   capture bytes, locator, scientific protocol and actual review artifact bytes.
   Strict Boolean declarations never become authenticated scientific authority.
3. Default-preview trusted registration with SERIALIZABLE integrity locking,
   bounded nonblocking lock acquisition, savepoint-only writes and exact no-op
   replay. The outer transaction remains the authorized caller's responsibility.
4. Complete stable-snapshot companion capture, including all actual bindings,
   source metadata closure, related-paper lifecycle holds, capture-sibling
   conflicts and full exact bytes. Source grouping includes reachable paper/Work
   bridges without promoting them into independent availability witnesses.
5. Separate internal body checksum and independent full canonical file pin;
   source/metadata/inventory/bytes and both digests are independently checked.
   No alteration of an older frozen capsule or fake Tc source occurrence.
6. Closed v2 tasks with exact bulk-only normal-state DFT/DFPT semantic profiles,
   original registry/component/unit/origin checks, protocol pins, retained typed
   reference/q-sampling/broadening data and source-formula reference coverage.
   Valid zeros remain zero; absent, censored, nonfinite and Boolean values do not.
7. Actual closed input/output run manifests, exact output membership and
   additive declared result dependencies. Unpublished operational calculations
   and unresolved parent-run receipts remain unsupported rather than backdated.
8. Actual coordinate parsing from bounded explicit-site JSON or a documented
   VASP5 POSCAR subset, with cell/site/composition/hash checks. Volume per atom
   and conventional mass density are intensive; no text/prototype or ordinal
   space-group substitute, isotope mass guess or vacuum correction is made.
9. Exact state applicability or a separately reviewed normal-state surrogate,
   with hard material/composition/sample/pressure/field/phase checks and pinned
   structural contexts. A legitimate 0 K simulation bridge is possible; known
   contradictions cannot be overridden by a positive flag.
10. Source-known-by and complete dependency timing, including coordinate parents,
    checked both against task cutoff and label availability. Invalid or
    target-derived supporting inputs propagate holds to their dependent features.
11. Tc, non-transition/non-detection, RPS and superconducting-response ancestry
    exclusion, including exact multi-hop/renamed SQL and actual run-document
    references. Noncausal evidence links merge groups without becoming derivations.
12. Shared-run/state/structure/common-protocol gate when lambda and omega-log are
    jointly present. Conflicting pairs are withheld; incomplete pairs keep their
    missingness. No independent alpha-squared-F spectral re-integration is claimed.
13. Full captured-relation grouping before base split, B/P/S/PS cohort accounting,
    same-subset composition controls and train-only preprocessing per view.
    Optional-feature failures retain B; empty or untrainable comparisons are no-go.
14. Private offline CLI with stable bounded no-alias file capture, independent
    pins, exact full recomputation, no overwrite, owner-only new outputs, no-go
    output suppression and private error handling. Original v1 CLI is unchanged.
15. Independent migrated-schema roundtrip, actual source workflow and populated
    downgrade refusal, after all older independent historical-ledger guards.

## Review findings resolved during implementation

- A property and its coordinates need their own source occurrence; the old Tc
  Work/capture and run creation timestamp cannot supply a convenient date.
- Additional source tables do not automatically join the frozen 0054 closure.
  A separately pinned complete companion is required and is consumed by the CLI.
- Comparing only the feature's leaf date allowed a late required structure to
  cross the label-time boundary. The complete DAG's effective date is now checked.
- Excluding bad coordinates only from S still left a dependent property in P.
  Supporting scientific/applicability checks now propagate independently of
  whether structure columns are requested.
- A non-detection is itself a superconductivity outcome; it is blocked as target
  ancestry even though it has no positive Tc value.
- Property-specific EPC protocol hashes differ by definition. Joint coherence
  compares their shared protocol projection and exact run/state/structure, not
  unequal full property hashes or merely equal method names.
- Arbitrary protocol hashes without actual retained reference/grid contents
  were insufficient. Typed data and source-element coverage are now checked.
- Materials use existing String(100) IDs, not the UUID type of research rows;
  the physical validator now accepts actual catalogue identity correctly.
- Extremely large JSON integers could overflow a finite-number predicate and
  abort the whole compiler. Range checking now precedes float conversion.
- A failing run/structure assertion could discard otherwise resolvable input
  references from grouping. Bounded exact references are retained conservatively.
- A duplicate physical feature-key overwrite was considered defensively.
  Existing 0045 SQL uniqueness already blocks that real insertion; both the SQL
  regression and a no-arbitrary-choice compiler guard preserve this invariant.
- Existing `models` package imports include ORM/configuration. The new runtime
  declaration therefore names the locked API interpreter; tests establish no
  network/database connection, not a false claim that no ORM definitions load.
- Native/subprocess comparisons caught source edits during an in-progress test
  run. The final verification is performed with executable files frozen; no
  equality assertion was weakened to hide changed compiler-source hashes.

## Verification

Final complete-suite results are recorded below. Intermediate
focused runs are not added to complete-suite totals. All positive sources,
reviewers, physical results and coordinate examples in these tests are synthetic.

| Check | Final result |
| --- | --- |
| Full API, owned native PostgreSQL/Redis | 4,643 passed; 20 existing warnings; 893.55 s |
| Full ingestion, inert PostgreSQL/Redis endpoints | 1,275 passed; 34 existing warnings; 11.15 s |
| Full scripts | 597 passed plus 36 subtests; 11.11 s |
| Full frontend components | 507 passed across 27 files; 22.17 s |
| Frontend source checks | 35 passed; 2.77 s |
| TypeScript | `tsc --noEmit` passed; no diagnostics |
| API/ingestion dependency locks | Both `uv lock --check` passed |
| Independent native migration rehearsal | Passed, including all older guards and empty/nonempty 0064 cases |
| Changed Python modules/tests | Ruff I/F passed |
| Patch whitespace and frozen v1 paths | Diff checks passed; v1 paths unchanged |

Total: **7,057 ordinary tests plus 36 subtests**, with no skipped cases in
these complete suites. This batch adds **278 ordinary tests**: 265 API
(181 task/property/coordinate, 34 companion/schema, 35 actual SQL/CLI,
15 dependency/numeric guard cases) and 13 scripts (11 CLI capture and two
migration lifecycle checks). Native SQL/CLI focused verification also passed
all 35 cases on frozen executable sources before the complete API run finished.
The owned test runner removed only its disposable services and temporary data.

Actual end-to-end cases include five independently grouped synthetic materials,
all seven property profiles, both supported coordinate formats, real run
manifests, own source captures and exact reviews. Positive and negative tests
cover the normal-state bridge, missing values versus valid zeros, full ancestry,
source/version/capture timing, conflicting spectral protocols, source bridges,
held-out extremes, all C/P/S selection combinations, CLI no-go, independent
rebuild and re-pinned output/source/review tampering.

## Remaining work and next priority

- Assemble real, redistribution-permitted small source packages and obtain
  actual scientific/source/applicability review. Synthetic contracts prove the
  technical workflow, not the quality of a real cross-family research dataset.
- Connect the trusted source/physical-property preparation steps to a bounded
  private curation/import workflow; do not auto-generate approved expert reviews.
- Extend model/task evaluation and adapters only after real label coverage,
  independent groups, feature completeness and time gates have been measured.
- Add new profile versions for justified observed proxies, isotope/disordered
  structures, 2D/moiré geometry, harmonized protocols or unpublished operational
  run receipts; do not weaken current frozen scientific meanings in place.
- Apply the separate current rights/release policy before training distribution
  or public publication. RPS publication governance is not ML dataset consent.

No externally required gate is silently marked complete. There is still useful
in-scope technical work, so the persistent goal remains active.
