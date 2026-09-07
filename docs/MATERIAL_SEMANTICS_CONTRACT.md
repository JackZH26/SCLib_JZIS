# Material semantics contract — SC10

Version: `material-semantics/1.0.0`.

The API and ingestion vendor byte-identical implementations in
`api/services/material_semantics.py` and `ingestion/material_semantics.py`.
`build_material_semantics(records, *, scope_id, family=None,
legacy_summary=None, source_statuses=None)` is a pure, non-mutating projection.
It covers only `has_competing_order`, `is_unconventional`, and
`pairing_symmetry`. No formula join, source-weighted vote, or automatic
scientific adjudication occurs.

## Small status vocabulary

| Status | Meaning in this contract |
| --- | --- |
| `reported` | At least one eligible, source-backed retained occurrence reports the value; no incompatible retained value establishes a different alternative. Not scientific acceptance or universal applicability. |
| `unknown` | The retained input cannot establish an eligible summary value or a more specific missingness status. |
| `not_reported` | An explicit record-level declaration says the field was not reported; this is not inferred from an absent JSON key. |
| `not_extracted` | An explicit processing declaration says extraction has not supplied the field. |
| `not_computed` | An explicit processing declaration says the field has not been computed. |
| `failed` | An explicit processing declaration reports failure, not a physical negative outcome. |
| `conflicted` | A retained field conflict remains unresolved. Known extraction conflicts and generic source-declared conflicts retain separate reasons. |
| `not_applicable` | Explicit non-applicability with a bounded reason and source identity; not equivalent to false or unknown. |

Absent keys and null values do not distinguish “not reported” from “not
extracted”; they therefore remain unknown. Explicit declarations use
`<field>_status` and, where relevant, `<field>_reason`. A few documented legacy
status spellings such as `not applicable` and `n/a` can preserve missingness,
but non-applicability still needs a source-bound reason. Boolean values are not
coerced from strings, numbers, or empty containers. A populated value together
with a missingness declaration is an extraction-channel conflict.

A material-level status does not erase the status of individual evidence
entries. Mixed missingness declarations remain unresolved at summary level;
their per-occurrence declarations stay available for inspection.

## Positive indicators and qualified negative reports

Only original record values can supply active properties. Historical summary
columns are diagnostic compatibility hints, never evidence. Stored
`material_semantics`, `property_evidence`, `visibility`, anomaly, pressure, and
classification envelopes cannot supply missing raw facts or remove holds.

Reported `pairing_symmetry` summary text must fit the existing 100-character
database field. Longer raw values remain unresolved with reason
`pairing_symmetry_value_exceeds_storage_limit`; they are never silently
truncated into a different value. The original raw record is retained unchanged.

For `has_competing_order`, an explicit raw Boolean can be considered. Existing
NER also reports a `competing_order` label from `CDW`, `AFM`, `SDW`,
`Mott_insulator`, or `PDW`; this can supply a source-reported positive indicator
with basis `reported_competing_order_label`. The original label is retained.
This does not establish causal competition with superconductivity. A bare
`t_cdw_k`, `t_sdw_k`, or `t_afm_k` value alone does not establish that indicator.

An explicit false value for either Boolean field is retained as evidence, but
does not become a material-level absence without all of:

1. A bounded bibliographic identifier.
2. A reported method from `<field>_method`, `measurement_method`, `measurement`,
   `method`, or `calculation_method`.
3. Bounded, non-placeholder detection/interpretation conditions from
   `<field>_detection_conditions` or `detection_conditions`.
4. No applicable source, governance, prior, or classification restriction.

Conditions can be a bounded source description or an allowlisted dictionary
containing `description`, `temperature_min_k`, `temperature_max_k`,
`magnetic_field_t`, `pressure_gpa`, `detection_limit`, and `protocol_id`.
Numeric condition fields must contain finite numbers, not Boolean or placeholder
values. An invalid or reversed temperature window does not qualify an absence.
This is a minimum provenance/shape check, not a validation of experimental
sensitivity, method suitability, interpretation, or sample comparability.

The public evidence entry exposes `negative_qualified`; an unqualified false
retains `value=false` in its evidence but has `eligible_for_summary=false` and
cannot populate the flat material value. Even a qualified false remains a
source-scoped report under its stated conditions, not proof of absence for every
state of that material.

## Priors remain separate

The historical cuprate suggestions for d-wave pairing and unconventional
classification are retained only in `priors`, labeled `knowledge_origin=Inferred`.
Their provenance is a versioned legacy SCLib application heuristic, not an
invented scientific citation. Applicability states that the individual sample
has not been assessed and that the rule is not universally applicable.

Priors never fill observed/material property columns, become ML labels, or
establish scientific approval. An explicitly source-reported result classified
as Inferred can remain a reported occurrence, with its origin unchanged; that
does not turn it into an observation. A source field explicitly marked with a
family/physics-prior basis is excluded from the active property value.

