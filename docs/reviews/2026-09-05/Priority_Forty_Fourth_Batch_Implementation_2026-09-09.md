# Forty-fourth implementation batch — exact RPS rights operator workflow

Date: 2026-09-09. Branch: `codex/sclib-research-v2`.
Baseline: `26c8fd64bbd0a20b9881da8eca089af1144355a8` (forty-third batch).
Issue: [ML07 / #68](https://github.com/JackZH26/SCLib_JZIS/issues/68).
Operator contract: [RPS rights preparation](../../RPS_RIGHTS_PREPARATION.md).
Original handoff: [implementation design](RPS_Rights_Preparation_Implementation_Design_2026-09-09.md).

## Outcome

Added a usable reviewer workflow to prepare one fixed-schema rights artifact
and its existing permission decision for an already registered RPS dependency.
Previously the real HTTP integration fixture needed a direct SQL artifact insert
before calling the permission route. The new positive integration goes through
the actual preparation endpoint instead, then uses the unchanged package review,
third-account publication and protective revocation paths.

The English workbench provides compact dependency pages, exact selected-row
inspection, no-default decision/license fields, explicit preview/commit,
historical receipts and original-request recovery. It does not hydrate the full
20,000-dependency raw projection inventory just to choose a row.

Implementation is additive: two new backend modules plus router registration,
new frontend contracts/component/route, shared client helpers and a dashboard
navigation link. No database migration, historical distribution validator,
role model, ML compiler, capsule format, baseline runner or public admission
policy was changed. No real rights review, source extraction, role grant,
scientific approval, ML training, paid provider call, production write, remote
push, PR, deployment or issue closure was performed.

## Backend behavior and preserved invariants

### Exact intent, real transaction and old validator reuse

`services.research_distribution_rights` binds the authenticated reviewer/grant,
package record/inventory/public-bundle hashes, exact dependency row, predecessor
ID/hash, request key, decision fields and canonical rights-document hash. Random
artifact identifiers and transaction timestamps are not preview anchors.

Preview exercises actual inserts and database constraints, then rolls back the
entire operation and guard epochs. New preview artifacts are not presented as
durable records. Commit requires its independent intent pin, verifies the current
head and dependency projection, creates the restricted artifact and invokes the
unchanged permission service. The existing SQL trigger repeats source-row and
rights checks. A service savepoint is not an outer-commit receipt.

The fixed document is the existing `rps-distribution-rights/1.0.0` object, not
an arbitrary uploaded file. Its bytes and hashes are computed locally from
canonical metadata. The new artifact has restricted access and no URL or
artifact-license assertion. Hash verification means byte verification, not legal
validation of a human rights decision. No source text or credentials are accepted.

### Historical recovery is not fresh authorization

Exact actor/key/intent replay resolves the existing permission before generating
an artifact or comparing the now-advanced head. It returns the same durable
identifiers without additional rows or guard-epoch changes. Changed intent under
the same key and stale heads for new decisions reject. Concurrent same-head
contenders use the existing governance fence rather than forking history.

The dedicated GET outcome query is read-only and scoped to the current reviewer
account plus original key and intent hash. It reconstructs the original grant
and predecessor from retained permission history. A currently authorized
replacement grant may read that account's old receipt without reauthorizing its
decision. Later source/head/live-artifact changes do not erase historical bytes.
An absent receipt in a snapshot is not proof that an in-flight commit rolled back.

Revocation continues to inherit predecessor rights without requiring obsolete
source bytes or renewed positive source eligibility. It can inherit a document
from the older governed workflow. GET and POST both reject attributing an old
externally prepared allow artifact to this new preparation path.

Immutable permission projection bytes are explicitly distinguished from the
mutable live EvidenceArtifact row. Public admission still rechecks the latter,
all required permissions, current sources and the independent publication chain.
The new receipt keeps scientific/ML/current-publication authority false.

### Bounded authenticated interface

The new router reuses disabled-by-default feature gating, authenticated browser
sessions, explicit reviewer grants, fresh session checks, serializable write
fencing, private/no-store responses and the existing nonwaiting process capacity
guard. GET reads use bounded read-only repeatable-read snapshots. Legacy admin
flags never become reviewer grants; the existing model does not have grant expiry.

The wire is closed and defaults to preview. POST is bounded to 8 KiB and 4,096
chunks, with a 10-second body deadline and the existing 30-second operation
deadline. Same-role late account/session changes are independently checked after
body streaming. Error responses do not echo private text or database details.

## Frontend behavior

`/dashboard/research/distributions` extends the existing Next.js dashboard and
English design conventions. It does not introduce another hosting platform,
authentication system, dependency package or public publishing switch.

The page loads 25 compact dependency headers at a time, pins pagination to the
inventory and inspects one exact dependency. A successful selection moves
keyboard focus to the decision heading with a sticky-header scroll offset.
No favorable decision or license is preselected. Editing the decision fields
invalidates the old preview; the explicit commit sends the identical reviewed
body and intent hash. A synchronous guard prevents double-click commits.

Closed client validators check allowed keys, actor/grant, package/dependency/head,
fixed purpose, false authority flags, document semantics and exact recomputed
intent/document hashes before showing a preview or receipt. A preview envelope
is never treated as a durable commit even when replaying an old permission.

Unknown responses lock new decisions. **Check original outcome** is GET-only.
**Retry exact original commit** is a separate deliberate write-capable action,
available only while the complete original in-memory draft remains; it uses
the exact same key/body/pin and is never automatic. Authentication changes clear
private evidence and drafts, retaining only opaque original-account recovery
references. Other accounts cannot see or reuse that recovery context.

The unresolved panel exposes the original references and says to keep the page
open. Full-page unload warnings do not cover every client-side route change;
the approved private operation record remains necessary. No browser persistent
storage, automatic upload, package publication or real rights decision is added.

## Independent review and resolved findings

1. Exact recovery originally had only a write-capable preview/replay route.
   Added a genuinely read-only actor/key/intent outcome endpoint; 404 is not
   interpreted as rollback and GET cannot create artifacts.
2. The first GET implementation could attribute an old allow artifact to the
   new preparation path while POST rejected it. Both now share the same retained
   origin check; protective revoke remains compatible with older documents.
3. Reading the old complete package inventory would unnecessarily expose large
   raw projections to the workbench. Added compact bounded dependency pages and
   selected-row metadata without changing the old operator API.
4. Empty stream chunks could avoid a byte-only request bound. Added the separate
   chunk limit and tests for the actual edge.
5. Long dependency pages could leave the selected form out of view. Added actual
   keyboard focus/scroll with the fixed-header offset and browser assertions.
6. In-memory recovery could be lost on client-side navigation. The UI now warns
   explicitly and exposes opaque original references without persisting private
   payloads in browser storage.

## Verification

Final combined API and frontend checks passed against the frozen sources.
Subsequent edits finalize documentation only.

| Check | Result |
| --- | --- |
| Guarded native API, exact fourteen-module selection below | **536 passed**, 1 existing warning; **469.18 seconds**, exit 0 |
| Complete frontend Vitest regression, one worker | **948 passed** across 33 files, **53.36 seconds**, exit 0 |
| Frontend source regression | **35 passed**, **0.92 seconds** |
| New focused frontend contract/component tests | **81 passed**, **4.14 seconds** |
| Desktop and 390 px Chromium workflows | **4 passed**, **18.5 seconds** |
| TypeScript `--noEmit --incremental false` | Passed |
| Isolated production-mode standalone build, `/sclib` base path | Passed; all 32 static pages generated, new route included |
| New/registered Python sources and tests, Ruff `I,F` | Passed |
| Git whitespace and historical service/schema source preservation | Passed |

The native runner confirmed cleanup of only its owned disposable services and
temporary test data. The warning is the existing FastAPI `regex` deprecation
in `routers/admin.py`. No failed or skipped case is hidden in the final results.

The new native selection contains 42 service/HTTP cases plus 91 independent wire
cases. Earlier focused runs passed 39 actual cases, then four focused additions,
and 91 wire cases; these overlap the final combined run and are not extra
independent coverage. Native tests retain actual source capsules and database
constraints. Boundary spies are explicitly separated from real package admission.

Native checks include full-state/epoch preview equality; actual atomic rights
and permission writes; independent pins; same-key and late-head replay; legacy
origin compatibility; revoked accounts/grants and changed sessions during upload;
deferred commit failure; acknowledgement loss after a durable commit; read-only
unknown/historical recovery; raw-byte drift; and real overlapping transactions
for both null and existing permission heads. The contention tests observe the
actual lock conflict and verify no orphan artifact or forked permission.

The browser fixture is copied from actual guarded synthetic HTTP responses
(`capabilities`, `listing`, `selected`, `request`, `preview`, `committed`,
`outcome`), without credentials or source projections. The browser transport
remaps only its generated request key and derived hashes; it is not a live API
or real rights review. Tests cover desktop/mobile keyboard focus, no horizontal
overflow, no automatic POST, exact commit, unknown 404/GET recovery, explicit
same-intent retry, access denial and safe copy. No external/API escape or page
error was observed. Its owned temporary server was stopped; port 3105 and the
normal worktree `.next` were untouched.

The first isolated build copy omitted the existing Plotly declaration directory;
compilation correctly failed at type checking. After copying those existing
declarations, external dependency symlinks made standalone tracing attempt an
invalid external output path and fail with EACCES. The final isolated build uses
a local copy-on-write clone of the installed dependencies, the actual type
declarations and unchanged build configuration. It passed compilation, types,
static generation and standalone tracing. Neither missing declarations nor
permissions were bypassed. All attempts remained in the owned OS temporary
workspace; original source/dependency/build directories were preserved.

The build uses the existing offline font-response fixture and inert API origins;
it is a production-mode local build check, not a deployable live release, actual
Linux image CI or production-origin verification. Frontend source/tests were
frozen for the final checks. The operator guide documents actual constraints
instead of inferring legal/scientific acceptance from test pass percentages.

Reproduce the combined native selection:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server --suite api -- \
  tests/test_research_distribution_rights.py \
  tests/test_research_distribution_rights_http.py \
  tests/test_research_distribution_rights_wire.py \
  tests/test_research_distribution_workflow.py tests/test_research_distribution_contract.py \
  tests/test_research_distribution_schema.py tests/test_research_distribution_operators.py \
  tests/test_rps_distribution_http.py tests/test_rps_catalog_delivery.py \
  tests/test_research_publication.py tests/test_research_publication_http.py \
  tests/test_research_publication_schema.py tests/test_research_publication_limits.py \
  tests/test_scientific_result_public_gates.py -q --tb=short --show-capture=no
```

From `frontend`, run `pnpm exec vitest run --maxWorkers=1`,
`node --test tests/*.test.mjs`, `pnpm exec tsc --noEmit --incremental false` and
`pnpm exec playwright test --config tests/e2e/distribution-rights.config.ts`.
This API selection is not the complete API suite. No new scripts regression
or production acceptance is claimed in this batch.

## Remaining acceptance and next work

A fresh read-only GitHub check on 2026-09-09 still found **38 review issues OPEN,
0 CLOSED**. ML07's actual scope is reviewed public metadata/structured export;
a general ML-use authorization scheme must not be invented as an additional
requirement merely to close that issue. Actual rights decisions, complete
approved releases, compatibility/release delivery and linked PR evidence remain
separate from this local operator implementation.

ML09 still has no authorized real-dataset execution path, and the real ML08
pilot remains a human/source/data requirement. No local Docker/OrbStack/Podman/
Colima/Lima runtime was found in the bounded read-only EN04 check; no installation
or Linux build was attempted. Actual Linux image acceptance needs an appropriate
runtime or authorized CI, not another layer of synthetic validation.

The next dependency-ready software item is a [private scientific-program import
workbench](Scientific_Import_Workbench_Implementation_Design_2026-09-09.md)
over the existing bounded pending phonon importer, with exact
material/file pins and original-key read-only attempt recovery. It does not
run calculations, expand supported physical properties or promote pending
results. The overall upgrade goal remains active; remote/production and human
acceptance requirements have not been waived.
