# Batch72 — authenticated own-review declarations

Date: 2026-09-13. Base commit: `dd4fb7746a8e7707951884f521088e0a262f5d33`,
branch `codex/sclib-research-v2`. This batch continues the private ML08 workflow
after registration, participation and complete-document preflight. It adds a
durable account declaration, not collective scientific acceptance. The resumed
turn finishes verification and the requested local commit; it does not push,
deploy, migrate a shared database, enable features or close remote issues.

## Delivered scope

Schema `0077_ml_pilot_attestations` adds the append-only
`ml_pilot_review_attestations` table. The separately default-off API provides
exact declaration wording, original-document preview/commit, protective
withdrawal, own-history inspection and original-key uncertain-outcome recovery.
The full [operator contract](../../ML_PILOT_ATTESTATIONS.md) specifies payloads,
consent, bounds, permissions and recovery behavior.

- The participant attests their own complete review contributions, including
  revisions, failures and unresolved results. Only the recorded conclusion
  author additionally endorses that exact conclusion. A nonauthor with no own
  reviews cannot create an empty endorsement. The synthetic integration test
  covers own contribution counts of 0 (conclusion author), 1 and 60.
- The immutable English declaration has a fixed version and UTF-8 digest.
  Both are bound into the stored intent and record. Explicit boolean consent,
  explicit preview/commit controls and an exact preview intent are required;
  numeric/string truthiness is not consent.
- A new declaration rechecks all four original files with the installed
  accounting kernel. The final serializable write checks registered accounts,
  grants, current participation, original document pins and declared review
  times against recorded participation intervals. A prior read-only preflight
  is not accepted as a reusable approval token.
- The declaration binds the original participant, exact accepted participation
  decision, all original-file hashes, complete document/log hashes, selected
  implementation hashes, own contribution digest/counts and declared outcome.
  Source-bearing originals and private review prose are not stored in this
  ledger. Private hashes/account references are not anonymized data.
- Preview exercises actual insertion constraints and rolls back. Commit needs
  the exact original key, predecessor and expected intent; stale concurrent
  writes do not create branches. A repeated unchanged declaration under a new
  key is refused, not counted as another independent review.
- Withdrawal derives the exact prior basis without another file upload. The
  bound active account can withdraw after reviewer-role revocation or leaving
  participation. Original-key recovery remains historical even after withdrawal
  and never turns a recovered receipt into fresh approval.

The positive declaration route requires registration, review-intake and
attestation flags. Withdrawal, inspection, wording and recovery need registration
and attestation flags, but not review-intake. All remain disabled by default.
The API retains private/no-store responses and the existing bounded upload,
isolated worker, deadline and concurrency controls. Old review-preflight uploads
cannot be exchanged with the new attestation envelope.

## Database and compatibility boundaries

SQL checks exact record/intent/basis relationships, the closed twelve-field
basis and four original-file pins, bounded counts, restrictive account/parent
references, one predecessor chain and current participation for positive acts.
At most 100 positive acts may be recorded per participant; protective withdrawal
does not consume that positive allowance. Server timestamps come from the
database clock. Update, delete and truncate are refused; retained declarations
also prevent account erasure and destructive schema downgrade.

An empty 0077 table can round-trip to 0076 and back while preserving old rows.
A populated table refuses downgrade. The migration runner now measures both
cases plus actual account declaration/withdrawal/recovery on a migrated schema.
Schema-report version 1.2 adds those outcomes while retaining validation of
original 1.0 and 1.1 historical reports. Old receipts are not relabeled as 0077.

SQL does not authenticate a privileged direct-SQL caller or verify original
source text. The trusted authenticated service and complete document verifier
remain required. Hash integrity establishes byte binding, not scientific truth.

## Scientific boundaries and next dependency

This is an authenticated account assertion, not an external digital signature,
proof of human independence or proof of truthful external completion dates.
The canary digest remains declared: no context file is opened, no canary is
replayed and no source permission is inferred by this endpoint.

Scientific acceptance, current collective signoff, source permissions, context
verification, canary replay, public release and run authorization remain false;
training execution remains disabled. A complete all-failure `stop` result is a
valid documentary outcome, not a reason to manufacture negative Tc labels.
All test candidates, accounts, source references and reviews are synthetic.

