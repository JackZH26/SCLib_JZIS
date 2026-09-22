# Batch 75 — authenticated canary and context byte replay

Base: `02949468802db042e56645e2932b08863a174074`, branch
`codex/sclib-research-v2`, with the retained uncommitted batch74 coverage work.
This report describes new local implementation, not production deployment or a
completed scientific study. The freshly inspected GitHub backlog still contains
38 open issues (#41–78). [ML08 #54](https://github.com/JackZH26/SCLib_JZIS/issues/54)
requires an actual preregistered, permitted-source, independent-human 60-event
pilot and field-level feasibility/effort recommendations. No such study is
created by synthetic regression fixtures or account declarations.

## Delivered scope

- A portable `services.ml_pilot_canary` v1.2 compiler shared by the existing
  offline CLI and a newly isolated installed-package byte checker. Complete
  selection, all log revisions, effective event accounting and exact context
  inventory must replay byte-for-byte. No evidence is omitted for convenience.
- A default-off, own-account admitted binary streaming endpoint at
  `/v1/ml/pilots/review-attestations/evidence`. It performs no database/source
  write and accepts no cached or browser-authored proof. A fresh read-only SQL
  transaction rechecks current session, registrar/reviewer grants, all cohort
  participation and joint declaration coverage after byte processing.
- Bounded request framing, stream backpressure, per-file/combined context limits,
  canonical closed metadata, strict original/logical hashes, two-operation
  per-API-process admission, isolated-child deadlines and cancellation cleanup. Context bytes
  are hashed incrementally, never embedded in a response or scientific canary.
- An English workbench section for explicit original canary/context upload,
  separate integrity and account snapshots, zero-context warning and opaque
  references. It does not select consent boxes or invoke a declaration write.
  Changed originals, context, account, write or failed recheck clears prior proof.
- A **source-only** Nginx evidence location with 130 MiB scoped ceiling, disabled
  request/response buffering, no proxy temp files and dedicated rate limiting.
  It is not applied to a server. Other ingress, logging, host swap and retention
  systems still require separate operational review. The existing generic
  20 MiB proxy limit for older JSON intake is not silently broadened.

## Scientific and compatibility boundaries

The integrity response reports actual `context_bytes_checked` and
`canary_replay_verified`; its nested account-only snapshot retains its distinct
false byte-check flags. All source-permission, human-independence, scientific
acceptance, collective signoff, public-release and ML/run authorization flags
stay false. All tests use synthetic accounts, events, declarations and evidence.

The new canary inventory observes four installed kernel/resource byte hashes by
basename, without embedding repository paths or self-asserted Python identity.
This allows CLI/installed-wheel portability, **not runtime attestation**. Existing
1.1 artifacts and HTML reports remain immutable, replayable with their original
code. A current 1.2 package needs fresh canary construction, an independently
retained pin, updated conclusion/report and fresh appropriate declarations.
Selection/review/conclusion schema versions remain 1.0.0; DB schema stays 0077.

## Verification record

- Canary, report, accounting and streaming-worker regression: **154 passed,
  7 subtests, 164.08 s**. A subsequent complete streaming-worker rerun after
  adding actual 64 MiB and scoped-proxy assertions: **32 passed, 24.77 s**.
  These two additional cases bring the unique set to 156 tests; this is not
  represented as a single 156-test run.
- Initial streaming tests: 30 passed, 17.49 s. Initial frontend byte protocol:
  32 passed, 5.35 s; own-review interaction: 28 passed, 17.00 s, before the final
  added original-file reset regression. Final wider results are recorded below.
- First native API collection failed because a test helper imported a repository
  `scripts` package not on API test paths. The test helper was made self-contained.
  Next run: 12 passed, two assertion failures (actual stronger `private, no-store`
  header and the established 409 conflict status). Assertions were corrected to
  the existing contracts; production admission was not weakened.
- Browser desktop/mobile synthetic-adapter run: **10 passed, 1.4 min**. Both
  byte-integrity screenshots were inspected: readable English, zero-context and
  non-authorizing warnings visible, no horizontal overflow. This first run
  preceded the final original-file reset hardening; final rerun recorded below.
- Independently built wheel installed with `--no-index --no-deps` into a new
  owned venv. The `-I -B` probe refused server/ORM/repository-script imports and
  network calls, checked installed resource paths and admitted exactly one
  owned child per run. Both an actual native zero-context frame and a synthetic
  two-context/63-review revision case replayed identically. The latter hashed
  99 context bytes; this is not source-rights or scientific-content verification.
- Wheel SHA-256:
  `6bcd2cda0f08a45d46cf06ff4724bf9763a0bd277924e1773f5f3d1a32936f6e`.
  Selected byte-checker implementation SHA-256:
  `36bbe31d8280d7a12fc1d2a9d68adcea21bce902e12532b97794dfe7b6839bd3`.
  These are local artifacts/source observations, not Linux image parity.

Native environment: Python 3.12.14, PostgreSQL 16.13, Redis 8.6.1, Darwin arm64.
API tests use only newly owned native services through
`scripts/run_disposable_tests.py`; no inherited/shared DSNs. This differs from
Linux PG16/Redis7 CI image/runtime conditions. No fresh migration, production
data, remote CI job, Nginx syntax execution, ESLint install or deployment is
claimed. There is no local Nginx executable; proxy verification is source-only.

Final owned native API regression: **145 passed, 489.28 s**, including byte
intake, prospective registration, reliability, own/joint review declarations,
retention, ML rights/run and Discovery main-barrier flows. The runner confirmed
cleanup of only its owned temporary PostgreSQL/Redis services and data.
Existing FastAPI `regex` deprecation warning remains.

The first all-component run had 1,855 passing cases and one test-only error:
a new archive assertion called a local hash helper before its declaration. The
assertion was moved below that declaration; no archive bytes or production
contract changed. The final full component rerun passed **1,856 tests in 52
files, 156.83 s**, using `--maxWorkers=2`. It includes the original-file reset
regression and all seven current native compatibility archives. The final
browser rerun passed **10 tests, 1.3 min**, including real File/Blob construction,
the unmodified native frame/replies, original-file recheck clearing canary inputs,
failed recheck clearing proofs, desktop/mobile layout, protective withdrawal,
session invalidation and lost-reply recovery. Its server ran only on the owned
isolated 32066 port and stopped on completion. Final nonincremental TypeScript
checking also passed. No shared server was started or stopped.
Source checks: **38 passed, 6.50 s**. Nonincremental TypeScript checks passed.
Ruff lint passed on all ten selected changed Python files; nine format checks
passed. `api/config.py` has pre-existing whole-file formatting differences,
confirmed against HEAD through a read-only stdin check, and was not mechanically
rewritten merely to refresh unrelated source pins. `git diff --check` passed.
All **3,852** selected source pins in the seven new archives matched current
bytes. A limited credential-pattern scan of 55 changed/new files found no
matches; 138 local Markdown links resolved. These are scoped checks, not a
complete security or content-rights audit. Existing React `act(...)` warnings
outside the new workbench remain.

## New native fixture archives

All seven files below are newly captured originals, copied without overwriting
earlier archives. Filenames are under `frontend/tests/fixtures/`. Six contain
593 selected API/harness/schema pins; the Discovery capture contains 294 selected
API pins. The scope of these inventories is selected sources, not the full repo
or a production runtime. The new evidence fixture retains actual original
preflight, account and zero-context byte-check replies plus synthetic upload bytes.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `ml-pilot-evidence-native.batch75.wire.json` | 360282 | `f8128d35236754dac5164721bb34becc0431751fcc79fac2236fa23f6aa1edd8` |
| `ml-pilot-attestations-native.batch75.wire.json` | 450767 | `4c55cf055b23be8554cf3eceb9edcda20bb4f3657b0d1c8eeacdc6f261d517b8` |
| `ml-pilot-participant-native.batch75.wire.json` | 155529 | `ce0cbb73250fc614964f5f028e20479903eb9f33a7dd1ffd1680ea43c409178a` |
| `ml-pilot-review-native.batch75.wire.json` | 83618 | `aef5ea69f813ea49fcfc43b96922744719953242b82a03e60528190bde414054` |
| `ml-use-runs-native.batch75.wire.json` | 198204 | `139a5042e0aa1e6b71301159c03047a6dcda6d0ccc92e600f93b83b16fffa6c5` |
| `ml-use-rights-native.batch75.wire.json` | 234617 | `325260f84981f4f663e249da71e542ade0f7c2cd52115e9bcd38138247c67689` |
| `discovery-main-barrier-native.batch75.wire.json` | 199803 | `8966bbc04eac7e46c98cb0cf764e8b9fd93585f5b5a007e1b4858ad3da0e6f7e` |

The active frontend compatibility tests now use these current captures, retaining
all old archive hash assertions. Synthetic browser operation-key adapters remain
explicitly distinct from new SQL receipts. No earlier fixture is relabeled as
proof of the new backend source state.

## Operational handoff and remaining work

The exact wire, ceilings, privacy preconditions and English interaction are in
[ML_PILOT_EVIDENCE.md](../../ML_PILOT_EVIDENCE.md). No feature flag was enabled in
a shared environment, no production migration/grant was made, and no model or
paid provider ran. Work remains uncommitted; no push/PR/issue closure is implied.

Next: complete the approved pilot handoff and field-level report workflow, then
exercise deployment-specific ingress/retention behavior in an authorized
disposable environment before enabling intake. A qualified reviewer must still
approve the actual 60-event plan, permitted sources, independent assessments,
arbitration and reasoned keep/narrow/defer decisions. A hash/count snapshot cannot
substitute for this work or unlock downstream scientific acceptance.
