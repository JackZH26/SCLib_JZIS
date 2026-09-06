# Atomic property evidence contract — SC02

Status: local pure-function implementation. This is a bounded derived display
and audit projection, not adjudication, production repair or a joint ML observation.

## One implementation in independent images

Canonical module: ingestion/ingestion/property_evidence.py.
API mirror: api/services/property_evidence.py. Tests enforce identical bytes.
Both use their local byte-matched numeric, pressure, origin and outcome contracts.
The module performs no database, filesystem, cloud, model or network I/O.
Policy version: property-evidence/1.1.0.

    build_property_evidence(
        records,
        scope_id="mat:example",
        legacy_summary=existing_summary,  # None only for explicit new selection
        reviewed_epc_matches=(),           # trusted review storage only
        include_joint_epc=True,
        property_fields=None,             # defaults to PROPERTY_FIELDS
        anomaly_context=None,             # external trusted context; gate always on
    )

PROPERTY_FIELDS is the authoritative display-property registry. NUMERIC_PROPERTIES
maps display properties to raw quantity fields; CATEGORICAL_PROPERTIES lists
directly reported discrete assertions. Unknown requested fields are rejected.

Numeric coverage includes Tc headline, experimental/theoretical splits and explicit
ambient Tc; Hc2; lambda, omega-log and superfluid stiffness; competing-order
temperatures; resistivity exponent; doping; London depth, GL coherence length
and layer thickness. Structural coverage includes a single-record lattice group,
crystal structure, space group and phase. Pairing, gap, competing-order,
sample/substrate/doping and interface assertions remain traceable discrete fields.

Temperature-role and lattice-component quantities use the same raw-preserving
unit parser. Unsupported units stay unresolved. No value is inferred from formula,
family, bulk sample form, another record or paper-wide genre.

The ambient_sc, disputed and retracted flags are intentionally NOT properties.
Ambient-superconductivity summaries require supported Tc and explicit pressure.
Governance warnings must not disappear because a raw record lacks a flag.
This module does not implement source-retraction or visibility policy.

## Response and bounded evidence

    version
    anomaly_policy_version
    not_joint_observation: true
    properties[field]:
      status: supported | untraceable | not_reported | pending
      selection: legacy_exact_support | deterministic_result | none
      selected: Evidence | null
      evidence: Evidence[]                  # maximum 20
      total_evidence_count: integer
      truncated: boolean
      statistic: catalogue_median | null
      warnings: string[]
    joint_epc:
      status: eligible | pending | not_reported | not_evaluated
      selected: Pair | null
      pairs: Pair[]                         # maximum 20
      total_pair_count: integer | null
      total_pair_count_exact: boolean
      total_pair_count_lower_bound: integer
      evaluated_pair_count: integer
      comparison_budget: integer
      truncated: boolean
      warnings: string[]

Supported means a contributing raw occurrence supports the value. It does NOT mean
correct extraction, source review, replication, state completeness, method validity
or scientific acceptance. Untraceable values receive no invented source.

Evidence has a fixed allowlist:

- result_id, property, value, quantity, bounded anomaly_review and warnings.
- conditions: same-record hc2_conditions, tc_conditions, tc_type, tc_criterion,
  hc2_direction, field-orientation aliases, measurement/method aliases and protocol
  IDs. Temperature quantities retain distinct roles: temperature_k,
  measurement_temperature_k and hc2_temperature_k are not interchanged.
- state: state_id, structure_id, sample_id, run_id, pressure_semantics, sample_form,
  substrate, doping_type and a doping quantity. The selected raw record's formula
  and formula_raw are optional strings limited to 200 characters. They never
  borrow a parent/catalogue summary formula, undergo normalization or establish
  EPC composition equality/inequality by string comparison.
- source: paper_id, DOI, arXiv ID, reported year and bounded source_locator.
  Numeric properties use their own preserved quantity locator when available.
- origin: the shared **record-level** result-origin and source-role classification,
  not an independently established origin for every property. An Observed record
  may include a measured Tc alongside inferred coupling or mechanism parameters.
  Clients must label it Record origin, retain the reported method context and
  avoid treating this label as property-level measurement validation.
- structure: same-record crystal_structure, space_group, structure_phase,
  lattice_params and per-component lattice_quantities.

Quantity preserves status, relation, value/lower/upper, unit, uncertainty and its
unspecified interpretation, approximation, raw value/unit, unit basis, parser
version/hash and reason codes. Bounds/intervals are browsable evidence, not scalar
selections. Uncertainty/approximation points can support an existing center only
with their precision metadata and warnings; the float alone is incomplete.

Lattice evidence has relation=group and per-component proposals. The module never
gets a from one record and c from another. If a legacy group only displays a,
a source containing both a and c may support the subset, but selected.value stays
a-only. Its complete SAME-SOURCE structure remains inspectable; that does not
authorize restoring an omitted flat compatibility component.

State/method/source absence stays explicit. Every per-property evidence list has
at most 20 entries, an exact total and truncation flag; the selected result stays
visible. Strings and source locators have explicit field/length limits. No arbitrary
nested raw records, private provenance, full-paper text or source excerpts are
exported. Oversized/structured raw quantities become a redaction/hash diagnostic
in this public projection. Source originals are not modified.

## Selection and legacy compatibility

With legacy_summary provided:

1. Select only an exact supporting finite point, discrete assertion or requested
   lattice components from one occurrence.
2. A null or absent legacy value is not recomputed. Raw alternatives are browsable
   but are not promoted to selected summary values.
