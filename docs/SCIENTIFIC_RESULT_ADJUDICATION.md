# Exact-result scientific adjudication

Local implementation: migration `0067_scientific_adjudication`, UX02 / #73.
This guide describes the current bounded implementation, not a production
deployment, completed issue, scientific endorsement, or authorization to train.

## What is reviewed

The subject is one original `event_properties.id`, bound to its event revision,
material/state/sample/structure/producer identities and forward evidence.
Decisions are an append-only overlay. They do not update the property, approve
its parent event, clone a result, replace a producer manifest, establish a Tc,
compute RPS, infer superconductivity, or supply missing physical conditions.

Three profiles are implemented, only for `phonon_min_frequency` in `THz`:

| Profile | Scope | Accepted proposition |
|---|---|---|
| `native-sampled-frequency-extraction/1.0.0` | Extraction fidelity | Retained native sampled-frequency minimum agrees with the declared extraction scope |
| `recorded-sampled-frequency-fidelity/1.0.0` | Extraction fidelity | Recorded sampled-frequency minimum agrees with its direct evidence and declared scope |
| `sampled-phonon-minimum-review/1.0.0` | Scientific result | The explicitly sampled minimum is accepted within the reviewed evidence and scope |

Acceptance is not a full-Brillouin-zone dynamical-stability conclusion. It does
not establish upstream execution, convergence, superconductivity, or a pairing
mechanism. A negative sampled frequency is still a negative sampled frequency;
acceptance of the observation does not transform it into a positive stability
signal. A missing temperature or pressure remains missing, not 0 K or ambient.
An extraction run remains an extraction run, even if its knowledge origin is
`Computed`. Other non-Tc/non-RPS quantities can have a subject/context but report
an empty supported-profile list; there is no universal approval fallback.

Every request explicitly retains these limitations:

- `conditions_remain_as_reported`
- `no_automatic_ml_or_publication_authority`
- `not_a_full_zone_stability_assessment`
- `review_does_not_establish_upstream_execution`
- `scope_is_sampled_q_points_only`

## Identities and retained audit data

| Table | Retained content |
|---|---|
| `scientific_result_subjects` | Versioned exact forward snapshot, original property identity, source-byte identities and SQL-defined hashes |
| `scientific_adjudication_requests` | Server-bound actor/grant, unique actor/request key, exact canonical request bytes, private rationale/checks/evidence and whole-request hash |
| `scientific_result_decisions` | Ordered item, subject, scope/profile, decision/reason, exact predecessor and fidelity dependency, actor/grant and decision hash |

All three are immutable against update, deletion and truncate; references use
RESTRICT. Actor identities participate in the existing account-deletion audit
hold. This is a technical integrity constraint, not a legal retention policy.
Administrative de-identification requires a separately reviewed workflow.

Subject hashes are SHA-256 of PostgreSQL's exact returned UTF-8 representation,
not Python reserialization of SQL numbers. A subject's property-row hash is not
interchangeable with a frozen 0054 row pin. A deterministic UUID is a minting
convenience: an already registered, valid SQL UUID4 subject is reused by exact
property/hash identity, not duplicated or rejected because of its UUID version.

The subject follows outgoing relationships. It does not include unrelated
sibling properties, reverse ML consumers or an entire shared source snapshot.
The separate impact snapshot inventories bounded, exact reverse consumers and
is independently pinned at preview/commit. Adding a downstream consumer can
invalidate a preview's impact pin without retroactively changing the scientific
subject. The larger read dossier is not the review subject hash.

Material composition/state association fields belong to the subject. Counters,
display Tc and routine `updated_at` changes do not. Event review/validity,
decision-artifact metadata and governance-only event rehashing are live checks,
not scientific basis. The current forward `material_claims` projection is more
conservative: a claim governance change can make the subject stale. Neither
case silently restores acceptance.

## Reviewer checks and negative decisions

Curators and reviewers can read context. A current active, verified user with an
explicit reviewer grant is required to preview, commit or recover their own
request. Legacy administrator/reviewer flags and publisher grants do not confer
this authority. Actor/grant identity is never accepted from request JSON.

