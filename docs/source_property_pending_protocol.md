# Pending source properties: initial closed backend

This additive interface stores source expressions separately from retained
material results. It does not write `materials`, Tc claims, scientific events,
sample/state associations, source holds or canonical property tables. Its
source-expression notes are not scientific acceptance, publication permission,
human identity verification or training rights.

`SOURCE_PROPERTY_PENDING_ENABLED` defaults to `false`. Enabling it exposes only
private JWT/browser-session endpoints under `/v1/research/source-properties`;
every response, including errors and downloads, is `private, no-store`.
Existing active, verified accounts need an explicit current `curator` grant
for import or `reviewer` grant for source-note appends. Legacy admin/reviewer
flags and self-declared request roles do not admit these actions. No new grant
or account is created by this implementation. Cookie writes keep the existing
Origin and session-version checks.

## Initial input scope

Only the exact bytes of the two existing published metadata snapshots are
accepted. The backend receives canonical base64 bytes; it does not fetch URLs,
read client paths, execute source instructions or receive original full text.
No duplicate API resource or new metadata fixture is packaged.

| Existing public JSON | Exact bytes SHA256 | Original source batch SHA256 | Task/expression/unavailable counts |
|---|---|---|---|
| `materials-source-observations-2026-10-02.json` | `ac144451b2f03ca2e0e3dbd9ec27748e8257e1cac86473f384d6e5c34ea5f43e` | `947e13d7947f27d9d291a3783ad262308babcec14c186de0e5fbf1c70b8a884f` | 15 / 15 / 0 |
| `materials-source-followup-2026-10-02.json` | `c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8` | `af823526b7c2764c75c116c2d42e48fde3746feac8e5d6635fecaa34f7a41615` | 34 / 31 / 3 |

These are 49 source tasks, 46 non-null source expressions and 3 unavailable
sources. Typed quantities also include repeated nominal subject parameters and
conditions; their component count is not an experiment or new-property count.
Unknown sources/uploads/field profiles and altered source bytes are rejected,
even if their own submitted hashes agree. Byte identity proves snapshot
identity; it does not prove scientific truth or current publication status.

The finite field registry retains source subjects and windows separately,
including nominal/refined composition differences, model/fit/measurement roles,
raw values and uncertainty, printed unit conflicts, implicit field/guide unit
bases, source hashes and exact entry/component JSON pointers. London penetration
depth is not electron–phonon coupling; pressure study extent is not a Tc
condition. Declared CIF sites/operations remain unvalidated source metadata.
All projected properties remain `pending`, with unestablished selected-result,
sample and phase relationships. `display_context_material_id` is null.
Original snapshot authority flags, including `database_changed: false`, describe
the source batch's original preparation scope. Generated projection authority
explicitly carries `scope: source_preparation`; it is not a live transaction
result. Import and note responses separately report `pending_ledger_written`:
false for a new rolled-back preview, true for a successful commit or replay of
an existing receipt. Successful imports append the new private pending ledger.

## Transactions and endpoints

Three independent append-only tables retain import receipts, initial
observation revisions and source-expression review appends. Authenticated actor,
grant and session version are derived from the caller. Services and PostgreSQL
guards require live authority, exact source/projection hashes, finite profiles,
source JSON pointer equality and a complete inventory committed atomically.
The SQL projection independently rebuilds typed components from the exact
received metadata and the finite registry; these checks verify faithful
transcription, not scientific interpretation. UPDATE, DELETE and TRUNCATE are
blocked. Account identity foreign keys and retention checks prevent audit
history from silently losing its actor. Non-empty downgrade is refused.

