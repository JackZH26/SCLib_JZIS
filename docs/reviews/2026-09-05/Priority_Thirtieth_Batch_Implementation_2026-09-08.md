# Thirtieth implementation batch — real scientific-program preflight

Date: 2026-09-08. Parent revision: `0461e99` on `codex/sclib-research-v2`.
Primary item: [ML05 / #67](https://github.com/JackZH26/SCLib_JZIS/issues/67).
Related delivery audit: [DR03 / #56](https://github.com/JackZH26/SCLib_JZIS/issues/56),
[EN03 / #59](https://github.com/JackZH26/SCLib_JZIS/issues/59) and
[EN01 / #42](https://github.com/JackZH26/SCLib_JZIS/issues/42).

## Outcome and scope

The first genuine-file path now runs from a completely pinned program package
through scientific-format validation into a private, reproducible report. It
does **not** yet write canonical SQL rows. Claiming a full ML05 importer from
these files would omit real structure/state/run bindings, attempt receipts,
and independent scientific/source-time review, so ML05 remains open.

No migration, frozen schema/registry change, production access, paid calculation,
source publication, model training, deployment, Git push or remote issue write
was performed. The goal remains active and incomplete.

## Implementation

- `api/services/qe_matdyn_import.py`: bounded native QE matdyn input/frequency
  reader; all q-points, signed modes, raw text, byte/line locators and sampled
  minimum retained. Numeric Cartesian paths/lists are matched to output records.
- `api/services/scientific_program_import.py`: closed independently pinned file
  inventory, unreviewed context, explicit pairing/quarantine, complete package
  accounting, compiler source pins and false authority flags.
- `scripts/scientific_program_preflight.py`: offline, read-only by default;
  optional new `0600` report, no alias/path traversal, complete recapture and
  original-directory identity held until output publication.
- `scripts/fetch_qe_matdyn_canaries.py`: separately invoked allowlisted public
  retrieval, fixed commit and seven independent content hashes. No shell is
  evaluated. Original scripts, license and explicit input derivations are kept
  in new private capsules outside the SCLib repository.
- [Operator and scientific contract](../../SCIENTIFIC_PROGRAM_PREFLIGHT.md)
  documents limits, exit codes, units, failures, cost missingness and remaining
  SQL/ML gates.

Independent review caught and regression-tested: newline-driven memory
amplification before parsing, non-native Unicode line separators corrupting
line-number claims, and a rename/replacement race allowing output into the
original captured input directory. These were fixed before final canary reports.

## Genuine reference-file results

All files are from QEF/q-e commit
`770a0b2d12928a67048e2f3da8d10d057e52179e`, resolved from `qe-7.5`.
The repository contains historical reference outputs; the tag does not attest
to their executable versions. Input/output associations here are documentary
format checks, not authenticated execution records.

| Context | q-points × modes | Native sampled minimum | THz | Disposition |
|---|---:|---:|---:|---|
| Al, `example14` | 161 × 3 | `0.0000 cm^-1` | `0` | Parsed; context and review pending |
| AlAs, `GRID_recover_example` | 161 × 6 | `-0.0000 cm^-1` | `-0` | Parsed; signed raw zero retained, not an imaginary-mode claim |
| Two-dimensional BN, `example17` | 91 × 6 | `-3.6074 cm^-1` | `-0.10814713129892` | Quarantined for explicit 2D treatment/nonbulk context; seven negative mode observations retained |

Denominator: **3 real upstream reference-format packages; 2 parsed, 1 quarantined,
0 scientifically accepted, 0 admitted ML properties**. Al and AlAs input bytes
are derived from retained exact heredoc spans; AlAs has an explicit, documented
`PREFIX='alas'` substitution. BN has a standalone upstream input. No derived
input is represented as a separately observed executed file.

The BN negative-frequency values are not discarded because their geometry is
outside this initial bulk-oriented subset. Nor are they automatically classified
as physical instability without convergence/context review. A minimum sampled
on a path cannot establish full-zone stability. The parser does not infer Tc,
ambient pressure, physical temperature, convergence, harmonic treatment or
calculation costs. All cost fields remain `null`, not zero.

Complete captured files and three private reports are stored locally under:

`/Users/jackzhou/Documents/YorkMsc/ML-SC/qe-matdyn-canaries-d6c843a22e8c4c35bde392b8937b65c9`

Only code, audit facts and pins are committed here, not third-party input/output
or license file copies. A retained repository license is documentary evidence,
not an independent per-source redistribution review.

| Package | Manifest SHA-256 | Report SHA-256 |
|---|---|---|
| `al-example14` | `2b558caaff631dcf64903f20b1db22af8b768860aba2dceb750bce8360d523d4` | `2fb79b6a6ff01f0f9d988caebeed45b4f5e07bd5265302c93320e39c2efad119` |
| `alas-grid-recover` | `3a174f442e90bceb11df01111a0952381a79eb61d3e5a0df9aa4c5b770025f0d` | `966216fcabcf9d57c1c060c19c10077bb30e6fa0e349895cead6d99fbedfcb06` |
| `bn-example17-2d` | `766672823aef629ac55a91be219c0a186cf82ecb34ce66fdb0fdf7c1f9ec6311` | `b4da6b724795e4fedb0aa5d890ea8243337d97a8ba714e04a3e42cab43a899f8` |

Each complete report was independently recomputed from the stored package in a
subsequent process and reproduced byte-identically. This is offline preflight
reproducibility, **not** the still-missing twice-replayed SQL import acceptance.
The final retrieval utility was additionally exercised against all seven actual
retained upstream originals: it reconstructed all bytes of all three capsules,
not only their manifest hashes, without more network requests or file writes.

## Verification

All executable files were frozen before the final complete scripts rerun. No
existing application service or reviewed corpus was used for destructive testing.

- Guarded native parser tests: **67 passed** in 1.87 seconds.
- Guarded DR03/EN03/EN01 plus Stats/Timeline API regression selection:
  **166 passed**, one existing FastAPI warning, 12.35 seconds; the disposable
  runner removed only its own services/data.
- Frontend Discovery-versioning and background-job components: **13 passed**
  in 1.89 seconds; English/source contracts **35 passed**; current TypeScript
  check passed.
- Complete scripts suite: **728 passed plus 36 subtests**, 9.68 seconds. This
  includes 66 new preflight boundary tests and 65 new fixed-source fetch tests.
- Ruff import/undefined-name checks and `git diff --check` passed.
- Three genuine upstream package reports recomputed exactly; all authority
  fields false. No independent program execution or scientific validation claimed.

Combined executed suites: **1,009 ordinary tests plus 36 subtests**. There are
**198 new tests** in this batch (67 parser, 66 preflight and 65 retrieval). The
separately reported 15 safety tests are included in the complete scripts suite
and are not double-counted. The three real reference-file reproductions are
additional smoke evidence, not added to pytest counts.

No API-wide rerun is claimed for this batch. New code is an isolated offline
adapter/CLI with no router, ORM import or schema mutation; guarded parser and
targeted existing engineering suites plus full script compatibility are the
risk-proportionate checks. The preceding batch's complete API run remains
separate evidence at its own revision.

## Engineering issue delivery audit

The [criterion-level closure audit](Engineering_Issue_Closure_Audit_2026-09-08.md)
maps all DR03 and EN03 criteria to existing implementation and fresh checks,
including the EN01 dependency. No software acceptance blocker was found in that
bounded audit. Real deployment or scientific review is not invented as an extra
acceptance criterion for those engineering issues.

However, read-only GitHub checks found no remote implementation branch, no PR,
and no remote copy of commit `0461e99`; default/main remains `d26fc09`. Their
required implementation delivery links therefore do not yet exist. Correct
status: **local targeted acceptance passed; remote delivery pending**, not
closed or deployed. No issue was prematurely marked complete.

## Next implementation priorities

1. Bind real package artifacts to independently pinned material/state/coordinate
   rows and actual force-constant/run ancestry; keep unresolved associations out
   of canonical accepted science.
2. Build default-preview, authenticated pending-row import with immutable
   attempt/failure/cost receipts and transactionally proven full-state replay.
3. Expose exact revision/evidence review candidates through the private curator
   workflow; neither parser output nor LLM confidence constitutes approval.
4. Connect only independently reviewed sources and times to the existing ML
   companion. Fresh unpublished calculations must not borrow old structure
   publication dates to pass a historical pre-outcome feature gate.
5. Separately obtain authorization for implementation publication/PR delivery,
   then close engineering issues whose documented software acceptance is met.

The original 60-event independently reviewed pilot and research evaluation gates
are not waived by this format-validation batch.
