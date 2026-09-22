# EN01 / EN04 implementation and validation

Date: 2026-09-06 (Asia/Singapore). Issues: EN01 #42; EN04 #52.

## Outcome and boundaries

EN01's connection-before-import guard, one-run capability, owned-service runner,
least-privilege service setup and guarded API/migration entry points are
implemented. Native disposable integration passed. No existing database,
Redis instance, production service, cloud account, release deployment or real
research data was used. All temporary instances created by the completed
validation runs were removed.

EN04's pinned-tool/locked-CI-install and inventory/comparison tooling are
implemented. **Docker-mode integration and actual production-image/test
inventory comparison remain unexecuted locally**, because Docker and uv are
not installed on this host. No environment installer was run. This is not a
claim of full EN04 closure, and neither remote issue was closed.

Existing user changes were preserved. Production `main.py`, `config.py`,
`models/db.py`, Dockerfiles, deployment entry points and scientific schema
files were not edited by this work.

## Changed files

| File | Change |
|---|---|
| `api/tests/conftest.py` | Fail closed before application/client imports; no connection defaults; disable `.env` in test process; recheck capability on engine creation and cleanup; verify connected PostgreSQL/Redis identity before destructive operations |
| `scripts/test_safety.py` | Pure-standard-library preflight: private manifest, ownership/lifetime, exact URL capability, strict loopback/high-port/role grammar, live native process or local Docker container proof; connected-service marker checks |
| `scripts/run_disposable_tests.py` | Create only new temporary services, least-privilege PG role and Redis ACL user, minimal test environment, native/Docker modes, exact owned-resource cleanup; no attach/reuse/input-DSN mode |
| `scripts/run_test_migrations.py` | Same preflight before importing Alembic/database clients; empty-database upgrade to current head and auth schema verification |
| `api/tests/test_disposable_environment.py` | Real PG privilege and Redis ACL/single-database/cleanup acceptance tests |
| `scripts/tests/test_test_safety.py` | No-network preflight and import-order tests, including URL/exception redaction |
| `.github/workflows/test.yml` | API/migration jobs use owned disposable runner; all three Python jobs pin uv 0.11.16 and consume their own lock with the dev extra; runtime inventory artifacts; original six jobs/frontend lock behavior preserved |
| `scripts/runtime_inventory.py` | Credential-free interpreter/package/lock capture and actual-runtime-versus-test comparison |
| `scripts/tests/test_runtime_inventory.py` | Comparison failures, explicit dev-only exceptions and CI contract checks |
| `docs/TESTING_SAFELY.md` | Supported entry points, threat model, native fallback, cleanup rules, CI and remaining image-parity gate |

The runner's operational files contain generated disposable credentials and
are owner-only under a new temporary directory. They are not repository
artifacts, are never printed, and are removed with the disposable run. Error
messages suppress chained parser exceptions that might otherwise reflect a URL.

## Validation performed

Local runtime: Python **3.12.14**, PostgreSQL **16.13 (Homebrew)**, Redis
**8.6.1**. CI is still configured for Python **3.11**, PostgreSQL **16** and
Redis **7**. The difference is explicit, not evidence of version parity.

| Check | Result |
|---|---|
| New preflight tests, sockets forbidden and client imports instrumented | **15 passed** |
| New runtime-inventory/CI-contract tests | **5 passed** |
| Existing scripts tests plus the then-current new tests | **60 passed**; subsequently added one additional passing exception-redaction guard test |
| Newly created native sandbox, targeted service isolation integration | **2 passed**, 1 existing FastAPI deprecation warning |
| Separate newly created native sandbox, empty database to Alembic head | **Passed through `0046_result_origin`**, marker/least-privilege/current head/auth schema verified |
| Newly created native sandbox, full API suite during parallel SC05 work | **222 passed, 5 failed**, 1 existing FastAPI deprecation warning; failures listed below and handed to the main agent |
| Direct unwrapped pytest collection with synthetic invalid URLs and no capability | Refused before client/application imports; no URL/password in output |
| Ruff on all owned Python files | Passed |
| Workflow YAML parsing | Passed; six original jobs preserved |
| Tracked-file whitespace diff check | Passed |

The five full-API failures concern the concurrent result-origin/Timeline
contract update, not connection safety. This work did not change their fixtures:

1. `tests/test_health.py::test_data_health_reports_metadata_without_age_thresholds`
   — old projection schema fixture yields `not_ready`.
2. `tests/test_timeline_http_cache.py::test_timeline_pagination_is_stable_after_optional_sampling`
   — expected `timeline-v1-*`, current `timeline-v2-origin-*`.
3. `tests/test_timeline_projection.py::test_classifier_preserves_audited_experimental_precedence`
   — old paper-genre/pressure inference expectation.
4. `tests/test_timeline_projection.py::test_extraction_is_stable_deduplicated_and_uses_paper_year_fallback`
   — old paper-wide theoretical inference expectation.
5. `tests/test_timeline_projection.py::test_projection_read_uses_flat_rows_without_material_records`
   — old 8-field fake row against a 12-field projection query.

The main agent is responsible for the SC05 fixture/contract reconciliation and
the final integrated rerun. The preceding full-suite result is retained as a
dated observation, not relabeled as an all-green run.

## Exact safe reproduction commands

Run from `/Users/jackzhou/Documents/SCLib_JZIS` using the existing environment:

```bash
api/.venv/bin/python -m unittest discover -s scripts/tests -p test_test_safety.py -v
api/.venv/bin/python -m unittest discover -s scripts/tests -p test_runtime_inventory.py -v

api/.venv/bin/python scripts/run_disposable_tests.py \
  --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server \
  --suite api -- -q tests/test_disposable_environment.py

api/.venv/bin/python scripts/run_disposable_tests.py \
  --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server \
  --suite migrations

api/.venv/bin/python scripts/run_disposable_tests.py \
  --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server \
  --suite api -- -q
```

Do not prepend a production/development DSN, copy a previous capability,
start an existing Homebrew service, or invoke destructive fixtures directly.
The runner ignores inherited connection settings and creates its own endpoints.

## Remaining gates and limitations

1. Execute the actual Docker-mode API/migration jobs in CI. Local mock tests
   verify container identity rules, but are not a Docker integration result.
2. Run a real locked `uv==0.11.16` installation in CI; the local existing Python
   environment was not reinstalled or claimed to match the Linux lock graph.
3. Capture inventories from actual immutable release images and compare them
   with CI test inventories using `runtime_inventory.py`. The matching lock
   digest alone does not prove platform-dependent package parity.
4. Complete the main agent's five Timeline fixture updates, then run the full
   integrated API suite again through the same guarded runner.
5. The guard protects accidental misconfiguration, not hostile code executed
   by an owner who can edit tests or a compromised Docker daemon. Provider calls
   remain the responsibility of test mocks; this is not an OS network sandbox.
6. If a runner is force-killed, inspect the exact orphan process/container
   identity and private path before cleanup. Never use broad prune/name-glob
   cleanup commands or reuse the abandoned capability.

No commit, push, deployment, remote-issue closure or production migration was
performed in this work package.