| Endpoint | Meaning |
|---|---|
| `GET /capabilities` | Current curator/reviewer capabilities; no grant creation |
| `POST /imports/preview` | `{request_key, source_bytes_base64}`; actual SERIALIZABLE SQL rehearsal, then savepoint rollback |
| `POST /imports/commit` | Same input plus `expected_preview_sha256`; exact live actor/grant/session-bound preview required |
| `GET /imports/outcome` | Original actor's `request_key` and `expected_request_sha256`; absence means unavailable outcome, not proof of failure |
| `GET /observations` | Consistent private pagination, field/profile/source-role filters; counts refer to source task observations |
| `GET /observations/{id}` or `/download` | Exact pending revision, original/projection hashes and bounded private source-note history |
| `POST /reviews/preview` | `{request}`; actual SQL source-note rehearsal, rolled back |
| `POST /reviews/commit` | `{request, expected_preview_sha256}`; append-only source note |
| `GET /reviews/outcome` | Original review actor's exact key/request hash |

Import keys are unique per actor and source snapshots globally unique. Replaying
the same request returns its original receipt without additional rows or epoch
changes; a changed request, source pin, grant/session-bound preview or review
head conflicts. The outer request owns its transaction; savepoints roll back
all rehearsal writes, including existing role-lock epochs. A timeout or lost
response does not imply rollback: query the original key before retrying it.
New previews bind the current actor, grant and session. Historical replay and
outcome lookup require the original actor to retain a current active role, but
preserve the receipt's historical grant/session rather than re-authorizing the
old operation as a new write. An existing replay can omit `dry_run`; its
`replayed: true` and `pending_ledger_written: true` identify the saved receipt.

A review request binds one exact observation hash and previous review ID/hash,
and includes `scope: source_expression_fidelity_note`, bounded `checks`, a
private note and explicit `source_inspection_attested: true`. Actions are
`matches_inspected_source`, `requires_clarification`, `source_mismatch` and
`withdraw_note`. A reviewer declaration is recorded as that actor's assertion;
the server does not infer a human inspection from roles, AI checks or CI.
Withdrawing requires the current preceding note to belong to the same actor
and to be a non-withdrawal note. It appends a withdrawal of that actor's own
preceding note; it cannot erase another reviewer's opinion, rewrite source
values or clear a source hold. Other reviewers may append their own differing
source-expression notes. All observations remain pending after every action.

## Deliberate remaining work

This first backend admits initial revisions of the two fixed snapshots only.
The 0082/model-v1 SQL replay hard-pins registry SHA256
`021e7bcbf53bb43afd2116dfd6ce750270a1d23aeca5e1d8283f1d6de4eb316e`.
The initial `source_property_contract.py` is an immutable v1 registry/mapper:
future fields require a separate contract-v2 module, additive migration and new
SQL function namespace, rather than modifying or replacing this replay contract.
It does not yet import arbitrary newly captured sources, register amended
source-expression revisions, establish physical subject/state relationships,
scientifically approve properties or publish newly uploaded private content.
Those flows need additive field-specific source/revision contracts and their
own review and disclosure rules. The existing two public snapshots and all
historical receipts remain immutable; this interface does not replace them.

Private queries use a consistent transaction and no cross-request catalogue
cache. The new tables are not silently added to old research release, public
distribution or ML allowlists. A later material-detail adapter must preserve
the existing eligible-source/actual snapshot guards; independent historical
source references do not reinstate disputed or held material records.

## Private source workbench

The existing authenticated dashboard links to
`/dashboard/research/source-properties`. Its current capabilities come from the
private API and are bound to the dashboard account; a navigation link does not
grant access or enable the default-disabled interface. The workbench supports
the two fixed snapshots above, bounded record pagination and type filtering,
source values, subjects, conditions, exact locators and private record downloads.
Large coordinate and operation lists and provenance remain behind disclosures.

Import and source-note actions have separate preview and explicit save controls.
The source-inspection attestation starts unchecked; the interface does not
declare an inspection on behalf of a reviewer. Withdrawing appends a note about
the current actor's own preceding note and retains all earlier history.

Session changes clear private response state and cancel pending reads. An
unverified write response locks further writes and retains the original actor,
request key and request/preview hashes for a GET-only outcome check. Review
recovery also binds the source-note digest already verified during preview.
The interface never automatically resubmits a write. This recovery identity is
held in the current browser component; it is not a durable offline queue.
Downloads re-fetch and validate the current private record before creating a
temporary local Blob URL. The public snapshots and their original download
bytes remain unchanged.
