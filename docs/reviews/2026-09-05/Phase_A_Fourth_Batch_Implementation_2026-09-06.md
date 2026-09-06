# SCLib Phase A — Fourth implementation batch

Date: 2026-09-06. Primary issue: [SC03 #48](https://github.com/JackZH26/SCLib_JZIS/issues/48). Tracker: [#41](https://github.com/JackZH26/SCLib_JZIS/issues/41).

Status: local implementation and regression verification, not production rollout or issue closure. Work remains in the pre-existing dirty `codex/sclib-research-v2` worktree, based on `44fd6ce377c89d4b4e1b78dbe082f420c33b8814`. The complete worktree diff includes earlier batches and user changes; it is not this batch's isolated diff. No commit, push, production connection, migration, backfill, deployment, paid extraction or scientific acceptance was performed.

## Outcome

The numeric pipeline no longer turns an operational Tc reference into a measurement or drops a current occurrence merely because its Tc is unusually high or low. Original scientific evidence, anomaly assessment, property-view eligibility and scientific approval are separate concepts.

The counterexample **reported 60 K + legacy 45 K cap** now retains the reported 60 K with a pending finding. It never invents 45 K. A separate eligible source can support a different headline; otherwise that view is null. A positive 0.001 K result is not discarded by an arbitrary minimum.

## Implemented scope

### Shared scientific policy

- `anomaly-review/1.0.0` has byte-identical ingestion and API modules. Findings distinguish parser/format problems, unusual operational values, and conflicting metadata. Every finding has a stable result/rule identity, applicability, affected properties and pending disposition.
- Operational references are explicitly **not physical limits, calibrated probabilities or verified current world records**. Family, origin, same-result pressure and view-specific context are explicit. Unknown family does not inherit a fabricated 45 K ceiling.
- `property-evidence/1.1.0` attaches anomaly assessments to original candidates and prevents affected candidates from becoming selected values. Unaffected properties remain usable as individually sourced observations. Joint EPC eligibility also checks relevant state fields.
- Equivalent-unit aliases agree; conflicting flat/alias or flat/nested-lattice raw channels require review. Cached normalized values are not evidence. A typed original retains precedence over its own compatibility scalar.
- API responses use one explicit UTC evaluation year per context, expose it as `evaluation_year`, and do not silently reuse an old stored evaluation year. Offline audits require an explicit year for reproducibility.
- The new `atomic-anomaly-aggregation/1.0.0` marker distinguishes current view-scoped source selection from old catalogue hints. It is not an approval flag. Legacy untraceable selections remain withheld.

### Ingestion and read surfaces

- Removed the driver 0.01–300 K exclusion, numeric whole-record drops, cap/exact numeric substitution, three-decimal scientific rounding and forced ambient/headline copying. Preserved existing non-numeric source, formula, citation, quality and quarantine policies.
- Numeric legacy overrides become structured review references without copying their free-text notes into public findings. Invalid or unknown references fail closed. Categorical legacy overrides were not granted new scientific authority.
- Materials list, detail, variants and bookmarks project the shared evidence and anomaly summaries. Detail includes annotated retained records and a bounded scientific-allowlist `raw_archive`. The archive is not full text or a complete historical ingestion archive.
- English UI labels explain pending versus no-findings states. No-findings is never labelled verified superconductivity. The compact material layout remains intact; details and retained evidence are expandable.
- Same-result scientific filters use the new policy. An `include_unknown_pressure` option does not waive malformed pressure findings.
- Timeline projection and fallback use the same parser and anomaly rules. Projection schema is version 4; policy changes invalidate compatibility and cache representations. The old database `Tc <= 300` ceiling becomes finite-positive representability, while source-level operational findings determine view eligibility. Phase-diagram points also reject unresolved relevant quantities.
- Pending Timeline mode does not bypass NIMS quarantine or source-level anomaly gates. Full Timeline identity, year-basis and sampling redesign remains SC06; existing legacy material `arxiv_year` values are not silently rewritten by a read projection.

### Nightly audit and proposed corrections

The nightly numeric SQL cap/clamp/delete suggestions have been retired in favor of the shared engine. The audit persists derived findings and can add a review hold; it never overwrites raw records/scalars or clears old governance/quarantine holds. Repeated evaluation is idempotent for a fixed input/context. Numeric report counts describe all currently affected materials, not necessarily newly added flags. Separate legacy governance rules retain their existing count/decision behavior.

`POST/GET /v1/admin/scientific-corrections` supports reviewer/admin-only, append-only **proposed** revisions:

1. Identify an exact retained result and scientific field under the current policy.
2. Require its existing source paper, a bounded locator, a reason, and a representable proposed quantity. Legacy aliases and nested lattice values use the shared accessor.
3. Verify an internal chunk locator belongs to that paper, without retrieving or returning text. Unsupported span locators are rejected. Page/table locators remain reviewer assertions; response metadata says `source_membership_only_not_content_verified`.
4. Store the original and proposed quantity, notation, units, uncertainty interpretation, opaque actor ID and revision predecessor. Row locking serializes competing proposals; a stale predecessor produces 409.
5. PostgreSQL triggers reject UPDATE/DELETE of existing proposals. There is no approve/apply endpoint. A proposed value, including an unusually high but representable one, does not modify the source or release a review hold.

Legacy override notes cannot approve numeric findings or clear numeric legacy flags without evidence. Quarantined materials are rejected by correction and override routes. The existing admin UI labels its remaining action as a legacy override, not scientific validation.

### Schema migration 0049

| Addition/change | Meaning |
| --- | --- |
| `materials.anomaly_context` JSONB | Versioned external family/reference/selection context, not raw self-approval |
| `materials.anomaly_review` JSONB | Recomputable bounded assessment cache; public reads re-evaluate raw evidence |
| `timeline_projection_state.anomaly_policy_version` | Rebuild/read compatibility gate |
| `scientific_correction_proposals` | Source-linked proposed revision ledger, not an accepted-result table |
| Timeline finite-positive Tc check | Representation constraint; no invented scientific ceiling |

Migration 0049 does not rewrite original material records. Downgrade refuses to discard a nonempty correction ledger or reintroduce the old constraint when incompatible projection points exist. Material deletion is restricted while proposals reference it; source and actor IDs are opaque identifiers, not copies of names, emails or licensed text. A controlled retention/erasure procedure must be approved before production use; this guard must not become a workaround for source-deletion obligations.

## Verification

Final frozen-code verification: **1,459 tests passed** (636 API + 643 ingestion + 61 operational-script + 32 frontend source + 87 frontend component/unit). This count does not double-count repeated targeted runs. All DB/Redis operations use the capability-checked disposable native runner; ordinary API pytest against inherited connection settings is prohibited.

| Check | Result |
| --- | --- |
| API full suite | 636 passed; one existing FastAPI `regex` deprecation warning |
| Ingestion full suite | 643 passed |
| Operational-script suite | 61 passed |
| Frontend source tests | 32 passed |
| Frontend component/unit tests | 87 passed |
| Frontend TypeScript and Next production build | Passed; 30/30 static pages |
| Migration 0049 upgrade/rollback guards | Passed: empty database to head; empty-ledger downgrade/upgrade; nonempty-ledger rollback refusal with source and ledger preserved |
| Scoped Ruff and whitespace checks | Passed; unrelated repository lint debt is not claimed fixed |
| API/ingestion independent-image parity | Six scientific modules byte-identical |

The correction endpoint contributes 39 regression cases: permissions, membership, stale identities/policies, uncertainty, no source mutation, supersession/concurrency, DB append-only enforcement and legacy override/quarantine boundaries. Additional surface tests cover raw preservation, low positive Tc, review-required filters/plots, bounded archive output, nightly idempotence and both Timeline quarantine read paths. Pure scientific contracts also test dual-channel conflicts and malformed-reference failure closure.

Reproduce the API and migration checks from the repository root:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server --suite api -- -q

api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server --suite migrations
```

Local macOS/runtime success is not verification of the Linux CI runtime, production latency or a live-data migration. Bounded output still requires evaluating retained input records; production-scale latency, memory and nightly lock duration need measurement before enablement.

## Offline evidence and remaining gates

See [SC03 ingestion implementation](SC03_Ingestion_Anomaly_Implementation_2026-09-06.md), [shared anomaly contract](../../ANOMALY_REVIEW_CONTRACT.md), and [property-evidence contract](../../PROPERTY_EVIDENCE_CONTRACT.md).

Frozen local scientific-module SHA-256 values: anomaly engine `c2ddec80eada58b57f1c692470d0908658e02581185d9ef8283f13050b7dc336`; property-evidence engine `8e3611e8fba4e866469cba423d783a5b21716ad24b0beaf9994a7d2dc2b2a37a`. These identify local files, not a published commit or approved data release.

`SC03_Synthetic_Anomaly_Input_2026-09-06.jsonl` and its impact report are reproducible synthetic fixtures, not a production audit. Six materials contain seven records, all retained by the new numeric path; the replay identifies two former driver drops and one former aggregation drop. Four displayed values change among six supplied comparable fields; 78 fields lack a supplied historical comparison. This does not estimate corpus prevalence or prove scientific validity.

Before rollout:

1. Review the complete local diff and migration, publish a traceable PR/revision, then run compatible staging tests. Keep #48 and #41 open until their review/release gates are met.
2. Obtain an authorized current-source snapshot and run the explicit-year offline impact audit. Existing stored materials may lack compound-reference context until controlled aggregation; the read adapter/audit do not invent that missing context or automatically query free-text override notes.
3. Review changed values, hidden views and reviewer workload before enabling migration, aggregation, audit and Timeline rebuild. Numeric rules are conservative pending-review gates, not empirical calibration.
4. Design accepted adjudication, revision application, retraction propagation and release invalidation separately. Proposals alone do not create accepted ML labels or change frozen datasets.
5. Recover historically discarded records only from authorized, still-available sources after checking corrections, retractions and retention obligations. Never blindly merge obsolete records back into the live catalogue.

Recommended next batch: SC07 shared visibility/hold semantics, followed by SC06 result-identity and explicit-date Timeline redesign. The 60-event evidence pilot and reviewed ML-loader/release work remain separate, unfinished research gates.
