# Twenty-seventh implementation batch — frozen task-specific ML datasets

Date: 2026-09-08. Branch: `codex/sclib-research-v2`.
Baseline: `47c3c24` (twenty-sixth batch).
Priority: [ML06 / #70](https://github.com/JackZH26/SCLib_JZIS/issues/70).
Specification: [ML task datasets](../../ML_TASK_DATASETS.md).

## Outcome

Implemented an actual SQL → 0054 freeze → exact source/label reconstruction →
task compiler → private offline artifact → full independent recomputation path.
The initial scientific scope is deliberately explicit: primary experimental
positive point Tc with one criterion, source-bound formula features and optional
reported pressure/field, an aware cutoff and declared-review eligibility.
This is not a universal all-family training release or a new unused schema.

The compiler and CLI preserve false scientific, reviewer-authentication, ML
training and public-release authority. No real sources were newly disclosed,
no real review was invented, no model trained, no production database changed,
and no push, PR, deployment or remote issue closure was performed. The overall
goal and #70 remain active; this batch completes a bounded implementation slice,
not their complete research acceptance.

## Delivered

1. A strict versioned task contract covering estimand, criterion, positive label
   window, limited measurement-window semantics, pressure/field scope, origin,
   censoring, review declarations, feature budget, cutoff, split and fitting.
2. A pure bulk frozen provenance resolver which rechecks existing 0052 review
   and source bytes and preserves the distinct 0054/0052 hash conventions.
   Exact source-version dates do not inherit an earlier Work's date. Property
   availability remains unknown without an actual exact occurrence contract.
3. Fixed 121 formula descriptors from the existing audited parser, packaged for
   the API without ingestion/DB dependencies. Original claim-bound formula
   strings—not contemporary catalog descriptors—supply historical features.
4. Full frozen identity grouping, including noncandidate and excluded bridges,
   exact composition, Work/capture, sample/state, parent/structure ancestry and
   declared trajectory/near-duplicate merges. Noncausal links remain noncausal.
5. Hash-ranked group interpolation, chemical-system extrapolation and explicit
   family holdout policies; conflict/unknown/insufficient-group no-go behavior.
6. Exact multi-hop target dependency checks despite renamed features. External
   feature bindings remain explicitly unsupported rather than silently entering
   a claimed physics-informed model. Missing/negative/censored data cannot turn
   into zero-Tc/class negatives. Stored labels/splits/groups are ignored.
7. Train-only median/scaling parameters, all-missing train column exclusions,
   constant-column behavior, finite-value validation and original missingness.
8. Complete private task/feature/label/partition/exclusion/coverage/dependency
   report with source hashes and deterministic assignment hashes. Independent
   pinning plus full recomputation rejects resealed output tampering.
9. An offline CLI with bounded canonical reads, no-follow/alias checks, repeated
   input checks, private atomic no-overwrite output, redacted errors and no output
   file when a task has a technical no-go.

## Independent review findings resolved

- Generic enum containers caused TypeError instead of a controlled task failure.
- A valid legacy claim without an event could be dereferenced after detecting
  its absence; it now becomes an explicit excluded candidate.
- Event-only, excluded bridge nodes needed grouping-only links even when they
  could not provide exact result provenance or causal dependencies.
- A normalized formula could hide a conflicting/variable original raw formula.
  Every simultaneously supplied original/extracted formula is now checked.
- JSON booleans could compare equal to numeric state magnetic fields; explicit
  finite non-boolean validation now refuses that false agreement.
- A tiny dataset with valid but extreme split percentages could leave no train
  group; it now gives a specific no-go instead of emitting a broken split.
- `independent_components` was an overstatement: output now labels graph units
  `leakage_components` and explicitly separates unique Work/state/sample counts
  from unproven experimental independence.
- Non-object JSON in a malformed frozen record now fails safely; live state
  JSON object constraints are tested without disabling them. A contradictory
  claim/sample label is a veto, never a string-equality identity heuristic.
- CLI argument parsing needed the same redacted errors as compilation. New
  output also cannot be written into the closed input-capsule directory.

## Verification

Final code and test inventories were frozen before the complete API run.
Earlier focused runs are not double counted. All positive source/review/CLI
fixtures are explicitly synthetic and use the guarded disposable native
PostgreSQL/Redis runner where SQL is required.

| Final check | Result |
| --- | --- |
| Full API, owned native PostgreSQL/Redis | 4,163 passed; 20 existing warnings; 371.29 s |
| Full ingestion, inert database/Redis endpoints | 1,275 passed; 34 existing warnings; 7.12 s |
| Full scripts | 582 passed plus 36 subtests; 9.15 s |
| Full frontend components | 507 passed across 27 files; 13.21 s |
| Frontend source checks | 35 passed |
| TypeScript | `tsc --noEmit` passed |
| API/ingestion dependency locks | Both `uv lock --check` passed |
| Changed Python modules/tests | Ruff `I,F` passed |
| Patch whitespace | Staged and unstaged `git diff --check` passed |

Total: **6,562 ordinary tests plus 36 subtests**, with no skipped cases in these
full suites. This batch adds **427 ordinary tests**: 274 API and 153 script
cases. The API additions comprise 152 composition/preprocessing tests, 47
independent compiler adversaries, 39 frozen provenance tests and 36 actual SQL /
freeze / compiler / subprocess CLI cases. Source parity covers both complete
vendored parser modules, not selected outputs only.

Actual SQL grouping tests cover both sample-trajectory and structural-near-
duplicate declarations with real captured endpoint hashes, reachable verified
review bytes, positive merges and corrupted/stale binding refusal. The complete
candidate closure also contains an unselected sibling Tc that is not admitted
as an extra ML example. Recomputed outer output hashes cannot legitimise changed
labels, splits or features.

No schema/DDL, dependency lock, frontend implementation or public route changed.
The unchanged migration head remains 0062; its independent migration rehearsal
was not rerun in this batch (the complete API suite still exercises existing
schema-lifecycle tests). Native local regressions are not Linux image/PR CI,
production canary, real-source approval or empirical ML performance evidence.
The test runner removed only its own disposable services and temporary data.

## Remaining acceptance and next priority

The actual issue was reread before this implementation. #70 remains OPEN for
unsupported typed physical/structure tasks, exact feature-source availability,
complete reviewed trajectory/near-duplicate coverage, fair nested subset and
adapter protocols, actual task/scientific/rights approval, and authorized release
integration. Those technical dependencies are not falsely called external-only
blockers. Missing real human acceptance is not manufactured by synthetic tests.

Next technical slice is ML07 admission for the existing RPS delivery consumers:
bind immutable release/artifact IDs to actual source/capsule identities and
purpose-specific disclosure decisions, and recheck current source/release/role
holds consistently on catalog, page, detail and download. The frozen 0055
metadata-only scope must not silently expand. Keep both existing configuration
pins as additional rollout controls. This does not publish the private ML06
report or approve its use for training; those need separate task/rights gates.
Then extend exact physics provenance and approved ML09 evaluation. Do not train
a model on an integrity-only capsule or close an issue merely because its
engineering tests pass.
