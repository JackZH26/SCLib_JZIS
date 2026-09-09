# Exact-result review companions for frozen ML datasets

Date: 2026-09-08.

Status: **Original proposal, retained for design history**. The bounded
negative-only implementation was added in the
[thirty-fifth batch](Priority_Thirty_Fifth_Batch_Implementation_2026-09-09.md).
Use [ML_REVIEW_COMPANIONS.md](../../ML_REVIEW_COMPANIONS.md) for the actual
interfaces, private full-audit admission and operational boundaries. Proposed
signatures and future-authority discussion below are not a live API contract.

Scope: a bounded next implementation slice following the 0067 exact-property adjudication work.

This document originally recorded a read-only code review and proposed integration.
Implementation and actual execution evidence are recorded separately in the
batch report above. No training authorization is supplied by either document.
No training, paid evaluation, production database operation, source backfill, or
external publication was performed for this design.

## 1. Recommended outcome

Add a separately pinned, private review companion and a new compiler version that applies exact-result review holds **before feature admission and preprocessing**. Preserve the original 0054 capsule, its artifact bytes, the existing source companion, and all producer input/output documents unchanged.

The first policy should be **negative-only**: rejected, clarification-required, stale, source-held, reviewer-unavailable, or dependency-held properties are unavailable as features. An accepted review is retained as a scoped observation; it does not waive the existing source-time, state, calculation, protocol, target-leakage, or label checks. Unreviewed properties retain the pre-existing compiler policy, not an invented acceptance.

This closes a concrete review-to-ML consumption gap without promoting the current native-file import canaries into scientifically qualified training data.

## 2. Code and interfaces inspected

| Existing path | Observed responsibility and reusable interface |
| --- | --- |
| `api/services/research_release_manifest.py` | `research-release/1.0.0`; `verify_manifest`, `canonical`, and `digest` validate the original frozen rows and actual artifact bytes. |
| `api/services/research_release_spec.py` | Frozen table fields and FK specification. 0065 import and 0067 decision ledgers are not added to this specification. |
| `api/services/ml_dataset_builder.py` | `ml-task-dataset/1.0.0`; `_compiler` pins its implementation sources; `_label_reasons`, grouping, composition, and split helpers implement the existing label policy. |
| `api/services/ml_dataset_builder_v2.py` | `ml-task-dataset/2.0.0`; `build_task_dataset_v2` and `verify_task_dataset_v2` consume independently pinned capsule, task, and source companion. `_implementation` adds physical/coordinate/compiler source pins. Feature admissions precede nested cohorts and train-only preprocessing. |
| `api/services/ml_frozen_provenance.py` | `resolve_result_contexts` obtains result identities, scientific conditions, explicit dependencies, and source witnesses from frozen rows. Pending event/claim review remains a reason, not approval. |
| `api/services/ml_feature_companion.py` | `ml-feature-companion/1.0.0`; `feature_input_pins`, `capture_feature_companion`, `verify_feature_companion`, and `decode_companion_artifacts` bind exact input/source identities and actual review/capture bytes. The expected external companion SHA hashes the **complete file**, distinct from its internal body digest. |
| `api/services/ml_feature_provenance_v2.py` | `computed_lineage` requires actual `ml-computed-input/1.0.0` and `ml-computed-output/1.0.0` documents; `applicability_reasons` and `validate_structure_context` preserve exact state or narrowly declared normal-state-surrogate conditions. |
| `api/services/ml_scientific_features.py` | `validate_property_feature` checks exact selectors, finite values, units, calculation origin, declared event review, input state, coordinate structure, completed producer, and retained protocol settings. |
| `api/models/ml_task_v2.py` | Closed `ml-task/2.0.0` task and physical protocol models. The information regime is `pre_outcome_normal_state`; missingness is preserved before train-only processing. |
| `api/services/scientific_pending_import.py` | Native-file imports create an **extraction** run/event and pending property; they do not create a verified upstream DFT/DFPT execution or known source-availability witness. |
| `api/services/scientific_result_subject.py` | `capture_result_subject(db, property_id)` returns private, forward-only SQL-canonical text and its exact UTF-8 hash. Reverse consumer additions are not scientific subject identity. |
| `api/services/scientific_result_effects.py` | `resolve_result_status`, `resolve_result_statuses`, and `gate_exact_property_reviews` resolve scoped live effects. Interactive status batches remain at 20; the current public-consumer gate checks up to 200 reviewed targets with one 10-second/16-MiB budget. |
| `scripts/ml_scientific_dataset.py` | Existing bounded offline build/verify workflow and independently supplied pins. The proposed runner should preserve its safe input/output conventions without changing this existing command. |

