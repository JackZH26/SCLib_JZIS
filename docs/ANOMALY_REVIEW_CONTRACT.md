# Non-destructive anomaly review contract — SC03

Status: local implementation and offline verification. This contract does not
claim a production incident, production repair, historical data recovery, source
validation or completion of a scientific curation workflow.

## Purpose and implementation

Canonical module: `ingestion/ingestion/anomaly_review.py`.
Independent API image: `api/services/anomaly_review.py`, byte-identical by test.
The standard-library-only module performs no database, file, model or network I/O.
Policy version: `anomaly-review/1.0.0`.

The engine separates three cases:

- `format_invalid`: original notation, unit or field shape cannot be represented
  by the current parser. This is not proof that a material is physically invalid.
- `unusual`: a reported value crosses an operational review reference or requires
  an explicit physical convention. This is not a physical impossibility claim.
- `metadata_conflict`: incompatible assertions or unresolved review context need
  source-backed resolution.

Every finding is pending. Values are never capped, replaced, rounded, deleted or
approved. `raw_preserved=true` means this function does not mutate the input; it
does not imply that older ingestion versions retained all historical originals.
The ingestion integration must retain the complete current input record list.

`no_findings` means only that this policy did not raise a finding. Every response
states `scientific_acceptance=false`. Neither that status nor property eligibility
is a released ML-label admission decision.

## API and wire

```python
assess_record_anomalies(
    record, scope_id="mat:example", family=None,
    compound_thresholds=(), current_year=None,
)
eligible_for_property(assessment, "tc_max")
build_anomaly_review(
    records, scope_id="mat:example", family=None,
    compound_thresholds=(), current_year=None, record_limit=100,
)
record_property_quantity(record, "lattice_a")
rule_registry()
```

The last numeric accessor reparses original proposals, including `tc`/Tc view
aliases, `pressure`/pressure-unit aliases and same-record nested lattice
components. It never trusts a cached normalized scalar over a typed raw proposal.
Unsupported scalar field names, including the whole `lattice_params` group, raise
`ValueError`. This internal-service accessor preserves full raw data; callers must
not export its arbitrary nested raw value directly as a public response.

Each assessment contains:

```text
version, evaluation_year, result_id
status: no_findings | review_required | format_invalid
findings: Finding[]                       # maximum 40
total_findings, findings_truncated
rule_counts                              # exact, before truncation
review_required_properties               # complete, before truncation
raw_preserved: true
scientific_acceptance: false
```

Each finding contains `finding_id`, `result_id`, `rule_id`, `rule_version`,
`category`, `field`, `affected_properties`, structured `applicability`, stable
`reason`, fixed `description`, `severity`, `outcome=pending`,
`action=retain_raw_and_review`, bounded `quantity` and
`default_view_disposition=review_required`. Applicability explicitly states
`physical_limit=false` and identifies the reference basis, unit, threshold and
relevant family/pressure/origin/view scope. IDs are deterministic for the same
raw occurrence, context and policy.

The material-level builder assesses every current occurrence, returns exact
record-status and rule counts, and emits at most 100 result assessments sorted by
stable result ID. `record_limit` may be reduced to zero for counts-only callers.
It reports `records_truncated` and `total_records`; bounded output never silently
turns partial findings into complete eligibility or count claims. Duplicate input
occurrences remain occurrences in these counts, not independent replications.

Public quantities preserve finite original parsed centers, endpoints, uncertainty,
notation and unit diagnostics. Strings are bounded; structured or oversized raw
values are represented by a redaction/hash diagnostic. Private nested provenance,
arbitrary source notes and full-paper text are not copied. Arithmetic extents used
for threshold evaluation are not exported as invented measurements; very large
finite uncertainty inputs cannot serialize newly generated infinite bounds.

Coexisting `tc_kelvin`/`tc` or `pressure_gpa`/`pressure` channels and flat/nested
lattice components are checked for consistency. Equivalent canonical units agree;
different values, relation, uncertainty or approximation remain pending under
`raw_quantity_conflict`. Unresolvable coexisting notation cannot be silently
shadowed. Findings expose bounded source-channel names, not arbitrary source data.
A typed raw proposal retains precedence over its own normalized compatibility
flat scalar; that scalar and `scientific_values.value` are not treated as another
original observation. Independent alias/nested channels are still compared against
the typed original. This boundary does not reconstruct lost raw-channel provenance
or retroactively certify old normalized caches.

