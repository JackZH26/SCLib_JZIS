# Batch74 — Same-snapshot joint declaration coverage

Date: 2026-09-13. Base commit: `02949468802db042e56645e2932b08863a174074`.
Branch: `codex/sclib-research-v2`.

The live review backlog still contains 38 open issues (#41–78).
[ML08 #54](https://github.com/JackZH26/SCLib_JZIS/issues/54) was reread: its real
60-event study, independent review, permitted source evidence, missingness/effort
report and scientific recommendation remain incomplete. This batch implements
the next account-review workflow dependency, not a substitute synthetic pilot.

## Delivered backend and interaction

`POST /v1/ml/pilots/review-attestations/coverage` accepts the existing strict
four-original-file review upload. The fixed route invokes the original-file
worker; it cannot accept a prior preflight, receipt or caller-selected write
operation. Registration, intake and attestation flags all remain default-off.
No new table, migration, source retention, write or approval token is introduced.

The existing admission logic is factored into an internal verified context and
one-member projection. Existing preflight/declaration responses retain their
wire contract. The private complete roster never crosses the response boundary.
One fresh read-only repeatable-read transaction checks the account session,
original reviewer/registrar bindings, current grants, complete cohort acceptance,
declared review chronology and participation intervals, then reads declaration
heads within that same snapshot.

The required declaration set is the union of actual review contributors and
the current conclusion author, not every registered role. This includes failures
and all revisions and requires a zero-review conclusion author. An unused backup
arbitrator with no contribution or conclusion authorship is not required to
declare nonexistent reviews; its registered participation must still be valid.

Each required account belongs to exactly one disjoint category:

| Category | Meaning |
| --- | --- |
| Matching | Latest attest action matches exact originals, complete documentary/contribution basis, selected implementation, declaration contract and current accepted participation head |
| Missing | No declaration exists |
| Withdrawn | Latest head withdraws the account's declaration; an older recovered receipt cannot restore it |
| Stale | Recorded attest no longer matches this basis, contract/version or accepted participation head |

The response contains aggregate counts, own status, conclusion-author coverage,
common document pins and transaction start time only. No foreign account IDs,
aliases, individual declaration IDs or source prose are exposed. Invalid account,
grant, cohort acceptance or chronology makes the whole check unavailable. It is
not reinterpreted as zero missing records or complete coverage.

The English workbench adds **Check joint declaration coverage** after the
four-original scope check. It explicitly explains the renewed upload, clears old
consent/preview and displays aggregate counts with a historical-snapshot warning.
It does not auto-select consent, record a declaration, persist private state or
poll. A failed recheck, changed originals/account or subsequent declaration action
removes the prior snapshot. Stale asynchronous results are discarded.

## Scientific meaning and non-guarantees

`account_declarations_complete` describes account assertions against these exact
documents in one historical database snapshot. It does not assert human identity,
independence, scientific correctness, actual event existence, source rights,
canary reconstruction, publication permission or execution authorization.
`current_collective_signoff_verified`, scientific-acceptance and ML/run flags
remain false even when all account declarations match.

Concurrent withdrawal may occur after the snapshot begins. The implementation
does not mix that newer head into the older snapshot or promise live approval;
the next fresh check observes the withdrawal. Scientific signoff, permitted
context evidence and canary replay remain separate work. The fixed 60-event
denominator is not an ML sample-size sufficiency claim or independent-material
count. All tested people/events/declarations are explicitly synthetic.

## Actual verification

| Check | Result |
| --- | --- |
| Initial related owned PostgreSQL/Redis API run | 67 passed, 75.61 s |
| Expanded final owned API regression | 131 passed, 200.82 s; owned services cleaned up |
| Updated review protocol/transport/component suite | 128 passed, 8.03 s |
| Default-English/source checks | 38 passed, 2.77 s |
| Full frontend component regression, two workers | 1,820 passed in 51 files, 105.43 s |
| Desktop/mobile browser workflows | 8 passed, 48.4 s; no retries |
| Nonincremental TypeScript | Passed |
| Changed six Python sources/tests Ruff check and format | Passed |

The final API run includes the earlier cases; they are not independent counts to
add together. Security/chronology tests now exercise both preflight and coverage.
Additional actual HTTP/SQL tests cover complete/missing/withdrawn coverage, byte-
only changes, review/conclusion changes, reaccepted participation, unused
arbitration and a withdrawal committed concurrently between two head reads.
Coverage calls leave all database state unchanged and reveal no foreign account
bindings. A newly matching own declaration repairs only that account's stale head.

The first frontend protocol attempt failed one test because the synthetic
canonical serializer refused a fractional number before reaching the parser.
The test now injects the malformed number into raw response bytes; the parser
rejects it. No production validation was relaxed. Existing FastAPI `regex` and
unrelated React `act` warnings remain. ESLint was not newly installed or claimed
as passing. Native Darwin tests are not Linux CI or release-image parity.
The actual native environment is Darwin/arm64, Python 3.12.14, Homebrew
PostgreSQL 16.13 and Redis 8.6.1, rather than the documented Linux PG16/Redis7
container environment. No service binary was installed or upgraded, and no
shared service was reused. The full frontend command uses `--maxWorkers=2`; browser QA
runs separately against copied source, existing dependencies and synthetic local
adapters, with nonlocal requests blocked.

Both desktop and 390-pixel mobile joint-snapshot screenshots were visually
inspected: the aggregates and scientific-boundary warning remain readable with
no horizontal overflow. The new browser cases verify exact original-file/header
payloads, cleared consent/preview and removal of prior coverage after a failed
recheck; existing cases retain explicit declaration, withdrawal, recovery and
session-change coverage. Local images are under
`sclib-ml-review-browser-artifacts-ZdeQqh` in the OS temporary directory.

## Fresh original interface archives

Six archives are copied byte-for-byte from the successful final owned run.
Previous batch73/older archives and digest assertions remain unchanged.
All 3,231 overlapping current-source pins match. The declaration archive retains
36 original declaration replies plus nine original joint snapshots across three
synthetic accounts. Browser/test adapters are not new SQL or human evidence.

| Fixture under `frontend/tests/fixtures` | Bytes | Pins | Raw SHA-256 |
| --- | ---: | ---: | --- |
| `ml-pilot-attestations-native.batch74.wire.json` | 450,126 | 588 | `f5f3f68dbf52e65eaf713e243b2015420c544415c00e498fce7b6982eb135cb6` |
| `ml-pilot-participant-native.batch74.wire.json` | 154,888 | 588 | `f9b85c230f5571eef3e798e547f6639fcb19ead3ddb87d7a8ced1f3f537ff10d` |
| `ml-pilot-review-native.batch74.wire.json` | 82,977 | 588 | `9c181e2388b74b271f2ca9bf74b4270a2bd39bb923b5e44b0a4617e74c0d8c8b` |
| `ml-use-runs-native.batch74.wire.json` | 197,563 | 588 | `6baf207b484913ebd34c0adef9ed3bf1ee6a2051f642d0cb0a384f36817f2280` |
| `ml-use-rights-native.batch74.wire.json` | 207,084 | 588 | `d87f6e34db0c2f09f7b810cf55ce62a9a3e9c8368b69250178ad4e63bedda751` |
| `discovery-main-barrier-native.batch74.wire.json` | 199,423 | 291 | `6d061a88e3ba71039fe09b1c3151569ef454854fd70738b615ff6758372ac556` |

These API checks execute the current source-tree worker under the existing venv,
not a newly installed wheel or deployed image. Schema stays 0077. Earlier
batch72 migration/installed-worker receipts remain untouched at their original
revision and scope; no fresh whole-source migration or wheel result is claimed.

## Remaining delivery

1. Bind actual permitted context bytes and canary reconstruction/replay to the
   authenticated review boundary under an approved retention policy.
2. Run the actual stratified 60-event pilot with independent humans, preserved
   failures/disagreements, field-specific missingness and effort measurements.
3. Complete downstream empirical dataset/ML/RPS evaluations and authorized exact-
   revision PR/CI/release evidence before closing the relevant issues.

No additional commit, remote push, PR, issue closure, production migration,
reviewer grant, deployment, paid provider call or ML execution is performed.
The [operator contract](../../ML_PILOT_ATTESTATIONS.md) documents the new workflow.

Final local checks: 32 changed/new files, 127 resolving local Markdown links,
3,231 matching interface source pins and a passing `git diff --check`. The
limited common-credential-pattern scan found no matches; it is not a full
security audit. The isolated browser listener on port 32066 is absent after QA.
