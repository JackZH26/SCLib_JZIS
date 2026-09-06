# Shared pressure semantics — SC04

`ingestion/ingestion/pressure_semantics.py` is the canonical standard-library-only
implementation. `api/services/pressure_semantics.py` is a byte-identical vendored
copy for the independently built API image. A regression test enforces parity.
Policy version: `pressure-policy/1.0.0`.

## API contract

```python
assessment = classify_pressure(record)
assessment.to_dict()
pressure_matches(assessment, max_gpa=None, min_gpa=None,
                 ambient_only=False, include_unknown=False)
annotate_pressure_records(records)
```

The immutable assessment contains `pressure_state`, `pressure_gpa`, `relation`,
`value_lower_gpa`, `value_upper_gpa`, `uncertainty_gpa`,
`uncertainty_interpretation`, `raw_value`, `raw_unit`, `unit_basis`, `approximate`,
`source_locator`, `reasons` and `classifier_version`.

`annotate_pressure_records` returns record copies with the derived
`pressure_semantics` envelope. The classifier ignores an existing envelope and
recomputes from original evidence. This envelope is excluded from source-occurrence
identity hashing; raw scientific fields and `scientific_values` are not excluded.

## Meaning and evidence precedence

| State | Meaning |
|---|---|
| `explicit_ambient` | A local explicit ambient/atmospheric/zero-pressure statement, or explicit ambient state with an actual zero quantity |
| `reported` | Parseable nonnegative pressure quantity, including intervals/bounds |
| `not_reported` | No pressure quantity or explicit pressure assertion |
| `ambiguous` | Legacy unexplained zero, conflicting assertions, missing claimed quantity, unsupported negative pressure or invalid syntax/unit |

The parser first reparses preserved `scientific_values.pressure_gpa.raw_value`
and its original input unit, rather than trusting its cached normalized value.
If a typed pressure proposal exists without `raw_value`, its complete content is
retained as the assessment's `raw_value`, with `missing_raw_proposal` and no
normalized scalar or extent. A cached scalar never substitutes for that missing
source evidence. Only when no typed proposal exists does the parser read
`pressure_gpa`/`pressure` and their unit fields. Specialized
hydride rows can supply the original structured proposal through
`provenance.extraction_proposal`.

`pressure_condition` may carry direct local wording. Its legacy `*_normalized`
derivative, `ambient_sc`, `pressure_type=none`, bulk/sample form and `tc_regime`
never establish ambient pressure. An explicit state without a quantity or local
ambient statement is not enough to manufacture zero.

Ambient is represented by 0 GPa under the existing catalog ambient-reference
convention; this is not a claim of zero absolute thermodynamic pressure. A numeric
zero lacking explicit evidence stays ambiguous. Explicit nonzero pressure plus an
ambient assertion is a conflict, not an invitation to select one silently.

Supported units: GPa, MPa, kPa, Pa, bar, kbar and atm with documented SI-case
handling. Bare legacy numbers use the GPa field convention and carry
`legacy_field_unit_assumed_gpa`; they have not thereby been source-verified.
Supported quantities include scientific notation, intervals, one-sided bounds,
two-endpoint sequences and symmetric +/- uncertainty. Uncertainty interpretation
remains unspecified. Unsupported syntax stays ambiguous with original evidence.

Negative pressure is retained in the assessment but is currently outside this
conventional-pressure policy's supported state domain. It is never called ambient
or admitted to a pressure-filtered list by the include-unknown option. Supporting
tensile/effective-pressure protocols requires an explicit future contract.

## Filtering

No pressure predicate means no pressure filtering. Otherwise a numeric condition
must be satisfied by the whole reported extent, not a midpoint. An interval
[2, 3] GPa passes max=3 but not max=2.5. A one-sided bound cannot prove a missing
opposite bound. For `p +/- u`, filtering tests `[p-u, p+u]` without inventing a
confidence level. An approximate point without a bounded extent cannot establish
a precise numerical cutoff.

Unknown/ambiguous pressure is excluded unless `include_unknown=True`; the caller
must visibly distinguish this explicit mode from verified numeric matches. A
compound material query must apply family, Tc, pressure and evidence policy to the
same result. `pressure_matches` alone cannot enforce that cross-property identity.

## Ingestion integration and v1 compatibility

- Material NER asks for local pressure wording and emits the derived envelope
  without mutating raw extraction proposals.
- Material aggregation only considers same-result explicit ambient evidence for
  ambient Tc; neither unrelated sample regimes nor a bare ambient boolean qualify.
- Derived fact sentences render explicit units, ranges, bounds and uncertainty;
  bulk or legacy zero no longer generates an ambient-pressure sentence.
- The typed v1 mapper cannot store a reported interval in its scalar-only
  pressure column. It projects that column to ambiguous/null and stores the
  complete reported extent in `extraction_metadata.pressure_semantics`. Negative
  values likewise remain in metadata, not in its nonnegative legacy column.
- Pressure relation, extent, uncertainty and approximation participate in the
  semantic fingerprint, so different pressure intervals are not treated as the
  same scientific condition.

This is new-pipeline and read-projection behavior, not a production repair. Existing
material summaries and fact-vector chunks require a separately reviewed rebuild
to reflect the policy. No historical raw values, production schema or database rows
were rewritten during implementation. Parser agreement, source-hash round trips,
derived sentences, aggregator behavior and API-copy parity have offline tests.
