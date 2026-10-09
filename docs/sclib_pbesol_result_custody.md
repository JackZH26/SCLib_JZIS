# PBEsol returned-initialization custody

This inert reader checks one bounded, pinned initialization return against a
separately retained submission and runtime configuration. It does not fetch
artifacts, execute QE, submit work, install a runtime, grade candidates or grant
scientific acceptance. All returned outputs used in its tests are synthetic.

`validate_returned_initialization(export_bytes, input_files, output_files, *,
submitted_spec_bytes, runtime_config_bytes, adapter_release_manifest_bytes,
expected)` accepts immutable bytes and an exact `CoordinatorPins` record. It
snapshots caller maps and reference values, validates raw hashes and strict JSON,
and reruns the existing PBEsol input validator. It normally imports the canonical
initialization reader; no private loader or alternate source trust is installed.

## Trust and results

Independent coordinator records must supply the expected raw export, submission,
runtime and release hashes, plus node, attempt, fence and absolute attempt root.
An internally consistent graph cannot prove that these root references came from
an authenticated coordinator. `custody_verified` therefore means only the
machine-readable scope
`conditional_byte_graph_given_independent_coordinator_pins`.
`coordinator_capture_authenticated` remains unknown. The function reads only the
input validator's existing, fixed, hash-pinned trust files; evidence paths are
never opened, and reported executable paths are never run or inspected.

The checked chain binds the exact JobSpec and input order, four returned files in
the required lexical order, file sizes and hashes, output caps, execution record,
manifest, reconstructed Completion and receipt. It also binds source state,
initialization stage, method profile, runtime configuration, fixed MPI argv and
single-thread controls. Contradictory export order is rejected, not silently
sorted into agreement.

Transport consistency, capture completeness, current-attempt status, raw process
outcome and semantic initialization reading remain separate fields. Currentness
means only the pinned export's state, with no live lease or freshness promise.
Upload heartbeat elapsed/memory, frozen Completion elapsed and solver duration/
peak memory are distinct observations and are not equated. A historical lost
attempt can retain its failure code and quarantined return without becoming a
current successful attempt.

The canonical UTF-8 boundary rejects non-UTF-8 bytes or declarations, NULs and
DTD/entity declarations before any returned XML parser is called. Such evidence
is rejected without rewriting its raw bytes, hashes or reported `xml_parseable`
check. Supported but malformed UTF-8 XML retains its separate unreadable status.
A completed process must supply a concrete integer exit code; legitimate absent
prelaunch observations can retain an unknown exit. OS exit 255 remains process
failure even when XML status 255 describes initialization only.

The release manifest is currently opaque, separately pinned JSON. Its byte
identity does not verify its contents, installation or the executing process.
Release-content verification, installation, runtime attestation, execution
readiness and next-stage readiness therefore remain false at this implementation
boundary. Scientific acceptance, candidate grade changes and Tc calculation also
remain false; physical outputs remain null. These are recorded limitations of
this reader, not permanent rules against future verified integration.

## Tests and provenance

The portable suite contains 100 synthetic graph cases spanning four source
contexts and needs no private input files. Four optional cases use the existing
strict `SCLIB_PBESOL_FORMAL_BUNDLE` helper. Unset means an explicit skip; an empty,
missing or corrupt supplied path fails. The helper verifies the pinned bundle and
preparation manifest before following paths. Even with authentic inputs, all
returned XML, stdout, execution metadata, JobSpecs and receipts remain synthetic.

Run `python -m pytest tests/test_sclib_pbesol_result_custody.py -q` from the
repository root in the compute test environment. The dedicated compute workflow
includes this module and suite in lint and test selection. Static source and
review provenance are recorded in
`docs/data/discovery-batches-20261008/pbesol-result-custody-provenance-v1.json`.
These hashes record implementation history, not runtime attestation.

The next integration work is finite and separate: verify a release's worker,
guardian, adapter and trust-file contents; bind an actual installation receipt
and distinct runtime/node grant to an attempt; add the reviewed worker/guardian
seams; and collect a genuine controlled initialization return. Authenticated
artifact capture and live execution acceptance require their own evidence.
SCF reading remains unimplemented, and initialization cannot establish EPC, Tc,
stability or scientific validity.
