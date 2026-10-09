# Homepage acceptance snapshot: 9 October 2026

## Subsequent deployment check: 09:52–09:53 UTC

The later [complete public capture](data/nextstage-20261009/public-after-7efe186-v1.json)
observed API and freshly fetched frontend revision `7efe186`, dataset
`v2026.09.03` and API `1` between matching version fences. All 206 static
source/evidence byte pins and all sixteen recovery windows passed again.
Coverage remained 75,202 papers, 11,463 stored materials, 10,507 default-public
materials and 1,117,982 retained chunks. Statistics now reported
`2026-10-09T09:00:01.676015+00:00`; last ingest was unchanged.
Deployment [37910749759](https://github.com/JackZH26/SCLib_JZIS/actions/runs/37910749759)
completed successfully before capture. One sample per fixed profile records
availability and observed timing; it establishes no p95, bottleneck or SLO.
The earlier `67b790e` observations below and their raw receipts remain intact.

## Earlier accepted baseline

This supersedes the [6 October homepage snapshot](README_SNAPSHOT_2026_10_06.md)
for current descriptions. Historical observations remain intact. The application
baseline was `67b790e30f136bacc0408b86d3be13bfbf2ee6f4` (PR #159).
Test, Security, Release images and Deploy completed successfully; deployment
run [37893207219](https://github.com/JackZH26/SCLib_JZIS/actions/runs/37893207219)
is distinct from this documentation/tool publication.

## Public observations

The complete static-file capture ran at **07:05:05 to 07:06:36 UTC**. Fresh API
version reads before and after agreed, and the freshly fetched homepage footer
matched `67b790e`. Search-engine cached page text was not used to establish runtime parity.

| Measure | Observed |
|---|---|
| Site / API / dataset | `67b790e` / `1` / `v2026.09.03` |
| Papers | 75,202: 46,895 arXiv + 28,307 APS |
| Stored materials | 11,463 |
| Current default public catalogue | 10,507 |
| Retained chunks | 1,117,982; not verified active vector membership |
| Last literature ingest | `2026-09-03T10:30:54.970754+00:00` |
| Statistics refreshed | `2026-10-09T07:00:21.163840+00:00` |
| Materials policy | `current_projected_catalogue` / `atomic_property_evidence` |
| Source-computed hypotheses | 103; C exploratory / E1 published source theory |
| Source details and evidence dossiers | All 206 requested public files matched checkout SHA-256 and byte counts |
| Primary recovery windows | All 16 matched seed `materials-primary16-2026-10-09-v2`, retaining 55 observations |

Full GET receipts, request timings, hashes and failure fields are retained in
[the complete capture](data/nextstage-20261009/public-all206-67b790e.json).
The source catalogue is pinned to
`4a9089bc569f99ad7f5f469280814fb22bfcc86252b1fb7c1e1be446f8bcac98`.
The recovery seed's canonical hash is
`ea347f50f1e440960f309e7bb4365c305a583c43576f90709568caeb0c6cbc81`.

These are integrity and serving checks. They do not authenticate experiments,
approve unresolved sample associations, establish scientific support or grant ML
use. The 55 observations and 34 pending candidates overlap. Counts must not be
added as independent facts. Each GET has its own serving checks; the capture is
not a single database transaction and deployment versions do not fence every
possible database change.

The daily arXiv workflow remained `disabled_manually` when checked. Historical
pipeline completion and a recent statistics refresh do not establish resumed
ingestion. This task did not resume schedulers.

## Measured client latency

Four fixed public GETs were measured sequentially, five times per request.
The first identity-encoded capture observed 7.538 seconds for the filtered
cuprate request and 18.186 seconds for source-count ordering. Their cache state
was not recorded, so neither is a proven cold-cache measurement.

Subsequent [identity](data/nextstage-20261009/public-cache-profile-67b790e.json)
and [gzip](data/nextstage-20261009/public-gzip-profile-67b790e.json) captures each
reported `X-Materials-Cache: HIT` for all 20 timed requests. The existing server
already supplied gzip; this task changed no compression configuration.

| Request | Identity median / empirical p95 (s) | Gzip median / empirical p95 (s) | Gzip wire / decoded bytes |
|---|---:|---:|---:|
| Default, 25 rows | 0.873 / 3.135 | 0.505 / 0.526 | 23,491 / 505,619 |
| `q=MgB2`, 25 rows | 0.791 / 0.846 | 0.424 / 0.587 | 13,539 / 336,659 |
| Observed cuprate, Tc ≥ 30 K, pressure ≤ 1 GPa | 0.788 / 0.803 | 0.517 / 0.617 | 15,000 / 216,930 |
| `sort=total_papers`, 25 rows | 1.480 / 2.218 | 0.698 / 0.824 | 185,332 / 2,557,859 |

There were zero failed attempts in these captures. The empirical p95 uses the
nearest-rank rule and equals the maximum at n=5. This is a descriptive client
baseline, not a population p95, accepted SLO or controlled compression experiment.
Network conditions and capture time can differ. Individual urllib requests
include connection/TLS, transfer and decoding; these are not server-only or
browser render timings. Actual cold-scan profiling remains open.

A separate normal request, `sort=total_papers&min_papers=2&limit=25&offset=0`,
reported an application response-cache **MISS at 14.516 seconds**, followed by
four **HITs at 0.646 to 0.843 seconds**, with gzip requested and a stable
`67b790e` version fence. The [original receipt](data/nextstage-20261009/application-cache-miss-profile.json)
preserves all five samples. No cache was purged. The MISS establishes response
cache behavior, not database/ranking-cache coldness or a per-stage cause.

The [refusal capture](data/nextstage-20261009/public-refusal-checks-67b790e.json)
also confirmed HTTP 422 for unreviewed phase filtering, `ambient_sc=false`,
inverted pressure bounds and duplicated `q` values. These guards cannot be
waived by a warm response cache.

## Reproduction

Run from the repository root, using a fresh output path:

```bash
python3 scripts/verify_public_snapshot.py --samples 5 --all-details --accept-encoding gzip --output /tmp/sclib-public-new-capture.json
```

The standard-library tool only sends bounded credential-free GETs. It has no
provider-backed Search/Ask call, SQL target, cache purge, scheduler mutation or
solver launch. It verifies pinned public bytes, checks live recovery windows,
retains failed attempts and checks software/dataset versions before and after.
Gzip decoding has a bounded decoded-size limit. Default detail coverage is six
files; `--all-details` explicitly checks all 206 with at most four simultaneous GETs.

The [execution record](NEXTSTAGE_EXECUTION_2026_10_09.md) tracks remaining
performance, scientific-review, evaluation, compute and ML gates separately.
