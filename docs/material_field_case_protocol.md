# Private material field cases v1

Additive 0084 ledger. The frozen 0082/0083 source contracts, catalogue values,
resources and publication/ML allowlists remain unchanged. All three tables are
append-only: field targets, pending association revisions, and field attempts.
Receipts live on those rows. All identities remain unestablished, science false,
canonical promotions zero and public release false.

The existing default-disabled `SOURCE_PROPERTY_PENDING_ENABLED` flag and current
JWT/browser session plus explicit curator/reviewer grants govern this namespace.
Curators write; curators and reviewers read. Responses and errors are private,
no-store. No URL is fetched, no source instructions are executed, and no new
account or permission is created.

## Endpoints and closed operations

Base: `/v1/research/material-field-cases`.

* `GET /capabilities`: actor_user_id, session_version, curator_grant_id,
  can_write, field_ids, expression_field_map, outcomes, reason_codes, max_page_size=8,
  max_operation_bytes=32768 and authority flags.
* `GET /context?material_id=...&kind=retained_result&record_index=0`;
  native kinds `tc_claim` and `event_property` use `entity_id` instead.
  Returns target selector, exact context_canonical_json/context_sha256,
  closure, eligibility `{eligible,reason_codes}`. Context hashes are computed
  from the exact SQL canonical text; clients must not reserialize decimals.
* `POST /operations/preview`: `{request}`.
* `POST /operations/commit`: `{request,expected_preview_sha256}`.
* `GET /operations/outcome?request_key=...&expected_request_sha256=...`:
  original actor's receipt; unavailable outcome does not establish rollback.
* `GET /targets?offset=0&limit=8&material_id=...&field_id=...`.
* `GET /targets/{target_id}`: target plus at most eight associations and
  eight attempts, heads first then display clock/id, with bounded returned,
  total and omitted counts.
* `GET /materials/{material_id}?offset=0&limit=8`: eligible target window and
  eligible pending expression associations for an authorized material-detail
  panel. Stale or held proposals return dispositions without expression text.
  Exact private history remains available through target details.

Request envelope has exactly `{version,request_key,operation,payload}`;
version is `material-field-case-operation/1.0.0`, operation is
`target|association|attempt`. request_key uses the existing bounded source
request-key grammar. Payloads:

```json
{"field_id":"tc_kelvin","target":{"kind":"retained_result","material_id":"mat:example","record_index":0,"entity_id":null,"expected_context_sha256":"<64 lowercase hex>"}}
```

```json
{"target_id":"<uuid>","target_sha256":"<sha>","expression_revision_id":"<uuid>","expression_record_sha256":"<sha>","source_identity":{"paper_id":"<existing paper id or null>","work_id":"<existing uuid or null>"},"action":"propose","predecessor":null}
```

```json
{"target_id":"<uuid>","target_sha256":"<sha>","outcome":"source_unavailable","reason_codes":["source_unavailable"],"checked_scope":{"source_ids":[],"fulltext_checked":false,"supplement_checked":false,"scope_label":"Detailed settings unavailable in inspected source"},"expression_pins":[],"predecessor":null}
```

Native target selectors use record_index=null and an existing entity_id.
An association predecessor is `{id,record_sha256}` and identifies the current
proposal head for that target/expression identity; actions `propose|withdraw`.
Attempt predecessors have the same shape and pin the current attempt for the
target. Heads follow predecessor/successor links; finite receipt timestamps
are display metadata outside stable receipt hashes and never select a head.
Each expression pin is `{revision_id,record_sha256}`; at most eight.
At most eight source IDs, sixteen unique reason codes, scope_label <=500
characters. Unsupported keys, floats outside source proofs, duplicate keys,
overlong/invalid identifiers and noncanonical UUID/hash pins are rejected.

