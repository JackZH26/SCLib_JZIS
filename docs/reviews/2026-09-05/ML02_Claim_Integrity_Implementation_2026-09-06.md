# ML02: claim integrity and contradictory-outcome quarantine

Date: 2026-09-06

Issue: ML02 / #43

Status: local implementation and disposable PostgreSQL verification complete; not deployed

## Scope and changes

This change strengthens the admission rules for typed claims and ML target identity. It does not infer that a scientifically valid negative experiment has occurred, promote imported records to accepted status, build a training dataset, or repair production data.

| File | Change |
| --- | --- |
| `api/models/claim_integrity.py` | Versioned 0047 constraint registry and read-only incompatible-row audit. |
| `api/alembic/versions/0047_claim_integrity.py` | Forward migration from `0046_result_origin`; preflight, bounded write lock, additive CHECK/unique/composite-FK constraints, no value repairs. |
| `api/models/db.py` | Append the 0047 registry after the research-v2 tables have been registered; no claim column redefinition. |
| `api/services/claim_outcomes.py` | Independent, standard-library-only outcome shape and positive-veto helpers. |
| `ingestion/ingestion/claims/outcomes.py` | Byte-identical ingestion copy, enforced by a test because API and ingestion ship independently. |
| `ingestion/ingestion/claims/mapper.py` | Quarantine conflicting outcome/value or outcome/origin interpretations, inspect conflicting positive markers, preserve raw evidence, version mapper as `legacy-material-record/v1.3`. |
| `api/tests/test_claim_integrity.py` | Real PostgreSQL constraints, migration compatibility/preflight, and helper parity tests. |
| `ingestion/tests/test_claim_outcome_integrity.py` | Pure mapper/helper outcome, origin, alias and source-identity regression tests. |

The historical migration files and `api/models/research_schema_v2.py` were not changed for ML02. Its existing finite/value-shape/state checks were verified against PostgreSQL rather than rewritten. Mapper pressure normalization belongs to the parallel SC04 change and was not edited here.

## Database invariants

1. `explicit_ambient` and `reported` pressure require a non-NULL numeric value. Existing rules still require explicit ambient to equal 0 GPa, permit `not_reported` with NULL, reject non-finite pressure, and preserve the existing ambiguous-state representation.
2. An accepted `non_transition` claim requires explicit `not_detected`, a compatible value shape, a finite nonnegative minimum tested temperature, and a nonempty, non-placeholder measurement method. It cannot bypass this rule through `unknown` or `inconclusive` result status.
3. An accepted negative rejects `primary_theoretical` evidence and an explicitly declared Computed, Inferred or AI-Proposed origin in `extraction_metadata.result_classification.knowledge_origin`. Missing/unknown legacy origin is not evidence of experimental provenance; its scientific review remains mandatory.
4. `(ml_examples.claim_id, ml_examples.material_id)` references the same `(material_claims.id, material_claims.material_id)` pair. The composite foreign key uses `MATCH FULL`, `ON UPDATE RESTRICT`, and `ON DELETE RESTRICT`. Independent existence of the two identifiers is insufficient. Cross-material insert, example update and parent-claim reassignment are tested.
5. Existing v1 and v2 numeric/shape checks continue to reject NaN, both infinities, missing required point/bound fields, contradictory populated fields and reversed intervals. Optional measurements remain NULL when unknown.

## Accepted result compatibility

The table is a storage-integrity contract, not an experimental verification or training-label policy. All rows remain subject to the numeric and value-shape constraints.

| Property type | Result status | Relations permitted when accepted | Additional conditions |
| --- | --- | --- | --- |
| `tc` | `observed` | `exact`, `interval`, `lt`, `le`, `gt`, `ge` | A source may explicitly report a transition using a bound; this alone does not establish experimental origin. |
| `tc` | `unknown` / `inconclusive` | All seven relations | A reviewed uncertain interpretation can be stored, but is not thereby a positive or negative training label. |
| `tc` | `not_detected` | None | The negative outcome must use the negative property type. |
| `non_transition` | `not_detected` | `unreported`, `lt`, `le` | Minimum tested temperature, actual method, and no explicit theoretical/computed/inferred/AI-origin contradiction. |
| `non_transition` | `observed` / `unknown` / `inconclusive` | None | Prevents a negative-property shortcut around outcome constraints. |

Pending, disputed, retracted and excluded records may preserve an outcome contradiction for review, but still cannot violate the basic finite/value-shape/identity constraints. A pending record with contradictory raw evidence must not enter accepted negative data.

For a negative record, `unreported` has no numeric Tc fields; `lt`/`le` have only a finite nonnegative upper bound. An upper bound alone is not proof that superconductivity was searched for and not detected. An exact Tc, interval or lower bound combined with an explicit negative outcome is mapped to `inconclusive` / `tc` and retained pending review; its numeric values and raw source are preserved. Explicit Computed, Inferred or AI-Proposed negative interpretations are also quarantined rather than presented as experimental non-detections.

## Shared helper boundaries

`negative_outcome_issues(claim)` consumes canonical v1 claim fields. An empty tuple means only that explicit negative status, property type, value shape, minimum tested temperature and method can be represented consistently. It does **not** validate detection sensitivity, experimental origin, pressure applicability, sample identity, evidential sufficiency, source truth, review approval or ML label eligibility.

