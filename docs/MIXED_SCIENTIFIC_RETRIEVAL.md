# Mixed scientific retrieval: records and original candidates

Version: `scientific-mixed-evidence/1.1.0`. Updated: 2026-09-21.
Issue: [RG04 / #75](https://github.com/JackZH26/SCLib_JZIS/issues/75).
This is a qualified retrieval workflow, not established numerical explanation
or completion of scientific acceptance.

## Actual request behavior

Ask now sends a resolved mixed question through both the exact-parent numerical
lookup and the existing generation-pinned hybrid/original-passage retrieval.
The response displays source-linked extraction rows separately from individually
cited original explanation candidates. It does not ask Gemini to bridge a
missing relationship or manufacture a numerical/causal answer.

Examples include `What is Tc of MgB2 at ambient pressure and why?`, its supported
Chinese equivalent, and `Explain MgB2 pairing at 150 GPa`. Unresolved sample,
phase, isotope, criterion or logical clauses still require clarification; the
new coordinator does not silently remove them to make retrieval succeed.

The grammar's primary `comparison` intent remains unchanged. Comparisons with
requested properties, quantity constraints or evidence constraints also enter
the dual workflow. This deliberately adds original candidates to a purely
numerical comparison as well as a comparison asking for explanation; it is not
a claim that every user asked "why" or that the reported experiments are
directly comparable. A trailing explanation request must not erase the named
Tc/pressure fields from a comparison. A pure mechanism comparison with no typed
numerical/evidence request retains its original-passage explanation route.

Non-comparison structured-only numerical Ask and structured Search keep the provider-free lookup
wrapper. Ordinary topic retrieval and unsupported-clause clarification remain
separate paths. The grammar is still bounded, not universal language parsing.

## Evidence and scientific boundary

Each numerical row comes from its complete immutable derived-Fact extraction
parent. Every condition applies to that same record; raw uncertainties,
inequalities, pressure state, origin, role, outcome and reported sample context
are retained through the existing selector. A non-detection down to a minimum
measured temperature is not `Tc = 0`, `Tc = Tmin` or a universal negative label.
Missing pressure is not ambient pressure.

Original chunks may carry an entire paper's extraction list. That attachment,
equal formulas, matching sample strings, shared Paper/Work or an equal catalogue
snapshot do not identify a common experiment. Schema 0078 adds an append-only,
reviewer-owned link from one immutable 0060 extraction parent, through closed
hash-only claim and sample identities, to one exact immutable original-passage
revision. It binds the parent, evidence record, content, locator and source
snapshot hashes. The existing source-occurrence witness resolver checks a
different part of the relationship and cannot create this link by itself.
The sample identity has scope `exact_retained_result_record`: it pins the
reported context of this extraction, not a canonical real-world specimen or
an independently adjudicated cross-paper sample identity.

The route consumes the current result-to-passage head for **every actual selected
pair**. A pair is `established` only when its latest immutable review action is
`establish`, the exact evidence remains current and eligible, and the reviewer's
specific grant and account remain active. Missing, withdrawn or stale links are
`not_established`, with reason `reviewed_result_passage_bridge_missing`.
`same_snapshot` reports only exact
Paper/catalogue-snapshot proximity; `not_same_snapshot` does not disprove a
shared experiment. Neither is a scientific score or a positive/negative ML
label. No independence count, calibrated probability or scientific acceptance
is produced. A positive relation is an explicit review record, not an inferred
boolean, same-paper heuristic, causal result or scientific acceptance.

## Reviewer workflow

The private authenticated endpoints under
`/v1/ml/scientific-review/result-passage-links` provide exact context, preview,
commit and actor-scoped receipt lookup. Curators may inspect context; only a
current explicit reviewer grant may preview or commit. Context contains hashes
and closed identities, not passage text.

Preview executes the real SERIALIZABLE insertion and database-trigger path in a
savepoint, then rolls it back. Commit requires the exact preview digest and
rechecks the actor, grant, evidence revisions, source lifecycle, current chunk
pointers and predecessor head. Establish and withdraw actions alternate through
an exact predecessor chain. Rows cannot be updated, deleted or truncated, and a
nonempty ledger blocks destructive downgrade. Request keys are actor-scoped and
replay idempotently only when every exact binding agrees.

## Preparation, packing and one final check

1. Pin the immutable generation and prepare a bounded exact-parent lookup in
   the caller's read transaction. Preparation never commits, rolls back or
   performs a separate final check. Failures propagate for caller cleanup.
2. Consume the preparation handle once. Its result DTOs, full raw records and
   retained snapshots are independent copies backed by immutable private JSON;
   all parents have corresponding evidence/generation/Work-mapping selection
   pins. A consumed handle cannot be replayed as a fresh approval.
3. Close that read transaction before semantic-provider work. Retrieve and
   hydrate original candidates from the same generation, reusing hybrid fusion,
   formula-aware candidates, complementary source expansion, Work/source caps,
   whole-chunk deduplication and canonical complete-context UTF-8 accounting.
4. Before any subsequent await, freeze each complete original presentation
   (attribution, snippet, descriptor and packing metadata) with its private pin.
   Later consumers obtain fresh DTO copies from that sealed snapshot. A changed
   presentation cannot reuse unchanged old pins; the seal is local consistency,
   not externally authenticated provenance.
5. Check the combined numerical and original pins and resolve the complete
   selected result×original review-head inventory in **one fresh read-only
   repeatable-read snapshot**. Source/material/permission/Work, activation,
   evidence pointers or reviewer authority changes cannot leave a positive link
   attached to an older checked input. Any resolver failure withdraws both
   inventories. Empty selections still check the active generation. Successful
   checking describes one read point, not future stability.

The old numerical wrapper now composes preparation, rollback, fresh selected
checks and the active-pin check. Current Work-mapping changes also invalidate
numerical rows' prepared pins; a Work assignment does not confer scientific
authority. The frozen 0060–0062 evidence/index contracts are unchanged.

### Resource semantics

`max_sources` is a **combined selected-input budget** for this workflow, at most
20 numerical parents plus original passages in total, not 20 of each. The
numerical limit is `max(1, floor(max_sources / 2))`; unused numerical capacity
is available to originals. With `max_sources=1`, a matching numerical row has
priority and the response explicitly reports that no original context was
selected. Numerical `has_more` remains honest about undisplayed eligible rows.

The association matrix has at most 100 pairs under this shared bound. Existing
candidate/hydration, record and material-input limits still apply. Detached
numerical preparation is additionally limited to 16 MiB and carries no vector
bytes. This remains the bounded 1,000-member generation pilot, not a million-
chunk benchmark or permission to run a production backfill.

The packer measures an exact canonical complete original-context request
representation under the existing UTF-8 budget. It does not truncate sources,
substitute character counts for model tokens or claim that this representation
was sent to a provider. Original cards display bounded 280-character previews;
the evidence content hash binds the retained full chunk, not that shortened
display. An empty retrieval does not invent a measured zero-byte
request. No Gemini CountTokens or generation call occurs in this mixed workflow;
`input_budget.status=not_requested`, `tokens_used=0`, `assessment_scope=none` and
`answer_mode=abstention` explicitly mean no generated scientific synthesis.
Semantic retrieval may still use the configured embedding/vector provider, so
zero generation tokens is **not** zero total provider work or a billing claim.

## Public wire and UI

`AskResponse.scientific_mixed` is a closed object, defaulting to `not_requested`
for existing routes. It contains version, execution status, result/source counts,
shared input limit, complete association dispositions, bounded reasons,
`scientific_acceptance=false` and `independent_support_count=null`.

Each association binds:

- The exact numerical `parent_result_revision_id` and its declared retained
  catalogue-snapshot hash.
- The separately numbered original `source_index`, generation vector ID,
  evidence revision, evidence record hash and full-content hash.
- Catalogue proximity and an explicit reviewed-current or missing disposition.
- For an established relation, the bridge revision and record hashes, canonical
  claim/sample identity hashes and exact source-locator hash. All five values are
  explicitly null for an unresolved 1.1 relation. Historical 1.0 associations
  retain their original field set when read and serialized; no new null bridge
  fields are inserted into the old wire contract.

Every returned result/original pair appears exactly once; no unknown or repeated
parent, source or pair is accepted. Source vector IDs must match packing metadata
and the current response generation namespace; evidence fields must match the
original descriptor. Result/activation/manifest bindings retain existing checks.
Source indices are not numerical-row indices. A derived Fact cannot be relabeled
an original candidate, nor can either inventory masquerade as the other.

`completed` means the bounded dual retrieval and final check completed, not that
an explanation was established. Zero matching rows or zero selected originals
are visible, qualified outcomes. `unavailable` withdraws numerical rows, original
citations and association metadata together; no eligible subset of a previous
combined answer is silently retained. No static answer discloses exception text.

The English-default interface separates extraction records from **Original
explanation candidates** and states **Numerical explanation not established**.
It labels current reviewed relations separately and explains that they confer no
causal explanation, independent support or scientific acceptance.
It validates the full mixed envelope before showing rows, snippets or association
details. A malformed present envelope does not fall back to displaying the old
answer prose; missing/default `not_requested` retains legacy route behavior.
Existing query equality, request-generation and cancellation protections remain.
Actual source wording and user queries retain their original language.

New authenticated mixed replies now retain their actual final extraction rows,
original candidates, association dispositions and exact generation references in
[private saved-answer receipts](ANSWER_HISTORY_RECEIPTS.md). Old placeholder-only
histories stay unchanged and explicitly unpinned. A withdrawn mixed reply saves
only its final abstention, never the removed identifiers or drafts. Historical
integrity is not a positive association review, currentness check, complete
provider-input archive or deterministically regenerated scientific answer.

## Verification and remaining acceptance

Use only guarded disposable SQL/Redis for API tests. The new mixed tests use
real synthetic 0060 evidence, 0061 receipts and 0062 generation publication,
including original passages deliberately carrying a whole paper's material
list. They check independent reported conditions, negative-result detection
limits, unknown pressure, English/Chinese requests, numerical comparisons,
exact pairing, private presentation changes, shared budgets, no model-generation
calls and joint withdrawal after source/Work/activation changes. Provider
transport is substituted; no real source acquisition or paid evaluation occurs.

The portable [scientific evaluation protocol](SCIENTIFIC_EVALUATION_PROTOCOL.md)
remains separate from genuine expert judgment. Synthetic tests establish and
withdraw a bridge only to verify the software path; no real source received a
review decision. Remaining gates include authorized review of real exact pairs,
authenticated original roots and rights, actual stratified gold acquisition,
blinded adjudication, preregistered held-out comparison, operational
measurements, remote release CI and authorized canary acceptance. This qualified
dual retrieval is not a claim that those gates passed and does not close #75.
