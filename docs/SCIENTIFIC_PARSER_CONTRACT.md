# Scientific parser contract — SC01 / SC09

Status: local implementation for shadow evaluation. No production backfill,
re-extraction or review approval is implied.

## Numeric values

`ingestion.extract.scientific_values` is the deterministic parser used by the
material NER normalization boundary and the legacy typed-claim mapper. The NER
prompt requests original numeric notation and local evidence instead of model
conversion. `raw_extraction` preserves the complete proposal; `scientific_values`
stores per-field raw value, unit, context/locator, proposal hash and parser version.

Only reported point values can populate the legacy scalar fields. Intervals and
one-sided bounds have no compatibility scalar. The typed Tc mapper consumes the
preserved proposals directly, so `80–95 K` never becomes an 87.5 K label.
Uncertainty and approximation flags survive in claim extraction metadata and
participate in the Tc semantic fingerprint. V1 does not have dedicated uncertainty
columns; consumers must read that metadata rather than claiming exact precision.

Examples:

| Input | Canonical proposal |
|---|---|
| `1e-3 K` | point, 0.001 K |
| `20 kbar` | point, 2 GPa; raw unit retained |
| `<2 K` | upper bound, no exact Tc |
| `80–95 K` | interval [80, 95] K |
| `0.16±0.02` | central value 0.16, uncertainty 0.02, statistical meaning unspecified |

Units are property-aware and deliberately allowlisted. Frequency-to-temperature
conversions are allowed only for the specialized `omega_log_source_value` contract
with explicit units and its declared energy/cyclic-frequency convention. Generic
`omega_log_k` does not silently accept THz. Oe-to-T ambiguity, parenthesized uncertainty and other unsupported
notation remain invalid proposals until a reviewed contract is added. Numeric
values without units use the documented field unit and are labeled
`field_schema_assumption`, not source-validated measurements. A parser cannot
recover a unit or interval already discarded by an older extraction run.

Invalid proposals retain their raw data, machine-readable reasons and pending
review status. Successful parsing alone never grants scientific acceptance.
Missing locators remain missing; the software does not invent source positions.
An existing typed proposal without `raw_value` remains invalid with
`missing_raw_proposal`, preserving the complete proposal as raw data instead of
falling back to a cached compatibility scalar. Two-endpoint sequences with an
approximate or uncertain endpoint remain unresolved (`invalid_interval_endpoints`)
and retain the complete raw sequence, rather than fabricating a strict interval.

## Isotopes and composition

Formula parser version `1.1.0` recognizes isotope/charge markers before Unicode
or LaTeX normalization: superscript digits/signs, LaTeX superscripts, leading or
bracketed mass labels, and D/T aliases. First-phase policy is **recognize and
quarantine**, not calculate isotope composition or isotope masses.

These cases use the existing `composition_status=invalid` plus
`isotope_or_charge_requires_resolution`, retain `formula_raw` and the matched
notation spans, and emit no exact numeric descriptors. Here `invalid` means
unsupported/unresolved by the current parser, not a physically invalid material.
Ordinary Unicode subscripts and variable occupancies retain their existing exact
or variable semantics. Plain interior ASCII digits can be intrinsically ambiguous;
the parser cannot reconstruct lost isotope superscripts from `La2Cu18O4` alone.

NER preserves the raw isotope notation even when a model's display formula has
already flattened it. `enrich_material_composition` also checks source records
before certifying a catalog formula. The offline backfill planner and independent
composition parity check call this function and recompute the current parser
output, rather than reusing a cached old exact composition. Neither formula aliases
nor this conservative guard constitute structure/sample identity resolution.

## Offline impact manifest

Run against an authorized local JSONL material export:

```bash
ingestion/.venv/bin/python scripts/audit_scientific_parser_impact.py MATERIALS.jsonl
```

The command reads only that file and prints a versioned deterministic manifest to
stdout. It does not connect to a database, cloud or model and does not rewrite any
input. The manifest identifies stale/tampered composition caches, normalized value
changes, invalid proposals and legacy numeric records whose original unit/relation
cannot be verified. Cache invalidation is proposed, not automatically applied.

Tests cover parser golden cases, NER-to-claim preservation, unsupported input,
isotope quarantine, stale features and current planner/parity integration.
Production prevalence, re-extraction effort, curator locator quality and a full
v2 importer/database release remain separate acceptance work. This code affects
new extraction/planning runs only; historical production records and caches have
not been rewritten.

## Specialized hydride path

Hydride NER uses the same numeric parser and pre-normalization isotope guard.
It no longer requests range midpoints or model-generated unit conversions.
`HydrideExtractionBatch` retains both scalar-compatible parameter rows and every
allowlisted structured proposal, including non-scalar Tc and unresolved isotopes.
Accepted rows keep the proposal in provenance; incompatible rows are not inserted
into the legacy scalar parameter table.

The runner requires a local checkpoint and writes/flushed/fsyncs the structured
proposal journal **before** any parameter-table write. A failed journal prevents
that write. The journal includes pending status, scalar eligibility and reason,
raw quantity strings, source section, parser/model/prompt metadata. It does not
retain arbitrary model response fields or full-paper text. Unexpected oversized
structured fields are explicitly hash/length-only quarantine entries, not silently
truncated numbers; they require source reinspection. Source licensing and public
export policy still need separate enforcement.

The specialized omega conversion keeps its historical explicit constants with a
declared convention; it is not a universal frequency conversion for every field.
Disagreement between supplied Kelvin and source-unit values is flagged and no
scalar omega is selected. Existing hydride range gates still control eligibility
for that legacy table, but rejected proposals remain in the journal. Redesigning
those anomaly policies belongs to SC03, not to numerical normalization.
