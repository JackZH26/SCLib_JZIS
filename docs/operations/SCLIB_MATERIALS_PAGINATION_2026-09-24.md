# Materials pagination cache, 2026-09-24

## Cause and change

Production `b842ced` already caches each exact Materials response. A previously unseen offset or page size still scans and evaluates the entire eligible catalogue, resolves current source policy, and ranks current projected values. Repeated visits to an already cached page are fast; visiting a new page repeats the expensive scan.

The new bounded cache retains ordered material identifiers for each complete filter/sort combination and committed catalogue/source revision. Pagination and page size share that ranking. Only the selected page is fetched and hydrated with its full current evidence DTO; ORM objects and raw records are never retained in this cache. Existing page-byte caching remains. Concurrent cold requests for different pages of the same query share the initial scan.

Both caches use the existing transactional catalogue/source epochs, database binding, transaction xmin and policy year. Private or repeatable-read snapshots do not populate the cache. A source change during ranking or page hydration rejects the response with retryable HTTP 503. Browser/CDN responses remain `private, no-store`; this does not authorize stale source policy or scientific claims.

Rankings are limited to 16 MiB total / 32 entries. Individual builds stop collecting identifiers above 100,000 materials or 4 MiB and continue through the existing bounded page-heap path. Cold scans still retain only offset+limit full material contexts. Locks have weak references and disappear when builders and waiters finish.

## Diagnostic measurements

Measured in separate Python processes inside the production API container using `SET TRANSACTION READ ONLY`. The candidate module was loaded from a temporary file; the serving API and production checkout were not replaced.

| Operation, 50 records/page | Production code | Candidate code |
| --- | ---: | ---: |
| First page, cold process | 20.449 s | 22.951 s |
| First page, repeated | 0.002 s | 0.001 s |
| First visit to second page, offset 50 | 19.887 s | 0.396 s |
| First visit to third page, offset 100 | 21.904 s | 0.263 s |
| First visit to offset 10,000 | Not measured | 0.153 s |

All tested responses reported 10,507 materials. The first three pages had identical SHA-256 hashes and byte counts before and after the change. The shared ranking used 218,850 bytes including its key. These are individual computation timings, not browser latency guarantees.

Public HTTPS requests to already warm pages on the unchanged serving API completed in 0.026–0.044 s; warm complete HTML responses took 0.298–0.337 s. This confirms that existing warm page caching works. A completely cold query still needs a full scan; warm the default list as part of release acceptance rather than making the first visitor perform that build. New filter combinations and source revisions can still require a cold build.

## Validation and release

Relevant SQL regressions cover complete response equivalence for all four sort modes, stable null/tie ordering, same-record filters, selected-page hydration, concurrent cold pages, source mutation during cached-ranking hydration, updates to unselected materials, cache bounds, and existing raw-record/material/source/parent/Work invalidation.

Local validation passed 102 relevant API regression tests in owned disposable PostgreSQL/Redis services, seven native HTTP capture producers, all 1,896 frontend component tests and 46 source checks. The 4,006 source pins in the new unmodified captures match the candidate files; historical archives remain intact. Fatal-error lint and git diff whitespace checks pass.

Before release, complete the normal Test/Security/signed-image pipeline. After deployment, warm `/v1/materials?sort=tc_max&limit=50&offset=0`, then check a repeat (`X-Materials-Cache: HIT`), first visits to offsets 50 and 100, unchanged counts and DTOs, and the Materials HTML pages. The first warm-up may take roughly 20 seconds. Preserve normal pre-release backup and rollback procedures. This document records a tested candidate, not a completed deployment.
