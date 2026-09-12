# ML08 — Proposed 60-event reviewed evidence pilot

Protocol revision: `ML08-pilot/0.1-proposed`

Issue: [ML08 #54](https://github.com/JackZH26/SCLib_JZIS/issues/54)

Status: **preparation only; proposed for user and scientific-reviewer approval**.

Actual candidate events selected: **0**. Human reviews completed: **0**.

This directory is a workflow preparation package, not a completed pilot, a
reviewed dataset, a source-access authorization, or permission to train a model.
No production database, paid extraction, scientific experiment or source
redistribution is authorized by these files. Sixty candidate events test the
workflow's feasibility, not statistical sufficiency for cross-family ML.

## 1. Decisions needed before selection

The PI/data steward and designated human scientific reviewers must approve:

1. A permitted source inventory and storage/access policy, including whether
   original context may be retained locally or only referenced by locator.
2. A small set of material-family and evidence-condition strata, their allocation,
   selection procedure, selection date/cutoff, and treatment of duplicates.
3. The independent second-review calibration subset and disagreement/arbitration
   process; roster roles and an independence declaration. An LLM or another
   software agent is not the independent human reviewer.
4. Field definitions, review/acceptance policy, timing procedure and who signs the
   go/narrow/stop recommendation. This document proposes no approved family
   quotas, minimum accuracy percentage, sample-size power, or automatic pass rate.

Suggested coverage dimensions for discussion are observed/computed reports,
ambiguous pressure, multiple states, difficult tables/figures, and censored or
explicit negative observations **where genuinely available**. They are not quotas
to fill with invented negatives, structures or accessible replacements. The
issue specifies 60 candidate events; the stratum allocation remains a human choice.

Record these decisions in a dated protocol revision, hash its approved bytes,
and retain the approval reference outside the editable review working copy.
The validator only checks a supplied approval reference/hash; it cannot verify
the approver, their authority, the approved document, or source permissions.

## 2. Units of accounting

| Unit | Meaning | Never substitute |
| --- | --- | --- |
| Candidate event | A preselected, locatable source event/question to review; may yield zero, one or many atomic results | Material formula, paper count or pressure-point count |
| Atomic result | One source-bound observation/assertion with its own state and criterion interpretation | A mixture of maxima selected from different records |
| Work | A reviewed bibliographic identity across publication versions, if resolved | Number of DOI/arXiv/catalogue identifiers |
| Sample/state | The explicitly interpreted sample and pressure/doping/other state associated with a result | Formula-only equality or a paper-wide phase label |
| Structure | An identified structure record/artifact or source-bound structural assertion | A generated coordinate structure inferred from a formula |
| Review | One completed human assessment/comparison revision | A second independent material or experiment |

Count each candidate event once in the fixed denominator even if it yields many
results. Different candidate events may belong to one work/material. Keep those
links rather than inventing independence. Reported distinct IDs are not proof of
independent works, independent samples or independent replication.

## 3. Preparation files and schema

- `selection.template.json`: valid **draft** selection with an empty candidate
  list, no reviewer roster and no approved protocol. It does not contain 60 fake
  IDs or sample scientific events.
- `reviews.template.jsonl`: deliberately empty. Append completed human review
  records only after selection is frozen. Schema: `$defs.review` in
  `ML08_Pilot.schema.json`.
- `conclusion.template.json`: draft conclusion with no recommendation, canary
  bundle or signoff assertion. Schema: `$defs.conclusion`.
- `ML08_Pilot.schema.json`: JSON Schema 2020-12 definitions for selection,
  reviews, atomic results and conclusion. The Python validator implements the
  schema keywords used here plus the cross-record checks below; it is not a
  general-purpose JSON Schema engine.

Work on copies in an authorized private directory. Do not commit real excerpts,
source credentials, reviewer names/emails, or private institutional records to
this repository. Reviewer IDs should be pseudonyms, with the identity/authority
mapping retained separately by the data steward. Permission references and raw
context references should be opaque, access-controlled references, not bearer
URLs, tokens or credentials.

## 4. Freeze the actual selection before review

For every one of the 60 actual events, record a stable `candidate_id`, source
reference, event locator, family, source class, declared stratum and selection
rationale. `selection_kind=actual_source_event` is a human assertion; the offline
validator cannot establish that the event really exists. The human freeze audit
must resolve each ID/reference to the intended source event.

Declare `second_review_candidate_ids` **before** reading outcomes, plus a human
roster and independence plan. Do not select only apparently easy/successful
events for second review. No minimum subset percentage is imposed here; its size,
stratification and disagreement policy require approval before selection freeze.

Set protocol approval metadata, `selected_at`, `frozen_at` and
`selection_status=frozen`. All dates require a timezone. Compute the canonical
selection hash (all fields except `selection_sha256`), insert it into that field,
then archive a read-only copy and an independently retained dated hash/approval
record. Example commands use only local files:

```bash
python3 scripts/validate_pilot_review.py /secure/pilot/selection.json \
  --print-selection-hash

python3 scripts/validate_pilot_review.py /secure/pilot/selection.json \
  /secure/pilot/reviews.jsonl --expected-selection-sha256 <separately-retained-hash> \
  --require ready
```

The tool never writes the hash, freezes a file or approves a protocol. A hash is
not a signature or trusted timestamp. Passing `--expected-selection-sha256`
from the same freely editable manifest defeats the independent-anchor purpose;
retain the anchor through an approved external record/process.

After freeze, do not remove inaccessible/irrecoverable events, change strata or
substitute easier events. Record an outcome/reason against the original ID.
If a selection error genuinely requires an amended pilot, retain the original
manifest and its 60-event accounting, document the amendment and obtain a new
approved pilot/version. Do not silently rewrite an existing cohort. Every review
must bind the original selection hash; external-anchor mismatches fail validation.

## 5. Human review record

Each JSONL row is one **completed assessment revision**, with `review_id`, event
ID, selection hash, pseudonymous human reviewer ID, role, timezone-aware date,
outcome/reason, time accounting, comparison metadata and zero or more results.
Available event outcomes are `recovered`, `inaccessible`, `irrecoverable`,
`no_relevant_result`, and `unresolved`. Failures contain no fabricated atomic
results. `recovered` means data were recovered for inspection, not that any result
was scientifically accepted.

Use `role=primary` for the initial assessment. Revisions append a new row with
incremented `revision` and `supersedes_review_id` pointing to the latest row for
the same event/role. Never overwrite the old row. `active_minutes` and field
times record **new effort for this revision**, not cumulative repeated totals.

### Minimum atomic-result context

Record the source paper ID, source revision, permitted locator, a reference/hash
to retained original context, access status and permission reference. The tool
does not open context references or verify file hashes/rights; the reviewer must
do so within their authorized environment. Locator-only retention can remain
pending when permitted original context is unavailable. Do not paste restricted
full text into a public report to satisfy a field.

Keep work/sample/state/structure IDs distinct and nullable. Record an explicit
state interpretation, Tc criterion, method and result origin. A source-state
interpretation may explicitly describe uncertainty; do not invent an association
to qualify an accepted row. Pending alternatives and evidence errors remain in
the ledger. Structure IDs do not imply coordinate artifacts or DFT readiness.

For the eleven priority fields, assign a status and a specific missingness reason
when not `reported`:

`source_revision`, `source_locator`, `raw_context`, `work_identity`,
`sample_state`, `structure_identity`, `tc_value`, `tc_criterion`, `pressure`,
`origin`, `method`.

The available statuses are `reported`, `not_reported`, `not_accessible`,
`not_extracted`, `ambiguous`, `conflicted`, `not_applicable`. Missing extraction
keys do not establish that the source says nothing: use `not_extracted` or
`ambiguous` with a reason until source inspection resolves it. `not_applicable`
requires a reason and is not derived merely from material-family membership.

### Quantity and negative-result rules

- Tc and pressure quantities preserve exact, inequality, interval, approximate
  and uncertainty representations. Normalized units are K/GPa; original units,
  expressions and conversion context remain in the separately retained raw
  evidence. Never replace a bound with a point value.
- `unknown`/`not_reported`/`ambiguous`/`conflicted` pressure does not contain a
  numeric normalized quantity. No unknown pressure becomes 0 GPa. An
  `explicit_ambient` declaration still needs source evidence; numerical pressure
  alone does not prove ambient conditions.
- An explicit non-transition observation uses `observation=not_detected`,
  `tc=null`, `fields.tc_value=not_applicable`, a measured minimum temperature,
  criterion, method, sample/state and source evidence. It is not a Tc=0 label.
  Missing Tc never creates a negative example.
- `decision=accepted` records a human assertion, not automatic validator approval.
  The proposed documentary checks require permitted source/revision/context,
  state interpretation, method, criterion and origin; unsupported/error-bearing
  rows remain pending or rejected. An accepted positive needs Tc; an accepted
  non-transition result must be Observed and have a tested-temperature window.
  Unresolved work/structure identities remain explicit and prevent later uses
  that need those identities, even when the limited source assertion is retained.

Source, normalization, state-association and extraction errors have separate
typed codes. Do not hide their rates inside a coverage percentage. Resolving an
error requires a new review revision; the old error-bearing review remains in
the ledger.

## 6. Independent comparison and disagreements

The second human first assesses the designated event without seeing the primary
result/decision. Afterwards, record a `secondary` comparison row containing their
own assessment and `compares_review_ids=[current_primary_id]`.
`independent_assessment=true` is a recorded declaration, not technical proof of
blinding or human independence. The validator rejects the same pseudonymous
person serving as both primary and secondary on that event; it cannot detect
two IDs belonging to one person.

Second review is required for the frozen subset **and** events explicitly flagged
for it, unresolved events, pending/conflicted results or recorded evidence errors.
Additional difficult cases do not replace the calibration subset. Log explicit
disagreement codes. A declared agreement with differing structured results/outcomes
does not complete the gate; resolve the difference or record a disagreement.
Different decision prose alone is permitted.

For disagreements, append an `arbitration` row comparing the current primary and
secondary IDs. Preserve either a reasoned resolution or `comparison=unresolved`
with disagreement codes and pending/rejected results. Unresolved disputes may
remain in a completed feasibility report; they may not become accepted labels.
Arbitration authority and any third-person requirement are human protocol choices,
not authentication supplied by this tool. If a primary review changes, the old
comparison/arbitration is stale until explicitly updated. The final signoff gate
reports missing/stale comparisons rather than counting them as current approval.

## 7. Time, recoverability and denominators

Measure active curation minutes, excluding downloads, unattended model runs,
waiting and breaks. Use `null` for unrecorded time: missing time is not zero.
Optional per-field minutes are disjoint measured intervals; shared work may remain
unallocated. Their sum cannot exceed a measured total for that review revision.
Do not reconstruct apparently precise times from memory just to fill the form.

The accounting report separates:

- Selected candidate denominator (60 after freeze), primary-reviewed candidates,
  failures and unreviewed candidates. Failed/inaccessible events stay in the 60.
- Candidate-level recovery: events with **any** reported result for a field divided
  by all selected candidates; this is not complete field recovery or source recall.
- Atomic-result missingness: field statuses divided by the effective reviewed
  distinct result-ID count, which can differ greatly from 60. Identical IDs/content
  appearing under multiple events count once here, while their event associations
  remain separately counted; conflicting content for one ID fails validation.
  Inaccessible events have
  no invented atomic results and remain visible in event outcomes/denominators.
- Reported distinct work/sample/state/structure IDs, never inferred independence.
- Recorded active time and timing coverage over **all review revisions**, by
  family/source class/selection stratum and field. Group recovery numerators use
  each group's selected-candidate denominator. Superseded revisions still consumed human effort.
- Disagreement/arbitration outcomes and source/normalization/state/extraction
  errors independently of recovery and missingness. The tool does not estimate
  extraction accuracy without a separately adjudicated reference.

Effective result statistics use the current primary assessment, or current
arbitration bound to the latest primary/secondary pair. Secondary results are not
added again as additional material observations. Report unresolved cases and
decision revisions; never silently vote or average conflicting Tc values.

## 8. Conclusion and canary signoff

After all original candidates have primary outcomes and the required comparisons
and disagreement dispositions are recorded, prepare an access-controlled canary
bundle containing accepted results **and** the accounting/failure/uncertainty
records needed to interpret them. Do not publish licensed raw context. Keep the
complete review ledger available to authorized auditors.

The conclusion binds the frozen selection and canonical ordered review-log hashes,
references/hashes the canary bundle, names the responsible human pseudonym/date,
and proposes `go`, `narrow` or `stop` with a rationale. For every priority field,
propose `keep`, `narrow` or `defer`, stating limitations. The validator only checks
that these declarations/references are present and consistent; it does not inspect
the canary or decide whether the scientific recommendation is justified.

```bash
python3 scripts/validate_pilot_review.py /secure/pilot/selection.json \
  /secure/pilot/reviews.jsonl --expected-selection-sha256 <retained-hash> \
  --conclusion /secure/pilot/conclusion.json --require final
```

Exit codes: `0` structurally valid (and requested documentary gate satisfied),
`1` malformed/inconsistent input, `2` valid preparation but requested gate incomplete.
The plain draft template intentionally exits 0 with `preparation_draft`, zero
selected/reviewed events and readiness false. `--require ready`/`--require final`
must not pass on that template.

The highest tool state is **`final_package_ready_for_human_signoff`**, never
“scientifically approved,” “pilot accepted,” “published,” or “ML ready.” All
reports carry `scientific_acceptance=false`. User/reviewer acceptance, independent
identity and permission checks, source/artifact inspection, and any release/ML
admission gates remain separate. Do not close #54 using preparation files or
synthetic unit-test fixtures as evidence that actual human reviews occurred.

## 9. Software scope and verification limits

The CLI uses Python standard library only and makes no network/database calls.
It reads only supplied selection/review/conclusion files and the bundled schema,
and prints aggregate accounting/errors to stdout. It writes no input, approval,
scientific value or public artifact. Unknown fields, duplicate JSON keys,
nonfinite JSON numbers, oversized input and malformed timestamps fail closed.
File/record bounds are operational safeguards, not scientific sampling thresholds.

Code tests use unmistakably synthetic IDs within test functions only. They prove
software invariants, not actual event existence, source rights, independence,
review completion, scientific precision or sufficient sample size. A full corpus
re-extraction, production loading, model training and paid providers are out of scope.
Even aggregate reports can identify small groups or disclose restricted outcomes;
the data steward must review sharing permissions and disclosure risk before release.

## 10. Executable private canary construction

The separate [private canary command](../ML_PILOT_CANARY.md) now constructs
and replays the artifact referenced in a conclusion. It reuses this unchanged
schema/accounting validator, binds raw/logical input hashes and separately
hashes explicitly supplied local context files without following references.
It does not change this validator's documentary gate, approve this proposed
protocol or authenticate reviewers.

Build after the frozen cohort's required reviews/disagreement dispositions are
complete, then prepare the human conclusion against the canary hash and verify
both together. The canary excludes the conclusion to avoid circular hashing
and retains all outcomes and review revisions. No invented events are added
to the empty templates, and the ML08 pilot is not marked complete.
