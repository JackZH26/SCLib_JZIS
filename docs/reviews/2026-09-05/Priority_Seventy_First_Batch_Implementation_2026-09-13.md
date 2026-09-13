# Batch71 — authenticated review-document preflight

Date: 2026-09-13. Base commit: `634265d7cd2323a077045d4042ee8dbdabe86f19`,
branch `codex/sclib-research-v2`. Prior batch68–70 worktree changes are retained.
This interruption-recovery checkpoint completes verification and documentation
of the existing work before the user's requested local commit. It does not
start a remote delivery, change shared databases or close research issues.

## Delivered scope

The separately default-off `POST /v1/ml/pilots/review-preflight` checks the
complete original selection, protocol, review log and conclusion against the
immutable registration and real authenticated account/participation records.
Both registration and review-intake feature flags must be enabled explicitly;
neither is enabled by this batch. The new endpoint is read-only and API-only.

- Four independently pinned original files, each at most 8 MiB, use the shared
  installed scientific accounting kernel. All 60 selected candidates and every
  review revision remain in scope, including failures and superseded records.
- The closed upload format rejects duplicate keys, extra fields, invalid
  UTF-8/base64, wrong pins and oversize input. There is no projection-only
  HTTP shortcut or truncation. A complete all-failure `stop` conclusion is
  accepted as documentary accounting, without inventing negative Tc labels.
- Exact participant admission precedes source upload and is repeated after
  upload and the actual owned document worker. The final fresh read-only SQL
  snapshot checks immutable document pins, current registered accounts/grants,
  every alias/role binding and intact participation histories.
- Declared review times must fit recorded acceptance intervals, registration
  and the database clock. A review during a withdrawal gap fails even after
  reacceptance; an earlier valid participation interval is not erased by later
  withdrawal/reacceptance. The conclusion author must also have been accepted
  at its declared completion time. This does not authenticate external dates.
- Caller-only results expose opaque own contribution counts/hashes, document
  and implementation pins and aggregate counts, not other account identities,
  reviewer aliases, individual timestamps or source prose.
- An isolated, bounded owned child performs complete document checking;
  cancellation, spawn cancellation, timeout and excess output are tested with
  actual children and cleanup. The installed-wheel probe has no API/ORM
  dependencies or editable-source fallback. CI now includes that probe, but
  actual remote CI execution is not claimed.

The [operator contract](../../ML_PILOT_REVIEW_PREFLIGHT.md) specifies the
44,804,784-byte envelope, exact headers/body, read-only semantics, privacy and
remaining admission gates. Registration and byte-intake documentation now link
to it. Schema remains 0076; no migration/model change is added in batch71.

## Scientific boundaries

This is a prerequisite **preflight**, not an authenticated scientific signature
ledger. It retains no source-bearing documents and records no endorsement.
The supplied canary hash is only declared; this endpoint does not open context
files, replay the canary or verify source permissions. Scientific acceptance,
public release and run authority remain false, with training disabled.

Account separation is not human independence. Declared completion times are
checked for consistency with server-recorded participation, not proven truthful.
A preflight is a current observation, not a reusable admission token; future
signed writes need their own exact-document, current-rights and concurrency
checks. `recorded_recommendation` describes the uploaded declaration only.

All test events/accounts/documents are explicitly synthetic. Native SQL/HTTP
captures establish implementation behavior, not actual human review. The real
60-event ML08 pilot, source permissions, signed independent review, ML09 model
evaluation and AL01 policy evaluation are not completed by these tests.

## Verification after interruption

The previous test handle was unavailable and no old test processes remained.
Its lost terminal result was not counted as passing. A new owned PostgreSQL/
Redis invocation supplied fresh test data; no prior test services or shared
database credentials were reused.

| Check | Actual result |
| --- | --- |
| Targeted document and registration/review worker tests | 114 passed, 40.91s |
| Full offline scripts regression | 2,176 passed and 39 subtests passed, 206.84s |
| Registration, reliability, participation, review preflight, retention and three existing native capture checks | 84 passed, 119.61s; owned-service cleanup confirmed |
| Frontend English/default/source checks, final run | 38 passed, 1.62s |
| Full frontend component regression, final run | 1,692 passed in 48 files, 40.56s |
| Nonincremental TypeScript check | Passed |
| Participant desktop/mobile browser checks | 6 passed, 1.1m |
| ML rights desktop/mobile browser checks | 4 passed, 1.1m |
| ML runs desktop/mobile browser checks | 4 passed, 1.3m |
| Scoped Ruff and formatting checks | Passed for all seven batch71 Python files |

Counts overlap: the targeted 114 tests are included in the scripts suite.
API coverage uses real disposable PostgreSQL, authenticated HTTP and the actual
owned worker. The existing FastAPI `regex` deprecation warning remains.
These are native Darwin/CPython 3.12.14 checks, not Linux image/test parity.
No migration rehearsal was rerun in batch71 because schema sources did not
change; earlier batch68/69 receipts retain their original scope and bytes.

