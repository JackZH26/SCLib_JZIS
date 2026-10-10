# Offline PBEsol JobSpec envelope validation

`validate_pbesol_inputs(spec, files, *, expected_runtime_id)` in
`scripts/sclib_compute/pbesol_native_contract.py` connects an existing JobSpec to
the fixed PBEsol input binding. It checks internal consistency only. No worker,
guardian, service or CLI imports this adapter, so it cannot dispatch a job.

The profile document is the existing `sclib-pbesol-input-binding/1`, stored as
`pbesol-input-binding.json`, alongside `source.in`, `input.in`, `delta.json`,
`preparation.json` and the expected two or three UPFs. There is no new descriptor
JSON schema or `native.json`. The input binding retains its explicit false
execution/queue/scientific flags and null job/runtime/attempt custody.

The validator revalidates a detached complete JobSpec, including nested resources,
FilePins, output rules and uniqueness constraints. This catches `model_construct`,
`model_copy(update=...)` and mutations of lists inside frozen Pydantic objects.
The independent expected runtime ID is a strict bounded Identifier. It must come
from the caller's trusted installation/review expectation; copying the job's own
runtime ID into that parameter does not establish independent runtime identity.

It verifies:

- Exact seven/eight input artifacts and JobSpec name set, byte lengths and SHA-256;
  metadata≤64KiB/file, UPF≤1MiB/file, entire input envelope≤4MiB.
- Unchanged source binding validation for the four pinned source states and their
  initialize/scf preparation stages. This does not approve a material phase.
- `qe_initialize` with initialize, `qe_scf` with scf, max_attempts1, expected
  runtime ID, and `state_ref` equal to the binding's exact source identifier.
  `case_ref` and `action_ref` remain opaque operator metadata; no research plan,
  action budget or RPS association is inferred from them.
- Exactly stdout/stderr/XML/execution outputs, bounded respectively by
  8MiB/1MiB/8MiB/128KiB. Their sum fits the declared output envelope, which is at
  most32MiB. These profile ceilings do not prove actual live storage capacity.

`ValidatedPbesolInput` is a frozen slots dataclass containing only immutable bytes,
strings, integers and a tuple of UPF names. Its `binding_document` retains the
exact validated original bytes. It holds no mutable model, list, dictionary or
caller reference. The projection carries raw binding length/SHA, selected
input/manifest names, source ID, stage, prefix, runtime/kind, and complete JobSpec
and input-manifest digests. Declared input order is preserved in those digests;
reordering produces a different identity rather than being silently normalized.

A valid envelope is not live admission. The function does not read executables,
check the clock, contact the coordinator, reserve a budget, test current memory,
inspect a lease or generate results. An expired JobSpec can be checked offline
for historical custody. Only installed source/profile/preparer trust reads occur
inside the unchanged binding validator. The existing PBE/native-v1 validator
continues to reject the exact PBEsol deck even inside an otherwise complete v1
source envelope.

The test JobSpecs are explicitly synthetic in-memory scaffolding, including
when they wrap actual frozen source bytes. Tests never enqueue them or save them
as real execution evidence. Ordinary CI explicitly skips eight private-input
checks unless `SCLIB_PBESOL_FORMAL_BUNDLE` is set; a configured missing/changed
input fails. Production runtime and scientific acceptance remain unperformed.

```sh
python -m pytest tests/test_sclib_pbesol_native_contract.py -q
SCLIB_PBESOL_FORMAL_BUNDLE=/absolute/private/formal-v2 \
  python -m pytest tests/test_sclib_pbesol_native_contract.py -q
```

The next integration can reuse this same validator in worker preflight, independent
guardian prelaunch checks and read-only export custody review. Each integration
still needs its own reviewed dispatch/receipt/reading changes; this module does
not implicitly enable them.
