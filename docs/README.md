# SCLib documentation index

Start with the [repository overview](../README.md) or the live
[user documentation](https://jzis.org/docs). This index distinguishes public
reading features from implementation contracts for restricted workflows.
An implementation record does not by itself establish current production
enablement, source permission, scientific acceptance or execution authority.

## Public API and interpretation

- [HTTP API](API.md), [versioning](API_VERSIONING.md) and [scientific query routing](SCIENTIFIC_QUERY_ROUTING.md).
- [Material semantics](MATERIAL_SEMANTICS_CONTRACT.md), [pressure semantics](PRESSURE_SEMANTICS.md), [property evidence](PROPERTY_EVIDENCE_CONTRACT.md), [result origin](RESULT_ORIGIN_CONTRACT.md) and [visibility policy](VISIBILITY_POLICY.md).
- [Reported-Tc timeline contract](TIMELINE_RESULT_CONTRACT.md).
- [Verified homepage coverage snapshot, 6 October 2026](README_SNAPSHOT_2026_10_06.md).

## Materials and independent sources

- [Formula lookup](materials_formula_lookup.md), [retained record reading](material_retained_record_reading.md) and [source scopes](MATERIAL_SOURCE_SCOPES.md).
- [Recovery, classification and external references](materials_enrichment.md), [source-value extraction](materials_source_value_extraction.md) and [pressure-table sources](materials_pressure_table_sources.md).
- [NIMS Organic reader](materials_mdr_organic.md), [source-reference pilot](materials_source_reference_pilot.md), [source observations](materials_source_observations.md) and [computational reference](materials_computational_reference.md).
- [Nb-doped CsV₃Sb₅ pressure study](materials_nb_cvs_pressure.md) and [NbScTiZr annealing study](materials_nbsctizr_annealing.md).
- [Source-expression intake](source_expression_intake_v2_protocol.md), [expression workbench](source_expression_workbench.md), [table intake](material_table_intake_2026_10_05.md), [pending source properties](source_property_pending_protocol.md), [field-case workbench](material_field_case_workbench.md) and [field review](material_field_review_protocol.md).

## Discovery and local calculation tools

- [Candidate catalogue and tabs](discovery_candidate_catalogue_2026_10_06.md), [candidate list](discovery_candidate_list.md) and [research design](discovery_research_design_protocol.md).
- [Structure coordinates](discovery_structure_coordinates.md), [site candidates](discovery_site_candidates.md) and [combined candidates](discovery_combined_candidates.md).
- [Host physical references](discovery_host_physical_references.md), [source comparison](discovery_source_comparison.md) and [pressure series](discovery_pressure_series.md).
- [QE input preparation](discovery_qe_input_preparation.md), [native output reading](discovery_qe_output_reading.md), [sampled convergence](discovery_qe_convergence.md), [server preflight](discovery_qe_server_preflight.md) and [follow-up protocol](discovery_qe_follow_up.md).
- [Calculation returns](discovery_calculation_returns.md), [condition sweeps](discovery_condition_sweep_protocol.md), [condition batches](discovery_condition_batch_protocol.md) and [evidence feedback](discovery_evidence_feedback_protocol.md).

## Restricted evidence and publication workflows

- [Research-v2 implementation](RESEARCH_V2_IMPLEMENTATION.md), [implementation history](reviews/2026-09-05/README.md), [research-role/publication access](RESEARCH_PUBLICATION_ACCESS.md), [release freeze](RESEARCH_RELEASE_FREEZE.md) and [restore](RESEARCH_RELEASE_RESTORE.md).
- [Private pending native-file importer](SCIENTIFIC_PENDING_IMPORTS.md), [parser contract](SCIENTIFIC_PARSER_CONTRACT.md), [import workbench](SCIENTIFIC_IMPORT_WORKBENCH.md), [evidence workbench](SCIENTIFIC_EVIDENCE_WORKBENCH.md) and [result adjudication](SCIENTIFIC_RESULT_ADJUDICATION.md).
- [Scientific Discovery projections](DISCOVERY_SCIENTIFIC_PROJECTIONS.md), [matrix](DISCOVERY_SCIENTIFIC_MATRIX.md), [selection preparation](DISCOVERY_SELECTION_PREPARATION.md), [operator governance](DISCOVERY_OPERATOR_GOVERNANCE.md) and [main barriers](DISCOVERY_MAIN_BARRIERS.md).
- [RPS action contract](RPS_ACTION_CONTRACT.md), [distribution preparation](RPS_DISTRIBUTION_PREPARATION.md), [rights preparation](RPS_RIGHTS_PREPARATION.md), [distribution governance](RPS_DISTRIBUTION_GOVERNANCE.md), [public delivery](RPS_PUBLIC_DELIVERY.md) and [scientific evaluation](SCIENTIFIC_EVALUATION_PROTOCOL.md).
- [Source provenance](SOURCE_PROVENANCE_REGISTRY.md), [lifecycle ledger](SOURCE_LIFECYCLE_LEDGER.md), [lifecycle guards](SOURCE_LIFECYCLE_GUARDS.md) and [impact inspection](SOURCE_IMPACT_INSPECTION.md).

These contracts describe separate identities, scopes and decisions. Frozen
releases, reviewer declarations and integrity hashes must not be interpreted
as authenticated experiments, unrestricted source rights or permission to run
a calculation or train a model.

## Restricted ML preparation and governance

- [ML foundation](ML_FOUNDATION_PHASE1.md), [task datasets](ML_TASK_DATASETS.md), [scientific-feature datasets](ML_SCIENTIFIC_DATASETS_V2.md), [identity audits](ML_IDENTITY_AUDITS.md) and [label currentness](ML_LABEL_CURRENTNESS.md).
- [Review companions](ML_REVIEW_COMPANIONS.md), [baseline preparation](ML_BASELINE_PREPARATION.md) and [baseline rehearsal](ML_BASELINE_REHEARSAL.md).
- [ML08 pilot evidence](ML_PILOT_EVIDENCE.md), [registration](ML_PILOT_REGISTRATION.md), [attestations](ML_PILOT_ATTESTATIONS.md), [report](ML_PILOT_REPORT.md), [canary replay](ML_PILOT_CANARY.md) and [run-review evidence](ML_RUN_EVIDENCE.md).
- [Membership](ML_USE_GOVERNANCE.md), [intake/preflight](ML_USE_PREFLIGHT.md), [input reconstruction](ML_USE_RECONSTRUCTION.md), [current inspection](ML_USE_CURRENTNESS.md), [submissions](ML_USE_SUBMISSIONS.md), [source rights](ML_USE_RIGHTS.md) and [conditional run plans](ML_USE_RUNS.md).

These workflows prepare or inspect task-specific evidence. Their feature flags
and current grants must be checked separately. They do not expose automatic
real-data model training or turn catalogue records into approved labels.

## Retrieval and answer provenance

- [Immutable index generations](INDEX_GENERATIONS.md), [legacy index preparation](LEGACY_INDEX_PREPARATION.md), [embedding completeness](EMBEDDING_COMPLETENESS.md) and [mixed scientific retrieval](MIXED_SCIENTIFIC_RETRIEVAL.md).
- [RAG support contract](RAG_SUPPORT_CONTRACT.md), [evidence lineage](RAG_EVIDENCE_LINEAGE.md), [complementary packing](COMPLEMENTARY_EVIDENCE_PACKING.md), [evaluation](RAG_EVAL.md) and [private answer-history receipts](ANSWER_HISTORY_RECEIPTS.md).

## Deployment, operations and security

- [Deployment](DEPLOYMENT.md), [explicit schema rollout](SCHEMA_ROLLOUT.md), [workload identity](WORKLOAD_IDENTITY.md), [runtime parity](RELEASE_RUNTIME_PARITY.md) and [supply-chain security](SUPPLY_CHAIN_SECURITY.md).
- [Safe testing](TESTING_SAFELY.md), [browser testing](RESEARCH_BROWSER_TESTING.md), [observability/SLO](OBSERVABILITY_SLO.md), [background coordination](BACKGROUND_JOB_COORDINATION.md), [disaster recovery](DISASTER_RECOVERY.md) and [privacy operations](PRIVACY_OPERATIONS.md).
- [September ingest/NER pause](operations/SCLIB_AUTOMATION_PAUSE_2026-09-03.md), [site integration](operations/SITE_INTEGRATION.md) and [October materials recovery acceptance](operations/MATERIALS_RECOVERY_ACCEPTANCE_2026-10-02.md).
- [APS ingestion runbook](APS_OPENCLAW_FULLTEXT_INGEST_RUNBOOK.md), [APS validation](APS_VALIDATION_FOR_OPENCLAW.md) and [arXiv capture provenance](ARXIV_CAPTURE_PROVENANCE.md).
- [Security reporting policy](../SECURITY.md), [code licence](../LICENSE) and [data licence](../LICENSE-DATA).

Historical dataset freezes in [DATASETS.md](../DATASETS.md) have their own dates
and scope. They must not be substituted for the current live coverage snapshot.
