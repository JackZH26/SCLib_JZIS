# Nineteenth implementation batch — typed RAG evidence and scientific Facts

Date: 2026-09-08. Local branch: `codex/sclib-research-v2`.
Baseline: `da01f0d` (eighteenth batch). Priority:
[RG02 / #65](https://github.com/JackZH26/SCLib_JZIS/issues/65), with existing
SC04/SC05 semantics, source lifecycle and ML provenance safeguards.
Contract: [RAG evidence lineage](../../RAG_EVIDENCE_LINEAGE.md).

## Outcome

Future ingestion now produces typed original/abstract/derived provenance and
persists real extraction/evidence revisions in the same SQL transaction as
indexed chunks. Facts preserve scientific qualifications and negative
outcomes. Search, Ask prompts, source cards and claim inspection receive the
same closed descriptor. Ask rechecks its selected inputs after generation and
withdraws the draft when evidence changes or cannot be checked.

This is a local implementation increment, not closure of RG02 or the SCLib
upgrade. No production rows, corpus-wide rerender, vector rebuild, external
publication or paid calculation is performed. Website copy remains English.

## Implemented changes

1. **Scientific rendering.** `sclib-fact-renderer/2.0.0` separates Observed,
   Computed, Inferred, AI-Proposed and Unknown; primary/cited roles; positive
   and not-detected outcomes; exact/approximate/uncertain/interval/bound values.
   Unknown pressure stays unknown; bulk is not ambient. Tc cannot supply a
   missing minimum test temperature. Raw/typed conflicts and malformed
   outcome/origin fields remain vetoes rather than lost qualifiers.
2. **Actual producers and normalization.** `sclib-material-ner/2.1.0` preserves
   strict result-origin, source-role and detection markers, minimum-temperature
   and magnetic-field proposals. Raw extraction remains unchanged. The
   normalizer supplies its actual version; model output cannot spoof it.
   Producer kind is independent of section names. Facts use the actual parent.
3. **Additive immutable lineage.** `0060_rag_evidence` adds three tables without
   changing frozen 0052–0059 specs or ML04 v1 Chunk fields. Historical revisions
   do not FK to replaceable chunks. Current pointers require exact bindings.
   Both actual ingestion writers append lineage atomically; a failed binding
   rolls back the paper/chunk write. Internal registration defaults to dry-run,
   never commits caller work, and exact replay preserves the full DB state.
4. **Restriction-preserving replacement.** Indexed immutable chunk keys retain
   identity after pointer invalidation. Restriction persists through update,
   deletion/reinsert and automatic unresolved rebind. Missing or oversized rows
   remain stale/unavailable, not visible legacy text. No restriction-clearance
   authority is granted by this version.
5. **Retrieval and delivery.** Strict descriptors reject malformed, unknown or
   authority-bearing fields. Restricted/stale/hash-mismatched sources supply
   neither text nor extracted material metadata to prompts/fallbacks. The answer
   seal includes the descriptor. Initial lineage work and fresh post-generation
   checks have 10-second application deadlines. Post-generation checks compare
   selected text, material, Paper/Work and lineage state without holding database
   locks across the model call. Changed drafts and old citations are withdrawn.
6. **English disclosure.** Search/Ask/claim inspection display evidence kind,
   unresolved root, versions and historical/current scope. The UI refuses
   forged positive badges and unattributable/held excerpts. Saved answers remain
   historical snapshots, not newly validated scientific assessments.

## Acceptance status against RG02

| Criterion | Local evidence and remaining gate |
| --- | --- |
| Typed kind and parent | Real machine-extraction revision and producer versions; root explicitly unresolved. Canonical reviewed Result/state revision binding remains |
| Permitted original locator | Closed locators and optional same-Paper 0052 capture binding; no invented root. Real source-version/locator review and purpose-specific permission admission remain |
| No self-confirmation/amplification | v1 admits no positive independent support, including shared-parent/self-citation fixtures. Reviewed positive-root resolution/deduplication remains |
| Truth-preserving rendering | Future Facts preserve origin, role, polarity, quantities and available conditions. Historical vector corpus has not been rebuilt |
| Revision/correction invalidation | Current source/renderer/content/parent-pointer changes invalidate delivery while preserving revisions. Full canonical revision closure and historical-answer lineage overlays remain |
| Prompt/citation/UI consistency | Same descriptor end to end; citations/current binding cannot become acceptance. Legacy content is still unreviewed |
| Regression matrix | Real DB and synthetic software fixtures cover the named boundaries; no human scientific accuracy or production-wide incident-rate claim |

## Defects resolved during review

- Missing pointers initially lost historical restrictions. Bounded historical
  lookup now preserves stale/restricted state through replacement.
- Exact service replay initially left research-integrity epoch increments.
  Genuine no-ops now roll back their own savepoint; migration checks compare
  complete DB state rather than excluding the epoch.
- Falsy malformed descriptors initially bypassed validation as if absent.
  Only the exact legacy empty dictionary retains internal compatibility.
- Withholding prompt text initially left extracted material metadata visible.
  Both are now suppressed. Derived section variants share the same conservative
  label/support helper; unresolvable UI excerpts are also withheld.
- Real Core-writer tests exposed existing create-all/server-default drift.
  Insert-only defaults are now explicit, without changing conflict-update
  fields or clearing existing retraction, quality flags or citation counts.
- Initial Ask provenance lookup lacked the post-generation deadline. Both
  call sites now use the bounded resolver; an initial failure skips generation,
  reports a sanitized reason and stores no old excerpt/source in history.

## Verification

The final complete API rerun passed after all review fixes. The earlier run
passed 2,329 tests; the final initial-lookup deadline fix added three HTTP
failure-path tests. Focused reruns are not counted again in the total below.

| Check | Result |
| --- | --- |
| Full final API | 2,332 passed |
| Full ingestion | 1,116 passed |
| Full scripts | 270 passed; 36 additional subtests |
| Frontend source / unit | 35 / 288 passed |
| Distinct ordinary tests | 4,041 passed, excluding the 36 script subtests |
| TypeScript | `tsc --noEmit` passed |
| Scoped Ruff I/F; diff | Passed |
| Real 0060 migration rehearsal | Passed; empty round trip, actual service, no-op full-state proof and all independent nonempty guards |

The migration harness checks all independent populated-history guards from
0052 through 0059 before inserting 0060 history. Empty 0060 downgrade/re-upgrade
preserves earlier rows. Actual dry-run/replay, pointer invalidation, old-binding
refusal, replacement revision and nonempty downgrade protection execute on
migrated disposable PostgreSQL. No test inherits application `.env` or a
production DSN. Existing FastAPI/Alembic and SQL-compilation-double warnings
are not new scientific or production validation evidence.

API retains 20 existing FastAPI/Alembic warnings; ingestion retains 34 existing
SQL-compilation-double `DISTINCT ON` warnings. The 38 new delivery-adversary,
38 ledger, 29 currentness, 8 real ingestion-writer and 9 Search-lineage cases
are included in the API total, not added again. Native verification is not
current-SHA Linux/release-image CI or a production rollout.

## Compatibility and unfinished gates

- A traceable extraction is not a reviewed Result. The text-free projection
  retains selected normalized semantics and full-input hash, not a complete
  replayable formula/sample/state record. SQL shape checks do not establish
  physical validity or complete dimensional/cross-field consistency.
- All v1 roots remain unresolved; all scientific-authority flags are false.
  Newly served live sources cannot establish positive scientific support
  through v1. Extractive fallback/abstention is intentional conservative
  delivery, not evidence that the source science is false.
- Existing-policy unresolved text gains no new reproduction/model/ML rights.
  Purpose-specific review remains; 0055 metadata publication is not text-use
  authorization. Real root/state/permission reviewer workflows remain open.
- Source checks describe one snapshot, not perpetual currentness, historical
  availability or retroactive answer validation. Saved evidence-lineage
  overlays and durable generation receipts require separate work.
- ML04 v1 capsules remain unchanged. New closure adapters, RG03 index
  reconciliation, current-SHA Linux/release-image CI, scientific pilot,
  performance canary and production rollout remain required.

Next local work should complete reviewed-root/permission and canonical revision
workflows in dependency order, alongside RG03 index reconciliation and
SC08/UX02 curator integration. External publication and production/cost
operations require their own authority. GitHub issue state is unchanged.