## Three distinct conflict concepts

`state_variability` is a diagnostic for differing reported values accompanied
by differing explicitly known state, sample, structure, run, sample form,
substrate, phase, doping, or pressure context. It does not establish that
source-extracted IDs are adjudicated physical identities. Missing context is not
filled by formula equality. Alternatives with unresolved context stay unknown,
not automatically classified as variability or scientific disagreement.

The same diagnostic can refer to `property=tc_kelvin` when two finite, positive,
exact raw Tc values differ and explicit state context differs. This does not add
a fourth classification property, replace a Tc summary, impose a universal
spread threshold, or declare a dispute. Bounds, ranges, approximations, and
unresolved uncertainty are not converted into point Tc values for this check.

`extraction_conflict` identifies contradictory raw channels in one occurrence,
or incompatible values under the same supplied result ID and revision. All
alternatives remain retained; no highest-confidence or majority value wins.
Those identifiers are still source-asserted, so the diagnostic requires review
rather than claiming that a physical result has been disproved. A generic
`<field>_status=conflicted` stays a field conflict without inventing an extraction
cause when no such contradiction is established.

`scientific_dispute` is separate. Its status is `reported_unadjudicated` only
when explicit retained dispute markers or a legacy material-governance dispute
flag exist. The old flag is not silently cleared. Its basis explicitly excludes
numerical Tc spread. A count of markers is not a count of independent disputes
or adjudications, and `scientific_acceptance` remains false.

## Source governance and non-approval

In ingestion mode, `source_statuses=None` permits otherwise eligible
bibliographic-source-backed reports while exposing
`current_source_status_not_checked`. This supports an auditable provisional
write without inventing a source-status lookup.

When a caller supplies a current source-status map, a missing, malformed,
unrecognized, pending, quarantined, corrected, retracted, or disputed source
cannot support a reported summary value. Positive raw/source-written labels
cannot remove a negative restriction. The API is expected to supply current
source metadata from its existing material read context.

Explicit record holds and classification conflicts also lower eligibility.
Absence of those flags is not acceptance. Shared numerical anomaly and parent
visibility policies remain separate gates and are not replaced by this module.
No T1 tier, extraction confidence, model result, or lack of findings is treated
as independent verification.

## Evidence, counts, and boundedness

Each property contains `status`, `value`, `basis`, `reason_codes`, `evidence`,
`total_evidence`, `total_occurrences`, and `evidence_truncated`. Evidence includes:

```text
result_id, result_revision, occurrence_id, occurrence_count
paper_id, bibliographic_identifiers, source_status
status, value, basis, eligible_for_summary, negative_qualified
knowledge_origin, classification_status, source_role
state, method, detection_conditions, source_locator
status_reason, source_value, reason_codes
```

An eligible contributing witness is prioritized in the bounded evidence list
so a reported summary remains inspectable even among many unknown entries.
Exact duplicate occurrences consolidate with an `occurrence_count`; they do
not become independent confirmations. Original raw records remain unchanged.

`support` counts retained occurrences, assessed structured occurrences, distinct
raw-content occurrences, source-backed occurrences, and distinct bibliographic
identifiers. DOI, arXiv, and catalogue paper IDs are counted as identifiers, not
deduplicated independent works. An arXiv/journal pair or repeated citation cannot
establish replication. Supplied root/work/sample identifiers remain
unadjudicated, so `independent_work_count` and `independent_replication_count`
are always null in this version.

The existing `total_papers` field remains a compatibility catalogue count.
`legacy_total_papers` and `legacy_total_papers_matches_identifier_count` expose
differences without silently changing either count. Differences can arise from
parent rollups, aliases, retained-record coverage, or prior catalogue policy;
they do not prove an ingestion error or independent support.

Up to 10,000 retained records and 10,000 cross-value comparisons are assessed.
Public property/conflict evidence lists and conflict identifier arrays are
bounded to 20 entries. Identities use bounded canonical raw JSON and exclude
known derived/private annotation fields. Public state/condition/locator objects
are allowlisted; reviewer identities, admin decisions, and raw governance notes
are not copied. Field-specific `status_reason` is bounded source-declared text,
not a general free-text PII sanitizer or a scientific reviewer decision.

Malformed records or exceeded assessment bounds produce explicit incomplete
coverage and prevent a reported material summary from being selected on a
partial assessment. Public display truncation is separately disclosed. The
contract does not claim a corpus-wide adjudication or production coverage rate.

## Regression and release boundary

`api/tests/test_material_semantics.py` covers missingness/false/non-applicability,
qualified negatives, source restrictions, family priors, differing states,
same-revision extraction contradictions, explicit disputes, Tc context
variation, identifier counts, privacy bounds, permutations, and byte parity.
The fixtures are synthetic software regressions, not measured scientific facts.
API and ingestion integration tests remain additional release gates; production
migration/backfill and scientific source review require their own authorization
and validation.
