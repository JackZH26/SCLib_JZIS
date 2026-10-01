# Materials recovery native protocol captures, 2026-10-02 R3

The recovery iteration adds fair inspection across linked papers, honest
per-paper coverage and a source-scoped classification candidate reader. After
all source owners froze their inputs, the unchanged seven native producers ran
once in the separate `codex/sclib-materials-recovery-20261002` worktree. They
generated new `materials20261002r3` archives. The previous
[R2 capture](SCLIB_NATIVE_CAPTURES_2026-10-02_R2.md) retains its original source
pins and bytes; the preceding upgrade worktree was not edited by this capture.

Run from the recovery repository root with its existing `api/.venv`:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py \
  --backend native --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite api -- \
  -q --tb=short --basetemp=/tmp/sclib-materials-recovery-captures-20261002-r3 \
  --junitxml=/tmp/sclib-materials-recovery-captures-20261002-r3.xml \
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
in **56.74 seconds**, followed by successful service cleanup.

Exact producer output bytes were copied into seven new archives, preserving the
original HTTP response strings, synthetic events and source pins. The
[R3 manifest](capture-manifest-materials-2026-10-02-r3.json) records each original
output path, producer, retained archive, SHA-256, byte count and pin count. The
six ML captures each bind **635 inputs**; discovery binds its narrower **313-input**
inventory. All **4,123 pin entries** matched both the capture-start snapshot and
the final frozen repository bytes. The distinct pinned inventory contains 635
Python/schema files under `api` and `scripts`.

The producers' pin lists do not include packaged resources. A separate pre/post
snapshot verified all **five resource files** without altering the producers or
adding synthetic pins to their output. The classification seed file SHA-256 was
`6ee4a68ba4ffc7cac838a7d23afbf4b0cb36696e7b07519a91bbfb03549fa898`.

All **289 historical native archives** retained their original byte counts and
SHA-256 values. The seven additions bring the inventory to **296 archives**.
Current frontend helpers, component imports and the rights visual fixture use
R3. Six new exact archive hash assertions were added while preserving all **115
previous complete archive assertions** and their occurrence counts. Across the
entire component directory, all **119 prior literal SHA-256 strings** were also
preserved. The resulting counts are 121 archive assertions and 125 component
hash strings. These are different inventories: the latter includes four hashes
used outside archive assertions. Historical capture documents and manifests
were not rewritten. The review-preflight archive remains retained evidence
without a direct frontend import.

The six focused frontend protocol suites passed all **384 tests** in **3.70
seconds**. Their current-source checks re-read each pinned file; their archive
checks retain every prior exact assertion. This capture verification is separate
from the complete release regression and CI gates.

An independent installed-wheel check used the same frozen source and resource
bytes. The wheel was **4,195,956 bytes**, with SHA-256
`925eef7449b90ab2acf1af23dcacdb4c4d5e190bcaa891b79d33d6886c54bf0d`.
All **361 packaged Python files** and **five resources** matched the repository
byte for byte. Execution outside the repository with `-S` and no editable
startup resolved the installed target and returned the actual offline MDR
inventories: Nb 19 rows and NbN 15 rows. The installed classification seed
contained three candidates and the general enrichment seed 41 candidates. The
classification seed's internal document digest was
`5652a30e82fb12e53403e69654239bef37230f3a728fe9133e386eb03a88f791`;
this differs from its complete file hash above. The private wheel proof receipt
SHA-256 was
`26ac053af97f206a205c244c0e99a51b348cef53d15f3a0ea04acc29bc13d1b8`.
This packaging proof is separate from the native protocol source pins.

The captures use synthetic accounts, evidence and review events, plus explicitly
declared compiler doubles. They prove the tested native SQL/HTTP and installed
worker behavior. They do not prove scientific validity, complete literature
coverage, source permission, candidate promotion or authorization to train a
model. No production data or credentials were used. Any post-commit secret-scan
finding requires inspection of its exact bytes and field; only independently
reviewed commit/path/rule/line fingerprints may be excluded. Existing exclusions
must not be broadened.