`outcome_conflicts_with_positive(record)` is a veto only. It checks every `result_status`, `outcome_state` and `outcome` alias, plus negative boolean markers. An earlier positive string cannot hide a later negative or inconclusive marker. Explicit unknown/unreported status also prevents inferring a positive from Tc alone. Boolean tests require actual booleans, not strings or numeric substitutes. Returning false supplies no affirmative evidence, and returning true does not establish a negative experiment.

The mapper uses the positive veto as well as the API-facing copy. All recognized nonpositive aliases are covered in each of the three status fields. API consumers must still independently enforce origin, pressure, source and review policy.

`result_classification` and `pressure_semantics` are reserved derived API envelopes excluded from source-record identity. Raw envelopes remain preserved, while adding/changing these annotations does not change a claim UUID/hash. Real scientific/raw fields remain part of the source identity. This supports an API-export round trip without making derived annotations authoritative source evidence.

## Preflight and migration behavior

The migration obtains a write-excluding table lock over the affected claim/example and audited v2 tables with a five-second lock wait. It then audits all existing CHECK expressions on `material_claims`, `material_states` and `event_properties`, plus the new constraints and target-pair mismatches. An incompatible record aborts the transaction before constraint installation; no pressure is filled with zero and no evidence is deleted or relabeled.

The audit reads PostgreSQL's original expressions with `pg_get_expr(conbin, conrelid)` and checks `IS NOT TRUE`. This is intentional: a SQL NULL must not silently satisfy a required-value rule. It does not use SQLAlchemy's reflected `sqltext`, because the installed reflection implementation was observed to remove an unmatched pair of parentheses from an `ALL`/`OR` CHECK expression, altering precedence when reused. The populated compatibility fixture covers every legitimate value shape, valid pressure states, and nullable optional columns to guard against rejecting ordinary missing data.

Reports contain the schema/version, compatibility flag, table/rule identifiers, counts, and at most 20 sample row IDs per rule. They contain no raw evidence or source-record text. Counts are **per rule** and must not be summed as a number of distinct incompatible records. Missing required constrained tables cause the preflight to fail.

The downgrade removes only the newly added constraints; it does not rewrite or delete data. After release, the 0047 contract module must remain frozen like the historical v2 registrar; subsequent changes require a new migration/contract.

## Verification evidence

All database runs used the EN01-owned disposable native runner: a newly created local PostgreSQL cluster and Redis instance with fresh restricted credentials, ownership markers and isolated ports. No existing local service, production/remote database or deployment was accessed. All created test services and temporary test data were removed by the runner.

Environment: Python 3.12.14; preinstalled Homebrew PostgreSQL 16.13 and Redis 8.6.1. Docker and Python 3.11 CI execution were not demonstrated by these local runs.

### Targeted API/database regression

From the repository root:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py \
  --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server \
  --suite api -- -q \
  tests/test_claim_integrity.py \
  tests/test_ml_foundation.py \
  tests/test_ml_foundation_schema.py \
  tests/test_research_shadow_schema.py
```

Result: **223 passed**, one existing FastAPI `regex` deprecation warning, 9.96 seconds. Includes the 112-case property/status/relation/validity matrix, non-finite and shape boundaries, target identity insert/update checks, successful populated forward migration, and a rollback-only reproduction of incompatible 0046-era rows with unchanged before/after data.

### Mapper and helper regression

From `ingestion/`:

```bash
.venv/bin/python -m pytest -q \
  tests/test_claim_outcome_integrity.py tests/test_claim_mapper.py
```

Result: **116 passed**, 0.10 seconds. The two earlier pressure-fixture failures were resolved by the SC04 owner before this final run.

### Migration chain

From the repository root:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py \
  --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server \
  --suite migrations
```

The empty-database chain passed through the current head `0048_pressure_projection`, including a compatible 0047 preflight, migration-head check, restricted-role check and auth-schema check. The separate populated tests exercise 0047 compatibility and failure behavior; an empty migration run alone would not establish that behavior.

Ruff passed for all new ML02 Python modules/tests. The main agent owns the final whole-repository regression after parallel changes are integrated.

## Remaining rollout and research gates

- No production incompatibility count is known. Run an explicitly authorized, controlled preflight and review every incompatible source before scheduling deployment. Multiple CHECK scans and migration table locks require a workload-specific maintenance plan; production duration was not measured.
- v1 has no independent typed knowledge-origin column. The new explicit-role/metadata veto is defense in depth, not proof that an unknown legacy claim is experimental. Cross-table event-origin agreement, reviewed source evidence and release admission remain the v2 loader/review responsibilities; no cross-table trigger was introduced in this issue.
- A Tmin and method name do not quantify negative-experiment quality. Detection limits, sample/phase identity, pressure window, measurement capability and task-specific censoring must be reviewed before a negative becomes an ML example.
- `accepted` alone is never a dataset inclusion rule. Unknown/inconclusive claims, Computed Tc, retractions, disputed data, duplicates and unavailable historical results require the appropriate task/origin/revision/split policies.
- No new automatic acceptance, production backfill, training release, licensing decision, deployment, commit, push or remote issue closure was performed.
