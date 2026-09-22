# Same-result scientific filtering — SC04

Status: local implementation; no production backfill, deployment, corpus-wide
coverage audit or workload-scale latency claim. See [pressure semantics](PRESSURE_SEMANTICS.md)
and [result origin](RESULT_ORIGIN_CONTRACT.md) for the independent contracts.

## One witness per scientific match

`api/services/scientific_filters.py` supplies the common predicate for Search and
Materials. Every requested family, Tc, pressure, origin/source-role, experimental,
APS and source-tier condition must be satisfied by **one extracted record**.

A paper containing A = 300 K at 200 GPa and B = 5 K at explicit ambient pressure
does not match `tc_min=200` AND `pressure_max=1`. Paper or chunk family cannot
supply A with B's family. For the material catalogue only, the material entity's
family may fill an absent record family because the records belong to that entity;
an explicit record-family assertion takes precedence. This inheritance is not
sample/phase matching or a scientific family reassessment.

Responses include `matching_results` with `result_id`, original `record_index`,
formula/family, supported `tc_lower_bound_k`, pressure interpretation, result
classification and `filter_policy_version=same-result/1.0.0`. The ID is a SHA-256
reference to the legacy scope and raw record excluding reserved derived envelopes.
It is stable under reordering/annotation but is **not** the future reviewed,
revision-aware scientific event identity. Identical reports are not thereby
independent replications. All witnesses are returned; the UI displays up to three
and states when the API contains more.

An unfiltered text search does not call every paper record a scientific match.
Its `matching_results` is empty unless a scientific filter was requested. Search
still operates within the existing bounded retrieval candidate pool; its result
count is not an exhaustive catalogue count or a literature-recall guarantee.

## Pressure and temperature

- `pressure_min`, `pressure_max` and `ambient_only` (Search) use the canonical
  pressure classifier. Unknown, ambiguous, unexplained zero and nonfinite pressure
  do not pass a numerical pressure predicate by default.
- `include_unknown_pressure=true` explicitly broadens a pressure query. Witness
  metadata/UI still says missing or unresolved; it does not claim numerical
  compliance. Unsupported negative-pressure protocols remain excluded from such
  queries. With no pressure predicate, unknown or negative pressure does not
  exclude an otherwise matching record.
- Tc filtering reparses original units/notation through the same scientific-value
  parser as ingestion. `api/services/scientific_values.py` is a byte-identical
  vendored copy, independently deployable without importing ingestion dependencies.
- A Tc interval/lower bound can establish a supported minimum; an upper-bound-only
  result cannot. Symmetric uncertainty uses the reported extent, not an inferred
  confidence interval. Unbounded approximation cannot establish an exact cutoff.
- Cached normalized values are not authoritative. Missing raw typed proposals,
  reversed intervals, negative uncertainty, nonfinite values and approximate
  interval endpoints fail closed while preserving the raw proposal for review.
- The shared outcome veto checks all explicit status aliases and negative boolean
  markers. A positive string cannot override a contradictory marker elsewhere.
  This veto is not a negative-label generator or a scientific validity assessment.

All bounds must be finite; reversed pressure bounds produce 422. Do not interpret
conservative exclusion as evidence that a material does not superconduct.

## Materials API compatibility

`ambient_sc=true` requires an observed positive result with explicit ambient
pressure. The separately named include-unknown mode can broaden pressure matching,
but it never changes the returned ambient summary to true without supporting
explicit evidence. `ambient_sc=false` now returns an explanatory 422: absence of
ambient evidence cannot establish an experimentally tested negative. The UI offers
Any or Explicit ambient + observed Tc, not an unsupported negative toggle.

Existing ambient summary values are checked against raw, same-result positive
Observed evidence. Unsupported `tc_ambient` is hidden, not replaced with a new
maximum; `ambient_sc` becomes unknown rather than false. This applies to list,
detail, variants and bookmarked-material reads, including missing record arrays.
It does not mutate the stored catalogue or release a validated training label.

Catalogue sorting still uses its declared summary field (`tc_max`, `tc_ambient`,
year or paper count), not the highest matched-result value. A matching witness can
therefore differ from the headline. The UI states this and exposes witness data;
the atomic per-property selection redesign remains SC02.

Pairing, structure-phase and other existing catalogue descriptor controls remain
catalogue-level filters. Only the family/Tc/pressure/evidence filter group claims
same-result semantics. No missing sample/state relationship is manufactured.

## Query execution and performance boundary

SQL applies existing visibility rules and safe necessary-condition family/APS
prefilters. Family prefilters retain either entity-family or record-family hits;
JSONPath literals are JSON-escaped and bound as values. Final admission always
uses the canonical predicate, not independent catalogue maxima.

When a scientific filter is active, qualifying candidate rows are streamed in
batches of 128. Every candidate is evaluated before counting; offset/limit are
applied to matching rows, so `total` is exact for that query transaction, not a
truncated scan count. Stream cleanup runs even if evaluation fails. Unfiltered
lists retain database count and ordinary pagination.

This bounds row-batch memory, **not total work or latency**. A broad Tc/pressure
query without selective family/APS filters still scans the visible candidate set;
a single large record array can also be large. No production load benchmark or
index-performance claim is made. Before enabling this path at production scale,
measure real row/record distributions, p95 latency and concurrency; a versioned,
indexed result projection is the preferred next optimization. Such a projection
must pass parity tests against this predicate and invalidate on parser, pressure,
origin and outcome policy versions. Do not improve speed by silently relaxing the
same-result or unknown-pressure rules, capping total, or skipping raw evidence.

## Timeline and UI

Migration `0048_pressure_projection` follows `0047_claim_integrity`, adds derived
pressure metadata and policy readiness fields, and invalidates the old projection.
Refresh/read/health check both pressure and origin versions. Ambiguous legacy zero
is not merged with explicit ambient or a reported nonzero pressure merely because
rounded values coincide. The numerical legacy scalar is null when pressure is
unresolved; full typed interpretation remains alongside it.

Cache keys and `data_version` include policy identity. Timeline validates caches
using body ETags; it deliberately does not emit Last-Modified or return 304 from
If-Modified-Since alone, because a policy change can alter the representation
without changing source timestamps. Source update time remains in the JSON body.

Materials, paper detail, hydride evidence, Search witnesses and Timeline use
English labels distinguishing explicit ambient, reported pressure, missing and
unresolved pressure. A legacy scalar without versioned metadata is unverified,
not an ambient assertion. Timeline's outline legend says reported non-zero
pressure, not high pressure; 1 atmosphere is not mislabeled high pressure.

## Rollout and remaining work

1. Review/merge code and run locked Linux CI; do not deploy the entire existing
   dirty worktree indiscriminately.
2. Run an authorized real-data impact/performance audit. Existing fact-vector
   sentences are unchanged and may still reflect older assumptions until a
   separately reviewed rebuild.
3. Run the claim-integrity preflight; do not auto-repair incompatible scientific
   values. Coordinate schema migrations before new refresh code and frontend.
4. Rebuild the derived Timeline projection and test fallback/policy changes;
   source records are not rewritten by these migrations.

Review visibility/retractions, true scientific occurrence deduplication, Timeline's
legacy 300 K cap, publication/measurement-year distinctions and paper-only update
invalidation remain SC03/SC06/SC07/SC08. These changes do not complete phase A,
produce an ML-ready dataset, establish scientific truth, or calibrate RPS.
