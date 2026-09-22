# Exact-result adjudication: implementation proposal

**Status: proposal only; not implemented or enabled.** Prepared 2026-09-08
against HEAD `73afd05` and the current, uncommitted batch-32 read-only review
workbench. This document changes no scientific records, authorization, releases,
or production settings. Migration `0067` below is a proposed next migration, not
an existing schema or an allocated production rollout.

## 1. Decision and scope

Implement an append-only adjudication overlay for one exact
`event_properties` result and its source/state/producer snapshot. Do **not** set
`research_events.review_status='approved'`, approve a material, replace native
output manifests, or copy a property simply to attach an approval.

A reviewer should be able to accept a limited, explicit proposition without
requiring every possible superconductivity descriptor. Conversely, acceptance
of faithful extraction must not become validation of the underlying physics.
The first usable vertical slice is native-file result review, including the
existing pending matdyn frequency results; it does not make those extraction
runs into executed DFT/DFPT calculations.

The live [UX02 issue #73](https://github.com/JackZH26/SCLib_JZIS/issues/73)
requires exact revision decisions, stale-review rejection, role separation,
enumerated batch actions, restricted-source protection and downstream status
changes without frozen-byte mutation. Its dependencies
[#49](https://github.com/JackZH26/SCLib_JZIS/issues/49),
[#66](https://github.com/JackZH26/SCLib_JZIS/issues/66),
[#61](https://github.com/JackZH26/SCLib_JZIS/issues/61) and
[#68](https://github.com/JackZH26/SCLib_JZIS/issues/68) were still open when read
for this proposal. A working non-Tc review endpoint is substantial progress, not
by itself a reason to close all of #73 or those dependencies.

## 2. Existing contracts to preserve

- `models/research_schema_v2.py`: `event_properties` has a UUID, exact parent
  event, registered property/unit, component, relation, value/bounds,
  uncertainty, raw data and record hash. It has **no property-specific review
  status or supersession field**. Tc is confined to `material_claims`; registered
  RPS properties belong to inferred priority-assessment events. Preserve these
  distinctions and every released schema definition.
- `services/scientific_result_dossier.py`: prepares the permitted typed result,
  source hashes and numeric locators beside state/structure/producer metadata.
  Its current descriptor hashes the complete forward closure **and** reverse
  impact inventory. That is a useful preview identity, but an unsuitable sole
  long-lived scientific subject identity: adding a downstream ML reference must
  not automatically invalidate an unchanged scientific result.
  The dossier needs its own traversal policy: include exact
  `snapshot_event_memberships` by each explicitly reached event, but never
  expand a referenced source snapshot into all of its unrelated memberships.
  Preserve snapshot metadata and relevant occurrence rows without importing an
  entire source corpus into a one-result preview. Do not change the frozen
  `0054` traversal to achieve this narrower read.
- `services/scientific_result_impact.py::inspect_result_impact`: bounded,
  explicit reverse references; not a complete transitive dependency graph or a
  refresh-completion receipt. Keep its unsupported-scope disclosure.
- `services/scientific_pending_import.py::_pending_rows`: preserves original
  native bytes and separate extraction input/output manifests, records
  `Computed` origin with an **extraction** producer and pending state, and leaves
  pressure, temperature, phase and upstream execution unresolved.
- `services/ml_feature_provenance_v2.py::computed_lineage`: actual computed
  output manifests pin each original property UUID **and full row SHA**;
  input manifests pin original structures and dependencies. A review-induced
  row edit or cloned output cannot silently retain that proof.
- `services/research_freeze.py` and `research_release_manifest.py`: `0054`
  capsules have a fixed closure contract, independently pinned bytes and
  immutable rows. A processing review is not scientific acceptance. New review
  tables must not be injected into the released v1 manifest format.

## 3. Machine-facing review semantics

Proposed versions: `scientific-result-subject/1.0.0`,
`scientific-result-adjudication/1.0.0`,
`scientific-result-review-status/1.0.0`.

Each decision has a required **scope** and **profile**, not just `approved=true`.

| Scope | Meaning of `accept` | What it cannot establish |
|---|---|---|
| `extraction_fidelity` | The selected quantity, relation, units and explicitly reported/missing conditions faithfully represent the pinned source occurrence | Correctness of the experiment/calculation, upstream execution, a complete Brillouin-zone stability conclusion, or ML eligibility |
| `scientific_result` | A reviewer endorses a stated, profile-bounded scientific proposition and assumptions for that exact result/state/evidence | Universal physical validity, a material-wide label, a different sample/phase, publication rights or permission to train |

Initial explicit profile allowlist:

- `native-sampled-frequency-extraction/1.0.0`: `extraction_fidelity` for the
  complete retained native frequency records and exact unit conversion. Missing
  pressure may remain missing; it is not replaced with ambient pressure.
- `sampled-phonon-minimum-review/1.0.0`: `scientific_result` about the minimum
  over the **declared sampled q-point records**, with exact source and geometry
  associations and explicit method/rounding/convergence qualifications. The
  review cannot assert an executed or converged upstream run if that evidence
  is absent. A request for whole-zone dynamical stability using this profile is
  incompatible and must be refused, not accepted with an invisible caveat.

Other profiles are unsupported until their required checks are implemented;
this is a small reviewed allowlist, not a demand to solve all material families
before the first decision can be recorded. `scientific_result` acceptance also
requires a current accepted `extraction_fidelity` decision for the same subject;
the UI may submit both explicitly in one bounded transaction.

Closed decision enum: `accept | reject | request_clarification`.
Required fields include `reason_code`, a bounded private rationale,
`proposition`, `limitations`, exact evidence references and structured checks
(`source_match`, `quantity_and_units`, `state_association`,
`method_and_scope`). Check states are `satisfied | not_applicable | unresolved`;
the selected profile, not the client, determines which checks may be
`not_applicable` and which must be satisfied for acceptance. Rejection or a
clarification request may truthfully record unresolved checks. No confidence,
citation count, JSON role, or source-embedded instruction chooses the reviewer.

Public/current resolver fields should be closed and small:

```text
version, property_id, subject_sha256, scope, profile_version,
decision_id|null, decision_sha256|null, decision|null,
effective_status, reason_codes[], as_of,
scientific_scope_accepted: bool,
ml_training_approved: false, public_release_authorized: false
```

`effective_status` is one of `unreviewed | accepted | rejected |
clarification_required | stale | source_held | reviewer_unavailable |
dependency_review_held`. Extraction acceptance always has
`scientific_scope_accepted=false`. Never fold these meanings into the legacy
event status or the existing blanket `scientific_acceptance` flags. A local
role check authenticates an account's authorized action; it does not prove the
reviewer's qualifications or independently reproduce the science.

## 4. Proposed 0067 schema and compare-and-swap

Three additive immutable tables are sufficient initially:

1. **`scientific_result_subjects`**: UUID; exact property/event IDs; event
   revision; full target-property hash; subject-policy version; canonical
   scientific-basis snapshot and hash; selected evidence/source pins. Bind
   state/sample, material identity/composition, structure, producer,
   input/output manifests and relevant source-edge rows. Retain complete
   row/byte identities privately. Exclude reverse consumer inventory from the
   subject hash. Define the material identity projection explicitly, excluding
   non-scientific counters, rather than letting a paper-count refresh change
   the review subject.
2. **`scientific_adjudication_requests`**: authenticated actor and exact grant;
   request key; complete canonical item inventory; request hash; item count;
   captured impact hash; DB timestamp. Limit to **20 unique
   `(property_id, scope)` items**, no material-wide selector. Store private
   rationale only in this protected, bounded envelope or a separately pinned
   review artifact; neither is a public disclosure grant.
3. **`scientific_result_decisions`**: request/item identity; subject FK; scope,
   profile, decision, reason; previous decision ID; optional exact
   extraction-decision dependency; server actor/grant; canonical decision hash
   and DB timestamp. Unique successor of each predecessor and one initial
   head per `(property_id, scope)` prevent forks. Index exact target/head
   resolution and subject lookup; actor/grant FKs are `RESTRICT`.

All rows reject update/delete/truncate. SQL guards validate canonical hashes,
actor/grant roles, exact FK relationships, request item completeness, strict
types and predecessor/subject consistency; equivalent raw SQL cannot bypass
the service. The current chain head is derived/indexed, not a client-controlled
mutable approval flag. A new source/result subject extends the same property's
scope chain; an old acceptance remains historical and does not cover the new
subject. Distinct reviewer proposals cannot silently become two current heads.

Request CAS pins:
`expected_subject_sha256`, `expected_previous_decision_id` (including explicit
null), and `expected_impact_sha256`. Recompute all before the first insert.
Impact changes require a fresh preview before committing a decision, but do
not later mark an unchanged scientific subject stale. Same actor/key and exact
body replay returns the original receipt without any row/epoch change; same
key/different body is `409`. Source/state/result/head mismatch is `409`, with no
partial decision and no source text in the error.

Use clean caller-owned `SERIALIZABLE` transactions, UTC, finite SQL deadline,
existing research-integrity/publication fences before a new adjudication fence
(proposed key `670017026`). Audit the common source-lifecycle lock order before
implementation; if that resolver acquires its own fence, it must precede the
new higher fence. Never acquire lower-order locks after the new fence. Dry-run
rolls back the whole operation, including guard epochs and deferred checks.
No provider call or source parsing occurs while holding the write locks.

## 5. Roles, supersession and correction

- Curator: prepares evidence, context corrections and enumerated requests;
  cannot adjudicate through curator authority alone.
- Reviewer: explicit current reviewer grant; active verified account and
  current browser session; can accept/reject/request clarification. For
  imported records, do not allow acceptance by the recorded importing account;
  require a different reviewer. Unknown legacy authorship is disclosed, not
  fabricated independence. Numeric locators alone do not prove that the
  reviewer inspected the source: require an explicit attestation to inspection
  of the pinned artifact through an independently permitted channel. This
  capability does not automatically deliver restricted source bytes.
- Publisher: independently admits a separately reviewed publication package;
  scientific acceptance is never a publication action. Legacy admin/reviewer
  booleans and LLM outputs confer no new capability.

The first batch mode is **all-or-nothing**, preview-first: any stale,
incompatible, unsupported or conflicted item rejects the batch, with per-item
safe reasons. Disjoint targets may succeed independently in separate requests.
Two reviewers racing the same head produce one success and one `409`; the
loser must read the prior decision and explicitly supersede it with a rationale.
For a disputed override, require a distinct reviewer and an explicit
`resolves_decision_id`; do not silently last-write-win scientific disagreement.

**Review is not correction.** Corrected quantity/source/sample/state creates a
new interpretation/result revision and separately audited supersession edge;
it never edits the old frozen fact. A corrected property must not be attached
to an old calculation output that never contained its new UUID/hash. Preserve
the original producer and add a curation/extraction derivation with exact
`event_evidence` input references and new input/output artifacts. For genuine
new computation, retain its genuine new run artifacts. Original `Observed`
claims remain Observed with extraction provenance; copying a row is not a new
independent experiment.

## 6. Freeze and consumer propagation: mandatory integration

Create `scientific-adjudication-companion/1.0.0`, bound to an independently
pinned complete `0054` manifest hash, exact reviewed row hashes, all applicable
decisions and predecessor/dependency inventory, subject/source snapshots, and
actual review bytes. A trusted SQL capture includes the complete applicable
decision inventory; an offline rehash cannot prove that a decision was not
omitted or that a role remains current. As with `0064`, preserve external full
file SHA separately from any internal body hash. Do not change released v1
capsule fields or hashes.

| Actual consumer | Required integration and status behavior |
|---|---|
| Private workbench: `scientific_result_dossier`, `scientific_review` | Show selected-result scope and effective decision separately from parent event status; preserve numeric locator-only access and safe reasons. One sibling's acceptance must leave every other sibling unreviewed. |
| New physical-feature dataset build: `ml_dataset_builder_v2`, `ml_scientific_features::validate_property_feature` | Introduce a new explicitly versioned compiler/profile consuming the companion. Exact property scientific-scope acceptance replaces event-wide review as the review authority for that new path, **not** producer/protocol/state/source-time/leakage gates. Preserve existing compiler reproducibility. Extraction-only acceptance never admits a DFPT feature; imported unknown method/state remains excluded. |
| Existing Tc label path: `ml_dataset_builder::_label_reasons`, `ml_foundation::_claim_response` | No property decision can approve a `material_claims` label. Add a separate exact-claim adapter/profile in a later bounded slice; until then retain current warnings/gates. No blanket `claim_qc` or event update. |
| Prospective/historical freezes: `freeze_research_release`, `append_release_notice` | Preserve original manifest, rows and artifact bytes. New dataset builds capture the new companion and relevant negative decisions. Existing historical capsule remains verifiable; separately authenticated current status/notice explains later rejection or clarification. Do not fabricate release-notice review bytes to auto-publish a notice. |
| RPS delivery: `research_distribution::admitted_distribution`, `prepare_rps_distribution_access`, `recheck_rps_distribution_access`; `discovery_priority` | Resolve exact property dependencies already enumerated in `research_distribution_dependencies`, including frozen capsule references. Negative/clarification/stale/held review removes affected packages from **current eligible serving**, including warm caches and conditional responses. Unrelated packages remain available. Unreviewed/extraction-only status never becomes scientific acceptance. Acceptance does not bypass existing paired pins, rights permissions, independent publisher or source holds. |
| RAG/Search/Ask: `rag_evidence`, `index_retrieval`, `scientific_query_lookup`, `retrieval_currentness::check_selected_sources` | Existing `0060` parents are extraction revisions, not canonical property FKs. Add an explicit reviewed exact-property↔extraction-parent binding before applying this status; never join by formula, paper alone, prose, or hash coincidence. Include matched decision/subject hashes in selection/final-currentness checks. Reject/clarification excludes the **bound derived result** from affirmative numerical/eligible synthesis; original passages may remain as independently permitted contextual evidence, without an acceptance badge. Unmapped native imports remain `not_applicable`, not falsely linked or reviewed. |
| Materials/Timeline: `material_property_projection`, legacy material records and Timeline projections | The first non-Tc overlay has no automatic Tc summary effect. Do not invalidate an entire material or hide independently supported Tc. Any later exact-claim adapter must supply precise affected occurrence/summary identities and its own policy-matrix tests. |

Synchronous read gates provide immediate post-commit safety without waiting for
a background cache job. Optional invalidation jobs are optimization/observability,
not authority. The frozen `0058` source-task action is currently timeline-cache
invalidation only; do not relabel it as general review propagation completion.
Add versioned job support only for actually implemented actions and expose
unknown/unimplemented scope honestly. Historical offline files cannot receive
live status automatically; current serving must use a live companion/status
endpoint, while archival download remains governed by separate explicit policy.

## 7. Minimal implementation sequence and acceptance tests

1. New `models/scientific_adjudication_v1.py`, migration `0067`, closed DTOs,
   pure subject/decision/companion contract, and
   `services/scientific_adjudication.py`. Preview/commit endpoints extend the
   existing private workbench; default preview, no public write route. Preserve
   original bytes and expose scope-specific English labels.
2. Native fixtures: use `tests/test_scientific_pending_import.py::seed_import`
   and the real HTTP preparation in `test_scientific_review_operators.py`.
   Accept/reject/clarify one sampled result; assert unknown pressure stays null,
   negative frequency stays negative, extraction stays extraction, all unrelated
   rows and siblings remain unchanged. Restrict rationale/source content at
   every preview/export depth, even if checksums are recomputed.
3. Genuine concurrent connections: two same-head reviews; source/quantity/
   state/source-edge change after preview; exact replay with full SQL/epoch
   equality; wrong actor/session/revoked grant; all-or-nothing mixed batch;
   deferred constraint failure and outer commit failure. Frozen raw-SQL
   immutability and no-op/nonempty downgrade rehearsal are mandatory.
   A source snapshot with more than 1,000 unrelated memberships must not
   exhaust a small exact-result dossier; an actually oversized relevant closure
   must still fail closed. Unrelated membership changes leave the scientific
   subject unchanged, while selected membership changes invalidate its CAS.
4. Real `0054` capsule plus actual computed-run output: append review, verify
   unchanged original property/run/output/capsule bytes, capture companion and
   rebuild with the new compiler. Verify precise accepted scope, unchanged
   grouping/splits and all existing temporal/leakage gates. Rejection removes
   only affected optional feature membership, not the baseline composition
   cohort. An accepted extraction from `0065` still fails native-DFPT gates.
5. Actual `0063` publication workflow and warm HTTP reads: accepted→clarification
   or reject changes effective serving immediately, leaves historical bytes
   reproducible, returns no stale `304`, and preserves an unrelated package.
   Test real mapped `0060/0062` retrieval plus final recheck after revocation;
   test unmapped and sibling parents cannot inherit either acceptance or holds.

Do not call #73 complete after step 1 alone. The bounded delivery target is a
usable exact-property decision UI **with** freeze/ML/public-delivery integration,
plus explicit supported/unsupported retrieval bindings. Tc-claim workflow and
the remaining dependency acceptance checks retain their own completion gates.
No real expert decisions, legal permissions, deployment, paid calculation,
production backfill, or scientific training approval are created by this design.
