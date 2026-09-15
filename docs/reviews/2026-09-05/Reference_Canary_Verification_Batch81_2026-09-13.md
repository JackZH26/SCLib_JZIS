# Batch 81 — genuine-byte reference regression and delivery audit

Base HEAD: `02949468802db042e56645e2932b08863a174074`, branch
`codex/sclib-research-v2`, preserving uncommitted batches 74–80. This batch adds
verification evidence, not application code or a new scientific admission rule.
The previous goal turn made implementation and actual-test progress. The full
eight-batch API process remains separate and is still running.

## Why the extra invocation matters

The ordinary API suite contains three explicit opt-in scientific-reference cases.
Without independently supplied local capsule/force-constant paths, those cases
report skips and download nothing. A completed ordinary suite alone would not
prove these real-byte import/replay paths. Existing documented captures were
located and checked instead of substituting synthetic positives or suppressing
the skips.

The read-only sources remain in their original private directories:

- `/Users/jackzhou/Documents/YorkMsc/ML-SC/qe-matdyn-canaries-d6c843a22e8c4c35bde392b8937b65c9`
- `/Users/jackzhou/Documents/YorkMsc/ML-SC/qe-force-constants-uq0y_w7o`

They are historical QEF/q-e reference-format files already captured in batches
30/31, not newly executed or independently authenticated QE calculations. No
file was downloaded, modified, redistributed or executed in this verification.

## Actual native result

The documented `-p tests.scientific_reference_options` invocation supplied those
two explicit paths through `run_disposable_tests.py`, with a new native
PostgreSQL/Redis pair. The original full-state, byte-pin, pending-import and
exact no-write replay assertions ran unchanged. The terminal reported
**3 passed, one existing FastAPI warning, 4.70 s, exit 0**, followed by owned
service/data cleanup. The [verbatim JUnit result](Scientific_Reference_Canaries_Batch81.xml)
has three cases, zero failures/errors/skips; its suite timing is 4.579 s, a
different measurement boundary from the pytest terminal duration.
This is a direct service/SQL canary: it does not itself exercise the HTTP upload
route, deployed ingress or an isolated parser-child process.

JUnit SHA-256: `2f8967dccb5a146ff1678a440c2390b489f52f17222d74f08da346af4aca2a2d`.
The original local artifact remains at
`/private/tmp/sclib-batch81-reference-DaTlZN/reference.xml`.

| Reference context | Actual disposition | Reason or boundary | Retained source files |
| --- | --- | --- | ---: |
| Al, example14 | Quarantined | Matching force constants and validated coordinates unavailable | 7 |
| AlAs, GRID recover | Success pending | Actual matching FC geometry parsed; scientific context/review still pending | 8 |
| BN, example17 2D | Quarantined | Unsupported `ibrav`/2D context; no invented bulk conversion | 7 |

All three reported `database_replay_unchanged=true`, `scientifically_accepted=0`
and `ml_admitted=0`. The pending AlAs import is not positive superconductivity
evidence. The two quarantines describe importer/input limitations, not negative
superconductivity labels or grounds for penalizing a material family.

The common observed compiler hash was
`1d9af3f2b938e5dd2ce82c296a8e8a748c3db2ceb5e7dfb3799e7cb22deefe76`.
Actual parser/compiler CPU/wall observations were 33/33 ms, 89/89 ms and 67/67 ms
for Al, AlAs and BN respectively. Calculation CPU, wall and monetary costs stayed
null; the existing `parser_worker_only` scope was not relabeled as DFT/DFPT cost,
proof of a separate worker process, or whole-request latency.
Within-run SQL equality is verified; generated account/row IDs make cross-run
whole-database hashes different, so those hashes are not claimed to be identical
to the older batch31 database.

## Live full regression and remote delivery

The full ordinary API coordinator remains live at handle **10177**, with its
artifacts under `/private/tmp/sclib-batch80-api-zfiWZL/run`. Batch 1 had already
verified 993 passes across 28 modules and owned cleanup. Batch 2 was still live
at approximately 80% at 2026-09-13 13:13:41 UTC. Observe the same handle before
deciding it is terminal; do not restart on a polling timeout. The source check
still matched all 734 API/script inputs after this separate real-byte run.

A fresh read-only GitHub check still found **38 open review issues (#41–78)**,
no open implementation PR for this branch and no published upgrade branch.
Remote main remained `d26fc098565492b78b416fb30b6b1ec7087b24c7`. The live ML05
#67 and EN04 #52 criteria were reread: native byte checks do not replace the
required reviewed source/method context, permitted-source canary, exact-revision
PR delivery or actual locked Linux image/test evidence.

No issue was closed, no local commit or remote write was made, and no production
state, feature flag or permission was changed. The requested confirmation for
committing/pushing the upgrade branch and opening a draft PR remains pending.
Independent source review, human pilot and empirical ML/RPS evaluation remain
unfinished. These three separately executed cases must not be double-counted
as additional ordinary-suite passes or as scientifically approved materials.
