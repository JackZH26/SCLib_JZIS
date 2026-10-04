# Continue from a native QE reading

The calculation reader now carries its reconstructed preparation into a collapsed
**Prepare a follow-up calculation** panel. A researcher can change the k mesh,
cutoffs, electronic controls or another explicit setting without recreating the
coordinate candidate or reselecting the original UPFs. The rationale is required.

This connects native result inspection to the next calculation input. It does not
submit a job, authenticate an execution, save a private server record or promote a
scientific property. The current supported parent is a fixed-geometry SCF execution,
including a report of nonconvergence. Relaxation output needs an explicit final
coordinate model; the interface does not silently replace it with initial geometry.
Initialization is still read separately and does not supply a prior SCF result.

## Preservation and provenance

The original reading export remains `discovery-qe-output-reading/1.0.0`, byte-for-byte
under the same file inputs. The in-memory context separately retains the regenerated
candidate batch, preparation and original UPF bytes. These bytes are neither uploaded
nor embedded in reading or follow-up exports. Clearing/replacing the selected files
removes the associated panel and pending asynchronous work cannot restore it.

Before another input is prepared, the code copies the context and requested settings,
checks the reading JSON and digest, reconstructs the old preparation from original
UPFs and source geometry, and checks its exact association to the reading. The new
input is generated through the same existing preparation path. No frozen manifest
contract or previous result is rewritten.

A new, independent `discovery-qe-follow-up/1.0.0` record contains:

- The original reading, its filename and SHA-256, and the previous preparation digest.
- The new preparation manifest and its digest.
- Every changed settings field with its before/after values.
- The researcher's stated reason, candidate identity and original coordinate digest.
- Explicit scope for an unexecuted new run, no inherited result and no established
  cross-run comparability.

An intentional repeat with no parameter change is identified as `repeat_preparation`.
A charge, spin, atomic mass or calculation-type change remains visible; the provenance
link does not make such runs a numerical convergence series. There is no wavefunction
restart and no relaxed-coordinate import. The researcher runs the new input outside
the website, then reads its native files separately. Added convergence-study readings
remain available while the current reader changes files.

## Verification

Contract and component checks cover exact reading compatibility, source/candidate/UPF
integrity, changed settings, unchanged repeats, nonconvergence, unsupported parent
runs, explicit rationale, snapshot-before-await behavior and stale-export clearing.
Synthetic header-only UPFs exercise contracts only; native execution acceptance uses
full original public PSLibrary pseudopotentials in a private local run directory.

The actual browser-selected 6³-mesh reading was used to prepare an 8³-mesh run of
the same three-atom AlB₂ proposal. Only `mesh` changed. The six real downloaded
files were checked against the prior preparation, original UPFs and each other.
The follow-up record is 36,475 bytes, SHA-256
`3c3ac43bbcddf33da486a2a74a7e7125f74ce1ea897b96f4343de2e131a7b7e4`.

Using the same pinned QE 7.5 executable and full original UPFs, the downloaded
initialization and execution inputs exited successfully. The bounded one-thread
SCF took approximately 22 seconds and reported nine iterations, energy
−31.20095847394393 Hartree/cell. Its native output was read back through the
actual browser and added to the existing study. The 4³/6³/8³ window remains
0.0026491570079407722 Hartree/atom, above the example 1e-4 tolerance. This is
workflow validation on a constructed candidate, not a phase-stability or Tc result.

An independent local reconstruction matched the actual downloaded follow-up,
manifest, new native reading and three-run study byte for byte. Native inputs,
XML/stdout, run receipts, downloads, screenshots and hashes remain in the private
`qe_follow_up_2026_10_05` audit. The checked-in synthetic tests do not substitute
for this native acceptance. All 2,841 frontend unit/component tests and 46 source
checks passed; 83 targeted checks include the temporary private native replay.
Production build and exact-head CI/release are tracked separately.

Final browser acceptance at 320, 390 and 1280 px has no document-level horizontal
overflow. Editing the rationale removes the stale export; replacing native files
removes the old follow-up panel while retaining explicitly queued comparison
readings. Clearing files removes the current preparation. No browser warnings or
errors were observed. The final copy-only revision also passed a production build.
