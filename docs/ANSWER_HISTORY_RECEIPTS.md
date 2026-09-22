# Private saved-answer evidence receipts

Local implementation for RG03 / #69. Schema: `0068_answer_evidence`.
Format: `ask-answer-evidence/1.0.0`. This is not a production migration,
scientific acceptance, source redistribution permission or issue closure.

## What is retained

New authenticated Ask requests save the **final returned answer-time output**,
not a placeholder that asks the user to repeat a numerical query. This includes
the request, ordinary citations, structured extraction results, mixed-query
association dispositions, uncertainty/missingness, abstention, support checks,
input-budget and packing reports, and the recorded retrieval generation.
The complete final response is retained except for live quota and save-status
fields (`remaining`, `guest_remaining`, `history`). Unknown token usage remains
`null`; it is never replaced with zero.

Each selected citation/result is position-bound to its actual retained input.
Generation-backed answers record the generation, historical activation event,
manifest, member/content/vector/source-snapshot hashes and applicable evidence
and extraction revision IDs/hashes. Selection input/grouping checksums are
bounded application observations, not independently authenticated provenance.
Source-snapshot hashes describe catalogue snapshots, not original PDF bytes.

Capture occurs before ORM rollback and provider work. Detached, process-sealed
inputs prevent an outgoing source alias from changing an already captured
reference. Numerical projections are checked against retained raw parent records
and the request **at capture time**. A historical read does not rerun a newer
parser or silently recompute old values.

If a final answer withdraws selected evidence, the receipt contains the final
abstention and no removed source/result identifiers. It does not preserve or
redisclose rejected drafts, unreturned candidates or withheld source excerpts.
Guest requests do not create private history.

## Three different evidence scopes

| Detail scope | Meaning |
| --- | --- |
| `generation_members` | Returned items bind to exact retained immutable generation members and applicable revision records. |
| `legacy_snapshot` | Newly recorded legacy lexical output and checksums, without a generation-member proof. |
| `no_selected_evidence` | An empty result, clarification or withheld answer; no missing inputs are invented. |

Old `ask_history` rows remain unchanged with a NULL receipt marker. They are
`legacy_unpinned`, not retrospectively assigned the current generation. An
existing unpinned history row cannot be upgraded in place to manufacture a
historical receipt. A recorded receipt's existence on the list page does not
mean its entire integrity chain has been checked by that list request.

## Atomic saving and honest failure handling

After producing the final response, Ask closes the previous read transaction.
Saving uses a fresh UTC SERIALIZABLE transaction, a 5-second SQL statement
timeout, a 10-second outer timeout and two non-queued process-local write slots.
The original authentication path is checked again in this transaction, including
current account/session state or the original API key's revocation state. This
does not charge quota or API-key usage a second time.

The history row and receipt insert commit together. PostgreSQL enforces the
new-row marker, matching final fields, complete ordered selection inventory,
actual immutable parent references and checksums. Deferred completeness is
checked at the real outer commit, not just at flush or savepoint release.

`AskResponse.history` has version `ask-history-save/1.0.0`:

- `saved`: the outer commit was acknowledged; includes the history ID and
  receipt checksum.
- `not_saved`: capture, storage, capacity or renewed authorization failed before
  commit; no saved ID/checksum is claimed. The usable answer is still returned.
- `unknown`: commit was attempted but its outcome was not confirmed. The
  original recovery ID is returned without a receipt checksum. No automatic
  retry creates another history entry.
- `not_requested`: no history was requested, including guest requests.

For `unknown`, read the original ID. A verified response proves that record is
present in that read snapshot. A 404 means unavailable to the current owner in
that snapshot; it is not proof that an earlier commit never occurred. Do not
automatically repeat the Ask POST. Cancellation releases the write slot and
session resources without inventing an acknowledgement.

## Owner-only reading

`GET /v1/history` remains paginated and adds a small receipt summary per entry.
It preflights saved-row bytes before hydration (4 MiB/page), never loads the
complete receipt payload for listing, and caps the serialized response at 8 MiB.

