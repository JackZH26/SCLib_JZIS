# Materials recovery native protocol captures, 2026-10-02 R6

This capture follows the numeric sample-form correction and bounded source-read
recovery in the recovery worktree. The numeric literal extractor is now
`materials-literal-extractor/1.0.1`: a bulk superconducting response does not
establish a bulk sample form. The fair source window, sparse source-paper
recovery, and both pending seed merge paths were final before the explicit
source/resource freeze. Classification extraction remains at `1.0.1` with its
unchanged two-candidate seed. These seven protocol captures pin those final
backend inputs; separate material endpoint and source-extraction tests assess
the field recovery behavior.

The unchanged seven native producers ran once in a fresh R6 output directory.
The preceding [R5 capture](SCLIB_NATIVE_CAPTURES_2026-10-02_R5.md), R3 and other
historical captures retain their original bytes, pins, complete archive hash
assertions, and manifest/triage history. No old response was relabelled or
re-sealed. The preceding upgrade worktree was not edited.

Run from the recovery repository root with its existing `api/.venv`:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py \
  --backend native --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite api -- \
  -q --tb=short --basetemp=/tmp/sclib-materials-recovery-captures-20261002-r6 \
  --junitxml=/tmp/sclib-materials-recovery-captures-20261002-r6.xml \
  tests/test_discovery_main_barrier.py::test_barrier_edit_needs_new_preview_package_and_independent_review_then_source_hold \
  tests/test_ml_pilot_attestations.py::test_actual_three_account_preview_commit_and_exact_recovery \
  tests/test_ml_pilot_evidence.py::test_byte_replay_is_read_only_and_never_turns_missing_declarations_into_acceptance \
  tests/test_ml_pilot_participant_wire.py::test_participant_workbench_real_native_wire \
  tests/test_ml_pilot_review_admission.py::test_real_four_file_preflight_binds_each_account_without_any_database_write \
  tests/test_ml_use_rights_wire.py::test_independent_rights_workbench_native_wire \
  tests/test_ml_use_runs_wire.py::test_run_workbench_native_wire
```

Each repetition requires a fresh directory. The guarded runner creates private
PostgreSQL and Redis services, verifies ownership, accepts no production DSN,
and removes only that invocation's services. All seven producer tests passed in
**55.19 seconds**. The runner then confirmed successful service cleanup. The
JUnit receipt records seven tests, zero failures, zero errors and zero skips.

Exact original producer bytes were copied into seven new
`materials20261002r6.wire.json` archives. The [R6 manifest](capture-manifest-materials-2026-10-02-r6.json)
records original output paths, producers, archive paths, SHA-256 values, byte
counts and source-pin counts. Each of the six ML captures binds **635 inputs**;
discovery binds its narrower **313-input** inventory. All **4,123 pin entries**
matched both the capture-start snapshot and the final frozen repository bytes.
There are 635 distinct Python/schema inputs in the combined pin inventory.

The native producers do not include packaged resources in their pin lists.
A separate pre/post snapshot verified all **five resource files** without
changing the producers or inventing extra pins in their output. The numeric
seed contains **39 pending source candidates**, after withholding the two bulk
superconductivity tokens previously misclassified as sample form. Its file
SHA-256 is
`405109c67636a5157cbc9efcf8e4fbbc9570864fdffe097dbb91eb895a72619c`;
its internal seed digest is
`810b25f4bec44212efe739a1b03d60bfc83c71cabd89bdfd332b9c1fde70c534`.
The classification seed remains byte-identical to R5, with two pending source
statements, file SHA-256
`d7bf29439311fb7c210fa34f339c47a4e3720775c735e7cfd6218648bcdb5b34`
and internal digest
`6aa56ccc9b4f1cfbf110dfa692cb4f6474539a674399414040346943db671787`.
This resource inventory is separate from protocol source pins and does not
grant source review, scientific acceptance or property promotion.

All **370 pre-existing wire files**, including **303 historical native
archives**, retained their original bytes and SHA-256 values. The additions
bring the inventory to **377 wire files / 310 native archives**. Current
frontend helpers, component imports and the rights visual fixture use R6.
Six exact R6 archive assertions were added, preserving all **127 previous
complete archive assertions** with their occurrence counts. All **131 previous
literal SHA-256 occurrences** across the component directory were also
preserved. The resulting totals are **133 archive assertions / 137 component
hash occurrences**. These are distinct inventories: four component hashes are
used outside complete archive assertions. The review-preflight archive remains
retained evidence without a direct frontend import.

The history snapshot also checked **46 pre-existing capture, manifest and
triage documents** across the entire `docs` tree, preserving their byte counts
and SHA-256 values. This is a broader document inventory than the materials-only
scope described by preceding capture receipts. Current release and acceptance
documents are maintained separately; this capture did not rewrite historical
proofs or add secret-scan exclusions.

The six focused frontend protocol suites passed all **384 tests** in **3.31
seconds**. Their current-source checks re-read pinned backend files; historical
archive checks retain every prior exact assertion. The private bookkeeping
directory is `/tmp/sclib-materials-recovery-r6-bookkeeping-20261002`, with final
source/resource pins, history snapshots, original producer and frontend logs,
and exact-copy verification. Installed-wheel verification, complete release
regression, CI, deployment and public production acceptance are separate gates.

These captures use synthetic accounts, evidence and review events, plus
explicitly declared compiler doubles. They verify the tested native SQL/HTTP
protocol behavior under the frozen inputs. They do not establish scientific
validity, complete literature coverage, source permission, candidate promotion
or authorization to train a model. No production data or credentials were used.
Any subsequent secret-scan finding requires inspection of its exact bytes and
field; historical exclusions must not be broadened.
