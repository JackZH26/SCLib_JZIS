# Independent scientific Discovery governance

Issues: [DR04 / #77](https://github.com/JackZH26/SCLib_JZIS/issues/77) and
[UX02 / #73](https://github.com/JackZH26/SCLib_JZIS/issues/73).
History contract: `discovery-operator-history/1.0.0`.
Write contract remains `discovery-projection-governance/1.0.0`.

## Implemented boundary

The English **Discovery governance** dashboard at
`/dashboard/research/discovery-governance` connects independent selection /
disclosure review and publication actions to the existing native ledger. It
complements [curator selection](DISCOVERY_SELECTION_PREPARATION.md),
[per-property scientific adjudication](SCIENTIFIC_RESULT_ADJUDICATION.md), and
the [public scientific matrix](DISCOVERY_SCIENTIFIC_MATRIX.md).

This upgrade adds private metadata-only reads and an operator UI. It does not
add a schema migration, alter frozen packages, approve real evidence or rights,
change scores, broaden the eight-property registry, or run a public release.
The existing [native projection contract](DISCOVERY_SCIENTIFIC_PROJECTIONS.md)
continues to decide positive admission and protective writes.

Three things remain separate:

| Surface | What it establishes | What it does not establish |
|---|---|---|
| Recorded governance | Exact retained package, review and action headers | Current source eligibility, active historical grants, scientific or public approval |
| Current scientific inspection | A reconstructible source-bound payload at that read snapshot | Ongoing authorization, new scientific acceptance, ML admission |
| Decision rehearsal / commit | Native validation / outer transaction durability for one exact request | Universal superconducting likelihood, calibrated priority, indefinite public availability |

## Narrow history API

All paths below are under `/v1/ml/discovery-projections`.

| Method / path | Query | Bounded response |
|---|---|---|
| `GET /operator/access` | None | 8 KiB: requesting actor and current explicit curator / reviewer / publisher grants |
| `GET /{package_id}/governance` | None | 16 KiB: package header, whole-history hash/counts, all publication actions |
| `GET /{package_id}/reviews` | Optional `after`, `expected_history_sha256` | 128 KiB: the same summary and up to 25 review headers |

Unknown or duplicate query fields are refused. A cursor requires the history
hash; the UI supplies the hash even on its first page. Package IDs are projection
IDs, not original RPS distribution IDs. These routes use the existing active,
verified session and explicit-role admission; legacy admin flags are insufficient.
Any currently admitted research operator may read recorded metadata. Historical
authors' grants need not remain active to inspect what was recorded.

The new read service selects only scalar ledger columns into a subquery before
calling the native header hash. It does not invoke the general full-row helper,
read the retained JSON bodies, or rebuild current scientific content. Returned
headers contain IDs, author/grant IDs, UTC timestamps with six fractional
digits, scope-specific decisions/reasons, and exact record/payload/selection/
rights hashes. Other actors' request keys and request hashes are not transferred
to the application service or returned. Raw source text, full rights assertions,
stored payloads, selections and public bundles are excluded.

The native digest intentionally excludes the JSON documents. This read verifies
**header integrity**, not the inaccessible body bytes. It must never be used as
a historical-payload fallback. A held source can leave history readable while
the separate existing current-inspection endpoint correctly rejects the read.

All four authority indicators are false: `scientific_acceptance`,
`ml_training_approved`, `current_authorization_checked`, and
`public_release_authorized`. Current eligibility is explicitly `not_checked`.
Session/role admission is for the current repeatable-read snapshot only. A
second query inside that same snapshot would not observe a later revocation;
no response-time revocation guarantee is claimed.

## Complete, pinned, append-only history

Before returning any page, the service verifies a complete bounded inventory:
one package, at most 1,000 reviews, and at most two actions. It cross-checks exact
package/payload/selection bindings, independent reviewer identity, and an
approved review with three distinct accounts for every action. More than the
supported inventory fails the whole read; nothing is silently omitted.

Reviews use total chronological order `(created_at, id)`. Actions use `(kind, id)`.
`history_sha256` hashes the version, package, **all** review headers and **all**
action headers, not just the displayed page. A later append invalidates the
old pin; a changed pin or absent cursor returns conflict and the client clears
its history/decision. The browser independently verifies the complete history
hash after the last page and requires completion before a positive decision.
Each additional page requires an explicit click; there is no background sweep.

Reviews do not have a latest-decision head. **Any rejection continues to hold
the package; a later approval does not supersede it.** Historical rejection
records may legitimately have true selection/disclosure booleans; they remain
rejections and are not discarded. New UI rejections deliberately send empty
rights and false confirmation booleans.

There is at most one publish and one withdraw action per package. Withdrawal
may legally be recorded before publication. The present model provides neither
withdrawal reversal nor rejection override. These actions are not UI toggles.

## Explicit decisions and rights

The UI does not preselect an operation, review ID, license, or confirmation.
The operator supplies a lowercase reason code, not private source prose.

| Operation | Current role / separation | Additional client prerequisites |
|---|---|---|
| Approve selection and disclosure | Reviewer distinct from curator | Complete history, exact current scientific inspection, complete new-scope rights file, two explicit confirmations |
| Reject | Reviewer distinct from curator | Exact recorded package pins; no current scientific payload or rights approval required |
| Publish | Publisher distinct from curator and selected reviewer | Explicit exact approved review, complete history, current scientific content with scope-accepted evidence, no reject/withdraw/prior action |
| Withdraw | Publisher distinct from curator and selected reviewer | Explicit exact approved review and package pins, no prior withdrawal; positive current source eligibility is not required |

These are client prerequisites, not replacements for native authorization.
The unchanged write service still revalidates current positive source/role/
rights conditions inside its write transaction. A read/rehearsal is not a lock
or promise that a later commit will succeed. The client's pre-commit history
refresh detects already-visible appends; it does not make separate HTTP calls
an atomic history compare-and-swap. Native constraints remain authoritative.

Approval rights have scope `discovery_scientific_projection`; old distribution
permissions are not inherited. The operator supplies an explicit UTF-8 JSON
array with exactly every current target in unique `dependency_id` order. Each
closed row contains `dependency_id`, `row_sha256`, `license_code`, `basis_code`.
Allowed license codes are `CC0-1.0`, `CC-BY-4.0`, `CC-BY-SA-4.0`, and
`permission-on-file`; these choices are human assertions, not legal conclusions
generated by software. The limit is 8 MiB / 20,000 targets; incomplete, reordered,
extra, duplicate, stale or malformed entries are refused.

Choosing or checking the file is local only. A decision rehearsal explicitly
uploads the assertions to the private API. Replacing **or rechecking** the file
clears both confirmations, which remain disabled until local verification
succeeds. The reviewer then approves the exact representative selection and
disclosure assertions separately. No old file's consent carries forward.

## Exact commands, durability and unknown outcomes

The client computes canonical request digests from closed integer/string/bool
command trees and retains exact preview/commit command bytes. Scientific payload
hashes instead use the original raw JSON span so Python float spellings are not
changed by JavaScript reserialization. Every receipt binds operation, package,
payload, selection and request digests. Rehearsal UUIDs need not match committed
UUIDs. Only outer `committed: true` establishes durability; the native inner
receipt intentionally keeps `committed: false`.

Every rehearsal and commit refreshes the requesting identity/grants and history.
Changing a decision invalidates its rehearsal. Synchronous in-flight guards
prevent duplicate clicks. Existing fixed credentialed, no-store, redirect-error
transport has bounded UTF-8 response reads, chunk limits and a 35-second
deadline; local file/digest work has a 55-second workbench deadline. Late work
cannot restore a cleared generation. The UI uses English numbers/dates,
semantic controls, focus restoration and scrolled-into-view receipt headings.

After dispatch, a lost/malformed acknowledgement is **unknown**, not rollback.
The UI clears scientific content and rights/drafts and locks new writes. It
retains only an opaque original actor / operation / request key / request hash /
package pin locator in memory. Explicit GET-only recovery uses that original
request. A 404 snapshot does not prove rollback or safe retry. Same-account
regrant can recover historical durability; a foreign actor cannot. No write is
automatically replayed and no new request key is manufactured for recovery.

Authentication changes or page hiding clear private material and visible
locators; refresh under the original actor can re-expose its retained locator.
Nothing is saved in browser storage. Navigation/reload loses this in-memory
record; the UI warns operators to preserve opaque references in their approved
private operation record. This is not a durable cross-page operation queue.

## Reproduction and limits

`frontend/tests/fixtures/discovery-governance` contains 55 exact request/response
texts, wrapped once as JSON strings, plus provenance. They were captured through
actual in-process ASGI HTTP backed by guarded disposable PostgreSQL/Redis, with
one synthetic scientifically reviewed phonon result and distinct fixture
accounts. No production approvals or real scientific pilot are represented.
Tests verify all byte hashes, 36 backend source pins, native request hashes, and
both actors' history hashes before/after synthetic approval, publish, material
hold, rejection and withdrawal. Later hold still denies raw inspection.

Reproduce explicitly from the repository root, never using ordinary pytest:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite api -- \
  -p tests.conftest -c pyproject.toml \
  "$PWD/frontend/tests/fixtures/capture-discovery-operators.py" \
  -q -s -p no:cacheprovider
```

The writer admits only owned loopback service ports, writes fixed names
exclusively to a private empty pytest directory, retains no JWT, verifies
unchanged source hashes and read/preview/recovery SQL snapshots, and never
overwrites repository fixtures. The parent runner cleans up only owned service
data. Random fixture IDs/timestamps differ between runs; each run records its
own actual byte hashes. The checked-in writer SHA-256 is
`fb3a1bc844e5b3f7cb077cbb27746874b24fe4ef5d86586577f34bc4265df2c9`.

The review inventory query has **no package-leading review index yet**. A
1,001-row rejection probe bounds returned records, not global scan/sort work.
Existing per-statement 10-second and per-request 30-second ceilings fail closed;
large-ledger latency is not measured here. Measure representative cardinalities
and plan a separate indexed migration before claiming production-scale speed.

An explicit main-barrier declaration, a real reviewed pilot with valid rights,
empirical calibration, browser/device QA and authorized remote delivery remain
separate. Passing these synthetic tests does not close either issue, authorize
deployment, or establish ML training eligibility.
