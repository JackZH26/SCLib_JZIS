# Materials enrichment native protocol captures, 2026-10-02 R2

The NOMAD exchange-correlation metadata, versioned NIMS MDR SuperCon reference
reader and correction of legacy NIMS export attribution change inputs pinned by
the existing ML and discovery protocols. After the scientific, API/UI and export
owners explicitly froze their sources, the unchanged native producers generated
one new `materials20261002r2` batch. The previous
[2026-10-02 capture](SCLIB_NATIVE_CAPTURES_2026-10-02.md) remains historical
evidence with its original source pins and archive bytes.

Run from the repository root with its isolated `api/.venv`:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py \
  --backend native --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite api -- \
  -q --tb=short --basetemp=/tmp/sclib-materials-native-20261002r2-locked \
  --junitxml=/tmp/sclib-materials-native-20261002r2-locked.xml \
  tests/test_discovery_main_barrier.py::test_barrier_edit_needs_new_preview_package_and_independent_review_then_source_hold \
  tests/test_ml_pilot_attestations.py::test_actual_three_account_preview_commit_and_exact_recovery \
  tests/test_ml_pilot_evidence.py::test_byte_replay_is_read_only_and_never_turns_missing_declarations_into_acceptance \
  tests/test_ml_pilot_participant_wire.py::test_participant_workbench_real_native_wire \
  tests/test_ml_pilot_review_admission.py::test_real_four_file_preflight_binds_each_account_without_any_database_write \
  tests/test_ml_use_rights_wire.py::test_independent_rights_workbench_native_wire \
  tests/test_ml_use_runs_wire.py::test_run_workbench_native_wire
```

Use a fresh output directory for any subsequent repetition. The guarded runner
creates private PostgreSQL and Redis services, verifies their identities, accepts
no production DSN and removes only that invocation's services after completion.

All seven producer tests passed in **56.29 seconds**. Their exact output bytes
were copied into seven new archives, preserving original HTTP response strings,
synthetic events and producer source pins. The
[R2 capture manifest](capture-manifest-materials-2026-10-02-r2.json) records each
producer, original output path, retained archive, SHA-256, byte count and pin
count. Each of the six ML archives binds **633 inputs**; discovery binds its
narrower **311-input** inventory. All **4,109 pins** were independently compared
with current files after capture.

All **282 previous native archives** retain their pre-capture SHA-256 values.
The seven additions bring the archive inventory to 289. Current frontend
helpers and the rights visual fixture import R2. Six protocol suites add six
new exact archive hash assertions and preserve all **113 pre-existing component
hash assertion strings**, including the previous `materials20261002` batch.
The review-preflight archive remains retained audit evidence without a direct
frontend import. The six focused frontend suites passed all **384 tests** in
**3.54 seconds**. These checks are distinct from the complete release regression
and CI runs.

An independent installed-wheel check used the same frozen Python sources and
packaged resources. The wheel SHA-256 was
`a610db34254678720ea72ef976c14c620dcb2863932ad736e1e60703beefbcbd`
and its size was **4,177,318 bytes**. All **359 packaged Python files**, the
candidate seed, MDR compressed resource, manifest and attribution file matched
the repository bytes exactly. Execution outside the repository with `-S` and no
editable startup resolved imports from the installed target and returned the
actual offline Nb 19-row and NbN 15-row reference inventories. All 41 seed
candidate identities and source digests remained valid. The private proof
receipt SHA-256 was
`16a39ee96309e5bbd146a63fa8b188911bd99e7acf0497ec86750a6a0506c4a7`.

The packaged MDR resource was also independently reproduced from the exact
official oxide/metallic table. All **33,458** complete original row hashes,
physical line ranges, including seven multiline rows, and all **66** projected
cells per row matched that source. The deterministic compressed resource
SHA-256 was
`d1fce28506d68732744858570f6e4ee2a8dfef94630c8b3b48d703b95443707c`
with 2,973,460 compressed bytes and 16,152,747 decompressed bytes. Its version is
240322, DOI 10.48505/nims.4487, under the release's CC BY 4.0 terms. No private
catalogue records or paper chunks were packaged. Original units and method
descriptions remain source metadata; missing units, undocumented codes and
sample/phase associations remain unresolved. This release attribution does not
establish the dataset, version or license of legacy NIMS-labelled records.

The native captures contain synthetic accounts, evidence, review events and
explicit compiler doubles. They establish the tested native SQL/HTTP and
installed-worker behavior. They do not establish scientific approval, source
permission or authorization to train a model. No production data or credentials
were used. If secret scanning flags a synthetic request key after commit,
inspect the exact field and bytes and apply only reviewed commit/path/rule/line
fingerprints. Existing exclusions must not be broadened.