## Centralized operational references

These values are retained or consolidated from local legacy operational code.
They have **not** been independently verified here as current records, literature
consensus or universal physical bounds. A finding requests review, not rejection
of a potential discovery.

| Rule / scope | Operational reference | Default affected properties |
| --- | --- | --- |
| Broad reported Tc, every pressure including unknown and every origin | Above 250 K | All Tc views for that occurrence |
| Resolved Observed Tc with explicit same-result ambient pressure | Above 152 K | All Tc views for that occurrence |
| Known family Tc | Family table below | All Tc views for that occurrence |
| Reported pressure | Above 500 GPa | Pressure only |
| Hydride, entire explicitly reported pressure extent below 50 GPa | Tc above 100 K | All Tc views for that occurrence |
| Electron–phonon coupling | Outside 0.01–10 | `lambda_eph` only |
| Coulomb pseudopotential | Outside 0–0.5 | `mu_star` only |
| Logarithmic phonon frequency | Outside 1–5000 K | `omega_log_k` only |
| Year | Before 1900; after explicit `current_year + 1` when supplied | Year only |

Family references in kelvin: cuprate 180; iron_based 110; nickelate 110;
hydride 270; mgb2 50; fulleride 50; bismuthate 45; conventional 45;
chalcogenide 40; elemental 40; borocarbide 30; bis2_layered 30;
heavy_fermion 30; organic 25; kagome 15; ruthenate 10. Rules may overlap;
for example the broad 250 K reference is already crossed before hydride 270 K.
Overlapping findings preserve their separate provenance and applicability.

A record's explicit family takes precedence over the external material-family
context. No family is inferred from a formula. The legacy unknown-family 45 K
fallback is retired: missing taxonomy is not evidence for a low physical ceiling.

Finite positive low Tc has no heuristic minimum. `1e-3 K` and `1 mK` remain
0.001 K. A zero Tc is not a positive transition headline, but this anomaly policy
does not manufacture a negative-superconductivity label from it. Likewise,
lambda=0 is unusual relative to the operational interval, not proof of non-SC or
format invalidity. Negative temperatures and pressure require source/convention
review; negative pressure is not universally impossible.

An explicitly reported interval is not an exact scalar. Review thresholds use
the reported extent, including uncertainty: a partial crossing is labelled
`reported_extent_may_exceed_reference`, distinct from a definitely above-reference
extent. Approximation and unknown uncertainty conventions remain visible.
The hydride low-pressure rule requires a fully bounded, non-approximate pressure
extent below 50 GPa. It does not combine pressure and Tc from different results.

Missing pressure and an unexplained legacy zero are not ambient evidence. They
do not trigger the ambient-Tc rule or automatically become pressure anomalies.
Known conflicting explicit pressure assertions produce a pressure finding.
Bulk sample form and catalogue `ambient_sc` do not establish measurement pressure.

Year evaluation has no hidden clock. Callers pass and persist `current_year`
where reproducible chronology checks are required. API archive and property
projections must use the same context for one assessment. Integer 1911 remains
valid; noninteger years are format-unresolved. This does not resolve publication,
preprint, experiment or discovery-year basis (SC06).
Both per-record and material assessments expose `evaluation_year` (null if no
year was supplied), including no-findings responses. Year context never changes
the raw occurrence's stable result ID.

## Compound references and disabled exact overrides

Trusted external context supplies references, not raw NER self-assertions:

```json
{
  "policy_version": "anomaly-review/1.0.0",
  "family": "mgb2",
  "current_year": 2026,
  "selection_policy": "atomic-anomaly-aggregation/1.0.0",
  "compound_thresholds": [
    {
      "field": "tc_max",
      "threshold": 45,
      "reference_id": "manual_overrides:example",
      "mode": "upper_reference"
    }
  ]
}
```

`upper_reference` is the default mode. The target is a supported numeric property
or Tc view; finite threshold and bounded auditable reference ID are required.
Free-form override source notes are not copied into public findings. Malformed
reference shapes produce `review_context_unresolved`, not silently ignored policy.

