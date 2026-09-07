# Current-source lifecycle guards and observed-change ledger

Issue: [SC08 / #66](https://github.com/JackZH26/SCLib_JZIS/issues/66).
Date: 2026-09-07. Local database head: `0057_source_impact`.

This is a local implementation of current-read/recomputation safeguards and an
append-only negative source-governance ledger. It is not a completed dependency
propagation or scientific reinstatement system. SC08 remains open. The additive
migration has been rehearsed on disposable PostgreSQL only; there is no production
source update, data backfill, automatic scientific approval, source revision
promotion, push or deployment. See the [ledger contract](SOURCE_LIFECYCLE_LEDGER.md).
The next additive [impact inspector](SOURCE_IMPACT_INSPECTION.md) provides an
indexed, snapshot-bound dependency plan; it does not schedule or acknowledge refresh.

## Scientific contract

Source `retracted`, `withdrawn`, `corrected` and `disputed` statuses remove
eligibility to supply the current supported summary. They do not prove that the
material cannot superconduct, that independent experiments are false, or that
all statements in a paper are invalid. An unknown/missing source is not evidence
of retraction. Material identity, retained evidence and historical releases are
not deleted to make a current view look consistent.

The existing SC07 public policy remains conservative: a retained held source
can hold the whole material pending a result-scoped review. This batch separates
the active support pool during aggregation, but does **not** claim independent
results are now individually admitted through every public surface. That requires
the explicit event/state/result revision workflow below.

## Material aggregation

The ingestion sweep reads all current source statuses, then excludes held
sources from new extracted input. It never reintroduces held extractions that
are absent from the existing material archive. Already-retained held records
survive mixed-source recomputation; only the active pool supplies flat numeric,
categorical and bibliographic support fields. Raw anomaly and semantics views
remain separately source-aware. `total_papers` is a current support count, not
the number of retained historical records, independent replications or accepted
experiments.

If every retained record explicitly resolves to a held source, a previously
orphaned non-NIMS material receives an empty current summary and a review hold.
Its existing ID, formula identity, family, substrate/overlayer identity, parent
link, external links and material-level scientific flags are preserved. Missing
sources, malformed/empty record inventories and NIMS-only rows do not satisfy
this rule. This is not recovery of missing source history.

Existing review holds remain sticky irrespective of `admin_decision`, including
quarantine prefixes on inconsistent old rows with `needs_review=false`. A newly
detected source/anomaly hold wins over an old positive note. A source changing
back to `published` is not by itself authorization to clear an existing hold.
Raw notes are not erased by the sweep.

An actual upsert change advances `updated_at`. An identical resulting row is a
true SQL no-op (`IS DISTINCT FROM` guard), preventing repeated sweeps from
unnecessarily invalidating downstream projections. This is local convergence
for identical snapshots, **not** ordering guarantees for concurrent/out-of-order
upstream events. The sweep still operates with its existing transactions and
does not implement a dependency refresh receipt or source-event acknowledgement.
The 0056 source-write ledger now independently orders observed changes. The sweep
reads durable negative overlays in addition to raw status, including a Work hold
through an explicitly accepted current Paper/Work identity map.

## Audit and legacy-review safeguards

Nightly critical rules and the periodic formula audit no longer skip rows with
an old `admin_decision`. The current source rule handles all four held lifecycle
states, including a mixed-source material. The sole-retracted-source rule also
recognizes withdrawal, but does not classify an unresolved record as retracted.
Both safely inspect malformed/non-array inventories and preserve raw values.

The old recommendation to set the material's `disputed` flag solely because
its sources were retracted has been removed. Existing unrelated review reasons
are preserved; one material may match multiple rules while retaining one stored
queue reason. Queue filters still use the stored reason, not all current rule
matches.

Legacy overrides cannot clear live source/record/material/parent/provenance
holds, numeric anomalies, or a retained lifecycle-specific reason even after
the source status becomes active. Other legacy flag overrides remain temporary
governance operations, subject to subsequent fresh audits; they are not
revision-bound scientific approvals. The mutable legacy note field and existing
confirmation endpoint are **not** a new append-only decision history.

Critical reports now count current rule matches. A versioned count-basis marker
is stored in existing `audit_reports.suggested_fixes` metadata; deltas compare
only successful reports with the same marker. Thus old newly-flagged counts and
failed checks are not used as an incompatible baseline. Historical rows are not
rewritten. The overview sums successful counts only, and the English UI explains
overlapping matches, failed checks and queue-reason differences. These metrics
are not a propagation SLA or a count of scientifically rejected materials.

## Reported Tc Timeline

Projection cache version is now **6**. Refresh compares a stored dependency
snapshot with the current source's presence, submitted/published dates, status
and UTC timestamp. It no longer relies only on a strictly advancing
`Paper.updated_at`. A date correction with an unchanged or backdated timestamp
can invalidate an existing point and rebuild its chronology. The read path also
checks the same source snapshot; stale projection metadata causes canonical
fallback instead of a stale plotted result.

The pre-existing five-minute watermark overlap remains conservative. A recent
paper anywhere in the source table can still trigger a full rebuild, even when
this particular material's content has converged. Content convergence and point
identity are tested separately from that global scheduling signal. Narrower
dependency indexing and representative refresh performance remain future work.

Internal dependency JSON is compared without casting malformed cached values to
dates. UTC microseconds and date formatting are independent of PostgreSQL session
timezone/DateStyle. These cache snapshots are **not** ML01 source revisions or
proof of when a scientific result became publicly known.

`refresh_timeline_projection(session, force_full_rebuild=True)` is an internal
recomputation hook; the caller owns the transaction. It can recover records that
previously lacked a projectable date and therefore had no prior point. If such
a record changes without any timestamp signal, automatic existing-point checks
alone cannot discover it. A dependency index or controlled full rebuild remains
necessary. Do not run a production sweep as part of a code review or test.

## Saved Ask history

`GET /v1/history` retains the saved answer and citations, adding a separate
`current_evidence` envelope containing source status and occurrence-state counts,
not repeated per-occurrence scientific records. Its scope is
`current_paper_metadata_not_saved_excerpt`, with
`saved_answer_revalidated=false`, `scientific_acceptance=false` and no established
ML-training eligibility. The English interface shows current source warnings
beside the explicitly historical answer. A current extraction cannot validate
the historical excerpt merely because both have the same paper ID.

Current metadata is read in a request-local REPEATABLE READ, READ ONLY transaction
with a 5-second SQL statement limit and a 10-second asynchronous request budget.
Paper metadata and every adapter-loaded material ancestor are preflighted before
full-row transfer. Missing, malformed, unknown or over-budget dependencies must
not produce an eligible nested evidence envelope. Only explicit material IDs are
resolved; formula/title matching does not establish identity.

Input budgets are 50 saved source positions per entry, 1,000 unique papers,
5,000 current occurrences / 4 MiB expanded occurrence JSON, 200 occurrences per
paper, and 1,000 material/ancestor rows / 4 MiB expanded material JSON. Additional
output projection has an 8 MiB serialized-envelope budget, counting every
repeated citation, so repeated references do not multiply the unique-input
budget into an unbounded response. Omitted summaries are explicitly unknown.
These protections do not
retrofit a hard byte limit onto the existing saved answer/citation payloads, or
preempt synchronous database/JSON CPU work with a hard deadline.

History and audit responses, including errors, use `private, no-store`. History
does not overwrite saved citations, regenerate answers, or change source status.
Existing user-owned history deletion behavior is unchanged.

## Research publication and historical capsules

ML07 already checks live material/Paper/Work governance and reviewed ML04 notices
before admitting a public metadata body. New integration tests exercise source
retraction, withdrawal, correction and dispute after publication across all
three public aliases and the inventory, including conditional-cache requests.
The body becomes unavailable while a current source hold applies. Historical
capsule inspection still yields exactly the original manifest bytes/hash.

This read-time hold does **not** manufacture an authenticated reviewer, a notice
artifact or an append-only withdrawal decision. Reviewed `append_release_notice`
and publication withdrawal remain explicit existing workflows. The 0056 ledger
now keeps a durable review hold once a source has a negative observation, even
after mutable status is restored. Both supported review decisions retain that
hold. The original public payload and capsule are unchanged; positive source
reinstatement and canonical supersession are still separate unfinished gates.

Internal ML04 capsules and the legacy raw source exporter remain non-training,
non-public scientific artifacts. This batch does not promote accepted ML labels
or forbid diagnostic snapshots of held source history. RPS filesystem releases
are a separate subsystem and are not silently governed by ML07's SQL notices.

## Remaining acceptance gates and next work

1. Extend the implemented negative-only source-change/review ledger into an
   explicitly authorized canonical supersession and reinstatement workflow.
   Preserve exact source/result revisions and every prior review; a checksum
   alone is not reviewer authority. Never clear flags or revive frozen labels
   merely because an upstream status has changed back to active.
2. Build an indexed dependency inventory for material results, zero-point
   Timeline candidates, chunks/retrieval context, dataset membership and RPS
   evidence. Never infer dependency identity from formula similarity.
3. Run idempotent dependency refresh jobs with observable requested/completed
   revisions, failures, retries and measured lag. Prove concurrency and
   out-of-order convergence before declaring a propagation SLA.
4. Admit unaffected mixed-source results separately only after exact
   event/state/result review; avoid suppressing independent support merely
   because it shares a formula or material family with a held claim.
5. Bind RPS evidence to trustworthy source/canonical result IDs and current
   notices. Recheck source revisions after long-running Ask generation before
   delivery (RG02), not just before it starts. Keep historical answer text intact.
6. Rehearse real reviewed corrections/retractions in staging, including
   prospective training releases and explicit historical notices. Synthetic
   regression tests and local rebuild logs are not real scientific validation.
