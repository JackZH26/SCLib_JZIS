# Proposed next increment: pending scientific import workbench

Date: 2026-09-09. Issues: [ML05 / #67](https://github.com/JackZH26/SCLib_JZIS/issues/67)
and [UX02 / #73](https://github.com/JackZH26/SCLib_JZIS/issues/73).
Status: implementation handoff only; **the workbench and original-key lookup
described here are not implemented**.
Existing contract: [pending scientific imports](../../SCIENTIFIC_PENDING_IMPORTS.md).

Subsequent implementation: the forty-fifth batch implements this workbench and
original-key recovery, including a new pre-start package-pin check. The original
status above records this document's proposal state, not current availability.
See the [operator contract](../../SCIENTIFIC_IMPORT_WORKBENCH.md) for actual
limits, compatibility and deliberate recovery restrictions.

## Evidenced gap

`api/routers/scientific_program_imports.py` already provides actual bounded
program-byte import, exact material binding, preview, explicit submit and
attempt-ID inspection. `services.scientific_pending_import` stores a durable
start before parsing and exposes pending/quarantined/failed outcomes, retained
source bytes, exact package identities and separate import-cost accounting.

The research dashboard currently exposes evidence review, source tasks and RPS
rights, but no corresponding import workbench or shared client calls. A curator
still has to prepare raw API requests. If the initial submit acknowledgement is
lost, the browser may never receive the attempt UUID required by the existing
GET route. The backend already resolves starts by authenticated actor plus
request key; a narrow read-only lookup can expose that recovery without another
write or a new authorization scheme.

## Implementation boundary

Build a private English workbench for the **existing supported phonon importer**:

1. Authenticate current explicit curator capability and inspect the exact
   material binding. Do not infer authority from legacy admin flags.
2. Let the curator explicitly choose the manifest and bounded local source
   files already allowed by the current importer. Match logical names, sizes
   and independently expected hashes; preserve actual bytes without silently
   repairing a manifest, generating coordinates or fetching a URL/path.
3. Show material/version, file inventory and hashes, existing missingness/
   quarantine reasons and the distinction between import cost and calculation
   cost. Do not call a successfully parsed frequency proof of dynamical stability
   over a complete Brillouin zone or of superconductivity.
4. Preview the exact current manifest/context/files, then require a separate
   explicit commit of the same bytes and material binding. Any changed input
   invalidates that preview. Do not automatically resubmit after timeout.
5. Display the durable attempt and current terminal state. `success_pending`
   remains pending review, not a published material property or ML feature.
   Link only actual returned result IDs to the existing evidence-review flow.
6. Recover an uncertain initial response through a current-actor/original-key
   read-only lookup, bound to the exact request/package pin. An observed durable
   start with no terminal and an absent start in this snapshot are different
   states; neither implies rollback, parser completion or an authorized retry.

Use the existing two-stage durable-start/terminal transaction design and recovery
worker rather than collapsing them into a misleading single success response.
Preserve existing append-only attempt/outcome history, package deduplication,
compiler/source pins and freeze guards. A historical grant is not a current
execution grant. Scope outcome lookup to the original authenticated account;
do not broaden access to another curator's private request merely by knowing a
key. Exact old-attempt inspection compatibility must remain deliberate.

The supported limits and schemas remain those of the existing importer:
bounded file inventory, program bytes, optional force-constant sidecar and
versioned manifest/context. Reuse them rather than inventing additional fields
or family coverage for the UI. Account for base64 expansion and browser memory
before reading files; do not create an unbounded in-browser directory upload.

No schema expansion, property-family expansion, DFT/phonopy execution, paid
provider call, actual file upload, scientific review, positive promotion,
publication or model fit is authorized by this design. Implementation tests use
owned synthetic program files and guarded disposable services.

## Minimum acceptance evidence

- Existing real parser/coordinate/phonon provenance tests remain unchanged;
  the workbench uses captured HTTP responses from those actual synthetic paths.
- A new actor/key/request-pin GET recovers a real durable start and later
  terminal without SQL writes; wrong actor/key/pin, missing start, replaced
  grants and revoked sessions are tested with actual database state.
- Real preview retains complete SQL state; exact commit records one attempt
  and the actual retained bytes. Concurrent/repeated requests do not duplicate
  successful imports or bypass failed/quarantined outcomes.
- File/manifest/context mismatch, oversize content, unsafe logical names,
  malformed bytes, changed material binding and source restrictions remain
  explicit errors or quarantine; no automatic input repair qualifies them.
- Desktop/mobile browser checks cover explicit file selection, no automatic
  upload, preview invalidation, one commit, uncertain-response recovery,
  pending/failed/quarantined display, keyboard focus, English defaults and
  private-data clearing on account changes.

This is a concrete interface/recovery increment over existing software, not a
new scientific importer, completed human review or evidence that the whole ML05
issue is ready to close. Remote delivery and actual data/review acceptance remain
separate from local implementation and synthetic tests.
