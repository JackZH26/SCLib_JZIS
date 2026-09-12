# Batch54 — independent ML workflow membership and currentness

Date: 2026-09-12. Base HEAD: `00718749b6eb15926ae8cbfc58e02a9432488815`.
Branch: `codex/sclib-research-v2`. Prior uncommitted batch52/53 work is preserved.
Tracking: ML07 #68 as a related authorization dependency; ML06 #70 and ML09 #76
remain blocked from genuine dataset execution by purpose-specific permission
and run-approval work. No issue is closed by this increment.

## Delivered outcome

SCLib now has a separately versioned, opt-in ML workflow membership registry.
It is the first online authorization foundation following the private baseline
preparation CLI, **not** a completed source-use or model-training authorization
system. A site administrator can preview, grant, revoke, regrant and recover
exact historical membership decisions. A verified user can inspect current own
membership without needing a pre-existing ML role.

The three roles are `requester`, `rights_reviewer` and `run_approver`. No existing
curator/reviewer/publisher/admin identity is automatically converted into one.
Role overlap and explicit admin self-assignment are allowed at this stage;
neither establishes independent human approval. Source/run decisions still
need their own distinct-actor and exact-scope policies.

Every role result is explicitly membership-only. Data access, source permission,
run authorization and all six existing authority flags remain false. Actual
`run_baseline_dataset` continues to reject before parsing/fitting. The fixed
synthetic numerical rehearsal and offline preparation contracts are unchanged.

The complete [operator and API contract](../../ML_USE_GOVERNANCE.md) documents
examples, currentness semantics, limits, recovery and remaining authority gates.

## Implementation

| Layer | Concrete change |
| --- | --- |
| Schema | New `ml_use_role_decisions` and migration `0071_ml_use_roles`; no memberships are seeded |
| Native integrity | Closed roles/actions, per-actor idempotency key, one root/successor, same-account/role alternating chain, Python/PostgreSQL hash agreement and current declared actor/target checks |
| Service | Rollback-only preview, exact intent/predecessor commit, no-op historical replay, authenticated current inspection and exact current grant-ID check |
| API | Four private routes under `/v1/ml/use`, JWT/browser-session admission, independent default-off feature flag, current session/admin recheck, bounded parsing/output/time/concurrency and sanitized errors |
| Audit retention | Both target and issuing actor are retained by exact restrictive foreign keys and existing account-deletion preflight |
| Migration safety | Empty downgrade/upgrade keeps all prior rows; nonempty downgrade refuses even if the membership was revoked |
| Compatibility | Fresh actual native Discovery capture against current backend inputs; original batch52 capture preserved byte-for-byte |
| Operator documentation | New ML membership contract, `.env.example` default-off flag, baseline/readiness/index updates and this report |

The existing SERIALIZABLE publication fence and epoch coordinate writers.
Reads use read-only REPEATABLE READ. The HTTP transaction commits only after
bounded response serialization; the service itself never commits its caller.
For a lost commit response, the same actor/request key/intent can recover the
durable event. Replaying an old grant after a revocation does not re-enable it.

Currentness is not inferred from a historical response. It requires a latest
grant and an active, verified target in the checked snapshot. Target disablement
suppresses roles without erasing history; re-enabling restores an unretracted
grant. Explicit revocation is the permanent withdrawal path. The issuing
administrator's later status does not automatically revoke past memberships.

The SQL checks validate a declared administrator, not the authentication of
arbitrary SQL callers. These are application integrity controls, not a defense
against a privileged database owner disabling guards.

## Verification

| Check | Final observed result |
| --- | --- |
| Broader native API regression: ML roles, research access, audit retention, schema lifecycle, baseline preparation and snapshot boundaries | 169 passed; 151.83s |
| Final complete new ML-role module plus Discovery main-barrier module | 117 passed; 87.18s |
| Full scripts suite after final migration-harness correction | 1,777 passed; 36 subtests passed; 76.08s |
| Complete native migration rehearsal | Passed; 0071; 82,785ms; 645 source pins; owned cleanup verified |
| New API files' configured Ruff checks and migration-harness/source-test F/I checks | Passed |
| Fresh native wire content and 258 backend source pins | Independently verified |
| Full frontend component suite with two workers | 1,353 passed across 40 files; 97.40s |
| Frontend source checks, including English-default copy/locale | 38 passed |
| TypeScript `tsc --noEmit --incremental false` | Passed |
| `git diff --check` and new contract/report link checks | Passed |

The final 117-test run includes all 65 ML-role cases and 52 existing main-barrier
cases. It follows the added missing-query normalization; the earlier 169-test
run is broader but overlaps those ML-role cases. Do not sum the test rows as
unique tests or call them a full API suite. Script subtests are reported
separately. Existing FastAPI `regex` and Alembic `path_separator` deprecation
warnings remain; no new warning suppression was introduced.