`GET /v1/history/{id}` resolves the **current owner session and history in one
read-only REPEATABLE READ snapshot**, with UTC and the same bounded timeouts.
It requires a browser session or bearer JWT; an API key alone cannot read it.
Missing and cross-owner IDs return the same 404 semantics. Success and errors
are private/no-store. The full detail has a 3 MiB serialized bound; each receipt
has a combined 1 MiB budget for its three SQL-canonical JSON texts.

Verification reads the stored SQL text bytes and checks their hashes, native
record checksum, exact generation/activation/member inventory and applicable
retained revision records. It never follows the active generation pointer,
loads mutable Chunk content, invokes an embedding/LLM provider or rewrites an
old answer. Subsequent generation promotion or mutable reingestion therefore
does not substitute different text for a recorded source.

Detail status is `verified`, `legacy_unpinned` or `unavailable`. Unchecked receipts
are not returned as verified data. `historical_integrity_verified` is separate
from the following flags, which remain false:

```text
scientific_acceptance
ml_training_approved
public_release_authorized
currentness_revalidated
```

Two separately labeled, request-time metadata overlays accompany the saved
output: `entry.current_evidence` for original citation source papers, and
`result_current_evidence` for numerical-result source papers. A retraction can
change those current warnings without changing any saved response or checksum.
The overlays do not establish that an old extraction or answer remains valid.

The English dashboard detail displays saved values and association dispositions,
historical pins, and these separate current warnings. Paper links explicitly
open a current paper page, not immutable source bytes. Strict frontend parsers
reject wrong-owner-entry IDs, missing fields and crossed result/source bindings.
Navigation aborts stale private reads; retry is a user-initiated GET, not a new
Ask request.

## Privacy, retention and compatibility

Immutability prevents UPDATE/rebinding and standalone receipt deletion. It does
**not** make private questions a permanent research archive. Owner deletion,
account deletion and the existing 90-day parent-history pruning cascade to the
receipt. Whole-receipt-table TRUNCATE is refused. No retention policy is changed.

The existing account export now explicitly identifies separate receipt access
and includes each history entry's `evidence_receipt_version` and
`evidence_detail_path`. Complete receipts are not silently embedded in an
already potentially large account snapshot; retrieve each owner-only detail
separately before deletion or retention expiry if a local copy is wanted.

Receipts are not complete provider-request archives, deterministic regeneration
packages, signatures, original-document authentication or research releases.
The HTTP envelope contains parsed JSON with server-verified SQL checksums; it
is **not** a standalone byte-for-byte offline-verification package. JavaScript
must not reserialize parsed numeric values and claim to recompute PostgreSQL's
original canonical byte hashes.

The native v1 response-key inventory is closed. Future Ask fields or changed
scientific DTO semantics require explicit receipt-version/read compatibility;
do not silently reinterpret already retained v1 records. Do not amend released
0060–0062/0067 migration semantics to implement this feature.

Schema admission uses the image's exact Alembic head. Apply 0068 only through
the separately authorized [schema rollout procedure](SCHEMA_ROLLOUT.md). The
empty upgrade/downgrade path is reversible; downgrade refuses while any receipt
or marked history row is retained. It must not delete private records merely
to make an application rollback possible. Old rows are not backfilled.

## Acceptance evidence and remaining gates

See the [batch implementation record](reviews/2026-09-05/Priority_Thirty_Eighth_Batch_Implementation_2026-09-09.md)
for actual native tests, migration measurements and desktop/mobile checks.
Synthetic receipts exercise real SQL guards and HTTP routes but are not an
audited scientific benchmark or approval to deploy. The remaining RG03 local
acceptance work includes a retained before/after fixture-migration measurement
report: coverage, truncation/rejection accounting, build/query latency and honest
known/unknown cost fields. An uncontrolled full-production rewrite is neither
needed nor authorized for that disposable-fixture acceptance. Actual provider/ANN
quality-cost measurements, reviewed RAG evaluation and any full-corpus rollout
remain separately scoped operational/research gates.
