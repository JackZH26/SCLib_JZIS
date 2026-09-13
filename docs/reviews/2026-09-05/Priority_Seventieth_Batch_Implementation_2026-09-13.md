# Batch70 — private ML08 participant workbench

Date: 2026-09-13. Base commit: `634265d7cd2323a077045d4042ee8dbdabe86f19`,
branch `codex/sclib-research-v2`. Batch68/69 worktree changes are preserved.
This batch implements participant interaction, not a completed scientific pilot
or a production rollout. A fresh read of ML08 #54 still found it open.

## Delivered scope

- English **Dashboard → ML pilot participation** at
  `/dashboard/research/ml-pilots`, wired into dashboard navigation.
- Exact private invitation inspection by registration UUID and record hash.
  The registrar sees the roster but cannot act for another account; participants
  see only their own binding/head plus server-reported aggregate counts.
- Explicit accept/decline/withdraw selection, nonsensitive reason code and
  reviewed-consent checkbox. Acceptance requires original selection/protocol
  files, each at most 8 MiB, with local raw-byte hash checks before upload and
  independent server document validation. Original file bytes are not rebuilt
  from parsed JSON. Decline/withdrawal require no source upload.
- Fresh account admission and invitation inspection before preview. A changed
  predecessor or role/policy state clears consent instead of silently applying
  it to a new head. Explicit commit preserves the exact preview input/key/hash
  and rechecks account identity; server concurrency checks remain authoritative.
- Original-key, read-only recovery after an uncertain commit. No automatic
  write retry, replacement key or file re-upload. An absent receipt is not
  treated as rollback; new writes remain locked. Manual recovery supports an
  earlier operation without source files or an active reviewer grant.
- Auth-change/refresh clearing, abort and late-response invalidation,
  synchronous duplicate-click protection and no browser-persisted private
  files/drafts/recovery data. Unresolved references are retained only in page
  memory and redisplayed only under the original account. Browser unload warns
  about unresolved state; a reload still requires independently retained refs.
- Bounded private transport: fixed routes, cookie authentication, no-store,
  redirect refusal, upload/response limits, strict UTF-8, stalled-operation
  timeouts and cancellation. Error bodies are not exposed to the UI.

The only new API operation is `GET /v1/ml/pilots/participant-access`, behind the
existing default-off feature flag. It checks an active account in a private,
read-only transaction without creating or requiring a reviewer role. Exact
invitation ownership remains a separate check. This preserves decline and
withdrawal access after reviewer-role revocation. No schema, worker, scientific
policy, real-account grants or feature enablement changes are introduced here.

The [operator contract](../../ML_PILOT_REGISTRATION.md) includes the page's
workflow and boundaries. Registrar creation remains API-only. Independent
scientific signoff and the real 60-event reviewed pilot are not implemented by
an account's agreement to participate.

## Scientific and evidence boundaries

Account-participation readiness is a current snapshot, not scientific review
completion, source permission, verified human identity/independence or ML run
authorization. A recovered acceptance is a historical receipt and cannot set
current readiness after withdrawal, revocation or policy changes.

The browser verifies closed shapes, non-authority flags, canonical hashes and
visible record relationships. A redacted participant projection cannot
reconstruct the hidden full registration or other participants' decisions.
Hashes provide consistency, not external signatures or source licences.

All test events, documents and accounts are synthetic. Native tests execute
actual owned PostgreSQL, authenticated HTTP and the installed document worker.
Browser/component adapters explicitly reseal synthetic replies around fresh UI
request keys; they are not additional native receipts or human review evidence.

## Verification

Recovered network-interruption state had no live prior test process or
recoverable terminal result. The old capture existed, but was not counted as a
passing run. The owned runner was invoked again, without reusing test services.

| Check | Actual result |
| --- | --- |
| Resumed participant/API HTTP checks | 11 passed, 13.08s |
| Final registration/HTTP/reliability/participant/audit-retention checks | 60 passed, 56.71s |
| Separate existing run/rights/Discovery native capture | 3 passed, 76.63s |
| New protocol, transport and participant component tests | 105 passed in 3 files, 4.92s |
| English/default/source checks | 38 passed, 1.75s |
| Nonincremental TypeScript check | Passed |
| Desktop/mobile participant browser suite | 6 passed, 30.7s |
| Full frontend regression | 1,692 passed in 48 files, 45.29s |
| Existing ML run browser suite with refreshed fixture | 4 passed, 36.8s |
| Existing ML rights browser suite with refreshed fixture | 4 passed, 27.2s |

Counts overlap: the 11 resumed API checks are included in the 60-case run;
targeted frontend tests are included in the full frontend run. They must not be
added as independent tests. API runs retain the pre-existing FastAPI `regex`
deprecation warning. The owned runner verified cleanup after every API run.
Final scoped Ruff checks and formatting checks passed, as did
`git diff --check`. All 110 local Markdown links in the four changed current
contract/report/index documents resolved. A separate final check verified all
2,012 overlapping source pins across the four new interface captures.

