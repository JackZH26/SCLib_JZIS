# SCLib performance and Discovery repair, 2026-09-24

Baseline production revision: `f33cbe8`. Diagnostics used the actual production data and a separate Python process, with `SET TRANSACTION READ ONLY`. Patched modules were loaded from a temporary directory; the running API service was not replaced. These timings are diagnostic observations, not a browser SLO or a release acceptance receipt.

## Findings and changes

- Discovery returned HTTP 503 and metadata `source_status=invalid`, although the mounted feed validated successfully with 268 candidates. The API mounted the directory read-only, then tried to write a last-good sidecar inside the same exception boundary as validation. A write failure discarded the valid snapshot. Recovery persistence is now best-effort; validation failures still use the existing stale/missing policy.
- Timeline recomputed raw records and live governance on every read. Its projection path could perform expensive work and then fall back to the raw path. Committed, read-committed requests now cache source-derived response bytes using the existing transactional catalogue and source lifecycle epochs, database binding, policy year and complete request variant. The cache is limited to 64 MiB and 32 entries; cold requests coalesce. Projection tables never populate this cache because those tables are outside the catalogue epoch. Each request checks the epoch, and mutations during a cold build reject publication. HTTP remains `private, no-store`, so a browser/CDN cannot bypass current governance.
- Search performed provider I/O before lexical/formula SQL. They now overlap without concurrent access to one SQLAlchemy session. The original MgB2 formula query hashed and joined 22,437 navigation rows to return 50; the revised query ranks first, verifies every selected candidate and rejects invalid bindings. Exact retained-text verification remains in place. A bounded 60-second ANN cache stores only immutable-generation neighbor identifiers, hashes and scores, keyed by full pin, query and filters. Hydration, lifecycle, evidence rights and active-pin validation still run every time. No user quota or personalized response is cached.

## Measurements

| Operation | Baseline | Patched diagnostic |
| --- | ---: | ---: |
| Timeline HTML, complete streamed response | 50.08 s | Not measured through patched frontend |
| Timeline API via public HTTPS, complete response | 39.030 s | Not measured through patched HTTP service |
| Timeline computation, first / repeated | Live endpoint uncached | 16.850 s / 0.063 s |
| Search MgB2, top_k=10 | 18.687 s | 6.187 s first / 0.575 s repeated |
| Search nickelate superconductivity, top_k=10 | Not measured | 4.418 s first / 0.420 s repeated |
| Discovery candidates | 503, no visible candidates | ready, 268 candidates |

The patched Timeline cold and warm responses both contained 2,000 display points and coverage of 19,338 results. Search returned 10 results in each diagnostic. Network and chart rendering time are additional to the patched in-process measurements. Cache contents are process-local and rebuild after restart or source epoch changes. Live semantic calls still incur provider latency on a new query.

## Verification

282 API regression tests passed using the repository's disposable-service runner with a private PostgreSQL 16 cluster and Redis process. Covered modules include Discovery cache/validation, Timeline response cache/projection/identity/HTTP, material ordering and epoch cache, immutable corpus/formula lookup, vector adapter, HTTP retrieval, scientific routing and search evidence lineage. The separate concurrency test proves SQL proceeds while provider work is pending.

Added tests cover read-only Discovery recovery, cold-request coalescing, mutation during Timeline computation, and cache invalidation after raw record changes, display changes without timestamp updates, material/source/parent/Work holds, accepted source maps, insertion and deletion. ANN cache tests cover immutable copies, pin changes, bounds, expiry and failed refresh. Static fatal-error lint and `git diff --check` pass.

The complete CI run exposed one older sampling test that injects projection points without selecting the uncached projection path, plus frontend captures pinned to the previous backend source. The sampling test now explicitly selects that path; the real SQL cache tests continue to cover the cached path. A fresh disposable PostgreSQL/Redis run passed 37 tests, including sampling, response caching and all seven native capture producers. Their raw output bytes were retained unchanged as `delivery20260924r1` fixtures, with hashes and original paths in `capture-manifest-2026-09-24.json`; earlier archives and their hash assertions remain intact. All 1,896 frontend component tests and 46 frontend source checks passed locally after recapture; the production Next.js build also passed. These local results do not substitute for the signed release pipeline's full CI checks.

## Release verification

Use the existing tested and signed image pipeline for production rollout. After replacement, warm `/v1/timeline?schema_version=1&max_points=2000&compact=true`, then verify `X-Timeline-Cache: HIT`, unchanged coverage, Discovery metadata/count and paginated candidates. Exercise a normal Search request and repeat it. No schema migration or frontend change is needed by this patch.