An acceptance requires an explicit source-inspection attestation and all four
checks marked `satisfied`: source match, quantity/units, state association and
method/scope. The reviewer must inspect lawfully available source evidence; the
browser does not deliver source bytes or independently prove that inspection.
The native fidelity profile requires every retained native source file. The
recorded/scientific profiles require verified direct result evidence, not an
arbitrary artifact reachable through an ancestor. Import actors cannot accept
their own native import merely by also holding a reviewer role.

Scientific acceptance additionally references the current accepted fidelity
decision for the exact same subject. Its original reviewer grant must remain
valid. A batch can list fidelity first and science second for the same property;
this is two explicitly declared items, not implied event approval.

Reject and clarification decisions retain their reason and rationale. An
acceptance overriding a same-subject reject/clarification requires a distinct
reviewer and an explicit reference to that current predecessor. Revoking the
author of a negative decision does not erase it or revive an older acceptance.
Source retraction/dispute/exclusion and invalid reviewer/dependency authority
can hold a previously accepted result. Restricted/unknown artifact access alone
does not forbid a private scientific review; it still never grants disclosure.

## Operator sequence and HTTP contracts

Use `/dashboard/research/review`. Select exact results on the current page, then
choose **Load review context**. Selection is explicitly bounded; there is no
whole-library select-all or hidden across-page selection. The side-by-side
dossier, subject, impact and status are captured in the same repeatable-read
transaction, so the displayed evidence belongs to the version being reviewed.

| Method and route under `/v1/ml/scientific-review/adjudication` | Purpose |
|---|---|
| `POST /context` with `{property_ids}` | Read current actor capability and exact result contexts |
| `POST /preview` with the complete request | Rehearse actual SQL insertion and deferred constraints, then roll back all changes |
| `POST /commit` with `{request, expected_preview_sha256}` | Recheck and append the entire explicitly listed request atomically |
| `GET /requests/{request_key}` | Read the current actor's historical receipt without writing or re-submitting |

Versioned responses are `scientific-adjudication-context/1.0.0`,
`scientific-adjudication-preview/1.0.0` and
`scientific-adjudication-receipt/1.0.0`. Requests are
`scientific-result-adjudication/1.0.0`. Each item names its decision/subject/
property, scope/profile, expected subject and impact hashes, predecessor,
decision/reason, private rationale, proposition/limitations, checks, evidence
references, inspection attestation and explicit resolution/fidelity references.
Unknown fields, duplicate JSON keys, nonfinite numbers, implicit defaults and
unknown profiles are rejected. Full details are defined by the closed Python,
SQL and browser validators rather than arbitrary free-form approval metadata.

Preview runs the real guarded write path in a rolled-back savepoint, including
constraint checks and guard epochs. Its hash binds the complete request and
server actor/grant; knowing a hash does not bypass SQL checks. Commit checks the
exact subject, impact and current decision head again. Stale pins or competing
decisions return 409 and require a fresh explicit review. There is no automatic
conflict retry. Reusing the same actor/request key with different bytes fails.
An identical committed request returns its historical receipt without new rows
or epoch changes.

The service deliberately returns `committed=false` before its caller-owned outer
transaction completes. Only the HTTP layer can return `committed=true` after
that commit succeeds. A historical receipt does not assert that its evidence,
reviewer, scientific effect or publication permission remains current now.

If a commit times out or its response is lost, the outcome is **unknown**. Keep
the page open and use the same-key read-only receipt check. Do not create another
request or auto-retry the write. The panel preserves the original request while
recovering and rechecks fresh actor/context afterward. Browser reload/close has
a `beforeunload` warning while pending/unknown; this is not a guaranteed SPA
navigation guard or durable recovery store. No rationale, evidence or token is
persisted in browser storage. Closing/navigating away can still require operator
recovery of the original key from the private audit workflow.

## Transaction and execution boundaries

Writes require serializable isolation, UTC and finite SQL deadlines, using the
existing integrity/publication/lifecycle locks plus an adjudication lock.
Catalogue writers participate in the integrity fence so a concurrent metadata
change cannot be hidden behind an old serializable snapshot. New constraints
check complete item counts, exact item hashes/order and combined subject size.
Incomplete requests cannot commit independently from their decisions.