New checks exercise original native account/owner projections, accept/decline/
withdraw sequences, grant revocation, historical acceptance recovery, invalid
hashes/roles/chronology/authority declarations, tampered and oversized files,
two exact 8 MiB inputs, stalled streams/file reads, session changes, late replies,
changed heads, consent invalidation, manual recovery and duplicate commits.

### Honest corrections during verification

- The resumed TypeScript check found a string-index type error in the unfinished
  file-upload validator. A literal-key tuple fixes it without changing bounds.
- The first protocol run had 56 passing cases and one incorrect test count:
  the native capture contains 21 response strings, not the assumed 24. The
  assertion now matches the enumerated actual capture; no receipt was changed.
- A deep equality assertion over two 8 MiB buffers exceeded the test timeout.
  It now uses exact bytewise `Buffer.equals`, with unchanged inputs and unchanged
  timeout. The complete targeted run then passed.
- The first browser run passed four cases and failed two on Playwright's
  generic disabled matcher for native `<option disabled>`. The logged DOM
  already had the required property. The assertion now checks the actual
  `disabled` DOM property, with unchanged application behavior. The full
  six-case rerun passed, including real browser withdrawal interaction.

### Visual inspection

The isolated harness copied source into a fresh temporary workspace, linked
already installed dependencies, used mocked offline fonts and routed only to
synthetic local API responses. It did not use production APIs, install packages
or alter the normal frontend build directory. Service workers were blocked.

Desktop 1440×1000 and mobile 390×844 checks covered keyboard focus below the
fixed header, horizontal bounds, exact-file preview, lost-reply recovery,
withdrawal after revoked roles and auth-change clearing. The mobile inspection
and preview, plus desktop recovered state, were opened and visually reviewed.
No horizontal overflow or unexpected external/API requests were observed.

Final screenshots are in the local temporary artifact directory
`/var/folders/m0/ztnj2ywn613cqhtb3_ym0xyc0000gn/T/sclib-ml-pilot-browser-artifacts-whhhZ7`.
The isolated preview listener on `127.0.0.1:32064` was confirmed stopped.
After the existing run/rights browser suites completed, their separate listeners
on ports 32062 and 32060 were also absent. No owned test, TypeScript check or
isolated preview process remained running at handoff.
This is development-browser verification, not a production build or deployment.

## Immutable native interface captures

New files were copied byte-for-byte from owned-run captures. Earlier batch
archives and their raw digest assertions are retained unchanged. Current
consumers now use batch70 rather than claiming old source pins match new code.

| Fixture in `frontend/tests/fixtures` | Bytes | Source pins | Original response strings | Raw SHA-256 |
| --- | ---: | ---: | ---: | --- |
| `ml-pilot-participant-native.batch70.wire.json` | 153,301 | 576 | 21 | `9ebb1a84f28cf713030b8a72fc5749b8a7d036237e8a01dd49216630635994ef` |
| `ml-use-runs-native.batch70.wire.json` | 195,976 | 576 | 28 | `ff58865a322a1e9a536298cb595177413673860452fe0cd23f6ce0c28cec61d9` |
| `ml-use-rights-native.batch70.wire.json` | 210,008 | 576 | 15 | `d9774a7e9e11c2f3e568f3361dccbe14d1a91393b4e1c5bd385276e4889aa40b` |
| `discovery-main-barrier-native.batch70.wire.json` | 198,499 | 284 | 7 | `45b4552e1c7e332fa77a95a20a16d8121e7b3c29126e94bccdf9766e6fca30e9` |

Runtime: CPython 3.12.14 / native PostgreSQL on Darwin arm64; frontend Node
25.5.0 and the existing locked frontend dependencies. Native fallback results
are not Linux CI/image parity evidence. No migration or scripts suite was
rerun in this batch because its changes do not alter schema/worker sources.
The [batch69 migration and installed-worker evidence](Priority_Sixty_Ninth_Batch_Implementation_2026-09-13.md)
retains its original scope and bytes; its whole-source inventory is historical
after adding the new router endpoint and test, not a fresh batch70 attestation.

## Remaining work and delivery boundary

1. Add the separately scoped authenticated independent scientific review and
   signoff workflow, preserving original selection, failures, disputes and
   review chronology. Do not derive scientific approval from this UI's consent.
2. Obtain actual named reviewers, permitted original sources and the genuine
   preregistered 60-event study. Measure recoverability, state association,
   missingness, disagreements and human effort without substituting synthetic
   events or manufacturing missing negatives/structures.
3. Review the combined local changes for authorized commit/PR delivery, then
   obtain actual Linux/final-image CI evidence. No issue is closed based only
   on local synthetic or native testing.

No push, PR creation, issue mutation, shared database migration, deployment,
real source extraction/review, source redistribution, account-role grant,
training execution or production feature enablement was performed.
