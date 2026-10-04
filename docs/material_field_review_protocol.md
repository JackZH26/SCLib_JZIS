# Private Tc metadata field review v1

`0085_material_field_review` adds exactly two append-only tables: requests and
decisions. `material-field-review/1.0.0` implements the closed profile
`retained-tc-field-fidelity/1.0.0` for `tc_criterion`, `measurement_method`, and
`pressure_gpa`. An accepted private overlay preserves the original retained
record. It accepts one inspected source-scoped field proposition, not the full
Tc claim or physical sample/state/phase identity. Scientific acceptance,
canonical promotions, ML approval and public release authority remain false.

The existing default-off source-property flag and explicit current research
grants apply. Curators and reviewers read; reviewers write. Acceptance requires
an independent reviewer, distinct from the capture/import/target/association
author, all four satisfied checks and explicit source-inspection attestation.
Automated synthetic fixtures do not represent a human scientific review.

## Private endpoints

Base: `/v1/research/material-field-review`. All responses/errors are private,
no-store. No URL is fetched and no supplied instruction is executed.

* `GET /capabilities`: current actor/session/reviewer grant, `can_write`, three
  field IDs, four checks, finite support scope and bounds.
* `GET /context?target_id&field_id&expression_revision_id&component_index`:
  SQL-derived subject, canonical subject text/SHA, and an item template with
  unresolved checks and no inspection attestation. Optional `association_id`
  pins a current proposal. A null association is a direct review selector; it
  does not imply admission of a curator association. `component_kind=value`
  is supported for a standalone method only with `tc_expression_revision_id`
  selecting a current same-capture/full-tuple Tc companion. Default kind is
  `condition`, with exact array index, field and `reported_result_condition`.
  Conditions prohibit a companion; their own parent Tc must match. Standalone
  methods require exactly one matching explicit method condition on the companion;
  a shared paragraph/window alone does not establish measurement identity.
* `POST /operations/preview`: `{request}`; actual guarded SQL writes are rolled
  back, including epoch locks. `POST /operations/commit` adds
  `expected_preview_sha256`; the exact preview is required.
* `GET /operations/outcome?request_key&expected_request_sha256`: original
  actor/key receipt. Unavailable outcome does not establish rollback.
* `GET /targets/{target_id}/history?field_id&offset&limit`: predecessor-defined
  heads first, then display time/ID. At most eight complete rows, with total,
  returned/omitted counts, next offset and byte truncation disclosure.
* `GET /targets/{target_id}/effective?field_id`: current effective head or null.
  `field_fidelity_accepted=true` is possible for a fully closed valid fixture.
  Both the candidate and its exact `effective_value_canonical_json` are returned
  only while effective. Hash the original string against the decision payload's
  `expected_candidate_sha256`; do not reserialize floats in JavaScript.

Request: `{version,profile_version,request_key,items}`; 1–8 distinct
target/field items, 32 KiB canonical request and a bounded wire envelope. Item
keys and nested closed shapes are defined in
`api/services/material_field_review_contract.py`. Each pins target/row/context,
association (or direct selector), source revision/projection, optional companion,
source paper/accepted Work identity, component, subject/candidate/missingness/
tuple hashes, predecessor, decision, checks, inspection, rationale and optional
clarification resolution. Actor/grant/session are server-derived. Accepted
clarification successors must explicitly resolve the preceding clarification.
Receipt IDs are deterministic actor/key identities; decision IDs are request/
item identities. Heads follow predecessor links, never timestamps.

## Independent SQL admission and finite scope

SQL reconstructs complete native original raw records, exact current context and
`(paper_id, legacy_result_id, digest(raw))`. It does not trust submitted Python
eligibility, stored visibility/anomaly envelopes or a rehashed receipt. The
eight derived envelopes are removed only for the legacy ID; full raw bytes remain
bound by the complete digest. Public material DTOs are not native raw proof.

The first supported raw subset is flat canonical scalar data, including ordinary
Pt-like Tc23.0/21.5, `iron_based`, year2009, Hc2=65.0, lattice3.9772/12.988,
doping0.094, confidence0.9/1.0 and its common descriptive fields. All raw numeric
leaves must have canonical decimal representation through six fractional digits,
at most five integer digits, and nonzero float magnitude at least 0.0001. ASCII
raw strings are supported. Exponents, excessive precision/trailing zeros,
Unicode raw hashing, typed proposals, competing numeric aliases, nested lattice
channels, original pressure assertions, numeric legacy zero pressure, ancestry
and populated/malformed compound overrides are finite holds. These holds are
implementation limits, not scientific rejection or source absence.

