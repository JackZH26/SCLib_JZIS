# Materials enrichment native protocol captures, 2026-10-02

The final Materials enrichment readers and Materials Project, COD and NOMAD
reference services change backend inputs pinned by the existing ML and discovery
protocol fixtures. After every source owner explicitly froze those inputs, the
unchanged native producers generated a new `materials20261002` batch. Earlier
captures, their source pins and their archive hash assertions remain historical
evidence; none were rewritten or relabelled.

Run from the repository root with its isolated `api/.venv`:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py \
  --backend native --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite api -- \
  -q --tb=short --basetemp=/tmp/sclib-materials-native-20261002-locked \
  --junitxml=/tmp/sclib-materials-native-20261002-locked.xml \
  tests/test_discovery_main_barrier.py::test_barrier_edit_needs_new_preview_package_and_independent_review_then_source_hold \
  tests/test_ml_pilot_attestations.py::test_actual_three_account_preview_commit_and_exact_recovery \
  tests/test_ml_pilot_evidence.py::test_byte_replay_is_read_only_and_never_turns_missing_declarations_into_acceptance \
  tests/test_ml_pilot_participant_wire.py::test_participant_workbench_real_native_wire \
  tests/test_ml_pilot_review_admission.py::test_real_four_file_preflight_binds_each_account_without_any_database_write \
  tests/test_ml_use_rights_wire.py::test_independent_rights_workbench_native_wire \
  tests/test_ml_use_runs_wire.py::test_run_workbench_native_wire
```

Use a fresh output directory for each repetition. The guarded runner creates
private PostgreSQL and Redis services, verifies their identities, accepts no
production DSN, and removes only that invocation's services after completion.

All seven producer tests passed in **60.34 seconds**. Their exact output bytes
were copied into seven new archives without changing HTTP response strings,
synthetic events or source pins. The
[capture manifest](capture-manifest-materials-2026-10-02.json) records each
producer, original output path, retained archive, SHA-256, byte count and pin
count. Each of the six ML archives binds 630 inputs; discovery binds its narrower
310-input inventory. All **4,090 pins** were independently compared with current
files after capture. All **275 previous native archives** still have their
pre-capture SHA-256 values.

Current frontend helpers and the rights visual fixture import the new batch.
Six protocol suites add new exact archive hash assertions and retain all **107
pre-existing component hash assertion strings**, including assertions for the
previous `materials20261001` batch. The review-preflight archive is retained audit
evidence, as in earlier batches. The six focused frontend suites passed all
**384 tests** in **4.43 seconds**; global TypeScript checking and `git diff --check`
also passed. These focused checks are distinct from the complete release
regression run.

An independent installed-wheel check used the same frozen source inventory.
The wheel SHA-256 was
`f24f43e7af8d8478021a9629c0838ec67b13615dc73c4b89c85f7020d7dcdfd8`
and its size was 1,192,118 bytes. All 358 packaged Python files and the candidate
seed matched the current sources exactly. Execution outside the repository with
`-S` and no editable startup resolved services, models and routers from the
installed target. All 41 seed candidates had unique identities, valid source
digests and no private evidence. This verifies packaging and candidate integrity;
it does not promote candidates into canonical scientific properties.

The captures contain synthetic accounts, evidence, review events and explicit
compiler doubles. They establish the tested native SQL/HTTP and installed-worker
behavior, not scientific approval, source permission or authorization to train a
model. No production data or credentials were used. If secret scanning flags a
synthetic request key after commit, inspect the exact field and bytes and apply
only reviewed commit/path/rule/line fingerprints. Existing exclusions must not
be broadened.
