# Materials-list profiling: 9 October 2026

This checkpoint adds diagnostics before choosing a performance optimization.
The existing public release `67b790e` does not emit these server timings. Local
correctness tests do not identify the bottleneck of a production cache miss.

## Observed baseline

The [retained application-cache observation](data/nextstage-20261009/application-cache-miss-profile.json)
captured one `X-Materials-Cache: MISS` taking **14.516175 seconds**, followed by
four `HIT` responses taking **0.645800–0.843437 seconds**, for the same fixed query:

```text
/materials?sort=total_papers&min_papers=2&limit=25&offset=0
```

Both version reads reported site `67b790e`, dataset `v2026.09.03`, API `1`.
Client time includes connection/TLS, response transfer and gzip decoding. A page
MISS does not establish a missing ranking cache, a cold PostgreSQL buffer cache
or a scientific-projection bottleneck.

The [second, predeployment capture](data/nextstage-20261009/material-profile-predeployment-v1.json)
contains ten successful GETs across five fixed queries, two attempts each. All
ten report page `HIT`; none emits `Server-Timing`. Median client times range
from 0.429308 to 0.736917 seconds. This small, sequential sample is descriptive;
it does not establish a p95 service objective, a speedup or controlled cold/warm
server performance. Missing server timings remain missing in the report.

## Request-specific diagnostic contract

Successful, cacheable `GET /materials` responses add a fixed-label
[`Server-Timing`](https://www.w3.org/TR/server-timing/) header in milliseconds.
The cache continues to retain response body bytes only. A page hit gets its
own fresh version-lookup time, never its builder's scan durations.

| `materials_path` description | Work performed by this request |
|---|---|
| `page_hit` | Initial revision lookup finds a cached complete page |
| `waited_hit` | Waits for the filter lock, rechecks the revision and finds the page |
| `ranking` | Reuses ordered identifiers, reloads the requested rows and projects the page |
| `scan` | Executes the current-policy candidate scan; includes sorting/publication when retained |

`X-Materials-Cache` keeps its existing `HIT`/`MISS` meaning. In particular,
`ranking` returns page `MISS` despite avoiding a complete scan. Internal calls
with unresolved FastAPI defaults and noncacheable transactions keep their DTO
return behavior; they do not acquire this HTTP header. Refusals/conflicts keep
their existing 422/503 responses without successful-response timings.

| Stage | Measurement boundary |
|---|---|
| `revision` | All catalogue/source epoch and transaction-mode lookups |
| `lock_wait` | Acquiring the shared filter-build lock |
| `scan_fetch` | Initial SQL stream setup and subsequent partition fetches, summed |
| `scope` | Source/Work/map/parent resolution and read-context preparation, summed |
| `selection` | Current visibility, same-occurrence filters, sort-value projection and bounded heap selection, summed |
| `scan_close` | Memo release and SQL stream closure |
| `projection` | Complete public DTOs for the displayed page |
| `ranking_page` | Reloading/projecting a page from retained ordered identifiers |
| `ranking_publish` | Identifier sorting, encoding and ranking-cache publication |
| `serialization` | Encoding the complete response DTO to JSON bytes |
| `total` | Decorated route execution, including its cache, revision and lock work |

`total` **contains** the other stages; do not add it to their durations. It
excludes dependency setup before route entry, outer middleware/compression,
reverse-proxy work and network transfer. Small unclassified route/measurement
overhead remains within `total`. `scope` includes its SQL; it is not pure CPU
time. The stages do not establish a query plan or identify one slow SQL statement.

The existing `sclib_material_list_stage_duration_seconds` histogram keeps its
stage label and gains these fixed stages. Batched stages observe each batch
separately in Prometheus; the response header sums them per request. `total`
observes the decorated execution, including exceptions, but validation errors
raised before route entry are outside its scope. Shared revision helper calls
from detail/enrichment routes do not enter this list metric. No SQL text,
filter value, source ID, user identity or credential is added to either label.

## Repeatable capture and interpretation

The new standalone collector uses five predeclared public GET queries, gzip,
one to ten sequential samples per query, and API/software/dataset version reads
before and after. It accepts no custom URL, credentials or random cache-busting
query. It preserves failures and observed cache states; it does not purge caches.

After deployment, write to a new path:

```bash
python3 scripts/profile_material_list.py --samples 5 --require-server-timing --output /tmp/material-list-profile-new.json
```

`--require-server-timing` refuses complete server-profile acceptance if headers
are missing/invalid or the capture's versions differ. Without it, a stable,
successful capture on an older release can succeed as HTTP evidence while
`server_profile_complete` remains false. No mode grants scientific/SLO acceptance.
The version fence does not turn multiple GETs into one database transaction.

Inspect the individual attempts before grouped medians. Compare only the same
fixed query, page size, encoding, deployed version and server path. If a genuine
`scan` is observed, the dominant stage guides the next controlled experiment:
SQL stream delivery for `scan_fetch`; source-policy queries for `scope`; exact
projection/filter CPU for `selection`; JSON cost for `serialization`; contention
for `lock_wait`. A `ranking` or `page_hit` cannot substitute for that scan evidence.
Naturally absent cache entries can be sampled after a normal release or epoch
change; an arbitrary first client request is not declared cold.

## Engineering validation and remaining gates

Eight new API tests cover real SQL scan/page/ranking/lifecycle invalidation,
same-body page replay with fresh timings, warm refusal, concurrent waiting,
builder/waiter cancellation, real stream/memo cleanup and batch aggregation.
Eleven offline collector cases reject malformed/duplicate/unsafe timing labels,
keep missing headers unavailable, preserve failure denominators and reject
changed versions. Existing ordering, formula lookup and lifecycle-scope tests
are included in focused regression.

Complete owned-service local regression and exact-revision Linux CI remain
release gates. Deployment observation, a genuine instrumented scan, frozen SLOs
and a measured optimization are subsequent gates. Human material acceptance,
retrieval gold labels, compute admission and training approvals retain their
separate pending states.
