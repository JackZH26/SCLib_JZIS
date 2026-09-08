# EN02 / EN04 engineering acceptance audit — 2026-09-08

## Decision

Neither issue should be closed from this audit alone. Their remaining work is
different:

- **EN02 / #58:** the principal software controls and the required *isolated*
  upgrade/read-model rollback are implemented and have native disposable
  evidence. The smallest remaining local deliverable is a retained, versioned
  rehearsal/cutover report containing the actual counts, exclusions and rollback
  identities—not another migration framework. Implementation publication and
  dependency acceptance remain outstanding. Production rollout remains a
  separate authorized operation, not a scientific-review prerequisite for this
  engineering issue.
- **EN04 / #52:** locked CI and candidate-image inventory comparison are
  implemented, but exact-revision Linux/image execution evidence is absent.
  There is also a concrete delivery-chain gap: the release workflow independently
  rebuilds and pushes an image after candidate-image verification, without
  comparing the final published digest's package inventory or promoting the
  already verified image. This needs a small release-workflow integration, not
  merely an issue status update.

No product files, dependencies, database, production system, Docker daemon,
GitHub issue, branch or release were changed by this audit. Only this report was
created. Human scientific review, source redistribution approval and permission
to run paid computation are not acceptance conditions for these engineering
controls.

## Scope and exact revision

The live issue bodies were read on 2026-09-08:

- [#58 — EN02 schema lifecycle](https://github.com/JackZH26/SCLib_JZIS/issues/58)
- [#52 — EN04 locked runtime](https://github.com/JackZH26/SCLib_JZIS/issues/52)
- Both depend on [#42 — EN01 disposable test safety](https://github.com/JackZH26/SCLib_JZIS/issues/42), which was still open.

Audited checkout: `codex/sclib-research-v2`, local HEAD
`73afd054adb272130fe9bb96c5bc4c2653a14c22`, plus the frozen, uncommitted batch-32
changes. The tested Alembic head is `0066_result_impact_indexes`; it is **not**
contained in the HEAD commit above. In particular, the completed migration
rehearsal used the worktree bytes identified below.

Read-only GitHub checks for that exact HEAD returned:

| Check | Result |
| --- | --- |
| Commit lookup | HTTP 422, no commit found for that SHA |
| Remote `codex/sclib-research-v2` branch | HTTP 404 |
| PRs with that head branch, all states | Empty list |
| Workflow runs for that SHA | Empty list |

These observations establish an unpublished-delivery gap; they are not claims
about the success or failure of older main-branch builds. There is no verified
implementation PR or remote commit link to put into a closure comment yet.

## EN02: criterion-by-criterion mapping

| Original acceptance criterion | Current implementation and evidence | Assessment |
| --- | --- | --- |
| API restart/scale cannot run schema-changing DDL | [entrypoint.sh](../../../api/entrypoint.sh), line 8, calls only `schema_lifecycle check`. [main.py](../../../api/main.py), lines 303–304, also gates direct application startup before background tasks. [schema_lifecycle.py](../../../api/services/schema_lifecycle.py), lines 77–110, uses a fresh read-only transaction, bounded statement/application timeout and exact-head comparison; it neither stamps nor upgrades. Native tests: [test_schema_lifecycle.py](../../../api/tests/test_schema_lifecycle.py), lines 41, 69 and 115. Executable shell test: [script test](../../../scripts/tests/test_schema_lifecycle.py), line 14. | Implemented; native and shell regression paths exist. This describes the supplied application startup, not a privileged operator's arbitrary SQL. |
| Concurrent migrations permit at most one upgrader, with explicit wait/failure | [schema_lifecycle.py](../../../api/services/schema_lifecycle.py), lines 60–74, takes a nonblocking session advisory lock. [alembic/env.py](../../../api/alembic/env.py), lines 57–71, applies it to every current online Alembic invocation. Session scope survives the older migration's autocommit block; `NullPool` closes the physical owner. Native test at line 82 exercises a second connection, a real `command.upgrade` contender and blocked API admission; line 99 covers release after failure. | Implemented and testable against actual PostgreSQL. Cooperative locking does not constrain arbitrary privileged SQL, obsolete external migration runners or an independently applied offline SQL script. |
| Failed/incompatible migration blocks new API traffic | Exact-head admission rejects missing, multiple, old and unknown heads; no permissive version range. [deploy.yml](../../../.github/workflows/deploy.yml), lines 168–204, checks the dedicated credential, retains backup and signature verification, runs migration, then runtime-credential admission, before API replacement. Script tests at lines 37 and 64 assert ordering. | Implemented. A failure may leave earlier autocommitted DDL; the contract blocks cutover, not a claim of whole-chain transactional undo. Existing running instances are not retroactively paused by the startup check. |
| Isolated old-schema upgrade and read-model rollback preserve records/releases | [run_test_migrations.py](../../../scripts/run_test_migrations.py), lines 1550–1650, starts from an empty, owned database, upgrades to real `0050_timeline_identity`, seeds legacy rows, upgrades to head and checks raw-record preservation. Subsequent independent guards retain frozen/released histories. Lines 955–1027 exercise actual retained vectors/text, staging, complete declared-member validation, activation, a second generation and CAS rollback to the first after mutable chunk replacement. Latest native rehearsal through 0066 passed. | Satisfied as an **isolated synthetic engineering rehearsal**. It is not a production migration, corpus-scale benchmark or authenticated scientific data release. The issue itself does not require a production rewrite. |
| Immutability check **or** documented versioned replacement mechanism | [SCHEMA_ROLLOUT.md](../../SCHEMA_ROLLOUT.md), lines 141–158, explicitly preserves released migration/schema semantics and requires additive versions or a separately reviewed replacement. Independent populated-history downgrade guards remain in the rehearsal. New 0066 adds indexes only and tests both empty and populated roundtrips without altering old migration files. | Documented-replacement branch of the criterion is implemented. Do not claim an automated digest audit of every historical schema dependency exists. |
| Cutover report contains counts, reason-coded exclusions, versions and rollback instructions | [SCHEMA_ROLLOUT.md](../../SCHEMA_ROLLOUT.md), lines 160–178, specifies the report. Shadow-import parity/receipt code and generation activation history provide useful underlying data. The current migration runner makes assertions and prints a success summary; it does not emit a consolidated, retained cutover report. No such completed report was located in the reviewed rollout/review/measurement documents. | **Remaining local deliverable.** A template or an aggregate pass count is not the actual report required by this checkbox. |

### Job/role and rollout boundary

[docker-compose.yml](../../../docker-compose.yml), lines 71–85, defines a
one-shot tools-profile migration job without the API env file, cloud credentials
or published ports. [docker-compose.prod.yml](../../../docker-compose.prod.yml),
lines 35–43, uses the same signed API image and a separate read-only mounted
migration credential, explicitly clearing the runtime URL fallback. Secret-file
failure and separation have focused tests. The code does not provision a
production PostgreSQL role or remove existing runtime-role DDL privileges as a
side effect.

Before any real deployment, an authorized operator still needs to provision and
inspect actual role privileges, check backups/restore capability, validate the
specific image and compatible readers, measure migration locks/disk/latency and
approve the real target's cutover/rollback procedure. Those are deployment
gates, not evidence that another unused schema abstraction is needed.

The opening/closing wording in `SCHEMA_ROLLOUT.md` requires a real staging
rehearsal before EN02 closure. That is stricter than #58's *isolated* rehearsal
criterion. Keep the stronger requirement for production readiness, or resolve
that documented policy explicitly during review; do not silently turn a local
software issue into an obligation to deploy production. A clearly labelled
disposable rehearsal report can satisfy the issue's engineering report
requirement without purporting to approve a real data cutover.

### Smallest next EN02 deliverable

Extend the existing guarded rehearsal's reporting, then archive one actual run:

1. Record source/target schema and source-code/input hashes; identify the owned
   disposable environment without secrets or reusable credentials.
2. Record actual per-scope input/output and retained-history counts. Account for
   every excluded fixture with an explicit reason; use an explicit zero only
   where no fixture was excluded. Do not convert untested corpus coverage into
   a zero-exclusion claim.
3. Retain the before/after generation and activation-event identities, validation
   receipts, unchanged original/released-row checks, and the verified rollback
   result. The normal rollback changes a compatible reader selection, not a
   destructive schema downgrade.
4. Label the report synthetic/isolated and not production approval. Link the
   implementation PR, the exact resulting commit and the reviewed EN01 evidence.

No new material review, DFT calculation or source-license adjudication is needed
to complete this engineering slice.

## EN04: criterion-by-criterion mapping

| Original acceptance criterion | Current implementation and evidence | Assessment |
| --- | --- | --- |
| Inconsistent pyproject/lock fails rather than resolving silently | [test.yml](../../../.github/workflows/test.yml), lines 27–29, 68–70 and 108–110: uv `0.11.16`, `uv sync --locked --extra dev --python 3.11`. API and ingestion Dockerfiles also use `--locked`; uv's build image is digest-pinned. [test_runtime_inventory.py](../../../scripts/tests/test_runtime_inventory.py), line 87, guards all three jobs against returning to unlocked installation. | Implemented. No new install or actual lock-resolver run was performed in this audit. |
| Test/image runtime versions match, excluding documented dev-only packages | All three jobs collect actual installed distributions and invoke [run_runtime_parity.py](../../../scripts/run_runtime_parity.py), lines 98–138. It builds the checked-out Dockerfile, verifies immutable candidate image ID/provenance, executes only the inventory collector in an isolated container, and compares [runtime_inventory.py](../../../scripts/runtime_inventory.py) v2 inventories. | **Not yet demonstrated on exact-revision Linux images.** Mocked orchestration is not image parity. The final release-image rebuild binding gap below also remains. |
| API/migration/ingestion consume the relevant locks | API and migration use `api/uv.lock`; ingestion uses `ingestion/uv.lock`. API/migration run the guarded disposable test runner; ingestion runs unit tests in its locked venv. [test.yml](../../../.github/workflows/test.yml), lines 29–45, 70–82 and 110–118. | Implemented; current-revision remote executions are absent. Unrelated operational-config test tooling is not the shipped API/ingestion dependency graph. |
| Lock changes invalidate caches and appear in provenance | Both Dockerfiles copy `pyproject.toml` and `uv.lock` before dependency installation. CI always performs locked synchronization rather than restoring a supposedly valid test-result cache. Inventories include actual lock, project, collector and source-revision identities; parity additionally records Dockerfile hash and image ID. Dirty/untracked build inputs and mismatched inventory identities fail before build. | Implemented for CI/candidate images. Final published-image provenance must additionally be joined to that comparison; a shared commit alone is not the same image. |
| Frontend frozen lock preserved | [test.yml](../../../.github/workflows/test.yml), lines 136–145, retains pinned pnpm, `pnpm-lock.yaml` cache identity and `pnpm install --frozen-lockfile`; E2E retains the same policy. | Implemented. This audit did not reinstall or change frontend dependencies. |

### Concrete final-image binding gap

`run_runtime_parity.py` records the immutable ID of a locally built candidate.
However, [release-images.yml](../../../.github/workflows/release-images.yml),
lines 109–120, independently builds and immediately pushes a new image after
the matching Test/Security workflows succeed. It does not download/consume the
candidate image or compare the published digest's runtime inventory. SBOM,
signing and revision provenance are valuable separate controls; none performs
this package-version equality check. A mutable Python base tag and a later build
also mean equality cannot be inferred solely from using the same source and lock.
No observed package divergence or vulnerability is asserted.

Smallest safe completion options:

- Prefer building a release candidate once, verifying its exact runtime package
  inventory against the matching API/migration or ingestion test inventories,
  then publishing/promoting those same verified bytes and retaining the digest
  relationship; or
- Add a final-image inventory comparison for the exact release digest, consuming
  the matched Test run's authenticated workflow artifacts, and make successful
  comparison a prerequisite for signing/deployment eligibility. A failed image
  must not become deployable merely because push already happened.

Test the missing handoff explicitly: same revision and lock but different final
package inventory must fail; wrong Test run/project/digest must fail; the exact
matching image must pass. Include API **and migration** test inventories for the
API image, and the ingestion inventory for its image. Do not widen this into
unrequested OS-library, wheel-ABI, vulnerability or scientific-model parity.

### Actual local installed-runtime inspection

Read-only calls to the existing `runtime_inventory.capture` on both native venvs
failed closed with `installed package is not represented by the captured lock`.
Independent `importlib.metadata`/lock inspection found:

| Environment | Actual platform / package count | Installed entries not represented by that lock |
| --- | --- | --- |
| API native venv | CPython 3.12.14, Darwin arm64; 83 distributions | pip 25.0.1; uv 0.11.16; Pygments 2.21.0; Ruff 0.16.3 |
| Ingestion native venv | CPython 3.12.14, Darwin arm64; 59 distributions | pip 25.0.1; Pygments 2.21.0; Ruff 0.16.3 |

Both locks contain Pygments 2.20.0 and Ruff 0.15.21, and neither includes the
listed pip/uv build tools. These differences are developer/build tools, not an
observed production runtime defect. They do not negate native database behavior
tests. They do mean those environments cannot be advertised as successful v2
locked-inventory captures, much less Linux Python-3.11 image parity. No tool was
upgraded, removed or installed to make the audit pass.

The existing comparator checks Python **minor** version and implementation,
platform/architecture, exact runtime package versions and bounded dev-only
exceptions. It records the patch version but does not require patch equality.
Its claims must stay at that scope. The existing
[EN04 follow-up](EN04_Runtime_Parity_Followup.md) and the
[live partial-progress comment](https://github.com/JackZH26/SCLib_JZIS/issues/52#issuecomment-5553128366)
already distinguish native tests from Linux/image evidence. The current audit
confirms that distinction rather than relabelling the old evidence.

## Execution evidence available for this audit

| Evidence | Actual result and limitation |
| --- | --- |
| Batch-32 native migration rehearsal | Passed, exit 0; temporary services and database cleaned up. Real 0050-to-0066 upgrade, retained original rows, every independent older history guard, actual service operations, generation CAS rollback, and empty/populated index-only 0066 roundtrips. Not Docker, staging or production. |
| Batch-32 focused API tests | 62 passed in 12.01 s across `test_scientific_result_impact.py`, `test_scientific_result_impact_indexes.py`, `test_source_impact_indexes.py`, `test_research_shadow_schema.py`; one existing FastAPI `regex` deprecation warning. Actual owned native PostgreSQL; cleanup complete. These are not the schema-admission test count. |
| Batch-32 script lifecycle regressions | 21 passed in 1.27 s. Source/order/executable shell checks, not an additional database rehearsal. |
| Current full offline scripts run | Parent task reported 778 passed in the native environment. This includes mocked/source runtime-parity coverage, not actual Linux/image execution. |
| Full batch-32 API run | Still running when this audit was finalized; it began before the final dossier fan-out fix. Parent separately reported 122 focused API tests passed after that fix. No pending full-suite result is counted as passed or described as a full post-fix run here. |
| Installed native runtime captures | Both refused, as detailed above. No Linux/image comparison was executed. |
| Exact-current-SHA GitHub CI / implementation PR | Not found by the read-only checks above. |

The completed migration command was:

```sh
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server --suite migrations
```

The smallest focused rerun set after a relevant change is the guarded API
`tests/test_schema_lifecycle.py`, plus the offline scripts
`test_schema_lifecycle.py`, `test_runtime_inventory.py` and
`test_runtime_parity.py`. The latter uses mocked Docker orchestration and must
not be presented as real image execution. The migration rehearsal need not be
repeated for this documentation-only audit. Review the current full-API result
separately when it completes.

## Captured byte identities

These SHA-256 values identify inspected worktree inputs, not remote publication:

| Path | SHA-256 |
| --- | --- |
| `api/uv.lock` | `da2e2690d821659f006cf0138ca1e299a6f7ce5efed4322dc2f9ba82d1654b56` |
| `api/pyproject.toml` | `83010d8205b72bb873cfd6ade36bc0b6f431a2a3c4ed7276a82febf72fec9ad4` |
| `ingestion/uv.lock` | `90e26484c0c6c4bf3314a021ee72e5fe27e0daad1353769f7fde52f86e92dee3` |
| `ingestion/pyproject.toml` | `f8df667bc4f39bc15f373b163252b8ee0c6e7b9d6c661f9b4fa2f670589c81f8` |
| `scripts/runtime_inventory.py` | `38b72e5c35b1c9db5ce24d8111c7b316c292366e3d3e563f29231a53ceff79ce` |
| `scripts/run_runtime_parity.py` | `b59a6749dd2a75fcb0ea412d478e298f14bc47cee9cc90a489ecdc9de48314b6` |
| `scripts/run_test_migrations.py` | `0588dabfdf2bcd8d9687356c9bcabae14dc4d09141571d173b8c9559d4ae2d21` |
| `api/alembic/versions/0066_result_impact_indexes.py` | `3651a76ceb6c3a497c37aa14d66ed5b219690698824475594ef799d43d029950` |
| `api/models/scientific_result_impact_indexes_v1.py` | `47287e12446be27be976d660a9ee52d1c5b3f4e71acda5baabedc5af804c96ae` |

## Closure versus deployment

Publish the implementation and exact-revision regression artifacts only through
an explicitly authorized repository-delivery step; do not invent a PR link.
Review the already implemented EN01 dependency using its own safety acceptance
evidence, not its open/closed label alone. Then close only criteria actually
satisfied, recording the remaining deployment checklist separately.

This report authorizes no production credential provisioning, database upgrade,
backfill, image push, release promotion, data distribution or scientific claim.
Conversely, none of those unrelated scientific/data approvals is required to
write a truthful isolated engineering rehearsal report or to implement and test
the missing final-image package-inventory gate.
