# SC07 — Source reads and frozen export eligibility

Date: 2026-09-06. Scope: local implementation; no production data audit, backfill, source deletion, scientific approval, commit, push or deployment.

## Implemented source-read boundary

`api/services/source_visibility.py` applies `material-visibility/1.0.0` to reported source occurrences on Search, Paper detail and Ask. This is a read-time projection; stored extraction arrays and source text are not overwritten.

- Only an explicit, resolvable `material_id` establishes a material link. The shared material read adapter supplies current anomaly, linked-paper and bounded-parent-chain state. Formula equality, title similarity and textual mentions are **not** identity joins.
- An explicitly linked provenance-quarantined material, including a quarantined ancestor, is omitted from structured public source-occurrence arrays. Its omission is counted without returning its identifier or raw occurrence. This does not quarantine every occurrence or the whole paper.
- Genuinely unlinked occurrences (no material ID, including a null optional ID) remain `unknown`, visibly unreviewed, `public_catalogue_eligible=false` and `scientific_acceptance=false`. They can still match **reported-source-claim** filters. An explicit material ID that is invalid or cannot be resolved is different: its provenance restrictions cannot be established, so the structured occurrence is omitted and cannot match scientific filters. Bibliography and excerpts remain accessible. No formula-based fallback is permitted.
- Explicit linked pending, disputed, corrected, retracted, quarantined or otherwise non-catalogue-eligible occurrences cannot satisfy scientific source filters. Record-specific negative lifecycle, pending and provenance assertions add holds; raw `reviewed=true`, private admin notes and forged visibility payloads cannot remove a hold.
- Malformed explicit review booleans or non-string review/provenance status fields add a pending hold rather than being silently ignored. Existing stronger holds retain precedence.
- Authoritative `Paper.status` corrections, disputes, retractions and withdrawals block scientific matches. Bibliographic Search and Paper detail retain source access with warnings. Search's `exclude_retracted=false` does not override scientific-claim eligibility. Ask excludes these source lifecycle cohorts from synthesis.
- Search result IDs and occurrence indices are computed against the original array before visibility filtering. Sorting by Tc applies the existing anomaly and quantity checks rather than ranking an arbitrary raw maximum.

The scientific filter describes a reported claim, not an accepted finding. A paper's active/published lifecycle state also does not establish scientific validity; an unknown lifecycle state is explicitly warned rather than invented as active.

## Response and RAG semantics

Search and Paper detail add a `source_visibility` envelope and an `occurrence_visibility_summary` (input, returned, omitted counts and state counts). Each retained occurrence has its own `visibility`. Ask includes source visibility and bounded occurrence visibility in citation evidence.

RAG receives separate server-derived visibility metadata and explicit instructions that unlinked/pending/disputed source reports are not approved claims. Untrusted extraction records cannot inject their own visibility envelope into the RAG formatter. The existing untrusted-source JSON boundary and citation checks remain intact. A prompt or a valid citation is not an adjudication guarantee.

Published bibliographic text and excerpts are intentionally preserved. This change prevents structured catalogue reintroduction; it is not a full-text takedown or a source-level licensing authorization system. Licensed-text restrictions and propagation of future source takedowns require a separately reviewed policy. Historical Ask answers remain historical snapshots, not live catalogue decisions.

## Frozen v1 export: deliberate compatibility boundary

`scripts/export_ml_foundation_snapshot.py` remains unchanged. Its `sclib-source-export/v1` egress schema, verifier, manifests and existing hashes are not silently reinterpreted or rewritten.

In v1, `material_scope=public` is a **legacy row filter** (`needs_review=false`, positive source count and the historical NIMS exclusion). It does not establish the new public catalogue policy, source lifecycle validity, or scientifically accepted ML examples. `material_scope=all` is a private source archive and may contain quarantined content. Integrity verification establishes checksums/schema, not scientific approval, rights clearance or training eligibility. Do not label a legacy v1 bundle as SC07-certified.

The new independent `scripts/audit_source_visibility_snapshot.py` evaluates a local snapshot under the current policy without changing any bundle. It reads only explicit file paths and does not connect to PostgreSQL, Redis, external APIs or the website.

```bash
api/.venv/bin/python scripts/audit_source_visibility_snapshot.py \
  --materials /absolute/path/materials.jsonl \
  --papers /absolute/path/papers.jsonl \
  --governance /absolute/path/authorized-governance.jsonl \
  --evaluation-year 2026
```

The separately authorized governance JSONL must have unique material `id` values and these fields for each evaluable material: `needs_review`, `total_papers`, `review_reason`, `status`, `disputed`, `retracted`, `family`, `parent_material_id`, `anomaly_context`. These omitted fields cannot be reconstructed scientifically from a formula or v1 raw records. Missing governance is reported as `undetermined_missing_governance`, not silently considered approved. Parent and source lifecycle holds are retained; absent parent context cannot confer eligibility.

The audit reports input SHA-256 fingerprints, an explicit evaluation year, eligibility transitions from the old public row filter, state/reason counts, and SHA-256 material identifiers for diagnostics. It emits no source text, formulas, free-text reviewer notes or unhashed quarantined identifiers. It always records `database_writes=0`, `scientific_acceptance=false` and `ml_training_eligibility_established=false`. Operator governance files themselves can be sensitive and must remain access-controlled.

Next export work should introduce a separately versioned contract with an explicit eligibility sidecar and pinned source/review context. It must preserve reproducibility and continue separating raw archives from accepted result-level training observations. No export-v2 migration or accepted-training release is claimed in this batch.

## ML Foundation claims read follow-up

The feature-flagged claims readers (`/claims`, `/claims/{id}`, `/materials/{id}/claims`) now apply current material/source/parent visibility and independent claim-validity holds. The feature flag still defaults to disabled. A stored `validity_status=accepted` is preserved as a claim-level database assertion, not relabeled as material approval or ML eligibility; both response envelopes explicitly keep scientific acceptance false.

Default lists require a catalogue-eligible material, no claim/source hold, and the stored claim validity `accepted`. `include_pending=true` explicitly selects Archive results. Retractions additionally require `include_retracted=true`; that legacy parameter alone cannot bypass other holds. Direct claim detail may show an available Archive claim with its exact stored validity and current warnings, but material, ancestor and raw-record provenance quarantine remain inaccessible.

Claims are scanned by UUID keyset until `limit+1` finally eligible responses have been collected, including when more than one initial batch contains only held rows. `has_more` and `next_cursor` therefore reflect post-policy visibility. These are live reads, not a frozen training export: source changes between requests may change eligibility. All three claim read paths are `no-store`. Structured private reviewer fields are removed after typed response conversion to JSON, preserving UUIDs and timestamps.

The read gate does not re-adjudicate the truth of previously accepted claims or release an ML dataset. It preserves the existing claim integrity constraints and adds current visibility checks. A future accepted training release still requires explicit result-level review and snapshot policy.

## Verification

Disposable regression run: **84 tests passed** across source visibility, RAG reliability, scientific filters and frozen v1 exporter integration. Follow-up includes a family-only Tc-sort regression; final whole-batch test totals are recorded in the parent implementation report.

Tests cover inherited parent quarantine, no formula-based identity inference, corrected-paper bibliographic access, scientific-filter suppression despite archive opt-in, original occurrence indices, RAG omission warnings, private visibility-injection resistance, raw-input immutability, missing governance, parent quarantine in offline audits, duplicate identities and deterministic explicit-year evaluation. All examples are synthetic and do not measure production prevalence or linkage coverage.
