# Fiftieth implementation batch — Discovery curator selection workbench

Date: 2026-09-09

Branch: `codex/sclib-research-v2`

Starting revision: `05ecafdcd4bd869b675551182284fb58ccd692aa`

Primary issues: [DR04 #77](https://github.com/JackZH26/SCLib_JZIS/issues/77),
[UX02 #73](https://github.com/JackZH26/SCLib_JZIS/issues/73)

## Outcome and boundary

The existing dashboard now includes an English **Discovery selection** curator
workbench at `/dashboard/research/discovery`. It consumes the forty-ninth
batch's real private selection API and the unchanged native registration API.
The sequence is explicit file inspection, representative choices, complete
scientific preview, native registration rehearsal, explicit registration and
read-only original-request recovery.

This is a local implementation increment, not a deployed site, scientific
approval, reviewed pilot or issue closure. The public scientific acceptance gate
is unchanged. No new database schema, dependency, authentication system or
hosting scaffold was introduced. The existing Next.js/FastAPI architecture and
English interface conventions remain in place.

## Scientific selection and presentation

- Every material starts with an unchosen state/action and an unchosen structure.
  There is no first/highest-score representative default. Explicit null structure
  matches only unbound events, not all structures.
- Native material/state/structure references remain distinct from RPS descriptors
  and assessment IDs. All original assessments remain inspectable, and every
  non-selected assessment is retained as an alternative.
- Every matching result for the selected state and structure is retained. No
  value editor or per-result exclusion control can hide unfavorable quantities.
  Components, signed frequencies, zero values, interval/censoring relations and
  unreported quantities remain intact.
- All eight native registry fields are inspectable. Planned geometry and
  competing-order capabilities remain explicitly unpopulated, rather than
  masquerading as measured fields or policy-score inputs.
- Reported/unknown follows the registered result inventory. Special availability
  declarations require explicit context-matched evidence and a reason code.
  Conflict additionally requires at least two quantified results of the same
  component. Material-family labels are not evidence of applicability.
- A required rationale explains the selected context. Changing the state/action
  or structure clears the old rationale, declaration codes and evidence.
- The full compiled preview includes native observations, current scope-specific
  reviews, source evidence/occurrences, exact pins and all policy contributions.
  The preliminary inventory does not invent current event types or review state.
- Private preparation legitimately accepts zero scientifically accepted results.
  The public parser still independently requires a qualifying accepted scope;
  it does not accept a fabricated public envelope for a private preview.
- The shared disclaimer remains explicit: **Policy-based research priority;
  empirical calibration pending**. Policy scores are not probabilities and can
  only be compared within their frozen campaign/budget/policy/release and
  eligible role/rank group. Nothing is rescored in the browser.

Existing scientific detail and policy components are reused, with private
"prepared" wording and a separate details ID. Tables have captions and column
headers; labeled controls, live status, keyboard focus on expanded scientific
details and focus return on close support the existing accessible UI pattern.
All website-owned text and numeric display remain English.

## Exact bytes, authorization and recovery

The new private client preserves raw UTF-8 response text. Closed schemas,
duplicate-key rejection, finite quantities, exact units and context bindings
remain independently checked. Scientific payload, selection, context and raw
registration commands are SHA-256 verified without reserializing float-bearing
fragments. Original bundle text must match the context pin.

Independent audit found and closed two preview/recovery integrity gaps:

1. Equivalent noncanonical JSON scalar escapes could otherwise produce a client
   request hash different from the backend canonical hash, making a committed
   operation unrecoverable under the retained locator. Known command scalars
   and the integer/string-only selection now require canonical spelling, with
   an adversarial resealed-escape regression.
2. A resealed scientific payload could otherwise relabel a pinned native
   structure from coordinates to prototype. Observation structure kind is now
   compared to the selected context, in addition to the existing ID/hash checks.

File selection does not upload. Inspection and preparation are explicit private
POSTs. Preparation does not count as the native rehearsal; only its actual
verified receipt enables explicit commit. Commands are posted unchanged, and
only successful outer transaction durability is accepted. The rehearsal's
provisional UUID/record hash is not confused with committed identity.

Each operation refreshes curator admission. Commit requires the original actor
and grant, and synchronous in-flight protection prevents double-click writes.
Editing invalidates the prepared payload and rehearsal. Fixed private endpoints,
HttpOnly-session requests, no-store, no redirects, bounded bodies and no retry
remain in force. Pre-aborted requests never dispatch a write; response bodies
are cancelled on failure or completion.

File reads and asynchronous cryptographic verification race an owned deadline.
Timeouts release busy state even if the underlying non-cancellable work stalls.
Epoch checks and abort races prevent late results from restoring private data
after session/page changes. This closes the lifecycle issue found by the
independent interaction audit.

After an ambiguous submitted write, the source file, original bundle text,
context, choices/rationale, compiled payload and commands are cleared. Only
opaque original actor/key/request/payload/selection pins remain in memory, and
new writes stay locked. Recovery uses the original GET, never a new key or
automatic POST. A 404 does not prove rollback. Same-actor regrant may recover;
another account cannot see the retained locator. Navigation/reload loses the
in-memory locator, which the UI explicitly discloses. No browser-stored private
draft or durable cross-page retry queue is introduced.

## Verification

| Check | Final result |
|---|---|
| New strict client / transport tests | 42 passed |
| New workbench interaction tests | 12 passed |
| Existing public scientific matrix regression | 88 passed |
| Full frontend unit/component suite | 1,219 passed across 37 files, 59.68 s |
| Frontend source checks, including English defaults | 38 passed |
| TypeScript, `tsc --noEmit --incremental false` | Passed |
| Isolated production Next.js build | Passed; all 34 static pages generated |
| Final portable actual SQL-to-HTTP capture | 1 passed, 9.72 s |
| Original retained wire / backend provenance | All 14 wire hashes and 36 backend source pins verified |
| Whitespace / patch check | `git diff --check` passed |

The new tests cover explicit null, all-unreviewed private payload, zero/negative
quantities, malformed or resealed contracts, stale/foreign bindings, raw command
preservation, independent rehearsal, duplicate clicks, unknown commits,
404/regrant recovery, hidden foreign-account locators, session/page clearing,
timeouts and late verification results. They do not replace browser/device QA
or an independently reviewed scientific pilot.

The 14 original request/response assets and provenance are checked in under
`frontend/tests/fixtures/discovery-selection`. Each wire file wraps the original
raw text as a JSON string; decoding once reproduces the original byte hash.
The component-only request-key adapter is clearly synthetic and does not
rewrite quantity-bearing text. All scientific data in this fixture are synthetic.

The portable writer is `frontend/tests/fixtures/capture-discovery-selection.py`.
Its exact byte hash is
`77330867abefb9cb44534174b463c1ffc4ca0e4661b5c7bd0c4f9617c92e76c8`.
It differs from the original external capture writer only in the final blank
line. An initial test incorrectly expected byte identity between those two
files; the test now pins the actual portable file without rewriting the
original provenance. The final full suite passes this corrected check.

The portable capture was actually run from its repository path through the
unchanged disposable runner. Only owned PostgreSQL/Redis ports were admitted;
full SQL snapshots remained unchanged for access/context/preparation/rehearsal
and recovery/replay. Commit added one synthetic projection package and existing
admission-epoch effects; it did not add scientific decisions, rights approvals
or publication actions. The runner confirmed cleanup of its own service data.
The pre-existing admin deprecated-regex warning remained.

The production build used `/tmp/sclib-selection-build.iISoTW/frontend`, an
owned source copy with copy-on-write installed dependencies, the unchanged
configuration, `/sclib` base path, an existing offline font fixture and inert
API origins. The new route compiled at 11.6 kB / 135 kB first-load JavaScript;
this is build output, not a production performance measurement. Built main
workbench/client source hashes were checked against the final worktree. Normal
worktree `.next` and existing development services were not used or overwritten.
No live authenticated preview or browser/device visual QA is claimed.

Backend source and schemas did not change. The prior batch's 376 guarded
integration passes remain historical evidence, not a new full API-suite run;
this batch adds the actual portable capture and source-pin verification.
See [the operator guide](../../DISCOVERY_SELECTION_PREPARATION.md) for exact
capture reproduction and boundaries.

## Remaining goal work

Both DR04 #77 and UX02 #73 were freshly read as OPEN during this batch. Neither
is closed by this local interface. The persistent upgrade goal remains active.

The next dependency is independent reviewer/publisher handoff: bounded recorded
package headers, append-only review/action history, explicit exact review IDs
and protective rejection/withdrawal workflows that remain usable after source
holds. Historical metadata must not bypass current scientific-payload admission
or imply that the latest approval supersedes a permanent rejection.

An independently declared main-barrier contract, real source/rights/scientific
pilot, empirical calibration and authorized remote issue/PR/release delivery
remain separate gates. No push, PR, remote issue mutation, deployment,
production migration/backfill, provider fetch, actual calculation, real approval
or model training was performed.
