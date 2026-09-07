# Sixteenth implementation batch — indexed exact-source impact inspection

Date: 2026-09-07. Branch: `codex/sclib-research-v2`.
Base checkpoint: `ac60417` (negative source lifecycle governance).
Priority: [SC08 / #66](https://github.com/JackZH26/SCLib_JZIS/issues/66).
Contract: [Exact-source impact inspection](../../SOURCE_IMPACT_INSPECTION.md).

## Outcome

This batch adds an operator-only way to inspect explicit source dependencies,
including record-backed materials with no Timeline points, and compare a
deterministic relationship inventory across source changes or graph edits.
Six additive reverse indexes support the bounded lookup paths. The current
database head is `0057_source_impact`; no new scientific data table is added.

The delivered object is a read-only impact plan, **not** an immutable execution
receipt or an operational refresh queue. No request is enqueued or marked
completed. The existing global Timeline loop and separate best-effort cache
invalidation cannot establish an exact-event cross-system completion guarantee;
execution tracking is deliberately left for the next bounded implementation.

No source hold, scientific claim, ML label, historical capsule or saved answer
is changed. No production migration, external source query, push or deployment
occurred. Existing site-owned copy and new endpoint messages are English.

| Area | Implemented | Not claimed |
| --- | --- | --- |
| Exact source anchor | Current event ID/hash and source snapshot binding; Paper versus accepted Work mapping | No same-Work sibling spread from a Paper event, formula/title or malformed-ID inference |
| Current impact | Explicit claims, records, descendant governance, direct chunks/hydrides, old projection rows, ML memberships | No full transitive feature/event/source-import lineage |
| Timeline candidates | Raw record-backed material discovery plus descendants | No dependence on an existing point or timestamp-only signal |
| Historical references | Reached-object frozen pins and publication proposal references | No row-body disclosure, withdrawal notice or scientific/publication approval |
| Manifest | Bounded sorted IDs/relationships, scope, graph fingerprint and separate observation | Not a target scientific-row hash, authenticated decision or durable receipt |
| HTTP | Explicit research grants in an RR/READ ONLY snapshot; private no-store; sanitized limits/errors | No anonymous exports, write route, grant provisioning or cache-based access |
| Migration | Six index additions; row-preserving populated-history round trips | No production latency, lock-duration, disk or SLA benchmark |

## Review decisions

An unchanged source event does not imply unchanged dependencies. Therefore the
manifest binds the observed graph and explicitly labels its currentness as
`current_in_database_snapshot`. Changing a covered relationship under the same
source head changes the fingerprint. No future worker should trust an old plan
without checking both source and graph currentness.

Material context from a claim is separate from record-supported material
propagation. Only explicit record-backed roots drive inherited parent-governance
closure. Existing inactive Timeline rows are inspectable references, not new
scientific results. ML memberships and frozen references remain review candidates,
never permission to rewrite frozen labels or publish raw source content.

Independent review emphasized explicit supported/unsupported scopes, exact
typed identifiers, connected ancestry cycle/depth handling and the difference
between descriptor and full-response size budgets. The HTTP tests check real
authorization and dedicated snapshots rather than replacing authentication with
an application-wide test override.

## Verification

All data are synthetic. PostgreSQL and Redis checks run only through the guarded
disposable native runner; ingestion auxiliary tests use unreachable placeholder
DSNs. No repository production connection settings are inherited.

Final checks:

| Check | Result |
| --- | --- |
| API full suite | 2,015 passed |
| New focused core / HTTP / index cases | 25 / 18 / 7 passed; included in the full API total |
| Ingestion full suite | 938 passed |
| Scripts | 264 passed, plus 36 separately reported subtests |
| Frontend source / unit suites | 35 / 247 passed |
| Distinct ordinary tests | 3,499; focused reruns not double-counted; excludes 36 script subtests |
| TypeScript | `tsc --noEmit` passed |
| Migration rehearsal | Actual 0057 head/admission, index definitions/readiness, populated-history index-only round trip, legacy row preservation and all prior independent history guards passed |
| Static checks | Scoped Ruff I/F and `git diff --check` passed |

The API suite reports the existing FastAPI `regex` deprecation and 19 Alembic
legacy path-separator warnings. Ingestion retains 34 PostgreSQL `DISTINCT ON`
warnings from its SQL-compilation doubles. These synthetic checks do not replace
real-data staging, scientific/rights review or production performance measurement.

The migration rehearsal checks the actual six index definitions, validity and
readiness; all prior independent nonempty-history downgrade guards; old
freeze/publication/withdrawal/source-lifecycle flows; and index-only removal and
recreation with every pre-existing application row preserved. An initial harness
failure came from attempting strict schema admission on a connection already in
an implicit transaction; using a fresh admission connection corrected the test
without changing or weakening the production admission gate.

## Remaining priority

Next implement a bounded durable request/attempt/receipt protocol for a specific
refresh target, with exact source/graph bindings, stale/superseded handling and
retry evidence. Only then connect executors and define measured completion/lag.
Broader lineage coverage, positive source reinstatement, canonical scientific
supersession, mixed-result admission, RG02, RPS linkage and reviewed staging cases
remain unfinished. SC08 is not closed by this batch.