The current public publication/distribution gates are live consumers of the review overlay. That does not make the existing offline ML v1/v2 compilers live consumers: their already captured artifacts remain reproducible historical objects.

## 3. A separate companion, not a rewritten capsule

Proposed new file: `api/services/ml_feature_review_companion.py`.

Proposed artifact version: `ml-feature-review-companion/1.0.0`. This is a new companion type, not an in-place change to `ml-feature-companion/1.0.0`.

Proposed interfaces:

```python
async def capture_ml_review_companion(
    db, *, base_manifest, expected_base_manifest_sha256,
    source_companion, expected_source_companion_sha256,
) -> dict: ...

def verify_ml_review_companion(
    review_companion, *, base_manifest, expected_base_manifest_sha256,
    source_companion, expected_source_companion_sha256,
    expected_review_companion_sha256,
) -> dict: ...

async def recheck_ml_review_companion(db, *, verified_receipt) -> None: ...
```

These signatures are proposals, not current callable APIs.

### Inventory and bindings

Derive the complete relevant property inventory from actual frozen `ml_example_inputs` plus their explicit result dependencies, including retained run-manifest dependencies. Do not accept a caller-selected list that can omit an inconvenient negative property. Unsupported Tc/RPS review targets must be explicit inventory entries; they must not acquire a fabricated 0067 profile or escape the existing target-leakage checks.

For each relevant property, retain:

- The exact frozen input/target references and original 0054 row hashes.
- The stored decision subject and its original SQL-canonical text/hash, complete canonical request JSON for every required decision, decision records, and exact scope/profile/head/fidelity-dependency identities.
- A separate current subject observation when needed to explain a stale decision; do not substitute it for the original decision basis.
- Explicit unreviewed/no-decision observations and bounded completeness metadata.
- The current reviewer-grant and source-governance observation needed to recompute the captured status, with an observation revision and capture time.
- Only the minimal private actor metadata needed for validation; no user email, credentials, session token, or unrelated account record.

Reuse existing 0067 closed request/profile validation and record hashes. Do not trust a serialized `effective_status` without reconstructing it from the retained inputs. A checksum establishes internal consistency, not independent authentication of the person who supplied an offline package.

The request digest binds the entire original `request_json`, not just the selected
item. Do not crop a twenty-item request and reuse its original digest. Keep the
audit-verification closure separate from the scientific-feature closure: other
items present only to verify a shared request are not feature dependencies,
scientific grouping edges, or independent support. Export admission must
explicitly authorize those complete private audit bytes; the existing
actor-scoped receipt endpoint does not implicitly authorize cross-actor audit
export. If the required complete bytes cannot be admitted, fail capture rather
than manufacturing a hash-preserving redaction.

Source-governance observation must also retain the existing source-companion checks. An unreviewed scope is not permission to ignore a live source hold: the current status resolver deliberately preserves unreviewed policy, so the capture operation must not use that one enum as a substitute for the pre-existing source admission checks.

Capture current observations for the full independent Paper/Work/source-capture
closure of every 0064 binding, even when those sources do not occur in the 0067
subject. The existing `verify_feature_companion` verifies historical source
rows; it does not establish their current governance. The old `_source_rows`
helper queries current lifecycle but raises on a hold. Do not reuse that helper
unchanged for the new negative-observation capture: a verifiable feature-source
hold is valid captured negative data, not automatically a malformed whole
package or a reason to erase an otherwise eligible composition baseline. Missing
or inconsistent mandatory bindings remain verification failures. Preserve the
old source companion's bytes and behavior.

### Two different hash definitions

The 0054 full-row hash and the 0067 SQL-canonical subject/property hash are different protocols. They must not be equated or reconstructed with an ordinary Python JSON serialization that changes numeric representations.

The new verifier needs an explicit versioned projection/binding rule between the frozen row inventory and the scientific fields represented by a subject. Preserve the original SQL text for its SHA. Compare corresponding scientific values losslessly; distinguish a valid captured mismatch (`stale`, with feature withheld) from a malformed or mismatched package (verification error). In particular, a different property UUID, missing row, or substituted source cannot be laundered by assigning a fresh outer digest.

Current event governance fields are excluded from the 0067 scientific projection. Forward `material_claims` governance fields remain in the current projection; changes can conservatively produce `stale`. The new design must reflect this actual policy rather than promise that every governance update always preserves the same subject hash.

