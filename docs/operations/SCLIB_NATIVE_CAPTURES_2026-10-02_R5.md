# Materials recovery native protocol captures, 2026-10-02 R5

This capture follows the source-condition corrections in the recovery worktree.
The classification reader recognizes TeX spacing between values and units,
preserves Unicode minus signs, and assesses the original condition token before
formula normalization. After all backend and resource owners froze their inputs,
the unchanged seven native producers ran once with the final R5 sources. The
previous [R3 capture](SCLIB_NATIVE_CAPTURES_2026-10-02_R3.md) retains its original
source pins and bytes. A completed R4 run remains private debugging evidence:
its source freeze was withdrawn after a condition-parser defect was identified,
and no R4 archive, manifest or import was published. The preceding upgrade
worktree was not edited by this capture.

Run from the recovery repository root with its existing `api/.venv`:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py \
  --backend native --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite api -- \
  -q --tb=short --basetemp=/tmp/sclib-materials-recovery-captures-20261002-r5 \
  --junitxml=/tmp/sclib-materials-recovery-captures-20261002-r5.xml \
  tests/test_discovery_main_barrier.py::test_barrier_edit_needs_new_preview_package_and_independent_review_then_source_hold \
  tests/test_ml_pilot_attestations.py::test_actual_three_account_preview_commit_and_exact_recovery \
  tests/test_ml_pilot_evidence.py::test_byte_replay_is_read_only_and_never_turns_missing_declarations_into_acceptance \
  tests/test_ml_pilot_participant_wire.py::test_participant_workbench_real_native_wire \
  tests/test_ml_pilot_review_admission.py::test_real_four_file_preflight_binds_each_account_without_any_database_write \
  tests/test_ml_use_rights_wire.py::test_independent_rights_workbench_native_wire \
  tests/test_ml_use_runs_wire.py::test_run_workbench_native_wire
```

Every repetition requires a fresh output directory. The guarded runner creates
private PostgreSQL and Redis services, verifies ownership, accepts no production
DSN and removes only that invocation's services. All seven producer tests passed
in **57.04 seconds**, followed by successful service cleanup.

Exact producer output bytes were copied into seven new `materials20261002r5`
archives, preserving the original HTTP response strings, synthetic events and
source pins. The [R5 manifest](capture-manifest-materials-2026-10-02-r5.json)
records each original output path, producer, retained archive, SHA-256, byte count
and pin count. The six ML captures each bind **635 inputs**; discovery binds its
narrower **313-input** inventory. All **4,123 pin entries** matched both the
capture-start snapshot and the final frozen repository bytes. The distinct
pinned inventory contains 635 Python/schema files under `api` and `scripts`.

The producers' pin lists do not include packaged resources. A separate pre/post
snapshot verified all **five resource files** without altering the producers or
adding synthetic pins to their output. The classification seed file SHA-256 was
`d7bf29439311fb7c210fa34f339c47a4e3720775c735e7cfd6218648bcdb5b34`.
It contains two pending primary-source candidates. A separate same-source
rebuild of the historical 321-source inventory retained 65 numeric candidates,
zero classification candidates and 122 review findings; the numeric candidate
array SHA-256 remained
`5dcf69800e72c71aa3f7a96b258c08b685f3e8e14e807e63d805f4826c3ded78`.
That rebuild did not change the database or establish scientific acceptance.
It is source-extraction evidence, separate from the protocol captures.

All **296 historical native archives** retained their original byte counts and
SHA-256 values. The seven additions bring the inventory to **303 archives**.
Current frontend helpers, component imports and the rights visual fixture use
R5. Six new exact archive hash assertions were added while preserving all **121
previous complete archive assertions** and their occurrence counts. Across the
entire component directory, all **125 prior literal SHA-256 strings** were also
preserved. The resulting counts are 127 archive assertions and 131 component
hash strings. These are different inventories: the latter includes four hashes
used outside archive assertions. All 14 historical capture, manifest and
materials secret-triage documents in the pre-capture snapshot retained their
bytes. The review-preflight archive remains retained evidence without a direct
frontend import.

The six focused frontend protocol suites passed all **384 tests** in **3.17
seconds**. Their current-source checks re-read each pinned file; their archive
checks retain every prior exact assertion. This capture verification is separate
from the complete release regression and CI gates. Results at a preceding
commit do not verify the current condition-parser corrections.

An independent installed-wheel check used the same frozen source and resource
bytes. The wheel was **4,195,759 bytes**, with SHA-256
`472a4f5b0574bed3b994a4d34dc035d7357ad7da83b6c222310d52f58f26b83f`.
All **361 packaged Python files** and **five resources** matched the repository
byte for byte. Execution outside the repository with `-S` and no editable
startup resolved the installed target and returned the actual offline MDR
inventories: Nb 19 rows and NbN 15 rows. The installed classification seed
contained two candidates and the general enrichment seed 41 candidates. The
classification seed's internal document digest was
`6aa56ccc9b4f1cfbf110dfa692cb4f6474539a674399414040346943db671787`;
this differs from its complete file hash above. The private R5 wheel proof
receipt SHA-256 was
`3946e8de909617ac2e21eba8b274873eb870305f2a99f5858c5ef767170e5751`.
This packaging proof is separate from the native protocol source pins.

The captures use synthetic accounts, evidence and review events, plus explicitly
declared compiler doubles. They prove the tested native SQL/HTTP and installed
worker behavior. They do not prove scientific validity, complete literature
coverage, source permission, candidate promotion or authorization to train a
model. No production data or credentials were used. Any post-commit secret-scan
finding requires inspection of its exact bytes and field; only independently
reviewed commit/path/rule/line fingerprints may be excluded. Existing exclusions
must not be broadened.
