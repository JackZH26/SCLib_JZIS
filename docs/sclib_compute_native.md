# Native QE integration contract — 2026-10-08

This opt-in adapter accepts `qe_initialize` and `qe_scf` only. It does not enable
those kinds on the service, issue node certificates, approve scientific results,
or establish M4 acceptance. Dummy registration and execution remain unchanged.

## Provisioned runtime

Run the worker as the dedicated non-root compute account. An administrator
provides a private mTLS client config, a separate runtime JSON and immutable
resolved binary paths. Record the full environment/library versions separately;
hashing the two executable files does not pin every dynamically linked library.
Never put private keys or populated client configs in a public handoff bundle.

```json
{
  "schema_version": "sclib-native-runtime/1",
  "runtime_id": "qe-7.5-770a0b2-arm64",
  "pw": {"path": "/absolute/resolved/pw.x", "sha256": "REPLACE_WITH_SHA256"},
  "mpiexec": {"path": "/absolute/resolved/mpiexec", "sha256": "REPLACE_WITH_SHA256"},
  "max_cpu_cores": 4,
  "max_wall_seconds": 900,
  "max_memory_bytes": 12884901888,
  "max_scratch_bytes": 4294967296,
  "min_free_bytes": 21474836480,
  "min_available_memory_bytes": 25769803776,
  "heartbeat_seconds": 5
}
```

These are bounded initial operational settings, not measured resource estimates.
The actual Mini config must retain its existing 149199387648-byte free-disk floor.
Before claiming and again before launching, available RAM must meet the configured
floor. macOS uses `(free + inactive + speculative pages) × page size`, deliberately
excluding wired/active/compressed memory; Linux uses `MemAvailable`. Missing actual
statistics refuses execution. Total installed RAM is never used as a substitute.
The process state directory must be owner-only, contain no symlink ancestor, and
be dedicated to this worker. Its lock permits one simultaneous job. Provision a
separate native node identity/runtime grant; the transport-test node registration
is immutable and must not be repurposed. Grant only the two supported kinds.

```sh
python scripts/sclib_compute_native_worker.py \
  --config /absolute/private/native-client.json \
  --runtime-config /absolute/private/native-runtime.json \
  --state-dir /absolute/private/native-state
```

The default runs one cycle. `--serve --max-jobs 0` explicitly enables the bounded
poll loop. Enable a persistent LaunchDaemon only after actual node acceptance;
its service configuration must also stop all processes on teardown. A 24-hour
soak is measured elapsed operation, not a local test-suite result.

This is a bounded staging campaign, not indefinite unattended retention. At the
current 30-second idle interval, the service's 10,000 persisted-claim cap would
be reached in approximately 3.47 idle days. The first 24-hour soak fits that cap;
longer operation needs an operator-reviewed polling/rotation policy with archived
state and no pending outbox. Reaching a campaign cap requires maintenance and
must not be reported as a healthy infinite loop. Node certificates also need
renewal before their recorded expiry (the current issuance policy is seven days).

## Frozen job inputs and outputs

Use the existing `JobSpec` with one attempt, exact runtime, an unexpired deadline
and bounded resources. MPI ranks equal `resources.cpu_cores`; jobs provide no
commands, arguments, environment variables, script hooks or arbitrary paths.

The flat staged input set is:

1. `native.json`, with exactly the descriptor below;
2. the original generated input deck (execution or initialization);
3. the original `discovery-qe-input/1.0.0` JSON manifest;
4. every UPF named by that manifest, as an individual flat artifact.

```json
{
  "schema_version": "sclib-native-qe/1",
  "input_name": "sclib_example.in",
  "source_manifest_name": "sclib_example.json",
  "prefix": "sclib_example",
  "pseudo_names": ["B.UPF", "Mg.UPF"]
}
```

Every artifact is SHA-256/length checked against `JobSpec`; the source manifest
must bind the selected deck and UPFs. The first adapter additionally enforces a
closed preparer grammar: neutral, nonmagnetic SCF; three reviewed namelists;
explicit fixed cell/positions and automatic k mesh; `restart_mode=from_scratch`,
`pseudo_dir=./pseudo`, `outdir=./out`, and `nstep=0` for initialization or `1` for
SCF. Unsupported options need a separately reviewed adapter change. The worker
never rewrites the scientific deck. Prepared manifest semantics beyond these
transport/execution checks still require the independent scientific importer.

The output set is exactly `stdout.txt`, `stderr.txt`, `data-file-schema.xml` and
`execution.json`. Recommended first-job maxima are 8 MiB, 1 MiB, 8 MiB and 128 KiB,
respectively; raise the service's default dummy artifact limits before use.
Missing output is represented by zero bytes and an explicit capture status.
Oversized output is a bounded prefix marked `truncated=true`; raw local evidence
is retained and the outcome is `interrupted`. It must never be treated as a full
scientific result.

## Execution and restart guarantees

The worker persists `execution_started` before launching an independent guardian.
The guardian executes only pinned `mpiexec -n N pw.x -in <staged input>` with a
fixed environment, one thread per rank and a dedicated process session. It checks
aggregate descendant RSS, wall time, scratch/output size and free disk every
approximately 250 ms. These are sampled watchdog limits with possible overshoot,
not a kernel memory reservation. Loss of the worker pipe, a refused heartbeat,
transport interruption or cancellation terminates the process group and tracked
descendants. The guardian independently enforces the last server-confirmed lease
deadline even if a heartbeat HTTP call stalls. There is no speculative execution
through a network outage.

A started attempt is never rerun. On recovery, the worker archives the guardian's
finished output, including explicit interruptions; it does not restart QE from
checkpoints. Native completion adds the `interrupted` outcome to the existing
transport vocabulary. Success requires the expected PWSCF 7.5 header, `JOB DONE`,
parseable XML, zero exit status and (for SCF) a positive convergence message.
These are execution checks, not numerical convergence, stability or Tc evidence.
Explicit nonconvergence remains `not_converged`, distinct from solver failure.

If both worker and guardian disappear without a final guardian record, recovery
fails closed and requires operator verification of process cleanup. It does not
blindly signal possibly reused saved PIDs, claim another job, or invent a clean
interruption receipt. The service teardown/cold-start acceptance remains essential.

Before upload, exact artifacts and the completion body are saved durably. An ACK
loss replays that outbox without rerunning a calculation. Late/cancelled results
are uploaded for an auditable quarantined receipt. `archive.json` binds the
output manifest, completion and server receipt hashes. The original inputs,
supervisor record and raw outputs remain in the private attempt directory.

## Tests and actual acceptance

```sh
python -m pytest tests/test_sclib_compute_staging.py tests/test_sclib_compute_native.py -q
```

The native fault suite uses clearly synthetic pinned executable fixtures. It
exercises exact deck/UPF pins, rejected path/restart/extra-card inputs, explicit
solver outcomes, durable ACK replay, cancellation, wall/output limits and worker
SIGKILL with descendant cleanup. Passing these tests does not mean actual M4 QE
or 24-hour operation passed. Run the real pinned parent initialization first,
retain the full returned XML/stdout, validate them with the independent result
reader, and only then release the first parent SCF/calibration sequence.
