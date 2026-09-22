# ML01: temporal consumer contract

This is an implementation contract, not a completed historical dataset or a
claim of first discovery. Synthetic dates in tests describe no real material.

## Four different times

- A **work date** is a bibliographic hint shared by a scholarly work's versions.
  It cannot establish when an individual Tc result, structure, or feature became
  public. Work grouping is still required for split-leakage control.
- A **source-version public time** belongs to one resolved version. Its exact
  captured representation, byte hash and result locator must be bound through
  the server-side source registry before it can support result availability.
- A **result known-by time** is the earliest qualified source-version witness
  for that exact result. It is a conservative upper bound on availability, not
  proof that the result was first introduced on that date. A later version
  cannot backdate a newly witnessed result to the work's first submission.
- **Captured at** is the local observation time, separate from public knowledge
  time. A verified 2001 version captured in 2026 may support a retrospective
  public-knowledge view of 2001. It does not prove that the local system had
  captured that version in 2001.

The policy requires timezone-aware instants. Date-only or naive timestamps are
not silently interpreted as midnight UTC. A date-precision import needs a
separately justified availability bound; the consumer does not invent one.

## Public claim reads

The existing ML Foundation feature flag remains off by default. No production
release is enabled by this change. When enabled against the migrated registry:

```text
GET /v1/claims?cutoff=2020-06-01T00:00:00Z
GET /v1/materials/{material_id}/claims?cutoff=2020-06-01T00:00:00Z
```

`cutoff` is inclusive and normalized to UTC. Only a complete, server-resolved
`known_by` provenance assessment at or before the cutoff is admitted. Unknown
and uncertain times are excluded even with `include_pending=true`. Existing
source/material/claim visibility rules still apply; a time witness cannot
override a retraction, correction, quarantine or other current hold.

Each claim exposes `temporal_provenance` (`temporal-provenance/1.0.0`) with its
status, basis, known-by/public/capture instants, public witness identifiers,
hashes and bounded source coordinates. Private review references, notes,
source excerpts and storage URIs are not part of the public response.

The compatibility `available_at` field is now only the UTC date of a qualified
result known-by timestamp, otherwise `null`. **Do not use this date-truncated
alias for instant-level cutoff comparisons.** The former stored value remains
`legacy_available_at`, explicitly not revision-verified. A Work response's
`available_at_basis` similarly identifies its date as a work-level legacy hint.
Neither `raw_record`, extraction metadata nor a supplied public provenance
envelope can authorize a result time. A registry database failure returns
`503 Temporal provenance registry unavailable`, not a fabricated empty/known
provenance result. Claim reads and these failures are `no-store`.

Collection responses label `temporal_filter.scope=live_claim_known_by_filter`.
The UUID cursor continues scanning past time-ineligible rows; the next cursor
is the last returned row, not the lookahead row. This is a **live read filter**:
review changes and new witnesses can change later requests. It does not pin a
snapshot, reconstruct historical review state, freeze an input closure, or
establish historical ML training eligibility.

At most 5,000 claim rows are hydrated and assessed per request. At that boundary,
one ID-only query may confirm EOF. If there are more rows and no complete eligible
page has been established, the API returns an explicit `503` with `no-store` and
guidance to narrow material/work filters. It does not return a false empty or
apparently complete partial page. This cap is not a global rate limit or a database
statement timeout.

## Offline dependency gate

The byte-identical API/ingestion `temporal_snapshots.py` module provides:

```python
evaluate_temporal_snapshot(
    nodes, cutoff=aware_instant,
    resolve_provenance=server_registry_resolver,
    mode="public_knowledge",
)
```

Every node explicitly declares `dependency_ids` and
`dependencies_complete=True`. An empty dependency list is an explicit leaf
declaration, not a default assumption. The node payload has no provenance
field: the caller must supply an independent, trusted resolver. Calling this
function with an untrusted resolver cannot authenticate the returned dates.

For a node and its entire declared dependency closure:

```text
effective result time = max(own qualified known-by time,
                            all dependency effective result times)
admit = complete known lineage AND effective time <= cutoff
```

The node's own time matters: early inputs do not prove that a later calculated
result was available earlier. A recent deterministic feature recomputation is
not automatically a historical public result. A separate, preregistered feature
reconstruction policy would have to pin the algorithm, constants, external
tables and input versions; this gate does not create that policy.