The first unconstrained-worker frontend run passed 1,350 tests but three
existing Discovery preview-layout cases hit the default 5-second test timeout.
A complete two-worker rerun passed all 1,353 tests without changing source,
assertions, timeout thresholds or the repository's test configuration. This is
consistent with local worker contention, not proof of a production UI defect
or a production performance measurement.

ML cases exercise native and HTTP grant/revoke/regrant, old-grant replay after
revocation, exact current grant IDs, account/session changes during body receipt,
cross-actor recovery refusal, closed malformed payloads, API-key rejection,
browser-session Origin rules, lost post-commit reply recovery, raw-route/training
denial, competing writers, resealed SQL forgeries, audit-retained account erasure
refusal and immutable update/delete/truncate protection. All accounts, labels
and membership decisions are synthetic in capability-owned temporary databases.

The first native iterations found a SQLAlchemy `quoted_name` canonical-key
mismatch and a test pointing to a nonexistent raw-claims URL; these were fixed
before passing the initial 48-case module. Later missing-query tests correctly
received private 400 responses but their initial exact-body assertion omitted
the existing global `error_code`/`request_id` fields. The assertion now checks
the complete actual error shape and no private input echo.

The first migration attempt correctly rejected the new harness's schema check
because an identity query had already started a transaction. No success receipt
was published. The harness now performs schema admission on a fresh connection,
then validates its owned database identity; an old schema must fail specifically
for the exact-revision reason. Source tests pin this ordering. No production
admission check, historical guard or data-retention assertion was weakened.

## Retained evidence

The fresh [0071 schema receipt](measurements/ML_Use_Role_Schema_2026-09-12-01.json)
is byte-identical to the runner's successful output. Full-file SHA-256:
`9c64a640ba67edee696ebe93baa723de3428a6cb769e49b5a33e6c726ec51e48`.
Its body hash is `8c58f793412f42d0bb1bac2756e53a91806f254bee883af78039cab26034c214`.
All 645 source pins and the closed receipt schema were independently verified
after publication. It records actual dirty-worktree bytes, not a new commit.

The established report-v1 table/outcome vocabulary is unchanged: there are no
invented ML-role counts in its JSON. The source-pinned executed harness checks
the exact three synthetic grant/revoke/regrant rows, old-request replay,
current-role read and nonempty rollback refusal before finishing. Earlier
Discovery v1/v2 and other nonempty guards run independently before these rows
exist. See the [measurement index](measurements/README.md) for runtime and scope.

The frontend's current capture is
`frontend/tests/fixtures/discovery-main-barrier-native.wire.json` with 258 actual
backend source pins and full-file SHA-256:
`bcdd029d75d726b8450e675b41abe608067b63ee948c595bf21d9ddec40d7fd2`.
Batch55 preserves these exact bytes as
`frontend/tests/fixtures/discovery-main-barrier-native.batch54.wire.json` and
recaptures the current compatibility fixture. The 258 pins here remain the
historical batch54 inventory, not the later intake/preflight implementation.
It comes from the final successful guarded native SQL-to-HTTP integration.
Only the outer archive is pretty-printed; every embedded raw response string
is equal to the original capture. No Python quantity is reserialized through
a JavaScript number to generate a replacement hash-bound payload.

The original batch52 capture remains
`frontend/tests/fixtures/discovery-main-barrier-native.batch52.wire.json` with
its original 255 historical pins and unchanged SHA-256
`1873c02e3d9305ec4c3d048706193447aa4c12b156afa7a003d83796c91f9f7a`.
The frontend test pins both archive hashes while requiring current source
equality only for the fresh capture. The original 0070 schema receipt also
remains unchanged and is explicitly historical.

## Reproduce locally

Use the owned runner, never an inherited database or Redis target:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite api -- -q \
  tests/test_ml_use_governance.py tests/test_discovery_main_barrier.py

api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite migrations

api/.venv/bin/python -m pytest scripts/tests -q
```

For a fresh retained migration receipt, pass `--report` with a new private file
path. Never overwrite or relabel an earlier receipt. Native local evidence is
not exact-revision Linux CI or production image parity.

Frontend checks run from `frontend/` with `pnpm exec vitest run --maxWorkers=2`,
`pnpm test:source` and `pnpm exec tsc --noEmit --incremental false`. This batch
changes frontend tests/evidence only; no new production bundle or live browser
QA is claimed for its API-only feature.

## Remaining work and delivery boundary

The next priority is exact dataset/task/input-scoped ML-use requests, current
recursive source-permission checks, independent rights/run decisions and
revocation/expiry at consumption. Existing metadata/RPS publication permissions
cannot be treated as training licenses. Then an actual reviewed ML08 pilot is
needed before an independently authorized real-data baseline execution.

This batch introduces no admin-page layout or model-training UI; all existing
website-owned UI remains English. It does not grant a real user any role, open
the feature flag, train real data, call an external provider, release source
content, run a paid calculation, migrate production or establish real human
scientific review. Commit/push/PR, remote issue mutation, Linux CI delivery and
deployment remain separate authorized steps. No such remote write was performed.
