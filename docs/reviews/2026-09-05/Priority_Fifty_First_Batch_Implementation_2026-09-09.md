# Priority batch 51 — independent Discovery governance workbench

Date: 2026-09-09. Branch: `codex/sclib-research-v2`.
Starting revision: `c482a478492d537071676e997616fa6b7d74710b`.
Issues: [DR04 #77](https://github.com/JackZH26/SCLib_JZIS/issues/77) and
[UX02 #73](https://github.com/JackZH26/SCLib_JZIS/issues/73).

## Outcome

The independent reviewer/publisher handoff following batch 50 is implemented
locally. The new English dashboard separates metadata-only history, current
scientific inspection, explicit native rehearsals, and exact committed actions.
Protective rejection/withdrawal remain usable when a source hold prevents
positive scientific inspection. Nothing turns historical approval into current
publication permission or scientific ground truth.

The [operator guide](../../DISCOVERY_OPERATOR_GOVERNANCE.md) documents the
endpoints, semantics, bounds, reproduction and remaining limits. The existing
Next.js/FastAPI/PostgreSQL architecture, session/grant system, styles and hosting
configuration are preserved. The website skill informed semantic controls,
English accessibility copy, mobile-sized targets and focus handling; no Sites
scaffold, hosting migration, asset generation or new dependency was introduced.

## Implementation

### Metadata that stays readable without exposing old science

`api/services/discovery_operator_history.py` and three new GET routes provide
current requesting operator/grants, exact package headers, all action headers,
and paginated review headers. SQL selects scalar-only subqueries before native
header hashing. It does not fetch full JSON/TOAST bodies or rebuild science.
Other actors' request keys/hashes stay inside native hashing; the responses
exclude source bodies, raw payloads, complete rights assertions and old bundles.

Historical author grants are not required to remain active. The requesting
operator must be currently admitted in the read snapshot. All four authority
flags are false, and publication eligibility is explicitly `not_checked`.
The API does not claim to observe revocations committed after that same
repeatable-read snapshot began.

The whole inventory is verified before each page: at most 1,000 reviews and
two actions, with exact package/payload/selection bindings and account separation.
The history hash covers every header. Reviews use `(created_at, id)` ordering;
pages contain at most 25. Changed history or an absent cursor conflicts and
invalidates the client's incomplete view. No head-selection or hidden truncation
is introduced.

Every rejection remains a hold, including when a later approval exists.
Historical reject records with true confirmation booleans are still retained.
Withdrawal before publication is legal; neither withdrawal nor rejection is
presented as reversible by a subsequent positive action.

### Exact independent operator decisions

`frontend/lib/discovery-governance.ts` validates closed private DTOs, full-history
hashes, exact current payload spans, complete rights files and stable command /
receipt digests. It shares only the existing private bounded transport, not
the public matrix loader. Source quantities retain their original raw spelling.
Command canonicalization is limited to non-floating command metadata.

`DiscoveryGovernanceWorkbench` is mounted at
`/dashboard/research/discovery-governance` with a dashboard navigation entry.
The operator explicitly supplies a projection ID, selects a decision and, when
applicable, an exact independent approved review. No operation, license, review
or confirmation is selected automatically. Positive decisions require complete
history and current scientific content. Protective decisions do not reuse a
retained raw scientific payload when current access fails.

Approval requires complete human-provided rights for the new projection scope
and two explicit confirmations. Choosing/checking a rights file is local;
rehearsing explicitly uploads it. Replacing **or rechecking** the file resets
both confirmations. This fixes the consent carryover found during independent
review: a different license/basis set cannot inherit the previous file's consent.

Every rehearsal/commit refreshes identity/grants and history. Stale history
clears existing content and rehearsal, including when detected before a current
scientific read. The native writer remains the authoritative concurrent guard;
separate HTTP reads are not an atomic history compare-and-swap.

Native rehearsal and final outer transaction durability are distinguished.
Duplicate-click guards prevent repeat dispatch. An ambiguous commit clears
private drafts and locks new writes, retaining only the original opaque locator
in memory. Explicit GET recovery never creates a new key or sends a retry;
404 is not rollback. Authentication changes hide locators, and only the same
actor with a current matching role may recover under a replacement grant.
Reload/navigation loses the in-memory locator; no durable browser queue is claimed.

Focused rehearsal/receipt headings scroll into view with a sticky-header offset;
closing scientific details restores trigger focus. UI-owned dates/numbers and
copy remain English. No live browser/device QA was performed in this batch.

## Actual-wire fixtures, not fabricated scientific data

The guarded native capture retained 55 exact HTTP/request/payload texts and
36 backend source pins under `frontend/tests/fixtures/discovery-governance`.
It exercised actual approval, publication, an owned synthetic source hold,
rejection and withdrawal, including both actors' historical reads and
same-request outcome recovery after the hold. It used one synthetic phonon
result with actual scoped fixture adjudications; this is not a real pilot.

Each file wraps the original text once as a JSON string. The frontend reproduces
all four actual command byte sequences and backend request digests. The external
capture passed in 32.70 seconds. The identical checked-in portable writer was
also run through the guarded runner: **1 passed in 23.88 seconds**. Read,
rehearsal and recovery SQL snapshots stayed unchanged; explicit synthetic commits
created only intended records and existing admission-epoch effects. Only the
runner's own service/test data were removed afterwards. No JWT was retained.

The added backend routes changed a source pin used by the previous selection
fixtures, so all 14 selection wire assets were freshly captured, not merely
rehash-labeled. That portable capture passed in **8.89 seconds**. Batch 50's
original data and provenance remain in its historical commit. One old mutation
test assumed the first randomly ID-sorted property never used kelvin; it now
targets `band_gap` explicitly before substituting an invalid unit.

## Final verification

| Check | Result |
|---|---|
| Guarded API: operator history + projection HTTP + governance + selection preparation | 198 passed, 305.08 s |
| New strict operator client / transport suite | 53 passed |
| New governance component interaction suite | 22 passed |
| Full frontend suite, bounded to two workers | 1,294 passed across 39 files, 79.61 s |
| Frontend source/English/security checks | 38 passed |
| TypeScript `--noEmit --incremental false` | Passed |
| Targeted backend Ruff | Passed |
| Portable operator / selection captures | 1 + 1 passed |
| Isolated production build | Passed; 35 static-generation items |
| Patch whitespace | `git diff --check` passed |

The first unrestricted-worker full frontend run completed 1,293 passes and one
existing layout test exceeded its unchanged five-second limit. The complete
suite was rerun with `--maxWorkers=2` and passed; no timeout was widened and no
assertion skipped. The original API deprecated-regex warning remains unrelated.
The 198 targeted API tests are not a claim that the entire repository API suite
was rerun.

The production build used `/tmp/sclib-governance-build.ox8hqZ/frontend`: an owned
source copy, copy-on-write installed dependencies, unchanged configuration,
`/sclib` base path, the existing offline font fixture and inert API origins.
The new route compiled at 9.74 kB / 139 kB first-load JS. Relevant built source,
configuration and dependency-manifest hashes matched the final worktree. Normal
`.next` and pre-existing development services were not overwritten or started.
These are build results, not measured deployed performance or authenticated QA.

## Open boundaries and next dependency

DR04 #77 and UX02 #73 were freshly read as OPEN in this batch. They remain open;
local synthetic validation is not remote delivery or scientific acceptance.

The next bounded software gap is an **explicit, versioned, curator-declared
main barrier**. The current matrix honestly reports that it was not separately
declared. It must not derive the barrier from the lowest score or first reason.
See the [next-increment design](Discovery_Main_Barrier_Implementation_Design_2026-09-09.md).

There is also no package-leading review index for the new history query.
Returning at most 1,001 rows does not bound full-ledger scan/sort work. The
current 10-second statement / 30-second request limits reject unavailable
work; production-scale performance needs a measured, separately migrated index.

A real reviewed source/rights/scientific pilot, empirical calibration and
authorized issue/PR/release delivery remain separate gates. No push, PR, remote
issue mutation, deployment, production migration/backfill, provider fetch,
real approval, calculation execution or model training was performed. The
persistent upgrade goal remains active.