The optional, separately named `operational_capture` mode also takes the maximum
capture time across the chosen node witnesses and dependencies. Missing capture
times hold operational admission but do not erase a known public-knowledge
bound. The provenance resolver may choose the earliest-public witness rather
than the earliest-local-capture witness; operational exclusion is conservative
and is not proof that an earlier local capture did not exist.

Unknown/uncertain provenance, incomplete assessments/declarations, missing
dependencies and dependency cycles hold the affected node and descendants.
Cycles do not invalidate an unrelated acyclic component. Limits are explicit:
10,000 nodes, 50,000 edges, 200 dependencies per node. Malformed or over-budget
graphs fail the whole call; they are not silently sampled. Evaluation is
iterative, deterministic under input reordering, and does not mutate inputs.

Returned counts retain every declared node in the denominator. Reason counts
are multi-label and must not be added to obtain a unique excluded-node count.
The report says `scientific_acceptance=false`,
`reproducible_snapshot_established=false`, and
`llm_pretraining_contamination_assessed=false`.

The caller must include every input actually used: target claim revision,
feature claims/properties, material-state/sample associations, structure parent
chains, source artifacts, and run inputs/settings/model or policy versions.
`context`, `supports` or `refutes` edges used by a feature are dependencies too.
Conversely, an unrelated later citation must not be treated as a dependency of
an earlier unchanged result. This function checks the **declared** graph; it
does not discover missing scientific dependencies or implement concurrent
database DAG integrity and immutable closure freezing (ML04).

## Consumers that are not historical snapshots

- Search `year_min`/`year_max` operate on bibliographic Chunk/index year fields.
  They are not result/source-revision availability filters. No historical
  search guarantee is added here, and ANN metadata is not an authority for
  future strict temporal retrieval. A future implementation must recheck exact
  source revisions after hydration and before returning snippets or RAG input.
- Ask has no supported historical cutoff contract. Prompting the model to
  answer "as of" a year is not a database temporal filter.
- Existing RPS release `artifact.available_at`/`evidence_cutoff` checks compare
  bundle-declared artifact times. They are not retrofitted with source-registry
  witnesses by this batch and must not be represented as verified result-time
  screening.
- Existing ML snapshot manifests/examples remain separate release objects.
  This gate does not automatically backfill them, validate their arbitrary
  `filters` metadata, or advance their release status.
- The legacy source exporter contains bibliographic dates, not a complete
  version/capture registry. Such an export alone cannot produce qualified
  historical result timestamps.

Retrieval cutoffs do not assess, remove or prove absence of LLM pretraining
contamination. Model-training provenance, split construction, scientific and
licensing review, frozen dependency manifests, and a prospective evaluation
remain independent requirements.

## Minimum regression matrix

| Fixture | Required outcome |
| --- | --- |
| v1 before cutoff; v2 first witnessed Tc/structure after cutoff | Later result and every dependent feature excluded; earlier independent result retained |
| Same result witnessed in v1 and v2 | Use earliest qualified occurrence; retain all occurrences, one work split group; do not infer first discovery |
| Only old work date or raw/extraction `available_at` | Unknown result time; no strict admission |
| Pending/invalid version witness or incomplete provenance | Uncertain/held; no partial-known max fallback |
| One unknown/missing input among early inputs | Node and descendants held; denominator retained |
| Self, two-node, multi-hop cycle; unrelated leaf | Cycle closure held; unrelated leaf eligible |
| Node's own result later than all inputs | Use later own time |
| Public version early, capture late or missing | Public and operational modes remain distinct |
| Exact boundary / timezone offset / date-only | Inclusive normalized boundary; date-only rejected |
| More than one API scan batch of ineligible claims | Cursor returns only eligible rows without skipping lookahead |
| Known time plus current source/material hold | Visibility still holds the claim |
| Source registry failure or oversize graph | Explicit failure; no legacy-date or truncated-graph fallback |

The graph suite tests synthetic resolver outputs; consumer API tests inject
synthetic typed witnesses to isolate read behavior. Source-registry integration
tests separately establish persistence, exact bindings and review gates.