### Bounded capture

Start with at most 200 reviewed property targets, explicit complete input enumeration, and a shared bounded byte/time budget; fail closed beyond the limit. Do not silently take the first 200 or reset the byte budget for every 20-item chunk. A larger dataset/export policy requires a separately reviewed bounded batching design.

Capture uses a clean, bounded RR/SERIALIZABLE caller-owned transaction and private operator admission. It must not mutate results, acquire authorization from request JSON, or change the old source bindings. The output is an immutable, independently pinned artifact; no new SQL fact columns are required for this first slice.

## 4. Compiler integration and preservation of fairness

Proposed new paths:

- `api/models/ml_task_v3.py`: closed task version with an explicit `exact_result_review_policy`, initially `negative_only/1.0.0`.
- `api/services/ml_dataset_builder_v3.py`: `build_task_dataset_v3` and an independent full-recompute `verify_task_dataset_v3`.
- `scripts/ml_reviewed_dataset.py`: explicit build/verify command with independent pins for the original capsule, original source companion, new review companion, task, and output bundle.

Reuse stable v1/v2 helpers where they are suitable, but do not edit old compiler/provenance source files simply to insert this hook: those files are part of existing source-pinned reproducibility contracts. Include every new implementation module in the new compiler provenance inventory.

The admission order should be:

1. Verify the original capsule, actual artifact bytes, original source companion, task, and new review companion.
2. Build the full original result/run dependency graph and conservative grouping relations, including dependencies of ultimately excluded optional features.
3. Resolve exact review holds and propagate them through explicit property dependencies. Do not propagate a rejection to an entire material, event, producer run, or sibling property merely because an identity is shared.
4. Apply the unchanged label, source-time, scientific protocol, state, structure, and target-leakage gates, together with the negative review gate.
5. Preserve the independently eligible composition baseline and its base split policy. Rebuild the affected `P`, `S`, and `PS` cohorts and all comparison views from raw admitted data.
6. Refit preprocessing on each view's training partition only. Do not delete columns or rows from a previously standardized dataset and retain its old fitted statistics.

Within the new bundle, paired views must retain the same cohort and split assignments. A new outer task hash legitimately changes assignment receipt hashes; preserving the base split means preserving the partition decision, not pretending that two differently pinned tasks have identical receipts.

A shared reviewer, request, review artifact, or adjudication batch is **not** a scientific Work/sample relation and must not merge experimental groups or count as independent support. Review timestamps are operational metadata, never substitutes for feature public-availability dates.

Valid captured feature holds must not erase an otherwise eligible composition label. Malformed or missing mandatory companion inputs are instead package verification failures; they must not produce a falsely approved training output.

## 5. Why native canaries still cannot be promoted to ML physics

The actual `_pending_rows` implementation currently records:

- `research_runs.run_kind='extraction'`, with `scientific-import-run/1.0.0` input/output manifests.
- `research_events.event_type='extraction'`, `knowledge_origin='Computed'`, and pending event review/validity.
- Unknown upstream execution, pressure, temperature, magnetic field, phase, and phonon treatment; coordinate parsing is not bulk/no-vacuum or state-applicability review.
- A `phonon_min_frequency` obtained from the complete **declared sampled q-point records**, not proof of a full-Brillouin-zone dynamical stability statement.

The v2 physical path instead requires a declared calculation with a compatible completed DFT/DFPT producer, exact `ml-computed-input/1.0.0` and `ml-computed-output/1.0.0` documents, retained settings/protocol content, applicable state/structure, and independently verified source timing.

Neither 0067 extraction fidelity nor the limited `sampled-phonon-minimum-review/1.0.0` proposition supplies these missing facts. The next slice must therefore demonstrate an honest exclusion even after both review scopes are accepted. It must not relabel an extraction run as a calculation, edit a pending event into a broad approval, rewrite old output manifests, fabricate a Paper/Work/0052 witness, or treat an import date as a publication date.

A later positive-admission extension needs a separate explicit upstream-calculation/context/source-time witness contract. If sampled minima are to become a new feature class, their sampling/profile comparability and limitations also need an explicit task/feature definition; the current broad DFT/DFPT feature must not be silently repurposed.

## 6. Offline reproducibility versus live authorization

An old companion and its old output should remain exactly reproducible after a later withdrawal. That reproducibility does not establish current reviewer availability, source rights, scientific acceptance, or authorization to train/export today.

