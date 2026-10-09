# Materials list: request-owned lifecycle memo

The cold list still scans current material/source evidence before ranking it.
Page and ordered-ID caches already avoid repeating that scan for unchanged
revisions. This change reduces repeated paper-lifecycle reads across the
128-material batches of one cold ranking build. It does not change ranking,
scientific eligibility, parent traversal, response fields or existing caches.

`LifecycleReadMemo` retains the complete `resolve_paper_lifecycle` result,
including direct and accepted-Work lifecycle overlays and explicit `None` for
missing paper IDs. It preserves exact lookup identifiers and returns detached
values. It is tied to one session and created only when the list has a non-null
catalogue/source revision. The existing final revision fence rejects a read
spanning any relevant committed change before publishing either cache.

The memo admits at most 20,000 entries and 8 MiB of encoded key/value weight.
This is a logical payload bound; Python object overhead is additional. Entries
that exceed either bound, or cannot be encoded, use the original resolver path.
Resolver failures propagate without being cached. A `finally` block clears the
memo and closes its session ownership after the scan, including failures and
cancellation. There is no cross-request lifecycle cache. Noncacheable/private
transactions, details and ranking-hit page hydration retain their prior reads.

## Metrics and their limits

`sclib_material_lifecycle_ids_total{result=...}` has three fixed labels:

- `resolved`: IDs in successful resolver calls, including explicit missing
  sources. It covers all visibility-adapter calls, including details and page
  hydration; it is not a unique-source or list-only count.
- `memo_hit`: IDs served from the current scan's memo.
- `not_retained`: resolved IDs rejected from the memo by its capacity or encoding
  limits. This overlaps `resolved`; these counters must not be added together.

`sclib_material_list_stage_duration_seconds{stage=...}` observes completed stages:

| Fixed stage | Scope |
|---|---|
| `scope` | One cold batch's parent/source reads and visibility/anomaly projection. |
| `selection` | That batch's policy filters, matching, scalar projection and heap maintenance. |
| `projection` | Final heap ordering, selected-page full DTOs and list model. |
| `ranking_page` | Existing-ranking page hydration, scoping and full DTOs. |
| `serialization` | Full result JSON encoding in the cacheable wrapper. |

These are partial measurements, not a complete request waterfall. Initial SQL
stream execution, batch fetch/ORM hydration, epoch reads, lock wait, final ranking
sort/encoding, and page-HIT handling are not separate stage observations. Failed
stages are not recorded as completed stages. Existing HTTP and dependency metrics
remain available, but subtracting or summing these metrics cannot reliably split
SQL and CPU time. No query, material, paper, user or formula labels are added.

## Validation

Use only the owned-service runner in [TESTING_SAFELY.md](TESTING_SAFELY.md).
`test_material_lifecycle_memo.py` exercises two real 128-row batches, complete
accepted-Work holds, missing sources, exact response-byte parity with memoization
disabled, private transaction bypass, and source/Work/map changes between batches.
The race tests require HTTP 503 and no ranking/page cache publication.
`test_material_visibility_adapter.py` covers detached values, entry/byte fallback,
exact legacy lookup identifiers, owner/close checks and resolver error behavior.
The existing ordering, visibility, formula and scientific-filter tests remain
the correctness baseline.

This change alone does not establish a production latency improvement or resolve
the previously observed 21.206-second first list. Query-count reduction is
verified separately from hardware- and dataset-dependent timing. Rank-only
scientific projection, parent memoization, persistent/shared ranking caches and
deployment prewarming are outside this patch.
