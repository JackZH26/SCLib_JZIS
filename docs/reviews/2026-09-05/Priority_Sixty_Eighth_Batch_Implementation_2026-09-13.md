# Batch68 — private pilot registration and actual migration compatibility

Historical source checkpoint: subsequent chronology/worker changes and their
own verification are recorded in the
[batch69 report](Priority_Sixty_Ninth_Batch_Implementation_2026-09-13.md). This
receipt remains evidence for its original pinned source state, not later code.

Base: local checkpoint `634265d` on `codex/sclib-research-v2`. A fresh read of
GitHub still found 38 open issues, including ML08 #54 and EN02 #58. This increment
advances their technical prerequisites, not scientific pilot acceptance or
production delivery.

## Implementation scope

The preceding checkpoint preserved the three private registration/participant/
decision ledgers, migration 0076, exact-document worker and authenticated private
API. Its 47 targeted native tests did not exercise Alembic migrations. The
[registration contract](../../ML_PILOT_REGISTRATION.md) still applies: exact
document commitments and each bound account's own participation are distinct
from real human independence, source permission and scientific acceptance.

This continuation integrates 0076 into the complete owned-database rehearsal:

- Earlier downgrade checks explicitly require the new pilot ledgers to be
  empty. Their existing snapshot exclusion lists add the three pilot tables
  that are absent on older schemas; no additional old scientific records are
  excluded. Pilot history is written only after all older
  populated-history guards have run, so its guard cannot mask their failures.
- A separate guarded helper exercises real 0076→0075→0076, compares all prior
  rows and both functions/all 13 triggers, and checks refusal by the current
  API against the actual old schema. No metadata-created replacement schema,
  disabled triggers or mocked migration compiler is used.
- The migrated-schema exercise attempts a valid registration with an incomplete
  roster and requires the actual deferred SQL constraint to reject it. It then
  checks rollback-only preview, caller-owned outer rollback, durable registration,
  exact replay, three own-account acceptances, a fresh-connection inspection,
  withdrawal and read-only recovery of the earlier acceptance.
- A populated 0076 downgrade must refuse without changing any retained row,
  version record or pilot function/trigger definition.

Synthetic accounts and candidate declarations test software behavior only. The
helper does not authenticate real people, supply real scientific sources or
constitute the actual 60-event feasibility study.

## Versioned evidence

New rehearsal receipts use `schema-rehearsal/1.1.0`. They additionally account for
all three pilot tables at each phase and require four separate pilot outcomes:
empty roundtrip, incomplete-roster refusal, account participation, and populated
history protection. The pilot tables must be absent in the legacy seed phase,
empty before their exercise and populated at the end.

The reader retains exact `1.0.0` compatibility without adding missing new claims.
A regression reads the original batch67 0075 receipt, requires its original
SHA-256 and rejects relabeling it as 1.1.0. No old native receipt or HTTP archive
is edited or resealed.

## Verification status

The first source-contract run found a test-marker ambiguity: a short substring
matched an earlier unrelated `empty_roundtrip` call. The assertion now matches
the exact indented pilot call; no execution-order requirement was removed.
Initial targeted lifecycle/receipt checks: **138 passed**, 5.53s.

The first report destination used macOS's `/tmp` alias. The runner rejected this
as `unsafe_report_destination` before starting services. The retry uses the
same owner-only directory via its resolved `/private/tmp` path. That rejection
is not an executed or passing database rehearsal.

The first actual native migration invocation reached the new helper but failed:
its identity query preceded `check_connection_schema`, which correctly requires
a fresh connection. It exited 1, cleaned up its owned services and published no
passing receipt. The helper must run admission before its other SQL checks;
the production fresh-connection guard is not weakened.

The helper now performs schema admission first, including the expected old-head
refusal, with a regression enforcing that order. The corrected lifecycle/receipt
suite passed **138 tests**, 5.23s. The actual complete native rehearsal then
passed in **409,287 ms**, including all four new pilot checks, and verified
owned-service cleanup before publishing its receipt.

The [0076 native receipt](measurements/schema-rehearsal-0076-native-batch68-2026-09-13.json)
is 109,893 bytes, raw SHA-256
`8b99e1b2db491344f3d8e1407a30da8a72a86d2c77c3f8bd108254f7aa04593b`.
It pins **703 source inputs**, inventory SHA-256
`3df07884a198d040926ce2d3d781f1cd92929b41673ea5bed796ff2a74252659`.
The archived receipt passed strict parsing and current-source comparison.
Runtime: PostgreSQL 16.13, CPython 3.12.14, Darwin arm64; this is not Linux image
parity, production data validation or deployment approval. Final synthetic pilot
counts are one registration, three participants and four decisions (three
acceptances followed by one withdrawal). Their earlier phase counts are absent
at the legacy schema and zero at both intermediate head observations.