The new offline verifier must keep the authority flags false and label status as **captured at the pinned observation**. A future live training/export operator must compare the exact verified receipt with a fresh bounded observation immediately before its authorized effect. Changed heads, grants, source holds, or scientific bindings must fail closed or require a newly captured companion and rebuild. They must not overwrite the historical artifact.

The existing v1/v2 CLIs do not provide this live adjudication authorization. The new offline command must not imply that it does. No training command, GPU execution, provider upload, automatic public release, or legal/source-rights attestation is part of this slice.

## 7. Implementation sequence

1. Freeze the new companion schema, completeness definition, hash/projection bridge, status-at-capture semantics, and size limits in pure tests.
2. Implement read-only authenticated SQL capture and independent offline verification using genuine 0054/0064/0067 records.
3. Implement the new compiler admission hook and full-recompute verifier; preserve old modules and byte formats.
4. Add the safe offline CLI using independent pins and exclusive bounded output creation.
5. Run actual disposable SQL-to-capsule-to-companion-to-CLI regressions and document exclusions. Treat these synthetic fixtures as technical contract tests, not scientific validation of a real training corpus.

Suggested new test files are `api/tests/test_ml_review_companion.py` and `api/tests/test_ml_reviewed_dataset_sql.py`, plus a dedicated script-safety test file. Reuse, without modifying, `seed_scientific_candidates`, `freeze_scientific_candidates`, and CLI fixture conventions from `api/tests/test_ml_physical_feature_sql.py`. Reuse the native import helpers from `api/tests/test_scientific_pending_import.py` for the still-ineligible canary.

## 8. Required acceptance tests

1. **Exact reproducibility:** actual SQL freeze plus original source companion plus new review companion produces deterministic output; independent verify recomputes the whole bundle. Original frozen rows, file bytes, SPEC, and producer manifests are unchanged.
2. **Same-property binding:** wrong property/event/subject/input pins, duplicate IDs, omitted reviewed targets, partial inventories, and modified request items fail even after recomputing an outer hash.
3. **No truncation:** a genuine inventory with 21 reviewed properties is fully checked; the 21st rejection cannot disappear. Count, cumulative-byte, and total-deadline excess produce explicit unavailable errors.
4. **Exact negative effect:** reject and clarification exclude the selected property and explicitly derived downstream features; unrelated siblings and same-material/run results do not receive an event-wide rejection.
5. **Historical versus current:** accepted review followed by role revocation, source hold, or scientific-row change yields a new held/stale capture. The old artifact remains reproducible but a fresh live receipt recheck fails.
6. **Scoped acceptance:** fidelity alone never becomes scientific acceptance. A scientific acceptance with an obsolete/revoked fidelity dependency cannot authorize a feature. Neither scope bypasses a missing method, state, source-time, or protocol witness.
7. **Real native importer boundary:** actual 0065 pending output followed by both accepted 0067 scopes remains physically ineligible for the current v2-compatible feature policy; its extraction run, original units, raw precision, unknown conditions, and lineage are preserved.
8. **Base cohort survival:** with at least five suitable synthetic base groups, optional review holds preserve eligible composition rows and base partition decisions. Recomputed `C@P`/`CP@P`, `C@S`/`CS@S`, and the four `PS` views remain fair paired comparisons.
9. **Train-only rebuilding:** a review change that alters an optional cohort rebuilds raw views and fitted statistics using only the remaining training rows. Validation/test values do not affect imputation or scaling.
10. **Leakage and time:** Tc-to-lambda-to-renamed-DOS, other superconducting-response ancestors, and non-detection target information remain excluded. Review/import dates never make post-cutoff or unknown-availability features eligible.
11. **No false grouping:** sharing a reviewer, request, or batch does not merge scientific groups or create independent evidence. Existing exact Work/sample/structure and run dependencies remain grouped before optional exclusion.
12. **Operational safety:** read-only capture leaves complete SQL state and epochs unchanged; preview/file verification does not write. CLI rejects aliases, symlinks, overwrite, input-capsule output paths, missing independent pins, and tampered bytes; no network/DB access is attempted by offline verification.

## 9. Completion boundary

This proposal is complete when it yields an independently verified review-aware dataset artifact, explicit exact-property exclusions, fair rebuilt comparison views, and an honest native-import no-go example without changing historical scientific records. It is not complete merely because a new table or an `accepted` flag exists.

It does not claim readiness of a real superconductivity training corpus, physical validation of sampled phonon minima, current legal permission, successful model training, or measured ML performance. Those remain separate scientific and operational gates.