3. If no source supports the value, return untraceable. Do not use the nearest,
   largest or most convenient record instead.
4. Respect a Tc headline's legacy contributing-origin pool when its split fields
   establish that pool. Equal Computed values do not become an experimental
   headline's provenance by hash order. Missing support receives
   legacy_origin_pool_untraceable.
5. Catalogue rho_exponent and doping_level medians remain labelled
   catalogue_median. A middle value with no source is untraceable; a coincident
   source does not turn the statistic into a joint experiment.

List, detail, variant and bookmark adapters must pass the original stored split
values as selection hints even if those fields are absent from a compact response.
Otherwise a compact read might select a source rejected by the full read.

This preserves existing values at the projection boundary while requiring source
support and current anomaly eligibility; it does not validate old caps/overrides
or establish visibility policy (SC07). Higher source values are not silently
restored to a summary or selected joint EPC pair.

New aggregation can explicitly supply the trusted, versioned context marker
selection_policy=atomic-anomaly-aggregation/1.0.0. Only that marker allows headline
origin selection from the currently eligible positive-point Observed pool, then
Computed if the Observed pool is empty. Legacy value equality remains necessary.
This handles view-specific references that make headline and split values differ.
It never guesses that an old snapshot already followed the new policy. An old
headline with inconsistent split support remains untraceable.

The default anomaly gate is property-scoped and uses anomaly-review/1.0.0.
Candidates retain original proposals and a bounded assessment; affected properties
cannot be selected. The property-level anomaly_review_required warning survives
compact projection even when candidate lists are omitted. Context can supply
family, compound_thresholds and explicit current_year; absent context family
falls back to legacy_summary.family. No hidden clock or raw self-approval exists.
See ANOMALY_REVIEW_CONTRACT.md for operational references, scopes and limits.

Without a legacy summary, numeric maximum fields select reported point centers;
median/discrete/structure views choose a single source rather than manufacturing
statistics or groups. This mode is an explicit new-selection operation.

Ties use stable raw-content result ID, not input order, recency, extractor
confidence or an invented quality score. Identity is the shared search hash of
[scope_id, raw_record], with sorted keys and compact JSON. Only reserved derived
result_classification, pressure_semantics, property_evidence and anomaly_review envelopes are
excluded. Original scientific fields remain in identity. Reordering or annotating
does not mint another occurrence; a real raw change does.

Identical raw occurrences are deduplicated. These are legacy occurrence IDs, not
global scientific result identities, work-version reconciliation or counts of
independent replication.

## Joint EPC association

Independent selected lambda and omega-log maxima are not a paired calculation.
Automatic association requires:

- Resolved Computed origin without conflicting source role.
- Explicit matching state, structure and run IDs.
- Matching, non-missing method and protocol.
- No known conflicting pressure, sample/substrate, doping, common lattice
  component, crystal phase or same-role temperature evidence.
- No pending numeric anomaly for the paired parameters or their reported
  pressure, lattice, doping or temperature state associations.

Two values in one raw record remain pending when association is incomplete.
Contradictory/ambiguous pressure cannot be repaired by equal IDs. Unreported
pressure remains unknown; a complete explicit association does not invent ambient
or numeric pressure.

An external accepted, revisioned review can resolve missing association. It must
bind exact result_ids, review_id, review_revision, state_id, structure_id and
protocol_id. It cannot contradict known IDs, either protocol alias or known state
values or waive numerical anomaly review. Raw reviewed=true or NER self-approval is ignored. The caller must obtain
operations from trusted review storage, never a client request or model output.
Current public callers supply none. Review revision participates in pair identity.

Eligible means ASSOCIATION COMPLETENESS ONLY. Every pair says
allen_dynes_applicability=not_assessed. It does not certify phonon stability,
Migdal/adiabatic assumptions, isotropic applicability, mu-star, strong-coupling
formula accuracy or superconductivity. Automatic paired-point selection leaves
explicit uncertainty/approximation pending unless an external review establishes
the association; richer uncertainty-aware exports require an explicit next policy.

With a legacy summary, both EPC values must also support its lambda and omega-log
values. Null, capped or unsupported fields cannot be bypassed by joint selection.

Candidates are indexed by state/run/protocol keys and trusted review result IDs.
Unrelated states do not generate a Cartesian product. Same-group comparisons are
bounded at 10,000. An incomplete scan reports total_pair_count=null, a confirmed
lower bound, evaluated count and explicit warning. It never presents a partial
count as exact. Only 20 pair objects are retained; bounded traversal is deterministic.

Aggregation/list callers can request a property_fields subset and disable joint
evaluation. A skipped stage is not_evaluated, not an absence-of-evidence claim.

## Verification and limits

Pure tests cover the Hc2 20 T along c at 5 K versus 100 T along ab at 0 K
counterexample; raw unit conversion and tampering; missing raw proposals;
same-result conditions/locators; tied sources; Tc contributing pools, ambient
pressure and nonpositive outcomes; mixed lattice sources; catalogue medians;
bounded/private metadata; association conflicts and trusted review binding;
preserved caps, comparison budgets and independent-image byte parity.

Ingestion and API/frontend adapters consume this projection separately. Read-only
impact auditing must distinguish value changes from provenance/condition changes
without rewriting production. Historical extraction may already have merged states
or discarded details. This module cannot recover that evidence, resolve all
sample identities, approve NER claims, invalidate retracted sources or produce a
release-ready scientific ML dataset.
