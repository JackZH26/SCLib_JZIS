# Scientific-program input/output preflight

Status: private, offline engineering preflight; **not a database importer**.
This first real-file adapter advances [ML05 / #67](https://github.com/JackZH26/SCLib_JZIS/issues/67)
without changing the frozen 0045 registry, 0053 shadow loader, 0054 capsules,
0064 companion, or ML task v1/v2 contracts.

## What is implemented

The `qe-matdyn-flfrq` adapter reads a bounded Quantum ESPRESSO `matdyn.x`
input and its complete native frequency file. It extracts one provisional
property: `phonon_min_frequency`, the **minimum over the supplied sampled
q-points**, not a proof of full-Brillouin-zone stability or superconductivity.

- All q-points and mode values remain in their original order, with raw number
  text and exact zero-based, end-exclusive byte spans plus one-based line numbers.
- Native signed wavenumbers are retained in `cm^-1`; the signed cyclic-frequency
  conversion to THz uses the exact factor `0.0299792458`. Negative frequencies
  are not removed, clamped to zero, or converted to absolute values.
- Repeated q-points are retained. They can encode distinct path approaches at
  Gamma; duplicates are not automatically corrupt observations.
- The declared numeric Cartesian path/list is checked against every output
  coordinate and count, allowing only the documented printed-coordinate rounding.
- Acoustic-sum-rule settings and atomic-mass overrides remain explicit input
  observations. Documented defaults are labeled as defaults, not observations.
- Unsupported coordinate transformations, symbolic path labels, DOS-grid input,
  two-dimensional treatment, and other unsupported settings are quarantined.
- Both historical three-column q records and newer four-column records with
  weights are distinguished. A repository tag is **not** the executable version
  that produced a stored reference output.

The authoritative format references are the pinned
[QE matdyn source](https://github.com/QEF/q-e/blob/770a0b2d12928a67048e2f3da8d10d057e52179e/PHonon/PH/matdyn.f90)
and the [official input specification](https://www.quantum-espresso.org/Doc/INPUT_MATDYN.html).
The adapter is deliberately narrower than the complete QE input language.
It never executes an upstream script, follows a program input path, or launches
a calculation. The format convention supplies the unit interpretation; a bare
frequency file is not self-authenticating evidence of its producer or units.

## Package contract

`scientific-program-package/1.0.0` is a closed canonical-JSON manifest with:

| Field | Meaning |
|---|---|
| `version`, `adapter_id` | Exact supported contract and adapter |
| `files` | Complete inventory of logical name, role, SHA-256 and actual size |
| `context.material_formula`, `material_id` | Optional unverified declarations; no SQL association |
| `context.geometry_scope` | `bulk_3d`, `other`, or `unknown`; not a geometry review |
| `context.source_url`, `source_revision` | Optional documentary HTTPS location and revision; never an availability date |
| `context.license_spdx` | Optional declared license label; not independently verified rights |
| `declarations` | Exactly unreviewed, execution-unattested and not ML-approved |

Exactly one `input` and one `frequency` entry are required. Optional `license`
and `provenance` entries retain documentary evidence without granting authority.
The observed input `flfrq` must match the frequency entry's logical file name.
All physical files are immutable captures named `<sha256>.bin`; names in the
program input are never opened or fetched.

The package directory contains only `manifest.json` and the exact declared
content-addressed leaves. Provide the full canonical manifest SHA-256 through an
independent trusted channel. Recomputing a hash from an untrusted replacement
package and supplying that replacement hash does not authenticate the source.

## Offline operation

Use the repository's locked API interpreter. No database credentials are needed:

```sh
api/.venv/bin/python scripts/scientific_program_preflight.py \
  --manifest /absolute/private/package/manifest.json \
  --manifest-sha256 INDEPENDENT_COMPLETE_FILE_SHA256
```

Without `--output`, this command changes no files. To retain a private report,
add `--output /absolute/private/reports/new-report.json`. The destination must
not already exist and must not be inside the closed input package. Parent
directories must already exist and contain no symlink traversal.

Exit codes:

- `0`: files parsed within the supported engineering subset; scientific and ML
  authority remain false, and material/state/structure/run bindings unresolved.
- `3`: a captured package contains quarantined program data. A requested report
  is still written so failure cases do not disappear from the denominator.
- `2`: invalid package, pin, filesystem state or output request; no new report
  is published, and stderr contains no raw source text, credentials or paths.

The report is deterministic for the same complete bytes and source revision.
It includes package/file/compiler source hashes, all parsed observations,
candidate disposition, complete package accounting and unresolved gates.
Requested output is canonical JSON, owner-only (`0600`) and never overwritten.
Both full input bytes and file/inventory signatures are rechecked before output.

Limits are 16 manifest entries, 64 KiB manifest, 4 MiB per artifact and 8 MiB
combined package/report. The parser additionally bounds input to 256 KiB,
768 modes, 1,000 q-points and 200,000 mode observations. A report that exceeds
the common JSON node or byte budget is rejected, not silently truncated.
Symlinks, hard links, devices, FIFOs, undeclared leaves, duplicate JSON keys,
nonfinite values, numeric underflow and mismatched pins are rejected.

## Genuine upstream reference-file canaries

The separate, **explicitly networked** helper
`scripts/fetch_qe_matdyn_canaries.py` downloads only fixed, hash-pinned public
files from QEF/q-e commit `770a0b2d12928a67048e2f3da8d10d057e52179e`:

```sh
api/.venv/bin/python scripts/fetch_qe_matdyn_canaries.py \
  --output-parent /absolute/existing/private/directory
```

It creates a new owner-only directory; it does not overwrite a previous run.
Keep these third-party captures outside the repository. Only retrieval code,
hashes and our audit summaries belong in the SCLib commit. The root repository
license bytes are retained as documentary evidence, without asserting that an
operator has completed a per-artifact redistribution review.

The three intended contexts are bulk Al (`example14`), bulk AlAs
(`GRID_recover_example`) and two-dimensional BN (`example17`). These are real
upstream **reference-format files**, not independently authenticated calculations,
experimental superconductivity results or approved training data. Al and AlAs
inputs are reconstructed from exact retained heredoc spans; only the explicitly
documented AlAs `PREFIX` substitution is applied. Derivation metadata and the
original script bytes are retained, and no shell is evaluated. BN has an actual
standalone input file. A successful format test is not a full reproduction of
the force-constant computation.

## Scientific boundaries and next SQL stage

All report authority flags remain false. In particular:

- Formula/context strings do not prove the package belongs to a particular
  material, phase, sample, pressure, magnetic field, structure or run.
- Program-file completion is not convergence or execution attestation. A tag,
  checkout time, file mtime, or local capture time cannot become a historical
  public availability witness for a result.
- Negative rounded frequencies require context and convergence review; their
  mere presence is not an automatic instability verdict. Missing values are
  not zeros or negative superconductivity labels.
- No temperature is inferred from electronic smearing. No total energy is
  relabeled formation energy or hull distance. No DOS, lambda, omega-log or
  stiffness field is silently synthesized by this adapter.
- Calculation CPU time, wall time and monetary cost are `null`: these files do
  not contain actual cost receipts. Import elapsed time is also `null` in this
  deterministic report, not a claim of zero processing cost.

The next implementation must bind a retained package to independently pinned
material/state/coordinate rows, verify force-constant/run ancestry, and write
only pending 0045 results under authenticated, idempotent transactions with
durable attempt/failure receipts. Raw source artifacts must connect through
existing `event_evidence` edges so frozen 0054 closure remains valid. Independent
scientific/source-time/rights reviews and 0064 source bindings remain subsequent
gates. Unpublished operational outputs must not acquire fabricated Paper/Work
records solely to pass the existing literature-based ML temporal contract.

ML05 remains open until these SQL, review, real-package replay, state/run and
cost-accounting acceptance requirements are met. This preflight is not a public
endpoint, a new migration, production backfill, source publication or ML result.