The initial full scripts run passed **2,092 tests / 39 subtests**, 266.52s, before
the connection-order correction. The final full run passed the same **2,092 tests
/ 39 subtests**, 326.72s, against the corrected sources. The targeted 138 and
earlier full run overlap and must not be added as unique coverage.

The combined owned-native registration, HTTP, audit-retention and three existing
interface-capture tests passed **50 tests**, 233.10s, with the pre-existing
FastAPI `regex` deprecation warning and verified owned cleanup. The later helper
correction changes a selected run/rights source, so their two capture tests were
repeated separately: **2 passed**, 209.80s, again with owned cleanup. Those are
overlapping cases, not two additional unique tests. The initial run/rights files
remain under the private temporary run directory; they are not active fixtures.
The Discovery capture's selected source scope was unchanged by that correction.

The final byte-exact archives and their current selected-input checks are:

| Archive | Bytes | Source pins | Original JSON replies | Raw SHA-256 |
| --- | ---: | ---: | ---: | --- |
| `ml-use-runs-native.batch68.wire.json` | 195,560 | 573 | 28 | `a25dfbf0052951446d9874c853c4d7dcf7dd090090219ff757a953f788a7d75b` |
| `ml-use-rights-native.batch68.wire.json` | 213,132 | 573 | 15 | `14885ab44024bc09ee55d2cf53c37c5a76e4cf8dfbf22d6d1acf6faf22bd5809` |
| `discovery-main-barrier-native.batch68.wire.json` | 198,499 | 284 | 7 | `24060676f250dda54bd604ff097f8a883e35a755f24f165d6146b467f2a6a428` |

These are declared source subsets, not whole-runtime attestations or new real
scientific reviews. Frontend consumers now use these new archives; every existing
historical raw-hash assertion is preserved. The run/rights tests also require
the new migration helper in their selected input inventory. All three archives'
source pins were compared with current files successfully.

Frontend source checks passed **38 tests**, followed by a nonincremental
TypeScript check. The first full frontend run passed **1,586 tests / failed one**,
174.40s: the existing layout provenance/inapplicability case exceeded its unchanged
five-second test timeout. This run overlapped the native/script checks; no product
layout source changed in this increment. The timeout does not establish any
assertions that had not completed. Its chained TypeScript step did not execute
after failure. Resource contention is a possible explanation, not a demonstrated
root cause.

The final full frontend run, after those other processes finished, passed all
**1,587 tests in 45 files**, 153.04s. It retained the same two-worker limit and
five-second timeout, with no skipped case or product/test behavior changes. Its
chained nonincremental TypeScript check passed. The two subsequent isolated
browser suites passed **4 run-workbench cases**, 56.2s, and **4 rights-workbench
cases**, 41.0s, covering desktop and mobile, independent-account handoff, preview,
lost-reply recovery, and admission revocation/clearing.

The browser suites use the actual archived replies with declared browser
transport doubles; they are not a fresh SQL run or a real human approval. Their
temporary Next.js servers bind loopback, refuse server reuse, block external
browser requests and use offline fonts. Normal development services and the
production API are not used. Current screenshots are retained under the private
temporary artifact directories `sclib-ml-runs-browser-artifacts-3eDaBX` and
`sclib-ml-rights-browser-artifacts-BVej1D`. Visual inspection of the mobile private
evidence and rights preview captures confirmed readable wrapping, visible
controls and English website-owned copy. Multilingual synthetic evidence remains
quoted as text; it is not translated or executed.

Scoped lint on the new helper, receipt implementation and receipt tests passes.
The older migration harness retains its four pre-existing C408 findings; the
lifecycle source tests retain two pre-existing PLW1510 findings. No lint rule
was disabled to conceal a new finding.

Final handoff checks revalidated the new receipt against all 703 current source
inputs and checked all three raw interface archives and their selected input
hashes. All **108 relative links across the five touched Markdown documents**
resolve, and `git diff --check` passes. Both owned browser ports (32060/32062)
have no remaining listener, and the observed owned browser server/worker PIDs
have exited. Native runner cleanup was verified in each completed invocation.
No unrelated development database or service was stopped.

This continuation is an uncommitted worktree increment on top of `634265d`.
It did not push, open a PR, deploy, migrate a shared/production database, grant
real account roles or close an issue.

## Remaining delivery and science gates

Further registration work includes adversarial worker/concurrency/chronology
coverage, an installed-wheel probe for the new worker, and an English participant
workbench with independent exact-artifact scientific signoff. The current default-
off API does not implement those later UI and scientific workflows.
In particular, this migration rehearsal does not test rejection of a declared
future freeze date against the server clock. Recording a server timestamp must
not be described as validation of external selection or review chronology.

The user still needs to identify real reviewers and permitted source material
for the actual pilot. No identity or independence is inferred from synthetic
accounts. ML09 execution and AL01 empirical scoring/active-learning evaluation
remain dependent on genuine reviewed data and their own rights/runtime/budget
gates. Remote PR/Linux CI delivery and production changes remain separate.
No issue is closed, and the overall upgrade goal remains active.