The next implementation is the English own-review declaration interaction:
display the exact contract and originals, show the participant's contribution,
require unselected explicit consent, and support preview, commit, withdrawal and
read-only recovery. Separately, collective currentness must reconcile all
required reviewers on the same exact latest documents. Real permitted evidence,
authenticated canary/context checks and the actual fixed 60-event independent
pilot are still required before ML08 acceptance. ML09/AL01 empirical evaluation
and exact-revision Linux CI/reviewed delivery remain open dependencies.

## Verification corrections and interruption recovery

The resumed turn recovered successful terminal results for the 104 related API
tests, the full frontend suite and the first final-source migration rehearsal.
Unavailable script/type-check handles were not assumed successful; those checks
were rerun. Earlier failures were corrected without weakening scientific gates:

- An initial test incorrectly expected the entire immutable declaration table
  to be empty across cases. It now scopes counts to the tested participant;
  retained audit history is never purged to make tests pass.
- Pydantic literal-true coercion admitted numeric `1`; the controls now require
  strict booleans and the service requires acknowledgement to be exactly true.
  Missing commit controls and numeric/string acknowledgements are tested.
- A capture helper referred to an import removed during cleanup. Its digest
  call now uses the existing worker document helper; the complete API suite was
  rerun after the correction.
- One rehearsal correctly refused a receipt because source files changed during
  its run. It is not counted as a successful final-source rehearsal. Later runs
  freeze their selected source inputs until completion.
- Final lint inspection identified two newly wrapped import blocks and one
  comprehension needing formatting. Only those additions were corrected;
  pre-existing whole-file formatting debt was not bulk-rewritten. The three
  legacy files retain exactly their HEAD lint findings (8, 4 and 2), with no new
  diagnostics. Seventeen other changed Python files pass Ruff; thirteen scoped
  formatted files pass the formatter check.

The final schema and native interface captures are regenerated after those
formatting-only changes. Earlier uncommitted captures remain in the owned local
temporary workspace, not substituted for current-source evidence. Committed
batch71 and older historical archives remain unchanged.

## Source-bound migration evidence

The [original 0077 native receipt](measurements/schema-rehearsal-0077-native-batch72-2026-09-13.json)
is copied byte-for-byte from the successful final, source-frozen run. Its raw
SHA-256 is `8a3b225f0035f52913af0646e1cfb141965b07800c33c54de5b05aff648512b4`
(112,781 bytes). This is `schema-rehearsal/1.2.0`, taking 137,712 ms, with
720 independently checked source inputs and verified owned-service cleanup.
It binds the base revision plus the then-dirty worktree inputs, not a fabricated
post-commit revision or a deployed image. Committing the same source bytes does
not rewrite that historical provenance.

All three new outcomes are observed: empty round-trip preservation, actual
account declaration/withdrawal/recovery, and populated-history downgrade refusal.
Final synthetic pilot counts are 2 registrations, 6 participants, 7 participation
decisions and 2 declaration-ledger rows. These are test accounting, not real
researcher participation or pilot completion. Legacy data/retention and earlier
migration checks also pass. The runtime is native Darwin arm64, CPython 3.12.14,
PostgreSQL 16.13, not Linux image/test parity or production backup/restore proof.

## Current native interface captures

All six files below come from the final successful 104-test owned SQL/HTTP run
after formatting. They retain original response strings, not synthesized client
responses. All 3,220 overlapping source pins match current bytes. The participant,
rights, runs and Discovery consumers use these new captures; the review preflight
and attestation captures remain API evidence, not a newly implemented signoff UI.

| Fixture in `frontend/tests/fixtures` | Bytes | Source pins | Original replies | Raw SHA-256 |
| --- | ---: | ---: | ---: | --- |
| `ml-pilot-attestations-native.batch72.wire.json` | 358,735 | 586 | 15 | `cd45d0b65b86fc9ea2d33e90ff3b150ebd4c392512e956e2810156cea1e30c3b` |
| `ml-pilot-participant-native.batch72.wire.json` | 154,622 | 586 | 21 | `51b334293c2e024d7b08648fdeaf0d4a53d0a1595444cd9f6af42239a9e41fb3` |
| `ml-pilot-review-native.batch72.wire.json` | 82,711 | 586 | 3 | `8ade8768f84bbd3b83599aa24fc2ae44e97e4c5c7402ef86495d210ff3a7f291` |
| `ml-use-runs-native.batch72.wire.json` | 197,297 | 586 | 28 | `4be1870e4e072254f65c1f304351b25bf164c4a6d3f9f3b9661fb9ab2972b221` |
| `ml-use-rights-native.batch72.wire.json` | 209,364 | 586 | 15 | `776c9bdf006b09f1ab9fd1818b891be26741f21d7b0081357ec347069ab2c86b` |
| `discovery-main-barrier-native.batch72.wire.json` | 199,291 | 290 | 7 | `ebc7a1b27ab2eaf742507da39eea4f4532e7ea629298d458d64b3f8d7deccd8e` |