External references are view-scoped: a `tc_ambient` reference applies only to
explicit ambient Observed occurrences and only to the ambient view. It does not
ban a high-pressure result or every Tc view. This differs deliberately from the
built-in explicit-ambient unusual-value rule, which flags that result's Tc itself
and therefore all Tc views. Experimental/theoretical targets use resolved origin
before applying their reference. Raw `tc_kelvin` rules affect every Tc view.

`unreviewed_exact_override` records a historical requested numeric replacement.
Every reported target value stays pending even if it happens to equal the proposed
number. The threshold is only the old proposal; the engine never writes it into
the scientific value. A 60 K observation plus a 45 K reference never produces an
invented 45 K observation. A separate source actually reporting 45 K may support
that value after the normal view and origin checks.

Raw `reviewed=true`, NER-generated admin decisions and cached anomaly envelopes
cannot approve findings. This module accepts no approval waiver. Source-backed
correction submission is a separate append-only proposed-revision facility; a
proposal alone must not silently rewrite originals, invalidate provenance or
publish a corrected scalar. Full accepted-review/revision application remains
outside this contract.

## Property selection and identity

`property-evidence/1.1.0` applies this policy by default. An optional external
`anomaly_context` supplies family, compound references, year and the new aggregation
selection marker. Each candidate retains its quantity/raw proposal and receives a
bounded `anomaly_review` assessment. Only affected properties are ineligible.
An anomalous Tc does not delete an unrelated Hc2 in the same record.

When all supporting candidates for a property require anomaly review, the property
entry includes `anomaly_review_required` even if compact responses omit candidates.
No new synthetic numeric value is selected. An invalid lattice component blocks
the atomic lattice group; a crystal/space-group fallback cannot smuggle that
ineligible lattice group back into a flat projection. Its original component
proposals remain inspectable.

Joint EPC selection additionally checks associated reported pressure, lattice,
doping and temperature roles. An external association review cannot waive a
numeric anomaly. Association completeness still does not certify Allen–Dynes
applicability, phonon stability or superconductivity.

New aggregation may explicitly persist
`selection_policy=atomic-anomaly-aggregation/1.0.0`. Only that known marker allows
headline source selection using the current eligible positive-point Observed
pool, followed by Computed when no eligible Observed pool exists. Legacy summary
value equality is still required. This handles view-specific references where a
headline differs from its split summaries without assigning a coincident theory
value as an experimental source. Old snapshots retain conservative contributing-
split anchoring; unresolved old origin support stays untraceable. A raw record
cannot enable this policy by claiming the marker itself.

Stable legacy result identity excludes only reserved derived envelopes:
`result_classification`, `pressure_semantics`, `property_evidence` and
`anomaly_review`. Original scientific fields, including typed raw proposals, remain
identity inputs. Adding review annotations does not mint a new source occurrence;
an actual raw evidence revision does.

## Migration boundary and verification

The legacy inventory includes broad Tc whole-record drops, compound-cap drops,
all-bad fallbacks, exact summary overrides, summary clamps, numeric precision
rounding, driver low/high Tc drops, and inconsistent audit/NER/timeline thresholds.
Integrations must remove destructive numeric actions rather than merely append a
new helper that those paths bypass. Existing governance review flags must not be
automatically cleared by a new no-findings response. Visibility/retraction,
mechanism/family priors, corroboration counts and confidence calibration remain
separate policies, not numeric validity judgments.

Pure regressions cover unit conversion and raw re-parsing; positive sub-millikelvin
values; explicit/unknown/negative pressure; same-result hydride context; unusual
versus format-invalid categories; view-specific references; disabled exact
overrides; field-scoped selection; EPC/lattice bypass prevention; deterministic
identity; bounded private-safe projections and exact counts; huge finite
uncertainty; explicit year; origin-pool selection markers; and independent-image
byte parity. Dual-write conflicts and equivalent-unit aliases are covered without
mistaking typed compatibility fields for independent originals. Offline impact reports must separately count retained raw evidence,
scientific-view eligibility changes and legacy synthetic values no longer emitted.
No historical full-corpus re-extraction or production migration is authorized by
these pure-function tests.
