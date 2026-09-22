# Batch63 — replayable private ML08 canary and documentary conclusion

Base: `c4b8fb5` on `codex/sclib-research-v2`, preserving all uncommitted batch62
changes. The previous goal turn made concrete progress by completing targeted
workbench/browser validation and seven client consistency fixes. This turn
advances the next scientific-review dependency, not a new training capability.

Fresh GitHub inspection found **38 open issues**. ML08 #54 was read in full;
the existing pilot protocol, schema, validator and tests were inspected. ML08
already has frozen-cohort, source/state, missingness, time, comparison and
disagreement rules. Those were reused, not replaced with a second scientific
acceptance policy. Its actual-event and human-review requirements remain unmet
by synthetic software tests.

## Concrete gap and implementation

The existing conclusion records a canary reference/hash but the documentary
validator deliberately never opens that artifact or its context files. There
was no executable canary constructor/replayer binding the complete pilot
accounting to actual supplied bytes. Added:

- `scripts/ml_pilot_canary.py`: private `build` and read-only `verify` commands,
  using the existing pilot schema/accounting validator and the existing bounded
  JSON codec, physical-path readers and no-clobber owner-only package writer.
- `scripts/tests/test_ml_pilot_canary.py`: 57 new synthetic offline tests,
  including actual subprocess CLI build/verify, not a mocked canary compiler.
- [Operator guide](../../ML_PILOT_CANARY.md), pilot-protocol cross-reference
  and explicit separation from [run-plan acceptance](../../ML_USE_RUNS.md).

All original 60 selected events, every review revision and effective
candidate/result associations remain in the canary. Failures cannot be dropped
to improve recovery; superseded reviews retain their effort and original
values. Unresolved arbitration keeps pending/rejected results. A fully
inaccessible cohort and reasoned `stop` conclusion are supported. No negative
example, structure, state, precision estimate or independent-work count is
invented. The canary is not an ML training dataset.

## Exact bindings and boundaries

Separate independently supplied pins cover original selection and JSONL file
bytes, canonical selection and ordered-log content, protocol bytes, final
conclusion bytes and the canary itself. Protocol bytes must match the selection's
recorded protocol hash. The canary excludes the conclusion to avoid circular
hashing; subsequent verification rebuilds the whole canary and requires the
conclusion to bind its exact hash, selection and log.

Every declared-permitted context reference/hash across all review revisions
requires a matching hash-named file in the explicit closed evidence directory.
Only those files are read, and identical hashes deduplicate byte checks rather
than independent scientific support. Changed-context revisions can retain the
same opaque reference with distinct source revision/hash bindings. Restricted
or missing context remains explicit, never fabricated or fetched.

Context bytes are hashed but never interpreted, executed or embedded in the
canary. The command follows no URL or path appearing in source/review text,
and makes no network/database call. It cannot establish current rights merely
from an `access_status` declaration. Original source authority and human
scientific inspection remain the operator/reviewer's responsibility.

Captured bytes and identities, directory inventories, parsed values and selected
source observations are checked again before output/success. Nonregular, empty,
aliased, oversized or changed inputs fail closed. A zero-leaf directory is
allowed only when the complete ledger requires no source-context files.
Output is `0600`, no-clobber and outside the evidence directory. Uncertain
publication uses the existing `output_state_unknown` behavior rather than a
false rollback claim. Stdout omits paths, names, source prose and result values.

The nested accounting report explicitly identifies the old documentary
validator as its component. Its original warning about not opening evidence
describes that validator; the enclosing command separately declares byte
hashing, not content support or permission verification. No human-identity,
independence, source-permission, scientific-pilot, publication or training
authority flag becomes true. Selected disk sources/Python observations are
not loaded-code or full execution-image attestation.

## Verification history

- Initial canary + existing pilot tests: **69 passed / 7 subtests**, 8.39s.
  Scoped Ruff identified only new-file executable/import formatting and two
  style findings; these were corrected without modifying unrelated files.
- Expanded scientific and filesystem boundaries: **82 passed / 7 subtests**,
  7.99s. Tests include exact final conclusion binding, failed cohorts,
  unresolved arbitration, repeated-result accounting, Tc inequalities,
  explicit non-transition observations, revisions with different context bytes,
  wrong pins, unsafe files, concurrent changes, no-clobber output, source
  reference nonexecution and private CLI diagnostics.
- First full script regression: **1,995 passed / 36 subtests**, 68.14s.
- Full frontend regression on preserved batch62: **44 files / 1,566 passed**,
  53.08s, followed by **38 passing source checks** and nonincremental TypeScript.
  No frontend or production API/schema source was changed by batch63.
- After adding explicit nested-accounting/context scope metadata, the combined
  canary/pilot scope again passed **82 tests / 7 subtests**, 8.02s.
- A final new adversarial test demonstrated that an empty file could otherwise
  be supplied as the asserted approved protocol: **1 failed**, 0.63s. The shared
  local-read path in the new command now requires nonempty files. This is a
  documentary existence check, not a claim to authenticate protocol content.

Final pre-commit regression after the nonempty-file guard completed:

- Scoped Ruff: passed.
- Full scripts: **1,996 passed / 36 subtests**, 68.79s.
- Full frontend: **44 files / 1,566 passed**, 54.61s; **38 source checks**
  and nonincremental TypeScript checking also passed.
- All **129 relative Markdown links** in the changed/new documents resolve;
  `git diff --check` passes.

These commands have terminal outcomes. Earlier results retain their original
source scope; the current frontend rerun covers preserved batch62 changes.

## Provenance, actual pilot work and remaining delivery

The protocol/schema and original documentary validator contracts are unchanged;
the protocol Markdown gains only a link explaining the executable canary step.
Draft templates remain empty. No real candidate selection, protocol approval,
human review, canary, signoff, membership or model result was manufactured.
The user has been asked asynchronously for an approved selection plan and
designated independent human reviewer. Software work can continue, but a
software agent must not stand in for that real review or signoff.

Adding the CLI changes the repository-wide source inventory. The retained 0074
migration report and native HTTP fixtures are historical evidence of their
selected source sets, not new captures of this CLI. They must not be resealed
or relabeled to cover it. No production API/schema was changed; database
tests/migration rehearsals and browser tests were not repeated for this
offline-only increment. Their prior batch61/batch62 scopes remain explicit.

Next dependencies are authenticated independent review of a replayed canary,
real ML08 source/event/roster and scientific acceptance work, mapping accepted
pilot evidence to the intended dataset/task scope, and guarded execution/runtime
admission. A successful canary replay alone cannot satisfy any of those gates.
Exact-revision PR/CI/runtime delivery is also still required by the issues.

The user subsequently requested a local Git checkpoint of the current batch62
and batch63 changes. No push, deployment, production backfill, source
redistribution, paid provider work, real model execution or issue closure was
performed. The full upgrade goal remains active, not narrowed to this artifact
milestone; a local commit does not establish release or scientific acceptance.

## Reproduction

```bash
api/.venv/bin/ruff check scripts/ml_pilot_canary.py scripts/tests/test_ml_pilot_canary.py
api/.venv/bin/python -m pytest scripts/tests/test_ml_pilot_canary.py scripts/tests/test_pilot_review.py -q
api/.venv/bin/python -m pytest scripts/tests -q
api/.venv/bin/python scripts/ml_pilot_canary.py --help
```

The operator guide describes required independently retained input pins, private
directories, deterministic build/replay and evidence limits. Tests use owned
temporary files and conspicuously synthetic records; passing tests do not
demonstrate the existence of 60 actual source events or completed human reviews.
