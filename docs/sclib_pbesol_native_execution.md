# One-shot PBEsol initialization execution

The fixed `PbesolWorker` and `pbesol_supervisor` entrypoint reuse the existing
native transport, guardian loop, lease/fence handling, sampled resource watchdog,
process cleanup, durable outbox and ACK replay. This slice enables only
`qe_initialize`. A PBEsol SCF job is rejected before launch; its scientific
reader and admission remain separate work. The default native PBE entrypoint
retains its existing behavior.

## Explicit local configuration

The operator supplies an absolute, non-symlink local profile path and its expected
raw SHA256. The profile and referenced files cannot be group/world writable.
`sclib_compute_pbesol_worker.py` accepts private mTLS configuration, that profile
path/hash and a separate state directory. It runs one cycle, with no serve mode,
automatic retry loop or queue-controlled command/module selection. It requires a
dedicated non-root user. A repeated invocation recovers the same durable attempt;
it does not rerun an attempt whose execution already started.

The closed `sclib-pbesol-local-profile/1` record contains:

- `method_profile`: `pbesol-source-coarse-qe75/1`.
- `stage`: `initialize`.
- `runtime_id`: the separately provisioned runtime identity.
- `runtime_config_path` and `runtime_config_sha256`: absolute path and raw hash
  of a complete `sclib-native-runtime/1` configuration, including binary pins and
  resource limits. Default-filled or incomplete runtime records are rejected.
- `adapter_release_manifest_path` and `adapter_release_manifest_sha256`: absolute
  path and raw hash of the separately retained release JSON.

The release JSON is opaque byte provenance at this stage. Matching its hash does
not verify installed code contents, installation history or authenticated origin.
No installation-verification or remote-attestation flag is granted. An exact
release-content/installation verifier remains needed before a real rollout is
accepted. Profile paths and hashes come from local operator configuration, not a
JobSpec, returned receipt or self-declared queue value.

## Launch and recovery boundary

The worker validates the original PBEsol envelope and preserves an immutable
`input-evidence` copy of the exact downloaded inputs, capped at 4 MiB. It stages
separate work files and saves the input projection plus profile identity. The
dedicated guardian independently reopens the actual staged deck, UPFs, source,
delta, preparation manifest and binding immediately before the shared loop's
`Popen`. It reruns the existing source-bound validator; a saved descriptor alone
is insufficient.

That last check also reopens pinned local configuration and checks executable
hashes, fresh owner-only `work/pseudo/out/tmp` directories, empty initial scratch,
current lease and absolute launch deadline. It then checks actual available RAM
and free disk again, followed by worker-pipe liveness. The MPI command has six
fixed arguments; lease freshness is rechecked after potentially slow resource
inspection and immediately before the final launch deadline check. All five
thread controls are one. No queued shell or module
is executable. The shared loop still watches process trees and resource use;
these are sampled limits, not a kernel reservation or filesystem race-proof
sandbox against a malicious process with the same operating-system identity.

If staged work changes and launch is rejected, the original input evidence still
supports a bounded interrupted return. The altered work and guardian diagnostic
log remain local. The worker does not need to repair work files or retry a solver
to report that failure. An early guardian exit is handled by the existing
explicit no-result fallback. Dual worker/guardian loss with unknown process
cleanup still blocks recovery for verified operator cleanup.

Recovery binds the saved profile, runtime, release, descriptor and original input
archive. It validates the frozen execution/outbox identities and preserves exact
saved bytes, including elapsed time. A completed ACK replay does not require the
currently installed executable to still match the old binary, because it launches
nothing; it does require the original pinned configuration and input evidence.
Changing those identities blocks replay instead of relabelling the old result.

The returned `sclib-pbesol-qe-execution/1` record matches the inert custody reader's
contract. UTF-8/DTD/entity checks precede output XML parsing. Raw OS exits, missing
or truncated captures and failed outcomes remain distinct from initialization
semantics. No calculation of Tc, scientific acceptance or candidate score is
performed by execution or transport success.

## Validation and deployment limits

The new tests use an owned temporary service/store, synthetic input trust and
mocked solver processes. They cover complete writer-to-custody roundtrip,
last-moment staged input/resource/lease changes, failure return, partial-outbox
recovery, lost ACK, corrupted original evidence and initialize-only capability.
The existing native PBE suite supplies legacy process/failure/recovery coverage
with executable fixtures, never scientific QE. The dedicated compute workflow
runs both suites; no dependency or release-policy change is required.

No real PBEsol run, Mini installation, runtime registration, resource allocation,
authenticated capture or 24-hour acceptance is established by these tests.
The first real operation requires a distinct node/runtime grant and an exclusive
one-shot handoff: drain and reconcile the old worker, stop its service, verify no
owned MPI processes remain, execute one admitted initialization, acknowledge its
return and verify cleanup before restoring the old service. There is no shared
cross-profile host lock here, so unattended alternating or concurrent profile
services remain unsupported. Registration capability is immutable: adding SCF
later requires an explicit supported node/runtime transition, not silently
expanding the current registration. SCF also needs its reviewed reader and budget.
