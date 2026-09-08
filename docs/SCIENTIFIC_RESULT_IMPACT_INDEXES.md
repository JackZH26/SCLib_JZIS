# Scientific result impact: reverse lookup indexes

Migration `0066_result_impact_indexes` adds eleven nonunique btree indexes. It
changes no row, column, scientific schema, immutable capsule format, publication
permission, or result status. Its downgrade removes only these indexes, including
when scientific/import/publication histories are populated.

| Reader predicate | Index | Scope |
| --- | --- | --- |
| `ml_example_inputs.input_event_id = target_event` | `idx_sri66_ml_input_event` | Non-null event references. The existing property/event composite FK makes a separate property-ID OR predicate unnecessary. |
| `event_evidence.input_event_id = target_event AND link_type = 'derives_from'` | `idx_sri66_derivation_input_event` | One-hop declared derivations only. Other evidence roles are not promoted into causality. |
| Exact dependency `(table_name, row_id)` | `idx_sri66_distribution_object` | Typed registered object identity, not JSON/text matching. |
| Any of `capsule_release_0` through `capsule_release_7` equals a reached release | `idx_sri66_distribution_capsule_0` through `_7` | Eight partial non-null FK indexes support the reader's complete OR predicate. |

Existing event membership, primary-key, frozen row-pin, and publication proposal
indexes are reused. Neither identical formula nor sample names create an impact
edge. Distribution references here are historical catalogue relationships, not a
claim that a package is currently authorized or scientifically accepted.

## Local verification and its limits

Guarded native PostgreSQL tests register real synthetic typed rows, an integrity
capsule, and an unpublished distribution package. `EXPLAIN (ANALYZE, FORMAT JSON,
BUFFERS)` verifies that the four actual reverse query shapes have the intended
index paths and return matching rows. Tests use `enable_seqscan=off` because tiny
fixtures correctly favor sequential scans; this checks access-path availability,
not production latency. The eight-branch query uses `BitmapOr`. Removing one
capsule index inside a rolled-back test transaction makes that complete OR query
fall back to a sequential scan. All source, scientific, and governance rows remain
unchanged by the checks.

The full disposable migration rehearsal verifies both initially empty and fully
populated index-only downgrade/upgrade round trips, exact application head
admission, all eleven actual catalog indexes, migrated-schema query plans, and
full row equality. Every older independent nonempty-history downgrade guard runs
before the final populated 0066 round trip.

## Deployment boundary

Creation is ordinary transactional `CREATE INDEX`, under the existing serialized
migration job. It can block writes and needs additional disk. Production rollout
still requires measured table/index sizes, write-lock duration, disk headroom,
and representative query plans/latencies; no production benchmark or migration
has been performed by these tests. This migration is not a concurrent-index
rollout recipe.

The impact reader continues to require a clean REPEATABLE READ or SERIALIZABLE
snapshot, a caller-installed statement timeout of at most ten seconds, and a
ten-second whole-operation deadline. Queries hydrate at most 1001 narrow identity
rows to detect a 1000-row scope overflow; nodes, relations, and the complete JSON
response are also bounded. Indexes do not waive these fail-closed limits or make
`LIMIT` a bound on scan CPU.
