# Source-scoped current material views

Issue: [SC08 / #66](https://github.com/JackZH26/SCLib_JZIS/issues/66).
Implemented locally on 2026-09-09; schema head remains `0068_answer_evidence`.
This is a read-policy change, not a migration, source reinstatement, scientific
adjudication, approved training dataset or deployment.

## What changes

A material can contain both a held source and a different explicitly active
source. The earlier `material-visibility/1.0.0` policy hides the entire material
from default reads. The conditional `material-visibility/2.0.0` policy instead
admits a nonempty, exact partition of unheld reported records, provided that all
material, ancestry and provenance gates still pass.

This does not establish that sources describe the same physical state or are
independent replications. Retraction is not proof that a material cannot
superconduct. An unknown source is not a retraction, but cannot contribute to
the new scoped selection. A restored publication status does not remove a
persistent Paper/Work lifecycle review hold.

| Situation | Current behavior |
| --- | --- |
| Ordinary material without a separable source hold | Existing v1 behavior |
| Explicit source hold plus exact active unheld records; all global gates pass | Conditional v2, eligible records only |
| Only held sources, no eligible records, or no complete source partition | No v2 admission; existing held/Archive policy |
| Existing material `needs_review`, disputed/retracted status, or a held parent | Never cleared or bypassed |
| Provenance quarantine, including a quarantine in an excluded record | Still blocks public Catalogue and Archive access |
| Missing, cyclic or over-depth ancestry | Still fails closed |
| Over-budget or noncanonical scoped input | Explicit unavailable-assessment fallback, never a partial v2 grant |

## Exact private partition and public schema

The read adapter obtains live lifecycle state using exact Paper IDs and the
existing accepted Paper/Work mapping policy. It never establishes identity by
formula, title, citation text or a model-generated assertion.

The internal immutable `SourceScope` retains every original record position,
raw-content hash, source identifier, eligibility decision and fixed exclusion
code. Its fingerprint binds the original visibility revision, complete raw
inventory, source state and selected anomaly assessment. The material review
revision in turn binds that fingerprint and its parent revision. Original raw
record arrays are neither edited nor renumbered.

Consumers verify the original inventory before selecting records. The private
object has a process-local integrity seal to detect field replacement; that is
not a persistent review signature, researcher credential or scientific approval.
The object and source identifiers are not serialized in the public scope.
Overlong or SQL-unrepresentable raw Paper identifiers stay unresolved and are
never sent to the SQL lifecycle resolver, so they cannot crash unrelated reads.
Legacy SQL-compatible IDs containing whitespace/control characters are queried
exactly as stored, without trimming, to retain their negative lifecycle state;
they remain ineligible for the new strict v2 source inventory.
The adapter separately retains the legacy nonempty-string source inventory for
the unchanged v1 fallback. In particular, a key exceeding v1's 500-character
metadata limit still produces its original invalid-metadata hold; sanitizing SQL
inputs cannot silently convert it into permissible unknown source knowledge.
When a genuine mixed-source partition is possible, a malformed record may
be excluded alongside the held source without invalidating the other exact,
active records. Both the original hold and raw inventory remain fingerprinted.

`visibility.source_scope` is a closed object:

```json
{
  "version": "material-source-scope/1.0.0",
  "status": "eligible_records_only",
  "total_records": 3,
  "eligible_records": 2,
  "excluded_records": 1,
  "eligible_source_count": 2,
  "fingerprint": "<64 lowercase hexadecimal characters>",
  "independent_support_count": null
}
```

The counts above are an illustrative schema example, not production statistics.
Counts must be positive integers, sum consistently, and remain within the
5,000-record bound. Source count cannot exceed eligible record count. The
partition is bounded to 4 MiB canonical input, depth 32 and 100,000 JSON nodes.
Source/occurrence wire DTOs remain v1; direct current material DTOs conditionally
use v2. A public dictionary cannot replace the trusted private partition.

## Values, filters and Archive

The current property policy is `source-scoped-atomic-selection/1.0.0`. It applies
only to a verified v2 context; v1 and historical compiler behavior are unchanged.

- A cached headline from an excluded source is not retained or used as a
  selection hint. Recompute from eligible atomic records.
- Tc headline selection prefers a resolved observation, then a resolved
  calculation, with the existing deterministic result/value ordering. Unknown
  origins remain retained evidence, not an observed headline.
- Experimental, calculated and explicit-ambient Tc views use their existing
  per-result origin, numeric, outcome, pressure and anomaly gates. A missing
  pressure cannot become ambient; non-detection cannot become Tc = 0.
- Conditions, source, state and method travel with the selected value. Separate
  columns are not a synthetic joint observation; existing EPC same-state/run/
  protocol rules remain in force. No mean or median is manufactured.
- Classification and structure proposals use the same eligible partition.
  Pending text structures remain proposals, not approved coordinate structures.
- `total_papers` in v2 means eligible bibliographic source membership, not
  independent experiments. Legacy `arxiv_year` and `best_credibility_tier` are
  null because this change does not rebuild a trustworthy current bibliography.
- The `min_papers` threshold is evaluated after current scoping, avoiding both
  stale undercounts and stale overcounts. A stale zero does not classify a
  source-scoped material with eligible records as an empty skeleton.
- List ordering is now `sort_basis=current_projected_catalogue`: sort by the
  actual current displayed field, descending with nulls last and exact material
  ID as tie-breaker, then paginate. An excluded historical 120 K cannot place a
  current 30 K material ahead of a current 60 K material. A bounded heap retains
  at most `offset + limit` summaries, although evaluation still visits all
  candidate rows. This is not a research-priority score or a production latency
  benchmark. The old `legacy_catalogue` literal remains parse-compatible.

Scientific filters use the original array's result IDs/indices and then apply
the same eligible partition. Detail retains all allowed original records and
the bounded raw Archive; each record has its own eligibility metadata. Excluded
records cannot inherit the material's eligible badge. Existing private-note and
structured-source redaction remains in place.

Phase diagrams and hydride enrichment use the same scope. An enrichment row
requires its own exact eligible source and still passes its independent
validation/anomaly gates. For a v2 material, `include_pending` does not reinsert
excluded source values into current quantitative views; inspect its detail
Archive for those records. Only-source v1 Archive behavior is unchanged.

## Timeline, retrieval and history

Timeline extracts from the current eligible records, retaining content-derived
point IDs. The older rebuildable projection does not contain a source-scope
contract, so a qualifying v2 material triggers the canonical raw fallback; an
old projected point is not treated as authorization. This favors correctness
over claiming an unmeasured projection-performance improvement. Responses bind
all current points/governance revisions before sampling/pagination and indicate
v2 when the complete returned dataset includes v2 points. Source-only changes
therefore change the dataset version and conditional response, even without a
material timestamp change. HTTP cache namespace is `v10-source-scoped-results`.

Paper/Chunk occurrences explicitly linked to a v2 material must resolve to an
eligible exact containing Paper. A missing raw `paper_id` may use that verified
container; a conflicting explicit ID is rejected. A Paper/Chunk raw hash is not
compared to the differently enriched `Material.records` hash. Formula-only
occurrences are not silently linked.

Paper detail, search, Ask, exact scientific lookup, selected-source currentness,
claim responses and current-history metadata pass the same private context and
container identity. Each scoped occurrence also passes its own anomaly check
with the trusted material's family/compound thresholds: one good record cannot
approve a different anomalous record from the same paper. Held or unresolvable scoped occurrences remain warned
Archive records where existing access policy permits, but cannot satisfy a
scientific filter. Private Ask selection digests bind material review revision,
so changing eligible source membership cannot masquerade as the same input.

Saved answers/0068 receipts and frozen ML release bytes are not rewritten or
retroactively revalidated. Current source metadata remains explicitly separate.

## Audit and operation

Nightly source-rule candidates and raw anomaly findings remain visible and
counted. A freshly verified source-scoped material does not acquire a new global
`needs_review` flag solely from the separated source hold or an anomaly confined
to its excluded records. Suggested actions identify the source-scoped case.
Existing flags/reasons remain sticky; other audit rules are unchanged.

No background job is run against production by this implementation. Scope
decisions are request-local current reads, not source correction, distributed
refresh acknowledgement or an observed propagation SLA. English UI warnings
state the limited record scope and explicitly disclaim scientific approval and
independent replication. Scientific SEO remains conservative: v2 does not emit
an approved-looking scientific SEO summary.

## Remaining limits

SC08 remains open pending repository delivery/CI and its remaining operational
and scientific acceptance gates. Existing blanket material holds are **not**
automatically cleared; a source-scope display policy is not permission to undo
historical review decisions. Positive exact-version scientific reinstatement,
full downstream propagation/SLA, current reviewed ML/RPS acceptance and
production canary rollout remain separate tasks. This batch makes no claim
about how many real SCLib materials will qualify until an authorized production
inspection is performed.
