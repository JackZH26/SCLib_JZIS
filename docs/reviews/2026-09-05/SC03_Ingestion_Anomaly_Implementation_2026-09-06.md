# SC03 — Raw-preserving ingestion and offline numeric-rule impact audit

Date: 2026-09-06. Scope: local implementation only; no production query, migration, deployment, backfill, source-history restoration, or scientific approval was performed by this workstream.

## Implemented behavior

- The paper aggregation driver no longer drops current source occurrences solely because `tc_kelvin < 0.01` or `tc_kelvin > 300`. Existing formula, citation, credibility-tier, retraction/source and extraction-quality policies remain in place.
- Aggregation never deletes a whole occurrence because its Tc crosses a review reference. It keeps the complete current input in `materials.records`; a flagged Tc does not erase unrelated Hc2, lattice, or other useful evidence from the same occurrence.
- The shared `anomaly-review/1.0.0` policy supplies property-specific review eligibility. Global/family Tc findings affect Tc views; explicitly view-scoped override references affect their named view. These are operational review references, not physical upper bounds.
- A legacy cap is a review reference, not a replacement measurement. The 60 K source plus 45 K cap counterexample no longer produces an unsupported 45 K result. If a separately eligible 39 K source exists, 39 K may be selected with its own provenance; otherwise the affected view is null.
- Exact numeric legacy overrides no longer mutate data. They produce `legacy_numeric_override_requires_revision`; free-text citations are not treated as authorization for a correction. Source-backed append-only correction proposals are a separate API workstream.
- Current material context records rule version, selected family, structured override references, the run's UTC year and the `atomic-anomaly-aggregation/1.0.0` selection-policy marker. The marker distinguishes new view-scoped aggregation from old catalogue-origin hints; it is not a scientific acceptance flag. The same explicit year is passed to property evidence and anomaly review. The API recomputes with the current request year instead of trusting a stale stored year.
- Tc, other scalar maxima and catalogue medians use reparsed canonical source quantities. A bound or interval is not collapsed into a scalar; a cached point does not replace preserved notation or units. Output precision is not rounded to three decimals.
- Hc2 values and conditions, and atomic lattice/structure groups, use the shared evidence selector with the same anomaly context. An invalid lattice group cannot re-enter through a fallback crystal/space-group record.
- Tc catalogue views can have different review and corroboration pools. No ambient-to-headline promotion or headline-to-ambient clamp forces a misleading ordering by copying values between views.
- NER confidence now describes extraction fidelity. Neither the prompt nor normalization lowers confidence merely because a reported positive Tc is unusually small or large.
- `anomaly_review` is a reserved derived envelope excluded from deterministic source identity; actual source fields remain identity-bearing.

`total_papers` counts the current retained catalogue provenance, including reviewed/flagged occurrences. It is not a count of independently confirmed positive superconductivity results. Existing corroboration wording and non-numeric catalogue policies are not a new scientific validation system.

## Offline audit

The new `scripts/audit_anomaly_aggregation.py` consumes local JSONL with `formula`, `records`, optional `legacy_summary`, and optional structured numeric `overrides`. Records must represent the current input after existing non-numeric filters. It does not connect to PostgreSQL, Redis, APIs, model services, or source repositories.

The tool replays the inventoried old destructive numeric branches: the driver 0.01–300 K exclusion, the 250 K / 1.5-times-compound-cap record exclusion, and the all-flagged fallback. It does **not** pretend to reproduce historical source availability, curator actions, or all former visibility rules. Actual old displayed values are compared only when explicitly supplied in `legacy_summary`.

It runs the new aggregation locally, reports old/new record dispositions, affected properties and rule IDs, value/provenance/condition differences, retained-record counts, unavailable comparisons, input and report hashes, and zero database/source rewrites. Output is bounded and uses scientific allowlists/redaction for old nested metadata. An old public evidence envelope is comparison metadata, never new source evidence. EPC joint compatibility is explicitly not evaluated.

Reproduce the supplied synthetic audit from the repository root:

```bash
ingestion/.venv/bin/python scripts/audit_anomaly_aggregation.py \
  docs/reviews/2026-09-05/SC03_Synthetic_Anomaly_Input_2026-09-06.jsonl \
  --current-year 2026
```

Artifacts:

- `SC03_Synthetic_Anomaly_Input_2026-09-06.jsonl`
- `SC03_Synthetic_Anomaly_Impact_2026-09-06.json`

These six synthetic materials contain seven input records. The local demonstration retains all seven; it identifies two records formerly dropped before grouping and one formerly dropped from the material record list, four changed displayed values among six supplied comparable fields, one changed condition set, and four newly resolvable provenance links. Seventy-eight fields lack a supplied historical comparison. These are test-fixture counts, not production estimates.

## Verification

The focused ingestion tests cover raw immutability, mixed/all-flagged records, low positive Tc, high-pressure/high-Tc evidence, capped and exact overrides, atomic Hc2 and lattice selection, view-scoped Tc behavior, source precision and unit/bound parsing, negative-outcome vetoes, mapper identity, and read-only audit replay/hash behavior.

The driver test executes the real aggregation function against a fake SQL executor and inspects the compiled upsert payload. It verifies that 400 K and 0.001 K occurrences survive while T4, cited, and low-confidence records remain excluded by the pre-existing non-numeric rules. It never opens a database connection.

Focused command (the final complete suite below supersedes intermediate counts):

```bash
cd ingestion
.venv/bin/python -m pytest -q \
  tests/test_anomaly_aggregation.py tests/test_anomaly_aggregation_impact.py \
  tests/test_atomic_aggregation.py tests/test_materials_aggregator_regression.py \
  tests/test_materials_aggregator_display.py tests/test_material_ner_values.py \
  tests/test_claim_outcome_integrity.py tests/test_property_aggregation_impact.py
```

Final verification after the shared alias-conflict, year-context, ambient-reference and origin-pool updates:

```text
cd ingestion
.venv/bin/python -m pytest -q tests
643 passed in 4.44s
```

Ruff passed for `materials_aggregator.py`, the two new anomaly aggregation test modules, and `audit_anomaly_aggregation.py`. The relevant tracked-file diff whitespace check passed. One existing origin-only fixture now uses YBa2Cu3O7, keeping its original origin assertions separate from the MgB2 review reference; a new test explicitly verifies that computed MgB2 at 80 K is retained but withheld under that reference, without declaring physical impossibility.

The final synthetic report was reproduced with `--current-year 2026`; its report hash is `ffb4365f282423470ccae66e27307cdb9ebf11dcdaf0e536c8cea40d627d39c5`. The shared engine now additionally marks conflicting original Tc/pressure aliases and flat/nested lattice components for review, while allowing equivalent unit representations and retaining typed-raw precedence over cached compatibility scalars. Unknown legacy override targets are retained as unresolved references and block default property selection; known targets with malformed values block the affected view instead of disappearing silently. Both final fail-closed cases are included in the complete regression count above.

## Limits and follow-up

1. Existing records already discarded by an earlier run cannot be recovered from absent data. Any restoration needs an authorized original paper/source snapshot and a review of retractions, corrections and TDM/deletion obligations. No blind merge with obsolete material records was introduced.
2. The retained-record projection is not a complete immutable ingestion archive or source-retention system. Non-numeric source/quality filters were intentionally not removed.
3. `no_findings` means no operational anomaly was detected. It does not mean peer review, verified superconductivity, eligibility for an accepted training label, or permission to execute an experiment.
4. Catalogue medians remain explicitly statistical summaries, not source-observation feature rows. Existing scientific snapshot exports still exclude flat joint-summary fields and make no scientific acceptance claim.
5. Categorical legacy overrides remain unchanged in scope. They do not acquire automatic source support through this numeric review implementation.
6. A production rollout requires the separately reviewed schema migration and a real authorized snapshot dry run before any controlled backfill. This report does not authorize that rollout.
