# Materials recovery native protocol captures, 2026-10-02 R7

This fresh capture follows the sample-form subject-binding correction. The R6
guard correctly withheld bulk superconducting properties from sample form, but
also withheld two explicit NbN thin-film statements when the surrounding text
contained other formula-like tokens. The final helper now retains an explicitly
bound material/form noun phrase in a comparison, while preventing another
compound's form from transferring by cooccurrence. Bulk superconductivity and
thermodynamic response remain separate from physical specimen morphology.

All backend and resource owners explicitly froze their final inputs before the
unchanged seven native producers ran once in a new R7 directory. The final
literal-helper file SHA-256 is
`13a2e420f124945facce8264b3bf9a8bbddd499d899d534a50eb053427dc6b8e`.
The [R6 capture](SCLIB_NATIVE_CAPTURES_2026-10-02_R6.md), saved in immutable commit
`49020f06b2a3459379033985ab9cc60a1a26f5e3`, remains historical engineering
evidence with its original bytes and pins. No R6 or earlier capture, hash
assertion, manifest or historical capture/triage document was rewritten.

Run from the recovery repository root with the existing `api/.venv`:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py \
  --backend native --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite api -- \
  -q --tb=short --basetemp=/tmp/sclib-materials-recovery-captures-20261002-r7 \
  --junitxml=/tmp/sclib-materials-recovery-captures-20261002-r7.xml \
  tests/test_discovery_main_barrier.py::test_barrier_edit_needs_new_preview_package_and_independent_review_then_source_hold \
  tests/test_ml_pilot_attestations.py::test_actual_three_account_preview_commit_and_exact_recovery \
  tests/test_ml_pilot_evidence.py::test_byte_replay_is_read_only_and_never_turns_missing_declarations_into_acceptance \
  tests/test_ml_pilot_participant_wire.py::test_participant_workbench_real_native_wire \
  tests/test_ml_pilot_review_admission.py::test_real_four_file_preflight_binds_each_account_without_any_database_write \
  tests/test_ml_use_rights_wire.py::test_independent_rights_workbench_native_wire \
  tests/test_ml_use_runs_wire.py::test_run_workbench_native_wire
```

Each repetition requires a fresh output directory. The guarded runner creates
private PostgreSQL and Redis services, verifies ownership, accepts no production
DSN and removes only that invocation's services. All seven producer tests passed
in **55.80 seconds**, followed by confirmed successful service cleanup. The
JUnit receipt contains seven tests, zero failures, zero errors and zero skips.

Seven exact original outputs were copied byte for byte into new
`materials20261002r7.wire.json` archives. The [R7 manifest](capture-manifest-materials-2026-10-02-r7.json)
records each original output path, producer, archive, SHA-256, byte count and pin
count. The six ML captures each bind **635 inputs**; discovery binds its narrower
**313-input** inventory. All **4,123 pin entries** matched the pre-capture
snapshot and the final frozen repository bytes. The distinct combined inventory
contains 635 Python/schema inputs.

The producers do not pin packaged resources. A separate pre/post snapshot
verified all **five resource files**, without modifying the producers or adding
invented pins to captured responses. The resources are byte-identical to R6:

- The general seed still contains **39 pending numeric/literal source
  candidates**. Its file SHA-256 is
  `405109c67636a5157cbc9efcf8e4fbbc9570864fdffe097dbb91eb895a72619c`,
  and its internal digest is
  `810b25f4bec44212efe739a1b03d60bfc83c71cabd89bdfd332b9c1fde70c534`.
- The classification seed still contains **two pending source statements**.
  Its file SHA-256 is
  `d7bf29439311fb7c210fa34f339c47a4e3720775c735e7cfd6218648bcdb5b34`,
  and its internal digest is
  `6aa56ccc9b4f1cfbf110dfa692cb4f6474539a674399414040346943db671787`.
- The MDR attribution, manifest and compressed reference metadata also retain
  their R6 byte hashes. These resources do not grant source review, scientific
  acceptance, sample-state association or property promotion.

The pre-capture history snapshot contained **377 wire files**, including **310
native archives**. Every pre-existing file retained its original bytes, size and
SHA-256. Seven additions bring the inventory to **384 wire files / 317 native
archives**. Current helpers, component imports and the rights visual fixture
use R7. Six exact R7 hash assertions were added while preserving every **133
previous complete archive assertion** and **137 previous component literal
SHA-256 occurrence**, including their occurrence counts. The resulting totals
are **139 archive assertions / 143 component hash occurrences**. Four hashes
remain outside complete archive assertions. The review-preflight archive is
retained without a direct frontend import.

All **48 pre-existing capture, manifest and triage documents** in the entire
`docs` tree also retained their original bytes and hashes. This snapshot includes
R6 history. Current release/acceptance documents and exact future secret-scan
reviews are separate; this capture did not add or broaden scan exclusions.

The six focused frontend protocol suites passed all **384 tests** in **3.50
seconds**. Their current-source checks re-read frozen input files, and archive
checks retain every historical exact assertion. Private bookkeeping is stored
at `/tmp/sclib-materials-recovery-r7-bookkeeping-20261002`, including pre/post
source and resource snapshots, history inventories, original logs, and
exact-copy verification.

These seven captures assess native SQL/HTTP protocol behavior with synthetic
accounts, evidence and declared compiler doubles. Material-field endpoint
tests, source-scope extraction comparisons, installed-wheel checks, full
frontend regression and CI are separate evidence. No producer used production
data or credentials. The captures do not establish scientific correctness,
human source review, literature completeness, candidate promotion, training
permission, deployment or public production acceptance.
