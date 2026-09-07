# SCLib review implementation backlog — 2026-09-05

[GitHub master tracker #41](https://github.com/JackZH26/SCLib_JZIS/issues/41) · [All review issues](https://github.com/JackZH26/SCLib_JZIS/issues?q=is%3Aissue%20label%3Areview%3A2026-09-05) · [Milestones](https://github.com/JackZH26/SCLib_JZIS/milestones)

Published **38 GitHub issues: 1 tracker + 37 independently testable execution items (22 P1, 15 P2)**. All 20 hard acceptance invariants from the comprehensive review have explicit owners in this backlog. No due dates or individual assignees have been imposed.

## Scope and evidence boundary

The source is `SCLib_Comprehensive_Review_2026-09-05.md`. Its review examined the local `codex/sclib-research-v2` worktree based on `44fd6ce377c89d4b4e1b78dbe082f420c33b8814`, including uncommitted changes; the checked public/default-branch revision was `d26fc098565492b78b416fb30b6b1ec7087b24c7`. Some referenced v2 files are not yet published. Verify the intended target before implementation: local defects or synthetic counterexamples do not prove production prevalence.

Each GitHub issue reproduces its relevant source-code evidence, scope, acceptance criteria, exclusions, owner role and dependency links; it does not require access to a private report path.

This backlog does **not** authorize production migrations/backfills, deployment, full-corpus extraction/re-embedding, paid calculations, source redistribution or scientific publication approval. The review-specific files are planning artifacts; no application code is changed by their creation.

## How to execute

- P1 is a scientific-integrity, admissibility or operational-safety gate, not an allegation of an active P0 incident. P2 remains required before its declared capability is released.
- Dependencies define prerequisite contracts for closure. Design may proceed in parallel; phase letters are completion gates, not rigid serial scheduling or dates.
- Start with [EN01 #42](https://github.com/JackZH26/SCLib_JZIS/issues/42) before any database/Redis-destructive tests. Existing test setup is not safe to run against inherited connection settings.
- Independently start [SC01 #44](https://github.com/JackZH26/SCLib_JZIS/issues/44), [SC05 #46](https://github.com/JackZH26/SCLib_JZIS/issues/46), [SC09 #51](https://github.com/JackZH26/SCLib_JZIS/issues/51), [DR03 #56](https://github.com/JackZH26/SCLib_JZIS/issues/56) and [DR01 #55](https://github.com/JackZH26/SCLib_JZIS/issues/55), following the child dependency chains.
- Start the manual 60-event pilot [ML08 #54](https://github.com/JackZH26/SCLib_JZIS/issues/54) in parallel. It does not wait for a completed loader and must preserve unresolved evidence rather than manufacture missing fields.
- Build source/revision/import/freeze and permission contracts before datasets, public research interfaces and release packages.
- [DR04 #77](https://github.com/JackZH26/SCLib_JZIS/issues/77) can close with real reviewed rows and an explicit calibration-pending disclaimer. Empirical RPS/multi-fidelity policy evaluation belongs to [AL01 #78](https://github.com/JackZH26/SCLib_JZIS/issues/78); a documented no-go or inconclusive result is a valid outcome.
- Close issues with linked PRs, exact revisions, acceptance evidence and migration/compatibility notes. Document approved deferrals and keep their release restrictions visible in #41. Do not silently remove scientific gates.
- Website-owned labels, errors, tooltips and accessibility copy default to English; original source text/user content retains its language.

## Milestone gates

| Phase | Gate | Execution items |
|---|---|---|
| A | [A — Scientific correctness and operational safeguards](https://github.com/JackZH26/SCLib_JZIS/milestone/1) | 15 |
| B | [B — Reviewed evidence pilot](https://github.com/JackZH26/SCLib_JZIS/milestone/2) | 2 |
| C | [C — Versioned research data foundation](https://github.com/JackZH26/SCLib_JZIS/milestone/3) | 12 |
| D | [D — Reproducible datasets and research interfaces](https://github.com/JackZH26/SCLib_JZIS/milestone/4) | 7 |
| E | [E — Validated discovery and active-learning policy](https://github.com/JackZH26/SCLib_JZIS/milestone/5) | 1 |

The initial practical focus is phase A plus the evidence pilot; this listing is not an instruction to run every data pipeline immediately.

## Scientific correctness and result semantics

| Issue | Priority | Phase | Deliverable | Required dependencies |
|---|---|---|---|---|
| [SC01 #44](https://github.com/JackZH26/SCLib_JZIS/issues/44) | P1 | A | Preserve raw scientific values, units, intervals, censoring and uncertainties during extraction | None |
| [SC02 #47](https://github.com/JackZH26/SCLib_JZIS/issues/47) | P1 | A | Keep every aggregated property atomic with its state, method and source result | [SC01 #44](https://github.com/JackZH26/SCLib_JZIS/issues/44), [SC04 #45](https://github.com/JackZH26/SCLib_JZIS/issues/45), [SC05 #46](https://github.com/JackZH26/SCLib_JZIS/issues/46) |
| [SC03 #48](https://github.com/JackZH26/SCLib_JZIS/issues/48) | P1 | A | Replace scientific value caps and destructive threshold filtering with versioned anomaly review | [SC01 #44](https://github.com/JackZH26/SCLib_JZIS/issues/44), [SC02 #47](https://github.com/JackZH26/SCLib_JZIS/issues/47) |
| [SC04 #45](https://github.com/JackZH26/SCLib_JZIS/issues/45) | P1 | A | Make pressure explicit and require compound scientific filters to match the same result | [SC01 #44](https://github.com/JackZH26/SCLib_JZIS/issues/44) |
| [SC05 #46](https://github.com/JackZH26/SCLib_JZIS/issues/46) | P1 | A | Share a result-level Observed/Computed/Inferred classification and independent source-role policy | None |
| [SC06 #50](https://github.com/JackZH26/SCLib_JZIS/issues/50) | P1 | A | Rebuild Timeline semantics around result identity, explicit dates and honest sampling | [SC04 #45](https://github.com/JackZH26/SCLib_JZIS/issues/45), [SC05 #46](https://github.com/JackZH26/SCLib_JZIS/issues/46), [SC07 #49](https://github.com/JackZH26/SCLib_JZIS/issues/49) |
| [SC07 #49](https://github.com/JackZH26/SCLib_JZIS/issues/49) | P1 | A | Apply shared review visibility and warning policies to all material read surfaces | [SC05 #46](https://github.com/JackZH26/SCLib_JZIS/issues/46) |
| [SC08 #66](https://github.com/JackZH26/SCLib_JZIS/issues/66) | P1 | C | Propagate source corrections and retractions through reviews, projections, caches and releases | [SC07 #49](https://github.com/JackZH26/SCLib_JZIS/issues/49), [ML01 #57](https://github.com/JackZH26/SCLib_JZIS/issues/57), [ML03 #61](https://github.com/JackZH26/SCLib_JZIS/issues/61), [ML04 #64](https://github.com/JackZH26/SCLib_JZIS/issues/64) |
| [SC09 #51](https://github.com/JackZH26/SCLib_JZIS/issues/51) | P1 | A | Make composition parsing isotope-aware before emitting exact formula features | None |
| [SC10 #53](https://github.com/JackZH26/SCLib_JZIS/issues/53) | P2 | A | Separate unknowns, priors, conflicts and independent support in material semantics | [SC05 #46](https://github.com/JackZH26/SCLib_JZIS/issues/46) |
| [SC11 #63](https://github.com/JackZH26/SCLib_JZIS/issues/63) | P2 | B | Bind structure and phase extraction to local material/state evidence instead of whole-paper fallback | [SC01 #44](https://github.com/JackZH26/SCLib_JZIS/issues/44), [SC02 #47](https://github.com/JackZH26/SCLib_JZIS/issues/47), [SC05 #46](https://github.com/JackZH26/SCLib_JZIS/issues/46) |

## Research data, datasets and ML

| Issue | Priority | Phase | Deliverable | Required dependencies |
|---|---|---|---|---|
| [ML01 #57](https://github.com/JackZH26/SCLib_JZIS/issues/57) | P1 | C | Preserve source revisions and result-level availability for temporal research | [EN01 #42](https://github.com/JackZH26/SCLib_JZIS/issues/42) |
| [ML02 #43](https://github.com/JackZH26/SCLib_JZIS/issues/43) | P1 | A | Enforce claim/example integrity and quarantine contradictory negative labels | [EN01 #42](https://github.com/JackZH26/SCLib_JZIS/issues/42) |
| [ML03 #61](https://github.com/JackZH26/SCLib_JZIS/issues/61) | P1 | C | Implement a revision-aware, idempotent shadow research loader | [ML01 #57](https://github.com/JackZH26/SCLib_JZIS/issues/57), [ML02 #43](https://github.com/JackZH26/SCLib_JZIS/issues/43), [SC01 #44](https://github.com/JackZH26/SCLib_JZIS/issues/44), [SC04 #45](https://github.com/JackZH26/SCLib_JZIS/issues/45), [SC05 #46](https://github.com/JackZH26/SCLib_JZIS/issues/46), [SC07 #49](https://github.com/JackZH26/SCLib_JZIS/issues/49), [SC09 #51](https://github.com/JackZH26/SCLib_JZIS/issues/51), [EN01 #42](https://github.com/JackZH26/SCLib_JZIS/issues/42) |
| [ML04 #64](https://github.com/JackZH26/SCLib_JZIS/issues/64) | P1 | C | Freeze complete research dependency closures with concurrency-safe DAG integrity | [ML03 #61](https://github.com/JackZH26/SCLib_JZIS/issues/61), [EN01 #42](https://github.com/JackZH26/SCLib_JZIS/issues/42) |
| [ML05 #67](https://github.com/JackZH26/SCLib_JZIS/issues/67) | P2 | C | Implement a limited scientific property importer with state, structure and run validation | [ML03 #61](https://github.com/JackZH26/SCLib_JZIS/issues/61), [SC02 #47](https://github.com/JackZH26/SCLib_JZIS/issues/47), [SC11 #63](https://github.com/JackZH26/SCLib_JZIS/issues/63) |
| [ML06 #70](https://github.com/JackZH26/SCLib_JZIS/issues/70) | P1 | D | Build task-specific ML datasets with split, temporal and dependency-leakage gates | [ML01 #57](https://github.com/JackZH26/SCLib_JZIS/issues/57), [ML02 #43](https://github.com/JackZH26/SCLib_JZIS/issues/43), [ML04 #64](https://github.com/JackZH26/SCLib_JZIS/issues/64), [ML05 #67](https://github.com/JackZH26/SCLib_JZIS/issues/67), [SC09 #51](https://github.com/JackZH26/SCLib_JZIS/issues/51), [SC10 #53](https://github.com/JackZH26/SCLib_JZIS/issues/53) |
| [ML07 #68](https://github.com/JackZH26/SCLib_JZIS/issues/68) | P1 | C | Restrict public research access to approved releases and enforce recursive export policies | [ML04 #64](https://github.com/JackZH26/SCLib_JZIS/issues/64), [SC07 #49](https://github.com/JackZH26/SCLib_JZIS/issues/49) |
| [ML08 #54](https://github.com/JackZH26/SCLib_JZIS/issues/54) | P1 | B | Run a 60-event reviewed pilot and publish data quality, missingness and curation effort | None |
| [ML09 #76](https://github.com/JackZH26/SCLib_JZIS/issues/76) | P2 | D | Publish reproducible ML baseline evaluations against audited dataset releases | [ML06 #70](https://github.com/JackZH26/SCLib_JZIS/issues/70), [ML07 #68](https://github.com/JackZH26/SCLib_JZIS/issues/68), [ML08 #54](https://github.com/JackZH26/SCLib_JZIS/issues/54) |
| [AL01 #78](https://github.com/JackZH26/SCLib_JZIS/issues/78) | P2 | E | Validate RPS and multi-fidelity action selection with a fixed-budget, leakage-safe replay | [ML09 #76](https://github.com/JackZH26/SCLib_JZIS/issues/76), [DR01 #55](https://github.com/JackZH26/SCLib_JZIS/issues/55), [DR02 #74](https://github.com/JackZH26/SCLib_JZIS/issues/74), [ML05 #67](https://github.com/JackZH26/SCLib_JZIS/issues/67) |

## Discovery and RPS

| Issue | Priority | Phase | Deliverable | Required dependencies |
|---|---|---|---|---|
| [DR01 #55](https://github.com/JackZH26/SCLib_JZIS/issues/55) | P1 | A | Gate RPS actions on verified prerequisites and complete resources, and explain contributions honestly | None |
| [DR02 #74](https://github.com/JackZH26/SCLib_JZIS/issues/74) | P1 | D | Publish independently verifiable RPS bundles and isolate catalog failures with revision-safe caching | [DR01 #55](https://github.com/JackZH26/SCLib_JZIS/issues/55), [ML07 #68](https://github.com/JackZH26/SCLib_JZIS/issues/68) |
| [DR03 #56](https://github.com/JackZH26/SCLib_JZIS/issues/56) | P1 | A | Validate legacy Discovery feeds before atomic publication and pin pagination/detail to one version | None |
| [DR04 #77](https://github.com/JackZH26/SCLib_JZIS/issues/77) | P2 | D | Connect the scientific Discovery matrix to reviewed data with explicit representative actions and calibration limits | [DR01 #55](https://github.com/JackZH26/SCLib_JZIS/issues/55), [DR02 #74](https://github.com/JackZH26/SCLib_JZIS/issues/74), [ML05 #67](https://github.com/JackZH26/SCLib_JZIS/issues/67), [ML04 #64](https://github.com/JackZH26/SCLib_JZIS/issues/64), [SC07 #49](https://github.com/JackZH26/SCLib_JZIS/issues/49), [ML08 #54](https://github.com/JackZH26/SCLib_JZIS/issues/54) |

## Scientific retrieval and RAG

| Issue | Priority | Phase | Deliverable | Required dependencies |
|---|---|---|---|---|
| [RG01 #62](https://github.com/JackZH26/SCLib_JZIS/issues/62) | P1 | A | Separate citation-index validity from scientific support and validate numerical/material-state claims | [SC01 #44](https://github.com/JackZH26/SCLib_JZIS/issues/44), [SC04 #45](https://github.com/JackZH26/SCLib_JZIS/issues/45), [SC05 #46](https://github.com/JackZH26/SCLib_JZIS/issues/46) |
| [RG02 #65](https://github.com/JackZH26/SCLib_JZIS/issues/65) | P1 | C | Type original versus derived Facts evidence and prevent circular provenance from validating extracted claims | [ML01 #57](https://github.com/JackZH26/SCLib_JZIS/issues/57), [ML03 #61](https://github.com/JackZH26/SCLib_JZIS/issues/61), [SC05 #46](https://github.com/JackZH26/SCLib_JZIS/issues/46), [SC04 #45](https://github.com/JackZH26/SCLib_JZIS/issues/45) |
| [RG03 #69](https://github.com/JackZH26/SCLib_JZIS/issues/69) | P2 | C | Version chunks and embedding generations, enforce hard token bounds and reconcile SQL/vector indexes safely | [RG02 #65](https://github.com/JackZH26/SCLib_JZIS/issues/65), [EN01 #42](https://github.com/JackZH26/SCLib_JZIS/issues/42) |
| [RG04 #75](https://github.com/JackZH26/SCLib_JZIS/issues/75) | P2 | D | Route scientific queries to state-aware results or complementary source evidence and establish an adjudicated gold evaluation | [RG01 #62](https://github.com/JackZH26/SCLib_JZIS/issues/62), [RG02 #65](https://github.com/JackZH26/SCLib_JZIS/issues/65), [RG03 #69](https://github.com/JackZH26/SCLib_JZIS/issues/69), [SC04 #45](https://github.com/JackZH26/SCLib_JZIS/issues/45), [SC09 #51](https://github.com/JackZH26/SCLib_JZIS/issues/51), [ML07 #68](https://github.com/JackZH26/SCLib_JZIS/issues/68) |

## Engineering safeguards and operations

| Issue | Priority | Phase | Deliverable | Required dependencies |
|---|---|---|---|---|
| [EN01 #42](https://github.com/JackZH26/SCLib_JZIS/issues/42) | P1 | A | Fail closed before tests can connect to non-disposable PostgreSQL or Redis | None |
| [EN02 #58](https://github.com/JackZH26/SCLib_JZIS/issues/58) | P2 | C | Separate production schema migration from API startup and define reversible shadow rollout | [EN01 #42](https://github.com/JackZH26/SCLib_JZIS/issues/42) |
| [EN03 #59](https://github.com/JackZH26/SCLib_JZIS/issues/59) | P2 | C | Make scheduled refresh and audit tasks single-executor and idempotent across replicas | [EN01 #42](https://github.com/JackZH26/SCLib_JZIS/issues/42) |
| [EN04 #52](https://github.com/JackZH26/SCLib_JZIS/issues/52) | P2 | A | Test the same locked Python runtime dependencies that are shipped in release images | [EN01 #42](https://github.com/JackZH26/SCLib_JZIS/issues/42) |
| [EN05 #60](https://github.com/JackZH26/SCLib_JZIS/issues/60) | P2 | C | Measure retrieval and API performance and bound provider work after timeout | [EN01 #42](https://github.com/JackZH26/SCLib_JZIS/issues/42) |
| [EN06 #71](https://github.com/JackZH26/SCLib_JZIS/issues/71) | P2 | D | Restore a complete scientific release including artifacts, provenance and index rebuild state | [EN01 #42](https://github.com/JackZH26/SCLib_JZIS/issues/42), [ML04 #64](https://github.com/JackZH26/SCLib_JZIS/issues/64), [ML07 #68](https://github.com/JackZH26/SCLib_JZIS/issues/68) |

## Public interfaces and curation

| Issue | Priority | Phase | Deliverable | Required dependencies |
|---|---|---|---|---|
| [UX01 #72](https://github.com/JackZH26/SCLib_JZIS/issues/72) | P2 | D | Expose evidence-first materials views and honest dataset coverage across the public site | [SC02 #47](https://github.com/JackZH26/SCLib_JZIS/issues/47), [SC05 #46](https://github.com/JackZH26/SCLib_JZIS/issues/46), [SC07 #49](https://github.com/JackZH26/SCLib_JZIS/issues/49), [SC10 #53](https://github.com/JackZH26/SCLib_JZIS/issues/53), [ML03 #61](https://github.com/JackZH26/SCLib_JZIS/issues/61), [ML05 #67](https://github.com/JackZH26/SCLib_JZIS/issues/67) |
| [UX02 #73](https://github.com/JackZH26/SCLib_JZIS/issues/73) | P2 | C | Build a revision-aware curator workflow with side-by-side evidence and impact preview | [SC07 #49](https://github.com/JackZH26/SCLib_JZIS/issues/49), [SC08 #66](https://github.com/JackZH26/SCLib_JZIS/issues/66), [ML03 #61](https://github.com/JackZH26/SCLib_JZIS/issues/61), [ML07 #68](https://github.com/JackZH26/SCLib_JZIS/issues/68) |

## Coverage of hard review invariants

| Review checklist item | Invariant | Issues |
|---|---|---|
| 1 | Units, scientific notation and non-exact values | [SC01 #44](https://github.com/JackZH26/SCLib_JZIS/issues/44) |
| 2 | Unknown pressure and same-result filters | [SC04 #45](https://github.com/JackZH26/SCLib_JZIS/issues/45) |
| 3 | Result-level observed/computed and primary/cited semantics | [SC05 #46](https://github.com/JackZH26/SCLib_JZIS/issues/46) |
| 4 | Atomic property/state pairing | [SC02 #47](https://github.com/JackZH26/SCLib_JZIS/issues/47), [ML05 #67](https://github.com/JackZH26/SCLib_JZIS/issues/67) |
| 5 | No manufactured Tc and traceable public values | [SC03 #48](https://github.com/JackZH26/SCLib_JZIS/issues/48), [SC07 #49](https://github.com/JackZH26/SCLib_JZIS/issues/49) |
| 6 | Isotope/variable/formula identity | [SC09 #51](https://github.com/JackZH26/SCLib_JZIS/issues/51) |
| 7 | Timeline identity and input-order independence | [SC06 #50](https://github.com/JackZH26/SCLib_JZIS/issues/50) |
| 8 | No conflicting accepted negative labels | [ML02 #43](https://github.com/JackZH26/SCLib_JZIS/issues/43) |
| 9 | Database rejection of ambient+NULL, cross-material targets and nonfinite values | [ML02 #43](https://github.com/JackZH26/SCLib_JZIS/issues/43) |
| 10 | Result availability, source revisions and temporal leakage | [ML01 #57](https://github.com/JackZH26/SCLib_JZIS/issues/57), [ML06 #70](https://github.com/JackZH26/SCLib_JZIS/issues/70) |
| 11 | Immutable dependency closure and concurrent cycle protection | [ML04 #64](https://github.com/JackZH26/SCLib_JZIS/issues/64) |
| 12 | Split-group and preprocessing leakage | [ML06 #70](https://github.com/JackZH26/SCLib_JZIS/issues/70) |
| 13 | Scientific claim support and anti-circular Facts | [RG01 #62](https://github.com/JackZH26/SCLib_JZIS/issues/62), [RG02 #65](https://github.com/JackZH26/SCLib_JZIS/issues/65) |
| 14 | Hard chunk bounds, truncation detection and index reconciliation | [RG03 #69](https://github.com/JackZH26/SCLib_JZIS/issues/69) |
| 15 | Action prerequisites and complete resources | [DR01 #55](https://github.com/JackZH26/SCLib_JZIS/issues/55) |
| 16 | Recomputable public RPS, contribution conservation and honest reasons | [DR01 #55](https://github.com/JackZH26/SCLib_JZIS/issues/55), [DR02 #74](https://github.com/JackZH26/SCLib_JZIS/issues/74) |
| 17 | Last-good feed, unique IDs and version-pinned pagination | [DR03 #56](https://github.com/JackZH26/SCLib_JZIS/issues/56) |
| 18 | Revision/retraction propagation and historical notices | [SC08 #66](https://github.com/JackZH26/SCLib_JZIS/issues/66), [RG02 #65](https://github.com/JackZH26/SCLib_JZIS/issues/65), [ML04 #64](https://github.com/JackZH26/SCLib_JZIS/issues/64) |
| 19 | Release-only public access and recursive export permissions | [ML07 #68](https://github.com/JackZH26/SCLib_JZIS/issues/68) |
| 20 | Pre-connect test safeguards, migration/task idempotence and recovery | [EN01 #42](https://github.com/JackZH26/SCLib_JZIS/issues/42), [EN02 #58](https://github.com/JackZH26/SCLib_JZIS/issues/58), [EN03 #59](https://github.com/JackZH26/SCLib_JZIS/issues/59), [EN06 #71](https://github.com/JackZH26/SCLib_JZIS/issues/71) |

The 15 finding groups S01–S08, M01–M02, R01, D01–D03 and E01 are covered across these execution items. Report finding IDs and backlog IDs are different namespaces; use the `report_sections` field and evidence inside each specification for mapping.

## Files and maintenance

- [Twentieth implementation batch — 2026-09-08](Priority_Twentieth_Batch_Implementation_2026-09-08.md): RG03 complete-input chunk bounds, atomic Facts, explicit untruncated embedding validation, immutable current-evidence-bound completion receipts, attempt observations and bounded Similar failure. Active generations, SQL/vector reconciliation, promotion/rollback and production corpus evaluation remain unfinished.
- [Nineteenth implementation batch — 2026-09-08](Priority_Nineteenth_Batch_Implementation_2026-09-08.md): RG02 typed immutable extraction/evidence lineage, scientific Facts rendering, atomic ingestion, restriction-preserving index replacement, post-generation checks and English disclosure. Original-root/permission approval, canonical reviewed Result bindings, historical-answer revalidation and corpus migration remain unfinished gates.
- [Eighteenth implementation batch — 2026-09-08](Priority_Eighteenth_Batch_Implementation_2026-09-08.md): EN03 cross-process coordination for all five existing jobs, atomic SQL completion, real process crash recovery, monotonic projection state, scheduled audit comparison isolation and a private English administrator status page. Native verification is not production rollout or external-delivery assurance.
- [Seventeenth implementation batch — 2026-09-07](Priority_Seventeenth_Batch_Implementation_2026-09-07.md): SC08 immutable exact-source task requests, bounded attempt/retry history, atomic Timeline readiness invalidation and private receipt inspection. Rebuild, external caches, worker delivery and scientific reinstatement remain separate unfinished gates.
- [Sixteenth implementation batch — 2026-09-07](Priority_Sixteenth_Batch_Implementation_2026-09-07.md): SC08 indexed, exact-event impact manifests and operator-only snapshot inspection; includes zero-point Timeline candidates and historical references. Plans are not scheduled refreshes or persisted receipts; broader lineage and execution tracking remain open.
- [Fifteenth implementation batch — 2026-09-07](Priority_Fifteenth_Batch_Implementation_2026-09-07.md): SC08 append-only Paper/Work negative observations, exact-version processing reviews, durable current-read holds after status reset, migration/concurrency and audit-retention guards. Positive reinstatement, canonical supersession, indexed propagation and measured SLA remain open.
- [Fourteenth implementation batch — 2026-09-07](Priority_Fourteenth_Batch_Implementation_2026-09-07.md): SC08 current-source safeguards across aggregation, audit, Timeline and bounded historical-answer metadata; retains raw evidence and frozen bytes. Revisioned review/event ledgers, mixed-result admission, RPS/RAG completion and propagation SLA remain open.
- [Thirteenth implementation batch — 2026-09-07](Priority_Thirteenth_Batch_Implementation_2026-09-07.md): ML07 operator-only raw research reads, explicit role/permission governance, independent-account metadata publication and live withdrawal checks; nested raw/scientific values remain excluded. Adds bounded reads and audit-aware account deletion. Real rights review, structured-value releases and curator workflow remain open.
- [Twelfth implementation batch — 2026-09-07](Priority_Twelfth_Batch_Implementation_2026-09-07.md): ML04 bounded database-derived dependency freeze, actual-byte offline verification, immutable pins and reviewed notices; EN02 explicit migration job and read-only API schema admission. Public/ML approval, canonical promotion and real staging/production acceptance remain open.
- [Eleventh implementation batch — 2026-09-07](Priority_Eleventh_Batch_Implementation_2026-09-07.md): ML03 bounded offline verification and append-only shadow import, exact source/work/review bindings, revision memberships, full raw-record accounting, transactional rollback and historical receipts. Real canary, canonical promotion and release gates remain open; no production writes.
- [Tenth implementation batch — 2026-09-07](Priority_Tenth_Batch_Implementation_2026-09-07.md): ML01 additive source-revision/capture/occurrence registry, exact known-by claim reads, arXiv capture diagnostics and bounded temporal dependency gates. Real source review, correction/supersession and historical release gates remain open; no production backfill.
- [Ninth implementation batch — 2026-09-07](Priority_Ninth_Batch_Implementation_2026-09-07.md): EN04 release-image/test runtime comparison gate, SC11 pending-only structure evidence and public interactions, and ML08 offline pilot preparation. Real Linux CI and human scientific pilot gates remain open. Prior batches five through eight are checkpointed locally in `52930eb`.
- [Eighth implementation batch — 2026-09-07](Phase_A_Eighth_Batch_Implementation_2026-09-07.md): SC10 separates missingness, reported classifications, Inferred family priors, conflict diagnostics and bibliographic support; no automatic negative labels, dispute adjudication or replication counts.
- [Seventh implementation batch — 2026-09-07](Phase_A_Seventh_Batch_Implementation_2026-09-07.md): RG01 separate citation-index and bounded scientific-support checks, fail-closed draft delivery and inspectable evidence; synthetic regression evidence is not human-adjudicated validation.
- [Sixth implementation batch — 2026-09-06](Phase_A_Sixth_Batch_Implementation_2026-09-06.md): SC06 provenance-bearing Reported Tc Timeline, explicit chronology, display-only sampling and accessible result inspection; no complete discovery-history or world-record claim.
- [Fifth implementation batch — 2026-09-06](Phase_A_Fifth_Batch_Implementation_2026-09-06.md): SC07 shared Catalogue/Archive visibility, current source/parent holds, consistent read surfaces and cache/metadata guards; no scientific approval or production rollout.
- [Fourth implementation batch — 2026-09-06](Phase_A_Fourth_Batch_Implementation_2026-09-06.md): SC03 raw-preserving anomaly review, source-linked proposed revisions and integrated scientific read gates; no production rollout or scientific acceptance.
- [Third implementation batch — 2026-09-06](Phase_A_Third_Batch_Implementation_2026-09-06.md): SC02 atomic property evidence, conditions, EPC association and offline impact audit; local implementation, not a production rollout.
- [Second implementation batch — 2026-09-06](Phase_A_Second_Batch_Implementation_2026-09-06.md): ML02/SC04/DR01 implementation, integrated verification and explicit rollout/research limits; issues remain open for review and release gates.
- [First implementation batch — 2026-09-06](Phase_A_First_Batch_Implementation_2026-09-06.md): local changes, final verification, remaining acceptance gates and rollout boundaries; not a declaration that phase A is complete.
- [Science specifications](issues-science.json): 11 SC items.
- [ML/data specifications](issues-ml.json): 9 ML items.
- [Discovery/RAG specifications](issues-discovery-rag.json): 4 DR + 4 RG items.
- [Platform/UX/AL specifications](issues-platform-ux.json): 6 EN + 2 UX + 1 AL item.
- [Publication manifest](github-issues.json): actual issue URLs/numbers, phases, labels, dependency IDs, topological order, all 20 invariant mappings and SHA-256 hashes of the published issue bodies.

GitHub is the authoritative source for live status; these files are a versioned publication snapshot, not an automatic sync. Update the specification, issue and manifest deliberately after an approved scope change. Do not blindly rerun creation or interpret an old body hash as a current synchronization failure. No human account has been assigned automatically.

For subsequent implementation, preserve existing user changes and raw evidence, retain immutable released artifacts, and use separately approved plans for operations with production or cost impact.
