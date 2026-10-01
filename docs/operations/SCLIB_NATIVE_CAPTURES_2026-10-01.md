# Materials upgrade native protocol captures, 2026-10-01

The Materials upgrade changes backend files that are pinned by the existing ML
and discovery protocol fixtures. Current compatibility tests therefore use new
captures from the unchanged native capture producers. Historical archives and
their hash assertions remain intact; old source pins were not rewritten.

The final capture run used the worktree's isolated `api/.venv`, installed with
`uv sync --locked --extra dev` and checked with `uv lock --check`: Python
3.12.14, PyJWT 2.15.0, urllib3 2.8.0, Pydantic 2.13.4 and pydantic-core 2.46.4.
It did not change or use the primary checkout's environment. An earlier
exploratory run remains outside the repository and is not an archived fixture.

Run from the repository root:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py \
  --backend native --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite api -- \
  -q --tb=short --basetemp=/tmp/sclib-materials-native-20261001-locked \
  --junitxml=/tmp/sclib-materials-native-20261001-locked.xml \
  tests/test_discovery_main_barrier.py::test_barrier_edit_needs_new_preview_package_and_independent_review_then_source_hold \
  tests/test_ml_pilot_attestations.py::test_actual_three_account_preview_commit_and_exact_recovery \
  tests/test_ml_pilot_evidence.py::test_byte_replay_is_read_only_and_never_turns_missing_declarations_into_acceptance \
  tests/test_ml_pilot_participant_wire.py::test_participant_workbench_real_native_wire \
  tests/test_ml_pilot_review_admission.py::test_real_four_file_preflight_binds_each_account_without_any_database_write \
  tests/test_ml_use_rights_wire.py::test_independent_rights_workbench_native_wire \
  tests/test_ml_use_runs_wire.py::test_run_workbench_native_wire
```

Use a fresh, distinct output directory when repeating the command. The guarded
runner creates its own PostgreSQL/Redis services, verifies their identities and
removes them after the run. It accepts no production DSN.

All seven producer tests passed in 60.45 seconds. Their output bytes were copied
unchanged into `materials20261001` archives. The
[capture manifest](capture-manifest-materials-2026-10-01.json) records each exact
producer, original path, archive path, SHA-256, byte count and source pin count.
The six ML archives pin 626 inputs each; discovery pins its existing narrower
308-input inventory. All 4,064 pins were independently compared with current
files after capture. SHA-256 comparison also confirmed that all 268 previously
retained native archives remained byte-for-byte unchanged.

Frontend helpers and the rights visual fixture now import the new archives.
Protocol tests add their new archive hashes, retain every previous hash
assertion, and still compare every selected current source pin with its actual
file. The review-preflight archive remains retained audit evidence, as in earlier
batches.

The six focused frontend protocol suites passed all 384 tests in 3.64 seconds.
All 97 pre-existing archive hash assertion strings were compared with the prior
commit and retained verbatim. `git diff --check` passed. These focused results
are separate from the release pipeline's complete frontend regression run.

These captures contain synthetic accounts, evidence, review events and explicit
compiler doubles. They prove the tested native SQL/HTTP and installed-worker
behavior; they do not establish scientific approval, source permission or
authorization to execute training. No production data or credentials were used.
If secret scanning flags a synthetic request key after commit, inspect its exact
field and bytes and apply only reviewed commit/path/rule/line fingerprints;
existing exclusions must not be broadened.