### Corrections made during verification

- The resumed formatting check found a wrapped `subprocess.run` call after
  adding explicit `check=False`; the formatter corrected it.
- The first frontend run found a newly added fixture hash assertion placed
  before its local helper declaration. It was moved after initialization;
  neither application behavior nor archived receipt bytes changed.
- That run also hit two existing Discovery layout test timeouts while three
  separate Next.js browser harnesses were compiling/running. The final rerun
  uses the same tests and unchanged timeout thresholds after those harnesses
  finish; no assertions or scientific gates were weakened.

The final complete frontend rerun passed with unchanged timeout thresholds.
All 135 local Markdown links in the ten changed/new documentation files
resolved. A limited credential-pattern check of the 65 changed/new files
found no matching credential patterns; this is not a comprehensive security
audit. Final `git diff --check` passed. All three isolated browser listeners
(32060, 32062, 32064) were absent after completion, and the owned database
runner confirmed its scoped cleanup.

The isolated browser harnesses use copied source, existing dependencies, offline
font mocks and explicit local synthetic API adapters. They do not access the
production API or alter the ordinary frontend build directory. The participant
mobile preview and desktop recovered state were visually inspected, with
English UI and no observed horizontal overflow. Artifacts remain local under
`/var/folders/m0/ztnj2ywn613cqhtb3_ym0xyc0000gn/T/sclib-ml-pilot-browser-artifacts-RtJ5bP`.
This is development-browser verification, not deployment approval.

## New immutable interface evidence

Five new files were copied byte-for-byte from the completed owned API run.
Historical batch68/69/70 archives and their raw digest assertions are unchanged.
Current frontend consumers use batch71; the additional review capture is an
API-only evidence archive, not a scientific-signoff UI implementation.

| Fixture in `frontend/tests/fixtures` | Bytes | Source pins | Original replies | Raw SHA-256 |
| --- | ---: | ---: | ---: | --- |
| `ml-pilot-participant-native.batch71.wire.json` | 153,964 | 581 | 21 | `5529a271abb2f0aee7990514cbe20bb8cd31fcd4bf017c06fa3f81415a17b593` |
| `ml-pilot-review-native.batch71.wire.json` | 82,053 | 581 | 3 | `af6664a05ec4b733bdcfa6c32f745fddaecaf9e11fb65e6c225a36229bb63a19` |
| `ml-use-runs-native.batch71.wire.json` | 196,639 | 581 | 28 | `d8759f5e1c15e484d53826c2df9baa8a33231d73e880ebe65443b7b3cc0f4be5` |
| `ml-use-rights-native.batch71.wire.json` | 214,690 | 581 | 15 | `d1f0d859d01baafaf32ccfe888d23331002da5e708c072aa21cc4b7123a4e0fc` |
| `discovery-main-barrier-native.batch71.wire.json` | 198,895 | 287 | 7 | `bbd9d7490b881a233314b3a60025788320c2205c8b9a6d1ba7a341e976d877a9` |

All 2,611 overlapping source pins were checked against current bytes. The review
capture stores three original response strings inside caller-reference entries;
it does not include the source-bearing uploaded documents.

## Independent installation evidence

A new wheel was built with existing local Hatchling dependencies, then installed
with `--no-index --no-deps` in a new environment under
`/private/tmp/sclib-batch71-zanA7g/installed`. Its isolated probe executed exactly
one actual child, with 60 synthetic candidates and 61 synthetic reviews. All
seven selected source/schema files resolved within that installed environment.
The source/probe checks reject ordinary nonisolated and repository-fallback use.

- Wheel SHA-256: `d8ee11fdd1e7a8769f43dad3b314e241d7ca4eecd02c95cbfb5f0c94cf257b6d`.
- [Original probe receipt](measurements/ml08-installed-review-worker-native-batch71-2026-09-13.json), SHA-256
  `b3d6ac342e17cabac858f3beaa757965dbd918cf4d24cb4d9eb68ccf9ceea9a3`.

The receipt explicitly does not establish database chronology, authenticated
account attribution, scientific acceptance, a signature, canary replay or
training permission. Native package installation does not establish Linux CI,
Docker runtime parity or a deployed image digest.

## Next work, after this local commit

1. Implement independently authenticated scientific signoff and its explicit
   human interaction against the exact complete reviewed documents; do not
   promote this read-only result into an approval token.
2. Bind actual source/context and canary replay to the authenticated boundary,
   with current source permissions and a separately approved retention policy.
3. Execute the actual fixed 60-event reviewed pilot with retained failure
   denominator, independent comparison/arbitration, missingness, effort and
   field-specific go/narrow/stop recommendations.
4. Deliver authorized PRs, exact-revision Linux CI and reviewed rollout evidence
   before issue closure or deployment. No push, PR, feature enablement, shared
   migration, real account grant or remote issue closure occurs in this batch.
