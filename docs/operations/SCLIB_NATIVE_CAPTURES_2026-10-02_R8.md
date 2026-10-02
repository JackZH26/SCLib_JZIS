# Materials criterion handoff native captures, 2026-10-02 R8

The source correction preserves explicit onset and zero-resistance definitions
when pending recovery handoffs reach the existing typed mapper. It also makes
missing extraction/metadata wording accurate. The candidate extractor, all 39
numeric/literal seed candidates, two classification seed statements, their IDs,
and five packaged resources retain their preceding bytes and semantics.

The frozen `api/services/material_enrichment.py` SHA-256 is
`18bd8887eaebaf012aa80fb58f5cbac143573e41e1f3850b955d2b5321487162`.
The unchanged seven native producers generated fresh actual SQL/HTTP outputs
against guarded owned PostgreSQL and Redis services. Run from the repository:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py \
  --backend native --suite api \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server -- \
  -q --basetemp=/tmp/sclib-materials-recovery-captures-20261002-r8-final \
  --junitxml=/tmp/sclib-materials-recovery-captures-20261002-r8-final.xml \
  tests/test_discovery_main_barrier.py::test_barrier_edit_needs_new_preview_package_and_independent_review_then_source_hold \
  tests/test_ml_pilot_attestations.py::test_actual_three_account_preview_commit_and_exact_recovery \
  tests/test_ml_pilot_evidence.py::test_byte_replay_is_read_only_and_never_turns_missing_declarations_into_acceptance \
  tests/test_ml_pilot_participant_wire.py::test_participant_workbench_real_native_wire \
  tests/test_ml_pilot_review_admission.py::test_real_four_file_preflight_binds_each_account_without_any_database_write \
  tests/test_ml_use_rights_wire.py::test_independent_rights_workbench_native_wire \
  tests/test_ml_use_runs_wire.py::test_run_workbench_native_wire
```

Use a new directory for any repetition. The successful final invocation passed
**7 tests in 56.193 seconds**, with zero failures, errors and skips, followed by
owned-service cleanup. The first setup attempt passed a Redis directory rather
than its executable and stopped at initialization, before any capture. Its
separate failed log is retained; it is not a successful test receipt.

Seven original outputs were copied byte for byte to new
`materials20261002r8.wire.json` files. The [R8 manifest](capture-manifest-materials-2026-10-02-r8.json)
contains actual output paths, hashes, byte counts and producers. Its six ML
archives each pin 635 inputs and discovery pins 313. All **4,123 entries** match
the 635 distinct frozen current source bytes. The separate frozen-source
supplement was recorded during producer execution, not assigned a pre-capture
timestamp. Owners had already finished their source edits; its equality check
and the final current-byte check are independently recorded.

All **384 preceding wire files**, including **317 native archives**, remain
byte-identical to parent `9493644c6f94e8d40c1b883a2d9fcc125a156eac`.
Five packaged resources were checked separately because the native producers
do not pin them. A broader filename-based history inventory checked all **68
preceding documents** under `docs` whose names contain `capture` or
`secret_triage`; this inventory has a different scope from the older R7 count.
No preceding archive, assertion, document or receipt was resealed.

Six suites preserve all 139 preceding literal archive hashes with their
occurrence counts, and append six R8 hash assertions. Current helpers and
imports use genuine R8 outputs. This protocol evidence uses synthetic accounts
and declarations; it is not human scientific review or source permission.

Separate local validation passed **372 tests plus 7 subtests** for recovery and
references, **2,038 frontend tests in 64 files**, and **46 frontend source
checks**. The actual typed-mapper regressions verify two known definitions,
seven unknown definitions and pending authority. They do not insert claims or
complete sample/run/structure associations.

The prior PCRE2 deployment correction is retained. Final explicit-head secret
scanning, exact-head CI, final image scan, signed release, deployment and public
acceptance remain separate gates. No production write, canonical promotion,
scientific acceptance, ML admission or new scientific calculation occurred in
these captures.