The new attestation fixture includes three explicitly synthetic original uploads
and five actual replies per account: wording, preview, commit, replay and
historical recovery. It contains no actual papers, identities or human reviews.
Older committed archives and their historical digest assertions are unchanged.

## Independent installed-worker evidence

The final wheel was built with existing local Hatchling and its cached build
dependencies, then installed with `--no-index --no-deps --force-reinstall` only
inside this task's isolated environment. No dependency or application installation
on a shared runtime was changed. `uv` was unavailable on PATH; the same existing
Hatchling backend performed the local wheel build without a download.

- Final wheel SHA-256: `8065f874976ac4a1eb6a61c19a7934e783c3cc02055976d5135f09bec54ed7fc`.
- [Original installed probe receipt](measurements/ml08-installed-review-worker-native-batch72-2026-09-13.json),
  raw SHA-256 `1e46204bc4cae60eb59854e1744f70aa173c8b4e35e17917f7eae2754e24ed7e`.

The isolated `-I -B` probe executes exactly two owned children: legacy review
preflight and the new fixed attestation-upload mode. All eight selected sources
resolve inside the independent installation; application/ORM imports and network
access are rejected. Both modes use 60 synthetic candidates and 61 reviews.
The final probe output exactly matches the archived original bytes because the
three final formatting changes do not alter any of those eight worker sources.

This is selected installed-kernel behavior, not full runtime attestation. The
receipt explicitly does not establish authenticated account attribution,
database chronology, recorded declarations, canary replay, source permission,
scientific acceptance or ML execution. Those checks belong to separate layers.

## Test results

- Full offline scripts regression: **2,193 passed, 39 subtests passed**, 165.33 s.
- Post-format targeted worker/schema regression: **155 passed**, 4.89 s.
- Final related API regression: **104 passed**, 168.91 s, including all 20 new
  attestation cases; actual owned PostgreSQL/Redis cleanup confirmed.
- Final frontend source/default-English regression: **38 passed**, 2.01 s.
- Final frontend component regression: **1,692 passed in 48 files**, 42.54 s.
- Nonincremental TypeScript check passed after refreshing the native captures.
- Final participant desktop/mobile browser checks: **6 passed**, 40.4 s.
- Final ML rights desktop/mobile browser checks: **4 passed**, 36.1 s.
- Final ML runs desktop/mobile browser checks: **4 passed**, 44.9 s.

Counts overlap; the 155 targeted checks are not additional unique coverage on
top of the full scripts suite. The existing FastAPI `regex` deprecation warning
remains. The final API suite is targeted integration coverage, not a claim that
every API test in the repository was rerun. No timing reported here measures
production throughput or scientific efficacy.

Browser checks ran after the full component suite, with unchanged timeouts and
no retries. Each used an isolated copied-source workspace, existing dependencies,
offline font mocks and explicitly synthetic native-response adapters, not the
production API. All three listeners (32060, 32062, 32064) were absent afterwards.
The participant mobile preview was visually inspected: the English layout and
explicit preview/commit distinction remain readable without observed horizontal
overflow. Screenshots remain in the local `sclib-ml-pilot-browser-artifacts-Foers0`
temporary artifact directory; this is not a deployed signoff page.

The six changed/new Markdown files have 124 valid local links. A limited
credential-pattern check of all 41 changed/new files found no matching private
key or common token patterns; it is not a comprehensive security audit.
`git diff --check` passed. Earlier uncommitted generated artifacts were moved
to `/private/tmp/sclib-batch72-Txc3k3/provisional-archives`, so they remain
recoverable while the repository retains final-source captures. No user source
data was removed. Shared services, real reviewer grants, remote issues and
deployment state were not changed.