0067-owned source-writer checks and request-completion checks revalidate complete
requests assembled in the same transaction, including after an explicit early
constraint check. Do not append a review and then mutate its source/impact in
that same transaction. Commit the review transaction first; subsequent legitimate
source updates remain possible and make the prior review stale/held. This is not
a permanent source freeze. Frozen 0054/0064/0065 compiler/guard bodies remain
unchanged; downgrade refuses to discard any retained 0067 audit history.

| Boundary | Limit |
|---|---|
| Explicit request/context items | 1–20; unique property/scope pairs in a request |
| Canonical request | 128 KiB UTF-8; rationale 20–2,000 characters per item |
| Raw commit envelope | 128 KiB + 256 bytes; the inner canonical request remains limited to 128 KiB |
| Evidence references | At most 50 per item and 200 per request |
| Subject | 8 MiB, 1,000 rows, 200 artifacts; 16 MiB across a batch |
| Context/response | 2 MiB; no partial-response truncation |
| Impact | 1,000 rows/query, 2,000 nodes, 4,000 relations, 1 MiB envelope |
| HTTP execution | Four in-flight requests/process, 20-second total deadline, 5-second SQL statements |
| Browser operation | 30-second deadline; commit timeout becomes unknown, never automatic resubmission |
| Public dependency gate | Up to 20,000 candidate IDs and 200 actually reviewed properties; one shared 10-second/16 MiB subject budget |

All responses use private/no-store and nosniff. Errors are sanitized. Oversized
or unverifiable evidence is a failure, never a false empty/unreviewed result.
Explicit research-role admission precedes streaming request-body consumption;
the guarded write path still rechecks current reviewer authority.
Execution limits are safety bounds, not production performance guarantees.

## Current consumers and remaining work

Current result status is a separate two-scope overlay. It can be unreviewed,
accepted, rejected, clarification-required, stale, source-held,
reviewer-unavailable or dependency-review-held. It exposes no rationale/source
bytes and never converts inspection into training or disclosure authorization.

Publication metadata and RPS distribution admission now check exact registered
property dependencies. A current reviewed hold blocks serving, including warm
conditional requests; unreviewed properties retain their existing policy rather
than receiving new approval. Distribution receipts include a private current
scientific-review revision hash for the final fresh authorization check.
Frozen bundle bytes and historical receipts are preserved. Unrelated packages
are not held by a formula-level or event-sibling-wide heuristic.

These are negative-only admission checks. Neither acceptance nor a good source
hash overrides rights, source lifecycle, bundle integrity, publication roles or
dataset admission. All decision responses retain `ml_training_approved=false`
and `public_release_authorized=false`.

Outstanding work includes a versioned review companion and new ML compilation
path that binds reviewed original-result identity without changing the twelve
existing frozen compiler pins; task-specific scientific/feature applicability
and dataset admission; scalable production corpus rehearsal; and separately
authorized delivery. Existing Facts/RAG 0060 data has no exact canonical-property
bridge, so no formula/paper-based invalidation or vector refresh is claimed.
These non-Tc profiles do not alter Tc Timeline records. Wider Tc/claim review
requires an explicit compatible adapter and separate scientific profiles.

## Verification and rollout

Tests use synthetic retained source bytes and synthetic reviewers only. Passing
tests do not assert human scientific review of a real material. Native PostgreSQL
tests run through the guarded disposable runner, never an inherited production
database. The frontend retains an actual synthetic HTTP context/request/preview/
receipt capture in `frontend/tests/fixtures/scientific-adjudication-http.json`;
its IDs and hashes are test evidence, not live scientific records.

Relevant suites: `test_scientific_adjudication*`, `test_scientific_result_subject`,
`test_scientific_result_effects`, `test_scientific_result_public_gates`, existing
publication/distribution/audit-retention regressions and the private workbench
browser tests. Deployment requires coherent schema/API/frontend rollout and the
existing release/schema rehearsal gates. No production migration, real review,
backfill, publication, vector write or remote issue closure is implied here.