Outcomes: `pending_expression_available`, `source_unavailable`,
`not_found_in_checked_scope`, `requires_interpretation`,
`association_unresolved`, `current_source_held`, `target_changed`,
`external_reference_available`, `needs_new_calculation_or_experiment`.
Initial reason codes are the outcome names plus `bounded_scope_only`,
`source_identity_unresolved`, `source_identity_proposed`,
`publication_currentness_unverified`, `publication_rights_unverified`,
`expression_superseded`, `target_fingerprint_changed`,
`material_not_currently_eligible`, `source_lifecycle_held`,
`native_source_binding_unavailable`, `unit_requires_review`,
`value_requires_review`, `different_source_window`, `different_model`,
`sample_state_unestablished`, `no_expression_available`.

Each operation result contains version=`material-field-case/1.0.0`,
receipt_id/receipt_sha256, operation, target_id, actor_user_id,
actor_grant_id/actor_session_version, request_key/request_sha256,
preview_sha256, exact request_canonical_json/preview_canonical_json/
receipt_canonical_json, replayed, dry_run, pending_ledger_written and authority.
The preview includes the future immutable row receipt. Commit requires that
exact preview binding; replay uses the original actor/key/request and original
grant/session receipt. A timeout locks client writes until GET recovery.

List envelopes contain version, actor_user_id, session_version, total, offset,
limit, entries, entries_returned, entries_omitted, next_offset,
response_truncated and authority. next_offset advances by actually returned
entries, including byte-budget trims; null marks the inventory end.
Each entry has id, record_sha256, record_canonical_json, operation, payload, context_canonical_json,
context_sha256, created_at, eligibility and authority. Only target entries
carry context_canonical_json; association/attempt entries use null and pin the
target's context_sha256, avoiding repeated large private closures. Association entries
retain the original immutable row body in record_canonical_json so the original
record SHA binds payload, context and operation proofs; hash that exact UTF-8
string, never a JavaScript decimal reserialization. Association entries
include is_head and expression only when eligible (the unchanged v2 expression
DTO, not retained full text). Attempt entries include is_head. Target detail
adds associations/attempts plus their total, returned and omitted counts and
response_truncated. Adapter replies include actor_user_id, session_version,
material_id, entries and top-level eligibility, plus expressions_returned and
expressions_omitted. The adapter has one shared budget of eight expressions
across all targets; these compact v2 DTOs omit full import receipts. Exact v2
revision endpoints provide full receipt proof separately. Actual canonical
response bytes, including JSON escaping, are bounded below 2 MiB; complete
entries are omitted with counts when necessary, never clipped source proofs.

## Identity, currentness and disclosure

SQL reconstructs exact target closure and source-expression pins independently.
Legacy targets pin the original record index and full bytes representation;
native Tc claims/event properties pin their actual event/state/sample links.
Missing or inconsistent native relationships fail closed. A complete foreign
key closure is identity provenance, not physical sample verification. Native
targets lacking an explicit eligible catalogue occurrence/source binding remain
ineligible for the material adapter with native_source_binding_unavailable.

Source identity is the curator's **proposal**. A matching URL, formula, v2
source_id or declared parent-file hash never makes it a verified publication
identity. Existing paper/accepted Work lifecycle checks can veto a proposed
source, but do not prove that its bytes belong to that paper. Missing source
identity stays unresolved. Fragment integrity, latest expression head and
publication currentness/rights remain separate fields.

Material reads reuse material_view/current_records, inherited holds and exact
current eligible inventory. Distinct windows/models/criteria are parallel
proposals; different numbers do not imply conflict. Fields count official
records, pending expressions, attempts and independent references separately.
No attempt reports an entire paper unreported after a bounded check.
Removal of a retained record or native closure yields
target_fingerprint_changed on immutable private history and suppresses the
associated expression. Controlled closure absence is handled in a SQL
savepoint; other database faults still fail the request.

## Required acceptance cases

Conference YScH6/8/10/12 retains 66/89/94.5/142.7 K and its source windows;
ambient text does not manufacture numerical pressure. Journal 116 K/140 GPa
stays unchanged. Pt onset/zero-resistance and 250 K crystallography stay separate.
Changed target fingerprint/superseded expression/held source suppresses pending
expression display without deleting history. YScH10 lambda_eph/omega_log_k/
mu_star unavailable attempts need no invented expression. Synthetic automated
tests prove contracts and SQL behavior; source inspections and genuine native
acceptance are recorded separately.
