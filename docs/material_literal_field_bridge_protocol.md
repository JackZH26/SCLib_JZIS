# Private raw literal field bridge

This additive bridge retains printed expressions for 14 material fields. It creates pending source expressions, pending field targets and proposed associations. It does not accept a physical interpretation, establish a sample/state identity, normalize units, release source rights, promote canonical values or approve ML use.

## Versions and compatibility

The frozen `source-expression-package/2.0.0`, numeric registry and 0083 SQL functions remain unchanged. The default source capabilities and expression lists remain 2.0. Use `profile=material-literal-field/1.0.0` for raw capabilities, raw expression lists and raw revision detail. Raw imports use `source-expression-package/2.1.0` and `source-expression-intake/2.1.0` through the existing preview, commit and outcome routes.

The default 24-field case capabilities, reads and operations remain `material-field-case/1.0.0` and `material-field-case-operation/1.0.0`. Raw operations use 1.1 only for the new 14 fields. Their association and attempt version must match the fixed target profile. Opt-in capabilities advertise the combined 38 fields with `field_request_versions`; this does not make old Tc operations 1.1. Opt-in case lists and material adapters return raw targets; old default lists return old targets.

## Literal profile

The exact registry contains `hc1_source_value`, `gap_energy_source_value`, `gap_ratio_source_value`, `electronic_specific_heat_coefficient_source_value`, `debye_temperature_source_value`, `isotope_effect_exponent`, `dtc_dp_source_value`, `maximum_applied_pressure_source_value`, `meissner_fraction_percent`, `transition_width_source_value`, `minimum_temperature_k`, `t_cdw_k`, `t_afm_k` and `t_sdw_k`.

Maximum pressure has role `study_extent`; minimum temperature has role `measurement_limit`; CDW/AFM/SDW temperatures have role `reported_order_transition`; the remaining nine have role `reported_property`. These are pending extraction roles, not a review of their physical meaning. Raw expressions have no conditions and cannot turn extrema into Tc conditions.

A 2.1 package adds the exact `profile` key to the 2.0 package shape. Its expression adds `profile`, `field_role`, `cue_spans`, `uncertainty_spans` and `qualifiers`. One original local window contains the original formula, amount, optional unit, cue and optional uncertainty. Character selections use `{start,end,sha256}`; projection spans use `{char_start,char_end,text_sha256}`. Projection retains printed `raw_value`, `raw_amount`, `raw_unit`, `raw_uncertainty`, cue and qualifier declarations. `quantity` is always null and `normalization` is `none`.

0086 independently recomputes these selections and their hashes in PostgreSQL. Existing immutable, atomic receipt, predecessor and inventory guards remain active. Mandatory selectors reject unknown versions or mismatched package, field and target profiles. Downgrade refuses retained 2.1/1.1 history.

## Prepare from actual retained source

`POST /research/material-literal-fields/prepare` uses the existing default-disabled private source flag and curator/reviewer read access. The closed request has exactly:

- `version`: `material-literal-field-prepare/1.0.0`
- `material_id`, `target`: the existing retained-result selector and current context hash
- `candidate_id`, `extractor_version`: current server enrichment pins
- `chunk_id`, `source_content_sha256`: actual retained original chunk pins
- `retained_result_id`, `retained_record_sha256`: exact selected retained record pins

The server rereads the current material partition, actual chunk bytes, evidence descriptor and source lifecycle. It reruns the bounded enrichment read and verifies the selected source fact and record reference. It never receives source text or candidate metadata from the browser, prepends a target formula, invents an alias or derives a source URL from an opaque paper ID. Missing stored DOI/arXiv URL, unresolved original/abstract chunk origin, stale/restricted evidence, held material/source, changed content/context or unavailable bounded candidate produces an explicit hold/error.

The response contains an inspectable 2.1 package, package/projection hashes, unchanged target context and a proposed 1.1 target operation. It writes no ledger. Capture metadata records a retained fragment declaration; publication revision, parent publication hash, rights and currentness remain unverified. Subsequent source import and field operation preview/commit remain separate explicit curator operations. Existing revision predecessors must be supplied for a successor.

## Current pending reads and retained history

Raw 1.1 association reads require the latest retained capture for that source and current curator authority for the original capture, import receipt and association actors. The existing read-only authority predicate checks each pinned grant and session independently. A later capture or an invalidated grant/session withholds the current expression: `expression` is null and `eligibility.eligible` is false. The association ID, immutable payload, canonical record and hashes remain available as history. Direct revision detail remains a historical source view and still reports capture currentness; it does not restore adapter eligibility.

Opt-in case capabilities add `read_hold_reason_codes` in this exact order: `literal_capture_superseded`, `literal_capture_authority_held`, `literal_import_authority_held`, `literal_association_authority_held`. These codes describe adapter reads only. The write-time `reason_codes` registry and old default 1.0 capability shape and behavior remain unchanged. A readable pending expression still carries no scientific, canonical, public or ML approval.

## Validation scope

Native validation uses fresh owned PostgreSQL/Redis and synthetic source fixtures. Required positive proof is 14 actual expression revisions, 14 actual targets and 14 matching proposed associations returned through the private adapter, with original spans/raw values and null quantities. It also tests legacy numeric/Tc operations and frozen function definitions, version/field mismatches, rehashed forgeries, replay and source/target holds. A passing pending workflow does not establish scientific precision or catalogue-wide source coverage.

Late-hold regression tests use distinct capture, import, association and reader actors. They isolate each of the three upstream grant revocations and each of the three session changes, then read in a PostgreSQL read-only transaction. A separate capture replacement keeps the old expression revision as its expression head while changing source-capture currentness. Every case asserts the exact hold, withheld expression and preserved immutable association history, alongside frozen legacy function definitions and default capabilities.