Frozen family threshold precedence and values are reproduced; broad Tc250,
conservative Tc152, family references, pressure500, hydride low-pressure/Tc,
valid year and nonnegative supported quantities prevent anomaly findings in
this subset. Every record's original governance and supported anomaly inputs
are checked. A clean global material without ancestry can use whole-material
v1 admission, or v2 only when there is an actual negative/tracked source and a
nonempty active partition. Equal Tc in another source never transfers admission.
Latest paper and accepted-Work lifecycle event hashes/snapshots are verified;
every lifecycle revision remains a hold, including after reactivation.

SQL independently verifies capture bytes/metadata, import/entry/row hashes and
reprojects the original spans with the unchanged source-v2 compiler. A namespaced
review helper restores the compiler's integral float `.0` representation for
exact canonical proof comparison; it changes no quantity or grammar. Frozen
unresolved units/values remain holds. Captures require declared currentness and
declared private inspection rights; these declarations plus reviewer checks do
not confer public distribution rights or establish publication/physical identity.

The parent Tc must be a parsed exact same-value K result, without uncertainty or
approximation; formula must match one retained formula span, with no model.
Explicit original observed/computed origin, recognized measurement-method origin,
and experimental/theoretical evidence
must agree with the source projection. Inferred/AI origins, unsupported evidence
roles and explicit nonequilibrium regimes are held. Empty/unknown origin remains
unestablished; it is not inferred from the new field.
Existing method aliases must match the source window before criterion/pressure
can append. Existing method/detail/pressure aliases preclude a missing-field
append; refinement/correction is a different workflow. Original coarse Tc type
is shown separately and must be compatible. Raw source units, uncertainty and
condition spans are preserved; no study extent, synthesis pressure, XRD
temperature or magnetic field becomes Tc pressure.

Effective reads repeat source/target/alias/head/reviewer checks, including current
capture/import/revision/target/association grants and original actor sessions, and use the
existing fresh read epoch/session fence. A namespaced read-only authority predicate reproduces the existing
verified-user/grant/hash/revocation policy without its write-time `FOR SHARE`;
the commit guard retains the original locked reviewer admission. Native API
tests exercise actual read-only GET after accepted commit. Held/superseded input hides effective
values and preserves immutable private history. Lock epoch rows may change on
commit; original materials, source expressions and canonical/scientific/ML
records do not. Downgrade refuses nonempty review history.

The genuine Bi/Mo/Pt preparation packet supplies refusal/clarification cases,
not closed native acceptance. Representative synthetic native positives must
prove actual preview/commit/effective behavior, float/hash parity, source-local
component spans, alias conflicts, v1/v2 partition and independent SQL rejection.

## Private browser review

`/dashboard/research/material-field-review` accepts bounded target, expression
and optional association selectors. A current compatible retained-result proposal
can also preselect its finite field, component kind and unique condition index.
Other scientific fields do not receive this Tc review link. A standalone method
still requires the user to select its exact Tc companion. Loading requires an
explicit action. The
original retained Tc, year and origin remain visible beside the proposed field;
source hashes and policy scope are collapsed disclosures. Printed value precision
is preserved. A separately selected unit is appended once; an inline unit is not
duplicated. The current effective decision and context predecessor must agree
before a new form is shown. All known capture, import, target, association and
companion authors are excluded from accepting their own proposition; SQL repeats
the independent reviewer check on the actual write.

Every save requires a verified exact preview. Before its POST, the browser must
persist and read back a closed actor-scoped `sessionStorage` recovery identity:
actor, original request key/hash, item count and preview/receipt pins only. No
source text, reviewed values, canonical request or draft is retained there.
Unavailable or corrupt storage blocks the write. Unknown outcomes preserve the
identity across route unmounts and actor changes; only the original GET outcome
is allowed, and no POST is retried. Verified commit or outcome clears that actor's
identity. An unavailable outcome remains unresolved. The tab storage lifetime
does not promise recovery after that storage is destroyed.

Private UI values clear on authentication changes and stale responses are fenced.
Another actor cannot display or recover the original actor's identity. Returning
to the original actor restores only the recovery control. Actual synthetic native
DTOs for criterion, condition method, condition pressure and standalone method
are checked directly against the production TypeScript proof validators, including
the original canonical float text. These are protocol fixtures, not accepted
scientific data or production reviews.
