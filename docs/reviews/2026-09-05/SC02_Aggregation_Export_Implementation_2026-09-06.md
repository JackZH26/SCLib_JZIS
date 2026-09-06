# SC02: atomic aggregation, offline impact audit and scientific-export boundary

Date: 2026-09-06

Issue: SC02 / #47

Scope: ingestion aggregation, source-export safeguards and local impact audit; API/frontend and the shared evidence engine are parallel implementation work.

## Outcome

The aggregator now obtains Hc2 conditions and its structural/lattice projection from complete individual results. Existing Tc value-selection, review visibility and manual cap/override policies remain in place. A value produced by an old cap or override cannot acquire invented source provenance through the new evidence projection.

The source exporter explicitly declares `catalogue_summary_not_joint_observation`. Its exact material JSONL schema remains `id`, `formula`, `formula_normalized`, and `records`: material-level scalar maxima are not silently admitted as a joint scientific feature row. Typed-claim rows, source records, and acceptance defaults have not been expanded or promoted.

An offline impact tool and a clearly synthetic example report are included. They do not connect to a database, call an API/model, rewrite an input, or backfill data.

## Ingestion changes

### Atomic Hc2 and structure

`ingestion/ingestion/extract/materials_aggregator.py` uses the shared `build_property_evidence` implementation on the existing policy-filtered input records. It requests only Hc2 and three structure/lattice selection fields and explicitly disables joint-EPC computation. The daily aggregation path therefore does not perform unnecessary EPC pairing.

- Maximum Hc2 retains the conditions of the same selected result. For 20 T along c at 5 K and 100 T along ab at 0 K, the 100 T summary receives the second result's conditions.
- If the selected result lacks Hc2 conditions, the conditions remain missing. Another record's conditions are never borrowed.
- If a cap, override, typed-value disagreement or rounding leaves a final Hc2 scalar different from the selected source's exact value, its pre-override conditions are cleared. The API's separate evidence projection can resolve other exact support or mark the final value untraceable; this code does not revive the uncapped value.
- `lattice_params`, `crystal_structure` and `space_group` come from one selected structural result. Unknown components remain unknown; another record is not used to complete a cell or add a different structure's space group.
- The independent legacy `structure_phase` consensus remains a catalogue classification and is not asserted to be a member of that crystallographic observation. Explicit manual structure overrides are preserved and can become untraceable in the evidence view.
- Equal-value Hc2 and Tc selections use stable raw-content result identity within the material scope, not input ordering. Structural selection uses the same deterministic identity policy. This is reproducibility of selection, not proof that the selected structure is physically preferred.

The independent lambda and omega-log maxima remain compatibility statistics, not a paired EPC observation. The shared evidence engine treats state/structure/run/protocol association separately. A catalogue median such as the median of 1 and 3 remains 2 in the legacy column, but cannot become a source observation when no source reports 2. Even a median coinciding with a source value retains the `catalogue_median` / non-joint-statistic warning.

No derived `property_evidence` object is inserted into `materials.records` or passed as an unknown SQL column. API consumers derive that envelope separately using the final legacy summary as an anchor. The only mapper change in this SC02 work adds `property_evidence` to the existing reserved derived-envelope exclusions in `source_record_identity`; the original raw envelope remains preserved and scientific fields remain part of source identity.

### Deliberately unchanged policies

This is not SC03 implementation. Existing confidence/visibility filtering, per-family checks, cap-as-value behavior, catalogue medians, family defaults and manual overrides remain subject to their separate review issue. Existing filtering can remove a record from the compatibility projection; this change neither broadens that filter nor mutates its surviving source records. Tests retain the existing visibility behavior and verify that the caller's supplied records are not modified by atomic projection.

## Scientific-export safeguards

`scripts/export_ml_foundation_snapshot.py` adds a `scientific_semantics` manifest object:

```json
{
  "material_row": "catalogue_summary_not_joint_observation",
  "records": "source_occurrences_require_result_state_and_method_review",
  "legacy_summary_fields_exported": false,
  "joint_feature_rows_exported": false,
  "scientific_acceptance": "not_implied_by_export_or_verification"
}
```

The verifier rejects a supplied declaration claiming joint observations or accepted labels. It also rejects extra flat material fields such as `lambda_eph`, `omega_log_k`, `hc2_tesla`, or `lattice_params`, even if every artifact checksum has been recomputed. Multiple source occurrences inside one material row are not one experimental state.

Previously captured v1 source bundles without the new annotation remain verifiable because their exact material-field contract already excluded flat summaries. They are not upgraded into joint observations. New manifest bytes naturally produce a new manifest hash; material/typed-claim row contracts are unchanged. This change does not clear licensing, freeze dependency closures or make the export a reviewed training release.

## Offline impact audit

Run from the repository root against a local JSONL snapshot:

```bash
ingestion/.venv/bin/python scripts/audit_property_aggregation.py \
  docs/reviews/2026-09-05/SC02_Synthetic_Property_Audit_Input_2026-09-06.jsonl \
  --sample-limit 3
```

The command writes a JSON report only to standard output. It reads the supplied file and hashes its bytes. It does not read service credentials or import the database-backed aggregator.

The report separates:

- Source-supported view-value changes from unchanged values and missing legacy fields.
- Provenance additions, changes, removals and unavailable old provenance.
- Condition changes and newly available conditions, including legacy Hc2/Tc condition strings.
- State changes/additions, including pressure semantics, state/sample/structure/run identifiers and doping context.
- Structural changes/additions, including the selected cell and space-group association.

`supported_value_changes` compares the old catalogue number with the newly supportable display value; an untraceable number may be withheld from that supported view. It is **not** a database-rewrite proposal. `stored_values_rewritten` is zero. Missing old result IDs count as provenance additions, not proof that the prior provenance was wrong. Missing summary fields are explicitly not comparable and must not be counted as zero impact.

Prior envelopes are comparison data only, not trusted new scientific evidence. Their conditions/state/structure use fixed allowlists. Nonstandard nested values, oversized text and unknown lattice payloads are hashed/redacted rather than copied into a report; nested arbitrary private metadata is not emitted. An old malformed result ID is not treated as an actual source reference.

Sampling bounds report details while counters cover all input rows. Duplicate material IDs and malformed record arrays fail validation. The report and input digests support reproducibility; input ordering does not affect deterministic selections or the semantic report. The byte-level input digest will naturally change if file ordering changes.

### Generated synthetic example

Input: `SC02_Synthetic_Property_Audit_Input_2026-09-06.jsonl`

Output: `SC02_Synthetic_Property_Impact_2026-09-06.json`

The example contains three synthetic materials, not production measurements. Its report records one Hc2 condition change, two unsupported view values withheld (a 45 K cap and a median of 2), three newly available provenance references, and zero database rewrites. The remaining 88 absent legacy property fields are explicitly not comparable. These counts are not an estimate of production prevalence.

## Verification

### Pure ingestion/audit regression

From `ingestion/`:

```bash
.venv/bin/python -m pytest -q \
  tests/test_atomic_aggregation.py \
  tests/test_property_aggregation_impact.py \
  tests/test_materials_aggregator_regression.py \
  tests/test_materials_aggregator_display.py \
  tests/test_claim_outcome_integrity.py \
  tests/test_claim_mapper.py
```

Result: **142 passed**. Coverage includes Hc2 condition binding, missing conditions, lattice/structure atomicity, reordering, cap preservation/untraceability, non-joint EPC maxima, catalogue medians, source-identity round trips, separate state/structure audit changes, prior-envelope redaction, and read-only CLI behavior. The impact test also blocks socket creation while the report is built.

### Disposable PostgreSQL export regression

From the repository root:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py \
  --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server \
  --suite api -- -q \
  tests/test_ml_foundation_exporter.py tests/test_ml_foundation.py
```

Result: **6 passed**, one existing FastAPI `regex` deprecation warning, 1.35 seconds. The exporter used the runner's newly created disposable database, not a local development or production database. Its temporary services/data were removed by the runner. Python 3.12.14 / native PostgreSQL 16.13 / Redis 8.6.1 were used; this is not Docker-image or Python 3.11 CI parity evidence.

Ruff passed for the new/modified audit, export and test files. `git diff --check` passed for the touched tracked files. The main agent owns final whole-project verification after the shared engine, API and frontend branches of work are integrated.

## Remaining gates

- No production impact count has been measured. The audit requires an explicitly authorized local snapshot reflecting the intended review/visibility scope; it cannot reconstruct missing historical overrides or excluded raw records.
- No production aggregator, backfill, migration, deployment, commit, push or remote issue change was run for this task.
- Source support does not establish scientific correctness. A complete EPC association is not proof of Allen–Dynes applicability, reliable Tc prediction, or dataset admission.
- Typed research-state loading, provenance-backed correction, licensing-safe release, dependency-closure freezing and task-specific ML splits remain separate gates.
